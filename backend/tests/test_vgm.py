"""The VGM page's tiles: picking "Game soundtracks" (VGM without a chip system) lists and
shuffles those albums, just as picking a real system does."""
from muzix import db
from muzix.api import library
from muzix.models import Album, Root, Track, User


def test_soundtracks_without_a_system_can_be_picked():
    with db.session() as s:
        user = User(username="vgm-tester", password_hash="x")
        root = Root(path="/vgm-test", kind="vgm")
        s.add_all([user, root])
        s.flush()
        ost = Album(kind="vgm", title="Some Game OST", folder="/vgm-test/ost", key="/vgm-test/ost|ost")
        nes = Album(kind="vgm", title="Some NES Game", folder="/vgm-test/nes", key="/vgm-test/nes|nes")
        s.add_all([ost, nes])
        s.flush()
        s.add_all([
            Track(root_id=root.id, path="/vgm-test/ost/01.mp3", kind="vgm", format="mp3", title="Title", album_id=ost.id),
            Track(root_id=root.id, path="/vgm-test/nes/game.nsf", subsong=0, kind="vgm", format="nsf", title="Stage 1",
                  album_id=nes.id, extra={"system": "NES"}),
        ])
        s.commit()

        tiles = {t["system"]: t for t in library.vgm_systems(s, user)}
        assert library.NO_SYSTEM in tiles and "NES" in tiles

        def albums(system):
            return [a["title"] for a in library.albums(s, user, kind="vgm", system=system, genre=None, artist_id=None,
                                                         liked_only=False, sort="name", limit=60, offset=0)["items"]]

        assert "Some Game OST" in albums(library.NO_SYSTEM) and "Some NES Game" not in albums(library.NO_SYSTEM)
        assert albums("NES") == ["Some NES Game"]
        shuffled = library.random_tracks(s, user, kind="vgm", genre=None, artist_id=None, album_id=None,
                                         system=library.NO_SYSTEM, tag=None, n=50)
        assert shuffled and all(t["album_id"] == ost.id for t in shuffled)
