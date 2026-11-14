"""An album's own tags (Edit tags on its cog): instead of its artist's, for it alone. A compilation by Various
Artists isn't psytrance because Various Artists is; its page, its songs (the genre skins) and the tag pages go
by its own."""
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from muzix import db, tagging
from muzix.api import library, tags
from muzix.models import Album, Artist, Root, TagRule, Track
from muzix.security import admin_user
from sqlalchemy import delete, select

ME = SimpleNamespace(id=-1)


def client():
    app = FastAPI()
    app.include_router(tags.router)
    app.dependency_overrides[admin_user] = lambda: SimpleNamespace(id=1, is_admin=True)
    return TestClient(app)


def _library():
    """Various Albumtags' two compilations (their tags psytrance, trance), one with a song by an artist with a page."""
    with db.session() as s:
        va = Artist(name="Various Albumtags", tags=[["zqpsytrance", 100], ["zqtrance", 90]])
        own = Artist(name="Albumtags Neuro", tags=[["zqneurofunk", 100]])
        root = Root(path="/at", kind="music")
        s.add_all([va, own, root])
        s.flush()
        dnb = Album(title="Albumtags DnB", folder="/at/dnb", key="at-dnb", artist_id=va.id, artist_name=va.name,
                    year=2018, genre="Electronic")
        psy = Album(title="Albumtags Psy", folder="/at/psy", key="at-psy", artist_id=va.id, artist_name=va.name, year=2019)
        s.add_all([dnb, psy])
        s.flush()
        songs = [Track(root_id=root.id, path=f"/at/{p}.mp3", title=p, artist=who, album_id=album.id, artist_id=va.id,
                       kind="music", format="mp3")
                 for p, who, album in (("a", "Nobody Albumtags", dnb), ("b", "Albumtags Neuro", dnb), ("c", "Nobody Albumtags", psy))]
        s.add_all(songs)
        s.flush()
        return {"va": va.id, "own": own.id, "dnb": dnb.id, "psy": psy.id, **{t.title: t.id for t in songs}}


def _clean():
    with db.session() as s:
        s.execute(delete(Track).where(Track.path.like("/at/%")))
        s.execute(delete(Album).where(Album.key.like("at-%")))
        s.execute(delete(Root).where(Root.path == "/at"))
        s.execute(delete(Artist).where(Artist.name.like("%Albumtags%")))
        s.execute(delete(TagRule).where(TagRule.key.like("zq%")))


def _album(aid):
    with db.session() as s:
        return library.album(aid, db=s, user=ME, limit=1000, offset=0)


def _songs(*ids):
    with db.session() as s:
        return {t["title"]: t["tags"] for t in library.tracks_json(s, ME, [s.get(Track, i) for i in ids])}


def _tagged(tag):
    with db.session() as s:
        return set(s.scalars(select(Track.title).where(library.tagged(s, tag), Track.path.like("/at/%"))))


def test_an_albums_own_tags_for_it_alone():
    try:
        ids = _library()
        c = client()
        got = c.get(f"/api/admin/albums/{ids['dnb']}/tags").json()
        assert got["own"] is False and got["artist"] == "Various Albumtags"
        assert [t["name"] for t in got["tags"]] == ["zqpsytrance", "zqtrance"] and got["taken_off"] == []
        assert _album(ids["dnb"])["artist_tags"] == ["zqpsytrance", "zqtrance"]

        r = c.put(f"/api/admin/albums/{ids['dnb']}/tags", json={"tags": ["zqtrance", "zq drum  & bass", "ZQTRANCE"]}).json()
        assert r["own"] is True and r["removed_everywhere"] == []
        assert [(t["name"], t["added"]) for t in r["tags"]] == [("zqtrance", False), ("zq drum & bass", True)]
        assert r["taken_off"] == ["zqpsytrance"]

        page = _album(ids["dnb"])
        assert page["artist_tags"] == ["zqtrance", "zq drum & bass", "Electronic"] and page["own_tags"] is True
        assert _album(ids["psy"])["artist_tags"] == ["zqpsytrance", "zqtrance"]        # the other album: its artist's
        # a song of nobody's with a page has the album's; one credited to its own artist, theirs
        assert _songs(ids["a"], ids["b"], ids["c"]) == {"a": ["zqtrance", "zq drum & bass", "Electronic"],
                                                        "b": ["zqneurofunk"], "c": ["zqpsytrance", "zqtrance"]}
        assert _tagged("zqpsytrance") == {"c"}
        assert _tagged("ZQ Drum & Bass") == {"a", "b"}
        assert _tagged("zqtrance") == {"a", "b", "c"}

        # renamed in Admin → Tags: the album's follows, and is found by its new name
        c.put(f"/api/admin/albums/{ids['dnb']}/tags", json={"tags": ["zqdnb"]}).raise_for_status()
        c.post("/api/admin/tags/merge", json={"names": ["zqdnb"], "into": "zq drum & bass"}).raise_for_status()
        assert _album(ids["dnb"])["artist_tags"] == ["zq drum & bass", "Electronic"]
        assert _tagged("zq drum & bass") == {"a", "b"}
        # removed everywhere: not shown, and said so
        r = c.put(f"/api/admin/albums/{ids['dnb']}/tags", json={"tags": ["zqdnb", "zqgone"]})
        c.post("/api/admin/tags/remove", json={"names": ["zqgone"]}).raise_for_status()
        assert _album(ids["dnb"])["artist_tags"] == ["zq drum & bass", "Electronic"]
        assert c.put(f"/api/admin/albums/{ids['dnb']}/tags", json={"tags": ["zqgone"]}).json()["removed_everywhere"] == ["zqgone"]

        # its artist's again
        r = c.put(f"/api/admin/albums/{ids['dnb']}/tags", json={"tags": None}).json()
        assert r["own"] is False and _album(ids["dnb"])["own_tags"] is False
        assert _tagged("zqpsytrance") == {"a", "b", "c"} and _tagged("zq drum & bass") == set()
        assert c.get("/api/admin/albums/999999/tags").status_code == 404
    finally:
        _clean()


def test_no_own_tags_no_rules_read():
    """Albums without tags of their own cost nothing: their artist's, as before."""
    with db.session() as s:
        assert library.album_tags(s, []) == {}
        assert tagging.album_names(SimpleNamespace(own_tags=None), tagging.Rules(s)) is None
