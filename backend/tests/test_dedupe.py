"""The same album in more than one library of the Library Network: one copy is listed, the
main library's (or the first in line's); what someone saved keeps the copy they saved."""
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, select

from muzix import db, mirror, network
from muzix.models import Album, Artist, Book, Peer, Root, Setting, Track


@pytest.fixture
def libraries():
    """Ours and two linked servers', with albums some of them share."""
    with db.session() as s:
        s.execute(delete(Setting).where(Setting.key == "network_main"))
        p1 = Peer(server_id="dedupe-one", name="One", sent=True, received=True)
        p2 = Peer(server_id="dedupe-two", name="Two", sent=True, received=True)
        roots = [Root(path=p, kind="music") for p in ("/dedupe-ours", "peer:dedupe-one", "peer:dedupe-two")]
        s.add_all([p1, p2, *roots])
        s.flush()
        made = {}

        def album(lib, title, artist, year=0, mbid="", tracks=1):
            peer = {"ours": None, "one": p1.id, "two": p2.id}[lib]
            root = roots[["ours", "one", "two"].index(lib)]
            a = Album(title=title, artist_name=artist, year=year, mbid=mbid, folder=f"{root.path}/{title}",
                      key=f"{root.path}:{title}:{year}", peer_id=peer)
            s.add(a)
            s.flush()
            s.add_all([Track(root_id=root.id, path=f"{root.path}/{title}/{year}/{n}", title=f"{title} {n}",
                             album_id=a.id, peer_id=peer) for n in range(tracks)])
            made[(lib, title, year)] = a.id

        album("ours", "Dupe Album", "The Dupe Band", tracks=2)
        album("one", "Dupe Album!", "Dupe Band", tracks=2)            # the same, written another way
        album("one", "Only There", "Dupe Band")
        album("ours", "Hits", "Various Artists", 1999)
        album("one", "Hits", "Various Artists", 2005)                # another compilation of the name
        album("ours", "Dupe Remaster", "Dupe Band", mbid="rel-1")
        album("two", "Dupe Remaster (2011)", "Dupe Band", mbid="rel-1")   # the same release by its id
        album("one", "Twice Theirs", "Dupe Band")
        album("two", "Twice Theirs", "Dupe Band")
        s.add_all([Book(root_id=roots[0].id, path="/dedupe-ours/book", title="Dupe Book", author="Writer"),
                   Book(root_id=roots[2].id, path="peer:dedupe-two/books/1", title="Dupe book", author="writer",
                        peer_id=p2.id)])
        s.add(Track(root_id=roots[1].id, path="peer:dedupe-one/loose", title="Loose", peer_id=p1.id))
        s.flush()
        ids = {"one": p1.id, "two": p2.id}
    yield made, ids
    with db.session() as s:
        s.execute(delete(Album).where(Album.id.in_(list(made.values()))))
        s.execute(delete(Root).where(Root.path.in_(["/dedupe-ours", "peer:dedupe-one", "peer:dedupe-two"])))
        s.execute(delete(Peer).where(Peer.server_id.in_(["dedupe-one", "dedupe-two"])))
        s.execute(delete(Setting).where(Setting.key == "network_main"))


def shadowed(model=Album):
    with db.session() as s:
        return set(s.scalars(select(model.id).where(model.shadowed.is_(True))))


def listed(model, copies=False, network=True):
    """What a page lists (a session that hides), or what one keeps copies for; for someone who
    left the network's music out, with `network` False."""
    s = db.SessionLocal()
    s.info["hide"], s.info["copies"], s.info["viewer"] = True, copies, SimpleNamespace(network=network)
    try:
        return set(s.scalars(select(model.id)))
    finally:
        s.close()


def test_ours_first_then_the_others_in_the_order_they_were_linked(libraries):
    made, _ = libraries
    got = mirror.dedupe()
    assert shadowed() == {made["one", "Dupe Album!", 0], made["two", "Dupe Remaster (2011)", 0],
                          made["two", "Twice Theirs", 0]}
    assert got["albums"] == 3 and got["books"] == 1
    with db.session() as s:
        (theirs,) = s.scalars(select(Book.id).where(Book.peer_id.is_not(None), Book.path == "peer:dedupe-two/books/1"))
        assert shadowed(Book) == {theirs}
        # its songs with it; a song on no album never
        dupe = made["one", "Dupe Album!", 0]
        assert {t.shadowed for t in s.scalars(select(Track).where(Track.album_id == dupe))} == {True}
        assert not s.scalar(select(Track.shadowed).where(Track.path == "peer:dedupe-one/loose"))

    # pages list one copy; what someone saved keeps theirs
    assert dupe not in listed(Album) and made["ours", "Dupe Album", 0] in listed(Album)
    assert dupe in listed(Album, copies=True)
    assert not ({made["ours", "Hits", 1999], made["one", "Hits", 2005]} - listed(Album))     # not the same


def test_the_main_library_comes_first(libraries):
    made, ids = libraries
    network.set_main("dedupe-two")
    mirror.dedupe()
    assert shadowed() == {made["ours", "Dupe Remaster", 0], made["one", "Twice Theirs", 0],
                          made["one", "Dupe Album!", 0]}         # ours is first after the main one
    network.set_main("dedupe-one")
    mirror.dedupe()
    assert shadowed() == {made["ours", "Dupe Album", 0], made["two", "Dupe Remaster (2011)", 0],
                          made["two", "Twice Theirs", 0]}
    with db.session() as s:
        assert {t.shadowed for t in s.scalars(select(Track).where(Track.album_id == made["ours", "Dupe Album", 0]))} \
            == {True}
        assert not any(t.shadowed for t in s.scalars(select(Track).where(Track.album_id == made["one", "Dupe Album!", 0])))
    network.set_main(None)
    mirror.dedupe()
    assert made["ours", "Dupe Album", 0] not in shadowed()


def test_names_as_compared():
    assert mirror._name("The Beatles") == mirror._name("beatles") == "beatles"
    assert mirror._name("Motörhead") == mirror._name("MOTORHEAD")
    assert mirror._name("Live: at the BBC!") == mirror._name("Live at the BBC")
    assert mirror._name("The") == "the"


def test_leaving_the_networks_music_out(libraries):
    made, _ = libraries
    with db.session() as s:
        theirs_only = Artist(name="Dedupe Theirs Only")
        ours = Artist(name="Dedupe Ours")
        s.add_all([theirs_only, ours])
        s.flush()
        s.get(Album, made["one", "Only There", 0]).artist_id = theirs_only.id
        s.get(Album, made["ours", "Hits", 1999]).artist_id = ours.id
        ids = theirs_only.id, ours.id
    network.set_main("dedupe-one")          # our own copy of Dupe Album is the shadowed one
    mirror.dedupe()
    everything, own = listed(Album), listed(Album, network=False)
    assert made["ours", "Dupe Album", 0] not in everything and made["ours", "Dupe Album", 0] in own
    assert made["one", "Only There", 0] in everything and made["one", "Only There", 0] not in own
    assert {made[k] for k in made if k[0] == "ours"} <= own
    assert not own & {made[k] for k in made if k[0] != "ours"}
    with db.session() as s:
        our_songs = set(s.scalars(select(Track.id).where(Track.root_id.in_(
            select(Root.id).where(Root.path == "/dedupe-ours")))))
        their_songs = set(s.scalars(select(Track.id).where(Track.peer_id.is_not(None))))
    assert our_songs <= listed(Track, network=False) and not their_songs & listed(Track, network=False)
    assert ids[0] in listed(Artist) and ids[0] not in listed(Artist, network=False) and ids[1] in listed(Artist, network=False)
    with db.session() as s:
        for i in ids:
            s.delete(s.get(Artist, i))
