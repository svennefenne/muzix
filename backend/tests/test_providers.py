"""The edit window's outside sources: Discogs with the admin's token, fanart.tv found through
MusicBrainz ids, and each source's own cover coming along with a picked album."""
import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from muzix import providers, settings
from muzix.api import manage as manage_api
from muzix.security import admin_user


class NoWait:
    def wait(self): pass


@pytest.fixture
def web(monkeypatch):
    """Answers from a dict of url → JSON (or a function of the request); every request is kept."""
    asked, answers = [], {}

    def handle(req: httpx.Request):
        asked.append(req)
        url = str(req.url).split("?")[0]
        a = answers.get(url)
        if callable(a):
            a = a(req)
        if a is None:
            return httpx.Response(404, json={"error": "Not found"})
        return a if isinstance(a, httpx.Response) else httpx.Response(200, json=a)

    monkeypatch.setattr(providers, "_client", lambda: httpx.Client(transport=httpx.MockTransport(handle)))
    monkeypatch.setattr(providers, "_mb", NoWait())
    return asked, answers


MASTERS = {"results": [
    {"type": "master", "id": 13814, "title": "Nirvana (2) - Nevermind", "year": "1991", "genre": ["Rock"],
     "format": ["Vinyl", "LP", "Album", "Vinyl"], "label": ["DGC", "Sub Pop"], "country": "US", "uri": "/master/13814-Nirvana-Nevermind",
     "thumb": "https://i.discogs.com/t150.jpeg", "cover_image": "https://i.discogs.com/full600.jpeg"},
    {"type": "master", "id": 2, "title": "Nirvana - Bleach", "year": "1989", "uri": "/master/2",
     "thumb": "", "cover_image": "https://st.discogs.com/images/spacer.gif"},
    {"type": "master", "id": 3, "title": "Nirvana - In Utero", "year": "1993", "uri": "/master/3",
     "thumb": "https://i.discogs.com/t3.jpeg", "cover_image": "https://i.discogs.com/f3.jpeg"},
]}


def test_discogs_needs_a_token(web):
    asked, _ = web
    settings.set_many({"discogs_token": ""})
    with pytest.raises(providers.SourceError, match="access token"):
        providers._discogs("album", "Nirvana", "Nevermind", "", None, None)
    assert not asked


def test_discogs_albums_and_artists(web):
    asked, answers = web
    settings.set_many({"discogs_token": "tok"})
    answers["https://api.discogs.com/database/search"] = lambda req: (
        MASTERS if req.url.params["type"] == "master" else
        {"results": [{"type": "artist", "id": 125246, "title": "Nirvana (2)", "uri": "/artist/125246", "thumb": "https://i.discogs.com/a.jpeg"}]})
    albums = providers._discogs("album", "Nirvana", "Nevermind", "", None, None)
    assert asked[0].headers["Authorization"] == "Discogs token=tok"
    assert asked[0].url.params["artist"] == "Nirvana" and asked[0].url.params["release_title"] == "Nevermind"
    assert len(asked) == 1          # three masters: no need for single releases
    first = albums[0]
    assert first == {"source": "discogs", "kind": "album", "id": "master/13814", "title": "Nevermind", "artist": "Nirvana",
                     "year": 1991, "genre": "Rock", "country": "US", "label": "DGC", "format": "Vinyl, LP, Album",
                     "cover": "https://i.discogs.com/t150.jpeg", "url": "https://www.discogs.com/master/13814-Nirvana-Nevermind"}
    assert albums[1]["cover"] is None
    artists = providers._discogs("artist", "Nirvana", "", "", None, None)
    assert artists[0]["title"] == "Nirvana" and artists[0]["id"] == "125246"
    assert providers._discogs("track", "Nirvana", "Lithium", "", None, None) == []

    found = providers.covers("album", "Nirvana", "Nevermind")
    discogs = [c for c in found["results"] if c["source"] == "Discogs"]
    assert [c["url"] for c in discogs] == ["https://i.discogs.com/full600.jpeg", "https://i.discogs.com/f3.jpeg"]   # no spacer
    assert discogs[0]["title"] == "Nevermind (1991, US, Vinyl, LP, Album)"


def test_discogs_track_list_and_cover(web):
    _, answers = web
    settings.set_many({"discogs_token": "tok"})
    answers["https://api.discogs.com/releases/99"] = {
        "title": "Live Set", "year": 2001, "genres": ["Electronic"],
        "artists": [{"name": "Orbital (2)", "join": "&"}, {"name": "Guest*", "join": ""}],
        "images": [{"type": "secondary", "uri": "https://i.discogs.com/back.jpeg"}, {"type": "primary", "uri": "https://i.discogs.com/front.jpeg"}],
        "tracklist": [
            {"type_": "heading", "position": "", "title": "Side One"},
            {"type_": "track", "position": "A1", "title": "Opening", "duration": "5:00"},
            {"type_": "track", "position": "A2", "title": "Second", "duration": "", "artists": [{"name": "Other (3)", "join": ""}]},
            {"type_": "track", "position": "B1", "title": "Third", "duration": "1:02:03"},
            {"type_": "track", "position": "2-01", "title": "Disc Two", "duration": "3:15"},
            {"type_": "index", "position": "2-02", "title": "Suite", "sub_tracks": []},
        ]}
    d = providers.details("discogs", "album", "release/99")
    assert d["artist"] == "Orbital & Guest" and d["year"] == 2001 and d["genre"] == "Electronic"
    assert d["cover"] == "https://i.discogs.com/front.jpeg"
    assert [(t["disc"], t["no"], t["title"], t["artist"], t["length"]) for t in d["tracks"]] == [
        (1, 1, "Opening", "Orbital & Guest", 300), (1, 2, "Second", "Other", 0), (1, 3, "Third", "Orbital & Guest", 3723),
        (2, 1, "Disc Two", "Orbital & Guest", 195), (2, 2, "Suite", "Orbital & Guest", 0)]
    with pytest.raises(providers.SourceError):
        providers.details("discogs", "album", "label/5")


def test_a_discogs_album_reaches_its_details_by_the_route(web):
    """The edit window asks for master%2F99: the slash in the id mustn't stop the route."""
    _, answers = web
    settings.set_many({"discogs_token": "tok"})
    answers["https://api.discogs.com/masters/99"] = {"title": "Live Set", "artists": [{"name": "Orbital (2)", "join": ""}],
                                                     "tracklist": [{"type_": "track", "position": "1", "title": "One"}]}
    app = FastAPI()
    app.include_router(manage_api.router)
    app.dependency_overrides[admin_user] = lambda: None
    app.dependency_overrides[manage_api.get_db] = lambda: None
    r = TestClient(app).get("/api/manage/lookup/discogs/album/master%2F99")
    assert r.status_code == 200 and r.json()["title"] == "Live Set" and r.json()["tracks"][0]["title"] == "One"


def test_fanart_album_covers_by_release_group(web):
    asked, answers = web
    settings.set_many({"fanarttv_api_key": "personal"})
    answers["https://musicbrainz.org/ws/2/release/rel-1"] = {"id": "rel-1", "release-group": {"id": "rg-1"}}
    answers["https://webservice.fanart.tv/v3/music/albums/rg-1"] = lambda req: (
        httpx.Response(401, json={"error": "invalid API key"}) if "api-key" in req.headers else
        {"albums": {"rg-1": {"albumcover": [
            {"url": "https://assets.fanart.tv/fanart/music/x/albumcover/a.jpg", "likes": "1"},
            {"url": "https://assets.fanart.tv/fanart/music/x/albumcover/b.jpg", "likes": "7"}]}}})
    found = providers.covers("album", "Nirvana", "Nevermind", mbid="rel-1")
    fanart = [c for c in found["results"] if c["source"] == "fanart.tv"]
    assert [c["url"].rsplit("/", 1)[1] for c in fanart] == ["b.jpg", "a.jpg"]        # most liked first
    assert fanart[0]["thumb"] == "https://assets.fanart.tv/preview/music/x/albumcover/b.jpg"
    tried = [r for r in asked if "fanart.tv" in str(r.url)]
    assert [("api-key" in r.headers, "client-key" in r.headers) for r in tried] == [(True, False), (False, True)]
    assert "personal" not in str(tried[0].url)          # the key travels in a header, out of the log


def test_fanart_artist_without_an_id(web):
    asked, answers = web
    settings.set_many({"fanarttv_api_key": "project"})
    answers["https://musicbrainz.org/ws/2/artist"] = {"artists": [{"id": "wrong", "name": "Nirvana UK"}, {"id": "right", "name": "nirvana"}]}
    answers["https://webservice.fanart.tv/v3/music/right"] = {"name": "Nirvana", "artistthumb": [
        {"url": "https://assets.fanart.tv/fanart/music/right/artistthumb/n.jpg", "likes": "2"}]}
    found = providers.covers("artist", "Nirvana")
    assert [c["title"] for c in found["results"] if c["source"] == "fanart.tv"] == ["Nirvana"]
    settings.set_many({"fanarttv_api_key": ""})
    assert "API key" in providers.covers("artist", "Nirvana")["errors"]["fanarttv"]


def test_a_picked_album_brings_its_cover(web):
    _, answers = web
    answers["https://musicbrainz.org/ws/2/release/rel-2"] = {"id": "rel-2", "title": "Nevermind", "media": [],
                                                             "cover-art-archive": {"front": True}}
    answers["https://coverartarchive.org/release/rel-2"] = {"images": [
        {"front": False, "image": "https://caa/back.jpg", "thumbnails": {}},
        {"front": True, "image": "https://caa/front.png", "thumbnails": {"1200": "https://caa/front-1200.jpg"}}]}
    assert providers.details("musicbrainz", "album", "rel-2")["cover"] == "https://caa/front-1200.jpg"
    answers["https://musicbrainz.org/ws/2/release/rel-3"] = {"id": "rel-3", "media": [], "cover-art-archive": {"front": False}}
    assert providers.details("musicbrainz", "album", "rel-3")["cover"] is None
    answers["https://api.deezer.com/album/5"] = {"title": "N", "cover_xl": "https://dz/1000.jpg", "tracks": {"data": []}}
    assert providers.details("deezer", "album", "5")["cover"] == "https://dz/1000.jpg"
    answers["https://itunes.apple.com/lookup"] = {"results": [
        {"wrapperType": "collection", "collectionName": "N", "artworkUrl100": "https://is1/x/100x100bb.jpg"}]}
    assert providers.details("itunes", "album", "7")["cover"] == "https://is1/x/1400x1400bb.jpg"


def test_a_picked_artist_brings_their_picture(web):
    _, answers = web
    settings.set_many({"discogs_token": "tok", "fanarttv_api_key": "key"})
    answers["https://api.discogs.com/artists/69866"] = {"name": "Alice Cooper (2)", "images": [
        {"type": "secondary", "uri": "https://i.discogs.com/live.jpeg"}, {"type": "primary", "uri": "https://i.discogs.com/alice.jpeg"}]}
    assert providers.details("discogs", "artist", "69866") == {"name": "Alice Cooper", "cover": "https://i.discogs.com/alice.jpeg"}
    answers["https://api.deezer.com/artist/5"] = {"name": "Alice Cooper", "picture_xl": "https://e-cdns-images.dzcdn.net/images/artist/abc/1000x1000-000000-80-0-0.jpg"}
    assert providers.details("deezer", "artist", "5")["cover"].endswith("/abc/1000x1000-000000-80-0-0.jpg")
    answers["https://api.deezer.com/artist/6"] = {"name": "Nobody", "picture_xl": "https://e-cdns-images.dzcdn.net/images/artist//1000x1000-000000-80-0-0.jpg"}
    assert providers.details("deezer", "artist", "6")["cover"] is None       # Deezer's blank face
    # MusicBrainz has the name; fanart.tv the picture, by the same id
    answers["https://musicbrainz.org/ws/2/artist/ee58c59f"] = {"id": "ee58c59f", "name": "Alice Cooper"}
    answers["https://webservice.fanart.tv/v3/music/ee58c59f"] = {"artistthumb": [
        {"url": "https://assets.fanart.tv/fanart/music/ee58c59f/artistthumb/a.jpg", "likes": "1"},
        {"url": "https://assets.fanart.tv/fanart/music/ee58c59f/artistthumb/b.jpg", "likes": "4"}]}
    assert providers.details("musicbrainz", "artist", "ee58c59f")["cover"].endswith("/b.jpg")
    settings.set_many({"fanarttv_api_key": ""})
    assert providers.details("musicbrainz", "artist", "ee58c59f") == {"name": "Alice Cooper", "cover": None, "mbid": "ee58c59f"}
