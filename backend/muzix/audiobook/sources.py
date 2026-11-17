"""Where an audiobook's details come from, all without keys:

- Audible's catalog API: title, authors, narrators, series and number, categories, language, runtime, summary, cover.
- Audnexus: Audible's chapter list for a title, with times.
- Bonnier Audio (Swedish audiobooks): its public book search, then the book's page for the narrator, length,
  summary, genre, series and number, first year and a large cover. Asked when Audible isn't sure.
- Apple Books (the iTunes Search API, about 20 searches a minute): a large cover, a summary, the release.
- The Warhammer 40k Wiki (Fandom's MediaWiki API) for Black Library's books and audio dramas: first release,
  author, performers, series. Black Library's own site and Lexicanum sit behind a human check, so not those.
- Open Library: the year a book was first published.

``identify`` asks them in that order and puts the answers together (``Found``)."""

import difflib
import html
import logging
import re
import threading
import time
import unicodedata
import urllib.parse
from dataclasses import dataclass, field

import httpx

from .. import enrich

log = logging.getLogger("muzix.audiobook")
TIMEOUT = 20
_gap = {"audible": 0.3, "audnexus": 0.3, "bonnier": 0.5, "apple": 3.2, "wiki": 0.4, "openlibrary": 0.5}
_last: dict[str, float] = {}
_lock = threading.Lock()
WARHAMMER = re.compile(r"warhammer|horus heresy|black library|siege of terra|space marine|gotrek|eisenhorn|ravenor|"
                       r"gaunt'?s ghosts|ciaphas cain|age of sigmar|necromunda|primarchs|40,?000|\b40k\b", re.I)


def _client() -> httpx.Client:
    return httpx.Client(headers={"User-Agent": enrich.UA}, timeout=TIMEOUT, follow_redirects=True)


def _get(source: str, url: str, params: dict | None = None, page: bool = False):
    """A JSON answer (or a page's text), or None. Each source is asked no faster than it allows."""
    for attempt in range(3):
        with _lock:                         # this source's next turn, waited for outside the lock: the others go meanwhile
            turn = max(time.monotonic(), _last.get(source, 0) + _gap[source])
            _last[source] = turn
        if turn > time.monotonic():
            time.sleep(turn - time.monotonic())
        try:
            with _client() as c:
                r = c.get(url, params=params)
            if r.status_code in (429, 503):
                time.sleep(5 * (attempt + 1))
                continue
            if r.status_code >= 400:
                return None
            return r.text if page else r.json()
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


# ---------------------------------------------------------------- one book, from any source

SOURCES = {"audible": "Audible", "bonnier": "Bonnier Audio", "apple": "Apple Books", "wiki": "Warhammer 40k Wiki"}


def book(source: str, id: str, **kw) -> dict:
    """A source's book, alike for every source: what identify() takes and "Pick the right book" lists."""
    return {"source": source, "id": str(id), "asin": "", "url": "", "title": "", "subtitle": "", "authors": [],
            "narrators": [], "runtime": 0, "release": "", "year": "", "format": "", "publisher": "", "series": [],
            "categories": [], "image": "", "language": "", "summary": "", **kw}


def split_by(t: str) -> tuple[str, str]:
    """"Mordets praktik av Kerstin Ekman", "Mrs Dalloway by Virginia Woolf" → (title, author); ("", "") if it isn't."""
    m = re.match(r"^(.+?)\s+(?:av|by)\s+((?:[A-ZÅÄÖÆØÉ][\w'.-]*\s+){1,3}[A-ZÅÄÖÆØÉ][\w'.-]+)$", (t or "").strip())
    return (m.group(1).strip(" -:,"), m.group(2).strip()) if m else ("", "")


# ---------------------------------------------------------------- Audible

GROUPS = "contributors,product_attrs,product_desc,product_extended_attrs,media,series,category_ladders"
AUDIBLE_LINK = re.compile(r"audible\.[a-z.]+/pd/(?:[^/?#]+/)?([A-Z0-9]{10})\b|^\s*(B0[0-9A-Z]{8})\s*$", re.I)


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
    return book(
        "audible", p["asin"], asin=p["asin"], url=f"https://www.audible.com/pd/{p['asin']}",
        title=p.get("title") or "", subtitle=p.get("subtitle") or "",
        authors=[a["name"] for a in p.get("authors") or [] if "translator" not in a["name"].lower()],
        narrators=[n["name"] for n in p.get("narrators") or []],
        runtime=(p.get("runtime_length_min") or 0) * 60, release=p.get("release_date") or "",
        format=p.get("format_type") or "", publisher=p.get("publisher_name") or "",
        series=[(s.get("title") or "", s.get("sequence") or "") for s in p.get("series") or []],
        categories=[[c["name"] for c in lad.get("ladder", [])] for lad in p.get("category_ladders") or []],
        image=imgs.get("1215") or imgs.get("500") or "", language=(p.get("language") or "").lower(),
        summary=p.get("publisher_summary") or p.get("merchandising_summary") or "",
    )


def audible_chapters(asin: str) -> dict | None:
    """{"runtime": s, "chapters": [{"start": s, "title"}]} for the Audible recording, from Audnexus."""
    d = _get("audnexus", f"https://api.audnex.us/books/{asin}/chapters")
    if not d or not d.get("chapters"):
        return None
    return {"runtime": d.get("runtimeLengthSec") or 0,
            "chapters": [{"start": c["startOffsetMs"] / 1000, "title": c["title"]} for c in d["chapters"]]}


# ---------------------------------------------------------------- Bonnier Audio

BONNIER = "https://www.bonnieraudio.se"
BONNIER_SEARCH = "https://data.bonnierforlagen.se/api/v1/public/works/search/"
BONNIER_BOOK = re.compile(r"bonnieraudio\.se/bocker/(\d+)", re.I)


def _bonnier_title(t: str) -> tuple[str, str]:
    """"Konsten att läsa tankar : hur du förstår ..." → (title, subtitle)."""
    title, _, sub = html.unescape(t or "").partition(" : ")
    return title.strip(), sub.strip()


def bonnier_search(q: str) -> list[dict]:
    """Bonnier Audio's books for a title: its search takes a title, or a surname and a title, not a full name. Brief:
    no narrator or length (those are on the book's page, bonnier_get)."""
    d = _get("bonnier", BONNIER_SEARCH, {"main_publisher": 0, "site_type": "audio_site", "site_domain": "www.bonnieraudio.se",
                                         "page": 1, "limit": 10, "s": q}) or {}
    data = d.get("data") if isinstance(d, dict) else None
    out = []
    for it in data.get("items", []) if isinstance(data, dict) else []:
        if not it.get("id") or not it.get("bookPath"):
            continue
        title, sub = _bonnier_title(it.get("title", ""))
        out.append(book("bonnier", it["id"], url=BONNIER + it["bookPath"], title=title, subtitle=sub,
                        authors=[a["name"] for a in it.get("authors") or [] if a.get("name")],
                        release=it.get("publishingDate") or "", language="swedish", publisher="Bonnier Audio",
                        image=re.sub(r"/bokbilder/[a-z]/", "/bokbilder/g/", it.get("coverImage") or "")))
    return out


def _text(v: str) -> str:
    v = re.sub(r"<\s*br\s*/?>", "\n", v or "", flags=re.I)
    v = html.unescape(re.sub(r"<[^>]+>", "", v))
    v = re.sub(r"\n[ \t]+|[ \t]+\n", "\n", re.sub(r"[ \t]+", " ", v))
    return re.sub(r"\n{3,}", "\n\n", v).strip()


def _section(page: str, cls: str) -> str:
    """The first <section class="cls"> (the page has each twice, for wide and narrow screens)."""
    m = re.search(rf'<section class="{re.escape(cls)}[^"]*">(.*?)</section>', page, re.S)
    return m.group(1) if m else ""


def bonnier_book(page: str, url: str) -> dict | None:
    """A Bonnier Audio book's page read."""
    m = re.search(r"<h1[^>]*>(.*?)</h1>", page, re.S)
    if not m:
        return None
    title, sub = _bonnier_title(_text(m.group(1)))
    intro = re.search(r'class="book__content__intro__author"(.*?)</div>', page, re.S)
    authors = [_text(a) for a in re.findall(r"<a [^>]*>(.*?)</a>", intro.group(1) if intro else "", re.S)]
    facts: dict[str, str] = {}
    for part in (_section(page, "book__content__facts"), _section(page, "book__content__details")):
        for k, v in re.findall(r"<strong>\s*([^<:]+?)\s*:\s*</strong>(.*?)(?=<strong>|</p>|<br)", part, re.S):
            facts.setdefault(k.strip(), _text(v))
    played = facts.get("Speltid", "")
    h, mins = re.search(r"(\d+)\s*h", played), re.search(r"(\d+)\s*min", played)
    series, vol = facts.get("Serie", ""), ""
    shelf = re.search(r"Boken ingår i serien.*?</h2>(.*?)</section>", page, re.S)
    own = BONNIER_BOOK.search(url)
    if series and shelf and own:             # the series' books are listed in order
        ids = list(dict.fromkeys(re.findall(r"/bocker/(\d+)/", shelf.group(1))))
        vol = str(ids.index(own.group(1)) + 1) if own.group(1) in ids else ""
    year = re.search(r"(19|20)\d\d", facts.get("Originalutgåvans utgivningsår", "") or facts.get("Utgivningsdag", ""))
    image = re.search(r'<meta property="og:image" content="([^"]+)"', page)
    return book(
        "bonnier", own.group(1) if own else url, url=url, title=title, subtitle=sub, authors=authors,
        narrators=[n.strip() for n in re.split(r",|&|\boch\b", facts.get("Uppläsare", "")) if n.strip()],
        runtime=(int(h.group(1)) * 3600 if h else 0) + (int(mins.group(1)) * 60 if mins else 0),
        release=facts.get("Utgivningsdag", ""), year=year.group(0) if year else "", publisher="Bonnier Audio",
        series=[(series, vol)] if series else [],
        categories=[[c] for c in (facts.get("Genre", ""), facts.get("Thema-kod", "")) if c],
        image=image.group(1) if image else "", language="swedish", summary=_text(_section(page, "book__content__excerpt")),
    )


def bonnier_get(url: str) -> dict | None:
    """A Bonnier Audio book by its page (https://www.bonnieraudio.se/bocker/155255/mordets-praktik/) or number."""
    m = BONNIER_BOOK.search(url or "") or re.fullmatch(r"\s*(\d+)\s*", url or "")
    if not m:
        return None
    url = url if BONNIER_BOOK.search(url) and url.startswith("http") else f"{BONNIER}/bocker/{m.group(1)}/"
    page = _get("bonnier", url, page=True)
    return bonnier_book(page, url) if page else None


def bonnier_find(titles: list[str], authors: list[str] = (), most: int = 5) -> list[dict]:
    """Bonnier Audio's books for the first of ``titles`` it has any for, the likeliest first, read from their pages."""
    hits: dict[str, dict] = {}
    for t in [t for t in dict.fromkeys(titles) if t]:
        for h in bonnier_search(t):
            hits.setdefault(h["id"], h)
        if hits:
            break

    def likely(h):
        ts = max((sim(h["title"], t) for t in titles if t), default=0)
        au = any(sim(a, b) > 0.8 for a in authors for b in h["authors"])
        return ts + au * 0.5

    out = []
    for h in sorted(hits.values(), key=lambda h: -likely(h))[:most]:
        p = bonnier_get(h["url"])
        if p:
            p["authors"], p["image"] = p["authors"] or h["authors"], p["image"] or h["image"]
            out.append(p)
    return out


def bonnier_lookup(g: "Guess") -> tuple[dict, bool] | None:
    """The Bonnier Audio book a guess is, and whether that's sure (as for Audible: the title, an author, the length)."""
    titles = [g.title] + g.titles[:2]
    near = [h for h in bonnier_find(titles, g.authors, most=3)
            if max((sim(h["title"], t) for t in titles if t), default=0) >= 0.8]
    ranked = sorted(((_score(p, g), p) for p in near), key=lambda x: -x[0][0])
    if not ranked or ranked[0][0][0] < 0.7 or ranked[0][0][1] < 0.6:
        return None
    return ranked[0][1], ranked[0][0][0] >= 0.8


# ---------------------------------------------------------------- Apple Books

APPLE_LINK = re.compile(r"(?:books|itunes)\.apple\.com/(?:([a-z]{2})/)?[^?#]*?/id(\d+)", re.I)
APPLE_STORES = ("us", "se")          # the Swedish store has books the American one hasn't (and Swedish ones)


def _apple_slim(r: dict, country: str) -> dict:
    art = r.get("artworkUrl100") or ""
    return book("apple", f"{country}:{r['collectionId']}", url=(r.get("collectionViewUrl") or "").split("?")[0],
                title=r.get("collectionName") or "",
                authors=[a.strip() for a in re.split(r",|&", r.get("artistName") or "") if a.strip()],
                release=(r.get("releaseDate") or "")[:10], categories=[[r["primaryGenreName"]]] if r.get("primaryGenreName") else [],
                image=re.sub(r"/\d+x\d+bb\.(jpg|png)$", "/1400x1400bb.jpg", art) if art else "",
                summary=r.get("description") or "")


def apple_list(q: str, country: str = "us") -> list[dict]:
    d = _get("apple", "https://itunes.apple.com/search", {"term": q, "media": "audiobook", "entity": "audiobook",
                                                          "limit": 10, "country": country}) or {}
    return [_apple_slim(r, country) for r in d.get("results", []) if r.get("collectionId")]


def apple_get(id: str) -> dict | None:
    """An Apple Books audiobook by "se:744991348" (store:number) or its page."""
    m = APPLE_LINK.search(id or "")
    country, num = (m.group(1) or "us", m.group(2)) if m else (id.partition(":")[0] if ":" in id else "us", id.rpartition(":")[2])
    if not num.isdigit():
        return None
    for c in dict.fromkeys([country.lower(), *APPLE_STORES]):
        d = _get("apple", "https://itunes.apple.com/lookup", {"id": num, "country": c}) or {}
        r = next((r for r in d.get("results", []) if r.get("collectionId")), None)
        if r:
            return _apple_slim(r, c)
    return None


def apple_search(title: str, author: str = "") -> dict | None:
    """The Apple Books audiobook a title (and author) is, from the American store."""
    best = None
    for p in apple_list(f"{title} {author}".strip()):
        ts = sim(bare_title(p["title"]), title)
        au = max((sim(a, author) for a in p["authors"]), default=0) if author else 0
        score = ts * 0.7 + (au > 0.8) * 0.3
        if ts >= 0.8 and (best is None or score > best[0]):
            best = (score, p)
    return best[1] if best else None


# ---------------------------------------------------------------- the Warhammer 40k Wiki

WIKI = "https://warhammer40k.fandom.com/api.php"
WIKI_LINK = re.compile(r"warhammer40k\.fandom\.com/wiki/([^?#]+)", re.I)
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


def _wiki_pages(title: str) -> list[str]:
    """The wiki's pages that may be the book: its title as it is and with a kind, then its search's."""
    q = _get("wiki", WIKI, {"action": "query", "titles": "|".join([title] + [f"{title} ({k})" for k in KINDS]),
                            "redirects": 1, "format": "json"}) or {}
    pages = [p["title"] for p in q.get("query", {}).get("pages", {}).values() if "missing" not in p]
    s = _get("wiki", WIKI, {"action": "query", "list": "search", "srsearch": title, "srlimit": 8, "format": "json"}) or {}
    return pages + [x["title"] for x in s.get("query", {}).get("search", []) if x["title"] not in pages]


def _wiki_box(page: str) -> dict:
    p = _get("wiki", WIKI, {"action": "parse", "page": page, "prop": "wikitext", "format": "json", "redirects": 1}) or {}
    return infobox(p.get("parse", {}).get("wikitext", {}).get("*", ""))


def _wiki_minutes(box: dict) -> int:
    hours = re.search(r"(\d+)\s*(hours?|hrs?)", box.get("length", ""), re.I)
    mins = re.search(r"(\d+)\s*min", box.get("length", ""), re.I)
    return (int(hours.group(1)) * 60 if hours else 0) + (int(mins.group(1)) if mins else 0)


def _wiki_slim(page: str, box: dict) -> dict:
    year = re.search(r"(19|20)\d\d", box.get("release_date") or box.get("released") or box.get("published") or "")
    narrators = box.get("performer") or box.get("narrator") or box.get("narrated_by") or ""
    series = re.sub(r"\s*\((novels|series)\)$", "", box.get("series", ""), flags=re.I)
    author = box.get("author", "")
    return book("wiki", page, url="https://warhammer40k.fandom.com/wiki/" + page.replace(" ", "_"),
                title=box["title"] or page, publisher="Black Library", language="english",
                authors=[] if author.lower().startswith("various") else
                [a.strip() for a in re.split(r",|\band\b|&", author) if a.strip()][:3],
                narrators=[n.strip() for n in re.split(r",|\band\b", narrators) if n.strip()][:6],
                runtime=_wiki_minutes(box) * 60, year=year.group(0) if year else "",
                series=[] if re.match(r"^(n/?a|none|various)$", series, re.I) or not series else [(series, "")])


def wiki_list(title: str) -> list[dict]:
    """The wiki's books for a title, read from their pages."""
    out = []
    for page in _wiki_pages(title)[:8]:
        if max(sim(re.sub(r"\s*\([^)]*\)$", "", page), title), sim(page, title)) < 0.6:
            continue
        box = _wiki_box(page)
        if box:
            out.append(_wiki_slim(page, box))
    return out


def wiki_get(page: str) -> dict | None:
    m = WIKI_LINK.search(page or "")
    if m:
        page = urllib.parse.unquote(m.group(1)).replace("_", " ")
    box = _wiki_box(page) if page else {}
    return _wiki_slim(page, box) if box else None


def wiki_lookup(title: str, author: str = "", minutes: int = 0) -> dict | None:
    best = None
    for page in _wiki_pages(title)[:10]:
        if max(sim(re.sub(r"\s*\([^)]*\)$", "", page), title), sim(page, title)) < 0.8:
            continue
        box = _wiki_box(page)
        if not box:
            continue
        au = sim(box.get("author", ""), author) if author else 0.5
        length = _wiki_minutes(box)
        close = bool(length and minutes and abs(length - minutes) <= max(15, 0.2 * minutes))
        audio = "audio" in (box.get("type", "") + page + box["template"]).lower()
        score = sim(box["title"] or page, title) * 0.5 + (au > 0.8) * 0.3 + close * 0.1 + (audio == (minutes < 300)) * 0.1
        if best is None or score > best[0]:
            best = (score, page, box)
    if not best or best[0] < 0.6:
        return None
    score, page, box = best
    w = _wiki_slim(page, box)
    return {"page": page, "title": w["title"], "author": box.get("author", ""), "year": w["year"],
            "narrators": w["narrators"], "series": w["series"][0][0] if w["series"] else ""}


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


def search(source: str, q: str, author: str = "") -> list[dict]:
    """One source's books for a search ("Mordets praktik av Kerstin Ekman" is looked for as that, then as "Mordets
    praktik" by her), or the book a link to it is (a link to another source's: nothing)."""
    q, author = (q or "").strip(), (author or "").strip()
    if re.match(r"^(https?://|www\.)", q, re.I) or AUDIBLE_LINK.search(q):
        p = get(source, q)
        return [p] if p else []
    title, by = split_by(q)
    for q, author in [(q, author)] + ([(title, by)] if title else []):
        hits = _search(source, q, author)
        if hits:
            return hits
    return []


def _search(source: str, q: str, author: str) -> list[dict]:
    if source == "audible":
        return audible_search(q, author) or audible_search("", keywords=f"{q} {author}".strip())
    if source == "bonnier":
        return bonnier_find([q], [author] if author else [])
    if source == "apple":
        out: dict[str, dict] = {}
        for c in APPLE_STORES:
            for p in apple_list(f"{q} {author}".strip(), c):
                out.setdefault(p["id"].partition(":")[2], p)
        return list(out.values())
    if source == "wiki":
        return wiki_list(q)
    return []


def get(source: str, id: str) -> dict | None:
    """A source's book by what search() gave as its id, or by a link to it."""
    id = (id or "").strip()
    if source == "audible":
        m = AUDIBLE_LINK.search(id)
        asin = (m.group(1) or m.group(2)) if m else id
        return audible_get(asin.upper()) if re.fullmatch(r"[A-Z0-9]{10}", asin.upper()) else None
    if source == "bonnier":
        return bonnier_get(id)
    if source == "apple":
        return apple_get(id) if APPLE_LINK.search(id) or re.fullmatch(r"([a-z]{2}:)?\d+", id) else None
    if source == "wiki":
        link = re.match(r"^(https?://|www\.)", id) or AUDIBLE_LINK.search(id)
        return wiki_get(id) if WIKI_LINK.search(id) or not link else None
    return None


def _audible_pick(g: Guess) -> tuple[dict | None, bool]:
    """Audible's book for a guess, and whether it agrees on title and author (and length) enough to be sure."""
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
    return pick, bool(pick) and ranked[0][0][0] >= 0.8


def _take(f: Found, g: Guess, pick: dict):
    """What a source's book says, into what's found."""
    f.sources.append(pick["source"])
    title = bare_title(pick["title"])
    short, who = split_by(g.title)
    if short and norm(short) == norm(title) and any(sim(who, a) > 0.8 for a in pick["authors"]):
        f.title = title                     # "Mordets praktik av Kerstin Ekman" was "Mordets praktik" by her
    # a name already given (a folder like "Vol 5 - 2024 - Wind and Truth") stays, unless it's something else
    elif not g.title or sim(title, g.title) < 0.8:
        f.title = title
    f.authors = pick["authors"][:3] or f.authors
    f.narrators = f.narrators or pick["narrators"]
    f.subtitle, f.publisher, f.asin = pick["subtitle"], pick["publisher"], pick["asin"]
    f.description, f.categories = pick["summary"], pick["categories"]
    f.language = f.language or pick["language"]
    f.year = f.year or pick["year"]
    if pick["image"]:
        f.images.append(pick["image"])
    if not f.series:
        s = [s for s in pick["series"] if s[0] and not UMBRELLA.match(s[0])]
        if s:
            f.series = re.sub(r":\s*warhammer( 40,000| chronicles)?$", "", s[0][0], flags=re.I).strip()
            f.vol = vol_text(s[0][1])
    if pick["source"] == "audible" and pick["runtime"] and g.duration and abs(pick["runtime"] - g.duration) <= 120:
        f.chapters = audible_chapters(pick["asin"])


def identify(g: Guess, chosen: dict | None = None) -> Found:
    """The book a guess is, as well as the sources can tell: Audible's, or Bonnier Audio's when Audible isn't sure
    (and the book may be Swedish); ``sure`` when one agrees on title, author and length. ``chosen``: the book the
    admin picked, from any source (search()), taken as sure."""
    f = Found(title=g.title, authors=list(g.authors[:1]), narrators=[g.narrator] if g.narrator else [],
              series=g.series, vol=g.vol, year=g.year, language=g.language)
    if chosen:
        pick, sure = chosen, True
    else:
        pick, sure = _audible_pick(g)
        if not sure and g.title and (not g.language or g.language[:2] == "sw"):
            b = bonnier_lookup(g)
            if b and (b[1] or not pick):
                pick, sure = b
    if pick:
        _take(f, g, pick)
    source = (pick or {}).get("source")
    f.warhammer = source == "wiki" or bool(WARHAMMER.search(" ".join([f.title, f.series, f.publisher, " ".join(g.titles)])))
    author = f.authors[0] if f.authors else ""
    if f.warhammer and source != "wiki":
        w = wiki_lookup(f.title, author, int(g.duration // 60))
        if w:
            f.sources.append("wiki")
            f.year = g.year or w["year"] or f.year
            f.narrators = f.narrators or w["narrators"]
            if not f.series and w["series"]:
                f.series = w["series"]
            if not f.authors and w["author"] and not w["author"].lower().startswith("various"):
                f.authors = [a.strip() for a in re.split(r",|\band\b|&", w["author"]) if a.strip()][:3]
    a = pick if source == "apple" else apple_search(f.title, author)
    if a:
        if "apple" not in f.sources:
            f.sources.append("apple")
        f.description = f.description or a["summary"]
        if a["image"] and a["image"] not in f.images:
            f.images.append(a["image"])
    if not f.year and f.title and author:
        f.year = first_published(f.title, author)
    if not f.year:
        f.year = ((pick or {}).get("release") or (a or {}).get("release") or "")[:4]
    f.sure = sure or (f.warhammer and "wiki" in f.sources)
    return f
