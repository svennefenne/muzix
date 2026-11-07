"""Another server's audio, covers and lyrics, through this one. The other server is this same app,
called back over a test client: its own songs, mirrored here under a peer's id, play from it."""
import hashlib
import io
import wave
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

from muzix import db, mirror
from muzix.api import library, network as network_api, stream
from muzix.models import Album, Artist, Peer, Root, Track
from muzix.security import current_user, stream_user

KEY = "loop" * 10


@pytest.fixture(scope="module")
def app():
    a = FastAPI()
    for r in (library.router, stream.router, network_api.router):
        a.include_router(r)
    a.dependency_overrides[stream_user] = a.dependency_overrides[current_user] = lambda: SimpleNamespace(id=0)
    return a


@pytest.fixture(scope="module")
def loop(app, tmp_path_factory):
    """A song (a second of a WAV) on an album with a cover, ours; then mirrored as the "loop"
    server's, which is this app answering for itself."""
    d = tmp_path_factory.mktemp("relay")
    with wave.open(str(d / "song.wav"), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(8000)
        w.writeframes(b"\0\1" * 8000)
    Image.new("RGB", (400, 400), (200, 30, 60)).save(d / "cover.jpg")
    with db.session() as s:
        root = Root(path=str(d), kind="music")
        ar = Artist(name="Relay Artist")
        s.add_all([root, ar])
        s.flush()
        al = Album(title="Relay Album", artist_name=ar.name, artist_id=ar.id, folder=str(d), key="relay-album",
                   art=str(d / "cover.jpg"))
        s.add(al)
        s.flush()
        t = Track(root_id=root.id, path=str(d / "song.wav"), title="Relay Song", artist=ar.name, album_id=al.id,
                  artist_id=ar.id, format="wav", duration=1.0)
        s.add_all([t, Peer(server_id="loop-server", name="Loop", address="http://testserver", sent=True,
                           received=True, key=KEY, their_key=hashlib.sha256(KEY.encode()).hexdigest())])
        s.flush()
        ours = {"track": t.id, "album": al.id}
        peer = s.scalar(select(Peer.id).where(Peer.server_id == "loop-server"))
    cat = {part: [] for part in mirror.PARTS}
    for part in ("artists", "albums", "tracks"):
        page = mirror.export(part, 0, 5000)
        cat[part] = [dict(zip(page["fields"], r)) for r in page["rows"]]
    mirror.store(peer, "loop-server", "Loop", cat)
    with db.session() as s:
        theirs = {"track": s.scalar(select(Track.id).where(Track.path == f"peer:loop-server/tracks/{ours['track']}")),
                  "album": s.scalar(select(Album.id).where(Album.key == f"peer:loop-server:{ours['album']}"))}
    return {"ours": ours, "theirs": theirs}


@pytest.fixture
def wire(app, monkeypatch):
    """The other server's answers, counted."""
    asked = []
    other = TestClient(app)
    real = other.send

    def send(req, **kw):
        asked.append((req.url.path, req.headers.get("range")))
        return real(req, **kw)

    monkeypatch.setattr(other, "send", send)
    monkeypatch.setattr(mirror, "_http", other)
    mirror._away.clear()
    return asked


def test_only_its_own_and_only_for_linked_servers(app, loop):
    c = TestClient(app)
    ok = {"Authorization": f"Bearer {KEY}"}
    assert c.get(f"/api/network/stream/{loop['ours']['track']}").status_code == 401
    assert c.get(f"/api/network/stream/{loop['ours']['track']}", headers=ok).content.startswith(b"RIFF")
    # what it has from another server isn't passed on
    assert c.get(f"/api/network/stream/{loop['theirs']['track']}", headers=ok).status_code == 404
    assert c.get(f"/api/network/art/album/{loop['theirs']['album']}", headers=ok).status_code == 404
    assert c.get(f"/api/network/art/album/{loop['ours']['album']}", headers=ok).headers["content-type"] == "image/webp"


def test_their_song_plays_through_here(app, loop, wire):
    c = TestClient(app)
    r = c.get(f"/api/stream/{loop['theirs']['track']}", headers={"Range": "bytes=0-99"})
    assert r.status_code == 206 and len(r.content) == 100 and r.content.startswith(b"RIFF")
    assert r.headers["content-range"].startswith("bytes 0-99/") and r.headers["content-type"].startswith("audio/")
    assert wire == [(f"/api/network/stream/{loop['ours']['track']}", "bytes=0-99")]


def test_their_cover_is_fetched_once(app, loop, wire):
    c = TestClient(app)
    album = c.get(f"/api/albums/{loop['theirs']['album']}").json()
    assert album["art"].startswith(f"/api/art/album/{loop['theirs']['album']}?v=") and album["colors"]
    for _ in range(2):
        r = c.get(f"/api/art/album/{loop['theirs']['album']}?s=160")
        assert r.status_code == 200 and Image.open(io.BytesIO(r.content)).size == (160, 160)
    assert [p for p, _ in wire].count(f"/api/network/art/album/{loop['ours']['album']}") == 2   # 300 (colours), 160


def test_their_lyrics_come_from_it(app, loop, wire):
    c = TestClient(app)
    got = c.get(f"/api/tracks/{loop['theirs']['track']}/lyrics").json()
    assert set(got) >= {"source", "lines", "colors"} and got["colors"]
    assert (f"/api/network/lyrics/{loop['ours']['track']}", None) in wire


def test_a_server_that_doesnt_answer_is_left_alone_a_while(app, loop, monkeypatch):
    calls = []

    def down(req):
        calls.append(req.url.path)
        raise httpx.ConnectError("no route to host")

    monkeypatch.setattr(mirror, "_http", httpx.Client(transport=httpx.MockTransport(down)))
    mirror._away.clear()
    c = TestClient(app)
    for _ in range(3):
        r = c.get(f"/api/stream/{loop['theirs']['track']}")
        assert r.status_code == 502 and "Loop can't be reached" in r.json()["detail"]
    assert len(calls) == 1
    assert c.get(f"/api/art/album/{loop['theirs']['album']}?s=600").status_code == 404
    mirror._away.clear()
