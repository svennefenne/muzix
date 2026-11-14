"""Whose a song is (credits.py): its own artist's page when the library has one (a compilation's songs aren't
Various Artists'), and on an artist's page the others' albums they appear on."""
from muzix import credits, db
from muzix.models import Album, Artist, Root, Track
from sqlalchemy import delete, select


def test_the_names_a_tag_gives():
    assert credits.names("Zyx Band") == (["Zyx Band"], {"zyx band"})
    likely, main = credits.names("Zyx Band feat. Plonk Duo")
    assert likely == ["Zyx Band feat. Plonk Duo", "Zyx Band"] and "zyx band" in main and "plonk duo" not in main
    assert credits.names("Zyx Band (ft. Mork)")[0] == ["Zyx Band (ft. Mork)", "Zyx Band"]
    assert credits.names("Simon & Garfunk")[0] == ["Simon & Garfunk", "Simon"]
    assert credits.names("Zyx Band, Plonk Duo")[1] >= {"zyx band", "plonk duo"}
    assert credits.names("AC/DC")[0] == ["AC/DC"]            # no spaces: a name
    assert credits.names("") == ([], set())


CREATED = []      # Various Artists, when a test made it


def _library():
    """Zyx Band's album; Various Artists' compilation; Plonk Duo's album with Zyx Band as a guest; Simon & Garfunk."""
    with db.session() as s:
        zyx, plonk, va, sg, simon = (Artist(name=n) for n in ("Zyx Credits Band", "Plonk Credits Duo", "Various Artists",
                                                                "Simon Credits & Garfunk", "Simon Credits"))
        had = s.scalar(select(Artist).where(Artist.name == "Various Artists"))
        va = had or va
        root = Root(path="/cr", kind="music")
        s.add_all([zyx, plonk, va, sg, simon, root])
        s.flush()
        own = Album(title="Credits Own", folder="/cr/own", key="cr-own", artist_id=zyx.id, artist_name=zyx.name, year=2001)
        comp = Album(title="Credits Comp", folder="/cr/comp", key="cr-comp", artist_id=va.id, artist_name=va.name, year=2010)
        guest = Album(title="Credits Guest", folder="/cr/guest", key="cr-guest", artist_id=plonk.id, artist_name=plonk.name,
                      year=2005)
        s.add_all([own, comp, guest])
        s.flush()
        if not had:
            CREATED.append(va.id)

        def song(album, artist, path):
            t = Track(root_id=root.id, path=f"/cr/{path}.mp3", title=path, artist=artist, album_id=album.id, artist_id=album.artist_id,
                      kind="music", format="mp3")
            s.add(t)
            return t
        t = {
            "own": song(own, "Zyx Credits Band", "a"),
            "comp_zyx": song(comp, "Zyx Credits Band", "b"),
            "comp_nobody": song(comp, "Nobody Credits Here", "c"),
            "comp_sg": song(comp, "Simon Credits & Garfunk", "d"),
            "guest": song(guest, "Zyx Credits Band feat. Plonk Credits Duo", "e"),
            "plonk_with": song(guest, "Mork Credits & Plonk Credits Duo", "f"),
            "plonk_ft": song(guest, "Plonk Credits Duo ft. Zyx Credits Band", "g"),
        }
        s.flush()
        return ({k: v.id for k, v in t.items()}, {"zyx": zyx.id, "plonk": plonk.id, "va": va.id, "sg": sg.id,
                                                    "simon": simon.id}, {"own": own.id, "comp": comp.id, "guest": guest.id})


def _clean():
    with db.session() as s:
        s.execute(delete(Track).where(Track.path.like("/cr/%")))
        s.execute(delete(Album).where(Album.key.like("cr-%")))
        s.execute(delete(Root).where(Root.path == "/cr"))
        s.execute(delete(Artist).where(Artist.name.like("%Credits%") | Artist.id.in_(CREATED)))
    CREATED.clear()


def test_a_songs_artist_to_go_to_and_where_artists_appear():
    try:
        songs, artists, albums = _library()
        with db.session() as s:
            tracks = list(s.scalars(select(Track).where(Track.id.in_(songs.values()))))
            got = credits.credit(s, tracks)
            assert {k: got[i] for k, i in songs.items()} == {
                "own": artists["zyx"], "comp_zyx": artists["zyx"],
                "comp_nobody": None,                    # no page of their own: not Various Artists' either
                "comp_sg": artists["sg"],               # the duo's page, not Simon's
                "guest": artists["zyx"],                # Zyx Band's song, with Plonk Duo as a guest
                "plonk_with": artists["plonk"],         # on Plonk Duo's album, and they're named: theirs, as before
                "plonk_ft": artists["plonk"]}
            zyx = s.get(Artist, artists["zyx"])
            assert [a.id for a in credits.appears_on(s, zyx)] == [albums["comp"], albums["guest"]]   # newest first
            assert credits.appears_on(s, s.get(Artist, artists["simon"])) == []
            assert [a.id for a in credits.appears_on(s, s.get(Artist, artists["sg"]))] == [albums["comp"]]
            assert credits.appears_on(s, s.get(Artist, artists["va"])) == []
    finally:
        _clean()


def test_songs_say_their_own_artist(monkeypatch):
    """What the pages get: the song's artist id is its own artist's, and their tags."""
    from types import SimpleNamespace

    from muzix.api import library
    try:
        songs, artists, _ = _library()
        with db.session() as s:
            s.get(Artist, artists["zyx"]).tags = [["qwertycore", 100]]
            s.flush()
            tracks = [s.get(Track, songs[k]) for k in ("comp_zyx", "comp_nobody")]
            got = library.tracks_json(s, SimpleNamespace(id=-1), tracks)
            assert [(t["artist"], t["artist_id"]) for t in got] == [("Zyx Credits Band", artists["zyx"]),
                                                                     ("Nobody Credits Here", None)]
            assert got[0]["tags"][0] == "qwertycore"
    finally:
        _clean()
