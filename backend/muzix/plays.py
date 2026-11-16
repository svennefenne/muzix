"""Songs played: what counts as a play (POST /api/plays, sent by the player once a song has played for
30 seconds or half its length), and what the home page's Most played is made of.

A player that sends the same play over and over counts it once. On 2026-10-31 one song's play came
12,000 times in an hour, tens of milliseconds apart: the page resets its "counted" mark whenever a Cast
speaker or the Android app says which song is playing, and their status kept coming. So the same song
again within half a minute (or most of its length, when it's shorter: repeat one) isn't a new play.
tidy() took out, once, the ones that came that way before.

Most played: the albums played most in the last 30 days, each song counted at most once a day, so a
night of an album on repeat doesn't top the list for good."""

import logging
import threading
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select, text

from . import settings
from .models import PlayEvent, Track

log = logging.getLogger(__name__)
_lock = threading.Lock()
HEAVY_DAYS = 30
TIDIED = "repeats-1"        # settings "plays_tidied": the repeated plays taken out, once


def gap(duration: float | None) -> float:
    """Seconds before the same song counts as played again."""
    return min(30.0, duration * 0.9) if duration else 30.0


def record(db, user_id: int, track: Track) -> bool:
    """A play of `track`, unless it was counted for them just now; whether it counted."""
    with _lock:         # requests of the same burst come at once
        since = datetime.now(timezone.utc) - timedelta(seconds=gap(track.duration))
        if db.scalar(select(PlayEvent.id).where(PlayEvent.user_id == user_id, PlayEvent.track_id == track.id,
                                               PlayEvent.played_at > since).limit(1)) is not None:
            return False
        db.add(PlayEvent(user_id=user_id, track_id=track.id))
        db.commit()
        return True


def repeats(rows) -> list[int]:
    """Of (play id, user, song, when, song's length) in order of user, song and time: the plays record()
    would have kept out."""
    last, out = {}, []
    for pid, uid, tid, at, duration in rows:
        k = (uid, tid)
        if k in last and (at - last[k]).total_seconds() < gap(duration):
            out.append(pid)
            continue
        last[k] = at
    return out


def tidy():
    """Once, at start: the plays sent over and over before record() kept them out, taken out."""
    if settings.get("plays_tidied") == TIDIED:
        return
    from . import db
    with db.session() as s:
        drop = repeats(s.execute(select(PlayEvent.id, PlayEvent.user_id, PlayEvent.track_id, PlayEvent.played_at,
                                        Track.duration).join(Track, Track.id == PlayEvent.track_id)
                                 .order_by(PlayEvent.user_id, PlayEvent.track_id, PlayEvent.played_at, PlayEvent.id)))
        for i in range(0, len(drop), 500):
            s.execute(delete(PlayEvent).where(PlayEvent.id.in_(drop[i:i + 500])))
    settings.set_many({"plays_tidied": TIDIED})
    if drop:
        log.info("took out %d plays sent over and over", len(drop))


def heavy_rotation(db, user_id: int, limit: int = 14) -> list[int]:
    """The albums they played most in the last HEAVY_DAYS days, each song once a day at most; the one played
    last first when it's even."""
    since = (datetime.now(timezone.utc) - timedelta(days=HEAVY_DAYS)).strftime("%Y-%m-%d %H:%M:%S.%f")
    return [r[0] for r in db.execute(text(
        "SELECT album_id, count(*) c, max(m) latest FROM ("
        " SELECT t.album_id, p.track_id, date(p.played_at) d, max(p.played_at) m FROM plays p"
        " JOIN tracks t ON t.id = p.track_id"
        " WHERE p.user_id = :u AND t.album_id IS NOT NULL AND p.played_at >= :since"
        " GROUP BY t.album_id, p.track_id, d)"
        " GROUP BY album_id ORDER BY c DESC, latest DESC LIMIT :n"), {"u": user_id, "since": since, "n": limit})]
