"""Metadata and cover art from outside: what an admin compares a library item with when editing it.

MusicBrainz (with the Cover Art Archive), Deezer and iTunes need no account; Spotify is asked
through the admin's own linked account; Brave Search finds plain web images with an API key from
the admin page. VGMdb isn't here: its API mirror is gone and the site sits behind a bot check.

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
    jobs = {"musicbrainz": _musicbrainz, "deezer": _deezer, "itunes": _itunes}
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


# ---------------------------------------------------------------- a picked album, in full

def details(source: str, kind: str, id_: str, user=None, db=None) -> dict:
    """An album's fields and track list from one source: {title, artist, year, genre, tracks: [...]}."""
    if kind != "album":
        raise SourceError("only albums have details")
    with _client() as c:
        if source == "musicbrainz":
            r = _get(c, f"https://musicbrainz.org/ws/2/release/{id_}",
                     {"inc": "recordings+artist-credits+genres+release-groups", "fmt": "json"}, mb=True)
            genres = sorted(r.get("genres") or r.get("release-group", {}).get("genres") or [], key=lambda g: -g.get("count", 0))
            tracks = [{"disc": m.get("position") or 1, "no": t.get("position") or 0, "title": t.get("title", ""),
                       "artist": _artists(t.get("artist-credit")), "length": round((t.get("length") or 0) / 1000)}
                      for m in r.get("media", []) for t in m.get("tracks", [])]
            return {"title": r.get("title", ""), "artist": _artists(r.get("artist-credit")), "year": _year(r.get("date")),
                    "genre": genres[0]["name"].title() if genres else "", "tracks": tracks, "mbid": r["id"]}
        if source == "deezer":
            r = _get(c, f"https://api.deezer.com/album/{id_}")
            data = r.get("tracks", {}).get("data", [])
            tracks = [{"disc": t.get("disk_number") or 1, "no": t.get("track_position") or i + 1, "title": t.get("title", ""),
                       "artist": t.get("artist", {}).get("name", ""), "length": t.get("duration") or 0}
                      for i, t in enumerate(data)]
            genres = r.get("genres", {}).get("data", [])
            return {"title": r.get("title", ""), "artist": r.get("artist", {}).get("name", ""),
                    "year": _year(r.get("release_date")), "genre": genres[0]["name"] if genres else "", "tracks": tracks}
        if source == "itunes":
            r = _get(c, "https://itunes.apple.com/lookup", {"id": id_, "entity": "song"})
            rows = r.get("results", [])
            head = next((x for x in rows if x.get("wrapperType") == "collection"), {})
            tracks = [{"disc": x.get("discNumber") or 1, "no": x.get("trackNumber") or 0, "title": x.get("trackName", ""),
                       "artist": x.get("artistName", ""), "length": round((x.get("trackTimeMillis") or 0) / 1000)}
                      for x in rows if x.get("wrapperType") == "track"]
            return {"title": head.get("collectionName", ""), "artist": head.get("artistName", ""),
                    "year": _year(head.get("releaseDate")), "genre": head.get("primaryGenreName", ""), "tracks": tracks}
        if source == "spotify":
            token = _spotify_token(user, db)
            r = _get(c, f"https://api.spotify.com/v1/albums/{id_}", headers={"Authorization": f"Bearer {token}"})
            tracks = [{"disc": t.get("disc_number") or 1, "no": t.get("track_number") or 0, "title": t.get("name", ""),
                       "artist": ", ".join(a["name"] for a in t.get("artists", [])),
                       "length": round((t.get("duration_ms") or 0) / 1000)} for t in r.get("tracks", {}).get("items", [])]
            return {"title": r.get("name", ""), "artist": ", ".join(a["name"] for a in r.get("artists", [])),
                    "year": _year(r.get("release_date")), "genre": "", "tracks": tracks}
    raise SourceError(f"unknown source {source}")


# ---------------------------------------------------------------- cover art

def covers(kind: str, artist: str = "", title: str = "", web: str = "", user=None, db=None) -> dict:
    """{results: [{source, thumb, url, title, width, height}], errors} for kind album | artist | book | podcast.
    Pictures from the music sources (albums and artists), and web images when `web` is a query."""
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
        jobs.update({"musicbrainz": mb, "deezer": dz, "itunes": it})
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
