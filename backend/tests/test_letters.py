"""Jumping to a letter in the library: where each first letter begins, in the list's own order."""
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete

from muzix import db
from muzix.api import library
from muzix.models import Album, Artist
from muzix.security import current_user


def test_letters_follow_the_list():
    with db.session() as s:
        s.execute(delete(Album).where(Album.key.like("letters-%")))
        s.execute(delete(Artist).where(Artist.name.like("Lt %")))
        names = ["abba lt", "ABBA Lt 2", "Beatles lt", "2Pac lt", "zz lt", "Åsa lt", "Östen lt", "Би-2 lt"]
        for i, n in enumerate(names):
            a = Artist(name=f"Lt {i}")
            s.add(a)
            s.flush()
            s.add(Album(title=n, artist_name=a.name, artist_id=a.id, folder=f"/x/{i}", key=f"letters-{i}", kind="music"))
    app = FastAPI()
    app.include_router(library.router)
    app.dependency_overrides[current_user] = lambda: SimpleNamespace(id=1)
    c = TestClient(app)
    got = c.get("/api/letters", params={"of": "albums", "sort": "name"}).json()
    titles = [a["title"] for a in c.get("/api/albums", params={"sort": "name", "limit": 500}).json()["items"]]
    for g in got:       # each letter's offset is the first album under it in the list itself
        assert library.initial(titles[g["offset"]]) == g["letter"]
        assert all(library.initial(t) != g["letter"] for t in titles[:g["offset"]])
    letters = [g["letter"] for g in got]
    assert {"#", "A", "B", "Z", "Å", "Ö", "…"} <= set(letters)
    assert library.initial("  the Beatles") == "T" and library.initial("") == "#"
