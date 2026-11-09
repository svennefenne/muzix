"""The account's devices: each browser and app signed in is a login of its own, listed, and signed out from
anywhere; an app signs in with a token (`Authorization: Bearer`) instead of the cookie."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete

from muzix import API_VERSION, db
from muzix.api import auth, connect, me
from muzix.models import User
from muzix.security import device_name, hash_password

FIREFOX = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
PHONE = "Mozilla/5.0 (Linux; Android 15; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Mobile Safari/537.36 MuzixApp/0.8.2 (Android)"


@pytest.fixture
def app():
    with db.session() as s:
        s.execute(delete(User).where(User.username.in_(["devices-owner", "devices-other"])))
        s.add_all([User(username="devices-owner", password_hash=hash_password("secret1")),
                   User(username="devices-other", password_hash=hash_password("secret2"))])
        s.commit()
    app = FastAPI()
    for r in (auth.router, me.router, connect.router):
        app.include_router(r)
    return app


def browser(app, agent=FIREFOX, who="devices-owner", pw="secret1"):
    c = TestClient(app, headers={"user-agent": agent})
    assert c.post("/api/auth/login", json={"username": who, "password": pw}).status_code == 200
    return c


def app_token(app, device="Pixel 8", who="devices-owner", pw="secret1"):
    r = TestClient(app).post("/api/auth/token", json={"username": who, "password": pw, "device": device})
    assert r.status_code == 200 and r.json()["user"]["username"] == who
    return r.json()["token"]


def test_an_app_signs_in_with_a_token_of_its_own(app):
    token = app_token(app)
    bare = TestClient(app)
    assert bare.get("/api/me").status_code == 401
    assert bare.get("/api/me", headers={"authorization": f"Bearer {token}"}).json()["username"] == "devices-owner"
    assert bare.get("/api/me", headers={"authorization": "Bearer nonsense"}).status_code == 401
    assert bare.post("/api/auth/token", json={"username": "devices-owner", "password": "wrong"}).status_code == 401
    # the Connect socket takes it too
    with bare.websocket_connect("/api/connect", headers={"authorization": f"Bearer {token}"}) as ws:
        ws.send_json({"t": "hello", "id": "pixel", "name": "Pixel 8", "kind": "app"})
        assert ws.receive_json()["t"] == "devices"


def test_each_device_is_listed_and_signed_out_from_anywhere(app):
    desk = browser(app)
    phone = browser(app, PHONE)
    token = app_token(app)
    browser(app, who="devices-other", pw="secret2")         # someone else's: not on this account's list
    listed = desk.get("/api/me/devices").json()
    assert sorted(d["name"] for d in listed) == ["Firefox on Linux", "Muzix for Android 0.8.2", "Pixel 8"]
    assert [d["name"] for d in listed if d["current"]] == ["Firefox on Linux"]
    assert {d["name"]: d["app"] for d in listed}["Pixel 8"] is True
    assert all(len(d["id"]) == 16 and d["seen"] for d in listed)
    assert token not in str(listed)                          # the list never shows what signs in

    # the desk signs the app out: its token stops working; the others go on
    pixel = next(d["id"] for d in listed if d["name"] == "Pixel 8")
    assert desk.delete(f"/api/me/devices/{pixel}").json() == {"ok": True}
    assert TestClient(app).get("/api/me", headers={"authorization": f"Bearer {token}"}).status_code == 401
    assert phone.get("/api/me").status_code == 200
    assert desk.delete(f"/api/me/devices/{pixel}").status_code == 404

    # another account's devices can't be signed out from here
    other = browser(app, who="devices-other", pw="secret2")
    theirs = other.get("/api/me/devices").json()[0]["id"]
    assert desk.delete(f"/api/me/devices/{theirs}").status_code == 404


def test_an_app_signs_itself_out(app):
    token = app_token(app)
    c = TestClient(app, headers={"authorization": f"Bearer {token}"})
    assert c.post("/api/auth/logout").json() == {"ok": True}
    assert c.get("/api/me").status_code == 401


def test_device_names_from_the_browser():
    assert device_name(FIREFOX) == "Firefox on Linux"
    assert device_name(PHONE) == "Muzix for Android 0.8.2"
    assert device_name("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/141.0.0.0 Safari/537.36 Edg/141.0.0.0") == "Edge on Windows"
    assert device_name("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
                       "Version/18.0 Mobile/15E148 Safari/604.1") == "Safari on iOS"
    assert device_name("curl/8.0") == "curl" and device_name("") == "Unknown device"


def test_the_api_version_is_told():
    from muzix.app import create_app
    assert TestClient(create_app()).get("/api/health").json()["api"] == API_VERSION
