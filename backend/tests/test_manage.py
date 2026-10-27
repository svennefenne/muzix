"""Admin mode: hiding keeps things out of the pages, deleting goes through the trash and can be
undone, and editing writes the tags and files the album the way the library is filed."""
import os
import tempfile
import threading
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
def library(monkeypatch):
    """A music folder filed like the real one, scanned. No background scans (putting back from the
    trash asks for one), and the tidying after an edit is waited for, so tests can't overlap."""
    monkeypatch.setattr(manage.jobs, "submit", lambda *a, **k: None)
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
    for t in threading.enumerate():
        if t.name == "manage-tidy":
            t.join(10)
    with db.session() as s:
        s.execute(text("DELETE FROM tracks"))
        s.execute(text("DELETE FROM albums"))
        s.execute(text("DELETE FROM trash"))
        s.execute(text("DELETE FROM edits"))
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


def raw_pictures(path):
    import mutagen
    return [k for k in mutagen.File(path).tags.keys() if k.startswith("APIC")]


def raw(path):
    """The file's own tag frames, as mutagen has them."""
    import mutagen
    t = mutagen.File(path).tags
    return {k: str(t[k]) for k in sorted(t.keys()) if not k.startswith("APIC")}


def test_undoing_an_album_edit_puts_tags_names_and_folder_back(library):
    top, album, album_id = library
    before = {f: raw(os.path.join(album, f)) for f in os.listdir(album) if f.endswith(".wav")}
    assert all("TPOS" not in r for r in before.values())
    with db.session() as s:
        ids = {t.title: t.id for t in s.scalars(select(Track).where(Track.album_id == album_id))}
    r = manage.edit_album(album_id, {"title": "Better Album", "artist": "New Artist", "year": 1992, "genre": "Metal"},
                          [{"id": ids["First"], "title": "Opener", "artist": "New Artist", "track_no": 1, "disc_no": 1},
                           {"id": ids["Second"], "title": "Second", "artist": "New Artist", "track_no": 2, "disc_no": 1}])
    assert not os.path.exists(album) and r["edit_id"]
    edit = manage.edit_list()[0]
    assert (edit["kind"], edit["item_id"], edit["undone_at"]) == ("album", album_id, None)
    assert edit["title"] == "Better Album (was Old Album)"
    assert edit["summary"] == "Title, album artist and year; 2 songs; filed in New Artist / New Artist - 1992 - Better Album"
    assert manage.details("album", album_id)["last_edit"]["id"] == r["edit_id"]

    manage.undo_edit(r["edit_id"])
    assert sorted(os.listdir(album)) == sorted(before) + ["cover.jpg"]
    assert {f: raw(os.path.join(album, f)) for f in before} == before       # disc numbers they never had: gone again
    assert not os.path.exists(r["moved_to"])
    with db.session() as s:
        alb = s.get(Album, album_id)        # the same album, back in its own folder
        assert (alb.title, alb.artist_name, alb.year, alb.art) == ("Old Album", "Old Artist", 1990, os.path.join(album, "cover.jpg"))
        assert s.get(Track, ids["First"]).path == os.path.join(album, "1. Old Artist - Old Album - First (1990).wav")
        assert s.get(Track, ids["First"]).title == "First"
    assert manage.edit_list()[0]["undone_at"] and manage.details("album", album_id)["last_edit"] is None
    with pytest.raises(manage.ManageError, match="already"):
        manage.undo_edit(r["edit_id"])


def test_an_edit_made_later_has_to_be_undone_first(library):
    top, album, album_id = library
    with db.session() as s:
        ids = {t.title: t.id for t in s.scalars(select(Track).where(Track.album_id == album_id))}
    first = manage.edit_album(album_id, {"title": "Better Album"}, [])
    song_edit = manage.edit_track(ids["Second"], {"title": "Second Thoughts"})
    assert song_edit["edit_id"] and song_edit["renamed_to"]
    with pytest.raises(manage.ManageError, match="changed since"):
        manage.undo_edit(first["edit_id"])
    assert os.path.exists(song_edit["renamed_to"])          # nothing was touched
    manage.undo_edit(song_edit["edit_id"])
    manage.undo_edit(first["edit_id"])
    assert sorted(os.listdir(album)) == ["1. Old Artist - Old Album - First (1990).wav",
                                         "2. Old Artist - Old Album - Second (1990).wav", "cover.jpg"]
    assert tags.read(os.path.join(album, "2. Old Artist - Old Album - Second (1990).wav")).album == "Old Album"


def test_undoing_an_artist_rename(library):
    top, album, album_id = library
    with db.session() as s:
        artist_id = s.scalar(select(Artist.id).where(Artist.name == "Old Artist"))
    d = manage.details("artist", artist_id)
    assert (d["albums"], d["songs"], d["folders"]) == (1, 2, [os.path.join("Metal", "Old Artist")])
    assert manage.namesake(artist_id, "Renamed Artist") is None and manage.namesake(artist_id, "old artist") is None
    assert manage.namesake(artist_id, " neighbour ")["name"] == "Neighbour"
    report = manage.rename_artist_job(Ctx(), artist_id, "Renamed Artist")
    moved = os.path.join(top, "Metal", "Renamed Artist", "Renamed Artist - 1990 - Old Album")
    assert os.path.isdir(moved) and not os.path.exists(album)
    edit = manage.edit_list()[0]
    assert report == {"old": "Old Artist", "name": "Renamed Artist", "albums": 1, "songs": 2, "folders": ["Metal / Renamed Artist"],
                      "failed": [], "merged": False, "edit_id": edit["id"], "artist_id": artist_id, "picture": False}
    assert (edit["kind"], edit["item_id"], edit["title"]) == ("artist", artist_id, "Renamed Artist (was Old Artist)")
    manage.undo_edit(edit["id"])
    assert os.path.isdir(album) and not os.path.exists(moved)
    assert tags.read(os.path.join(album, "1. Old Artist - Old Album - First (1990).wav")).albumartist == "Old Artist"
    with db.session() as s:
        assert s.get(Artist, artist_id).name == "Old Artist"


def test_an_album_goes_to_its_new_album_artist(library):
    top, album, album_id = library
    with db.session() as s:
        neighbour = s.scalar(select(Artist.id).where(Artist.name == "Neighbour"))
    r = manage.edit_album(album_id, {"artist": "Neighbour"}, [])
    with db.session() as s:
        assert s.get(Album, album_id).artist_id == neighbour
    manage.undo_edit(r["edit_id"])
    with db.session() as s:       # back with their old artist (a new row, when the emptied one was tidied away)
        assert s.get(Artist, s.get(Album, album_id).artist_id).name == "Old Artist"


def test_a_picture_picked_with_a_new_name_goes_to_whoever_has_it(library, monkeypatch):
    """Renaming onto a name the library has makes the two one: the picture goes to that one."""
    from io import BytesIO
    from PIL import Image
    img = BytesIO()
    Image.new("RGB", (40, 40), (10, 200, 30)).save(img, "PNG")
    monkeypatch.setattr(manage, "fetch_image", lambda url: img.getvalue())
    with db.session() as s:
        old_id = s.scalar(select(Artist.id).where(Artist.name == "Old Artist"))
        neighbour = s.scalar(select(Artist.id).where(Artist.name == "Neighbour"))
    report = manage.rename_artist_job(Ctx(), old_id, "Neighbour", picture="https://pictures/neighbour.jpg")
    assert report["merged"] and report["artist_id"] == neighbour and report["picture"]
    with db.session() as s:
        assert s.get(Artist, neighbour).image and os.path.isfile(s.get(Artist, neighbour).image)
        assert s.scalar(select(func.count()).select_from(Album).where(Album.artist_id == neighbour)) == 2
    manage.undo_edit(report["edit_id"])
    # the same name and a picture: set at once, no job
    assert manage.edit_simple("artist", neighbour, {"name": "Neighbour"}, "https://pictures/n2.jpg") == {"picture": True}


def test_undoing_a_station_rename():
    from muzix.models import Station, User
    with db.session() as s:
        user = User(username="undo-test", password_hash="-")
        s.add(user)
        s.flush()
        st = Station(user_id=user.id, name="Old FM", url="http://example.com/stream")
        s.add(st)
        s.flush()
        sid = st.id
    r = manage.edit_simple("station", sid, {"name": "New FM"})
    assert manage.edit_list()[0]["summary"] == "Name"
    manage.undo_edit(r["edit_id"])
    with db.session() as s:
        assert s.get(Station, sid).name == "Old FM"
        s.delete(s.get(Station, sid))
        s.delete(s.scalar(select(User).where(User.username == "undo-test")))


def test_putting_a_cover_back_swaps_it_with_the_newer_one(library):
    from io import BytesIO
    from PIL import Image
    top, album, album_id = library
    img = BytesIO()
    Image.new("RGB", (50, 50), (200, 30, 30)).save(img, "PNG")
    manage.set_cover("album", album_id, img.getvalue())
    first = os.path.join(album, "1. Old Artist - Old Album - First (1990).wav")
    assert "APIC:Cover" in raw_pictures(first)
    trash = manage.trash_items()
    assert trash[0]["kind"] == "cover"
    manage.restore(trash[0]["id"])
    assert raw_pictures(first) == []            # the files had no picture before it
    with open(os.path.join(album, "cover.jpg"), "rb") as f:
        assert f.read() == b"\xff\xd8not really a picture"
    now = manage.trash_items()
    assert len(now) == 1 and now[0]["kind"] == "cover"         # the newer one, put back in its place


def test_undoing_an_edit_puts_back_the_cover_picked_with_it(library):
    from io import BytesIO
    from PIL import Image
    top, album, album_id = library
    r = manage.edit_album(album_id, {"title": "Better Album"}, [])
    img = BytesIO()
    Image.new("RGB", (50, 50), (20, 90, 200)).save(img, "PNG")
    manage.set_cover("album", album_id, img.getvalue(), r["edit_id"])
    manage.undo_edit(r["edit_id"])
    with open(os.path.join(album, "cover.jpg"), "rb") as f:
        assert f.read() == b"\xff\xd8not really a picture"
    assert not os.path.exists(r["moved_to"])
    import mutagen
    assert not [k for f in os.listdir(album) if f.endswith(".wav")
                for k in mutagen.File(os.path.join(album, f)).tags.keys() if k.startswith("APIC")]   # none, as before
    assert [t["kind"] for t in manage.trash_items()] == ["cover"]       # the picked one, to put back if wanted
    with db.session() as s:
        assert s.get(Album, album_id).art == os.path.join(album, "cover.jpg")


def test_songs_can_swap_names(library):
    top, album, album_id = library
    first, second = (os.path.join(album, f"{n}. Old Artist - Old Album - {t} (1990).wav") for n, t in ((1, "First"), (2, "Second")))
    with db.session() as s:
        ids = {t.title: t.id for t in s.scalars(select(Track).where(Track.album_id == album_id))}
    # each file takes the other's title and number, so each takes the other's name too
    r = manage.edit_album(album_id, {}, [{"id": ids["First"], "title": "Second", "track_no": 2},
                                         {"id": ids["Second"], "title": "First", "track_no": 1}])
    assert sorted(os.listdir(album)) == [os.path.basename(first), os.path.basename(second), "cover.jpg"]
    with db.session() as s:
        assert s.get(Track, ids["First"]).path == second and s.get(Track, ids["Second"]).path == first
    assert (tags.read(second).title, tags.read(second).track_no) == ("Second", 2)
    manage.undo_edit(r["edit_id"])
    with db.session() as s:
        assert s.get(Track, ids["First"]).path == first and s.get(Track, ids["Second"]).path == second
    assert tags.read(first).title == "First"


def test_a_file_changed_since_it_was_read_stops_the_edit(library):
    top, album, album_id = library
    path = os.path.join(album, "1. Old Artist - Old Album - First (1990).wav")
    was = raw(path)
    os.utime(path, (1, 1))
    with pytest.raises(manage.ManageError, match="scan the library folder first"):
        manage.edit_album(album_id, {"title": "Better Album"}, [])
    assert raw(path) == was and os.path.isdir(album)


def test_a_save_that_fails_halfway_puts_the_files_back(library, monkeypatch):
    top, album, album_id = library
    before = {f: raw(os.path.join(album, f)) for f in os.listdir(album) if f.endswith(".wav")}

    def broken(*a, **k):
        raise RuntimeError("the database went away")
    monkeypatch.setattr(manage, "_reread", broken)
    with pytest.raises(manage.ManageError, match="put back as they were"):
        manage.edit_album(album_id, {"title": "Better Album", "year": 1992}, [])
    assert {f: raw(os.path.join(album, f)) for f in os.listdir(album) if f.endswith(".wav")} == before
    assert not os.path.exists(os.path.join(top, "Metal", "Old Artist", "Old Artist - 1992 - Better Album"))
    assert manage.edit_list() == []
