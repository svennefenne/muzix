"""Colour schemes of the users' own: made, changed and taken away by their owner only, shared for everyone
on the server to use, kept to what's safe to draw on other people's devices, and with pictures of their own."""
import io

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import delete

from muzix import db, env
from muzix.api import auth, me, schemes
from muzix.models import Scheme, User
from muzix.security import hash_password

COLORS = {"bg": "#101820", "surface": "#18222c", "text": "#f0e8d8", "primary": "#e07a3a", "secondary": "#3aa0e0",
          "error": "#e04040", "warning": "#e0c040", "success": "#40c080", "border": "#405060"}


def data(**kw):
    return {"base": "muzix", "modes": "both", "dark": COLORS, "light": {**COLORS, "bg": "#f8f0e0", "text": "#202830"},
            "display": "bebas-neue", "ui": "saira", "caps": True, "headline": "none", "radius": 6, "glass": 60,
            "frame": "neon", "backdrop": "embers", "picture": {"desktop": "", "mobile": "", "dim": 30, "blur": 4, "size": "cover"},
            **kw}


@pytest.fixture
def app():
    with db.session() as s:
        s.execute(delete(Scheme))
        s.execute(delete(User).where(User.username.in_(["scheme-maker", "scheme-friend"])))
        s.add_all([User(username="scheme-maker", password_hash=hash_password("secret1")),
                   User(username="scheme-friend", password_hash=hash_password("secret2"))])
        s.commit()
    app = FastAPI()
    for r in (auth.router, me.router, schemes.router):
        app.include_router(r)
    return app


def signed_in(app, who, pw):
    c = TestClient(app)
    assert c.post("/api/auth/login", json={"username": who, "password": pw}).status_code == 200
    return c


def test_a_scheme_is_made_shared_used_and_taken_away(app):
    maker, friend = signed_in(app, "scheme-maker", "secret1"), signed_in(app, "scheme-friend", "secret2")
    made = maker.post("/api/schemes", json={"name": "Ember night", "data": data(), "shared": False}).json()
    assert made["mine"] and made["data"]["frame"] == "neon" and made["owner"]["name"] == "scheme-maker"
    sid = made["id"]
    # only its maker sees it until it's shared
    assert friend.get("/api/schemes").json() == {"mine": [], "shared": []}
    assert friend.get(f"/api/schemes/{sid}").status_code == 404
    maker.put(f"/api/schemes/{sid}", json={"name": "Ember night", "data": data(radius=12), "shared": True})
    listed = friend.get("/api/schemes").json()
    assert [s["name"] for s in listed["shared"]] == ["Ember night"] and not listed["shared"][0]["mine"]
    # the friend's device uses it: counted; but the friend can't change it or take it away
    friend.patch("/api/me/prefs", json={"scheme": f"custom:{sid}"})
    assert maker.get("/api/schemes").json()["mine"][0]["uses"] == 1
    assert friend.put(f"/api/schemes/{sid}", json={"name": "Mine now", "data": data(), "shared": True}).status_code == 404
    assert friend.delete(f"/api/schemes/{sid}").status_code == 404
    # a copy to change is the friend's own
    copy = friend.post("/api/schemes", json={"name": "Ember night (copy)", "data": listed["shared"][0]["data"]}).json()
    assert copy["mine"] and copy["data"]["radius"] == 12
    assert maker.delete(f"/api/schemes/{sid}").json() == {"ok": True}
    assert friend.get(f"/api/schemes/{sid}").status_code == 404


def test_only_whats_safe_to_draw_is_kept(app):
    maker = signed_in(app, "scheme-maker", "secret1")
    bad = [data(dark={**COLORS, "bg": "red; background: url(https://tracker.example/x)"}),
           data(display="'Comic Sans'; } body { display: none"),
           data(picture={"desktop": "https://tracker.example/x.webp", "mobile": "", "dim": 0, "blur": 0, "size": "cover"}),
           data(radius=400)]
    for d in bad:
        assert maker.post("/api/schemes", json={"name": "Nope", "data": d}).status_code == 422
    assert maker.post("/api/schemes", json={"name": "", "data": data()}).status_code == 422


def test_a_picture_is_kept_as_webp_by_its_contents(app):
    maker = signed_in(app, "scheme-maker", "secret1")
    png = io.BytesIO()
    Image.new("RGB", (3000, 1500), "#336699").save(png, "PNG")
    up = maker.post("/api/schemes/pictures", files={"file": ("sky.png", png.getvalue(), "image/png")}).json()
    assert up["url"].startswith("/api/schemes/pictures/") and up["url"].endswith(".webp")
    got = maker.get(up["url"])
    assert got.status_code == 200 and got.headers["content-type"] == "image/webp"
    assert Image.open(io.BytesIO(got.content)).size == (2560, 1280)
    assert maker.post("/api/schemes/pictures", files={"file": ("x.png", b"not a picture", "image/png")}).status_code == 400
    assert TestClient(app).get(up["url"]).status_code == 401
    made = maker.post("/api/schemes", json={"name": "Sky", "data": data(picture={"desktop": up["url"], "mobile": "", "dim": 40,
                                                                                 "blur": 0, "size": "cover"})})
    assert made.status_code == 200 and (env.SCHEME_DIR / up["url"].rsplit("/", 1)[1]).exists()
