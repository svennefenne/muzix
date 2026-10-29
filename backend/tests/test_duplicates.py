"""Before an upload: the same file again, and songs the library has already by their names."""
import os

from muzix import db, env
from muzix.api import upload as api
from muzix.models import Root, Track, UploadedFile
from muzix.organize import duplicates


def test_names_boil_down_to_titles():
    assert duplicates.norm("Motörhead - Ace of Spades!") == "motorhead ace of spades"
    assert duplicates.base("Battery (Remastered 2017)") == "battery"
    assert "Battery" in duplicates.titles("01 Battery")
    assert "Battery" in duplicates.titles("01 - Battery")
    assert "Prospero's Curse (1991)" in duplicates.titles("2. Michael Nyman - Prospero's Books - Prospero's Curse (1991)")
    assert "99 Luftballons" in duplicates.titles("99 Luftballons")         # a title starting with a number stays too


def test_duplicates_before_an_upload():
    with db.session() as s:
        root = Root(path="/lib", kind="music")
        s.add(root)
        s.flush()
        s.add_all([
            Track(root_id=root.id, path="/lib/Metal/Metallica/Metallica - 1999 - S & M/1. Metallica - S & M - Battery.mp3",
                  title="Battery", artist="Metallica", albumartist="Metallica", album="S & M", format="mp3"),
            Track(root_id=root.id, path="/lib/Metal/Metallica/Metallica - 1986 - Master of Puppets/1. Metallica - Master of Puppets - Battery.mp3",
                  title="Battery", artist="Metallica", albumartist="Metallica", album="Master of Puppets", format="mp3", size=9_000_000),
            Track(root_id=root.id, path="/lib/Metal/Metallica/Metallica - 1986 - Master of Puppets/2. Metallica - Master of Puppets - Master of Puppets.mp3",
                  title="Master of Puppets (Remastered)", artist="Metallica", albumartist="Metallica", album="Master of Puppets", format="mp3"),
            Track(root_id=root.id, path="/lib/Pop/Nena/Nena - 99 Luftballons.mp3", title="99 Luftballons", artist="Nena", format="mp3"),
            Track(root_id=root.id, path="/lib/Rock/Other Band/Other Band - Thing/1. Other Band - Thing - Intro.mp3",
                  title="Intro", artist="Other Band", album="Thing", format="mp3"),
            Track(root_id=root.id, path="/vgm/Uploads/tune.sid", title="Tune", kind="vgm", format="sid", size=4321),
        ])
        s.add(UploadedFile(name="old.flac", size=1000, path="Old/old.flac", batch="20261001-120000-abcd"))
    waiting = env.UPLOAD_DIR / "20261028-120000-beef" / "Album"
    os.makedirs(waiting, exist_ok=True)
    (waiting / "waiting.flac").write_bytes(b"x" * 10)

    files = [
        ("Metallica - Master of Puppets (1986)/01 Battery.flac", 30_000_000),       # in the library
        ("Metallica - Master of Puppets (1986)/02 Master of Puppets.flac", 40_000_000),  # remastered there: similar
        ("Metallica - Master of Puppets (1986)/cover.jpg", 200_000),               # its whole folder goes: so does this
        ("Metallica - Master of Puppets (1986)/01 Battery.lrc", 2_000),
        ("Some Other Artist/01 Battery.flac", 30_000_000),                          # same title, another artist: new
        ("Nena - 99 Luftballons.mp3", 5_000_000),                                    # by name, no folder
        ("Intro.mp3", 1_000),                                                        # a bare title: similar
        ("Old/old.flac", 1000),                                                      # uploaded before
        ("Album/waiting.flac", 10),                                                  # waiting to be imported
        ("tune.sid", 4321),                                                          # in the library as it is
        ("New Band - New Album/01 Fresh.flac", 1234),
        ("New Band - New Album/cover.jpg", 99),
    ]
    with db.session() as s:
        got = duplicates.check(files, s)
    why = {f["path"]: f["why"] for f in got["found"]}
    assert why == {
        "Metallica - Master of Puppets (1986)/01 Battery.flac": "library",
        "Metallica - Master of Puppets (1986)/02 Master of Puppets.flac": "similar",
        "Nena - 99 Luftballons.mp3": "library",
        "Intro.mp3": "similar",
        "Old/old.flac": "uploaded",
        "Album/waiting.flac": "waiting",
        "tune.sid": "library",
    }
    first = got["found"][0]
    assert first["match"]["album"] == "Master of Puppets" and first["match"]["format"] == "mp3"   # not the live one
    assert set(got["skip"]) == set(why) | {"Metallica - Master of Puppets (1986)/cover.jpg",
                                           "Metallica - Master of Puppets (1986)/01 Battery.lrc"}

    # remembered as they come, forgotten when their batch is thrown away
    with db.session() as s:
        duplicates.remember(s, "20261029-100000-cafe", [{"path": "Fresh/new.flac", "size": 77}])
        assert duplicates.check([("x/NEW.flac", 77)], s)["found"][0]["why"] == "uploaded"
        duplicates.forget(s, "20261029-100000-cafe")
        assert duplicates.check([("x/NEW.flac", 77)], s)["found"] == []

    # switched off
    from muzix import settings
    settings.set_many({"upload_check_duplicates": False})
    with db.session() as s:
        assert api.check(api.CheckBody(files=[{"path": "Old/old.flac", "size": 1000}]), db=s)["off"]
    settings.set_many({"upload_check_duplicates": True})
