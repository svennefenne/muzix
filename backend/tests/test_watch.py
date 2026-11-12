"""The watch folder (watch.py): an album is taken once it stays as it is, looked up on MusicBrainz and then
Bandcamp by its songs' lengths, filed as uploads are, and what's left, a duplicate or a failure set aside."""
import pytest

from muzix import settings, watch


class Ctx:
    def __init__(self):
        self.lines = []

    def log(self, line):
        self.lines.append(line)

    def update(self, *a):
        pass


@pytest.fixture
def folder(tmp_path, monkeypatch):
    settings.set_many({"watch_folder": str(tmp_path), "watch_computer": ""})
    monkeypatch.setattr(watch.env, "UPLOAD_DIR", tmp_path.parent / (tmp_path.name + "-uploads"))
    monkeypatch.setattr(watch.jobs, "submit", lambda *a, **k: submitted.append((a, k)) or 1)
    submitted = []
    yield tmp_path, submitted
    settings.set_many({"watch_folder": "", "watch_computer": ""})


def album(root, name="Zyx Band - 2021 - Qwerty Songs", songs=("1. Opening Qwerty.mp3", "2. Closing Qwerty.mp3"), extra=("info.nfo",)):
    d = root / name
    d.mkdir()
    for s in songs:
        (d / s).write_bytes(b"\xff\xfb" + b"0" * 4000)
    for e in extra:
        (d / e).write_text("notes")
    return d


def song(no, length, title="Song"):
    return {"disc": 1, "no": no, "title": f"{title} {no}", "length": length, "albumartist": "", "artist": "", "album": "", "year": 0}


def test_a_release_fits_by_its_songs_lengths():
    ours = [song(1, 200.4), song(2, 315.0), song(3, 61.0)]
    assert watch.fits(ours, [{"length": 201}, {"length": 313}, {"length": 61}])
    assert not watch.fits(ours, [{"length": 201}, {"length": 313}])                    # a song short
    assert not watch.fits(ours, [{"length": 201}, {"length": 290}, {"length": 61}])    # one far off
    assert not watch.fits(ours, [{"length": 0}, {"length": 0}, {"length": 61}])        # too little to go by


def test_named_by_tags_or_folder():
    tagged = [{**song(1, 1), "albumartist": "Zyx Band", "album": "Qwerty"}]
    assert watch._named(tagged, "whatever") == ("Zyx Band", "Qwerty")
    assert watch._named([song(1, 1)], "Zyx Band - 2021 - Qwerty Songs") == ("Zyx Band", "Qwerty Songs")


def test_musicbrainz_first_then_bandcamp(monkeypatch):
    ours = [{**song(1, 100), "albumartist": "Zyx Band", "album": "Qwerty"}, {**song(2, 200), "album": "Qwerty"}]
    monkeypatch.setattr(watch.providers, "_musicbrainz", lambda kind, a, t, al: [{"id": "mb-1", "tracks": 2}])
    monkeypatch.setattr(watch.providers, "_bandcamp", lambda kind, a, t, al: [{"id": "1/2"}])
    details = {"mb-1": {"title": "Qwerty", "artist": "Zyx Band", "mbid": "mb-1", "tracks": [{"length": 100}, {"length": 260}]},
               "1/2": {"title": "Qwerty", "artist": "Zyx Band", "tracks": [{"length": 101}, {"length": 199}]}}
    monkeypatch.setattr(watch.providers, "details", lambda source, kind, i: details[i])
    assert watch.match(ours, "x")[:2] == ("bandcamp", "1/2")                 # MusicBrainz's second song is longer
    details["mb-1"]["tracks"][1]["length"] = 201
    assert watch.match(ours, "x")[:2] == ("musicbrainz", "mb-1")
    monkeypatch.setattr(watch.providers, "details", lambda source, kind, i: {"tracks": []})
    assert watch.match(ours, "x") == ("none", "", None)


def test_taken_once_it_stays_as_it_is(folder, monkeypatch):
    root, submitted = folder
    album(root)
    (root / "_Done").mkdir()                                  # its own: left alone
    now = [1000.0]
    monkeypatch.setattr(watch.time, "time", lambda: now[0])
    monkeypatch.setattr(watch, "_busy", lambda: set())
    watch._seen.clear()
    watch.check()
    assert watch.state()["waiting"] == ["Zyx Band - 2021 - Qwerty Songs"] and not submitted
    now[0] += 60
    (root / "Zyx Band - 2021 - Qwerty Songs" / "3. Bonus Qwerty.mp3").write_bytes(b"x")    # still coming in
    watch.check()
    assert not submitted
    now[0] += watch.SETTLE
    watch.check()
    (args, params), = submitted
    assert args[0] == "import_watched" and params == {"name": "Zyx Band - 2021 - Qwerty Songs", "key": f"server:{root}"}


def filed(calls, gone=True, albums=None):
    """file_music as beets does it: the music moved out of the folder, and the albums as filed."""
    def fake(ctx, source, batch, autotag=None, search_id=""):
        calls.append({"source": source, "autotag": autotag, "search_id": search_id})
        if gone:
            for p in list(source.rglob("*.mp3")):
                p.unlink()
        return {"albums": albums if albums is not None else
                [{"artist": "Zyx Band", "album": "Qwerty Songs", "folder": "/lib/Rock/Zyx Band/x", "songs": 2, "mbid": search_id}]}
    return fake


def test_filed_with_musicbrainz_and_the_rest_to_done(folder, monkeypatch):
    root, _ = folder
    album(root)
    calls = []
    monkeypatch.setattr(watch.duplicates, "check", lambda files, s: {"found": [], "skip": []})
    monkeypatch.setattr(watch, "match", lambda songs, name, ctx=None: ("musicbrainz", "mb-1", {}))
    monkeypatch.setattr(watch.importer, "file_music", filed(calls))
    got = watch.import_watched(Ctx(), "Zyx Band - 2021 - Qwerty Songs", f"server:{root}")
    assert got["match"] == "musicbrainz" and got["albums"][0]["album"] == "Qwerty Songs"
    assert calls == [{"source": root / "Zyx Band - 2021 - Qwerty Songs", "autotag": None, "search_id": "mb-1"}]
    assert not (root / "Zyx Band - 2021 - Qwerty Songs").exists()
    assert (root / "_Done" / "Zyx Band - 2021 - Qwerty Songs" / "info.nfo").read_text() == "notes"


def test_bandcamps_tags_and_nothing_left(folder, monkeypatch):
    root, _ = folder
    album(root, extra=())
    calls, applied = [], []
    monkeypatch.setattr(watch.duplicates, "check", lambda files, s: {"found": [], "skip": []})
    monkeypatch.setattr(watch, "match", lambda songs, name, ctx=None: ("bandcamp", "1/2", {"title": "Qwerty Songs", "artist": "Zyx Band"}))
    monkeypatch.setattr(watch, "_apply", lambda songs, d, f: applied.append((len(songs), d["title"], f.name)))
    monkeypatch.setattr(watch.importer, "file_music", filed(calls))
    got = watch.import_watched(Ctx(), "Zyx Band - 2021 - Qwerty Songs", f"server:{root}")
    assert applied == [(2, "Qwerty Songs", "Zyx Band - 2021 - Qwerty Songs")]
    assert got["match"] == "bandcamp" and got["albums"][0]["match"] == "bandcamp"
    assert calls[0]["autotag"] is False and calls[0]["search_id"] == ""      # filed as Bandcamp has it
    assert not (root / "Zyx Band - 2021 - Qwerty Songs").exists() and not (root / "_Done").exists()


def test_duplicates_and_failures_set_aside(folder, monkeypatch):
    root, _ = folder
    album(root)
    monkeypatch.setattr(watch.duplicates, "check", lambda files, s: {"found": [{"path": files[0][0], "why": "library"}], "skip": []})
    got = watch.import_watched(Ctx(), "Zyx Band - 2021 - Qwerty Songs", f"server:{root}")
    assert got["duplicate"] and (root / "_Duplicates" / "Zyx Band - 2021 - Qwerty Songs" / "1. Opening Qwerty.mp3").exists()
    assert watch.ServerPlace(str(root)).held()["_Duplicates"] == ["Zyx Band - 2021 - Qwerty Songs"]

    # filed anyway, from _Duplicates: no looking for duplicates again; beets fails, and it's in _Failed
    def broken(*a, **k):
        raise RuntimeError("beet import failed (1)")
    monkeypatch.setattr(watch, "match", lambda songs, name, ctx=None: ("none", "", None))
    monkeypatch.setattr(watch.importer, "file_music", broken)
    with pytest.raises(RuntimeError):
        watch.import_watched(Ctx(), "Zyx Band - 2021 - Qwerty Songs", f"server:{root}", held="_Duplicates")
    assert (root / "_Failed" / "Zyx Band - 2021 - Qwerty Songs" / "info.nfo").exists()
    assert not (root / "_Duplicates" / "Zyx Band - 2021 - Qwerty Songs").exists()


def test_a_song_by_itself_gets_a_folder(folder, monkeypatch):
    root, _ = folder
    (root / "Lonely Qwerty Song.mp3").write_bytes(b"\xff\xfb" + b"0" * 4000)
    calls = []
    monkeypatch.setattr(watch.duplicates, "check", lambda files, s: {"found": [], "skip": []})
    monkeypatch.setattr(watch, "match", lambda songs, name, ctx=None: ("none", "", None))
    monkeypatch.setattr(watch.importer, "file_music", filed(calls))
    got = watch.import_watched(Ctx(), "Lonely Qwerty Song.mp3", f"server:{root}")
    assert got["match"] == "none" and calls[0]["source"].name == "Lonely Qwerty Song"
    assert not (root / "Lonely Qwerty Song.mp3").exists()


def test_the_folder_changed_meanwhile(folder):
    root, _ = folder
    with pytest.raises(RuntimeError):
        watch.import_watched(Ctx(), "x", "server:/elsewhere")


def test_an_artists_albums_each_by_itself(folder, monkeypatch):
    """A folder of albums (a discography): each looked up by itself, beets files them in one go, and each
    says how it was matched."""
    root, _ = folder
    disco = root / "zyx-band"
    album(disco.parent, "zyx-band", songs=(), extra=())
    for name in ("first-album", "second-album", "live-album"):
        album(disco, name, songs=("01 a.mp3", "02 b.mp3"), extra=())
    (disco / "second-album" / "CD2").mkdir()
    (disco / "second-album" / "CD2" / "01 c.mp3").write_bytes(b"\xff\xfb" + b"0" * 4000)
    looked, applied, calls = [], [], []

    def lookup(songs, name, ctx=None):
        looked.append((name, len(songs)))
        return ("bandcamp", "1/2", {"title": "Live Album", "artist": "Zyx Band"}) if name == "live-album" else ("none", "", None)
    monkeypatch.setattr(watch.duplicates, "check", lambda files, s: {"found": [], "skip": []})
    monkeypatch.setattr(watch, "match", lookup)
    monkeypatch.setattr(watch, "_apply", lambda songs, d, f: applied.append(f.name))
    filed_albums = [{"artist": "Zyx Band", "album": "First Album", "folder": "/lib/1", "songs": 2, "mbid": "mb-1"},
                    {"artist": "Zyx Band", "album": "Second Album", "folder": "/lib/2", "songs": 3, "mbid": "mb-2"},
                    {"artist": "Zyx Band", "album": "Live Album", "folder": "/lib/3", "songs": 2, "mbid": ""}]
    monkeypatch.setattr(watch.importer, "file_music", filed(calls, albums=filed_albums))
    got = watch.import_watched(Ctx(), "zyx-band", f"server:{root}")
    assert sorted(looked) == [("first-album", 2), ("live-album", 2), ("second-album", 3)]    # CD2 with its album
    assert applied == ["live-album"]
    assert calls == [{"source": disco, "autotag": None, "search_id": ""}]                 # one import, beets matches each
    assert [a["match"] for a in got["albums"]] == ["musicbrainz", "musicbrainz", "bandcamp"] and got["match"] == "mixed"


def test_how_each_album_was_matched_the_import_or_the_librarys_word():
    """The import log and the watch folder's list say per album how it was matched: the import's own word, or
    for an older one (which only had one word for the whole folder) whether the library has a MusicBrainz id."""
    from muzix import db
    from muzix.api.upload import filed
    from muzix.models import Album
    with db.session() as s:
        s.add_all([Album(title="Matched Qwerty", folder="/lib/Metal/Qwop/Qwop - 1999 - Matched Qwerty", key="qwop-1", mbid="mb-9"),
                   Album(title="Live Qwerty", folder="/lib/Metal/Qwop/Qwop - 2008 - Live Qwerty", key="qwop-2", mbid="")])
    old = {"match": "none", "music_root": "/lib", "albums": [
        {"artist": "Qwop", "album": "Matched Qwerty", "folder": "/lib/Metal/Qwop/Qwop - 1999 - Matched Qwerty", "songs": 9},
        {"artist": "Qwop", "album": "Live Qwerty", "folder": "/lib/Metal/Qwop/Qwop - 2008 - Live Qwerty", "songs": 12},
        {"artist": "Qwop", "album": "Not Scanned Yet", "folder": "/lib/Metal/Qwop/Qwop - 2010 - Not Scanned Yet", "songs": 3}]}
    with db.session() as s:
        got = filed(old, s)
    assert [(a["match"], a["where"], bool(a["album_id"])) for a in got] == [
        ("musicbrainz", "Metal/Qwop/Qwop - 1999 - Matched Qwerty", True), ("none", "Metal/Qwop/Qwop - 2008 - Live Qwerty", True),
        ("", "Metal/Qwop/Qwop - 2010 - Not Scanned Yet", False)]
    new = {"music_root": "/lib", "albums": [{"artist": "Qwop", "album": "Live Qwerty", "songs": 12, "match": "bandcamp",
                                             "folder": "/lib/Metal/Qwop/Qwop - 2008 - Live Qwerty", "mbid": ""}]}
    with db.session() as s:
        assert filed(new, s)[0]["match"] == "bandcamp"
