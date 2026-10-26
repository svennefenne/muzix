"""Podcast feeds: fetching, parsing, refreshing and downloading episodes."""

import calendar
import logging
import os
import re
from datetime import datetime, timedelta, timezone

import feedparser
import httpx
from sqlalchemy import select

from . import __version__, db, env, jobs, settings
from .models import Episode, Feed, Subscription

log = logging.getLogger("muzix.podcasts")
UA = f"Muzix/{__version__} (podcast client; +https://github.com/svennefenne/muzix)"


def _when(entry) -> datetime | None:
    t = entry.get("published_parsed") or entry.get("updated_parsed")
    return datetime.fromtimestamp(calendar.timegm(t), timezone.utc) if t else None


def _duration(v) -> float:
    if not v:
        return 0.0
    v = str(v).strip()
    if v.isdigit():
        return float(v)
    parts = v.split(":")
    try:
        secs = 0.0
        for p in parts:
            secs = secs * 60 + float(p)
        return secs
    except ValueError:
        return 0.0


def _strip_html(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s or "")).strip()


def fetch(feed: Feed, client: httpx.Client) -> bool:
    """Refresh one feed in place. Returns True when anything changed."""
    headers = {}
    if feed.etag:
        headers["If-None-Match"] = feed.etag
    if feed.modified:
        headers["If-Modified-Since"] = feed.modified
    r = client.get(feed.url, headers=headers, follow_redirects=True)
    feed.last_checked = datetime.now(timezone.utc)
    if r.status_code == 304:
        return False
    r.raise_for_status()
    parsed = feedparser.parse(r.content)
    if parsed.bozo and not parsed.entries:
        raise ValueError(f"not a podcast feed ({parsed.bozo_exception})")
    f = parsed.feed
    feed.title = f.get("title", feed.title or feed.url)
    feed.author = f.get("author") or f.get("itunes_author", "")
    feed.description = _strip_html(f.get("summary") or f.get("subtitle", ""))[:5000]
    feed.link = f.get("link", "")
    feed.image = (f.get("image") or {}).get("href") or (f.get("itunes_image") or {}).get("href", "") or feed.image
    feed.categories = [t.get("term") for t in f.get("tags", []) if t.get("term")][:10]
    feed.etag = r.headers.get("etag", "")
    feed.modified = r.headers.get("last-modified", "")
    feed.error = ""
    for k, v in (feed.custom or {}).items():   # the admin's edits win over the feed
        setattr(feed, k, v)
    with db.session() as s:
        known = set(s.scalars(select(Episode.guid).where(Episode.feed_id == feed.id)))
    new = []
    for e in parsed.entries:
        enclosure = next((l for l in e.get("links", []) if l.get("rel") == "enclosure"
                          and (l.get("type", "").startswith(("audio", "video")) or l.get("href", "").lower()
                               .split("?")[0].endswith((".mp3", ".m4a", ".aac", ".ogg", ".opus")))), None)
        if not enclosure:
            continue
        guid = e.get("id") or enclosure["href"]
        if guid in known:
            continue
        known.add(guid)
        new.append(Episode(
            feed_id=feed.id, guid=guid[:1024], title=e.get("title", "")[:1024],
            description=_strip_html(e.get("summary", ""))[:8000], published=_when(e),
            duration=_duration(e.get("itunes_duration")), audio_url=enclosure["href"],
            mime=enclosure.get("type", ""), size=int(enclosure.get("length") or 0) if str(enclosure.get("length", "")).isdigit() else 0,
            image=(e.get("image") or {}).get("href", "")))
    if new:
        with db.session() as s:
            s.add_all(new)
    return bool(new)


def open_feed(url: str, fresh: bool = True) -> int:
    """The feed's id, reading it first if it's new (or, with `fresh`, older than six hours);
    nobody is subscribed by this, so a podcast can be looked at before subscribing."""
    with db.session() as s:
        feed = s.scalar(select(Feed).where(Feed.url == url))
        if feed is None:
            feed = Feed(url=url)
            s.add(feed)
            s.flush()
        feed_id, checked = feed.id, feed.last_checked
    if checked is not None and checked.tzinfo is None:   # SQLite hands times back without their zone
        checked = checked.replace(tzinfo=timezone.utc)
    if checked is None or (fresh and datetime.now(timezone.utc) - checked > timedelta(hours=6)):
        with db.session() as s:
            feed = s.get(Feed, feed_id)
            with httpx.Client(headers={"User-Agent": UA}, timeout=30) as client:
                fetch(feed, client)
    return feed_id


def subscribe(url: str, user_id: int) -> Feed:
    feed_id = open_feed(url)
    with db.session() as s:
        if s.get(Subscription, (user_id, feed_id)) is None:
            s.add(Subscription(user_id=user_id, feed_id=feed_id))
        return s.get(Feed, feed_id)


def download_path(ep: Episode) -> str:
    ext = os.path.splitext(ep.audio_url.split("?")[0])[1].lower()
    if ext not in (".mp3", ".m4a", ".aac", ".ogg", ".opus", ".mp4", ".m4b"):
        ext = ".mp3"
    d = env.PODCAST_DIR / str(ep.feed_id)
    d.mkdir(parents=True, exist_ok=True)
    return str(d / f"{ep.id}{ext}")


@jobs.job("download_episode")
def download_episode(ctx: jobs.JobContext, episode_id: int):
    with db.session() as s:
        ep = s.get(Episode, episode_id)
        if ep is None or (ep.local_path and os.path.exists(ep.local_path)):
            return
        url, out = ep.audio_url, download_path(ep)
    part = out + ".part"
    with httpx.Client(headers={"User-Agent": UA}, timeout=60, follow_redirects=True) as client:
        with client.stream("GET", url) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length") or 0)
            done = 0
            with open(part, "wb") as f:
                for chunk in r.iter_bytes(256 * 1024):
                    ctx.check()
                    f.write(chunk)
                    done += len(chunk)
                    if total:
                        ctx.update(done / total)
    os.replace(part, out)
    with db.session() as s:
        s.get(Episode, episode_id).local_path = out
    ctx.log(f"saved {out}")


@jobs.job("refresh_feeds")
def refresh_feeds(ctx: jobs.JobContext):
    with db.session() as s:
        feeds = list(s.scalars(select(Feed).where(Feed.id.in_(select(Subscription.feed_id)))))
    changed = 0
    with httpx.Client(headers={"User-Agent": UA}, timeout=30) as client:
        for i, feed in enumerate(feeds):
            ctx.check()
            with db.session() as s:
                f = s.get(Feed, feed.id)
                before = {e for e in s.scalars(select(Episode.id).where(Episode.feed_id == f.id))}
                try:
                    if fetch(f, client):
                        changed += 1
                except (httpx.HTTPError, ValueError) as e:
                    f.error = str(e)[:500]
                    ctx.log(f"{f.title or f.url}: {e}")
            with db.session() as s:
                new_ids = [e for e in s.scalars(select(Episode.id).where(Episode.feed_id == feed.id))
                           if e not in before]
                auto = s.scalar(select(Subscription.feed_id).where(
                    Subscription.feed_id == feed.id, Subscription.auto_download.is_(True)).limit(1))
            if auto and before:   # only for feeds we knew already: no mass download on subscribe
                for eid in new_ids:
                    jobs.submit("download_episode", "Download episode", episode_id=eid, _allow_parallel=True)
            ctx.update((i + 1) / max(1, len(feeds)))
    prune_downloads(ctx)
    ctx.log(f"{len(feeds)} feeds, {changed} with new episodes")
    return {"feeds": len(feeds), "changed": changed}


def prune_downloads(ctx):
    days = int(settings.get("podcast_keep_days"))
    if not days:
        return
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    with db.session() as s:
        for ep in s.scalars(select(Episode).where(Episode.local_path != "")):
            try:
                mtime = datetime.fromtimestamp(os.path.getmtime(ep.local_path), timezone.utc)
            except OSError:
                ep.local_path = ""
                continue
            if mtime < cutoff:
                os.remove(ep.local_path)
                ep.local_path = ""
                ctx.log(f"removed old download: {ep.title}")
