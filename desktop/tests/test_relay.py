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


def test_a_speakers_link_to_the_server_is_signed_by_the_server():
    """With this computer's library on, the page signs a speaker's links with that library's token; the
    account's episodes and stations are the server's, which signs them itself."""
    asked = []

    async def health(request: Request):
        return JSONResponse({"ok": True, "api": 1, "address": ""})

    async def token(request: Request):
        asked.append(request.cookies.get("muzix_session"))
        return JSONResponse({"token": "1.99.server", "expires": int(time.time()) + 86400})

    app = Starlette(routes=[Route("/api/health", health), Route("/api/cast/token", token)])
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", lifespan="off"))
    threading.Thread(target=server.run, kwargs={"sockets": [s]}, daemon=True).start()
    up = f"http://127.0.0.1:{s.getsockname()[1]}"
    _up(up + "/api/health")
    relay = Relay(up)
    _up(relay.origin + "/")
    relay.session = "abc"
    episode = relay.origin + "/api/podcasts/episodes/5/stream?q=cast&ct=1.99.local"
    # the server's music shows: the page's links are signed by the server already
    assert relay.speaker_link(episode) == up + "/api/podcasts/episodes/5/stream?q=cast&ct=1.99.local"
    assert asked == []
    # this computer's library: the server's links get the server's signature, asked for once
    relay.use_local("http://127.0.0.1:9", "tok")
    assert relay.speaker_link(episode) == up + "/api/podcasts/episodes/5/stream?q=cast&ct=1.99.server"
    assert relay.speaker_link(relay.origin + "/api/radio/play?url=https%3A%2F%2Fradio.example.com%2Fs&ct=1.99.local") \
        == up + "/api/radio/play?url=https%3A%2F%2Fradio.example.com%2Fs&ct=1.99.server"
    assert asked == ["abc"]
    assert relay.speaker_link("https://radio.example.com/s") == "https://radio.example.com/s"
    relay.stop()
    server.should_exit = True


def test_the_windows_sockets_trust_what_the_app_brings_not_the_systems_certificates(monkeypatch):
    """Muzix Connect over https: the AppImage's OpenSSL looks for certificates where the system it was built
    on keeps them (/usr/lib/ssl), which others (Arch, CachyOS) don't have; certifi's go along with the app."""
    import ssl

    import certifi
    import websockets.sync.client

    from muzix_desktop import relay as relay_mod

    asked: list[tuple[str, dict]] = []

    def connect(url, **kw):
        asked.append((url, kw))
        raise websockets.exceptions.InvalidURI(url, "not really")        # gone again: no server needed

    monkeypatch.setattr(relay_mod.websockets, "connect", connect)
    relay = Relay("http://127.0.0.1:9")
    _up(relay.origin + "/")
    for address in ("https://muzix.example", "http://192.168.1.5:8484"):
        relay.address = address
        with websockets.sync.client.connect(relay.origin.replace("http", "ws") + "/api/connect",
                                            additional_headers={"x-muzix-window": relay.secret}) as ws:
            with pytest.raises(websockets.exceptions.ConnectionClosed):
                ws.recv(timeout=5)
    (wss, kw), (plain, kw2) = asked
    assert wss == "wss://muzix.example/api/connect" and plain == "ws://192.168.1.5:8484/api/connect"
    trusted = kw.get("ssl")
    assert isinstance(trusted, ssl.SSLContext)
    pem = open(certifi.where()).read()
    assert len(trusted.get_ca_certs()) == pem.count("BEGIN CERTIFICATE") > 100
    assert kw2.get("ssl") is None                                       # no TLS at home
    relay.stop()
