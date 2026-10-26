"""The Mod Archive (modarchive.org), through its XML API, as folders for the online browser.

The Mod Archive asks programs to use its API instead of reading its web pages, and gives each
program a key of its own on request (on its forum); the key goes on the admin page and must
not be shared, so Muzix ships without one. Folders: letters/<A-Z>, genres/<id>, ratings/<10-1>,
artists, artists/<id>; a module is module/<id>/<file name>, downloaded through the API.
"""

import re
import string
import xml.etree.ElementTree as ET
from html import unescape
from urllib.parse import urlencode

API = "https://api.modarchive.org/xml-tools.php"
ROOT = [("letters", "By file name"), ("genres", "By genre"), ("ratings", "By rating"), ("artists", "Artists")]
LETTERS = list(string.ascii_uppercase)
RATINGS = list(range(10, 0, -1))

# what the listings said, for the breadcrumbs and for naming modules once they're opened
folder_names: dict[str, str] = dict(ROOT)
modules: dict[str, dict] = {}


class BadKey(Exception):
    """The API turned the key down (missing, wrong or withdrawn)."""


def request_url(key: str, names: list[str], page: int = 0) -> str | None:
    """The API call for a folder (`page` counts from 0), or None when there's no such folder."""
    q = None
    if names == ["genres"]:
        q = {"request": "view_genres"}
    elif names == ["artists"]:
        q = {"request": "search_artist", "page": page + 1}
    elif len(names) == 2 and names[0] == "letters" and names[1] in LETTERS:
        q = {"request": "view_by_list", "query": names[1], "page": page + 1}
    elif len(names) == 2 and names[0] == "genres" and names[1].isdigit():
        q = {"request": "search", "type": "genre", "query": names[1], "page": page + 1}
    elif len(names) == 2 and names[0] == "ratings" and names[1].isdigit() and int(names[1]) in RATINGS:
        q = {"request": "view_by_rating_comments", "query": names[1], "page": page + 1}
    elif len(names) == 2 and names[0] == "artists" and names[1].isdigit():
        q = {"request": "view_modules_by_artistid", "query": names[1], "page": page + 1}
    return f"{API}?{urlencode({'key': key, **q})}" if q else None


def static_folders(names: list[str]) -> list[dict] | None:
    """Folders that need no API call: the letters and the ratings."""
    if names == ["letters"]:
        return [{"name": c, "path": f"letters/{c}"} for c in LETTERS]
    if names == ["ratings"]:
        for r in RATINGS:
            folder_names[f"ratings/{r}"] = f"Rated {r} of 10"
        return [{"name": f"Rated {r} of 10", "path": f"ratings/{r}"} for r in RATINGS]
    return None


def download_url(names: list[str]) -> str | None:
    if len(names) == 3 and names[0] == "module" and names[1].isdigit():
        return f"https://api.modarchive.org/downloads.php?moduleid={names[1]}"
    return None


def _text(el, tag: str) -> str:
    found = el.find(tag)
    return unescape((found.text or "").strip()) if found is not None else ""


def _root(xml: str):
    root = ET.fromstring(xml)
    error = _text(root, "error")
    if error:
        if "key" in error.lower():
            raise BadKey(error)
        raise ValueError(error)
    return root


def file_name(module_id: str, name: str) -> str:
    return re.sub(r'[/\\?*:"<>|\x00-\x1f]', "_", name).strip(" .") or f"{module_id}.mod"


def parse(xml: str, names: list[str], page: int) -> tuple[list[dict], list[dict], bool]:
    """(folders, files, whether there's another page) from an API answer."""
    root = _root(xml)
    total_pages = int(_text(root, "totalpages") or 1)
    dirs, files = [], []
    for g in root.iter("child"):                        # view_genres: parent > children > child
        gid, name, count = _text(g, "id"), _text(g, "text"), int(_text(g, "files") or 0)
        if gid and name and count:
            folder_names[f"genres/{gid}"] = name
            dirs.append({"name": name, "path": f"genres/{gid}", "count": count})
    for a in root.iter("item"):                         # search_artist: items > item
        aid, alias = _text(a, "id"), _text(a, "alias")
        if aid and alias:
            folder_names[f"artists/{aid}"] = alias
            dirs.append({"name": alias, "path": f"artists/{aid}"})
    for m in root.iter("module"):
        mid, fname = _text(m, "id"), _text(m, "filename")
        if not mid.isdigit() or not fname:
            continue
        name = file_name(mid, fname)
        artist = _text(m, "artist_info/artist/alias") or _text(m, "artist_info/guessed_artist/alias")
        info = {"title": _text(m, "songtitle") or name.rsplit(".", 1)[0], "artist": artist,
                "genre": _text(m, "genretext")}
        modules[mid] = info
        files.append({"name": name, "path": f"module/{mid}/{name}", "size": int(_text(m, "bytes") or 0), **info})
    return dirs, files, page + 1 < total_pages


def label(names: list[str], row: dict):
    """The archive's song title and artist when the module's own are missing."""
    info = modules.get(names[1]) if len(names) == 3 and names[0] == "module" else None
    if not info:
        return
    if info["artist"] and not row.get("artist"):
        row["artist"] = row["albumartist"] = info["artist"]
    if info["title"] and (not row.get("title") or row["title"] == names[2].rsplit(".", 1)[0]):
        row["title"] = info["title"]
    if row.get("album") == names[1]:                  # named after the folder it was saved in
        row["album"] = ""
