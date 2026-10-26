"""VGMRips (vgmrips.net), sound chip logs of game soundtracks, as folders for the online browser.

VGMRips has no folder pages either; its own pages list systems, composers, companies and
chips, and each of those lists its packs, twenty to a page. A pack is one zip of .vgz files,
which opens like the other archives' game sets. Folders: systems/<maker>/<system>,
composers/<id>, companies/<id>, chips/<id>; a pack is files/<its path on the site>.
"""

import re
from html import unescape
from urllib.parse import unquote

SITE = "https://vgmrips.net/"
ROOT = [("systems", "Systems"), ("composers", "Composers"), ("companies", "Companies"), ("chips", "Chips")]
GROUPS = {"systems": "system", "composers": "composer", "companies": "company", "chips": "chip"}
SLUG = re.compile(r"^[a-z0-9][a-z0-9._-]*$")

# what the listings said, for the breadcrumbs and for naming packs once they're opened
folder_names: dict[str, str] = dict(ROOT)
packs: dict[str, dict] = {}


def page_url(names: list[str], page: int = 0) -> str | None:
    """The site's page for a folder, or None when there's no such folder."""
    if len(names) == 1 and names[0] in GROUPS:
        return SITE + f"packs/{names[0]}/"
    if not names or names[0] not in GROUPS or not all(SLUG.match(n) for n in names[1:]):
        return None
    kind = GROUPS[names[0]]
    if kind == "system" and len(names) == 3:
        path = f"packs/system/{names[1]}/{names[2]}"
    elif kind != "system" and len(names) == 2:
        path = f"packs/{kind}/{names[1]}" + ("/developed" if kind == "company" else "")
    else:
        return None
    return SITE + path + (f"?p={page}" if page else "")


def _text(s: str) -> str:
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", s)).split())


def _count(s: str) -> int:
    m = re.search(r'<span class="badge">\s*(\d+)', s)
    return int(m.group(1)) if m else 0


def parse_groups(html: str, group: str) -> list[dict]:
    """The folders of a systems, composers, companies or chips page."""
    kind = GROUPS[group]
    out, seen = [], set()
    if group == "systems":
        blocks = re.findall(r'<div class="system">(.*?)<div class="cat">', html, re.S)
    elif group == "composers":
        blocks = re.findall(r'<li class="composer">(.*?)</li>', html, re.S)
    elif group == "companies":
        blocks = re.findall(r"<tr>(.*?)</tr>", html, re.S)
    else:
        blocks = re.findall(r'<div class="chip">(.*?)</div>', html, re.S)
    for b in blocks:
        m = re.search(rf'href="https?://vgmrips\.net/packs/{kind}/([^"/?#]+(?:/[^"/?#]+)?)"', b)
        if not m:
            continue
        slug = unquote(m.group(1))
        if group == "companies":
            dev = re.search(r'href="[^"]*/developed"[^>]*>\s*(\d+)', b)    # packs of games it developed
            count = int(dev.group(1)) if dev else 0
            name = re.search(r'title="([^"]*)"', b)
            name = unescape(name.group(1)) if name else slug
        elif group == "systems":
            count = _count(b)
            name = re.search(r'<div class="name"><a[^>]*>(.*?)</a>', b, re.S)
            name = _text(name.group(1)) if name else slug
        else:
            count = _count(b)
            name = _text(re.sub(r'<span class="pull-right".*?</span>\s*</span>|<span class="badge">.*?</span>', "", b, flags=re.S))
        path = f"{group}/{slug}"
        if not name or not count or path in seen or not all(SLUG.match(p) for p in slug.split("/")):
            continue
        seen.add(path)
        folder_names[path] = name
        out.append({"name": name, "path": path, "count": count})
    return out


def parse_packs(html: str) -> tuple[list[dict], int, bool]:
    """(packs, how many there are in all, whether there's another page) from a packs page."""
    files = []
    for b in re.split(r'<div class="result row"', html)[1:]:
        dl = re.search(r'<a class="download" href="https?://vgmrips\.net/(files/[^"]+\.zip)"[^>]*>(.*?)</a>', b, re.S)
        title = re.search(r'<img[^>]*alt="([^"]*)"', b)
        if not dl or not title:
            continue
        path = unquote(dl.group(1))
        if any(p in ("", ".", "..") or "\\" in p for p in path.split("/")):
            continue
        detail = _text(dl.group(2))                         # "48 songs • 2.17 MB"
        songs = re.match(r"(\d+)\s+songs?", detail)
        size = re.search(r"([\d.]+)\s*(KB|MB|GB)", detail)
        composers = [_text(c) for c in re.findall(r'href="https?://vgmrips\.net/packs/composer/[^"]+"[^>]*>(.*?)</a>', b, re.S)]
        info = {"title": unescape(title.group(1)), "artist": ", ".join(dict.fromkeys(c for c in composers if c)),
                "songs": int(songs.group(1)) if songs else 0}
        packs[path] = info
        files.append({"name": path.rsplit("/", 1)[-1], "path": path, **info,
                      "size": int(float(size.group(1)) * {"KB": 1024, "MB": 1024 ** 2, "GB": 1024 ** 3}[size.group(2)])
                      if size else 0})
    m = re.search(r"Packs\s+\d+\s+to\s+(\d+)\s+of\s+(\d+)\s+total", html)
    shown, total = (int(m.group(1)), int(m.group(2))) if m else (len(files), len(files))
    return files, total, shown < total


def label(path: str, row: dict):
    """The pack's own title for the album; the composers when the file doesn't say."""
    info = packs.get(path)
    if not info:
        return
    row["album"] = info["title"]
    if not row.get("artist") and info["artist"]:
        row["artist"] = row["albumartist"] = info["artist"]
