"""Where podcasts are found to browse and search (api/podcasts.py): Apple Podcasts' charts for a country,
in its categories and their subcategories; with a key each, what trended on Podcast Index this month (by
language and category, and what it has about topics Apple has no category for, such as tabletop and
role-playing games) and Listen Notes' best (by region). National is the server's country (Settings → Radio
home country) and its language, international the United States' charts and English. Answers are kept on
disk a while: an hour, and Listen Notes' a week, as its free plan allows few requests a month."""

import hashlib
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

from . import enrich, env, settings

log = logging.getLogger(__name__)

# Apple Podcasts' categories and their subcategories (its genre ids), each with Podcast Index's categories
# for it, by their ids (the Podcast Namespace's, which cut Apple's names into words; its trending takes the
# ids, not those names); Podcast Index's own ones that Apple doesn't have come under the nearest of Apple's
# ("pi-<its id>"), found by search, as few feeds use them
CATEGORIES = [
    (1301, "Arts", "1", [
        (1482, "Books", "2"),
        (1402, "Design", "3"),
        (1459, "Fashion & Beauty", "4,5"),
        (1306, "Food", "6"),
        (1405, "Performing Arts", "7"),
        (1406, "Visual Arts", "8"),
    ]),
    (1321, "Business", "9", [
        (1410, "Careers", "10"),
        (1493, "Entrepreneurship", "11"),
        (1412, "Investing", "12"),
        (1491, "Management", "13"),
        (1492, "Marketing", "14"),
        (1494, "Non-Profit", "15"),
        ("pi-112", "Cryptocurrency", "112"),
    ]),
    (1303, "Comedy", "16", [
        (1496, "Comedy Interviews", "17"),
        (1495, "Improv", "18"),
        (1497, "Stand-Up", "19"),
    ]),
    (1304, "Education", "20", [
        (1501, "Courses", "21"),
        (1499, "How To", "22"),
        (1498, "Language Learning", "23"),
        (1500, "Self-Improvement", "25"),
    ]),
    (1483, "Fiction", "26", [
        (1486, "Comedy Fiction", "26"),
        (1484, "Drama", "27"),
        (1485, "Science Fiction", "26"),
    ]),
    (1511, "Government", "58", []),
    (1512, "Health & Fitness", "29,30", [
        (1513, "Alternative Health", "31"),
        (1514, "Fitness", "30"),
        (1518, "Medicine", "32"),
        (1517, "Mental Health", "33"),
        (1515, "Nutrition", "34"),
        (1516, "Sexuality", "35"),
    ]),
    (1487, "History", "28", []),
    (1305, "Kids & Family", "36,37", [
        (1519, "Education for Kids", "36"),
        (1521, "Parenting", "38"),
        (1522, "Pets & Animals", "39,40"),
        (1520, "Stories for Kids", "41"),
    ]),
    (1502, "Leisure", "42", [
        (1510, "Animation & Manga", "43,44"),
        (1503, "Automotive", "45"),
        (1504, "Aviation", "46"),
        (1506, "Crafts", "47"),
        (1507, "Games", "48"),
        (1505, "Hobbies", "49"),
        (1508, "Home & Garden", "50,51"),
        (1509, "Video Games", "52"),
        ("pi-110", "Tabletop", "110"),
        ("pi-111", "Role-Playing", "111"),
    ]),
    (1310, "Music", "53", [
        (1523, "Music Commentary", "54"),
        (1524, "Music History", "53"),
        (1525, "Music Interviews", "17"),
    ]),
    (1489, "News", "55", [
        (1490, "Business News", "9"),
        (1526, "Daily News", "56"),
        (1531, "Entertainment News", "57"),
        (1530, "News Commentary", "54"),
        (1527, "Politics", "59"),
        (1529, "Sports News", "86"),
        (1528, "Tech News", "102"),
    ]),
    (1314, "Religion & Spirituality", "65,66", [
        (1438, "Buddhism", "60"),
        (1439, "Christianity", "61"),
        (1463, "Hinduism", "62"),
        (1440, "Islam", "63"),
        (1441, "Judaism", "64"),
        (1532, "Religion", "65"),
        (1444, "Spirituality", "66"),
    ]),
    (1533, "Science", "67", [
        (1538, "Astronomy", "68"),
        (1539, "Chemistry", "69"),
        (1540, "Earth Sciences", "70"),
        (1541, "Life Sciences", "71"),
        (1536, "Mathematics", "72"),
        (1534, "Natural Sciences", "73"),
        (1537, "Nature", "74"),
        (1542, "Physics", "75"),
        (1535, "Social Sciences", "76"),
        ("pi-108", "Climate", "108"),
        ("pi-109", "Weather", "109"),
    ]),
    (1324, "Society & Culture", "77,78", [
        (1543, "Documentary", "79"),
        (1302, "Personal Journals", "80,81"),
        (1443, "Philosophy", "82"),
        (1320, "Places & Travel", "83,84"),
        (1544, "Relationships", "85"),
    ]),
    (1545, "Sports", "86", [
        (1549, "Baseball", "87"),
        (1548, "Basketball", "88"),
        (1554, "Cricket", "89"),
        (1560, "Fantasy Sports", "90"),
        (1547, "Football", "91"),
        (1553, "Golf", "92"),
        (1550, "Hockey", "93"),
        (1552, "Rugby", "94"),
        (1551, "Running", "95"),
        (1546, "Soccer", "96"),
        (1558, "Swimming", "97"),
        (1556, "Tennis", "98"),
        (1557, "Volleyball", "99"),
        (1559, "Wilderness", "100"),
        (1555, "Wrestling", "101"),
    ]),
    (1309, "TV & Film", "104,105", [
        (1562, "After Shows", "106"),
        (1564, "Film History", "105"),
        (1565, "Film Interviews", "17"),
        (1563, "Film Reviews", "107"),
        (1561, "TV Reviews", "107"),
    ]),
    (1318, "Technology", "102", []),
    (1488, "True Crime", "103", []),
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
TRENDING_DAYS = 30          # what trended in the last month: a narrow category in one language has little in a day
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
    """Apple's chart for a country: overall, or for a category or subcategory (its older feed of charts: the
    newer one, rss.marketingtools.apple.com, often doesn't answer for 100)."""
    def fetch():
        with _client() as c:
            r = c.get(f"https://itunes.apple.com/{country}/rss/toppodcasts/limit={limit}{f'/genre={genre}' if genre else ''}/json")
            if r.status_code != 200:
                return []
            entries = r.json().get("feed", {}).get("entry", [])
        ids = [e["id"]["attributes"]["im:id"] for e in (entries if isinstance(entries, list) else [entries])]
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
    """What's trended on Podcast Index this month in these languages, in these of its categories (ids; or all)."""
    def fetch():
        params = {"max": 60, "lang": langs, "since": int(time.time()) - TRENDING_DAYS * 86400, **({"cat": cats} if cats else {})}
        return _pi_hits(_pi_get("/podcasts/trending", params).get("feeds") or [])
    return _kept(f"pi:{langs}:{cats}", PI_TTL, fetch)


def pi_search(q: str, most: int = 30) -> list[dict]:
    return _pi_hits(_pi_get("/search/byterm", {"q": q, "max": most}).get("feeds") or [])


def pi_about(topic: str) -> list[dict]:
    """Podcasts about a topic, by search (Podcast Index's own categories, which few feeds use)."""
    return _kept(f"pi-about:{topic}", PI_TTL, lambda: pi_search(topic.replace("-", " "), 60))


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
    if _pi_on() and isinstance(gid, str):
        jobs["podcastindex"] = lambda: pi_about(name)
    elif _pi_on() and (pi or not genre):
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
            sections.append({"source": src, "items": items, **({"about": name} if src == "podcastindex" and isinstance(gid, str) else {})})
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
