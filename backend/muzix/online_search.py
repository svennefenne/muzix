"""Searching and shuffling the online archives, all of them or one.

Each archive is searched the way it allows: HVSC, Modland and ASMA through the index of their
published lists (online_index), ZXArt, VGMRips and The Mod Archive through their own search,
the Joshw rips by reading the one letter folder a title starts with. scene.org has no list and
no search, so it only shuffles. Words that name a system ("c64", "nes", "amiga") pick the
archives; a year keeps what's known to be from that year.

Shuffling takes random tunes from an index where there is one, and otherwise from a few random
folders; a game set (a Joshw or VGMRips archive) comes as one random song of the set.
"""

import logging
import random
import re
from concurrent.futures import ThreadPoolExecutor, wait
from urllib.parse import quote

from . import modarchive, online, online_index, settings, vgmrips, zxart

log = logging.getLogger("muzix.online.search")
INDEXED = ("hvsc", "modland", "asma")
JOSHW = ("nsf", "gbs", "spc", "hes", "kss")
PER_SOURCE = 40
TIMEOUT = 25

# names of an archive's systems; a query that uses one only searches those archives. Words that are
# also common in titles ("mega", "super", "game") only count as part of a full name.
SYSTEMS = {
    "hvsc": ["commodore 64", "commodore", "c64", "sid"],
    "modland": ["amiga", "tracker", "trackers", "module", "modules"],
    "asma": ["atari 8-bit", "atari", "pokey", "sap"],
    "nsf": ["nes", "famicom", "nintendo"],
    "gbs": ["game boy color", "game boy", "gameboy", "gbc", "gb", "nintendo"],
    "spc": ["super nintendo", "super famicom", "snes", "sfc", "nintendo"],
    "hes": ["pc engine", "pc-engine", "pce", "turbografx-16", "turbografx", "tg16"],
    "kss": ["master system", "game gear", "msx", "sms", "sega"],
    "zxart": ["zx spectrum", "zx", "spectrum", "speccy"],
    "vgmrips": ["mega drive", "neo geo", "fm towns", "arcade", "vgm", "pc-98", "pc98", "x68000", "genesis", "sega", "msx"],
    "modarchive": ["amiga", "tracker", "trackers", "module", "modules"],
    "sceneorg": ["demoscene", "demo scene"],
}
PHRASES = sorted({p for names in SYSTEMS.values() for p in names}, key=len, reverse=True)
YEAR = re.compile(r"^(19[5-9]\d|20[0-4]\d)$")


def parse_query(q: str) -> tuple[list[str], set[str], str]:
    """(title words, the archives its system names pick (none: all), year)."""
    rest = " " + " ".join(w for w in re.split(r"[\s,;:/\\|()\[\]\"'+*?!]+", (q or "").lower()) if w) + " "
    picked = set()
    for phrase in PHRASES:
        if f" {phrase} " in rest:
            picked |= {a for a, names in SYSTEMS.items() if phrase in names}
            rest = rest.replace(f" {phrase} ", " ")
    words = rest.split()
    year = next((w for w in words if YEAR.match(w)), "")
    return [w for w in words if w != year], picked, year


def _archives(only: str | None, picked: set[str]) -> list[online.Source]:
    return [s for s in online.SOURCES if (not only or s.id == only) and (not picked or s.id in picked)]


def _fits(entry: dict, text: list[str], year: str) -> bool:
    """A result from an archive's own search, checked against every word and the year."""
    hay = " ".join(str(entry.get(k) or "") for k in ("title", "artist", "name", "path")).lower()
    hay = re.sub(r"[_\W]+", " ", hay)
    words = hay.split()
    if year and str(entry.get("year") or "") != year and year not in words:
        return False
    return all(any(h.startswith(w) for h in words) for w in re.sub(r"[_\W]+", " ", " ".join(text)).split())


# ---------------------------------------------------------------- searching

def search(q: str, only: str | None = None) -> dict:
    """Results grouped by archive, best first, with the archives that couldn't be searched."""
    text, picked, year = parse_query(q)
    groups, skipped = [], []
    if not text and not year:
        return {"query": q, "groups": [], "skipped": [], "building": []}
    jobs = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        for src in _archives(only, picked):
            jobs[pool.submit(_search_one, src, text, year)] = src
        done, late = wait(jobs, timeout=TIMEOUT)
        for fut in done:
            src = jobs[fut]
            try:
                dirs, files, total, note = fut.result()
            except online.OnlineError as e:
                skipped.append({"source": src.id, "name": src.name, "label": src.label, "reason": str(e)})
                continue
            except Exception as e:
                log.info("searching %s failed: %r", src.id, e)
                skipped.append({"source": src.id, "name": src.name, "label": src.label, "reason": f"{src.name} isn't answering right now"})
                continue
            if note:
                skipped.append({"source": src.id, "name": src.name, "label": src.label, "reason": note})
            if dirs or files:
                listing = online._folder(src, [], dirs, files, [], keep_order=True)
                groups.append({**listing, "label": src.label, "archive": src.name, "total": max(total, len(files))})
        for fut in late:
            src = jobs[fut]
            skipped.append({"source": src.id, "name": src.name, "label": src.label, "reason": f"{src.name} took too long to answer"})
    order = {s.id: i for i, s in enumerate(online.SOURCES)}
    groups.sort(key=lambda g: order[g["source"]])
    return {"query": q, "groups": groups, "skipped": sorted(skipped, key=lambda s: order[s["source"]]),
            "building": [s for s in online_index.building() if s in {g.id for g in _archives(only, picked)}]}


def _search_one(src: online.Source, text: list[str], year: str) -> tuple[list, list, int, str]:
    """(folders, files, how many in all, a note when the search was partial)."""
    if src.id in INDEXED:
        if year and src.id != "asma":
            return [], [], 0, ""                         # HVSC and Modland don't record years
        if not online_index.ready(src.id):
            return [], [], 0, f"Fetching {src.name}'s list of everything in it; search again in a minute"
        words = [*text, year] if year else text
        files, total = online_index.search(src.id, words, PER_SOURCE)
        dirs = online_index.folders(src.id, text) if text else []
        if src.id == "modland":                          # the same composer under several trackers
            for d in dirs:
                d["name"] = f"{d['name']} ({d['path'].split('/')[0]})"
        return dirs, files, total, ""
    if not text:
        return [], [], 0, ""                             # these search by title, not by year alone
    if src.id == "zxart":
        return _zxart(src, text, year)
    if src.id == "vgmrips":
        return _vgmrips(src, text, year)
    if src.id == "modarchive":
        return _modarchive(src, text, year)
    if src.id in JOSHW:
        return _joshw(src, text, year)
    return [], [], 0, ""


def _zxart(src, text, year):
    url = zxart.API + "action:search/query:" + quote(" ".join(text))
    online._zxart_listing(src, ["authors"])              # tunes name their authors by id
    dirs_, files = online._cached(url, lambda: zxart.parse(online._page(src, url), zxart.authors))
    files = [f for f in files if _fits(f, text, year)]
    authors = [] if year else [d for d in online._zxart_listing(src, ["authors"])["dirs"] if _fits(d, text, "")]
    return authors[:12], files[:PER_SOURCE], len(files), ""


def _vgmrips(src, text, year):
    if year:
        return [], [], 0, ""                             # packs aren't listed with years
    url = vgmrips.SITE + "packs/search?q=" + quote(" ".join(text))
    files, total, _ = online._cached(url, lambda: vgmrips.parse_packs(online._page(src, url)))
    files = [f for f in files if _fits(f, text, year)]
    dirs = []
    for group in ("systems", "composers"):
        dirs += [d for d in online._vgmrips_listing(src, [group], 0)["dirs"] if _fits(d, text, "")]
    return dirs[:12], files[:PER_SOURCE], max(total, len(files)), ""


def _modarchive(src, text, year):
    key = settings.get("modarchive_api_key")
    if not key:
        return [], [], 0, "Needs an API key (admin page)"
    if year:
        return [], [], 0, ""
    url = modarchive.API + "?" + "&".join(f"{k}={quote(str(v))}" for k, v in {
        "key": key, "request": "search", "type": "filename_or_songtitle", "query": "*" + " ".join(text) + "*"}.items())
    try:
        _, files, _ = online._cached(url, lambda: modarchive.parse(online._page(src, url), ["search"], 0))
    except modarchive.BadKey:
        raise online.OnlineError("The Mod Archive didn't accept the API key")
    files = [f for f in files if _fits(f, text, year)]
    return [], files[:PER_SOURCE], len(files), ""


def _joshw(src, text, year):
    """Joshw keeps its sets in a folder per first letter: only that folder is read."""
    first = text[0][0]
    letter = "0-9" if first.isdigit() else first if first.isalpha() else ""
    if not letter:
        return [], [], 0, ""
    tops = list(src.top) if src.top else [""]
    files = []
    for top in tops:
        path = f"{top}/{letter}" if top else letter
        try:
            d = online.listing(src, path)
        except online.OnlineError:
            continue
        files += [f for f in d["files"] if _fits(f, text, year)]
    return [], files[:PER_SOURCE], len(files), ""


# ---------------------------------------------------------------- shuffling

def shuffle(only: str | None = None, path: str = "", n: int = 60) -> list[dict]:
    """Random tunes (and game sets, to play one random song of) from one archive, or all of them."""
    sources = [s for s in online.SOURCES if (s.id == only if only else _shufflable(s))]
    per = n if only else max(4, -(-n // max(1, len(sources))))
    items = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        jobs = {pool.submit(_shuffle_one, s, path if only else "", per): s for s in sources}
        done, _ = wait(jobs, timeout=TIMEOUT)
        for fut in done:
            src = jobs[fut]
            try:
                picked = fut.result()
            except online.OnlineError:
                if only:
                    raise
                continue
            except Exception as e:
                log.info("shuffling %s failed: %r", src.id, e)
                continue
            items += [{**f, "source": src.id, "system": src.system} for f in picked]
    random.shuffle(items)
    return items[:n]


def _shufflable(src: online.Source) -> bool:
    return src.id != "modarchive" or bool(settings.get("modarchive_api_key"))


def _playable(src, files: list[dict]) -> list[dict]:
    return online._folder(src, [], [], files, [], keep_order=True)["files"]


def _shuffle_one(src: online.Source, path: str, n: int) -> list[dict]:
    if src.id in INDEXED and online_index.ready(src.id, wait=True):
        return _playable(src, online_index.sample(src.id, path, n))
    if src.id == "zxart" and not path:
        return random.sample(_tunes(src, "top"), min(n, len(_tunes(src, "top"))))
    return _from_folders(src, path, n)


def _tunes(src, path: str) -> list[dict]:
    return online.listing(src, path)["files"]


def _from_folders(src: online.Source, path: str, n: int, budget: int = 6) -> list[dict]:
    """Random files from a folder, or from a few of its random sub-folders, a level or two down.
    A folder that won't open is passed over."""
    def listing(p: str) -> dict | None:
        try:
            return online.listing(src, p, _random_page(src, p))
        except online.OnlineError as e:
            log.info("shuffle: %s/%s: %s", src.id, p, e)
            return None

    d = online.listing(src, path, _random_page(src, path))
    picks = list(d["files"])
    dirs = list(d["dirs"])
    random.shuffle(dirs)
    for sub in dirs:
        if len(picks) >= n * 2 or budget <= 0:
            break
        budget -= 1
        inner = listing(sub["path"])
        if not inner:
            continue
        picks += inner["files"]
        if not inner["files"] and inner["dirs"] and budget > 0:
            budget -= 1
            deeper = listing(random.choice(inner["dirs"])["path"])
            picks += deeper["files"] if deeper else []
    random.shuffle(picks)
    return picks[:n]


def _random_page(src: online.Source, path: str) -> int:
    """For paged folders (VGMRips), a random page of the folder's first listing."""
    if src.id != "vgmrips" or path.count("/") < 1:
        return 0
    first = online.listing(src, path)
    total = first.get("total") or 0
    pages = max(1, -(-total // 20))
    return random.randrange(pages)
