"""One .m4b for a book: its files joined in order with a chapter each (or their own chapters, or Audible's when they
say nothing and it is the same recording), tagged, with the cover inside; cover.jpg and metadata.json (in
Audiobookshelf's format) beside it; and whatever else lay in the book's folder (a pdf, an epub, pictures).

AAC files are joined as they are. Everything else is turned into AAC at about the bitrate it had, 128 kbit/s at
most (64 for mono): far more than speech needs. The new file must be as long as the old ones or nothing is kept."""

import collections
import html
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.request

from mutagen.mp4 import MP4, MP4Cover, MP4FreeForm
from PIL import Image

from .. import enrich, formats
from .sources import Found

JUNK = re.compile(r"(^|/)(__MACOSX|\.DS_Store|Thumbs\.db|desktop\.ini)|torrent.*demonoid|\.(torrent|nzb|cue|m3u|m3u8|nfo|"
                  r"sfv|rar|zip|par2|part)$|(^|/)AlbumArt(Small|_\{).*\.jpg$|(^|/)\._", re.I)
GENERIC = re.compile(r"^((track|chapter|part|disc|disk|cd|kapitel|del)?[\s\d._\-–:,()]*)+$", re.I)


class Failed(Exception):
    pass


def natural(s: str):
    return [int(t) if t.isdigit() else t.casefold() for t in re.split(r"(\d+)", s)]


def probe(path: str) -> dict:
    out = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams",
                          "-show_chapters", path], capture_output=True, text=True, timeout=600).stdout
    d = json.loads(out or "{}")
    a = next((s for s in d.get("streams", []) if s.get("codec_type") == "audio"), {})
    t = {k.lower(): v for k, v in (d.get("format", {}).get("tags") or {}).items()}
    return {"path": path, "duration": length(d, a),
            "codec": a.get("codec_name"), "profile": a.get("profile") or "", "rate": int(a.get("sample_rate") or 0),
            "ch": int(a.get("channels") or 0),
            "bitrate": int(d.get("format", {}).get("bit_rate") or 0), "title": t.get("title", ""), "track": t.get("track", ""),
            "chapters": [{"start": float(c["start_time"]), "end": float(c["end_time"]), "title": (c.get("tags") or {}).get("title", "")}
                         for c in d.get("chapters", [])]}


def length(d: dict, a: dict) -> float:
    """The length ffprobe gives, unless an .m4b's 32-bit length wrapped (a book over 27 h at 44.1 kHz: Disquiet Gods
    said 4.6 h of its 31.6): then its AAC frames, 1024 samples each, tell."""
    dur = float(d.get("format", {}).get("duration") or a.get("duration") or 0)
    rate, nb = int(a.get("sample_rate") or 0), int(a.get("nb_frames") or 0)
    if a.get("codec_name") == "aac" and rate and nb:
        real, wrap = nb * 1024 / rate, 2 ** 32 / rate
        if real - dur > 60 and abs((real - dur) / wrap - round((real - dur) / wrap)) < 0.01:
            return real
    return dur


def order(files: list[dict]) -> list[dict]:
    """Folders in natural order; in one, by track number when every file has its own, else by name."""
    by_dir = collections.defaultdict(list)
    for f in files:
        by_dir[os.path.dirname(f["path"])].append(f)
    out = []
    for d in sorted(by_dir, key=natural):
        fs = by_dir[d]
        nums = [re.match(r"^\s*(\d+)", f["track"] or "") for f in fs]
        if all(nums) and len({int(n.group(1)) for n in nums}) == len(fs):
            fs.sort(key=lambda f: int(re.match(r"^\s*(\d+)", f["track"]).group(1)))
        else:
            fs.sort(key=lambda f: natural(os.path.basename(f["path"])))
        out += fs
    return out


def chapter_name(f: dict, i: int, book: str) -> str:
    stem = os.path.splitext(os.path.basename(f["path"]))[0]
    for cand in ((f["title"] or "").strip(), stem):
        c = re.sub(re.escape(book), "", cand, flags=re.I) if book and len(book) > 3 else cand
        c = re.sub(r"^[\s\d._\-–:]+", "", c).strip(" -_.,;:")
        if re.match(r"^(chapter|part|kapitel|book)\s*\d+$", c, re.I):
            return c.title()
        if c and len(c) > 1 and not GENERIC.match(c) and c.lower() != book.lower():
            return c
    return f"Part {i}"


def chapters_of(files: list[dict], found: Found) -> list[dict]:
    chapters, at = [], 0.0
    for i, f in enumerate(files, 1):
        inner = [c for c in f["chapters"] if c["end"] > c["start"]]
        if len(inner) >= 2:
            chapters += [{"start": at + c["start"], "end": at + min(c["end"], f["duration"]),
                          "title": c["title"] or f"Chapter {len(chapters) + 1}"} for c in inner]
        else:
            chapters.append({"start": at, "end": at + f["duration"], "title": chapter_name(f, i, found.title)})
        at += f["duration"]
    if chapters:
        chapters[-1]["end"] = max(chapters[-1]["end"], at)
    own = [c for c in chapters if not re.match(r"^(Part|Chapter) \d+$", c["title"])]
    ac = found.chapters or {}
    if len(own) <= 1 and len(ac.get("chapters") or []) > 1 and ac.get("runtime") and abs(ac["runtime"] - at) <= 60:
        k = at / ac["runtime"]
        starts = [c["start"] * k for c in ac["chapters"]]
        chapters = [{"start": s, "end": starts[i + 1] if i + 1 < len(starts) else at, "title": c["title"]}
                    for i, (s, c) in enumerate(zip(starts, ac["chapters"], strict=True))]
    return chapters


def _metafile(chapters: list[dict], path: str):
    def esc(s):
        return re.sub(r"([=;#\\\n])", r"\\\1", s)
    with open(path, "w") as f:
        f.write(";FFMETADATA1\n")
        prev = 0
        for c in chapters:          # in order, none before the last one's end, none empty (ffmpeg refuses those)
            s, e = max(int(round(c['start'] * 1000)), prev), int(round(c['end'] * 1000))
            if e <= s:
                continue
            f.write(f"[CHAPTER]\nTIMEBASE=1/1000\nSTART={s}\nEND={e}\ntitle={esc(c['title'])}\n")
            prev = e


def cover_for(found: Found, home: str | None, first_file: str, tmp: str) -> tuple[bytes | None, str]:
    """A picture from the book's folder at least 500 px wide, else the sources', else a small one, else the file's."""
    best = None
    if home:
        for dp, dns, fns in os.walk(home):
            for fn in fns:
                path = os.path.join(dp, fn)
                if not fn.lower().endswith((".jpg", ".jpeg", ".png")) or JUNK.search(path) or re.search(
                        r"wallpaper|\d{3,4}x\d{3,4}|ipad|iphone|map|artwork \d|script", path, re.I):
                    continue
                try:
                    with Image.open(path) as im:
                        w, h = im.size
                except Exception:  # noqa: BLE001
                    continue
                score = (bool(re.search(r"cover|folder|front", fn, re.I)), w * h)
                if 0.6 < w / max(h, 1) < 1.7 and (best is None or score > best[0]):
                    best = (score, path, w)
    if best and best[2] >= 500:
        return open(best[1], "rb").read(), "folder"
    for url in found.images:
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": enrich.UA}), timeout=30) as r:
                return r.read(), "apple" if "mzstatic" in url else "audible"
        except Exception:  # noqa: BLE001
            continue
    if best:
        return open(best[1], "rb").read(), "folder"
    out = os.path.join(tmp, "embedded.jpg")
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", first_file, "-map", "0:v:0", "-frames:v", "1", out],
                   capture_output=True, timeout=120)
    if os.path.exists(out) and os.path.getsize(out) > 1000:
        return open(out, "rb").read(), "file"
    return None, ""


def as_jpeg(data: bytes) -> bytes:
    with Image.open(io.BytesIO(data)) as im:
        if im.format == "JPEG" and im.mode == "RGB":
            return data
        buf = io.BytesIO()
        im.convert("RGB").save(buf, "JPEG", quality=92)
        return buf.getvalue()


def plain(s: str) -> str:
    s = re.sub(r"<\s*(br|/p|/li)\s*/?>", "\n", s or "", flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    return re.sub(r"\n{3,}", "\n\n", html.unescape(s)).strip()


def safe(s: str) -> str:
    """A name a file or folder can have, on any system."""
    s = (s or "").replace("꞉", ":").replace("’", "'").replace("‘", "'")
    s = re.sub(r"\s*:\s*", " - ", s)
    s = re.sub(r"[\\/]", "-", s)
    s = re.sub(r'[*?"<>|]', "", s)
    return re.sub(r"\s+", " ", s).strip(" .")[:150]


def write_tags(path: str, f: Found, genre: str, language: str, cover: bytes | None, description: str):
    mp4 = MP4(path)
    if mp4.tags is None:
        mp4.add_tags()
    t = mp4.tags
    authors = ", ".join(f.authors)
    t["\xa9nam"], t["\xa9alb"], t["\xa9ART"], t["aART"], t["\xa9gen"] = [f.title], [f.title], [authors], [authors], [genre]
    if f.narrators:
        t["\xa9wrt"] = [", ".join(f.narrators)]
        t["----:com.apple.iTunes:NARRATOR"] = [MP4FreeForm(", ".join(f.narrators).encode())]
    if f.year:
        t["\xa9day"] = [f.year]
    if description:
        t["ldes"], t["desc"] = [description], [description[:250]]
    if f.series:
        t["\xa9grp"] = [f.series + (f" #{f.vol}" if f.vol else "")]
        t["\xa9mvn"] = [f.series]
        t["----:com.apple.iTunes:SERIES"] = [MP4FreeForm(f.series.encode())]
        if f.vol:
            t["----:com.apple.iTunes:SERIES-PART"] = [MP4FreeForm(f.vol.encode())]
            if f.vol.isdigit():
                t["\xa9mvi"] = [int(f.vol)]
    if language:
        t["----:com.apple.iTunes:LANGUAGE"] = [MP4FreeForm(language.encode())]
    if f.asin:
        t["----:com.apple.iTunes:ASIN"] = [MP4FreeForm(f.asin.encode())]
    if f.publisher:
        t["\xa9pub"] = [f.publisher]
    t["stik"] = [2]
    if cover:
        t["covr"] = [MP4Cover(cover, imageformat=MP4Cover.FORMAT_JPEG)]
    mp4.save()


def make(paths: list[str], f: Found, genre: str, language: str, folder: str, home: str | None = None,
         extra_homes: tuple = (), muzix: dict | None = None) -> dict:
    """The book in ``folder`` (made if missing). Raises Failed and leaves nothing behind when it can't."""
    os.makedirs(folder, exist_ok=True)
    name = safe(f.title) or "Audiobook"
    final = os.path.join(folder, name + ".m4b")
    part = os.path.join(folder, f".{name}.m4b.part")
    tmp = tempfile.mkdtemp(prefix="muzix-book-")
    try:
        files = order([probe(p) for p in paths])
        files = [x for x in files if x["duration"] > 0.5] or files
        total = sum(x["duration"] for x in files)
        if total <= 0:
            raise Failed("no sound in the files")
        chapters = chapters_of(files, f)
        _metafile(chapters, os.path.join(tmp, "meta.txt"))
        with open(os.path.join(tmp, "list.txt"), "w") as lf:
            for x in files:
                lf.write("file '" + x["path"].replace("'", "'\\''") + "'\n")
        same = len({(x["codec"], x["profile"], x["rate"], x["ch"]) for x in files}) == 1
        copy = same and files[0]["codec"] == "aac"
        ch = 1 if max(x["ch"] for x in files) == 1 else 2
        rate = collections.Counter(x["rate"] for x in files).most_common(1)[0][0] or 44100
        if same:            # one stream of packets, the files one after another
            cmd = ["nice", "-n", "15", "ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "concat", "-safe", "0",
                   "-i", os.path.join(tmp, "list.txt"), "-i", os.path.join(tmp, "meta.txt"),
                   "-map", "0:a:0", "-map_metadata", "1", "-map_chapters", "1"]   # meta.txt's: -1 drops the chapters' titles too
        else:               # files of different kinds (an AAC profile, a rate): each decoded by itself, then joined
            n = len(files)
            graph = "".join(f"[{i}:a:0]aresample={rate},aformat=channel_layouts={'mono' if ch == 1 else 'stereo'}[a{i}];"
                            for i in range(n)) + "".join(f"[a{i}]" for i in range(n)) + f"concat=n={n}:v=0:a=1[out]"
            cmd = ["nice", "-n", "15", "ffmpeg", "-nostdin", "-v", "error", "-y"]
            for x in files:
                cmd += ["-i", x["path"]]
            cmd += ["-i", os.path.join(tmp, "meta.txt"), "-filter_complex", graph, "-map", "[out]",
                    "-map_metadata", str(n), "-map_chapters", str(n)]
        src = sum(x["bitrate"] * x["duration"] for x in files) / total / 1000
        if copy:
            cmd += ["-c:a", "copy"]
            kbps = round(src)
        else:
            kbps = 64 if src <= 72 or ch == 1 else 96 if src <= 112 else 128
            cmd += ["-c:a", "aac", "-aac_coder", "twoloop" if kbps <= 64 else "fast", "-b:a", f"{kbps}k",
                    "-ac", str(ch), "-ar", str(rate), "-threads", "2"]
        cmd += ["-movflags", "+faststart", "-f", "mp4", part]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            raise Failed("ffmpeg: " + r.stderr[-600:])
        got = probe(part)["duration"]
        if abs(got - total) > max(3.0, 0.005 * total):
            raise Failed(f"the new file is {got:.0f} s long, the old ones {total:.0f} s")
        cover, cover_from = cover_for(f, home, files[0]["path"], tmp)
        cover = as_jpeg(cover) if cover else None
        description = plain(f.description)
        write_tags(part, f, genre, language, cover, description)
        os.replace(part, final)
        if cover:
            with open(os.path.join(folder, "cover.jpg"), "wb") as cf:
                cf.write(cover)
        meta = {"tags": [], "chapters": [{"id": i, "start": round(c["start"], 3), "end": round(c["end"], 3), "title": c["title"]}
                                         for i, c in enumerate(chapters)],
                "title": f.title, "subtitle": f.subtitle or None, "authors": f.authors, "narrators": f.narrators,
                "series": [f.series + (f" #{f.vol}" if f.vol else "")] if f.series else [], "genres": [genre],
                "publishedYear": f.year or None, "publishedDate": None, "publisher": f.publisher or None,
                "description": description or None, "isbn": None, "asin": f.asin or None, "language": language or None,
                "explicit": False, "abridged": bool(re.search(r"\babridged\b", f.title, re.I)), "muzix": muzix or {}}
        with open(os.path.join(folder, "metadata.json"), "w") as jf:
            json.dump(meta, jf, ensure_ascii=False, indent=2)
        extras = []
        for h in [home, *extra_homes]:
            if not h:
                continue
            for dp, dns, fns in os.walk(h):
                for fn in fns:
                    src_path = os.path.join(dp, fn)
                    rel = os.path.relpath(src_path, h)
                    if formats.is_audio(fn) or JUNK.search(rel):
                        continue
                    dst = os.path.join(folder, rel)
                    if not os.path.exists(dst):
                        os.makedirs(os.path.dirname(dst), exist_ok=True)
                        shutil.copy2(src_path, dst)
                        extras.append(src_path)
        return {"file": final, "seconds": round(total, 1), "chapters": len(chapters), "copied": copy, "kbps": kbps,
                "cover": cover_from, "extras": extras}
    except Failed:
        raise
    except Exception as e:  # noqa: BLE001
        raise Failed(f"{type(e).__name__}: {e}") from e
    finally:
        if os.path.exists(part):
            os.remove(part)
        shutil.rmtree(tmp, ignore_errors=True)
