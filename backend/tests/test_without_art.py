"""Admin → Overview: the albums without a cover, counted and listed; one that gets a cover leaves the list."""
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete

from muzix import db
from muzix.api import admin
from muzix.models import Album
from muzix.security import admin_user


def test_albums_without_a_cover():
    with db.session() as s:
        s.execute(delete(Album).where(Album.key.like("noart-%")))
        bare = Album(title="Bare", artist_name="Zed", folder="/m/bare", key="noart-1", kind="music", track_count=9)
        s.add_all([bare,
                   Album(title="Covered", artist_name="Abe", folder="/m/c", key="noart-2", kind="music", art="/m/c/cover.jpg"),
                   Album(title="Embedded", artist_name="Abe", folder="/m/e", key="noart-3", kind="music", art="embedded:4"),
                   Album(title="Game", artist_name="Konami", folder="/v/g", key="noart-4", kind="vgm"),
                   Album(title="Theirs", artist_name="Abe", folder="peer:x/albums/1", key="noart-5", kind="music", peer_id=None),
                   Album(title="Also bare", artist_name="abba", folder="/m/ab", key="noart-6", kind="music", track_count=3)])
        s.flush()
        bare_id = bare.id
    app = FastAPI()
    app.include_router(admin.router)
    app.dependency_overrides[admin_user] = lambda: SimpleNamespace(id=1, is_admin=True)
    c = TestClient(app)
    got = c.get("/api/admin/without-art").json()
    mine = [a for a in got["items"] if a["title"] in ("Bare", "Also bare", "Theirs")]
    assert [a["title"] for a in mine] == ["Also bare", "Theirs", "Bare"]       # by artist, then title
    assert next(a for a in mine if a["title"] == "Bare")["folder"] == "/m/bare"
    before = c.get("/api/admin/status").json()["without_art"]
    with db.session() as s:
        s.get(Album, bare_id).art = "/m/bare/cover.jpg"           # Edit metadata saved a cover
    after = c.get("/api/admin/status").json()["without_art"]
    assert after == {"albums": before["albums"] - 1, "tracks": before["tracks"] - 9}
    assert all(a["title"] != "Bare" for a in c.get("/api/admin/without-art").json()["items"])
