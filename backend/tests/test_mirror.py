"""The Library Network's libraries: a server's catalog, exported a page at a time and mirrored on
another (here both are this test database: what's mirrored is told apart by its peer_id)."""
import json

import httpx
import pytest
from sqlalchemy import select

from muzix import art, db, mirror
from muzix.models import (Album, Artist, Book, BookPart, FilePlaylist, FilePlaylistItem, Like, Peer, Root, Track,
                          User)


class Ctx:
    def log(self, line):
        pass

    def update(self, *a, **k):
        pass

    def check(self):
        pass


@pytest.fixture(scope="module")
def library():
    """Our own: an album of two songs by an artist with genres, a hidden album, a book, a playlist file."""
    with db.session() as s:
        root, books = Root(path="/mirror-music", kind="music"), Root(path="/mirror-books", kind="audiobooks")
        s.add_all([root, books])
        s.flush()
        ar = Artist(name="Mirror Band", tags=[["shoegaze", 1.0]])
        s.add(ar)
        s.flush()
        al = Album(title="Mirror Album", artist_name=ar.name, artist_id=ar.id, folder="/mirror-music/a",
                   key="mirror-a", art="/mirror-music/a/cover.jpg", year=1991)
        gone = Album(title="Mirror Hidden", artist_name=ar.name, artist_id=ar.id, folder="/mirror-music/h",
                     key="mirror-h", hidden=True)
        s.add_all([al, gone])
        s.flush()
        t1 = Track(root_id=root.id, path="/mirror-music/a/1.flac", title="Mirror One", artist=ar.name,
                   albumartist=ar.name, album=al.title, album_id=al.id, artist_id=ar.id, track_no=1,
                   duration=200.5, format="flac", extra={"comment": "hi"})
        t2 = Track(root_id=root.id, path="/mirror-music/a/2.flac", title="Mirror Two", artist=ar.name,
                   album=al.title, album_id=al.id, artist_id=ar.id, track_no=2, duration=180, format="flac")
        th = Track(root_id=root.id, path="/mirror-music/h/1.mp3", title="Mirror Secret", artist=ar.name,
                   album_id=gone.id, artist_id=ar.id, hidden=True)
        b = Book(root_id=books.id, path="/mirror-books/b", title="Mirror Book", author="Writer", duration=7200,
                 chapters=[{"title": "One", "start": 0}])
        s.add_all([t1, t2, th, b])
        s.flush()
        s.add_all([BookPart(book_id=b.id, position=i, path=f"/mirror-books/b/{i}.mp3", title=f"Part {i}",
                            duration=3600, offset=3600 * i, format="mp3") for i in range(2)])
        fp = FilePlaylist(root_id=root.id, path="/mirror-music/mix.m3u", name="Mirror Mix", entries=3)
        s.add(fp)
        s.flush()
        s.add_all([FilePlaylistItem(playlist_id=fp.id, position=0, track_id=t2.id),
                   FilePlaylistItem(playlist_id=fp.id, position=1, track_id=th.id),
                   FilePlaylistItem(playlist_id=fp.id, position=2, track_id=t1.id)])
        friend = Peer(server_id="friend-server", name="Friend", address="https://friend.example",
                      sent=True, received=True, key="k" * 40)
        s.add(friend)
        s.flush()
        return {"artist": ar.id, "album": al.id, "t1": t1.id, "t2": t2.id, "peer": friend.id}


def catalog():
    """All of what this server shares, fetched a small page at a time."""
    out = {}
    for part in mirror.PARTS:
        rows, after = [], 0
        while True:
            page = json.loads(json.dumps(mirror.export(part, after, limit=2)))     # as it goes over the wire
            rows += [dict(zip(page["fields"], r)) for r in page["rows"]]
            if page["next"] is None:
                break
            after = page["next"]
        out[part] = rows
    return out


def mirrored(model, peer):
    with db.session() as s:
        return list(s.scalars(select(model).where(model.peer_id == peer).execution_options(include_hidden=True)))


def test_what_a_server_shares(library):
    cat = catalog()
    titles = [t["title"] for t in cat["tracks"]]
    assert "Mirror One" in titles and "Mirror Two" in titles and "Mirror Secret" not in titles   # hidden stays home
    assert "Mirror Hidden" not in [a["title"] for a in cat["albums"]]
    (al,) = [a for a in cat["albums"] if a["title"] == "Mirror Album"]
    assert al["artist"] == "Mirror Band" and al["added_at"]
    assert al["art"] == art.version("album", library["album"]) >= 1                   # its picture's version
    (t,) = [t for t in cat["tracks"] if t["title"] == "Mirror One"]
    assert t["artist_ref"] == "Mirror Band" and t["extra"] == {"comment": "hi"} and "path" not in t
    (b,) = [b for b in cat["books"] if b["title"] == "Mirror Book"]
    assert [p[1] for p in b["parts"]] == ["Part 0", "Part 1"]
    (p,) = [p for p in cat["playlists"] if p["name"] == "Mirror Mix"]
    assert p["tracks"] == [library["t2"], library["t1"]]                           # the hidden song left out


def test_mirrored_and_kept_in_step(library):
    peer = library["peer"]
    cat = catalog()
    counts = mirror.store(peer, "friend-server", "Friend", cat)
    assert counts["tracks"] == len(cat["tracks"]) and counts["albums"] == len(cat["albums"])

    tracks = {t.title: t for t in mirrored(Track, peer)}
    one = tracks["Mirror One"]
    assert one.path.startswith("peer:friend-server/tracks/") and one.duration == 200.5
    assert one.artist_id == library["artist"]                  # the same artist: one artist page for both
    (alb,) = [a for a in mirrored(Album, peer) if a.title == "Mirror Album"]
    assert one.album_id == alb.id != library["album"] and alb.folder.startswith("peer:friend-server/albums/")
    version = art.version("album", library["album"])
    assert alb.art == f"peer:friend-server/albums/{library['album']}/{version}"   # where its cover is, and which
    (book,) = [b for b in mirrored(Book, peer) if b.title == "Mirror Book"]
    with db.session() as s:
        assert [p.title for p in s.scalars(select(BookPart).where(BookPart.book_id == book.id)
                                           .order_by(BookPart.position))] == ["Part 0", "Part 1"]
        (lst,) = [p for p in mirrored(FilePlaylist, peer) if p.name == "Mirror Mix"]
        assert list(s.scalars(select(FilePlaylistItem.track_id).where(FilePlaylistItem.playlist_id == lst.id)
                              .order_by(FilePlaylistItem.position))) == [tracks["Mirror Two"].id, one.id]
        assert s.scalar(select(Root.kind).where(Root.path == "peer:friend-server")) == "peer"

    # what's mirrored isn't shared on: a third server gets only what's ours
    with db.session() as s:
        s.add(Artist(name="Only Theirs"))
        s.flush()
        s.add(Album(title="Their Own", artist_name="Only Theirs", artist_id=s.scalar(select(Artist.id).where(
            Artist.name == "Only Theirs")), folder="peer:friend-server/albums/x", key="peer:friend-server:x",
            peer_id=peer))
    again = catalog()
    assert len(again["tracks"]) == len(cat["tracks"]) and "Their Own" not in [a["title"] for a in again["albums"]]
    assert "Only Theirs" not in [a["name"] for a in again["artists"]] and "Mirror Band" in [a["name"] for a in again["artists"]]

    # a like here, then the other server changes a title and drops a song: same rows, same like
    with db.session() as s:
        u = User(username="mirror-liker", password_hash="x")
        s.add(u)
        s.flush()
        s.add(Like(user_id=u.id, item_type="track", item_id=one.id))
    (t1,) = [t for t in cat["tracks"] if t["title"] == "Mirror One"]
    t1["title"] = "Mirror One (Remastered)"
    cat["tracks"] = [t for t in cat["tracks"] if t["title"] != "Mirror Two"]
    cat["books"][0]["parts"] = cat["books"][0]["parts"][:1]
    mirror.store(peer, "friend-server", "Friend", cat)
    tracks = {t.title: t for t in mirrored(Track, peer)}
    assert tracks["Mirror One (Remastered)"].id == one.id and "Mirror Two" not in tracks
    with db.session() as s:
        assert s.scalar(select(Like.item_id).where(Like.item_type == "track", Like.item_id == one.id)) == one.id
        book_id = cat["books"][0]["id"]
        mine = s.scalar(select(Book.id).where(Book.path == f"peer:friend-server/books/{book_id}"))
        assert s.scalar(select(BookPart.title).where(BookPart.book_id == mine)) is not None
        assert len(list(s.scalars(select(BookPart).where(BookPart.book_id == mine)))) == 1


def test_a_sync_over_the_wire_then_the_server_leaves(library, monkeypatch):
    peer = library["peer"]

    def answer(req: httpx.Request) -> httpx.Response:
        assert req.headers["authorization"] == "Bearer " + "k" * 40
        part = req.url.path.rsplit("/", 1)[1]
        page = mirror.export(part, int(req.url.params["after"]), int(req.url.params["limit"]))
        return httpx.Response(200, content=json.dumps(page))

    real = httpx.Client
    monkeypatch.setattr(mirror.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(answer), **kw))
    assert mirror.sync_peer(Ctx(), peer)
    with db.session() as s:
        p = s.get(Peer, peer)
        assert p.synced_at and not p.error and p.counts["tracks"] >= 2
    assert {"Mirror One", "Mirror Two"} <= {t.title for t in mirrored(Track, peer)}

    mirror.drop_job(Ctx(), "friend-server")
    assert mirrored(Track, peer) == [] and mirrored(Album, peer) == [] and mirrored(Book, peer) == []
    with db.session() as s:
        assert s.scalar(select(Root).where(Root.path == "peer:friend-server")) is None
        assert s.get(Track, library["t1"]) is not None                     # our own untouched


def test_a_server_that_doesnt_answer(library, monkeypatch):
    real = httpx.Client
    monkeypatch.setattr(mirror.httpx, "Client",
                        lambda **kw: real(transport=httpx.MockTransport(lambda r: httpx.Response(500)), **kw))
    assert not mirror.sync_peer(Ctx(), library["peer"])
    with db.session() as s:
        assert "HTTP 500" in s.get(Peer, library["peer"]).error
