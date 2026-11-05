"""Muzix Connect: one account's devices see each other, follow the one that plays, control it, and
move the music between them; another account's devices see none of it."""
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from muzix.api import connect


class Who:
    def __init__(self, uid):
        self.id = uid


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(connect, "session_user", lambda db, token: Who(int(token)) if token else None)
    monkeypatch.setattr(connect, "GRACE", 0.3)
    connect.accounts.clear()
    app = FastAPI()
    app.include_router(connect.router)
    return TestClient(app)


def until(ws, t):
    """The next message of kind `t` (the device lists in between skipped)."""
    while True:
        m = ws.receive_json()
        if m["t"] == t:
            return m


def device(client, uid, did, name, kind="browser"):
    ws = client.websocket_connect("/api/connect", headers={"cookie": f"muzix_session={uid}"}).__enter__()
    ws.send_json({"t": "hello", "id": did, "name": name, "kind": kind})
    assert until(ws, "devices")["you"] == did
    return ws


QUEUE = [{"key": "track:1", "title": "One"}, {"key": "track:2", "title": "Two"}]


def test_devices_follow_control_and_hand_over(client):
    desk = device(client, 1, "desk", "Chrome on Linux")
    phone = device(client, 1, "phone", "Galaxy S23", "app")
    elsewhere = device(client, 2, "other", "Someone else's")
    listed = until(desk, "devices")
    assert {d["name"] for d in listed["devices"]} == {"Chrome on Linux", "Galaxy S23"} and listed["active"] == ""

    # the desk plays: it's the device that plays, and the phone follows what it plays
    desk.send_json({"t": "state", "state": {"queue": QUEUE, "index": 0, "position": 10, "playing": True}})
    assert until(phone, "devices")["active"] == "desk"
    st = until(phone, "state")["state"]
    assert st["queue"] == QUEUE and st["position"] == 10
    desk.send_json({"t": "state", "state": {"index": 1, "position": 0, "playing": True}})
    st = until(phone, "state")["state"]
    assert st["index"] == 1 and st["queue"] == QUEUE        # the queue kept when it didn't change

    # back in view, the phone asks again: the devices and what plays now
    phone.send_json({"t": "sync"})
    assert until(phone, "devices")["active"] == "desk"
    assert until(phone, "state")["state"]["index"] == 1

    # the phone's controls reach the desk
    phone.send_json({"t": "command", "cmd": "pause"})
    assert until(desk, "command") == {"t": "command", "cmd": "pause", "from": "phone"}
    # a device that only follows doesn't tell what it plays
    phone.send_json({"t": "state", "state": {"queue": [], "index": -1, "playing": False}})

    # the music moves to the phone: the desk stops and follows, the phone carries on where it was
    time.sleep(0.2)
    phone.send_json({"t": "transfer", "to": "phone", "play": True})
    assert until(desk, "yield") == {"t": "yield"}
    took = until(phone, "takeover")
    assert took["play"] and took["state"]["queue"] == QUEUE and took["state"]["index"] == 1
    assert took["state"]["position"] > 0.15                  # it went on playing meanwhile
    assert until(desk, "devices")["active"] == "phone"

    # the phone goes; for a while (a reload) it still plays, away, then nothing does, and what it played is kept
    phone.close()
    listed = until(desk, "devices")
    assert listed["active"] == "phone" and "phone" not in [d["id"] for d in listed["devices"]] and listed["grace"] == 0.3
    time.sleep(0.4)
    again = device(client, 1, "laptop", "Firefox on Windows")
    assert until(desk, "devices")["active"] == ""
    st = until(again, "state")["state"]
    assert st["queue"] == QUEUE and st["playing"] is False and st["position"] > 0.15

    # the other account heard none of it
    elsewhere.send_json({"t": "state", "state": {"queue": [{"key": "track:9"}], "index": 0, "playing": True}})
    assert until(elsewhere, "devices")["active"] == "other"
    for ws in (desk, elsewhere, again):
        ws.close()


def test_a_reload_is_the_same_device_and_nobody_signed_out_gets_in(client):
    desk = device(client, 1, "desk", "Chrome on Linux")
    desk.send_json({"t": "state", "state": {"queue": QUEUE, "index": 0, "position": 0, "playing": True}})
    reloaded = client.websocket_connect("/api/connect", headers={"cookie": "muzix_session=1"}).__enter__()
    reloaded.send_json({"t": "hello", "id": "desk", "name": "Chrome on Linux", "kind": "browser"})
    listed = until(reloaded, "devices")
    assert [d["id"] for d in listed["devices"]] == ["desk"] and listed["active"] == "desk"
    reloaded.close()
    with pytest.raises(Exception):
        with client.websocket_connect("/api/connect") as ws:
            ws.receive_json()
