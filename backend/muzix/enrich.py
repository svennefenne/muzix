"""Detailed genre tags per artist ("death metal", "goa trance"...), used to pick genre skins.

Sources: MusicBrainz (no key needed; 1 request per second) or Last.fm (needs
an API key). Artists are refreshed every 90 days.
"""

import re
import time
from collections import Counter
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import delete, func, or_, select, text

from . import __version__, db, jobs, settings, tagging
from .models import Album, Artist, BandcampTags

UA = f"Muzix/{__version__} ( https://github.com/svennefenne/muzix )"
REFRESH = timedelta(days=90)


class RateLimited:
    def __init__(self, per_second=1.0):
        self.gap = 1.0 / per_second
        self.last = 0.0

    def wait(self):
        delay = self.last + self.gap - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        self.last = time.monotonic()


def _get(client: httpx.Client, limiter: RateLimited, url: str, params: dict) -> httpx.Response:
    """GET with a polite retry when MusicBrainz says it's busy (503)."""
    for attempt in range(4):
        limiter.wait()
        r = client.get(url, params=params)
        if r.status_code != 503:
            return r
        time.sleep(2 * (attempt + 1))
    return r


def mb_tags(client: httpx.Client, limiter: RateLimited, name: str, mbid: str) -> tuple[list, str]:
    if not mbid:
        r = _get(client, limiter, "https://musicbrainz.org/ws/2/artist",
                 {"query": f'artist:"{name}"', "limit": 3, "fmt": "json"})
        r.raise_for_status()
        for cand in r.json().get("artists", []):
            if cand.get("score", 0) >= 95 and cand.get("name", "").casefold() == name.casefold():
                mbid = cand["id"]
                break
        if not mbid:
            return [], ""
    r = _get(client, limiter, f"https://musicbrainz.org/ws/2/artist/{mbid}", {"inc": "genres+tags", "fmt": "json"})
    if r.status_code == 404:
        return [], mbid
    r.raise_for_status()
    data = r.json()
    counts: dict[str, int] = {}
    for g in data.get("genres", []):
        counts[g["name"]] = counts.get(g["name"], 0) + g.get("count", 1) * 2
    for t in data.get("tags", []):
        counts[t["name"]] = counts.get(t["name"], 0) + t.get("count", 1)
    tags = sorted(([k, v] for k, v in counts.items() if v > 0), key=lambda kv: -kv[1])
    return tags[:15], mbid


def lastfm_tags(client: httpx.Client, limiter: RateLimited, name: str, key: str) -> list:
    limiter.wait()
    r = client.get("https://ws.audioscrobbler.com/2.0/", params={
        "method": "artist.gettoptags", "artist": name, "api_key": key, "format": "json", "autocorrect": 1})
    r.raise_for_status()
    tags = r.json().get("toptags", {}).get("tag", [])
    return [[t["name"].lower(), int(t.get("count", 0))] for t in tags if int(t.get("count", 0)) >= 10][:15]


def keep_bandcamp_tags(albums: list[dict]):
    """Bandcamp's tags of albums just filed (import_watched: each album's "tags"), for their artists' genre tags
    when MusicBrainz has none: an artist looked up already without any is looked up again."""
    albums = [a for a in albums if a.get("tags") and a.get("artist")]
    if not albums:
        return
    with db.session() as s:
        for a in albums:
            s.execute(delete(BandcampTags).where(func.casefold(BandcampTags.artist) == a["artist"].casefold(),
                                                 func.casefold(BandcampTags.album) == (a.get("album") or "").casefold()))
            s.add(BandcampTags(artist=a["artist"], album=a.get("album") or "", tags=a["tags"]))
            for artist in s.scalars(select(Artist).where(func.casefold(Artist.name) == a["artist"].casefold())):
                if not (artist.source_tags or artist.tags):
                    artist.tags_checked = None


# Bandcamp's tags that say an album is psytrance (as musicorg.PSY_TAG has them for the main genre)
PSY_TAG = re.compile(r"psytrance|psy-trance|psychedelic trance|psychedelic goa|\bgoa\b|goa ?trance|full[ -]?on|"
                     r"dark ?psy|forest ?psy|psychill|psy ?chill|psybient|psydub|hi-?tech|\bpsy\b", re.IGNORECASE)


def bandcamp_artist_tags(s, name: str) -> list:
    """An artist's genre tags from Bandcamp's tags of their albums: [[tag, how many of their albums have it],
    ...], the most albums' first, then in Bandcamp's own order (its genre and sub-genres before the free tags);
    "psytrance" first when Bandcamp tags their albums psytrance (it's their genre, and picks the psytrance skin)."""
    counts: Counter = Counter()
    first: dict[str, int] = {}
    psy = False
    for tags in s.scalars(select(BandcampTags.tags).where(func.casefold(BandcampTags.artist) == name.casefold())):
        for i, t in enumerate(dict.fromkeys(x.lower() for x in tags or [])):
            counts[t] += 1
            first[t] = min(first.get(t, i), i)
        psy = psy or any(PSY_TAG.search(t) for t in tags or [])
    if psy:
        counts["psytrance"], first["psytrance"] = max(counts.values()) + 1, -1
    return sorted(([k, v] for k, v in counts.items()), key=lambda kv: (-kv[1], first.get(kv[0], 99), kv[0]))[:15]


@jobs.job("artist_tags")
def artist_tags(ctx: jobs.JobContext, limit: int = 5000):
    source = settings.get("artist_tags")
    if source == "off":
        ctx.log("turned off in settings")
        return
    key = settings.get("lastfm_api_key")
    if source == "lastfm" and not key:
        ctx.log("Last.fm needs an API key; using MusicBrainz")
        source = "musicbrainz"
    cutoff = datetime.now(timezone.utc) - REFRESH
    with db.session() as s:
        rows = s.execute(
            select(Artist.id, Artist.name, Artist.mbid, func.count(Album.id).label("n"))
            .join(Album, Album.artist_id == Artist.id)
            .where(Album.kind == "music", or_(Artist.tags_checked.is_(None), Artist.tags_checked < cutoff))
            .group_by(Artist.id).order_by(text("n DESC")).limit(limit)).all()
        # MusicBrainz artist ids already in the files' tags
        known = dict(s.execute(text(
            "SELECT artist_id, coalesce(json_extract(extra, '$.albumartist_mbid'), json_extract(extra, '$.artist_mbid')) "
            "FROM tracks WHERE artist_id IS NOT NULL AND (json_extract(extra, '$.albumartist_mbid') IS NOT NULL "
            "OR json_extract(extra, '$.artist_mbid') IS NOT NULL) GROUP BY artist_id")).all())
    ctx.log(f"{len(rows)} artists to look up via {source}")
    limiter = RateLimited(1.0 if source == "musicbrainz" else 4.0)
    found = 0
    with httpx.Client(headers={"User-Agent": UA}, timeout=20) as client:
        for i, (aid, name, mbid, _) in enumerate(rows):
            ctx.check()
            if name.casefold() in ("various artists", "[unknown]"):
                tags, mbid2 = [], mbid
            else:
                try:
                    if source == "lastfm":
                        tags, mbid2 = lastfm_tags(client, limiter, name, key), mbid
                    else:
                        tags, mbid2 = mb_tags(client, limiter, name, mbid or (known.get(aid) or "").split(";")[0])
                except httpx.HTTPError as e:
                    ctx.log(f"{name}: {e}")
                    time.sleep(5)
                    continue
            with db.session() as s:
                a = s.get(Artist, aid)
                if a is not None:
                    tags = tags or bandcamp_artist_tags(s, name)        # none there: Bandcamp's, if it has the albums
                    a.source_tags, a.mbid = tags, mbid2 or a.mbid
                    a.tags_checked = datetime.now(timezone.utc)
                    tagging.apply(a, tagging.Rules(s))     # the admin's rules (Admin → Tags)
            found += bool(tags)
            if i % 20 == 0:
                ctx.update(i / max(1, len(rows)), f"{i}/{len(rows)} artists, {found} with genres")
    ctx.log(f"done: {found} of {len(rows)} artists got genre tags")
    return {"checked": len(rows), "found": found}
