import os
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from xml.sax.saxutils import escape

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import jobs, podcasts, settings
from ..db import get_db
from ..models import Episode, EpisodeProgress, Feed, Subscription, User
from ..security import current_user, stream_user
from .proxy import check_url, relay

router = APIRouter(prefix="/api/podcasts", tags=["podcasts"])


def feed_json(f: Feed, sub: Subscription | None = None, unplayed: int | None = None, new: bool = False):
    return {"id": f.id, "url": f.url, "title": f.title or f.url, "author": f.author,
            "description": f.description, "image": f.image, "link": f.link, "categories": f.categories,
            "error": f.error, "subscribed": sub is not None,
            "auto_download": bool(sub and sub.auto_download), "unplayed": unplayed, "new": new,
            "last_checked": f.last_checked.isoformat() if f.last_checked else None}


def episode_json(e: Episode, prog: EpisodeProgress | None, feed: Feed | None = None, sub: Subscription | None = None):
    return {"id": e.id, "feed_id": e.feed_id, "title": e.title, "description": e.description,
            "published": e.published.isoformat() if e.published else None, "duration": e.duration,
            "image": e.image or (feed.image if feed else ""), "downloaded": bool(e.local_path),
            "position": prog.position if prog else 0, "finished": bool(prog and prog.finished),
            "new": is_new(e, sub, prog), "stream": f"/api/podcasts/episodes/{e.id}/stream",
            "feed_title": feed.title if feed else None}


# Spotify's blue dot: an episode that came out after you subscribed is new until you start it,
# and a podcast is marked while one of those has come in since you last opened its page

def _utc(d: datetime) -> datetime:
    """As SQLite gives it back: UTC without a zone."""
    return d.astimezone(timezone.utc).replace(tzinfo=None) if d.tzinfo else d


def is_new(e: Episode, sub: Subscription | None, prog: EpisodeProgress | None) -> bool:
    out = e.published or e.added_at
    return sub is not None and prog is None and out is not None and _utc(out) > _utc(sub.created_at)


def fresh_feeds(db: Session, user_id: int) -> set[int]:
    """The subscribed podcasts with a new episode the user hasn't seen on their page."""
    came = func.coalesce(Episode.added_at, Episode.published)     # when Muzix first read it
    return set(db.scalars(
        select(Episode.feed_id).distinct()
        .join(Subscription, (Subscription.feed_id == Episode.feed_id) & (Subscription.user_id == user_id))
        .outerjoin(EpisodeProgress, (EpisodeProgress.episode_id == Episode.id) & (EpisodeProgress.user_id == user_id))
        .where(EpisodeProgress.episode_id.is_(None),
               func.coalesce(Episode.published, Episode.added_at) > Subscription.created_at,
               came > func.coalesce(Subscription.seen_at, Subscription.created_at))))


@router.get("")
def subscriptions(db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = db.execute(select(Feed, Subscription).join(Subscription, Subscription.feed_id == Feed.id)
                      .where(Subscription.user_id == user.id).order_by(func.lower(Feed.title))).all()
    fresh = fresh_feeds(db, user.id)
    out = []
    for f, sub in rows:
        unplayed = db.scalar(select(func.count()).select_from(Episode).outerjoin(
            EpisodeProgress, (EpisodeProgress.episode_id == Episode.id) & (EpisodeProgress.user_id == user.id))
            .where(Episode.feed_id == f.id, func.coalesce(EpisodeProgress.finished, False).is_(False)))
        out.append(feed_json(f, sub, unplayed, f.id in fresh))
    return out


@router.get("/latest")
def latest(db: Session = Depends(get_db), user: User = Depends(current_user), limit: int = 40):
    rows = db.execute(select(Episode, Feed, EpisodeProgress, Subscription)
                      .join(Feed, Feed.id == Episode.feed_id)
                      .join(Subscription, (Subscription.feed_id == Feed.id) & (Subscription.user_id == user.id))
                      .outerjoin(EpisodeProgress, (EpisodeProgress.episode_id == Episode.id)
                                 & (EpisodeProgress.user_id == user.id))
                      .order_by(Episode.published.desc()).limit(limit)).all()
    return [episode_json(e, p, f, sub) for e, f, p, sub in rows]


class SubscribeBody(BaseModel):
    url: str


@router.post("/open")
def open_podcast(body: SubscribeBody, user: User = Depends(current_user)):
    """A podcast's page without subscribing: its feed is read so the episodes can be played."""
    check_url(body.url)
    try:
        return {"id": podcasts.open_feed(body.url.strip())}
    except (httpx.HTTPError, ValueError) as e:
        raise HTTPException(400, f"Couldn't read that feed: {e}")


@router.post("")
def subscribe(body: SubscribeBody, user: User = Depends(current_user)):
    check_url(body.url)
    try:
        f = podcasts.subscribe(body.url.strip(), user.id)
    except (httpx.HTTPError, ValueError) as e:
        raise HTTPException(400, f"Couldn't read that feed: {e}")
    return {"id": f.id}


@router.get("/search")
def search(q: str, user: User = Depends(current_user)):
    country = (settings.get("radio_country") or "US").lower()
    r = httpx.get("https://itunes.apple.com/search", params={
        "media": "podcast", "term": q, "limit": 30, "country": country}, timeout=15)
    r.raise_for_status()
    return [{"title": x.get("collectionName"), "author": x.get("artistName"), "url": x.get("feedUrl"),
             "image": x.get("artworkUrl600") or x.get("artworkUrl100"), "genre": x.get("primaryGenreName")}
            for x in r.json().get("results", []) if x.get("feedUrl")]


# Apple Podcasts' categories, for browsing
GENRES = [(1301, "Arts"), (1321, "Business"), (1303, "Comedy"), (1304, "Education"), (1483, "Fiction"),
          (1511, "Government"), (1512, "Health & Fitness"), (1487, "History"), (1305, "Kids & Family"),
          (1502, "Leisure"), (1310, "Music"), (1489, "News"), (1314, "Religion & Spirituality"), (1533, "Science"),
          (1324, "Society & Culture"), (1545, "Sports"), (1318, "Technology"), (1488, "True Crime"), (1309, "TV & Film")]


@router.get("/genres")
def genres(user: User = Depends(current_user)):
    return [{"id": i, "name": n} for i, n in GENRES]


@router.get("/top")
def top(genre: int | None = None, user: User = Depends(current_user)):
    """The charts for this server's country: overall, or for one category."""
    country = (settings.get("radio_country") or "us").lower()
    if genre:
        r = httpx.get(f"https://itunes.apple.com/{country}/rss/toppodcasts/limit=50/genre={genre}/json",
                      timeout=15, follow_redirects=True)
        if r.status_code != 200:
            return []
        entries = r.json().get("feed", {}).get("entry", [])
        ids = [e["id"]["attributes"]["im:id"] for e in (entries if isinstance(entries, list) else [entries])]
    else:
        r = httpx.get(f"https://rss.marketingtools.apple.com/api/v2/{country}/podcasts/top/30/podcasts.json",
                      timeout=15, follow_redirects=True)
        if r.status_code != 200:
            return []
        ids = [x["id"] for x in r.json().get("feed", {}).get("results", [])]
    if not ids:
        return []
    look = httpx.get("https://itunes.apple.com/lookup", params={"id": ",".join(ids), "entity": "podcast"}, timeout=15)
    return [{"title": x.get("collectionName"), "author": x.get("artistName"), "url": x.get("feedUrl"),
             "image": x.get("artworkUrl600"), "genre": x.get("primaryGenreName")}
            for x in look.json().get("results", []) if x.get("feedUrl")]


@router.get("/{feed_id}")
def feed(feed_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    f = db.get(Feed, feed_id)
    if f is None:
        raise HTTPException(404, "No such podcast")
    rows = db.execute(select(Episode, EpisodeProgress).outerjoin(
        EpisodeProgress, (EpisodeProgress.episode_id == Episode.id) & (EpisodeProgress.user_id == user.id))
        .where(Episode.feed_id == feed_id).order_by(Episode.published.desc()).limit(500)).all()
    sub = db.get(Subscription, (user.id, feed_id))
    return {**feed_json(f, sub), "episodes": [episode_json(e, p, sub=sub) for e, p in rows]}


@router.post("/{feed_id}/seen")
def seen(feed_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """The podcast's page was opened: its dot in the library goes (its new episodes keep theirs)."""
    sub = db.get(Subscription, (user.id, feed_id))
    if sub is not None:
        sub.seen_at = datetime.now(timezone.utc)
        db.commit()
    return {"ok": True}


class SubSettings(BaseModel):
    auto_download: bool


@router.put("/{feed_id}/subscription")
def sub_settings(feed_id: int, body: SubSettings, db: Session = Depends(get_db), user: User = Depends(current_user)):
    sub = db.get(Subscription, (user.id, feed_id))
    if sub is None:
        raise HTTPException(404, "Not subscribed")
    sub.auto_download = body.auto_download
    db.commit()
    return {"ok": True}


@router.delete("/{feed_id}")
def unsubscribe(feed_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    sub = db.get(Subscription, (user.id, feed_id))
    if sub is not None:
        db.delete(sub)
        db.commit()
    return {"ok": True}


@router.post("/refresh")
def refresh(user: User = Depends(current_user)):
    return {"job_id": jobs.submit("refresh_feeds", "Refresh podcasts")}


@router.get("/episodes/{episode_id}/stream")
async def episode_stream(episode_id: int, request: Request, db: Session = Depends(get_db),
                         user: User = Depends(stream_user)):
    e = db.get(Episode, episode_id)
    if e is None:
        raise HTTPException(404, "No such episode")
    if e.local_path and os.path.exists(e.local_path):
        return FileResponse(e.local_path)
    return await relay(e.audio_url, request)


@router.post("/episodes/{episode_id}/download")
def download(episode_id: int, user: User = Depends(current_user)):
    return {"job_id": jobs.submit("download_episode", "Download episode", episode_id=episode_id,
                                  _allow_parallel=True)}


class Progress(BaseModel):
    position: float
    finished: bool = False


@router.put("/episodes/{episode_id}/progress")
def progress(episode_id: int, body: Progress, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if db.get(Episode, episode_id) is None:
        raise HTTPException(404, "No such episode")
    row = db.get(EpisodeProgress, (user.id, episode_id)) or EpisodeProgress(user_id=user.id, episode_id=episode_id)
    row.position, row.finished, row.updated_at = body.position, body.finished, datetime.now(timezone.utc)
    db.merge(row)
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- OPML

@router.get("/opml/export")
def opml_export(db: Session = Depends(get_db), user: User = Depends(current_user)):
    feeds = db.scalars(select(Feed).join(Subscription, Subscription.feed_id == Feed.id)
                       .where(Subscription.user_id == user.id)).all()
    body = "\n".join(f'    <outline type="rss" text="{escape(f.title, {chr(34): "&quot;"})}" '
                     f'xmlUrl="{escape(f.url, {chr(34): "&quot;"})}"/>' for f in feeds)
    xml = (f'<?xml version="1.0" encoding="utf-8"?>\n<opml version="2.0">\n  <head><title>Muzix podcasts'
           f'</title></head>\n  <body>\n{body}\n  </body>\n</opml>\n')
    return Response(xml, media_type="text/x-opml",
                    headers={"Content-Disposition": 'attachment; filename="muzix-podcasts.opml"'})


@router.post("/opml/import")
async def opml_import(file: UploadFile, user: User = Depends(current_user)):
    try:
        root = ET.fromstring(await file.read())
    except ET.ParseError as e:
        raise HTTPException(400, f"Not an OPML file: {e}")
    urls = [o.get("xmlUrl") for o in root.iter("outline") if o.get("xmlUrl")]
    ok, failed = 0, []
    for url in urls:
        try:
            podcasts.subscribe(url, user.id)
            ok += 1
        except Exception as e:
            failed.append({"url": url, "error": str(e)[:200]})
    return {"subscribed": ok, "failed": failed}
