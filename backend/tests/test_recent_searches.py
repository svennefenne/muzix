"""Recent searches, as on Spotify: what was picked from search results, newest first."""
from muzix import db
from muzix.api import library as api
from muzix.models import Album, Artist, Book, Root, Track, User


def test_recent_searches_keep_the_latest_picks_as_they_are_now():
    with db.session() as s:
        u, other = User(username="searcher", password_hash="x"), User(username="other-searcher", password_hash="x")
        root = Root(path="/recent-searches", kind="music")
        s.add_all([u, other, root])
        s.flush()
        ar = Artist(name="Searched Artist")
        s.add(ar)
        s.flush()
        al = Album(title="Searched Album", artist_name=ar.name, artist_id=ar.id, folder="/recent-searches", key="recent-searches")
        s.add(al)
        s.flush()
        t = Track(root_id=root.id, path="/recent-searches/a.mp3", title="Searched Song", artist=ar.name, album_id=al.id, artist_id=ar.id)
        b = Book(root_id=root.id, title="Searched Book", author="Writer", path="/recent-searches/book")
        s.add_all([t, b])
        s.flush()
        uid, oid, ids = u.id, other.id, {"artist": ar.id, "album": al.id, "track": t.id, "book": b.id}

    def call(fn, *args, user=uid):
        with db.session() as s:
            return fn(*args, db=s, user=s.get(User, user))

    def recent(user=uid):
        return [(r["kind"], r["item"].get("title") or r["item"].get("name")) for r in call(api.recent_searches, user=user)]

    for kind in ("track", "artist", "book", "album", "artist"):     # the artist again: it moves to the top
        call(api.remember_search, api.Picked(kind=kind, id=ids[kind]))
    assert recent() == [("artist", "Searched Artist"), ("album", "Searched Album"), ("book", "Searched Book"), ("track", "Searched Song")]
    assert recent(oid) == []
    assert call(api.recent_searches)[3]["item"]["stream"]       # a song comes as search gives it, ready to play

    call(api.forget_search, "book", ids["book"])
    assert [k for k, _ in recent()] == ["artist", "album", "track"]
    with db.session() as s:          # gone from the library: gone from the list
        s.delete(s.get(Track, ids["track"]))
    assert [k for k, _ in recent()] == ["artist", "album"]

    # only the latest 30 are kept
    for n in range(40):
        call(api.remember_search, api.Picked(kind="album", id=100000 + n))
    with db.session() as s:
        from muzix.models import RecentSearch
        assert s.query(RecentSearch).filter_by(user_id=uid).count() == api.KEEP_RECENT

    call(api.clear_searches)
    assert recent() == []
