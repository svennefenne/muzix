"""Admin mode: hiding keeps things out of the pages, deleting goes through the trash and can be
undone, and editing writes the tags and files the album the way the library is filed."""
import os
import tempfile
import wave

import pytest
from sqlalchemy import func, select, text

from muzix import db, manage, scanner
from muzix.meta import tagwrite, tags
from muzix.models import Album, Artist, Root, TagOverride, Track, TrashItem


class Ctx:
    def log(self, line):
        pass

    def update(self, *a, **k):
        pass

    def check(self):
        pass


def song(path, **fields):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\0\0" * 800)
    tagwrite.write(path, fields)


@pytest.fixture
def library():
    """A music folder filed like the real one, scanned."""
    top = tempfile.mkdtemp(prefix="muzix-manage-")
    album = os.path.join(top, "Metal", "Old Artist", "Old Artist - 1990 - Old Album")
    for n, title in ((1, "First"), (2, "Second")):
        song(os.path.join(album, f"{n}. Old Artist - Old Album - {title} (1990).wav"), title=title, artist="Old Artist",
             albumartist="Old Artist", album="Old Album", track_no=n, year=1990, genre="Metal")
    with open(os.path.join(album, "cover.jpg"), "wb") as f:
        f.write(b"\xff\xd8not really a picture")
    other = os.path.join(top, "Metal", "Neighbour", "Neighbour - 2001 - Next Door")
    song(os.path.join(other, "1. Neighbour - Next Door - Hello (2001).wav"), title="Hello", artist="Neighbour",
         albumartist="Neighbour", album="Next Door", track_no=1, year=2001, genre="Metal")
    with db.session() as s:
        s.execute(text("DELETE FROM tracks"))
        s.execute(text("DELETE FROM albums"))
        s.execute(text("DELETE FROM artists"))
        root = Root(path=top, kind="music", name="test")
        s.add(root)
        s.flush()
        root_id = root.id
    with db.session() as s:
        root = s.get(Root, root_id)
        scanner.scan_root(Ctx(), root, full=True)
    scanner.finish_scan(Ctx())
    with db.session() as s:
        album_id = s.scalar(select(Album.id).where(Album.title == "Old Album"))
    yield top, album, album_id
    with db.session() as s:
        s.execute(text("DELETE FROM tracks"))
        s.execute(text("DELETE FROM albums"))
        s.execute(text("DELETE FROM trash"))
        s.execute(text("DELETE FROM roots"))


def web_session():
    s = db.SessionLocal()
    s.info["hide"] = True
    return s


def test_new_columns_are_added_to_an_old_database():
    with db.engine.begin() as c:
        c.execute(text("ALTER TABLE stations DROP COLUMN hidden"))      # as a database from before admin mode
    db._add_new_columns()
    with db.engine.connect() as c:
        cols = {r[1]: r for r in c.execute(text("PRAGMA table_info(stations)"))}
    assert "hidden" in cols and cols["hidden"][3] == 1                     # NOT NULL, default 0


def test_hiding_an_album_hides_its_songs_from_the_pages(library):
    _, _, album_id = library
    manage.set_hidden("album", album_id, True)
    web = web_session()
    assert web.get(Album, album_id) is None
    assert web.scalar(select(func.count()).select_from(Track).where(Track.album_id == album_id)) == 0
    assert web.scalar(select(func.count()).select_from(Track)) == 1          # the neighbour's song
    assert {i["kind"] for i in manage.hidden_items()} == {"album"}
    manage.set_hidden("album", album_id, False)
    assert web_session().scalar(select(func.count()).select_from(Track)) == 3


def test_hiding_an_artist_and_a_rescan_keeps_new_files_hidden(library):
    top, album, album_id = library
    with db.session() as s:
        artist_id = s.scalar(select(Artist.id).where(Artist.name == "Old Artist"))
    manage.set_hidden("artist", artist_id, True)
    song(os.path.join(album, "3. Old Artist - Old Album - Third (1990).wav"), title="Third", artist="Old Artist",
         albumartist="Old Artist", album="Old Album", track_no=3, year=1990, genre="Metal")
    with db.session() as s:
        scanner.scan_root(Ctx(), s.scalar(select(Root).where(Root.path == top)), full=False)
    web = web_session()
    assert web.scalar(select(func.count()).select_from(Track)) == 1
    assert [i["kind"] for i in manage.hidden_items()] == ["artist"]


def test_deleting_an_album_moves_its_folder_to_the_trash_and_back(library):
    top, album, album_id = library
    r = manage.delete_item("album", album_id)
    assert not os.path.exists(album)
    with db.session() as s:
        item = s.get(TrashItem, r["trash_id"])
        assert item.moves == [[album, os.path.join(item.folder, os.path.relpath(album, top))]]
        assert os.path.isdir(item.moves[0][1]) and os.path.dirname(item.folder) == os.path.join(top, ".muzix-trash")
        assert s.scalar(select(func.count()).select_from(Track).where(Track.path.startswith(album))) == 0
    assert manage.trash_items()[0]["title"] == "Old Album"
    manage.restore(r["trash_id"])
    assert os.path.exists(os.path.join(album, "cover.jpg"))
    assert not os.listdir(os.path.join(top, ".muzix-trash"))
    with pytest.raises(manage.ManageError):
        manage.restore(r["trash_id"])


def test_emptying_the_trash_deletes_for_good(library):
    top, album, album_id = library
    r = manage.delete_item("album", album_id)
    with db.session() as s:
        folder = s.get(TrashItem, r["trash_id"]).folder
    assert manage.empty_trash(r["trash_id"]) == 1
    assert not os.path.exists(folder) and not os.path.exists(album)


def test_editing_an_album_writes_the_tags_and_files_it_again(library):
    top, album, album_id = library
    with db.session() as s:
        ids = {t.title: t.id for t in s.scalars(select(Track).where(Track.album_id == album_id))}
    r = manage.edit_album(album_id, {"title": "Better Album", "artist": "New Artist", "year": 1992, "genre": "Metal"},
                          [{"id": ids["First"], "title": "Opener", "artist": "New Artist", "track_no": 1, "disc_no": 0},
                           {"id": ids["Second"], "title": "Second", "artist": "New Artist", "track_no": 2, "disc_no": 0}])
    new = os.path.join(top, "Metal", "New Artist", "New Artist - 1992 - Better Album")
    assert r["moved_to"] == new and r["written"] == 2 and r["album_id"] == album_id
    assert sorted(os.listdir(new)) == ["1. New Artist - Better Album - Opener (1992).wav",
                                       "2. New Artist - Better Album - Second (1992).wav", "cover.jpg"]
    assert os.path.isdir(os.path.join(top, "Metal", "Old Artist"))       # empty folders stay, as in the library
    t = tags.read(os.path.join(new, "1. New Artist - Better Album - Opener (1992).wav"))
    assert (t.title, t.artist, t.albumartist, t.album, t.year) == ("Opener", "New Artist", "New Artist", "Better Album", 1992)
    with db.session() as s:
        alb = s.get(Album, album_id)        # the same album, found again in its new folder
        assert (alb.title, alb.artist_name, alb.year, alb.art) == ("Better Album", "New Artist", 1992, os.path.join(new, "cover.jpg"))
        assert s.get(Track, ids["First"]).path.startswith(new + "/")


def test_editing_a_song_renames_its_file_in_place(library):
    top, album, album_id = library
    with db.session() as s:
        tid = s.scalar(select(Track.id).where(Track.title == "Second"))
    r = manage.edit_track(tid, {"title": "Second Thoughts"})
    assert r["renamed_to"] == os.path.join(album, "2. Old Artist - Old Album - Second Thoughts (1990).wav")
    assert tags.read(r["renamed_to"]).title == "Second Thoughts"


def test_files_without_tags_keep_their_edits_in_muzix():
    with db.session() as s:
        s.merge(TagOverride(path="/vgm/tunes/x.sid", subsong=2, fields={"title": "Better name"}))
        assert scanner.load_overrides(s, "/vgm/tunes") == {("/vgm/tunes/x.sid", 2): {"title": "Better name"}}
        assert scanner.load_overrides(s, "/vgm/other") == {}


def test_file_names_are_cleaned_like_beets_does():
    assert manage.clean('AC/DC: "Live"?') == "AC_DC_ _Live__"
    assert manage.clean(".hidden.") == "_hidden"
