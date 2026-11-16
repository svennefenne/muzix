"""What counts as a play: the same song sent over and over just now counts once (a player's status coming
again and again sent one play 12,000 times in an hour), those that came so before are taken out once, and
Most played is the last 30 days, each song once a day."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select, update

from muzix import db, plays, settings
from muzix.api import stream
from muzix.models import Album, PlayEvent, Root, Track, User
from muzix.security import current_user

ago = lambda **k: datetime.now(timezone.utc) - timedelta(**k)     # noqa: E731


def _library():
    with db.session() as s:
        user = User(username="plays-tester", password_hash="x")
        root = Root(path="/pl", kind="music")
        s.add_all([user, root])
        s.flush()
        albums = [Album(title=f"Plays {n}", folder=f"/pl/{n}", key=f"pl-{n}") for n in ("a", "b", "c")]
        s.add_all(albums)
        s.flush()
        songs = [Track(root_id=root.id, path=f"/pl/{a.title}/{n}.mp3", title=f"{a.title} {n}", album_id=a.id,
                       duration=d, kind="music", format="mp3") for a in albums for n, d in ((1, 200), (2, 10))]
        s.add_all(songs)
        s.flush()
        return user.id, [a.id for a in albums], {t.title: t.id for t in songs}


def _clean():
    with db.session() as s:
        s.execute(delete(PlayEvent).where(PlayEvent.track_id.in_(select(Track.id).where(Track.path.like("/pl/%")))))
        s.execute(delete(Track).where(Track.path.like("/pl/%")))
        s.execute(delete(Album).where(Album.key.like("pl-%")))
        s.execute(delete(Root).where(Root.path == "/pl"))
        s.execute(delete(User).where(User.username == "plays-tester"))


def _count(tid):
    with db.session() as s:
        return s.scalar(select(func.count()).select_from(PlayEvent).where(PlayEvent.track_id == tid))


def _back(tid, **k):
    """Its plays as if they were that long ago."""
    with db.session() as s:
        for p in s.scalars(select(PlayEvent).where(PlayEvent.track_id == tid)):
            p.played_at = p.played_at.replace(tzinfo=timezone.utc) - timedelta(**k) if p.played_at.tzinfo is None \
                else p.played_at - timedelta(**k)


def test_the_same_play_sent_over_and_over_counts_once():
    try:
        uid, _, songs = _library()
        app = FastAPI()
        app.include_router(stream.router)
        app.dependency_overrides[current_user] = lambda: SimpleNamespace(id=uid)
        c = TestClient(app)
        long, short = songs["Plays a 1"], songs["Plays a 2"]
        got = [c.post("/api/plays", json={"track_id": long}).json()["counted"] for _ in range(50)]
        assert got[0] is True and not any(got[1:]) and _count(long) == 1
        _back(long, seconds=31)                         # half a minute on: played again
        assert c.post("/api/plays", json={"track_id": long}).json()["counted"] is True and _count(long) == 2
        c.post("/api/plays", json={"track_id": short})
        _back(short, seconds=9.5)                       # a 10-second song on repeat one: each time
        assert c.post("/api/plays", json={"track_id": short}).json()["counted"] is True
        assert c.post("/api/plays", json={"track_id": 999999}).status_code == 404
    finally:
        _clean()


def test_the_repeats_from_before_are_taken_out_once(monkeypatch):
    try:
        uid, _, songs = _library()
        long = songs["Plays a 1"]
        start = ago(days=2)
        with db.session() as s:
            s.add_all([PlayEvent(user_id=uid, track_id=long, played_at=start + timedelta(seconds=0.04 * i)) for i in range(300)])
            s.add_all([PlayEvent(user_id=uid, track_id=long, played_at=start + timedelta(minutes=m)) for m in (10, 20)])
        monkeypatch.setattr(settings, "get", lambda k, d=None: None if k == "plays_tidied" else d)
        saved = {}
        monkeypatch.setattr(settings, "set_many", saved.update)
        plays.tidy()
        assert _count(long) == 3 and saved == {"plays_tidied": plays.TIDIED}
        monkeypatch.setattr(settings, "get", lambda k, d=None: plays.TIDIED if k == "plays_tidied" else d)
        with db.session() as s:
            s.add(PlayEvent(user_id=uid, track_id=long, played_at=start + timedelta(minutes=10, seconds=1)))
        plays.tidy()                                    # once only
        assert _count(long) == 4
    finally:
        _clean()


def test_most_played_is_the_last_30_days_each_song_once_a_day():
    try:
        uid, albums, songs = _library()
        a, b, c = albums
        with db.session() as s:
            # a: one song on repeat all night (40 plays), one day; b: two songs on two days; c: long ago
            night = ago(hours=30).replace(hour=1)
            s.add_all([PlayEvent(user_id=uid, track_id=songs["Plays a 1"], played_at=night + timedelta(minutes=4 * i))
                       for i in range(40)])
            s.add_all([PlayEvent(user_id=uid, track_id=songs[f"Plays b {n}"], played_at=ago(days=d))
                       for n in (1, 2) for d in (3, 4)])
            s.add_all([PlayEvent(user_id=uid, track_id=songs["Plays c 1"], played_at=ago(days=40 + d)) for d in range(9)])
        with db.session() as s:
            assert plays.heavy_rotation(s, uid) == [b, a]
            s.execute(update(PlayEvent).where(PlayEvent.track_id == songs["Plays c 1"]).values(played_at=ago(days=1)))
            assert plays.heavy_rotation(s, uid)[0] == b        # nine plays today: once
    finally:
        _clean()
