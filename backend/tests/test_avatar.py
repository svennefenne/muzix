"""Each account's icon: a picture of its own, cropped to a square and kept as a small WebP, or a letter
or two on a colour; by default the first letter of the name."""
import io

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import delete

from muzix import db, env
from muzix.api import admin, auth, me
from muzix.models import AuthSession, User
from muzix.security import hash_password


@pytest.fixture
def c():
    with db.session() as s:
        s.execute(delete(User).where(User.username.in_(["avatar-owner", "avatar-other"])))
        owner = User(username="avatar-owner", password_hash=hash_password("secret1"), is_admin=True)
        s.add(owner)
        s.flush()
        s.add(AuthSession(token="avatar-token", user_id=owner.id))
    app = FastAPI()
    for r in (auth.router, me.router, admin.router):
        app.include_router(r)
    yield TestClient(app, headers={"authorization": "Bearer avatar-token"})
    with db.session() as s:
        s.execute(delete(User).where(User.username.in_(["avatar-owner", "avatar-other"])))


def picture(w=400, h=200) -> bytes:
    """Red on the left half, blue on the right."""
    img = Image.new("RGB", (w, h), "red")
    img.paste(Image.new("RGB", (w // 2, h), "blue"), (w // 2, 0))
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


def test_the_first_letter_until_its_changed(c):
    assert c.get("/api/auth/state").json()["user"]["avatar"] == {"picture": None, "letter": "A", "color": None}


def test_a_letter_on_a_colour(c):
    got = c.put("/api/me/avatar", json={"letter": "AF", "color": "#FF8800"}).json()
    assert got == {"picture": None, "letter": "AF", "color": "#ff8800"}
    assert c.get("/api/me").json()["avatar"] == got
    assert c.get("/api/me/avatar").json() == got
    assert c.put("/api/me/avatar", json={"color": "orange"}).status_code == 422
    assert c.put("/api/me/avatar", json={"letter": "TOO LONG TO FIT"}).status_code == 422
    assert c.delete("/api/me/avatar").json()["letter"] == "A"


def test_a_picture_cropped_to_a_square(c):
    # the right half's square: all blue
    up = c.post("/api/me/avatar/picture", files={"file": ("me.png", picture(), "image/png")},
                data={"x": "0.75", "y": "0.5", "size": "1"}).json()
    assert up["url"] == f"/api/avatars/{up['picture']}"
    img = Image.open(env.AVATAR_DIR / up["picture"])
    assert img.format == "WEBP" and img.size == (256, 256)
    r, g, b = img.convert("RGB").getpixel((128, 128))
    assert b > 200 and r < 60
    assert c.put("/api/me/avatar", json={"picture": up["picture"]}).json() == {"picture": up["url"], "letter": None, "color": None}
    assert c.get("/api/auth/state").json()["user"]["avatar"]["picture"] == up["url"]
    assert c.get(up["url"]).headers["content-type"] == "image/webp"
    # listed with the users, for the admin
    assert {u["username"]: u for u in c.get("/api/admin/users").json()}["avatar-owner"]["avatar"]["picture"] == up["url"]
    # only pictures uploaded here, and only files that are pictures
    assert c.put("/api/me/avatar", json={"picture": "0" * 24 + ".webp"}).status_code == 400
    assert c.put("/api/me/avatar", json={"picture": "../muzix.db"}).status_code == 422
    assert c.get("/api/avatars/..%2Fmuzix.db").status_code == 404
    bad = c.post("/api/me/avatar/picture", files={"file": ("me.png", b"not a picture", "image/png")})
    assert bad.status_code == 400
    assert TestClient(c.app).get(up["url"]).status_code == 401
