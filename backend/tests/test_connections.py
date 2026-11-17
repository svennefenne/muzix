"""A request lets go of its database connections once it has answered, not when the answer has been sent:
a song streams for minutes, a radio station for hours, and a phone that left the wifi keeps its half of a
stream open long after. Holding two connections each, twenty such streams used up the pool (40) and Muzix
stopped answering (Plopp, 2026-11-17)."""
import pytest
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient
from sqlalchemy import delete

from muzix import db
from muzix.api import auth, stream
from muzix.models import Root, Track, User
from muzix.security import hash_password

SESSIONS = (db.get_db, db.get_db_with_copies, db.get_db_all)


@pytest.fixture
def song(tmp_path):
    f = tmp_path / "song.mp3"
    f.write_bytes(b"\xff\xfb" + b"\0" * 4096)
    with db.session() as s:
        s.execute(delete(User).where(User.username == "conn-owner"))
        s.add(User(username="conn-owner", password_hash=hash_password("secret1")))
        root = Root(path=str(tmp_path), kind="music")
        s.add(root)
        s.flush()
        t = Track(root_id=root.id, path=str(f), format="mp3", codec="mp3", title="Song", sample_rate=44100)
        s.add(t)
        s.flush()
        return t.id


def test_a_song_being_sent_holds_no_database_connection(song, monkeypatch):
    def pipe(cmd, mime):
        def body():
            yield str(db.engine.pool.checkedout()).encode()      # while the song is on its way
        return StreamingResponse(body(), media_type=mime)
    monkeypatch.setattr(stream, "_pipe", pipe)
    app = FastAPI()
    app.include_router(auth.router)
    app.include_router(stream.router)
    c = TestClient(app)
    token = c.post("/api/auth/token", json={"username": "conn-owner", "password": "secret1", "device": "Phone"}).json()["token"]
    r = c.get(f"/api/stream/{song}?q=high&t=1", headers={"authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.text == "0"


def _uses(dependant, seen):
    for d in dependant.dependencies:
        if d.call in SESSIONS:
            seen.append(d.scope)
        _uses(d, seen)


def _routes(routes):
    for r in routes:
        if inner := getattr(r, "original_router", None):      # a router included in the app
            yield from _routes(inner.routes)
        else:
            yield r


def test_every_session_closes_when_the_request_has_answered():
    from muzix.app import create_app
    scopes = []
    for route in _routes(create_app().routes):
        if dependant := getattr(route, "dependant", None):
            _uses(dependant, scopes)
    assert len(scopes) > 100
    assert set(scopes) == {"function"}
