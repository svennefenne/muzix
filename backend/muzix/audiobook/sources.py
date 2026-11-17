"""Where an audiobook's details come from, all without keys:

- Audible's catalog API: title, authors, narrators, series and number, categories, language, runtime, summary, cover.
- Audnexus: Audible's chapter list for a title, with times.
- Apple Books (the iTunes Search API, about 20 searches a minute): a large cover, a summary, the release.
- The Warhammer 40k Wiki (Fandom's MediaWiki API) for Black Library's books and audio dramas: first release,
  author, performers, series. Black Library's own site and Lexicanum sit behind a human check, so not those.
- Open Library: the year a book was first published.

``identify`` asks them in that order and puts the answers together (``Found``)."""

import difflib
import logging
import re
import threading
import time
import unicodedata
from dataclasses import dataclass, field

import httpx

from .. import enrich

log = logging.getLogger("muzix.audiobook")
TIMEOUT = 20
_gap = {"audible": 0.3, "audnexus": 0.3, "apple": 3.2, "wiki": 0.4, "openlibrary": 0.5}
_last: dict[str, float] = {}
_lock = threading.Lock()
WARHAMMER = re.compile(r"warhammer|horus heresy|black library|siege of terra|space marine|gotrek|eisenhorn|ravenor|"
                       r"gaunt'?s ghosts|ciaphas cain|age of sigmar|necromunda|primarchs|40,?000|\b40k\b", re.I)


def _client() -> httpx.Client:
    return httpx.Client(headers={"User-Agent": enrich.UA}, timeout=TIMEOUT, follow_redirects=True)


def _get(source: str, url: str, params: dict | None = None) -> dict | None:
    """A JSON answer, or None. Each source is asked no faster than it allows."""
    for attempt in range(3):
        with _lock:
            wait = _last.get(source, 0) + _gap[source] - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            _last[source] = time.monotonic()
        try:
            with _client() as c:
                r = c.get(url, params=params)
            if r.status_code in (429, 503):
                time.sleep(5 * (attempt + 1))
                continue
            if r.status_code >= 400:
                return None
            return r.json()
        except (httpx.HTTPError, ValueError) as e:
            log.info("%s: %s", source, e)
            time.sleep(2 * (attempt + 1))
    return None


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\b(the|a|an)\b", " ", s.replace("&", "and"))
    return re.sub(r"[\W_]+", "", s)


def sim(a: str, b: str) -> float:
    """How alike two titles or names are, 0..1; one inside the other counts as the same."""
    a, b = norm(a), norm(b)
    if not a or not b:
        return 0.0
    if (a in b or b in a) and min(len(a), len(b)) > 3:
        return 1.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def bare_title(t: str) -> str:
    """A shop's title without what shops add: (Unabridged), ": The Horus Heresy, Book 3", "Star Wars: "."""
    t = re.sub(r"\s*[\[(](unabridged|abridged|dramati[sz]ed adaptation)[\])]", "", t or "", flags=re.I)
    t = re.sub(r"\s*\((audio drama|novel|novella|short story|anthology|audiobook|audio book)\)\s*$", "", t, flags=re.I)
    t = re.sub(r"[:,]\s*(the )?horus heresy.*$|[:,]\s*(a )?warhammer( 40,000)?.*$|[:,]\s*star wars legends$", "", t, flags=re.I)
    t = re.sub(r"^star wars:\s*", "", t, flags=re.I)
    return re.sub(r"\s+", " ", t).strip(" -:,")


# ---------------------------------------------------------------- Audible

GROUPS = "contributors,product_attrs,product_desc,product_extended_attrs,media,series,category_ladders"


def audible_search(title: str, author: str = "", keywords: str = "") -> list[dict]:
    params = {"num_results": 10, "products_sort_by": "Relevance", "response_groups": GROUPS, "image_sizes": "1215,500"}
    if keywords:
        params["keywords"] = keywords
    else:
        params["title"] = title
        if author:
            params["author"] = author
    d = _get("audible", "https://api.audible.com/1.0/catalog/products", params) or {}
    return [_audible_slim(p) for p in d.get("products", []) if p.get("asin")]


def audible_get(asin: str) -> dict | None:
    d = _get("audible", f"https://api.audible.com/1.0/catalog/products/{asin}",
             {"response_groups": GROUPS, "image_sizes": "1215,500"}) or {}
    return _audible_slim(d["product"]) if d.get("product", {}).get("asin") else None


def _audible_slim(p: dict) -> dict:
    imgs = p.get("product_images") or {}
    return {
        "asin": p["asin"], "title": p.get("title") or "", "subtitle": p.get("subtitle") or "",
        "authors": [a["name"] for a in p.get("authors") or [] if "translator" not in a["name"].lower()],
        "narrators": [n["name"] for n in p.get("narrators") or []],
        "runtime": (p.get("runtime_length_min") or 0) * 60, "release": p.get("release_date") or "",
        "format": p.get("format_type") or "", "publisher": p.get("publisher_name") or "",
        "series": [(s.get("title") or "", s.get("sequence") or "") for s in p.get("series") or []],
        "categories": [[c["name"] for c in lad.get("ladder", [])] for lad in p.get("category_ladders") or []],
        "image": imgs.get("1215") or imgs.get("500") or "", "language": (p.get("language") or "").lower(),
        "summary": p.get("publisher_summary") or p.get("merchandising_summary") or "",
    }


def audible_chapters(asin: str) -> dict | None:
    """{"runtime": s, "chapters": [{"start": s, "title"}]} for the Audible recording, from Audnexus."""
    d = _get("audnexus", f"https://api.audnex.us/books/{asin}/chapters")
    if not d or not d.get("chapters"):
        return None
    return {"runtime": d.get("runtimeLengthSec") or 0,
            "chapters": [{"start": c["startOffsetMs"] / 1000, "title": c["title"]} for c in d["chapters"]]}


# ---------------------------------------------------------------- Apple Books

def apple_search(title: str, author: str = "") -> dict | None:
    d = _get("apple", "https://itunes.apple.com/search", {"term": f"{title} {author}".strip(), "media": "audiobook",
                                                          "entity": "audiobook", "limit": 10, "country": "us"}) or {}
    best = None
    for r in d.get("results", []):
        ts = sim(bare_title(r.get("collectionName", "")), title)
        au = max((sim(a, author) for a in re.split(r",|&", r.get("artistName", ""))), default=0) if author else 0
        score = ts * 0.7 + (au > 0.8) * 0.3
        if ts >= 0.8 and (best is None or score > best[0]):
            best = (score, r)
    if not best:
        return None
    r = best[1]
    art = r.get("artworkUrl100") or ""
    return {"title": r.get("collectionName") or "", "author": r.get("artistName") or "",
            "release": (r.get("releaseDate") or "")[:10], "description": r.get("description") or "",
            "image": re.sub(r"/\d+x\d+bb\.(jpg|png)$", "/1400x1400bb.jpg", art) if art else "",
            "genre": r.get("primaryGenreName") or "", "author_ok": best[0] >= 0.99}


# ---------------------------------------------------------------- the Warhammer 40k Wiki

WIKI = "https://warhammer40k.fandom.com/api.php"
KINDS = ["Audio Drama", "Novel", "Short Story", "Novella", "Anthology", "Audiobook", "Audio Book"]


def _unwiki(v: str) -> str:
    v = re.sub(r"<ref.*?(</ref>|/>)", "", v or "", flags=re.S)
    v = re.sub(r"\[\[File:[^\]]*\]\]", "", v)
    v = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", v)
    v = re.sub(r"<br\s*/?>", ", ", v)
    v = re.sub(r"<[^>]+>|'{2,}|\{\{[^}]*\}\}", "", v)
    return re.sub(r"\s+", " ", v).strip(" ,")


def infobox(text: str) -> dict:
    """The fields of a page's book infobox ({{Audiobook}}, {{Infobox book}} ...)."""
    text = text or ""
    m = re.search(r"\{\{\s*(Audiobook|Book|Novel|Anthology|Audio ?Drama|Infobox[^|\n]*)", text, re.I)
    if not m or not re.search(r"audio|book|novel|anthology", m.group(1), re.I):
        return {}
    depth, i = 0, m.start()
    while i < len(text) - 1:
        if text[i:i + 2] == "{{":
            depth, i = depth + 1, i + 2
        elif text[i:i + 2] == "}}":
            depth, i = depth - 1, i + 2
            if depth == 0:
                break
        else:
            i += 1
    body = text[m.end():i - 2]
    parts, cur, d = [], "", 0
    for ch in body:                                # | outside [[ ]] and {{ }} separates the fields
        d += ch in "[{"
        d -= ch in "]}"
        if ch == "|" and d == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    parts.append(cur)
    box = {"template": m.group(1).strip()}
    for part in parts:
        if "=" in part:
            k, v = part.split("=", 1)
            box[k.strip().lower().replace(" ", "_")] = _unwiki(v)
    box.setdefault("title", box.get("title1") or box.get("name") or "")
    return box


def wiki_lookup(title: str, author: str = "", minutes: int = 0) -> dict | None:
    q = _get("wiki", WIKI, {"action": "query", "titles": "|".join([title] + [f"{title} ({k})" for k in KINDS]),
                            "redirects": 1, "format": "json"}) or {}
    pages = [p["title"] for p in q.get("query", {}).get("pages", {}).values() if "missing" not in p]
    s = _get("wiki", WIKI, {"action": "query", "list": "search", "srsearch": title, "srlimit": 8, "format": "json"}) or {}
    pages += [x["title"] for x in s.get("query", {}).get("search", []) if x["title"] not in pages]
    best = None
    for page in pages[:10]:
        if max(sim(re.sub(r"\s*\([^)]*\)$", "", page), title), sim(page, title)) < 0.8:
            continue
        p = _get("wiki", WIKI, {"action": "parse", "page": page, "prop": "wikitext", "format": "json", "redirects": 1}) or {}
        box = infobox(p.get("parse", {}).get("wikitext", {}).get("*", ""))
        if not box:
            continue
        au = sim(box.get("author", ""), author) if author else 0.5
        hours = re.search(r"(\d+)\s*(hours?|hrs?)", box.get("length", ""), re.I)
        mins = re.search(r"(\d+)\s*min", box.get("length", ""), re.I)
        length = (int(hours.group(1)) * 60 if hours else 0) + (int(mins.group(1)) if mins else 0)
        close = bool(length and minutes and abs(length - minutes) <= max(15, 0.2 * minutes))
        audio = "audio" in (box.get("type", "") + page + box["template"]).lower()
        score = sim(box["title"] or page, title) * 0.5 + (au > 0.8) * 0.3 + close * 0.1 + (audio == (minutes < 300)) * 0.1
        if best is None or score > best[0]:
            best = (score, page, box)
    if not best or best[0] < 0.6:
        return None
    score, page, box = best
    year = re.search(r"(19|20)\d\d", box.get("release_date") or box.get("released") or box.get("published") or "")
    narrators = box.get("performer") or box.get("narrator") or box.get("narrated_by") or ""
    series = re.sub(r"\s*\((novels|series)\)$", "", box.get("series", ""), flags=re.I)
    return {"page": page, "title": box["title"] or page, "author": box.get("author", ""), "year": year.group(0) if year else "",
            "narrators": [n.strip() for n in re.split(r",|\band\b", narrators) if n.strip()][:6],
            "series": "" if re.match(r"^(n/?a|none|various)$", series, re.I) else series}


# ---------------------------------------------------------------- Open Library

def first_published(title: str, author: str) -> str:
    d = _get("openlibrary", "https://openlibrary.org/search.json",
             {"title": title, "author": author, "fields": "title,first_publish_year", "limit": 5}) or {}
    years = [x["first_publish_year"] for x in d.get("docs", [])[:3]
             if x.get("first_publish_year") and sim(x.get("title", ""), title) > 0.8]
    return str(min(years)) if years else ""


# ---------------------------------------------------------------- all together

@dataclass
class Guess:
    """What a book's folder and files say about it."""
    title: str = ""
    titles: list = field(default_factory=list)       # other ways to put it (the album tag, the file name)
    authors: list = field(default_factory=list)
    narrator: str = ""
    series: str = ""
    vol: str = ""
    year: str = ""
    asin: str = ""
    duration: float = 0
    language: str = ""


@dataclass
class Found:
    title: str
    authors: list
    narrators: list
    series: str = ""
    vol: str = ""
    year: str = ""
    subtitle: str = ""
    language: str = ""
    description: str = ""
    publisher: str = ""
    asin: str = ""
    categories: list = field(default_factory=list)
    images: list = field(default_factory=list)       # cover addresses, the best first
    chapters: dict | None = None                     # Audible's, for the same recording
    warhammer: bool = False
    sources: list = field(default_factory=list)
    sure: bool = False


UMBRELLA = re.compile(r"^(warhammer( 40,000)?|star wars|star wars: legends|the cosmere|wizarding world.*)$", re.I)


def vol_text(v: str) -> str:
    v = (v or "").strip()
    if not re.match(r"^\d+(\.\d+)?$", v):
        return ""
    return v.rstrip("0").rstrip(".") if "." in v else str(int(v))


def _score(p: dict, g: Guess) -> tuple[float, float]:
    titles = [g.title] + g.titles
    ts = max((sim(bare_title(p["title"]), t) for t in titles if t), default=0)
    names = p["authors"] + p["narrators"]
    au = 1.0 if any(sim(a, n) > 0.8 for a in g.authors for n in names) else 0.0
    dur = 1 - min(1, abs(p["runtime"] - g.duration) / max(g.duration, 1)) if p["runtime"] and g.duration else 0.3
    return ts * 0.55 + au * 0.25 + dur * 0.2, ts


def identify(g: Guess) -> Found:
    """The book a guess is, as well as the sources can tell; ``sure`` when Audible agrees on title and author."""
    cands: dict[str, dict] = {}
    if g.asin:
        p = audible_get(g.asin)
        if p:
            cands[p["asin"]] = p
    for t in [g.title] + g.titles[:1]:
        for a in g.authors[:2] or [""]:
            if t:
                for p in audible_search(t, a):
                    cands.setdefault(p["asin"], p)
    if not cands and g.title:
        for p in audible_search("", keywords=f"{g.title} {g.authors[0] if g.authors else ''}".strip()):
            cands.setdefault(p["asin"], p)
    ranked = sorted(((_score(p, g), p) for p in cands.values()
                     if not p["language"] or not g.language or p["language"][:2] == g.language[:2] or p["asin"] == g.asin),
                    key=lambda x: -x[0][0])
    pick = ranked[0][1] if ranked and ranked[0][0][0] >= 0.7 and ranked[0][0][1] >= 0.6 else None
    sure = bool(pick) and ranked[0][0][0] >= 0.8

    f = Found(title=g.title, authors=list(g.authors[:1]), narrators=[g.narrator] if g.narrator else [],
              series=g.series, vol=g.vol, year=g.year, language=g.language)
    if pick:
        f.sources.append("audible")
        # a name already given (a folder like "Vol 5 - 2024 - Wind and Truth") stays, unless it's something else
        if not g.title or sim(bare_title(pick["title"]), g.title) < 0.8:
            f.title = bare_title(pick["title"])
        f.authors = pick["authors"][:3] or f.authors
        f.narrators = f.narrators or pick["narrators"]
        f.subtitle, f.publisher, f.asin = pick["subtitle"], pick["publisher"], pick["asin"]
        f.description, f.categories = pick["summary"], pick["categories"]
        f.language = f.language or pick["language"]
        if pick["image"]:
            f.images.append(pick["image"])
        if not f.series:
            s = [s for s in pick["series"] if s[0] and not UMBRELLA.match(s[0])]
            if s:
                f.series = re.sub(r":\s*warhammer( 40,000| chronicles)?$", "", s[0][0], flags=re.I).strip()
                f.vol = vol_text(s[0][1])
        if pick["runtime"] and g.duration and abs(pick["runtime"] - g.duration) <= 120:
            f.chapters = audible_chapters(pick["asin"])
    f.warhammer = bool(WARHAMMER.search(" ".join([f.title, f.series, f.publisher, " ".join(g.titles)])))
    author = f.authors[0] if f.authors else ""
    if f.warhammer:
        w = wiki_lookup(f.title, author, int(g.duration // 60))
        if w:
            f.sources.append("wiki")
            f.year = g.year or w["year"] or f.year
            f.narrators = f.narrators or w["narrators"]
            if not f.series and w["series"]:
                f.series = w["series"]
            if not f.authors and w["author"] and not w["author"].lower().startswith("various"):
                f.authors = [a.strip() for a in re.split(r",|\band\b|&", w["author"]) if a.strip()][:3]
    a = apple_search(f.title, author)
    if a:
        f.sources.append("apple")
        f.description = f.description or a["description"]
        if a["image"]:
            f.images.append(a["image"])
    if not f.year and f.title and author:
        f.year = first_published(f.title, author)
    if not f.year:
        f.year = ((pick or {}).get("release") or (a or {}).get("release") or "")[:4]
    f.sure = sure or (f.warhammer and "wiki" in f.sources)
    return f
