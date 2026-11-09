"""The Muzix window's own server (relay.py): only the window gets through, and what's for the server goes
on to it, at home or outside."""
import socket
import threading
import time

import httpx
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
    relay.stop()
