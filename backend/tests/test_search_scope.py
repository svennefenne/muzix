"""The search field searches the section it's in (music, VGM, audiobooks, podcasts, radio), or everything with
a * first: /api/search's scope. Without one, the library as before (older apps)."""
from types import SimpleNamespace

from sqlalchemy import delete

from muzix import db, scanner
from muzix.api import library as api
from muzix.models import Album, Artist, Book, Episode, Feed, Root, Station, Subscription, Track, User


def _library():
    with db.session() as s:
        u, other = User(username="scope-searcher", password_hash="x"), User(username="scope-other", password_hash="x")
        root = Root(path="/scope-search", kind="music")
        s.add_all([u, other, root])
        s.flush()
        ar = Artist(name="Scopewave")
        s.add(ar)
        s.flush()
        music = Album(title="Scopewave Sun", artist_name=ar.name, artist_id=ar.id, folder="/scope-search/a", key="scope-a")
        game = Album(title="Scopewave Quest", kind="vgm", artist_name=ar.name, artist_id=ar.id, folder="/scope-search/b",
                     key="scope-b")
        s.add_all([music, game])
        s.flush()
        s.add_all([
            Track(root_id=root.id, path="/scope-search/a/1.mp3", title="Scopewave Song", artist=ar.name, album="Scopewave Sun",
                  album_id=music.id, artist_id=ar.id),
            Track(root_id=root.id, path="/scope-search/b/1.vgm", kind="vgm", title="Scopewave Theme", artist=ar.name,
                  album="Scopewave Quest", album_id=game.id, artist_id=ar.id),
            Book(root_id=root.id, title="Scopewave Stories", author="Writer", path="/scope-search/book"),
        ])
        mine, theirs = Feed(url="https://scope.test/mine", title="Scopewave Cast"), Feed(url="https://scope.test/theirs",
                                                                                          title="Scopewave Talk")
        s.add_all([mine, theirs])
        s.flush()
        s.add_all([Subscription(user_id=u.id, feed_id=mine.id), Subscription(user_id=other.id, feed_id=theirs.id),
                   Episode(feed_id=mine.id, guid="1", title="Scopewave Episode"),
                   Episode(feed_id=theirs.id, guid="1", title="Scopewave Episode Too"),
                   Station(user_id=u.id, name="Scopewave FM", url="https://scope.test/fm"),
                   Station(user_id=other.id, name="Scopewave Radio", url="https://scope.test/radio")])
        uid = u.id
    scanner.rebuild_search()
    return uid


def _clean_up():
    """The test database is shared: what's made here would turn up in other tests' lists."""
    with db.session() as s:
        s.execute(delete(Feed).where(Feed.url.like("https://scope.test/%")))
        s.execute(delete(Album).where(Album.key.in_(["scope-a", "scope-b"])))
        s.execute(delete(Artist).where(Artist.name == "Scopewave"))
        s.execute(delete(Root).where(Root.path == "/scope-search"))
        s.execute(delete(User).where(User.username.in_(["scope-searcher", "scope-other"])))
    scanner.rebuild_search()


def _found(uid, scope):
    with db.session() as s:
        r = api.search("scopewave", SimpleNamespace(state=SimpleNamespace()), db=s, user=s.get(User, uid), limit=20,
                       scope=scope)
    names = {k: sorted(x.get("title") or x.get("name") for x in v) for k, v in r.items()}
    return {k: v for k, v in names.items() if v}


def test_each_section_searches_its_own_and_a_star_everything():
    uid = _library()
    try:
        _check(uid)
    finally:
        _clean_up()


def _check(uid):
    assert _found(uid, "music") == {"artists": ["Scopewave"], "albums": ["Scopewave Sun"], "tracks": ["Scopewave Song"]}
    assert _found(uid, "vgm") == {"albums": ["Scopewave Quest"], "tracks": ["Scopewave Theme"]}
    assert _found(uid, "audiobooks") == {"books": ["Scopewave Stories"]}
    # the user's own podcasts and saved stations: not someone else's
    assert _found(uid, "podcasts") == {"podcasts": ["Scopewave Cast"], "episodes": ["Scopewave Episode"]}
    assert _found(uid, "radio") == {"stations": ["Scopewave FM"]}
    assert _found(uid, "all") == {
        "artists": ["Scopewave"], "albums": ["Scopewave Quest", "Scopewave Sun"], "tracks": ["Scopewave Song", "Scopewave Theme"],
        "books": ["Scopewave Stories"], "podcasts": ["Scopewave Cast"], "episodes": ["Scopewave Episode"],
        "stations": ["Scopewave FM"]}
    # an older app, asking without a scope: the library as before
    assert _found(uid, "") == {
        "artists": ["Scopewave"], "albums": ["Scopewave Quest", "Scopewave Sun"], "tracks": ["Scopewave Song", "Scopewave Theme"],
        "books": ["Scopewave Stories"]}
