"""Where podcasts are found to browse and search (api/podcasts.py): Apple Podcasts' charts for a country,
in its categories and their subcategories; with a key each, what's trending on Podcast Index (by language,
in its categories, some of which Apple doesn't have, such as tabletop and role-playing games) and Listen
Notes' best (by region). National is the server's country (Settings → Radio home country) and its language,
international the United States' charts and English. Answers are kept on disk a while: an hour, and Listen
Notes' a week, as its free plan allows 300 requests a month."""

import hashlib
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

from . import enrich, env, settings

log = logging.getLogger(__name__)

# Apple Podcasts' categories and their subcategories (its genre ids), each with Podcast Index's categories
# for it (the Podcast Namespace's, which cut Apple's names into words); Podcast Index's own ones that Apple
# doesn't have come under the nearest of Apple's ("pi-<its id>")
CATEGORIES = [
    (1301, "Arts", "Arts", [
        (1482, "Books", "Books"),
        (1402, "Design", "Design"),
        (1459, "Fashion & Beauty", "Fashion,Beauty"),
        (1306, "Food", "Food"),
        (1405, "Performing Arts", "Performing"),
        (1406, "Visual Arts", "Visual"),
    ]),
    (1321, "Business", "Business", [
        (1410, "Careers", "Careers"),
        (1493, "Entrepreneurship", "Entrepreneurship"),
        (1412, "Investing", "Investing"),
        (1491, "Management", "Management"),
        (1492, "Marketing", "Marketing"),
        (1494, "Non-Profit", "Non-Profit"),
        ("pi-112", "Cryptocurrency", "Cryptocurrency"),
    ]),
    (1303, "Comedy", "Comedy", [
        (1496, "Comedy Interviews", "Interviews"),
        (1495, "Improv", "Improv"),
        (1497, "Stand-Up", "Stand-Up"),
    ]),
    (1304, "Education", "Education", [
        (1501, "Courses", "Courses"),
        (1499, "How To", "How-To"),
        (1498, "Language Learning", "Language"),
        (1500, "Self-Improvement", "Self-Improvement"),
    ]),
    (1483, "Fiction", "Fiction", [
        (1486, "Comedy Fiction", "Fiction"),
        (1484, "Drama", "Drama"),
        (1485, "Science Fiction", "Fiction"),
    ]),
    (1511, "Government", "Government", []),
    (1512, "Health & Fitness", "Health,Fitness", [
        (1513, "Alternative Health", "Alternative"),
        (1514, "Fitness", "Fitness"),
        (1518, "Medicine", "Medicine"),
        (1517, "Mental Health", "Mental"),
        (1515, "Nutrition", "Nutrition"),
        (1516, "Sexuality", "Sexuality"),
    ]),
    (1487, "History", "History", []),
    (1305, "Kids & Family", "Kids,Family", [
        (1519, "Education for Kids", "Kids"),
        (1521, "Parenting", "Parenting"),
        (1522, "Pets & Animals", "Pets,Animals"),
        (1520, "Stories for Kids", "Stories"),
    ]),
    (1502, "Leisure", "Leisure", [
        (1510, "Animation & Manga", "Animation,Manga"),
        (1503, "Automotive", "Automotive"),
        (1504, "Aviation", "Aviation"),
        (1506, "Crafts", "Crafts"),
        (1507, "Games", "Games"),
        (1505, "Hobbies", "Hobbies"),
        (1508, "Home & Garden", "Home,Garden"),
        (1509, "Video Games", "Video-Games"),
        ("pi-110", "Tabletop", "Tabletop"),
        ("pi-111", "Role-Playing", "Role-Playing"),
    ]),
    (1310, "Music", "Music", [
        (1523, "Music Commentary", "Commentary"),
        (1524, "Music History", "Music"),
        (1525, "Music Interviews", "Interviews"),
    ]),
    (1489, "News", "News", [
        (1490, "Business News", "Business"),
        (1526, "Daily News", "Daily"),
        (1531, "Entertainment News", "Entertainment"),
        (1530, "News Commentary", "Commentary"),
        (1527, "Politics", "Politics"),
        (1529, "Sports News", "Sports"),
        (1528, "Tech News", "Technology"),
    ]),
    (1314, "Religion & Spirituality", "Religion,Spirituality", [
        (1438, "Buddhism", "Buddhism"),
        (1439, "Christianity", "Christianity"),
        (1463, "Hinduism", "Hinduism"),
        (1440, "Islam", "Islam"),
        (1441, "Judaism", "Judaism"),
        (1532, "Religion", "Religion"),
        (1444, "Spirituality", "Spirituality"),
    ]),
    (1533, "Science", "Science", [
        (1538, "Astronomy", "Astronomy"),
        (1539, "Chemistry", "Chemistry"),
        (1540, "Earth Sciences", "Earth"),
        (1541, "Life Sciences", "Life"),
        (1536, "Mathematics", "Mathematics"),
        (1534, "Natural Sciences", "Natural"),
        (1537, "Nature", "Nature"),
        (1542, "Physics", "Physics"),
        (1535, "Social Sciences", "Social"),
        ("pi-108", "Climate", "Climate"),
        ("pi-109", "Weather", "Weather"),
    ]),
    (1324, "Society & Culture", "Society,Culture", [
        (1543, "Documentary", "Documentary"),
        (1302, "Personal Journals", "Personal,Journals"),
        (1443, "Philosophy", "Philosophy"),
        (1320, "Places & Travel", "Places,Travel"),
        (1544, "Relationships", "Relationships"),
    ]),
    (1545, "Sports", "Sports", [
        (1549, "Baseball", "Baseball"),
        (1548, "Basketball", "Basketball"),
        (1554, "Cricket", "Cricket"),
        (1560, "Fantasy Sports", "Fantasy"),
        (1547, "Football", "Football"),
        (1553, "Golf", "Golf"),
        (1550, "Hockey", "Hockey"),
        (1552, "Rugby", "Rugby"),
        (1551, "Running", "Running"),
        (1546, "Soccer", "Soccer"),
        (1558, "Swimming", "Swimming"),
        (1556, "Tennis", "Tennis"),
        (1557, "Volleyball", "Volleyball"),
        (1559, "Wilderness", "Wilderness"),
        (1555, "Wrestling", "Wrestling"),
    ]),
    (1309, "TV & Film", "TV,Film", [
        (1562, "After Shows", "After-Shows"),
        (1564, "Film History", "Film"),
        (1565, "Film Interviews", "Interviews"),
        (1563, "Film Reviews", "Reviews"),
        (1561, "TV Reviews", "Reviews"),
    ]),
    (1318, "Technology", "Technology", []),
    (1488, "True Crime", "True Crime", []),
]

INTERNATIONAL = "us"
# a country's languages, as Podcast Index's feeds give them (the rest: English)
LANGUAGES = {"se": "sv", "no": "no,nb,nn", "dk": "da", "fi": "fi,sv", "is": "is", "de": "de", "at": "de", "ch": "de,fr,it",
             "fr": "fr", "be": "nl,fr", "nl": "nl", "es": "es", "mx": "es", "ar": "es", "co": "es", "cl": "es", "it": "it",
             "pt": "pt", "br": "pt", "pl": "pl", "cz": "cs", "sk": "sk", "hu": "hu", "ro": "ro", "gr": "el", "tr": "tr",
             "ru": "ru", "ua": "uk", "jp": "ja", "kr": "ko", "cn": "zh", "tw": "zh", "hk": "zh", "in": "en,hi", "id": "id",
             "ee": "et", "lv": "lv", "lt": "lt", "il": "he"}
APPLE_TTL = PI_TTL = 3600
LN_TTL = 7 * 86400
LN = "https://listen-api.listennotes.com/api/v2"
PI = "https://api.podcastindex.org/api/1.0"


def _pi_on() -> bool:
    return bool(settings.get("podcastindex_key") and settings.get("podcastindex_secret"))


def tree() -> list[dict]:
    """The categories to browse, each with its subcategories (Podcast Index's own with its key)."""
    return [{"id": gid, "name": name, "subs": [{"id": sid, "name": sname} for sid, sname, _ in subs
                                               if not isinstance(sid, str) or _pi_on()]}
            for gid, name, _, subs in CATEGORIES]


def _find(genre: str) -> tuple[int | str, str, str] | None:
    """(id, name, Podcast Index's categories) of a category or subcategory, by its id."""
    for gid, name, pi, subs in CATEGORIES:
        if str(gid) == genre:
            return gid, name, pi
        for sid, sname, spi in subs:
            if str(sid) == genre:
                return sid, sname, spi
    return None


def place(scope: str) -> tuple[str, str]:
    """(country, languages) for national or international."""
    if scope == "international":
        return INTERNATIONAL, "en"
    country = (settings.get("radio_country") or INTERNATIONAL).lower()
    langs = LANGUAGES.get(country, "en").split(",")
    return country, ",".join(langs + [f"{lang}-{country}" for lang in langs])


# ---------------------------------------------------------------- kept on disk

def _kept(key: str, ttl: float, fetch):
    """What `fetch` gave for `key`, kept `ttl` seconds; an older answer if the source fails meanwhile."""
    path = env.CACHE_DIR / "podcast-directory" / (hashlib.sha1(key.encode()).hexdigest() + ".json")
    old = None
    try:
        old = json.loads(path.read_text())
        if time.time() - old["at"] < ttl:
            return old["data"]
    except (OSError, ValueError, KeyError):
        pass
    try:
        data = fetch()
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as e:
        if old is not None:
            log.info("%s: %s (an older answer stands)", key, e)
            return old["data"]
        raise
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"at": time.time(), "data": data}))
    tmp.replace(path)
    return data


def _client() -> httpx.Client:
    return httpx.Client(headers={"User-Agent": enrich.UA}, timeout=15, follow_redirects=True)


def _hit(title, author, url, image, genre, source) -> dict:
    return {"title": title or "", "author": author or "", "url": url, "image": image or None, "genre": genre or "", "source": source}


def _itunes(ids: list) -> list[dict]:
    """Apple's podcasts by id, with their feeds, in the order asked."""
    if not ids:
        return []
    with _client() as c:
        r = c.get("https://itunes.apple.com/lookup", params={"id": ",".join(map(str, ids[:150])), "entity": "podcast"})
        r.raise_for_status()
    found = {str(x.get("collectionId")): x for x in r.json().get("results", []) if x.get("feedUrl")}
    return [_hit(x.get("collectionName"), x.get("artistName"), x["feedUrl"], x.get("artworkUrl600") or x.get("artworkUrl100"),
                 x.get("primaryGenreName"), "apple") for i in ids if (x := found.get(str(i)))]


# ---------------------------------------------------------------- Apple Podcasts

def apple_chart(country: str, genre: int | None, limit: int = 100) -> list[dict]:
    """Apple's chart for a country: overall, or for a category or subcategory."""
    def fetch():
        with _client() as c:
            if genre:
                r = c.get(f"https://itunes.apple.com/{country}/rss/toppodcasts/limit={limit}/genre={genre}/json")
                if r.status_code != 200:
                    return []
                entries = r.json().get("feed", {}).get("entry", [])
                ids = [e["id"]["attributes"]["im:id"] for e in (entries if isinstance(entries, list) else [entries])]
            else:
                r = c.get(f"https://rss.marketingtools.apple.com/api/v2/{country}/podcasts/top/{min(limit, 100)}/podcasts.json")
                if r.status_code != 200:
                    return []
                ids = [x["id"] for x in r.json().get("feed", {}).get("results", [])]
        return _itunes(ids)
    return _kept(f"apple:{country}:{genre}:{limit}", APPLE_TTL, fetch)


def apple_search(q: str, country: str) -> list[dict]:
    with _client() as c:
        r = c.get("https://itunes.apple.com/search", params={"media": "podcast", "term": q, "limit": 30, "country": country})
        r.raise_for_status()
    return [_hit(x.get("collectionName"), x.get("artistName"), x["feedUrl"], x.get("artworkUrl600") or x.get("artworkUrl100"),
                 x.get("primaryGenreName"), "apple") for x in r.json().get("results", []) if x.get("feedUrl")]


# ---------------------------------------------------------------- Podcast Index

def _pi_get(path: str, params: dict) -> dict:
    key, secret = settings.get("podcastindex_key"), settings.get("podcastindex_secret")
    now = str(int(time.time()))
    with _client() as c:
        r = c.get(PI + path, params=params, headers={
            "X-Auth-Key": key, "X-Auth-Date": now,
            "Authorization": hashlib.sha1((key + secret + now).encode()).hexdigest()})
        r.raise_for_status()
        return r.json()


def _pi_hits(feeds: list) -> list[dict]:
    return [_hit(f.get("title"), f.get("author"), f["url"], f.get("artwork") or f.get("image"),
                 next(iter((f.get("categories") or {}).values()), ""), "podcastindex")
            for f in feeds if f.get("url")]


def pi_trending(langs: str, cats: str) -> list[dict]:
    """What's trending on Podcast Index in these languages, in these of its categories (or all)."""
    params = {"max": 60, "lang": langs, **({"cat": cats} if cats else {})}
    return _kept(f"pi:{langs}:{cats}", PI_TTL, lambda: _pi_hits(_pi_get("/podcasts/trending", params).get("feeds") or []))


def pi_search(q: str) -> list[dict]:
    return _pi_hits(_pi_get("/search/byterm", {"q": q, "max": 30}).get("feeds") or [])


# ---------------------------------------------------------------- Listen Notes

def _ln_get(path: str, params: dict) -> dict:
    with _client() as c:
        r = c.get(LN + path, params=params, headers={"X-ListenAPI-Key": settings.get("listennotes_key")})
        r.raise_for_status()
        left = r.headers.get("X-ListenAPI-FreeQuota"), r.headers.get("X-ListenAPI-Usage")
        if all(left):
            log.info("Listen Notes: %s of %s requests used this month", left[1], left[0])
        return r.json()


def _ln_genre(name: str) -> int | None:
    """Listen Notes' genre by the name Apple gives it (theirs follow Apple's)."""
    genres = _kept("ln:genres", 30 * 86400, lambda: _ln_get("/genres", {}).get("genres") or [])
    want = name.lower().replace("&", "and")
    return next((g["id"] for g in genres if g.get("name", "").lower().replace("&", "and") == want), None)


def ln_best(region: str, name: str | None) -> list[dict]:
    """Listen Notes' best for a region, overall or in the genre named so; their feeds, or Apple's for them
    (the free plan may leave the feed out)."""
    genre = _ln_genre(name) if name else None
    if name and genre is None:
        return []

    def fetch():
        podcasts = _ln_get("/best_podcasts", {"region": region, "page": 1, "safe_mode": 0,
                                              **({"genre_id": genre} if genre else {})}).get("podcasts") or []
        out, by_apple = [], []
        for p in podcasts:
            rss = p.get("rss") or ""
            if rss.startswith("http"):
                out.append(_hit(p.get("title"), p.get("publisher"), rss, p.get("image") or p.get("thumbnail"), "", "listennotes"))
            elif p.get("itunes_id"):
                by_apple.append(p["itunes_id"])
        return out + [{**h, "source": "listennotes"} for h in _itunes(by_apple)]
    return _kept(f"ln:{region}:{genre}", LN_TTL, fetch)


# ---------------------------------------------------------------- together

def browse(genre: str, scope: str) -> dict:
    """The lists for a category (or overall, ""), national or international: Apple's chart, and with their
    keys Podcast Index's trending and Listen Notes' best; a source that fails is left out."""
    country, langs = place(scope)
    found = _find(genre) if genre else None
    gid, name, pi = found if found else (None, None, "")
    jobs = {}
    if not isinstance(gid, str):        # Apple has no chart for Podcast Index's own categories
        jobs["apple"] = lambda: apple_chart(country, gid)
    if _pi_on() and (pi or not genre):
        jobs["podcastindex"] = lambda: pi_trending(langs, pi)
    if settings.get("listennotes_key") and not isinstance(gid, str):
        jobs["listennotes"] = lambda: ln_best(country, name)
    sections = []
    with ThreadPoolExecutor(len(jobs) or 1) as pool:
        futures = {src: pool.submit(fn) for src, fn in jobs.items()}
        for src, fut in futures.items():
            try:
                items = fut.result()
            except (httpx.HTTPError, ValueError, KeyError, TypeError) as e:
                log.info("podcast directory, %s: %s", src, e)
                continue
            sections.append({"source": src, "items": items})
    missing = [src for src, on in (("podcastindex", _pi_on()), ("listennotes", bool(settings.get("listennotes_key")))) if not on]
    return {"country": country, "languages": langs.split(",")[0], "sections": sections, "missing": missing}


def search(q: str, scope: str) -> list[dict]:
    """Apple's matches, then Podcast Index's (with its key) that Apple didn't have."""
    country, _ = place(scope)
    hits = apple_search(q, country)
    if _pi_on():
        try:
            seen = {h["url"] for h in hits}
            hits += [h for h in pi_search(q) if h["url"] not in seen]
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as e:
            log.info("podcast search, Podcast Index: %s", e)
    return hits
