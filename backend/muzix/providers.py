"""Metadata and cover art from outside: what an admin compares a library item with when editing it.

MusicBrainz (with the Cover Art Archive), Deezer and iTunes need no account; Spotify is asked
through the admin's own linked account; Discogs (a personal token), fanart.tv (pictures found by
MusicBrainz id) and Brave Search (plain web images) use keys from the admin page. VGMdb isn't here:
its API mirror is gone and the site sits behind a bot check.

`search(kind, ...)` asks every source at once and returns what each found (or why it couldn't);
`details(source, kind, id)` fills in a picked result's track list; `covers(...)` gathers pictures.
"""

import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait

import httpx

from . import enrich, settings

log = logging.getLogger("muzix.providers")
TIMEOUT = 12
LIMIT = 8
_mb = enrich.RateLimited(1.0)      # MusicBrainz asks for one request a second
_mb_lock = threading.Lock()


class SourceError(Exception):
    pass


def _client() -> httpx.Client:
    return httpx.Client(headers={"User-Agent": enrich.UA}, timeout=TIMEOUT, follow_redirects=True)


def _year(date: str | None) -> int:
    m = re.match(r"(\d{4})", date or "")
    return int(m.group(1)) if m else 0


def _artists(credit) -> str:
    """MusicBrainz artist credits as one name ("A feat. B")."""
    return "".join(c.get("name", c.get("artist", {}).get("name", "")) + c.get("joinphrase", "") for c in credit or [])


def _get(c: httpx.Client, url: str, params: dict | None = None, mb: bool = False, **kw) -> dict:
    for attempt in range(3):
        if mb:
            with _mb_lock:
                _mb.wait()
        r = c.get(url, params=params, **kw)
        if not (mb and r.status_code == 503) or attempt == 2:
            break           # MusicBrainz says it's busy: a moment, then once more
        time.sleep(1.5 * (attempt + 1))
    if r.status_code in (401, 403):
        raise SourceError("refused the request")
    if r.status_code == 429:
        raise SourceError("asks to slow down; try again in a minute")
    r.raise_for_status()
    return r.json()


# ---------------------------------------------------------------- searching

def search(kind: str, artist: str = "", title: str = "", album: str = "", user=None, db=None) -> dict:
    """{results: [...], errors: {source: why}} for kind album | track | artist."""
    jobs = {"musicbrainz": _musicbrainz, "discogs": _discogs, "deezer": _deezer, "itunes": _itunes}
    if user is not None and db is not None:
        jobs["spotify"] = _spotify
    results, errors = [], {}
    with ThreadPoolExecutor(len(jobs)) as pool:
        futs = {pool.submit(fn, kind, artist, title, album, user, db): name for name, fn in jobs.items()}
        done, late = wait(futs, timeout=TIMEOUT + 8)
        for f in done:
            name = futs[f]
            try:
                results += f.result()
            except SourceError as e:
                errors[name] = str(e)
            except (httpx.HTTPError, ValueError, KeyError) as e:
                log.info("%s search failed: %r", name, e)
                errors[name] = "isn't answering right now"
        for f in late:
            errors[futs[f]] = "took too long to answer"
    return {"results": results, "errors": errors}


def _musicbrainz(kind, artist, title, album, user, db) -> list[dict]:
    def q(field, v):
        v = v.replace('"', "")
        return f'{field}:"{v}"' if v else ""
    out = []
    with _client() as c:
        if kind == "album":
            query = " AND ".join(x for x in (q("release", title), q("artist", artist)) if x)
            data = _get(c, "https://musicbrainz.org/ws/2/release", {"query": query, "fmt": "json", "limit": LIMIT}, mb=True)
            for r in data.get("releases", []):
                out.append({"source": "musicbrainz", "kind": "album", "id": r["id"], "title": r.get("title", ""),
                            "artist": _artists(r.get("artist-credit")), "year": _year(r.get("date")),
                            "tracks": r.get("track-count") or 0, "country": r.get("country", ""),
                            "label": ((r.get("label-info") or [{}])[0].get("label") or {}).get("name", ""),
                            "format": "+".join(m.get("format", "") for m in r.get("media", []) if m.get("format")),
                            "cover": f"https://coverartarchive.org/release/{r['id']}/front-250",
                            "url": f"https://musicbrainz.org/release/{r['id']}"})
        elif kind == "track":
            query = " AND ".join(x for x in (q("recording", title), q("artist", artist), q("release", album)) if x)
            data = _get(c, "https://musicbrainz.org/ws/2/recording", {"query": query, "fmt": "json", "limit": LIMIT}, mb=True)
            for r in data.get("recordings", []):
                rel = (r.get("releases") or [{}])[0]
                out.append({"source": "musicbrainz", "kind": "track", "id": r["id"], "title": r.get("title", ""),
                            "artist": _artists(r.get("artist-credit")), "album": rel.get("title", ""),
                            "year": _year(rel.get("date") or r.get("first-release-date")),
                            "length": round((r.get("length") or 0) / 1000),
                            "url": f"https://musicbrainz.org/recording/{r['id']}"})
        else:
            # unfielded: the name, its aliases ("Yuzo Koshiro" for 古代祐三) and sort name
            data = _get(c, "https://musicbrainz.org/ws/2/artist", {"query": (artist or title).replace('"', ""),
                                                                  "fmt": "json", "limit": LIMIT}, mb=True)
            for a in data.get("artists", []):
                out.append({"source": "musicbrainz", "kind": "artist", "id": a["id"], "title": a.get("name", ""),
                            "artist": a.get("disambiguation", ""), "country": a.get("country", ""),
                            "url": f"https://musicbrainz.org/artist/{a['id']}"})
    return out


def _deezer(kind, artist, title, album, user, db) -> list[dict]:
    # plain words rank better than Deezer's artist:"" album:"" syntax, which favours exact titles by anyone
    query = " ".join(x for x in ((artist, title) if kind != "artist" else (artist or title,)) if x)
    with _client() as c:
        data = _get(c, f"https://api.deezer.com/search/{kind}", {"q": query, "limit": LIMIT})
    if "error" in data:
        raise SourceError(data["error"].get("message", "error"))
    out = []
    for r in data.get("data", []):
        if kind == "album":
            out.append({"source": "deezer", "kind": "album", "id": str(r["id"]), "title": r.get("title", ""),
                        "artist": r.get("artist", {}).get("name", ""), "tracks": r.get("nb_tracks") or 0,
                        "cover": r.get("cover_medium"), "url": r.get("link", "")})
        elif kind == "track":
            out.append({"source": "deezer", "kind": "track", "id": str(r["id"]), "title": r.get("title", ""),
                        "artist": r.get("artist", {}).get("name", ""), "album": r.get("album", {}).get("title", ""),
                        "length": r.get("duration") or 0, "cover": r.get("album", {}).get("cover_medium"),
                        "url": r.get("link", "")})
        else:
            out.append({"source": "deezer", "kind": "artist", "id": str(r["id"]), "title": r.get("name", ""),
                        "cover": r.get("picture_medium"), "url": r.get("link", "")})
    return out


def _dc_name(name: str) -> str:
    """Discogs tells namesakes apart with a number: "Nirvana (2)"; an asterisk marks a name variation."""
    return re.sub(r"\s*\(\d+\)$", "", (name or "").strip().rstrip("*"))


def _dc_artists(artists) -> str:
    out = ""
    for a in artists or []:
        join = (a.get("join") or "").strip()
        out += _dc_name(a.get("anv") or a.get("name", "")) + (", " if join == "," else f" {join} " if join else ", ")
    return out.strip(" ,")


def _dc_get(c: httpx.Client, path: str, params: dict | None = None) -> dict:
    token = settings.get("discogs_token")
    if not token:
        raise SourceError("needs a personal access token on the admin page")
    return _get(c, f"https://api.discogs.com/{path}", params, headers={"Authorization": f"Discogs token={token}"})


def _dc_search(kind: str, artist: str, title: str, per_page: int = LIMIT) -> list[dict]:
    """Albums as masters (one per album, all its versions behind it), or releases when no master fits."""
    with _client() as c:
        if kind == "artist":
            return _dc_get(c, "database/search", {"type": "artist", "q": artist or title, "per_page": per_page})["results"]
        ask = {"artist": artist, "release_title": title} if artist and title else {"q": artist or title}
        found = _dc_get(c, "database/search", {"type": "master", **ask, "per_page": per_page})["results"]
        if len(found) < 3:
            found += _dc_get(c, "database/search", {"type": "release", **ask, "per_page": per_page})["results"]
        return found


def _dc_split(r: dict) -> tuple[str, str]:
    """A search result's "Artist - Album" title."""
    artist, _, album = r.get("title", "").partition(" - ")
    return (_dc_name(artist), album) if album else ("", artist)


def _discogs(kind, artist, title, album, user, db) -> list[dict]:
    if kind == "track":
        return []       # Discogs lists releases, not songs
    out = []
    for r in _dc_search(kind, artist, title):
        url = "https://www.discogs.com" + r.get("uri", "")
        if kind == "artist":
            out.append({"source": "discogs", "kind": "artist", "id": str(r["id"]), "title": _dc_name(r.get("title", "")),
                        "cover": r.get("thumb") or None, "url": url})
            continue
        name, album_title = _dc_split(r)
        out.append({"source": "discogs", "kind": "album", "id": f"{r['type']}/{r['id']}", "title": album_title,
                    "artist": name, "year": _year(r.get("year")), "genre": (r.get("genre") or [""])[0],
                    "country": r.get("country", ""), "label": (r.get("label") or [""])[0],
                    "format": ", ".join(dict.fromkeys(r.get("format") or [])), "cover": r.get("thumb") or None, "url": url})
    return out[:LIMIT]


def _dc_tracks(rows: list[dict], artist: str) -> list[dict]:
    """Discogs positions are A1, B2 on vinyl, 1-03 or CD2-3 on several discs: numbered again per disc."""
    out, count = [], {}
    for t in rows:
        if t.get("type_") not in ("track", "index"):
            continue        # side and section headings
        m = re.match(r"^(?:CD|DVD|Disc|D)?\s*(\d+)[-.](\d+)$", t.get("position", ""), re.I)
        disc = int(m.group(1)) if m else 1
        count[disc] = count.get(disc, 0) + 1
        parts = (t.get("duration") or "").split(":")       # "5:00", "1:02:03" or nothing
        length = sum(int(p) * 60 ** i for i, p in enumerate(reversed(parts))) if all(p.isdigit() for p in parts) else 0
        out.append({"disc": disc, "no": count[disc], "title": t.get("title", ""),
                    "artist": _dc_artists(t.get("artists")) or artist, "length": length})
    return out


def _art(url: str | None, size: int) -> str:
    """An iTunes artwork address at another size."""
    return re.sub(r"/\d+x\d+bb\.", f"/{size}x{size}bb.", url or "")


def _itunes(kind, artist, title, album, user, db) -> list[dict]:
    entity = {"album": "album", "track": "song", "artist": "musicArtist"}[kind]
    term = " ".join(x for x in (artist, title if kind != "artist" else "") if x)
    with _client() as c:
        data = _get(c, "https://itunes.apple.com/search", {"term": term, "entity": entity, "limit": LIMIT, "media": "music"})
    out = []
    for r in data.get("results", []):
        if kind == "album":
            out.append({"source": "itunes", "kind": "album", "id": str(r["collectionId"]), "title": r.get("collectionName", ""),
                        "artist": r.get("artistName", ""), "year": _year(r.get("releaseDate")),
                        "genre": r.get("primaryGenreName", ""), "tracks": r.get("trackCount") or 0,
                        "cover": _art(r.get("artworkUrl100"), 250), "url": r.get("collectionViewUrl", "")})
        elif kind == "track":
            out.append({"source": "itunes", "kind": "track", "id": str(r["trackId"]), "title": r.get("trackName", ""),
                        "artist": r.get("artistName", ""), "album": r.get("collectionName", ""),
                        "year": _year(r.get("releaseDate")), "genre": r.get("primaryGenreName", ""),
                        "no": r.get("trackNumber") or 0, "disc": r.get("discNumber") or 0,
                        "length": round((r.get("trackTimeMillis") or 0) / 1000),
                        "cover": _art(r.get("artworkUrl100"), 250), "url": r.get("trackViewUrl", "")})
        else:
            out.append({"source": "itunes", "kind": "artist", "id": str(r["artistId"]), "title": r.get("artistName", ""),
                        "genre": r.get("primaryGenreName", ""), "url": r.get("artistLinkUrl", "")})
    return out


def _spotify_token(user, db) -> str:
    from .api import spotify
    try:
        return spotify.token(db=db, user=user)["access_token"]
    except Exception as e:      # not linked, or the sign-in expired
        raise SourceError("isn't linked to this account" if "linked" in str(getattr(e, "detail", "")) else
                          "sign-in has expired; link it again") from e


def _spotify(kind, artist, title, album, user, db) -> list[dict]:
    token = _spotify_token(user, db)
    field = {"album": "album", "track": "track", "artist": "artist"}[kind]
    query = " ".join(x for x in ([f"artist:{artist}"] if artist and kind != "artist" else [])
                     + ([f"{field}:{title}"] if title and kind != "artist" else [artist or title]) if x)
    with _client() as c:
        data = _get(c, "https://api.spotify.com/v1/search", {"q": query, "type": kind, "limit": LIMIT},
                    headers={"Authorization": f"Bearer {token}"})
    out = []
    for r in data.get(f"{kind}s", {}).get("items", []):
        if not r:
            continue
        images = (r.get("album", r) if kind == "track" else r).get("images") or []
        cover = images[-2]["url"] if len(images) > 1 else images[0]["url"] if images else None
        names = ", ".join(a["name"] for a in r.get("artists", []))
        if kind == "album":
            out.append({"source": "spotify", "kind": "album", "id": r["id"], "title": r.get("name", ""), "artist": names,
                        "year": _year(r.get("release_date")), "tracks": r.get("total_tracks") or 0, "cover": cover,
                        "url": r.get("external_urls", {}).get("spotify", "")})
        elif kind == "track":
            out.append({"source": "spotify", "kind": "track", "id": r["id"], "title": r.get("name", ""), "artist": names,
                        "album": r.get("album", {}).get("name", ""), "year": _year(r.get("album", {}).get("release_date")),
                        "no": r.get("track_number") or 0, "disc": r.get("disc_number") or 0,
                        "length": round((r.get("duration_ms") or 0) / 1000), "cover": cover,
                        "url": r.get("external_urls", {}).get("spotify", "")})
        else:
            out.append({"source": "spotify", "kind": "artist", "id": r["id"], "title": r.get("name", ""), "cover": cover,
                        "url": r.get("external_urls", {}).get("spotify", "")})
    return out


def _fa_get(c: httpx.Client, path: str) -> dict:
    """fanart.tv with the admin's key: a project key, or a personal one. {} when it has nothing yet."""
    key = settings.get("fanarttv_api_key")
    if not key:
        raise SourceError("needs an API key on the admin page")
    for header in ("api-key", "client-key"):
        r = c.get(f"https://webservice.fanart.tv/v3/music/{path}", headers={header: key})
        if r.status_code != 401:
            break
    if r.status_code == 401:
        raise SourceError("doesn't accept the API key")
    if r.status_code == 404:
        return {}
    r.raise_for_status()
    return r.json()


def _fa_liked(rows) -> list[dict]:
    return sorted((p for p in rows or [] if p.get("url")), key=lambda p: -int(p.get("likes") or 0))


# ---------------------------------------------------------------- a picked album or artist, in full

def _artist(c: httpx.Client, source: str, id_: str, user, db) -> dict:
    """{name, cover}: an artist as one source has them, with its own picture of them (None when it has none).
    MusicBrainz has no pictures; fanart.tv has them by its ids, when the admin has a key."""
    if source == "musicbrainz":
        r = _get(c, f"https://musicbrainz.org/ws/2/artist/{id_}", {"fmt": "json"}, mb=True)
        cover = None
        if settings.get("fanarttv_api_key"):
            try:
                cover = next((p["url"] for p in _fa_liked(_fa_get(c, id_).get("artistthumb"))), None)
            except (SourceError, httpx.HTTPError, ValueError):
                pass        # the name without a picture is still worth having
        return {"name": r.get("name", ""), "cover": cover, "mbid": id_}
    if source == "discogs":
        if not id_.isdigit():
            raise SourceError("doesn't know that artist")
        r = _dc_get(c, f"artists/{id_}")
        images = r.get("images") or []
        front = next((i for i in images if i.get("type") == "primary"), images[0] if images else {})
        return {"name": _dc_name(r.get("name", "")), "cover": front.get("uri") or None}
    if source == "deezer":
        r = _get(c, f"https://api.deezer.com/artist/{id_}")
        if "error" in r:
            raise SourceError(r["error"].get("message", "error"))
        cover = r.get("picture_xl") or None
        return {"name": r.get("name", ""), "cover": None if cover and "/artist//" in cover else cover}   # its blank face
    if source == "spotify":
        token = _spotify_token(user, db)
        r = _get(c, f"https://api.spotify.com/v1/artists/{id_}", headers={"Authorization": f"Bearer {token}"})
        return {"name": r.get("name", ""), "cover": (r.get("images") or [{}])[0].get("url")}
    if source == "itunes":
        r = _get(c, "https://itunes.apple.com/lookup", {"id": id_})
        return {"name": (r.get("results") or [{}])[0].get("artistName", ""), "cover": None}
    raise SourceError(f"unknown source {source}")


def details(source: str, kind: str, id_: str, user=None, db=None) -> dict:
    """An album's fields and track list from one source: {title, artist, year, genre, tracks: [...], cover},
    where cover is the source's own picture of it at full size (None when it has none). An artist: {name, cover}."""
    if kind not in ("album", "artist"):
        raise SourceError("only albums and artists have details")
    with _client() as c:
        if kind == "artist":
            return _artist(c, source, id_, user, db)
        if source == "musicbrainz":
            r = _get(c, f"https://musicbrainz.org/ws/2/release/{id_}",
                     {"inc": "recordings+artist-credits+genres+release-groups", "fmt": "json"}, mb=True)
            genres = sorted(r.get("genres") or r.get("release-group", {}).get("genres") or [], key=lambda g: -g.get("count", 0))
            tracks = [{"disc": m.get("position") or 1, "no": t.get("position") or 0, "title": t.get("title", ""),
                       "artist": _artists(t.get("artist-credit")), "length": round((t.get("length") or 0) / 1000)}
                      for m in r.get("media", []) for t in m.get("tracks", [])]
            cover = None
            if (r.get("cover-art-archive") or {}).get("front"):
                try:
                    art = _get(c, f"https://coverartarchive.org/release/{r['id']}")
                    front = next((i for i in art.get("images", []) if i.get("front")), None)
                    cover = front and ((front.get("thumbnails") or {}).get("1200") or front.get("image"))
                except httpx.HTTPError:
                    pass        # the album without its cover is still worth having
            return {"title": r.get("title", ""), "artist": _artists(r.get("artist-credit")), "year": _year(r.get("date")),
                    "genre": genres[0]["name"].title() if genres else "", "tracks": tracks, "mbid": r["id"], "cover": cover}
        if source == "discogs":
            what, _, num = id_.partition("/")
            if what not in ("master", "release") or not num.isdigit():
                raise SourceError("doesn't know that album")
            r = _dc_get(c, f"{what}s/{num}")
            artist = _dc_artists(r.get("artists"))
            images = r.get("images") or []
            front = next((i for i in images if i.get("type") == "primary"), images[0] if images else {})
            return {"title": r.get("title", ""), "artist": artist, "year": _year(str(r.get("year") or "")),
                    "genre": (r.get("genres") or [""])[0], "tracks": _dc_tracks(r.get("tracklist") or [], artist),
                    "cover": front.get("uri") or None}
        if source == "deezer":
            r = _get(c, f"https://api.deezer.com/album/{id_}")
            data = r.get("tracks", {}).get("data", [])
            tracks = [{"disc": t.get("disk_number") or 1, "no": t.get("track_position") or i + 1, "title": t.get("title", ""),
                       "artist": t.get("artist", {}).get("name", ""), "length": t.get("duration") or 0}
                      for i, t in enumerate(data)]
            genres = r.get("genres", {}).get("data", [])
            return {"title": r.get("title", ""), "artist": r.get("artist", {}).get("name", ""),
                    "year": _year(r.get("release_date")), "genre": genres[0]["name"] if genres else "", "tracks": tracks,
                    "cover": r.get("cover_xl") or None}
        if source == "itunes":
            r = _get(c, "https://itunes.apple.com/lookup", {"id": id_, "entity": "song"})
            rows = r.get("results", [])
            head = next((x for x in rows if x.get("wrapperType") == "collection"), {})
            tracks = [{"disc": x.get("discNumber") or 1, "no": x.get("trackNumber") or 0, "title": x.get("trackName", ""),
                       "artist": x.get("artistName", ""), "length": round((x.get("trackTimeMillis") or 0) / 1000)}
                      for x in rows if x.get("wrapperType") == "track"]
            return {"title": head.get("collectionName", ""), "artist": head.get("artistName", ""),
                    "year": _year(head.get("releaseDate")), "genre": head.get("primaryGenreName", ""), "tracks": tracks,
                    "cover": _art(head.get("artworkUrl100"), 1400) or None}
        if source == "spotify":
            token = _spotify_token(user, db)
            r = _get(c, f"https://api.spotify.com/v1/albums/{id_}", headers={"Authorization": f"Bearer {token}"})
            tracks = [{"disc": t.get("disc_number") or 1, "no": t.get("track_number") or 0, "title": t.get("name", ""),
                       "artist": ", ".join(a["name"] for a in t.get("artists", [])),
                       "length": round((t.get("duration_ms") or 0) / 1000)} for t in r.get("tracks", {}).get("items", [])]
            return {"title": r.get("name", ""), "artist": ", ".join(a["name"] for a in r.get("artists", [])),
                    "year": _year(r.get("release_date")), "genre": "", "tracks": tracks,
                    "cover": (r.get("images") or [{}])[0].get("url")}
    raise SourceError(f"unknown source {source}")


# ---------------------------------------------------------------- cover art

def covers(kind: str, artist: str = "", title: str = "", web: str = "", user=None, db=None, mbid: str = "") -> dict:
    """{results: [{source, thumb, url, title, width, height}], errors} for kind album | artist | book | podcast.
    Pictures from the music sources (albums and artists), and web images when `web` is a query.
    `mbid` is the item's own MusicBrainz id (an album's release, an artist), when its tags have one."""
    out, errors = [], {}
    music = kind in ("album", "artist")

    def mb():
        found = []
        if kind != "album":
            return found
        for r in _musicbrainz("album", artist, title, "", None, None)[:4]:
            with _client() as c:
                try:
                    data = _get(c, f"https://coverartarchive.org/release/{r['id']}")
                except httpx.HTTPStatusError:
                    continue        # no art for this release
            for img in data.get("images", []):
                if img.get("front"):
                    found.append({"source": "Cover Art Archive", "thumb": img["thumbnails"].get("250") or img["image"],
                                  "url": img["image"], "title": f"{r['title']} ({r['year'] or '?'}, {r['country'] or '?'})"})
        return found

    def dz():
        rows = _deezer(kind, artist, title, "", None, None)
        return [{"source": "Deezer", "thumb": r["cover"], "url": re.sub(r"/\d+x\d+-", "/1000x1000-", r["cover"] or ""),
                 "title": f"{r['title']}" + (f" · {r['artist']}" if r.get("artist") else ""), "width": 1000, "height": 1000}
                for r in rows if r.get("cover")]

    def it():
        if kind != "album":
            return []
        return [{"source": "iTunes", "thumb": r["cover"], "url": _art(r["cover"], 1400), "title": f"{r['title']} · {r['artist']}",
                 "width": 1400, "height": 1400} for r in _itunes("album", artist, title, "", None, None) if r.get("cover")]

    def dc():
        found = []
        for r in _dc_search(kind, artist, title, per_page=12):
            if not r.get("cover_image") or r["cover_image"].endswith("/spacer.gif"):
                continue
            if kind == "artist":
                label = _dc_name(r.get("title", ""))
            else:
                bits = [r.get("year"), r.get("country"), ", ".join(dict.fromkeys(r.get("format") or []))[:30]]
                label = f"{_dc_split(r)[1]} ({', '.join(b for b in bits if b) or '?'})"
            found.append({"source": "Discogs", "thumb": r.get("thumb") or r["cover_image"], "url": r["cover_image"],
                          "title": label})
        return found[:12]

    def fa():
        if not settings.get("fanarttv_api_key"):
            raise SourceError("needs an API key on the admin page")
        with _client() as c:
            ask = lambda path: _fa_get(c, path)

            def pictures(rows, label):
                return [{"source": "fanart.tv", "thumb": p["url"].replace("/fanart/", "/preview/", 1), "url": p["url"],
                         "title": label, "width": 1000, "height": 1000} for p in _fa_liked(rows)]

            if kind == "artist":
                aid = mbid
                if not aid:     # the namesake MusicBrainz ranks first, unless one is spelled exactly so
                    named = _musicbrainz("artist", artist, "", "", None, None)
                    aid = next((a["id"] for a in named if a["title"].casefold() == artist.casefold()),
                               named[0]["id"] if named else "")
                data = ask(aid) if aid else {}
                return pictures(data.get("artistthumb"), data.get("name") or artist)
            # fanart.tv files covers under the release group, the album over all its editions
            groups = []
            if mbid:
                r = _get(c, f"https://musicbrainz.org/ws/2/release/{mbid}", {"inc": "release-groups", "fmt": "json"}, mb=True)
                groups = [r["release-group"]["id"]] if r.get("release-group") else []
            if not groups:
                v = lambda x: x.replace('"', "")
                query = " AND ".join(x for x in (f'releasegroup:"{v(title)}"' if title else "",
                                                 f'artist:"{v(artist)}"' if artist else "") if x)
                r = _get(c, "https://musicbrainz.org/ws/2/release-group", {"query": query, "fmt": "json", "limit": 3}, mb=True)
                groups = [g["id"] for g in r.get("release-groups", []) if (g.get("score") or 0) >= 90][:2]
            found = []
            for g in groups:
                data = ask(f"albums/{g}")
                found += pictures(((data.get("albums") or {}).get(g) or {}).get("albumcover"), title)
            return found

    def sp():
        rows = _spotify(kind, artist, title, "", user, db)
        return [{"source": "Spotify", "thumb": r["cover"], "url": r["cover"], "title": r["title"]} for r in rows if r.get("cover")]

    def brave():
        key = settings.get("brave_api_key")
        if not key:
            raise SourceError("needs a Brave Search API key on the admin page")
        with _client() as c:
            data = _get(c, "https://api.search.brave.com/res/v1/images/search",
                        {"q": web, "count": 40, "safesearch": "strict"},
                        headers={"X-Subscription-Token": key, "Accept": "application/json"})
        found = []
        for r in data.get("results", []):
            props, thumb = r.get("properties") or {}, r.get("thumbnail") or {}
            url = props.get("url") or thumb.get("src")
            if not url:
                continue
            found.append({"source": "Web", "thumb": thumb.get("src") or url, "url": url, "title": r.get("title", ""),
                          "page": r.get("url", ""), "width": props.get("width") or thumb.get("width"),
                          "height": props.get("height") or thumb.get("height")})
        return found

    jobs = {}
    if music:
        jobs.update({"musicbrainz": mb, "fanarttv": fa, "discogs": dc, "deezer": dz, "itunes": it})
        if user is not None and db is not None:
            jobs["spotify"] = sp
    if web:
        jobs["web"] = brave
    with ThreadPoolExecutor(max(1, len(jobs))) as pool:
        futs = {pool.submit(fn): name for name, fn in jobs.items()}
        done, late = wait(futs, timeout=TIMEOUT + 15)
        for f in done:
            try:
                out += f.result()
            except SourceError as e:
                errors[futs[f]] = str(e)
            except (httpx.HTTPError, ValueError, KeyError) as e:
                log.info("%s covers failed: %r", futs[f], e)
                errors[futs[f]] = "isn't answering right now"
        for f in late:
            errors[futs[f]] = "took too long to answer"
    return {"results": out, "errors": errors}
