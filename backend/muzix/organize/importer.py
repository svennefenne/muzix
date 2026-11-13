"""Uploads: tag, find art and file new music into the library with beets + musicorg.

Each upload batch is a folder in /config/uploads/<batch>. Music goes through
beets (MusicBrainz match, genre decision, cover art, Genre/Artist/Album naming,
tags written, covers embedded) and is moved into the music upload folder.
Chip/tracker files are copied into the VGM upload folder as they are. The watch
folder (watch.py) files its albums the same way, from where they are (file_music).
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import yaml
from sqlalchemy import select

from .. import db, env, formats, jobs, lyrics, settings
from ..models import Artist, Root

PLUGIN_DIR = Path(__file__).parent / "beetsplug"
BEET = shutil.which("beet") or "beet"


def beets_config(music_root: str, batch: str, autotag: bool | None = None, bandcamp_tags: str = "",
                 bandcamp_only: bool = False) -> str:
    """beets' settings for one import; `autotag` False: the files' tags as they are (matched already);
    `bandcamp_tags`: a file of Bandcamp's tags for the albums, by their folders (musicorg's genres go by them);
    `bandcamp_only`: those tags alone (the watch folder for Bandcamp alone)."""
    cfg = {
        "directory": music_root,
        "library": str(env.BEETS_DIR / "library.db"),
        "statefile": str(env.BEETS_DIR / "state.pickle"),
        "plugins": ["musicbrainz", "fetchart", "embedart", "musicorg"],
        "pluginpath": [str(PLUGIN_DIR)],
        "clutter": [],
        "ignore": [".*", "*~", "System Volume Information"],
        "import": {
            "write": False, "copy": False, "move": False, "quiet": True, "quiet_fallback": "asis",
            "timid": False, "incremental": False, "resume": False, "duplicate_action": "keep",
            # beets bug: WAV-wrapped files already named .mp3 are overwritten and deleted
            "remux_mp3_in_wav": False,
            "log": str(env.BEETS_DIR / "import.log"),
            "autotag": bool(settings.get("upload_musicbrainz")) if autotag is None else autotag,
        },
        "original_date": True, "per_disc_numbering": False, "id3v23": True, "max_filename_length": 200,
        "match": {"strong_rec_thresh": 0.10},
        "musicbrainz": {"genres": True, "search_limit": 5},
        "fetchart": {"auto": False, "sources": ["coverart", "filesystem", "itunes", "amazon", "albumart"],
                     "cautious": False, "cover_names": ["cover", "front", "folder", "albumart", "album", "art"],
                     "minwidth": 200, "maxwidth": 1200, "quality": 90},
        "embedart": {"auto": False, "maxwidth": 600, "quality": 88, "ifempty": False, "remove_art_file": False},
        "musicorg": {"lastfm_cache": str(env.BEETS_DIR / "lastfm-cache.json"),
                     "overrides": str(env.DATA_DIR / "genre-overrides.yaml"),
                     "artist_genres": str(env.BEETS_DIR / "artist-genres.json"),
                     "bandcamp_tags": bandcamp_tags, "bandcamp_only": bandcamp_only,
                     # the owner's rule: soundtracks go to Soundtrack, whatever else the artist plays
                     "soundtrack_titles": "always"},
        "ui": {"color": False},
    }
    if settings.get("upload_genre_folders"):
        pattern = "$mo_root/$mo_artistdir/$mo_albumdir/$mo_track"
    else:
        pattern = "$albumartist/$album%aunique{}/$track $title"
    cfg["paths"] = {"default": pattern, "comp": pattern, "singleton": pattern}
    path = env.BEETS_DIR / f"config-{batch}.yaml"
    path.write_text(yaml.safe_dump(cfg, allow_unicode=True))
    return str(path)


def write_artist_genres():
    with db.session() as s:
        rows = s.execute(select(Artist.name, Artist.genre).where(Artist.genre != "")).all()
    (env.BEETS_DIR / "artist-genres.json").write_text(json.dumps(dict(rows), ensure_ascii=False))


class Beet:
    def __init__(self, ctx, config: str):
        self.ctx, self.config = ctx, config

    def __call__(self, *args, check=True, quiet=False):
        cmd = [BEET, "-c", self.config, *args]
        self.ctx.log("$ beet " + " ".join(args)[:300])
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(env.BEETS_DIR),
                           env={**os.environ, "BEETSDIR": str(env.BEETS_DIR)}, timeout=6 * 3600)
        out = (r.stdout + r.stderr).strip()
        for line in [] if quiet else out.splitlines()[-40:]:
            self.ctx.log("  " + line[:300])
        if check and r.returncode != 0:
            raise RuntimeError(f"beet {args[0]} failed ({r.returncode})")
        return out

    def albums(self, query: str) -> list[dict]:
        """The albums of the songs a query finds, as filed: {artist, album, year, folder, songs, mbid, came} (the
        genre is the folder's first part; mbid: the MusicBrainz release it was matched with, or ""; came: the
        folder it came in)."""
        out: dict[str, dict] = {}
        for line in self("ls", "-f", "$albumartist\t$album\t$year\t$mb_albumid\t$mo_orig_path\t$path", query,
                         quiet=True).splitlines():
            r = line.split("\t", 5)
            if len(r) != 6:
                continue
            mbid, came = r.pop(3), os.path.dirname(r.pop(3))
            folder = os.path.dirname(r[3])
            if os.path.basename(folder).lower().startswith(("cd", "disc", "disk")) and len(os.path.basename(folder)) < 8:
                folder = os.path.dirname(folder)        # one album over its discs
            a = out.setdefault(folder, {"artist": r[0], "album": r[1], "year": int(r[2]) if r[2].isdigit() else 0,
                                        "folder": folder, "songs": 0, "mbid": mbid, "came": came})
            a["songs"] += 1
        return list(out.values())

    def songs(self, query: str) -> dict[str, tuple[str, str]]:
        """id -> (path, title) of the songs a query finds."""
        rows = (line.split("\t", 2) for line in self("ls", "-f", "$id\t$path\t$title", query, quiet=True).splitlines())
        return {r[0]: (r[1], r[2]) for r in rows if len(r) == 3}


def upload_root(kind: str) -> str | None:
    with db.session() as s:
        r = s.scalar(select(Root).where(Root.kind == kind, Root.upload_target.is_(True), Root.enabled.is_(True)))
        if r is None:
            r = s.scalar(select(Root).where(Root.kind == kind, Root.enabled.is_(True)).order_by(Root.id))
        return r.path if r else None


@jobs.job("import_upload")
def import_upload(ctx: jobs.JobContext, batch: str):
    batch_dir = (env.UPLOAD_DIR / batch).resolve()
    if env.UPLOAD_DIR.resolve() not in batch_dir.parents or not batch_dir.is_dir():
        raise RuntimeError("no such upload batch")
    music, chips = [], []
    for root, _, files in os.walk(batch_dir):
        for f in files:
            fam = formats.family(f)
            if fam in ("native", "decode"):
                music.append(os.path.join(root, f))
            elif fam is not None:
                chips.append(os.path.join(root, f))
    ctx.log(f"{len(music)} music files, {len(chips)} chiptune/tracker files")
    result = {"music": len(music), "vgm": len(chips)}

    if chips:
        dest_root = upload_root("vgm") or upload_root("music")
        if not dest_root:
            raise RuntimeError("add a VGM or music folder on the admin page first")
        for path in chips:
            rel = os.path.relpath(path, batch_dir)
            dest = os.path.join(dest_root, "Uploads", rel)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            if not os.path.exists(dest):
                shutil.copy2(path, dest)
                os.chmod(dest, 0o644)
            os.remove(path)
        ctx.log(f"copied {len(chips)} files to {dest_root}/Uploads")
        result["vgm_folder"] = os.path.join(dest_root, "Uploads")

    if music:
        result.update(file_music(ctx, batch_dir, batch))

    left = [os.path.relpath(os.path.join(r, f), batch_dir) for r, _, fs in os.walk(batch_dir) for f in fs]
    if not left:
        shutil.rmtree(batch_dir, ignore_errors=True)
    else:
        ctx.log(f"{len(left)} files were not imported and stay in the upload area")
    result["left"] = left[:200]
    jobs.submit("scan", "Scan new uploads")
    return result


def file_music(ctx: jobs.JobContext, source, batch: str, autotag: bool | None = None, search_id: str = "",
               duplicate: bool = False, bandcamp_tags: dict[str, list[str]] | None = None,
               bandcamp_only: bool = False) -> dict:
    """The music in `source` matched with MusicBrainz (with `search_id`, as that release; with `autotag` False,
    as its tags have it), given a main genre and cover art, and moved into the music upload folder. `duplicate`:
    the library has it already, filed anyway: to Duplicates/<artist>/<album> (2), (3), ... as the library's own.
    `bandcamp_tags`: Bandcamp's tags of its albums, by the folders they're in (its genre first): the main genre
    goes by them too (with `bandcamp_only`, by them alone), and each album filed says its own ("tags")."""
    out: dict = {}
    music_root = upload_root("music")
    if not music_root or not os.access(music_root, os.W_OK):
        raise RuntimeError("the music upload folder is missing or read-only; check the admin page")
    write_artist_genres()
    bc_file = ""
    if bandcamp_tags:
        bc_file = str(env.BEETS_DIR / f"bandcamp-{batch}.json")
        Path(bc_file).write_text(json.dumps(bandcamp_tags, ensure_ascii=False))
    beet = Beet(ctx, beets_config(music_root, batch, autotag, bc_file, bandcamp_only))
    tag = f"mo_batch:{batch}"
    plan = ("mplan", "--duplicates", tag) if duplicate else ("mplan", tag)
    ctx.update(0.05, "matching with MusicBrainz")
    beet("import", *(["-S", search_id] if search_id else []), "--", str(source))
    beet("modify", "-y", "-a", f"mo_batch={batch}", f"path:{source}")
    ctx.update(0.35, "deciding genres")
    beet(*plan)
    beet("mgenre", tag)
    if settings.get("upload_fetch_art"):
        ctx.update(0.5, "finding cover art")
        beet("fetchart", "-q", tag, check=False)
    beet(*plan)
    ctx.update(0.65, "writing tags and moving files")
    before = beet.songs(tag)
    beet("write", tag)
    beet("move", tag)
    after = beet.songs(tag)
    moved = {path: after[i][0] for i, (path, _) in before.items() if i in after}
    if n := lyrics.carry(moved, {path: title for path, title in before.values()}):
        ctx.log(f"{n} lyrics files went along with their songs")
    beet("embedart", "-y", tag, "artpath::.", check=False)
    beet("extractart", "-a", "-n", "cover", tag, "^artpath::.", check=False)
    for r, _, fs in os.walk(music_root):
        for f in fs:
            if f.startswith("cover") and os.stat(os.path.join(r, f)).st_mode & 0o777 == 0o600:
                os.chmod(os.path.join(r, f), 0o644)
    out["report"] = beet("mreport", tag, check=False)[-2000:]
    out["albums"] = beet.albums(tag)
    for a in out["albums"]:
        came = a.pop("came", "")
        if found := (bandcamp_tags or {}).get(came) or (bandcamp_tags or {}).get(os.path.dirname(came)):
            a["tags"] = found
    out["music_root"] = music_root
    if bc_file:
        Path(bc_file).unlink(missing_ok=True)
    return out
