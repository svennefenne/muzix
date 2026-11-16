"""Public links (api/shares.py): anyone with one listens to what it shows, without an account, until it
runs out or is taken away; only this server's own library, and only what its maker may see."""
import wave
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import delete, update

from muzix import db, settings
from muzix.api import shares
from muzix.models import Album, Artist, Playlist, PlaylistItem, Root, Share, Track, User
from muzix.security import current_user, admin_user


def _wav(path):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\0\0" * 800)


def _outside(monkeypatch):
    """The server's public address, as an admin set it."""
    real = settings.get
    fixed = {"public_url": "https://music.example", "site_name": "Muzix"}
    monkeypatch.setattr(settings, "get", lambda k, *d: fixed[k] if k in fixed else real(k, *d))


def _library(tmp_path):
    for n in (1, 2):
        _wav(tmp_path / f"song{n}.wav")
    with db.session() as s:
        me = User(username="share-tester", password_hash="x")
        other = User(username="share-other", password_hash="x")
        root = Root(path="/sh", kind="music")
        artist = Artist(name="Sharers")
        s.add_all([me, other, root, artist])
        s.flush()
        ours = Album(title="Sharing Album", folder="/sh/a", key="sh-a", artist_id=artist.id, artist_name="Sharers",
                     year=2020, art="/sh/a/cover.jpg")
        theirs = Album(title="Friend's Album", folder="peer:1/b", key="sh-b", peer_id=1)
        s.add_all([ours, theirs])
        s.flush()
        t1, t2 = (Track(root_id=root.id, path=str(tmp_path / f"song{n}.wav"), title=f"Song {n}", artist="Sharers", album_id=ours.id,
                        artist_id=artist.id, track_no=n, duration=0.1, kind="music", format="wav") for n in (1, 2))
        far = Track(root_id=root.id, path="peer:1/x.mp3", title="Far", album_id=theirs.id, kind="music", format="mp3", peer_id=1)
        s.add_all([t1, t2, far])
        s.flush()
        secret = Playlist(user_id=other.id, name="Not yours")
        mix = Playlist(user_id=me.id, name="Mix")
        s.add_all([secret, mix])
        s.flush()
        s.add_all([PlaylistItem(playlist_id=mix.id, track_id=t2.id, position=0),
                   PlaylistItem(playlist_id=mix.id, track_id=far.id, position=1)])
        return SimpleNamespace(me=me.id, other=other.id, album=ours.id, theirs=theirs.id, t1=t1.id, t2=t2.id,
                               far=far.id, secret=secret.id, mix=mix.id, artist=artist.id)


def _clean():
    with db.session() as s:
        s.execute(delete(Share))
        s.execute(delete(PlaylistItem))
        s.execute(delete(Playlist).where(Playlist.name.in_(["Not yours", "Mix"])))
        s.execute(delete(Track).where(Track.path.like("%/song_.wav") | Track.path.like("peer:1/%")))
        s.execute(delete(Album).where(Album.key.like("sh-%")))
        s.execute(delete(Artist).where(Artist.name == "Sharers"))
        s.execute(delete(Root).where(Root.path == "/sh"))
        s.execute(delete(User).where(User.username.like("share-%")))


def _client(uid, admin=False):
    app = FastAPI()
    app.include_router(shares.router)
    who = SimpleNamespace(id=uid, is_admin=admin, can_share=True, prefs={}, limits=None)
    app.dependency_overrides[current_user] = lambda: who
    app.dependency_overrides[admin_user] = lambda: who
    return TestClient(app), who


def test_a_public_link_plays_what_it_shows_and_nothing_else(tmp_path, monkeypatch):
    _outside(monkeypatch)
    try:
        ids = _library(tmp_path)
        c, me = _client(ids.me)
        made = c.post("/api/shares", json={"kind": "album", "id": ids.album, "days": 7}).json()
        assert made["url"].startswith("https://music.example/s/") and made["path"] == f"/album/{ids.album}"
        assert made["title"] == "Sharing Album" and made["sub"] == "Sharers · 2020" and not made["run_out"]
        tok = made["token"]

        anyone = TestClient(c.app)       # no account: the public routes ask for none
        page = anyone.get(f"/api/s/{tok}").json()
        assert [t["title"] for t in page["tracks"]] == ["Song 1", "Song 2"] and page["by"] == "share-tester"
        assert anyone.get(f"/api/s/{tok}/track/{ids.t1}").status_code == 200
        assert anyone.get(f"/api/s/{tok}/track/{ids.far}").status_code == 404     # not in it
        assert c.get("/api/shares").json()[0]["opened"] == 1

        # a friend's album (the Library Network) can't be; nor someone else's private playlist
        r = c.post("/api/shares", json={"kind": "album", "id": ids.theirs, "days": 7})
        assert r.status_code == 400 and "friend" in r.json()["detail"]
        assert c.post("/api/shares", json={"kind": "playlist", "id": ids.secret, "days": 7}).status_code == 404
        assert c.post("/api/shares", json={"kind": "album", "id": ids.album, "days": 3}).status_code == 400

        # a playlist: its own library's songs only, a friend's left out
        mix = c.post("/api/shares", json={"kind": "playlist", "id": ids.mix, "days": None}).json()
        assert mix["expires_at"] is None
        assert [t["title"] for t in anyone.get(f"/api/s/{mix['token']}").json()["tracks"]] == ["Song 2"]
        assert anyone.get(f"/api/s/{mix['token']}/track/{ids.t1}").status_code == 404

        # an artist: their albums with their songs
        art = c.post("/api/shares", json={"kind": "artist", "id": ids.artist, "days": 1}).json()
        got = anyone.get(f"/api/s/{art['token']}").json()
        assert [(a["title"], len(a["tracks"])) for a in got["albums"]] == [("Sharing Album", 2)]
        assert anyone.get(f"/api/s/{art['token']}/track/{ids.t2}").status_code == 200

        # run out: gone; the lists still show it a while
        with db.session() as s:
            s.execute(update(Share).where(Share.token == tok)
                      .values(expires_at=datetime.now(timezone.utc) - timedelta(minutes=1)))
        assert anyone.get(f"/api/s/{tok}").status_code == 404
        assert anyone.get(f"/api/s/{tok}/track/{ids.t1}").status_code == 404
        assert next(x for x in c.get("/api/shares").json() if x["token"] == tok)["run_out"] is True

        # sharing turned off for the account: its links stop, and it can't make new ones
        with db.session() as s:
            s.execute(update(User).where(User.id == ids.me).values(can_share=False))
        assert anyone.get(f"/api/s/{mix['token']}").status_code == 404
        me.can_share = False
        assert c.post("/api/shares", json={"kind": "album", "id": ids.album, "days": 7}).status_code == 403
        with db.session() as s:
            s.execute(update(User).where(User.id == ids.me).values(can_share=True))
        assert anyone.get(f"/api/s/{mix['token']}").status_code == 200

        # taken away: only by its maker or an admin
        other, _ = _client(ids.other)
        other.delete(f"/api/shares/{mix['token']}")
        assert anyone.get(f"/api/s/{mix['token']}").status_code == 200
        c.delete(f"/api/shares/{mix['token']}")
        assert anyone.get(f"/api/s/{mix['token']}").status_code == 404
        admin, _ = _client(ids.other, admin=True)
        assert {x["by"] for x in admin.get("/api/admin/shares").json()} == {"share-tester"}
    finally:
        _clean()


def test_the_link_page_says_what_is_shared(tmp_path, monkeypatch):
    _outside(monkeypatch)
    try:
        ids = _library(tmp_path)
        c, _ = _client(ids.me)
        tok = c.post("/api/shares", json={"kind": "album", "id": ids.album, "days": 7}).json()["token"]
        index = "<html><head><title>Muzix</title></head><body></body></html>"
        req = Request({"type": "http", "method": "GET", "path": f"/s/{tok}", "headers": [], "query_string": b"",
                       "server": ("localhost", 80), "scheme": "http", "root_path": ""})
        page = shares.og_page(tok, index, req)
        assert "<title>Sharing Album · Muzix</title>" in page
        assert 'og:description" content="Album · Sharers · 2020"' in page
        assert f'og:image" content="https://music.example/api/art/album/{ids.album}?v=' in page and "s=600" in page
        assert shares.og_page("nothing-here", index, req) == index
    finally:
        _clean()
