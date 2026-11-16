"""Change genre on an album's cog: a double album whose second disc was filed under Rock (its tag said
so) is given Metal; its songs are tagged Metal and it moves into the Metal folder, next to the first
disc. Undoing puts it back. Only the library's genre folders can be picked; Duplicates keep their place."""
import os
import tempfile
import threading
from types import SimpleNamespace

import pytest
from sqlalchemy import select, text

from muzix import db, manage
from muzix.models import Album, Root

from test_merge import raw, scan, song, tree

ENTOMBED = "Entombed - 2004 - Inferno _ Averno"


@pytest.fixture
def inferno(monkeypatch):
    monkeypatch.setattr(manage.jobs, "submit", lambda *a, **k: None)
    # the main genres as uploads file them (beets' musicorg, which the server's image has; the tests may not)
    rules = SimpleNamespace(MAIN_GENRES=("Metal", "Rock", "Pop", "Electronic"))
    monkeypatch.setattr(manage, "_genre_rules", lambda: (rules, None))
    top = tempfile.mkdtemp(prefix="muzix-genre-")
    discs = {"Metal": ("Death Metal", ["Retaliation", "The Fix Is In"]), "Rock": ("Rock", ["When Humanity's Gone"])}
    for genre, (tag, titles) in discs.items():
        for n, title in enumerate(titles, 1):
            song(os.path.join(top, genre, "Entombed", ENTOMBED, f"{n}. Entombed - Inferno _ Averno - {title} (2004).wav"),
                 title=title, artist="Entombed", albumartist="Entombed", album="Inferno / Averno", track_no=n, year=2004,
                 genre=tag)
    for other in ("Pop", "_Metal", "Duplicates", "Uncategorized", "Bandcamp"):
        os.makedirs(os.path.join(top, other))
    song(os.path.join(top, "Duplicates", "Entombed", "Entombed - 1997 - Wreckage", "1. Entombed - Wreckage - Lights Out (1997).wav"),
         title="Lights Out", artist="Entombed", albumartist="Entombed", album="Wreckage", track_no=1, year=1997, genre="Metal")
    with db.session() as s:
        for t in ("tracks", "albums", "artists", "trash", "edits", "roots"):
            s.execute(text(f"DELETE FROM {t}"))
        root = Root(path=top, kind="music", name="test")
        s.add(root)
        s.flush()
        root_id = root.id
    scan(root_id)
    with db.session() as s:
        ids = {os.path.relpath(a.folder, top).split(os.sep)[0]: a.id for a in s.scalars(select(Album))}
    yield top, ids
    for t in threading.enumerate():
        if t.name == "manage-tidy":
            t.join(10)
    with db.session() as s:
        for t in ("tracks", "albums", "trash", "edits", "roots"):
            s.execute(text(f"DELETE FROM {t}"))


def test_the_second_disc_moves_from_rock_to_metal_and_back(inferno):
    top, ids = inferno
    choices = manage.genre_choices(ids["Rock"])
    assert choices["genres"] == ["Metal", "Pop", "Rock"]       # main genres only: not Bandcamp, _Metal, Duplicates
    assert (choices["now"], choices["genre"], choices["stays"]) == ("Rock", "Rock", None)
    before = tree(top)
    tags_before = {f: raw(os.path.join(top, f)) for f in before}

    r = manage.change_genre(ids["Rock"], "metal")
    moved = os.path.join(top, "Metal", "Entombed", ENTOMBED + " [2]")      # the first disc has the name
    assert r["moved_to"] == moved and r["edit_id"]
    assert os.listdir(moved) == ["1. Entombed - Inferno _ Averno - When Humanity's Gone (2004).wav"]
    assert raw(os.path.join(moved, os.listdir(moved)[0]))["TCON"] == "Metal"
    with db.session() as s:
        alb = s.get(Album, ids["Rock"])
        assert (alb.genre, alb.folder) == ("Metal", moved)
    assert manage.edit_list()[0]["summary"] == "Genre; filed in Metal / Entombed / " + ENTOMBED + " [2]"

    manage.undo_edit(r["edit_id"])
    assert tree(top) == before and {f: raw(os.path.join(top, f)) for f in before} == tags_before
    with db.session() as s:
        assert s.get(Album, ids["Rock"]).genre == "Rock"


def test_a_genre_already_its_folders_still_tags_every_song(inferno):
    _, ids = inferno
    assert manage.genre_choices(ids["Metal"])["now"] == "Metal"
    r = manage.change_genre(ids["Metal"], "Metal")           # in Metal, tagged Death Metal: retagged, not moved
    assert r["moved_to"] is None and r["written"] == 2
    with db.session() as s:
        assert s.get(Album, ids["Metal"]).genre == "Metal"
    again = manage.change_genre(ids["Metal"], "Metal")        # nothing left to do
    assert (again["written"], again["moved_to"], again["edit_id"]) == (0, None, None)


def test_only_the_librarys_genres_and_duplicates_stay(inferno):
    top, ids = inferno
    with pytest.raises(manage.ManageError):
        manage.change_genre(ids["Rock"], "Bandcamp")
    assert manage.genre_choices(ids["Duplicates"])["stays"] == "Duplicates"
    r = manage.change_genre(ids["Duplicates"], "Rock")       # tagged Rock, but it stays a duplicate
    assert r["moved_to"] is None and r["written"] == 1
    assert os.path.isdir(os.path.join(top, "Duplicates", "Entombed", "Entombed - 1997 - Wreckage"))


def test_without_the_genre_rules_every_folder_but_the_kept_ones_is_a_genre(tmp_path, monkeypatch):
    monkeypatch.setattr(manage, "_genre_rules", lambda: None)
    for f in ("Metal", "rock", "Bandcamp", "_Metal", ".trash", "Duplicates", "Other formats", "Uncategorized"):
        (tmp_path / f).mkdir()
    (tmp_path / "cover.jpg").write_bytes(b"")
    assert manage.genre_folders(str(tmp_path)) == ["Bandcamp", "Metal", "rock"]
