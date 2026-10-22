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
from ..security import current_user
from .proxy import check_url, relay

router = APIRouter(prefix="/api/podcasts", tags=["podcasts"])


def feed_json(f: Feed, sub: Subscription | None = None, unplayed: int | None = None):
    return {"id": f.id, "url": f.url, "title": f.title or f.url, "author": f.author,
            "description": f.description, "image": f.image, "link": f.link, "categories": f.categories,
            "error": f.error, "subscribed": sub is not None,
            "auto_download": bool(sub and sub.auto_download), "unplayed": unplayed,
            "last_checked": f.last_checked.isoformat() if f.last_checked else None}


def episode_json(e: Episode, prog: EpisodeProgress | None, feed: Feed | None = None):
    return {"id": e.id, "feed_id": e.feed_id, "title": e.title, "description": e.description,
            "published": e.published.isoformat() if e.published else None, "duration": e.duration,
            "image": e.image or (feed.image if feed else ""), "downloaded": bool(e.local_path),
            "position": prog.position if prog else 0, "finished": bool(prog and prog.finished),
            "stream": f"/api/podcasts/episodes/{e.id}/stream",
            "feed_title": feed.title if feed else None}


@router.get("")
def subscriptions(db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = db.execute(select(Feed, Subscription).join(Subscription, Subscription.feed_id == Feed.id)
                      .where(Subscription.user_id == user.id).order_by(func.lower(Feed.title))).all()
    out = []
    for f, sub in rows:
        unplayed = db.scalar(select(func.count()).select_from(Episode).outerjoin(
            EpisodeProgress, (EpisodeProgress.episode_id == Episode.id) & (EpisodeProgress.user_id == user.id))
            .where(Episode.feed_id == f.id, func.coalesce(EpisodeProgress.finished, False).is_(False)))
        out.append(feed_json(f, sub, unplayed))
    return out


@router.get("/latest")
def latest(db: Session = Depends(get_db), user: User = Depends(current_user), limit: int = 40):
    rows = db.execute(select(Episode, Feed, EpisodeProgress)
                      .join(Feed, Feed.id == Episode.feed_id)
                      .join(Subscription, (Subscription.feed_id == Feed.id) & (Subscription.user_id == user.id))
                      .outerjoin(EpisodeProgress, (EpisodeProgress.episode_id == Episode.id)
                                 & (EpisodeProgress.user_id == user.id))
                      .order_by(Episode.published.desc()).limit(limit)).all()
    return [episode_json(e, p, f) for e, f, p in rows]


class SubscribeBody(BaseModel):
    url: str


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


@router.get("/top")
def top(user: User = Depends(current_user)):
    country = (settings.get("radio_country") or "us").lower()
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
    return {**feed_json(f, db.get(Subscription, (user.id, feed_id))),
            "episodes": [episode_json(e, p) for e, p in rows]}


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
                         user: User = Depends(current_user)):
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
