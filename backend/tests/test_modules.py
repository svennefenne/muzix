"""Modules a server can do without, and the setup a new server goes through: a module that's
off is out of sight (its content, its requests, its background work) but nothing of it is gone."""
from types import SimpleNamespace

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from muzix import db, modules, network, settings
from muzix.api import admin, auth, books as books_api, setup
from muzix.models import Album, Book, Feed, Root, Setting, Station, Track, User
from muzix.security import admin_user, current_user, optional_user


@pytest.fixture(autouse=True)
def all_on():
    """Every module on before and after (the default), and no setup half done."""
    def reset():
        settings.set_many({modules.setting(m.key): True for m in modules.MODULES})
        with db.session() as s:
            s.execute(delete(Setting).where(Setting.key.in_([setup.PENDING, "network_code"])))
    reset()
    yield
    reset()


@pytest.fixture
def submitted(monkeypatch):
    """The jobs asked for, not run."""
    asked = []
    monkeypatch.setattr(setup.jobs, "submit", lambda type_, title="", **kw: asked.append(type_))
    monkeypatch.setattr(admin.jobs, "submit", lambda type_, title="", **kw: asked.append(type_))
    return asked


@pytest.fixture
def client():
    app = FastAPI()
    for r in (auth.router, setup.router, admin.router):
        app.include_router(r)
    app.include_router(books_api.router, dependencies=[Depends(modules.needed("audiobooks"))])
    return app


def as_admin(app):
    me = SimpleNamespace(id=0, is_admin=True, username="admin", prefs={})
    for dep in (admin_user, current_user, optional_user):
        app.dependency_overrides[dep] = lambda: me
    return TestClient(app)


@pytest.fixture
def library(tmp_path):
    """A song, a chiptune, an audiobook, a podcast and a saved station."""
    with db.session() as s:
        root = Root(path=str(tmp_path / "mods-music"), kind="music")
        user = User(username="modules-listener", password_hash="x")
        s.add_all([root, user])
        s.flush()
        made = {}
        for kind in ("music", "vgm"):
            a = Album(title=f"Modules {kind}", artist_name="Someone", kind=kind, key=f"modules-{kind}", folder=str(tmp_path / kind))
            s.add(a)
            s.flush()
            t = Track(root_id=root.id, path=str(tmp_path / kind / "song"), title=f"Modules {kind} song", kind=kind, album_id=a.id)
            s.add(t)
            s.flush()
            made[kind] = (a.id, t.id)
        b = Book(root_id=root.id, path=str(tmp_path / "book"), title="Modules book")
        f = Feed(url="https://example.com/modules.xml", title="Modules show")
        st = Station(user_id=user.id, name="Modules FM", url="https://example.com/fm")
        s.add_all([b, f, st])
        s.flush()
        made.update(book=b.id, feed=f.id, station=st.id)
    yield made
    with db.session() as s:
        s.execute(delete(Album).where(Album.key.in_(["modules-music", "modules-vgm"])))
        s.execute(delete(Feed).where(Feed.url == "https://example.com/modules.xml"))
        s.execute(delete(Root).where(Root.path == str(tmp_path / "mods-music")))
        s.execute(delete(User).where(User.username == "modules-listener"))


def seen(model):
    """What a page lists."""
    s = db.SessionLocal()
    s.info["hide"] = True
    try:
        return set(s.scalars(select(model.id)))
    finally:
        s.close()


def test_a_module_thats_off_is_out_of_sight_and_back_when_its_on(library):
    m = library
    for key in ("vgm", "audiobooks", "podcasts", "radio"):
        settings.set_many({modules.setting(key): False})
    assert m["music"][0] in seen(Album) and m["vgm"][0] not in seen(Album)
    assert m["music"][1] in seen(Track) and m["vgm"][1] not in seen(Track)
    assert m["book"] not in seen(Book) and m["feed"] not in seen(Feed) and m["station"] not in seen(Station)
    with db.session() as s:      # nothing of it is gone: the admin's own lists and the jobs see it all
        assert s.get(Album, m["vgm"][0]) and s.get(Book, m["book"]) and s.get(Feed, m["feed"])
    assert modules.kinds() == {"music"}
    for key in ("vgm", "audiobooks", "podcasts", "radio"):
        settings.set_many({modules.setting(key): True})
    assert {m["vgm"][0], m["music"][0]} <= seen(Album) and m["book"] in seen(Book) and m["station"] in seen(Station)
    assert modules.kinds() == {"music", "vgm", "audiobooks"}


def test_its_requests_answer_that_its_off(client):
    c = as_admin(client)
    settings.set_many({"module_audiobooks": False})
    r = c.get("/api/books")
    assert r.status_code == 404 and r.json()["detail"] == "The Audiobooks module is turned off on this server"
    assert c.get("/api/auth/state").json()["modules"] == {
        "vgm": True, "audiobooks": False, "podcasts": True, "radio": True, "spotify": True, "network": True}


def test_turned_on_again_it_catches_up(client, submitted):
    c = as_admin(client)
    assert c.put("/api/admin/modules/podcasts", json={"on": False}).json()["on"] is False
    assert submitted == []
    assert c.put("/api/admin/modules/podcasts", json={"on": True}).json()["on"] is True
    c.put("/api/admin/modules/vgm", json={"on": False})
    c.put("/api/admin/modules/vgm", json={"on": True})
    c.put("/api/admin/modules/radio", json={"on": True})          # it was on: nothing to catch up on
    assert submitted == ["refresh_feeds", "scan"]
    mods = {x["key"]: x for x in c.get("/api/admin/modules").json()}
    assert [s["key"] for s in mods["podcasts"]["settings"]] == ["podcast_refresh_hours", "podcast_keep_days"]
    # the Settings page leaves a module's settings to it
    owners = {s["key"]: s["module"] for s in c.get("/api/admin/settings").json()}
    assert owners["chip_loops"] == "vgm" and owners["spotify_client_id"] == "spotify" and owners["site_name"] is None


def test_a_new_server_sets_up_after_its_admin_account(client, submitted, monkeypatch, tmp_path):
    for d in ("music/Other formats", "vgm", "audiobooks"):
        (tmp_path / d).mkdir(parents=True)
    monkeypatch.setattr(setup.env, "DEFAULT_ROOTS", f"{tmp_path}/music:music,{tmp_path}/vgm:vgm,{tmp_path}/none:audiobooks")
    monkeypatch.setattr(auth, "has_users", lambda db: False)
    c = TestClient(client)
    r = c.post("/api/auth/setup", json={"username": "modules-admin", "password": "secret1"})
    try:
        assert r.status_code == 200
        assert setup.pending() and submitted == []           # no folders yet, nothing scanned
        c = as_admin(client)
        assert c.get("/api/auth/state").json()["setup"] is True
        info = c.get("/api/setup").json()
        # the mounted folders first (then any the library has already: other tests' here)
        assert info["folders"][:2] == [{"path": f"{tmp_path}/music", "kind": "music"}, {"path": f"{tmp_path}/vgm", "kind": "vgm"}]
        suggested = {m["key"]: m["suggested"] for m in info["modules"]}
        assert suggested["vgm"] and suggested["podcasts"] and suggested["radio"]
        assert not suggested["spotify"] and not suggested["network"]
        assert [s["key"] for s in info["general"]] == ["site_name", "public_url", "allow_signup"]

        bad = c.post("/api/setup/finish", json={"folders": [{"path": f"{tmp_path}/nowhere", "kind": "music"}]})
        assert bad.status_code == 400 and setup.pending()
        assert c.post("/api/setup/finish", json={"settings": {"is_admin": True}}).status_code == 400

        done = c.post("/api/setup/finish", json={
            "folders": [{"path": f"{tmp_path}/music", "kind": "music"}, {"path": f"{tmp_path}/audiobooks", "kind": "audiobooks"}],
            "modules": {"vgm": False, "audiobooks": True, "podcasts": True, "radio": False, "spotify": False, "network": True},
            "settings": {"site_name": "Modules Muzix", "chip_loops": 3, "lastfm_api_key": "••••••"},
            "share": True,
        })
        assert done.status_code == 200 and network.clean_code(done.json()["code"])
        assert not setup.pending() and submitted == ["scan"]
        assert modules.states() == {"vgm": False, "audiobooks": True, "podcasts": True, "radio": False,
                                    "spotify": False, "network": True}
        assert settings.get("site_name") == "Modules Muzix" and settings.get("chip_loops") == 3
        with db.session() as s:
            roots = {r.path: (r.kind, r.excludes, r.upload_target) for r in s.scalars(select(Root).where(Root.path.like(f"{tmp_path}%")))}
        assert roots == {f"{tmp_path}/music": ("music", ["Other formats"], roots[f"{tmp_path}/music"][2]),
                         f"{tmp_path}/audiobooks": ("audiobooks", [], False)}
        assert c.post("/api/setup/finish", json={}).status_code == 409
        assert c.get("/api/auth/state").json()["setup"] is False
    finally:
        settings.set_many({"site_name": "Muzix", "chip_loops": 2})
        with db.session() as s:
            s.execute(delete(Root).where(Root.path.like(f"{tmp_path}%")))
            s.execute(delete(User).where(User.username == "modules-admin"))


def test_skipping_the_setup_takes_the_mounted_folders(client, submitted, monkeypatch, tmp_path):
    (tmp_path / "music").mkdir()
    monkeypatch.setattr(setup.env, "DEFAULT_ROOTS", f"{tmp_path}/music:music,{tmp_path}/vgm:vgm")
    setup.begin()
    c = as_admin(client)
    try:
        assert c.post("/api/setup/skip").status_code == 200
        assert not setup.pending() and submitted == ["scan"] and all(modules.states().values())
        with db.session() as s:
            assert list(s.scalars(select(Root.path).where(Root.path.like(f"{tmp_path}%")))) == [f"{tmp_path}/music"]
        assert c.post("/api/setup/skip").status_code == 409
    finally:
        with db.session() as s:
            s.execute(delete(Root).where(Root.path.like(f"{tmp_path}%")))
