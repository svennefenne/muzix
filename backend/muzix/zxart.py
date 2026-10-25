"""ZXArt (zxart.ee), the big ZX Spectrum music archive, as folders for the online browser.

ZXArt has no folder pages, but it answers the small XML API it made for ZXTune: authors,
parties, an author's or a party's tunes, the top list, and one file per tune. Those become
folders like the other archives': top, authors/<id>, parties/<id>; a tune is tune/<id>/<name>.
"""

import re
import xml.etree.ElementTree as ET

from . import formats

API = "https://zxart.ee/zxtune/language:eng/"
TOP = 500

ROOT = [("top", "Top tunes"), ("authors", "Authors"), ("parties", "Parties")]

# what the listings said, for naming tunes once they're opened and folders in the breadcrumbs
tunes: dict[str, dict] = {}
authors: dict[str, str] = {}          # id -> nickname
folder_names: dict[str, str] = dict(ROOT)    # folder path -> name


def api_url(names: list[str]) -> str | None:
    """The API call for a folder, or None when there's no such folder."""
    if names == ["top"]:
        return API + f"action:topTunes/limit:{TOP}"
    if names in (["authors"], ["parties"]):
        return API + f"action:{names[0]}"
    if len(names) == 2 and names[0] in ("authors", "parties") and names[1].isdigit():
        scope = "authorId" if names[0] == "authors" else "partyId"
        return API + f"action:tunes/{scope}:{names[1]}"
    return None


def file_url(names: list[str]) -> str | None:
    if len(names) == 3 and names[0] == "tune" and names[1].isdigit():
        return f"https://zxart.ee/file/id:{names[1]}"
    return None


def _text(el, tag: str) -> str:
    found = el.find(tag)
    return (found.text or "").strip() if found is not None else ""


def _seconds(t: str) -> float:
    try:
        secs = 0.0
        for p in t.split(":"):
            secs = secs * 60 + float(p)
        return secs
    except ValueError:
        return 0.0


def file_name(tune_id: str, original: str, title: str) -> str:
    """A safe file name that tells Muzix what plays it: ZXArt keeps the uploader's name, which
    for old disk files is often "song.$m" or "tune.c"."""
    name = re.sub(r'[/\\?*:"<>|\x00-\x1f]', "_", original or title or tune_id).strip(" .") or tune_id
    ext = name.rsplit(".", 1)[1].lower() if "." in name else ""
    if not formats.family(ext) and (not ext or ext.startswith("$") or len(ext) == 1):
        name += ".zx"
    return name


def parse(xml: str, author_names: dict[str, str]) -> tuple[list[dict], list[dict]]:
    """(folders, files) from an API answer."""
    root = ET.fromstring(xml)
    data = root.find("responseData")
    if data is None:
        return [], []
    dirs, files = [], []
    for a in data.iter("author"):
        aid, nick, real = _text(a, "id"), _text(a, "title"), _text(a, "realName")
        authors[aid] = folder_names[f"authors/{aid}"] = nick
        dirs.append({"name": f"{nick} ({real})" if real and real != nick else nick, "path": f"authors/{aid}"})
    for p in data.iter("party"):
        pid, title, year = _text(p, "id"), _text(p, "title"), _text(p, "year")
        folder_names[f"parties/{pid}"] = title if year in title else f"{title} {year}".strip()
        dirs.append({"name": folder_names[f"parties/{pid}"], "path": f"parties/{pid}"})
    for t in data.iter("tune"):
        tid = _text(t, "id")
        title = _text(t, "title")
        name = file_name(tid, _text(t, "originalFileName"), title)
        by = [author_names.get((i.text or "").strip(), "") for i in t.findall("authors/id")]
        info = {"title": title, "artist": ", ".join(a for a in by if a), "year": int(_text(t, "year") or 0),
                "duration": _seconds(_text(t, "time"))}
        tunes[tid] = info
        files.append({"name": name, "path": f"tune/{tid}/{name}", "title": title, "artist": info["artist"],
                      "year": info["year"], "duration": info["duration"]})
    return dirs, files


def label(names: list[str], row: dict):
    """ZXArt's own title, author and year for a tune: the file's are often decorated."""
    info = tunes.get(names[1]) if len(names) == 3 and names[0] == "tune" else None
    if not info:
        return
    row["title"] = info["title"] or row["title"]
    row["artist"] = row["albumartist"] = info["artist"] or row.get("artist") or ""
    row["year"] = info["year"] or row.get("year") or 0
    row["album"] = ""
