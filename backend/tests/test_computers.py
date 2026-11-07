"""Computers in the Library Network (tunnel.py): the desktop client links with the server's code and
a check of its own, the admin says yes with the computer's code, and then the computer keeps a
connection open through which this server takes its catalog, songs and covers. Its music is hidden
while it's off. The computer here is a thread answering over a test client's websocket."""
import io
import json
import os
import threading
import wave
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from PIL import Image
from sqlalchemy import delete, select

from muzix import db, jobs, mirror, network, tunnel
from muzix.api import library, network as network_api, stream
from muzix.models import Album, Artist, Peer, Root, Setting, Track
from muzix.security import admin_user, current_user, stream_user

CODE = "CCCCC-DDDDD-EEEEE-FFFFF"         # the computer's own
SID = "computer-of-anna"


def song() -> bytes:
    b = io.BytesIO()
    with wave.open(b, "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(8000)
        w.writeframes(bytes(range(256)) * 62)
    return b.getvalue()


SONG = song()
COVER = io.BytesIO()
Image.new("RGB", (300, 300), (20, 160, 90)).save(COVER, "JPEG")
CATALOG = {
    "artists": {"fields": ["id", "name", "sort_name", "mbid", "tags", "image"],
                "rows": [[1, "Computer Artist", "", "", [], 0]]},
    "albums": {"fields": ["id", "kind", "title", "artist", "artist_name", "year", "genre", "art", "mbid", "added_at"],
               "rows": [[7, "music", "Computer Album", "Computer Artist", "Computer Artist", 2001, "Rock", 1, "",
                         "2026-11-01T10:00:00"]]},
    "tracks": {"fields": list(mirror.FIELDS["tracks"]),
               "rows": [[3, 7, "Computer Artist", "music", -1, "wav", "pcm_s16le", "Computer Song", "Computer Artist",
                         "Computer Artist", "Computer Album", 1, 1, 2001, "Rock", 1.0, 128, 8000, 16, 1, len(SONG),
                         False, "", {}, "2026-11-01T10:00:00"]]},
}


class Computer:
    """The desktop client: answers what the server asks, as the real one does (desktop/)."""

    def __init__(self, ws):
        self.ws, self.states, self.asked = ws, [], []
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self):
        try:
            while True:
                m = self.ws.receive_json()
                if m.get("op") == "state":
                    self.states.append(m["state"])
                    continue
                self.asked.append(m["op"])
                rid = m["id"]
                if m["op"] == "catalog":
                    page = CATALOG.get(m["part"], {"fields": mirror.FIELDS[m["part"]], "rows": []})
                    self.ws.send_json({"id": rid, "result": {**page, "next": None}})
                elif m["op"] in ("file", "art"):
                    data = SONG if m["op"] == "file" else COVER.getvalue()
                    for i in range(0, len(data), 4096):
                        last = i + 4096 >= len(data)
                        self.ws.send_bytes(tunnel.HEAD.pack(rid, 1 if last else 0) + data[i:i + 4096])
                elif m["op"] == "lyrics":
                    self.ws.send_json({"id": rid, "result": None})
                else:
                    self.ws.send_json({"id": rid, "error": "unknown"})
        except Exception:       # the connection closed
            pass


@pytest.fixture(scope="module")
def app():
    a = FastAPI()
    for r in (library.router, stream.router, network_api.router):
        a.include_router(r)
    a.dependency_overrides[stream_user] = a.dependency_overrides[current_user] = \
        a.dependency_overrides[admin_user] = lambda: SimpleNamespace(id=0, is_admin=True)
    return a


@pytest.fixture
def server(monkeypatch):
    """A fresh network with this server's code; jobs run right away."""
    with db.session() as s:
        s.execute(delete(Peer))
        s.execute(delete(Setting).where(Setting.key == "network_code"))
    network._tries.clear()
    code = network.new_code()
    ran = []

    def submit(type_, title="", **params):
        ran.append(type_)
        if type_ == "network_sync":
            mirror.sync_peer(SimpleNamespace(check=lambda: None, log=lambda m: None, update=lambda *a: None),
                             params["peer_id"])
        elif type_ == "network_away":
            mirror.dedupe()
        elif type_ == "network_drop":
            mirror.drop_job(SimpleNamespace(log=lambda m: None, update=lambda *a: None, check=lambda: None),
                            params["server_id"])
        return 1

    monkeypatch.setattr(jobs, "submit", submit)
    monkeypatch.setattr(mirror.scanner, "finish_scan", lambda ctx: mirror.dedupe())
    return SimpleNamespace(code=code, ran=ran)


def ask(code=None):
    """The computer's link request, as its client sends it."""
    return network.receive({"protocol": 1, "code": code, "server_id": SID, "name": "Anna's laptop", "address": "",
                            "key": "k" * 40, "kind": "computer", "check": network.computer_check(CODE)}, "198.51.100.4")


def peer() -> dict:
    with db.session() as s:
        return network.peer_json(s.scalar(select(Peer).where(Peer.server_id == SID)))


def wait(cond, seconds=5):
    import time
    end = time.time() + seconds
    while not cond():
        assert time.time() < end, "timed out"
        time.sleep(0.02)


def test_a_computer_asks_and_the_admin_says_yes_with_its_code(server):
    got = ask(server.code)
    assert not got["linked"] and len(got["key"]) >= 32
    p = peer()
    assert p["kind"] == "computer" and p["state"] == "asked" and not p["online"] and p["address"] == ""
    with pytest.raises(network.NetworkError, match="isn't Anna's laptop's code"):
        network.accept(p["id"], "AAAAA-BBBBB-CCCCC-DDDDD")
    assert network.accept(p["id"], CODE.lower().replace("-", " "))["state"] == "linked"
    assert "network_sync" not in server.ran       # it's off: its catalog comes when it connects


def test_a_computer_needs_the_servers_code_and_a_check():
    with pytest.raises(network.Refused):
        ask("AAAAA-BBBBB-CCCCC-DDDDD")
    with pytest.raises(network.Refused, match="check"):
        network.receive({"protocol": 1, "code": network.code(), "server_id": SID, "key": "k" * 40,
                         "kind": "computer"}, "198.51.100.5")


def test_its_music_comes_through_its_connection_and_hides_while_its_off(app, server):
    key = ask(server.code)["key"]
    pid = peer()["id"]
    c = TestClient(app)
    with pytest.raises(WebSocketDisconnect):        # not a member
        with c.websocket_connect("/api/network/tunnel", headers={"Authorization": "Bearer nope" + "x" * 40}):
            pass
    with c.websocket_connect("/api/network/tunnel", headers={"Authorization": f"Bearer {key}"}) as ws:
        comp = Computer(ws)
        wait(lambda: comp.states == ["waiting"])
        assert peer()["online"] and not peer()["counts"]
        c.post(f"/api/network/peers/{pid}/accept", json={"code": CODE}).raise_for_status()
        wait(lambda: comp.states == ["waiting", "linked"])
        wait(lambda: peer()["counts"].get("tracks") == 1)
        with db.session() as s:
            track = s.scalar(select(Track).where(Track.path == f"peer:{SID}/tracks/3"))
            album = s.scalar(select(Album).where(Album.key == f"peer:{SID}:7"))
            tid, aid = track.id, album.id
        assert any(a["title"] == "Computer Album" for a in c.get("/api/albums").json()["items"])

        # the song comes here once and plays from here
        r = c.get(f"/api/stream/{tid}")
        assert r.status_code == 200 and r.content == SONG
        assert c.get(f"/api/stream/{tid}", headers={"Range": "bytes=0-9"}).content == SONG[:10]
        assert comp.asked.count("file") == 1
        # its cover, through the connection
        r = c.get(f"/api/art/album/{aid}?s=160")
        assert r.status_code == 200 and Image.open(io.BytesIO(r.content)).size == (160, 160)

    # it went offline: its music is hidden, and nothing is deleted
    wait(lambda: not peer()["online"])
    assert db.computers_away and "network_away" in server.ran
    assert not any(a["title"] == "Computer Album" for a in c.get("/api/albums").json()["items"])
    assert not any(a["name"] == "Computer Artist" for a in c.get("/api/artists").json()["items"])
    with db.session() as s:
        assert s.get(Track, tid) is not None and s.get(Album, aid) is not None
    r = c.get(f"/api/stream/{tid}")
    assert r.status_code in (200, 404)        # the copy here plays; a new song would say it's off

    # back on: back in the lists
    with c.websocket_connect("/api/network/tunnel", headers={"Authorization": f"Bearer {key}"}) as ws:
        comp = Computer(ws)
        wait(lambda: comp.states == ["linked"])
        assert not db.computers_away
        assert any(a["title"] == "Computer Album" for a in c.get("/api/albums").json()["items"])
        assert any(a["name"] == "Computer Artist" for a in c.get("/api/artists").json()["items"])

        # the admin ends it: the computer is told, and what came from it goes
        c.delete(f"/api/network/peers/{pid}").raise_for_status()
        wait(lambda: comp.states[-1:] == ["removed"])
    with db.session() as s:
        assert s.get(Track, tid) is None and s.scalar(select(Root).where(Root.path == f"peer:{SID}")) is None
    assert not os.path.exists(os.path.join(tunnel.cache_dir(), SID))
