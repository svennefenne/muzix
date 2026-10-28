"""Podcast feeds: fetching, parsing, refreshing and downloading episodes."""

import calendar
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from html import escape
from html.parser import HTMLParser

import feedparser
import httpx
from sqlalchemy import select, update

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


# ---------------------------------------------------------------- show notes

_TOKEN = re.compile(r"(?P<url>https?://[^\s<>\"']+)|(?<![\d:.])(?P<t>(?:(?P<h>\d{1,2}):)?(?P<m>\d{1,2}):(?P<s>[0-5]\d))(?![\d:])")
_BREAK = {"p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "tr", "ul", "ol", "table", "section", "article"}
_SKIP = {"script", "style", "iframe", "object", "embed", "noscript", "template", "svg", "head", "title", "form"}
_INLINE = {"b": "b", "strong": "b", "i": "i", "em": "i"}


class _Notes(HTMLParser):
    """Rebuilds show notes from a few known pieces, so nothing of the feed's own markup reaches
    the page: paragraphs, line breaks, list items, bold and italics, links to the web, and
    timestamps (as buttons the episode page makes seek)."""

    def __init__(self, duration: float):
        super().__init__(convert_charrefs=True)
        self.duration = duration
        self.out: list[str] = []
        self.para = False
        self.inline: list[str] = []
        self.link = False
        self.skip = 0

    def _open(self):
        if not self.para:
            self.out.append("<p>")
            self.para = True

    def _close(self):
        self._end_link()
        while self.inline:
            self.out.append(f"</{self.inline.pop()}>")
        if self.para:
            self.out.append("</p>")
            self.para = False

    def _end_link(self):
        if self.link:
            self.out.append("</a>")
            self.link = False

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP:
            self.skip += 1
        elif self.skip:
            return
        elif tag in _BREAK:
            self._close()
        elif tag == "li":
            self._close()
            self._open()
            self.out.append("• ")
        elif tag == "br":
            if self.para:
                self.out.append("<br>")
        elif tag in _INLINE and not self.link:
            self._open()
            self.inline.append(_INLINE[tag])
            self.out.append(f"<{_INLINE[tag]}>")
        elif tag == "a" and not self.link:
            href = (dict(attrs).get("href") or "").strip()
            if re.match(r"(https?://|mailto:)", href, re.I):
                self._open()
                self.out.append(f'<a href="{escape(href)}" target="_blank" rel="noopener noreferrer nofollow">')
                self.link = True

    def handle_endtag(self, tag):
        if tag in _SKIP:
            self.skip = max(0, self.skip - 1)
        elif self.skip:
            return
        elif tag in _BREAK or tag == "li":
            self._close()
        elif tag == "a":
            self._end_link()
        elif tag in _INLINE and _INLINE[tag] in self.inline:
            self._end_link()
            while self.inline:
                closed = self.inline.pop()
                self.out.append(f"</{closed}>")
                if closed == _INLINE[tag]:
                    break

    def handle_data(self, data):
        if self.skip or (not self.para and not data.strip()):
            return
        self._open()
        text = re.sub(r"\s+", " ", data)
        if self.link:
            self.out.append(escape(text))
            return
        pos = 0
        for m in _TOKEN.finditer(text):
            self.out.append(escape(text[pos:m.start()]))
            pos = m.end()
            if m["url"]:
                url = m["url"].rstrip(".,;:!?)")
                self.out.append(f'<a href="{escape(url)}" target="_blank" rel="noopener noreferrer nofollow">{escape(url)}</a>')
                self.out.append(escape(m["url"][len(url):]))
                continue
            secs = int(m["h"] or 0) * 3600 + int(m["m"]) * 60 + int(m["s"])
            if (m["h"] is None or int(m["m"]) < 60) and (not self.duration or secs <= self.duration):
                self.out.append(f'<button type="button" class="ts" data-t="{secs}">{escape(m["t"])}</button>')
            else:
                self.out.append(escape(m[0]))
        self.out.append(escape(text[pos:]))


def show_notes(source: str, duration: float = 0) -> str:
    """An episode's show notes (HTML or plain text) as safe HTML for its page."""
    source = (source or "")[:100_000]
    if not re.search(r"<\s*(p|br|div|li)\b", source, re.I):    # plain text: its blank lines are paragraphs
        source = re.sub(r"<(?!/?(a|b|i|em|strong|span)\b)", "&lt;", source)    # and a "<" is just that
        source = "".join(f"<p>{p.replace(chr(10), '<br>')}</p>" for p in re.split(r"\n\s*\n", source.strip()))
    parser = _Notes(duration)
    parser.feed(source)
    parser.close()
    parser._close()
    html = "".join(parser.out)
    return re.sub(r"<p>(\s|<br>|• )*</p>", "", html).strip()


def _notes_of(entry, duration: float) -> str:
    content = max((c.get("value", "") for c in entry.get("content", [])), key=len, default="")
    summary = entry.get("summary", "")
    return show_notes(content if len(_strip_html(content)) >= len(_strip_html(summary)) else summary, duration)


def fetch(feed: Feed, client: httpx.Client) -> bool:
    """Refresh one feed in place. Returns True when anything changed."""
    with db.session() as s:     # episodes read before their show notes were kept
        unread = dict(s.execute(select(Episode.guid, Episode.id)
                                .where(Episode.feed_id == feed.id, Episode.notes.is_(None))).all())
    headers = {}
    if feed.etag and not unread:     # with some to fill in, the whole feed is read once more
        headers["If-None-Match"] = feed.etag
    if feed.modified and not unread:
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
    new, notes = [], {}
    for e in parsed.entries:
        enclosure = next((l for l in e.get("links", []) if l.get("rel") == "enclosure"
                          and (l.get("type", "").startswith(("audio", "video")) or l.get("href", "").lower()
                               .split("?")[0].endswith((".mp3", ".m4a", ".aac", ".ogg", ".opus")))), None)
        if not enclosure:
            continue
        guid = e.get("id") or enclosure["href"]
        if guid in known:
            if guid in unread:
                notes[unread.pop(guid)] = _notes_of(e, _duration(e.get("itunes_duration")))
            continue
        known.add(guid)
        new.append(Episode(
            feed_id=feed.id, guid=guid[:1024], title=e.get("title", "")[:1024],
            description=_strip_html(e.get("summary", ""))[:8000], published=_when(e),
            notes=_notes_of(e, _duration(e.get("itunes_duration"))),
            duration=_duration(e.get("itunes_duration")), audio_url=enclosure["href"],
            mime=enclosure.get("type", ""), size=int(enclosure.get("length") or 0) if str(enclosure.get("length", "")).isdigit() else 0,
            image=(e.get("image") or {}).get("href", "")))
    notes.update({ep_id: "" for ep_id in unread.values()})     # gone from the feed: their summary stands in
    with db.session() as s:
        s.add_all(new)
        for ep_id, html in notes.items():
            s.execute(update(Episode).where(Episode.id == ep_id).values(notes=html))
    return bool(new)


def read_now(feed_id: int):
    """Reads a feed straight away (an episode page wanting show notes that were never kept)."""
    with db.session() as s:
        feed = s.get(Feed, feed_id)
        with httpx.Client(headers={"User-Agent": UA}, timeout=20) as client:
            fetch(feed, client)


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
