"""The Muzix window's own server (relay.py): only the window gets through, and what's for the server goes
on to it, at home or outside."""
import socket
import threading
import time

import httpx
import pytest
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from muzix_desktop.relay import SECRET_COOKIE, Relay


def _server() -> str:
    """A stand-in Muzix server: its health, and a sign-in that sets a Secure cookie."""
    async def health(request: Request):
        return JSONResponse({"ok": True, "api": 1, "address": ""})

    async def login(request: Request):
        r = JSONResponse({"agent": request.headers.get("user-agent"), "cookie": request.headers.get("cookie"),
                          "body": (await request.json())})
        r.set_cookie("muzix_session", "abc", secure=True, httponly=True, domain="muzix.example.com")
        return r

    app = Starlette(routes=[Route("/api/health", health), Route("/api/auth/login", login, methods=["POST"])])
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", lifespan="off"))
    threading.Thread(target=server.run, kwargs={"sockets": [s]}, daemon=True).start()
    return f"http://127.0.0.1:{s.getsockname()[1]}"


def _up(url: str):
    for _ in range(50):
        try:
            httpx.get(url, timeout=1)
            return
        except httpx.HTTPError:
            time.sleep(0.1)


def test_only_the_window_gets_through_to_the_server():
    up = _server()
    _up(up + "/api/health")
    gone = "http://127.0.0.1:9"         # nothing answers there: "home", left
    relay = Relay(gone, up)
    _up(relay.origin + "/")
    assert httpx.get(relay.origin + "/api/health").status_code == 403
    window = httpx.Client(cookies={SECRET_COOKIE: relay.secret, "theirs": "1"})
    # home doesn't answer: the outside address, for the same request
    assert window.get(relay.origin + "/api/health").json()["ok"] is True
    assert relay.address == up
    r = window.post(relay.origin + "/api/auth/login", json={"username": "x"})
    got = r.json()
    assert got["body"] == {"username": "x"} and got["agent"].startswith("MuzixDesktop/")
    assert got["cookie"] == "theirs=1"              # the window's secret stays here
    cookie = r.headers["set-cookie"]
    assert "muzix_session=abc" in cookie and "secure" not in cookie.lower() and "domain" not in cookie.lower()
    # the app's player: the secret as a header (GStreamer before 1.22 runs cookies together), and the
    # window's login added here
    player = httpx.Client(headers=relay.headers(relay.origin + "/api/auth/login"))
    assert relay.headers("https://radio.example.com/stream") == {}         # the secret goes nowhere else
    got = player.post(relay.origin + "/api/auth/login", json={}).json()
    assert got["cookie"] == "muzix_session=abc"
    assert httpx.post(relay.origin + "/api/auth/login", json={},
                      headers={"x-muzix-window": "guess"}).status_code == 403
    relay.stop()


def test_speakers_get_only_signed_audio_from_this_computers_library():
    async def stream(request: Request):
        return JSONResponse({"ct": request.query_params.get("ct"), "auth": request.headers.get("authorization")})

    app = Starlette(routes=[Route("/api/stream/{id}", stream), Route("/api/albums", stream)])
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", lifespan="off"))
    threading.Thread(target=server.run, kwargs={"sockets": [s]}, daemon=True).start()
    local = f"http://127.0.0.1:{s.getsockname()[1]}"
    _up(local + "/api/albums")
    relay = Relay()
    _up(relay.origin + "/")
    relay.use_local(local, "the-librarys-token")
    for _ in range(50):
        if relay.loop:
            break
        time.sleep(0.1)
    lan = relay.for_speakers()
    if not lan:
        pytest.skip("no network here")
    got = httpx.get(lan + "/api/stream/7?q=cast&ct=signed").json()
    assert got == {"ct": "signed", "auth": None}               # the speaker's own signature, not the library's token
    assert httpx.get(lan + "/api/stream/7").status_code == 403  # unsigned
    assert httpx.get(lan + "/api/albums?ct=signed").status_code == 403
    relay.stop()
    server.should_exit = True
