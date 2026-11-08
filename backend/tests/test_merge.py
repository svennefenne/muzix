"""Merging albums: a reissue's bonus disc and the album itself, filed as two, become one album with
two discs in one folder; undoing it puts both back as they were. And a new year shows, though
the files have an original release date (read first)."""
import os
import tempfile
import threading
import wave

import mutagen
import pytest
from mutagen.id3 import TDOR
from sqlalchemy import select, text

from muzix import db, manage, scanner
from muzix.meta import tagwrite
from muzix.models import Album, Like, Root, Track, TrashItem, User

GATHERING = "Metal/The Gathering"


class Ctx:
    def log(self, line):
        pass

    def update(self, *a, **k):
        pass

    def check(self):
        pass


def song(path, original=None, **fields):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\0\0" * 800)
    tagwrite.write(path, fields)
    if original:            # as MusicBrainz tags a reissue: its year, and the first release's
        audio = mutagen.File(path)
        audio.tags.add(TDOR(encoding=3, text=[original]))
        audio.save()


def raw(path):
    t = mutagen.File(path).tags
    return {k: str(t[k]) for k in sorted(t.keys())}


def tree(top):
    return sorted(os.path.relpath(os.path.join(d, f), top) for d, _, fs in os.walk(top) for f in fs
                  if manage.TRASH not in d)


def scan(root_id):
    with db.session() as s:
        scanner.scan_root(Ctx(), s.get(Root, root_id), full=True)
    scanner.finish_scan(Ctx())


@pytest.fixture
def mandylion(monkeypatch):
    monkeypatch.setattr(manage.jobs, "submit", lambda *a, **k: None)
    top = tempfile.mkdtemp(prefix="muzix-merge-")
    one = os.path.join(top, GATHERING, "The Gathering - 2005 - Mandylion [2]")
    bonus = os.path.join(top, GATHERING, "The Gathering - 2005 - Mandylion")
    for n, title in ((1, "Strange Machines"), (2, "Eléanor"), (3, "In Motion #1")):
        song(os.path.join(one, f"{n}. The Gathering - Mandylion - {title} (2005).wav"), original="1995", title=title,
             artist="The Gathering", albumartist="The Gathering", album="Mandylion", track_no=n, disc_no=1, year=2015,
             genre="Doom Metal")
    for n, title in ((1, "In Motion #1"), (2, "Third Chance")):
        song(os.path.join(bonus, f"{n}. The Gathering - Mandylion - {title} (2005).wav"), title=title, artist="The Gathering",
             albumartist="The Gathering", album="Mandylion", track_no=n, disc_no=2, year=2005, genre="Doom Metal")
    for folder, picture in ((one, b"\xff\xd8the album's"), (bonus, b"\xff\xd8the bonus disc's")):
        with open(os.path.join(folder, "cover.jpg"), "wb") as f:
            f.write(picture)
    with open(os.path.join(bonus, "1. The Gathering - Mandylion - In Motion #1 (2005).lrc"), "w") as f:
        f.write("[00:01.00]words")
    with open(os.path.join(bonus, "info.txt"), "w") as f:
        f.write("the demos")
    with db.session() as s:
        for t in ("tracks", "albums", "artists", "trash", "edits", "roots"):
            s.execute(text(f"DELETE FROM {t}"))
        root = Root(path=top, kind="music", name="test")
        s.add(root)
        s.flush()
        root_id = root.id
    scan(root_id)
    with db.session() as s:
        ids = {a.folder: a.id for a in s.scalars(select(Album))}
    yield top, one, bonus, ids[one], ids[bonus]
    for t in threading.enumerate():
        if t.name == "manage-tidy":
            t.join(10)
    with db.session() as s:
        for t in ("likes", "tracks", "albums", "trash", "edits", "roots"):
            s.execute(text(f"DELETE FROM {t}"))


def test_a_new_year_shows_though_the_files_have_an_original_date(mandylion):
    top, one, bonus, first, _ = mandylion
    with db.session() as s:
        assert s.get(Album, first).year == 1995         # the original release date is read first
    path = os.path.join(one, "1. The Gathering - Mandylion - Strange Machines (2005).wav")
    before = raw(path)
    r = manage.edit_album(first, {"title": "Mandylion", "artist": "The Gathering", "year": 2005, "genre": "Doom Metal"}, [])
    with db.session() as s:
        assert s.get(Album, first).year == 2005
    assert "TDOR" not in raw(os.path.join(r["moved_to"] or one, "1. The Gathering - Mandylion - Strange Machines (2005).wav"))
    manage.undo_edit(r["edit_id"])
    assert raw(path) == before                           # the original date back too
    with db.session() as s:
        assert s.get(Album, first).year == 1995


def test_merging_the_bonus_disc_into_its_album_and_back(mandylion):
    top, one, bonus, first, second = mandylion
    files_before = tree(top)
    tags_before = {f: raw(os.path.join(top, f)) for f in files_before if f.endswith(".wav")}
    with db.session() as s:
        user = User(username="merge-liker", password_hash="x")
        s.add(user)
        s.flush()
        s.add(Like(user_id=user.id, item_type="album", item_id=second))
        added = {a.id: a.added_at for a in s.scalars(select(Album))}

    plan = manage.merge_plan([first, second], {"year": 2005})
    folder = os.path.join(GATHERING, "The Gathering - 2005 - Mandylion")      # the bonus disc's name, its folder emptied
    assert plan["folder"] == folder and plan["discs"] == 2 and plan["trashed"] == [folder]
    assert [a["discs"] for a in plan["albums"]] == [[1], [2]]
    assert plan["albums"][1]["songs"][0]["name"] == "2-1. The Gathering - Mandylion - In Motion #1 (2005).wav"
    assert tree(top) == files_before                      # the plan changes nothing

    r = manage.merge_albums([first, second], {"year": 2005})
    assert r["album_id"] == first and r["edit_id"]
    merged = os.path.join(top, folder)
    assert tree(top) == sorted(os.path.join(folder, f) for f in (
        "1-1. The Gathering - Mandylion - Strange Machines (2005).wav", "1-2. The Gathering - Mandylion - Eléanor (2005).wav",
        "1-3. The Gathering - Mandylion - In Motion #1 (2005).wav", "2-1. The Gathering - Mandylion - In Motion #1 (2005).wav",
        "2-1. The Gathering - Mandylion - In Motion #1 (2005).lrc", "2-2. The Gathering - Mandylion - Third Chance (2005).wav",
        "cover.jpg"))
    with open(os.path.join(merged, "cover.jpg"), "rb") as f:
        assert f.read() == b"\xff\xd8the album's"          # the first album's cover stays
    assert raw(os.path.join(merged, "2-2. The Gathering - Mandylion - Third Chance (2005).wav"))["TPOS"] == "2/2"
    assert raw(os.path.join(merged, "1-1. The Gathering - Mandylion - Strange Machines (2005).wav"))["TPOS"] == "1/2"
    with db.session() as s:
        albums = list(s.scalars(select(Album)))
        assert [(a.id, a.title, a.year, a.track_count, a.folder) for a in albums] == [(first, "Mandylion", 2005, 5, merged)]
        assert albums[0].art == os.path.join(merged, "cover.jpg")
        assert sorted((t.disc_no, t.track_no) for t in s.scalars(select(Track))) == [(1, 1), (1, 2), (1, 3), (2, 1), (2, 2)]
        assert s.scalar(select(Like.item_id).where(Like.user_id == user.id)) == first       # the like came along
        trash = s.scalar(select(TrashItem))
        assert sorted(os.path.basename(src) for src, _ in trash.moves) == ["cover.jpg", "info.txt"]
    edit = manage.edit_list()[0]
    assert edit["summary"] == ("Merged with Mandylion (2 songs); 2 discs; filed in The Gathering / "
                               "The Gathering - 2005 - Mandylion")

    manage.undo_edit(r["edit_id"])
    assert tree(top) == files_before
    assert {f: raw(os.path.join(top, f)) for f in tags_before} == tags_before
    with open(os.path.join(bonus, "cover.jpg"), "rb") as f:
        assert f.read() == b"\xff\xd8the bonus disc's"
    with db.session() as s:
        albums = {a.folder: a for a in s.scalars(select(Album))}
        assert sorted(albums) == [bonus, one] and albums[one].id == first
        assert (albums[one].year, albums[one].track_count, albums[one].art) == (1995, 3, os.path.join(one, "cover.jpg"))
        assert (albums[bonus].track_count, albums[bonus].art) == (2, os.path.join(bonus, "cover.jpg"))
        assert albums[bonus].added_at == added[second]      # a new row, but as old as it was
        assert s.scalar(select(TrashItem)) is None


def test_a_merge_that_fails_halfway_puts_everything_back(mandylion, monkeypatch):
    top, one, bonus, first, second = mandylion
    files_before = tree(top)
    tags_before = {f: raw(os.path.join(top, f)) for f in files_before if f.endswith(".wav")}

    def broken(*a, **k):
        raise RuntimeError("the database went away")
    monkeypatch.setattr(manage, "_reread", broken)
    with pytest.raises(manage.ManageError, match="put back"):
        manage.merge_albums([first, second], {"year": 2005})
    assert tree(top) == files_before
    assert {f: raw(os.path.join(top, f)) for f in tags_before} == tags_before
    assert not os.listdir(os.path.join(top, manage.TRASH)) if os.path.isdir(os.path.join(top, manage.TRASH)) else True
    with db.session() as s:
        assert sorted(a.id for a in s.scalars(select(Album))) == sorted([first, second])


def test_merging_needs_two_music_albums_of_ours(mandylion):
    _, _, _, first, second = mandylion
    with pytest.raises(manage.ManageError, match="at least two"):
        manage.merge_plan([first, first], {})
    with pytest.raises(manage.ManageError, match="isn't there"):
        manage.merge_plan([first, 999999], {})
