"""What's downloaded to this computer (downloads.py): an album's songs and cover come through the window's
own server, play from here (player.py), and offline the window answers for the server with them (relay.py)."""
import json
import socket
import struct
import threading
import time
import wave

import httpx
import pytest
import uvicorn
from PySide6.QtCore import QCoreApplication, QTimer
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from muzix_desktop import player
from muzix_desktop.downloads import Downloads
from muzix_desktop.relay import SECRET_COOKIE, Relay


def _wav(seconds: float) -> bytes:
    import io
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(struct.pack("<h", 1000) * int(8000 * seconds))
    return out.getvalue()


def _server(asked: list) -> tuple[str, uvicorn.Server]:
    """A stand-in Muzix server: two songs and a cover."""
    async def health(request: Request):
        return JSONResponse({"ok": True, "api": 1, "address": ""})

    async def stream(request: Request):
        asked.append(str(request.url.path) + "?" + str(request.url.query))
        return Response(_wav(1.0 + int(request.path_params["id"])), media_type="audio/wav")

    async def art(request: Request):
        return Response(b"\xff\xd8cover", media_type="image/jpeg")

    app = Starlette(routes=[Route("/api/health", health), Route("/api/stream/{id}", stream), Route("/api/art/album/{id}", art)])
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", lifespan="off"))
    threading.Thread(target=server.run, kwargs={"sockets": [s]}, daemon=True).start()
    return f"http://127.0.0.1:{s.getsockname()[1]}", server


def _up(url: str):
    for _ in range(50):
        try:
            httpx.get(url, timeout=1)
            return
        except httpx.HTTPError:
            time.sleep(0.1)


def _until(done, most: float = 8.0):
    end = time.monotonic() + most
    while not done() and time.monotonic() < end:
        time.sleep(0.05)


def _album(origin: str, songs=(1, 2)) -> dict:
    """An album as the page hands it over (frontend/src/downloads.ts)."""
    return {"id": "album:7", "kind": "album", "title": "Computer World", "subtitle": "Kraftwerk", "art": "/api/art/album/7?v=3",
            "path": "/album/7", "pages": {"/api/albums/7": {"id": 7, "title": "Computer World"}},
            "items": [{"key": f"track:{n}", "url": f"{origin}/api/stream/{n}?q=high", "title": f"Song {n}"} for n in songs]}


def test_an_album_downloads_and_answers_offline(tmp_path):
    QCoreApplication.instance() or QCoreApplication([])
    asked = []
    up, server = _server(asked)
    _up(up + "/api/health")
    relay = Relay(up)
    _up(relay.origin + "/")
    d = Downloads(str(tmp_path), relay.headers, relay.origin)
    relay.downloads = d
    d.add(_album(relay.origin))
    _until(lambda: d.list()[0]["done"] == 2)
    got = d.list()[0]
    assert (got["total"], got["done"], got["failed"]) == (2, 2, 0) and got["bytes"] > 40_000
    assert sorted(asked) == ["/api/stream/1?q=high", "/api/stream/2?q=high"]     # through the window's server, as asked
    # the song plays from here, whatever the address's host, quality or start
    f = d.file("http://127.0.0.1:1/api/stream/2?t=12.0")
    assert f and open(f, "rb").read(4) == b"RIFF"
    assert d.file(relay.origin + "/api/stream/3") is None
    # a song in two collections stays while either has it
    d.add({"id": "playlist:1", "kind": "playlist", "title": "Mix", "subtitle": "", "path": "/playlist/1", "pages": {},
           "items": [{"key": "track:2", "url": f"{relay.origin}/api/stream/2", "title": "Song 2"}]})
    _until(lambda: any(tmp_path.joinpath("art").iterdir()))

    # offline: what's downloaded answers for the server
    went = []
    relay.on_offline = went.append
    server.should_exit = True
    time.sleep(0.5)
    window = httpx.Client(cookies={SECRET_COOKIE: relay.secret})
    d.keep_state({"user": {"id": 1, "username": "fenne"}, "modules": {}})
    assert window.get(relay.origin + "/api/albums/7").json() == {"id": 7, "title": "Computer World"}
    assert relay.offline and went == [True]
    state = window.get(relay.origin + "/api/auth/state").json()
    assert state["offline"] is True and state["user"]["username"] == "fenne"
    assert window.get(relay.origin + "/api/art/album/7?v=3").content == b"\xff\xd8cover"
    assert window.get(relay.origin + "/api/albums/8").status_code == 404
    assert window.post(relay.origin + "/api/likes/track/1").status_code == 502

    # taken off: its songs go, but not the one the playlist has
    d.remove("album:7")
    assert d.file(relay.origin + "/api/stream/1") is None and d.file(relay.origin + "/api/stream/2")
    assert [c["id"] for c in d.list()] == ["playlist:1"]
    # and it's all still there after a restart
    again = Downloads(str(tmp_path))
    assert [c["id"] for c in again.list()] == ["playlist:1"] and again.file(relay.origin + "/api/stream/2")
    d.stop()
    again.stop()
    relay.stop()


@pytest.mark.skipif(not player.available(), reason="no GStreamer here")
def test_a_downloaded_song_plays_from_its_file(tmp_path, monkeypatch):
    monkeypatch.setenv("MUZIX_AUDIO_SINK", "fakesink sync=true")
    (tmp_path / "song").write_bytes(_wav(3.0))
    app = QCoreApplication.instance() or QCoreApplication([])
    # nothing answers at the song's address: it plays from the file, from where the stream would have started
    here = {"/api/stream/5": str(tmp_path / "song")}
    p = player.Player(lambda url: {}, speakers=False, downloaded=lambda url: here.get(url.split("?")[0][len("http://127.0.0.1:9"):]))
    got = []
    p.sent.connect(lambda s: got.append(json.loads(s)))
    items = [{"key": "track:5", "url": "http://127.0.0.1:9/api/stream/5?q=high&t=1.5", "title": "Five", "duration": 3.0,
              "offset": 1.5, "muzix": "five"}]
    p.handle(json.dumps({"t": "load", "index": 0, "position": 0, "play": True, "items": items}))
    t = QTimer(interval=50, timeout=lambda: p.position() > 1.8 and app.quit())
    t.start()
    QTimer.singleShot(8000, app.quit)
    app.exec()
    t.stop()
    last = p._state_msg()
    p.release()
    assert not [m for m in got if m["t"] == "error"]
    assert [m["offset"] for m in got if m["t"] == "item"] == [0.0]     # the file's times are the song's own
    assert 1.8 < last["position"] < 3.0 and last["seekable"]
