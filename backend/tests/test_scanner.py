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


def test_casefold_works_in_queries():
    from sqlalchemy import func, select
    with db.session() as s:
        s.add(Artist(name="Ølvis Æther"))
    with db.session() as s:
        assert s.scalar(select(Artist.id).where(func.casefold(Artist.name) == "ølvis æther")) is not None
