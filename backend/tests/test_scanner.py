from muzix import db
from muzix.models import Artist
from muzix.scanner import Resolver


def test_artists_with_non_english_capitals_are_found_again():
    # SQLite's lower() only folds A-Z; this crashed the scan with a UNIQUE error
    with db.session() as s:
        for name in ("Árstíðir", "Проект Звездолет"):
            s.add(Artist(name=name))
    with db.session() as s:
        r = Resolver()
        ids = {n: r.artist(s, n) for n in ("Árstíðir", "Проект Звездолет", "ÁRSTÍÐIR", "проект звездолет")}
    assert ids["Árstíðir"] == ids["ÁRSTÍÐIR"]
    assert ids["Проект Звездолет"] == ids["проект звездолет"]
    with db.session() as s:
        assert s.query(Artist).filter(Artist.name.in_(["ÁRSTÍÐIR", "проект звездолет"])).count() == 0


def test_various_artists_has_no_genre_of_their_own():
    # a doom metal tribute filed with mostly psytrance compilations showed "Psytrance"
    import os
    import tempfile
    from sqlalchemy import select
    from muzix import scanner
    from muzix.api.library import artist_tags
    from muzix.models import Album, Root, Track

    class Ctx:
        def log(self, line):
            pass

    top = tempfile.mkdtemp(prefix="muzix-va-")
    with db.session() as s:
        root = Root(path=top, kind="music", name="va")
        va, band = Artist(name="Various Artists"), Artist(name="Psy Band")
        s.add_all([root, va, band])
        s.flush()
        for n, (artist, genre) in enumerate([(va, "Psytrance"), (va, "Psytrance"), (va, "Doom Metal"),
                                             (band, "Psytrance")]):
            folder = os.path.join(top, str(n))
            alb = Album(title=f"VA test {n}", artist_id=artist.id, folder=folder, key=folder)
            s.add(alb)
            s.flush()
            s.add(Track(root_id=root.id, path=os.path.join(folder, "1.mp3"), album_id=alb.id,
                        artist_id=artist.id, genre=genre))
        ids = va.id, band.id
    scanner.finish_scan(Ctx())
    with db.session() as s:
        assert [s.get(Artist, i).genre for i in ids] == ["", "Psytrance"]
        assert artist_tags(s, ids) == {ids[0]: [], ids[1]: ["Psytrance"]}
        assert s.scalar(select(Album.genre).where(Album.title == "VA test 2")) == "Doom Metal"


def test_casefold_works_in_queries():
    from sqlalchemy import func, select
    with db.session() as s:
        s.add(Artist(name="Ølvis Æther"))
    with db.session() as s:
        assert s.scalar(select(Artist.id).where(func.casefold(Artist.name) == "ølvis æther")) is not None
