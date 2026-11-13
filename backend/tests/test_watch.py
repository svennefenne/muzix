"""The watch folder (watch.py): an album is taken once it stays as it is, looked up on MusicBrainz and then
Bandcamp by its songs' lengths, filed as uploads are, and what's left, a duplicate or a failure set aside."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from muzix import db, settings, watch


class Ctx:
    def __init__(self):
        self.lines = []

    def log(self, line):
        self.lines.append(line)

    def update(self, *a):
        pass


@pytest.fixture
def folder(tmp_path, monkeypatch):
    settings.set_many({"watch_folder": str(tmp_path), "watch_computer": "", "watch_folders": []})
    monkeypatch.setattr(watch.env, "UPLOAD_DIR", tmp_path.parent / (tmp_path.name + "-uploads"))
    monkeypatch.setattr(watch.jobs, "submit", lambda *a, **k: submitted.append((a, k)) or 1)
    submitted = []
    yield tmp_path, submitted
    settings.set_many({"watch_folder": "", "watch_computer": "", "watch_folders": []})


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
    asked = []
    monkeypatch.setattr(watch.providers, "details", lambda source, kind, i, artist="": asked.append(artist) or details[i])
    assert watch.match(ours, "x")[:2] == ("bandcamp", "1/2")                 # MusicBrainz's second song is longer
    assert set(asked) == {"Zyx Band"}           # whose album it is, as its songs say (not a compilation on Bandcamp)
    details["mb-1"]["tracks"][1]["length"] = 201
    assert watch.match(ours, "x")[:2] == ("musicbrainz", "mb-1")
    monkeypatch.setattr(watch.providers, "details", lambda source, kind, i, artist="": {"tracks": []})
    assert watch.match(ours, "x") == ("none", "", None)


def test_taken_once_it_stays_as_it_is(folder, monkeypatch):
    root, submitted = folder
    album(root)
    (root / "_Done").mkdir()                                  # its own: left alone
    now = [1000.0]
    monkeypatch.setattr(watch.time, "time", lambda: now[0])
    monkeypatch.setattr(watch, "_busy", lambda key: set())
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
    def fake(ctx, source, batch, autotag=None, search_id="", duplicate=False, bandcamp_tags=None):
        calls.append({"source": source, "autotag": autotag, "search_id": search_id, **({"duplicate": True} if duplicate else {}),
                      **({"bandcamp_tags": bandcamp_tags} if bandcamp_tags else {})})
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
    monkeypatch.setattr(watch, "match", lambda songs, name, ctx=None, sources=watch.SOURCES: ("musicbrainz", "mb-1", {}))
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
    monkeypatch.setattr(watch, "match", lambda songs, name, ctx=None, sources=watch.SOURCES: ("bandcamp", "1/2", {"title": "Qwerty Songs", "artist": "Zyx Band"}))
    monkeypatch.setattr(watch, "_apply", lambda songs, d, f: applied.append((len(songs), d["title"], f.name)))
    monkeypatch.setattr(watch.importer, "file_music", filed(calls))
    got = watch.import_watched(Ctx(), "Zyx Band - 2021 - Qwerty Songs", f"server:{root}")
    assert applied == [(2, "Qwerty Songs", "Zyx Band - 2021 - Qwerty Songs")]
    assert got["match"] == "bandcamp" and got["albums"][0]["match"] == "bandcamp"
    assert calls[0]["autotag"] is False and calls[0]["search_id"] == ""      # filed as Bandcamp has it
    assert not (root / "Zyx Band - 2021 - Qwerty Songs").exists() and not (root / "_Done").exists()


def test_bandcamps_tags_go_with_each_album_whoever_matched_it(folder, monkeypatch):
    """Each album's Bandcamp tags (its genre first), for its main genre to go by too: from the match when
    Bandcamp's, looked up on Bandcamp too when MusicBrainz's (The Operator Sound INC.'s album, MusicBrainz's
    with no genres, went to Pop by Last.fm alone), none when neither has it; kept for the artist's tags."""
    root, _ = folder
    d = root / "zyx-band"
    d.mkdir()
    for name in ("on-musicbrainz", "on-bandcamp", "nowhere"):
        album(d, name)
    calls, looked, kept = [], [], []
    monkeypatch.setattr(watch.duplicates, "check", lambda files, s: {"found": [], "skip": []})
    monkeypatch.setattr(watch, "match", lambda songs, name, ctx=None, sources=watch.SOURCES: {
        "on-musicbrainz": ("musicbrainz", "mb-1", {"title": "On MB", "artist": "Zyx Band"}),
        "on-bandcamp": ("bandcamp", "1/2", {"title": "On BC", "artist": "Zyx Band", "tags": ["Rock", "post-rock"]}),
    }.get(name, ("none", "", None)))
    monkeypatch.setattr(watch, "bandcamp_tags", lambda songs, name, ctx=None: looked.append(name) or ["Electronic", "dungeon synth"])
    monkeypatch.setattr(watch, "_apply", lambda songs, d, f: None)
    monkeypatch.setattr(watch.enrich, "keep_bandcamp_tags", lambda albums: kept.append(albums))
    monkeypatch.setattr(watch.importer, "file_music", filed(calls))
    watch.import_watched(Ctx(), "zyx-band", f"server:{root}")
    assert looked == ["on-musicbrainz"]
    assert calls[0]["bandcamp_tags"] == {str(d / "on-musicbrainz"): ["Electronic", "dungeon synth"],
                                         str(d / "on-bandcamp"): ["Rock", "post-rock"]}
    assert calls[0]["autotag"] is None and len(kept) == 1


def test_a_bandcamp_only_folder_asks_bandcamp_alone(folder, monkeypatch):
    """A watch folder for Bandcamp only: its albums looked up on Bandcamp alone, and beets doesn't match them
    with MusicBrainz either, Bandcamp's or not."""
    root, _ = folder
    album(root)
    place = watch.ServerPlace(str(root))
    place.only = "bandcamp"
    monkeypatch.setattr(watch, "place", lambda key="": place)
    asked, calls = [], []
    monkeypatch.setattr(watch.duplicates, "check", lambda files, s: {"found": [], "skip": []})
    monkeypatch.setattr(watch, "match", lambda songs, name, ctx=None, sources=watch.SOURCES: asked.append(sources) or ("none", "", None))
    monkeypatch.setattr(watch.importer, "file_music", filed(calls))
    watch.import_watched(Ctx(), QWERTY, place.key)
    assert asked == [("bandcamp",)] and calls[0]["autotag"] is False


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
    monkeypatch.setattr(watch, "match", lambda songs, name, ctx=None, sources=watch.SOURCES: ("none", "", None))
    monkeypatch.setattr(watch.importer, "file_music", broken)
    with pytest.raises(RuntimeError):
        watch.import_watched(Ctx(), "Zyx Band - 2021 - Qwerty Songs", f"server:{root}", held="_Duplicates")
    assert (root / "_Failed" / "Zyx Band - 2021 - Qwerty Songs" / "info.nfo").exists()
    assert not (root / "_Duplicates" / "Zyx Band - 2021 - Qwerty Songs").exists()


def test_filed_anyway_goes_to_the_librarys_duplicates_tried_again_as_any_album(folder, monkeypatch):
    root, _ = folder
    for held in ("_Duplicates", "_Failed"):
        (root / held).mkdir()
        album(root / held, "Zyx Band - 2021 - Qwerty Songs")
    calls = []
    monkeypatch.setattr(watch.duplicates, "check", lambda files, s: pytest.fail("not looked for again"))
    monkeypatch.setattr(watch, "match", lambda songs, name, ctx=None, sources=watch.SOURCES: ("musicbrainz", "mb-1", {}))
    monkeypatch.setattr(watch.importer, "file_music", filed(calls))
    watch.import_watched(Ctx(), "Zyx Band - 2021 - Qwerty Songs", f"server:{root}", held="_Duplicates")
    watch.import_watched(Ctx(), "Zyx Band - 2021 - Qwerty Songs", f"server:{root}", held="_Failed")
    assert [c.get("duplicate", False) for c in calls] == [True, False]


@pytest.mark.skipif(not shutil.which("ffmpeg") or not (Path(sys.executable).parent / "beet").exists(),
                    reason="needs beets (pip install -e './backend[organize]') and ffmpeg")
def test_a_duplicate_filed_with_beets_lands_beside_the_librarys_other_copies(tmp_path, monkeypatch):
    """Duplicates/<artist>/<Artist - Year - Album> (n), the first n the library hasn't got, as the library's
    own duplicates are named; never beside the copy in its genre folder with beets' ".1" names."""
    from muzix import db, env
    from muzix.models import Root
    from muzix.organize import importer

    lib = tmp_path / "lib"
    (lib / "Rock" / "Zyx Band" / "Zyx Band - 2021 - Qwerty Songs").mkdir(parents=True)
    (lib / "Duplicates" / "Zyx Band" / "Zyx Band - 2021 - Qwerty Songs (2)").mkdir(parents=True)
    src = tmp_path / "in" / "qwerty"
    src.mkdir(parents=True)
    for n in (1, 2):
        subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "anullsrc=r=44100", "-t", "1",
                        *[x for k, v in {"artist": "Zyx Band", "album_artist": "Zyx Band", "album": "Qwerty Songs",
                                         "date": "2021", "track": str(n), "title": f"Song {n}"}.items()
                          for x in ("-metadata", f"{k}={v}")], str(src / f"{n}.mp3")], check=True)
    beets = tmp_path / "beets"
    beets.mkdir()
    # Last.fm's word on the band, so nothing is asked online
    (beets / "lastfm-cache.json").write_text(json.dumps({"artist\x1fzyx band": [["rock", 100]],
                                                         "album\x1fzyx band\x1fqwerty songs": [["rock", 100]]}))
    monkeypatch.setattr(env, "BEETS_DIR", beets)
    monkeypatch.setattr(importer, "BEET", str(Path(sys.executable).parent / "beet"))
    was = {k: settings.get(k) for k in ("upload_genre_folders", "upload_fetch_art")}
    settings.set_many({"upload_genre_folders": True, "upload_fetch_art": False})
    with db.session() as s:
        s.add(Root(path=str(lib), kind="music", upload_target=True))
        s.commit()
    try:
        got = importer.file_music(Ctx(), src, "dupe-test", autotag=False, duplicate=True)
    finally:
        settings.set_many(was)
        with db.session() as s:
            s.query(Root).filter(Root.path == str(lib)).delete()
            s.commit()
    there = lib / "Duplicates" / "Zyx Band" / "Zyx Band - 2021 - Qwerty Songs (3)"
    assert sorted(p.name for p in there.iterdir()) == ["1. Zyx Band - Qwerty Songs - Song 1 (2021).mp3",
                                                         "2. Zyx Band - Qwerty Songs - Song 2 (2021).mp3"]
    assert not any((lib / "Rock" / "Zyx Band" / "Zyx Band - 2021 - Qwerty Songs").iterdir())
    assert [a["folder"] for a in got["albums"]] == [str(there)]


@pytest.mark.skipif(not shutil.which("ffmpeg") or not (Path(sys.executable).parent / "beet").exists(),
                    reason="needs beets (pip install -e './backend[organize]') and ffmpeg")
@pytest.mark.parametrize("tags, known, lastfm, where", [
    # Last.fm's "pop" alone would file it in Pop (The Operator Sound INC.'s case): Bandcamp's tags make it Electronic
    (["Electronic", "Experimental", "dungeon synth", "easy listening", "modular synth"], {},
     [["space age pop", 100], ["modular synth", 67]], "Electronic"),
    # Bandcamp's psytrance is psytrance: whatever Last.fm says of a namesake, and though the artist is in Rock already
    (["Electronic", "Progressive Trance", "Psychedelic Trance", "Psytrance"], {"Zyx Band": "Rock"},
     [["rock", 100], ["hard rock", 60]], "Psytrance"),
])
def test_filed_with_beets_bandcamps_tags_decide_the_main_genre_with_last_fms(tmp_path, monkeypatch, tags, known, lastfm, where):
    """Through beets and musicorg: the album filed where Bandcamp's tags say, and saying them."""
    from muzix import db, env
    from muzix.models import Root
    from muzix.organize import importer

    lib = tmp_path / "lib"
    lib.mkdir()
    src = tmp_path / "in" / "esoteric"
    src.mkdir(parents=True)
    for n in (1, 2):
        subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "anullsrc=r=44100", "-t", "1",
                        *[x for k, v in {"artist": "Zyx Band", "album_artist": "Zyx Band", "album": "Esoteric Songs",
                                         "date": "2026", "track": str(n), "title": f"Song {n}"}.items()
                          for x in ("-metadata", f"{k}={v}")], str(src / f"{n}.mp3")], check=True)
    beets = tmp_path / "beets"
    beets.mkdir()
    (beets / "lastfm-cache.json").write_text(json.dumps({"artist\x1fzyx band": lastfm, "album\x1fzyx band\x1fesoteric songs": []}))
    monkeypatch.setattr(env, "BEETS_DIR", beets)
    monkeypatch.setattr(importer, "write_artist_genres", lambda: (beets / "artist-genres.json").write_text(json.dumps(known)))
    monkeypatch.setattr(importer, "BEET", str(Path(sys.executable).parent / "beet"))
    was = {k: settings.get(k) for k in ("upload_genre_folders", "upload_fetch_art")}
    settings.set_many({"upload_genre_folders": True, "upload_fetch_art": False})
    with db.session() as s:
        s.add(Root(path=str(lib), kind="music", upload_target=True))
        s.commit()
    try:
        got = importer.file_music(Ctx(), src, "bc-test", autotag=False, bandcamp_tags={str(src): tags})
    finally:
        settings.set_many(was)
        with db.session() as s:
            s.query(Root).filter(Root.path == str(lib)).delete()
            s.commit()
    [filed_album] = got["albums"]
    assert filed_album["folder"] == str(lib / where / "Zyx Band" / "Zyx Band - 2026 - Esoteric Songs")
    assert filed_album["tags"] == tags and "came" not in filed_album
    assert not (beets / "bandcamp-bc-test.json").exists()


def test_a_song_by_itself_gets_a_folder(folder, monkeypatch):
    root, _ = folder
    (root / "Lonely Qwerty Song.mp3").write_bytes(b"\xff\xfb" + b"0" * 4000)
    calls = []
    monkeypatch.setattr(watch.duplicates, "check", lambda files, s: {"found": [], "skip": []})
    monkeypatch.setattr(watch, "match", lambda songs, name, ctx=None, sources=watch.SOURCES: ("none", "", None))
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

    def lookup(songs, name, ctx=None, sources=watch.SOURCES):
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


QWERTY = "Zyx Band - 2021 - Qwerty Songs"


def test_set_aside_only_when_at_least_half_its_songs_are_in_the_library(folder, monkeypatch):
    """One song like one of a single in the library doesn't make an album a duplicate (Jinjer's albums,
    2026-11-12): fewer than half of its songs found, it's filed as any album."""
    root, _ = folder
    album(root, songs=("1. A.mp3", "2. B.mp3", "3. C.mp3"))
    album(root, "Zyx Band - 2022 - Again", songs=("1. A.mp3", "2. B.mp3", "3. C.mp3", "4. D.mp3"))
    monkeypatch.setattr(watch.duplicates, "check", lambda files, s: {"found": [{"path": f[0], "why": "similar"} for f in files[:2]],
                                                                     "skip": []})
    monkeypatch.setattr(watch, "match", lambda songs, name, ctx=None, sources=watch.SOURCES: ("none", "", None))
    calls, ctx = [], Ctx()
    monkeypatch.setattr(watch.importer, "file_music", filed(calls))
    with_one = {"found": [{"path": "x", "why": "similar"}], "skip": []}
    monkeypatch.setattr(watch.duplicates, "check", lambda files, s: with_one)
    got = watch.import_watched(ctx, QWERTY, f"server:{root}")
    assert not got.get("duplicate") and len(calls) == 1
    assert any("1 of its 3 songs" in line and "filed as any album" in line for line in ctx.lines)
    monkeypatch.setattr(watch.duplicates, "check", lambda files, s: {"found": [{"path": f[0], "why": "similar"} for f in files[:2]],
                                                                     "skip": []})
    got = watch.import_watched(Ctx(), "Zyx Band - 2022 - Again", f"server:{root}")
    assert got["duplicate"] and got["songs"] == 4 and len(got["found"]) == 2 and len(calls) == 1
    assert (root / "_Duplicates" / "Zyx Band - 2022 - Again").is_dir()


def _discography(root):
    """An artist's folder: two albums the library has (one with a disc of its own), one it hasn't."""
    d = root / "zyx-band"
    d.mkdir()
    album(d, "known-one")
    (d / "known-two").mkdir()
    album(d / "known-two", "CD1")
    album(d, "new-one", songs=("1. Fresh.mp3", "2. Fresher.mp3", "3. Freshest.mp3"))
    return d


def _found_in(*albums, one_of=""):
    """The songs of `albums` found in the library, and one of `one_of`'s (fewer than half of it)."""
    return lambda files, s: {"found": [{"path": f[0], "why": "same"} for f in files if f[0].split("/")[1] in albums
                                       or f[0] == f"zyx-band/{one_of}/1. Fresh.mp3"], "skip": []}


def test_of_an_artists_albums_those_the_library_has_are_set_aside_and_the_rest_filed(folder, monkeypatch):
    """Each album of a folder of albums is judged by itself (Perturbator's, 2026-11-12: seven the library had,
    Terror 404 new): those the library has go to _Duplicates/<the folder>, the new one is filed."""
    root, _ = folder
    _discography(root)
    monkeypatch.setattr(watch.duplicates, "check", _found_in("known-one", "known-two", one_of="new-one"))
    monkeypatch.setattr(watch, "match", lambda songs, name, ctx=None, sources=watch.SOURCES: ("none", "", None))
    calls, ctx = [], Ctx()
    monkeypatch.setattr(watch.importer, "file_music", filed(calls))
    got = watch.import_watched(ctx, "zyx-band", f"server:{root}")
    assert not got.get("duplicate") and len(calls) == 1
    assert got["aside"]["albums"] == ["known-one", "known-two"] and got["aside"]["songs"] == 4
    assert {f["path"].split("/")[1] for f in got["aside"]["found"]} == {"known-one", "known-two"}
    assert (root / "_Duplicates" / "zyx-band" / "known-one" / "1. Opening Qwerty.mp3").exists()
    assert (root / "_Duplicates" / "zyx-band" / "known-two" / "CD1" / "2. Closing Qwerty.mp3").exists()
    assert not (root / "zyx-band").exists() and not (root / "_Done" / "zyx-band" / "known-one").exists()
    assert any("2 of its 3 albums" in line for line in ctx.lines)

    # all of them the library has: the folder set aside whole, as one album is
    _discography(root)
    monkeypatch.setattr(watch.duplicates, "check", _found_in("known-one", "known-two", "new-one"))
    got = watch.import_watched(Ctx(), "zyx-band", f"server:{root}")
    assert got["duplicate"] and len(calls) == 1 and (root / "_Duplicates" / "zyx-band (2)" / "new-one").is_dir()


def test_from_a_computer_too_and_with_an_older_desktop_the_folder_as_one(folder, monkeypatch):
    root, _ = folder
    _discography(root)
    comp = Computer(root)
    calls = _from_a_computer(monkeypatch, comp, albums=[{"artist": "Zyx Band", "album": "New One", "folder": "/lib/x", "songs": 3}])
    monkeypatch.setattr(watch.duplicates, "check", _found_in("known-one", "known-two"))
    got = watch.import_watched(Ctx(), "zyx-band", comp.key)
    assert got["aside"]["albums"] == ["known-one", "known-two"] and got["removed"] and len(calls) == 1
    assert (root / "_Duplicates" / "zyx-band" / "known-one").is_dir() and not (root / "zyx-band").exists()

    # a Muzix Desktop before 0.4.23 can't set part of a folder aside: judged as one, as before
    _discography(root)
    comp = Computer(root, old=True)
    _from_a_computer(monkeypatch, comp)
    monkeypatch.setattr(watch.duplicates, "check", _found_in("known-one", "known-two"))
    ctx = Ctx()
    got = watch.import_watched(ctx, "zyx-band", comp.key)
    assert got["duplicate"] and "aside" not in got and (root / "_Duplicates" / "zyx-band (2)" / "new-one").is_dir()
    assert any("couldn't set some of its albums aside" in line for line in ctx.lines)


def test_transfer_now_takes_what_isnt_still_coming_in(folder, monkeypatch):
    root, submitted = folder
    album(root)
    album(root, "Zyx Band - 2022 - Arriving")
    monkeypatch.setattr(watch, "_busy", lambda key: set())
    monkeypatch.setattr(watch, "NOW_LOOK", 0)
    watch._seen.clear()
    entries, looks = watch.ServerPlace.entries, []

    def looked(self, held=""):
        looks.append(held)
        if len(looks) == 2:         # between the two looks, one album gets another song
            (root / "Zyx Band - 2022 - Arriving" / "3. More.mp3").write_bytes(b"\xff\xfb" + b"0" * 10)
        return entries(self, held)
    monkeypatch.setattr(watch.ServerPlace, "entries", looked)
    assert watch.check(now=True) == {"taken": [QWERTY], "waiting": ["Zyx Band - 2022 - Arriving"]}
    assert [params["name"] for _args, params in submitted] == [QWERTY]
    assert watch.state()["waiting"] == ["Zyx Band - 2022 - Arriving"]


class Computer(watch.ComputerPlace):
    """A computer's watch folder as its Muzix Desktop answers (desktop/muzix_desktop/sharing.py), here in a
    folder: `old` a Muzix Desktop before 0.4.22 (no deleting), `short` a file that comes short."""

    def __init__(self, root, old=False, short=""):
        super().__init__(1, "/home/someone/Incoming")
        self.root, self.old, self.short, self.asked = root, old, short, []
        self.here = watch.ServerPlace(str(root))

    def _ask(self, op, timeout=60, **args):
        self.asked.append(op)
        held = args.get("held") or ""
        if op == "watch_list":
            if not (self.root / held).is_dir():         # as Muzix Desktop answers for a folder that isn't there
                raise watch.tunnel.Refused(f"[Errno 2] No such file or directory: '{self.path}/{held}'")
            return [{"name": n, "files": [list(f) for f in fs]} for n, fs in self.here.entries(held).items()]
        if op == "watch_move":
            return self.here.move(args["name"], held, args["to"])
        if op == "watch_delete" and not self.old:
            return self.here.remove(args["name"], held)
        if op == "watch_aside" and not self.old:
            return self.here.aside(args["name"], args["parts"], args["to"])
        raise watch.tunnel.Refused(f"Unknown request {op}")

    def _file(self, rel, held):
        data = ((self.root / held) if held else self.root).joinpath(rel).read_bytes()
        yield data[:-1] if rel.endswith(self.short or "\0") else data


def _from_a_computer(monkeypatch, comp, albums=None):
    monkeypatch.setattr(watch, "place", lambda key="": comp)
    monkeypatch.setattr(watch.duplicates, "check", lambda files, s: {"found": [], "skip": []})
    monkeypatch.setattr(watch, "match", lambda songs, name, ctx=None, sources=watch.SOURCES: ("musicbrainz", "mb-1", {}))
    calls = []
    monkeypatch.setattr(watch.importer, "file_music", filed(calls, albums=albums))
    return calls


def test_from_a_computer_an_album_filed_whole_is_deleted_there(folder, monkeypatch):
    root, _ = folder
    album(root)
    comp = Computer(root)
    calls = _from_a_computer(monkeypatch, comp)
    got = watch.import_watched(Ctx(), QWERTY, comp.key)
    assert calls[0]["source"] != root / QWERTY                              # filed from a copy
    assert got["removed"] and "watch_delete" in comp.asked
    assert not (root / QWERTY).exists() and not (root / "_Done").exists()


def test_from_a_computer_an_album_not_filed_whole_is_kept(folder, monkeypatch):
    root, _ = folder
    album(root)                     # two songs; beets files one
    comp = Computer(root)
    _from_a_computer(monkeypatch, comp, albums=[{"artist": "Zyx Band", "album": "Qwerty Songs", "folder": "/lib/x", "songs": 1}])
    ctx = Ctx()
    got = watch.import_watched(ctx, QWERTY, comp.key)
    assert not got.get("removed") and "watch_delete" not in comp.asked
    assert (root / "_Done" / QWERTY / "1. Opening Qwerty.mp3").exists() and (root / "_Done" / QWERTY / "2. Closing Qwerty.mp3").exists()
    assert any("1 of its 2 songs were filed" in line for line in ctx.lines)

    # a Muzix Desktop before 0.4.22 can't delete: in _Done as before
    album(root, "Zyx Band - 2022 - Old")
    comp = Computer(root, old=True)
    _from_a_computer(monkeypatch, comp)
    got = watch.import_watched(Ctx(), "Zyx Band - 2022 - Old", comp.key)
    assert not got.get("removed") and (root / "_Done" / "Zyx Band - 2022 - Old" / "info.nfo").exists()


def test_from_a_computer_the_albums_set_aside_show_without_a_failed_folder(folder):
    """A computer's _Duplicates is listed though it has no _Failed (Muzix Desktop says that one isn't there)."""
    root, _ = folder
    (root / "_Duplicates").mkdir()
    album(root / "_Duplicates")
    comp = Computer(root)
    assert comp.held() == {"_Duplicates": [QWERTY], "_Failed": []}


def test_from_a_computer_a_file_that_comes_short_fails_the_album(folder, monkeypatch):
    root, _ = folder
    album(root)
    comp = Computer(root, short="2. Closing Qwerty.mp3")
    calls = _from_a_computer(monkeypatch, comp)
    with pytest.raises(RuntimeError, match="came short"):
        watch.import_watched(Ctx(), QWERTY, comp.key)
    assert not calls and (root / "_Failed" / QWERTY / "2. Closing Qwerty.mp3").stat().st_size == 4002


def test_in_place_of_the_librarys_copy(folder, monkeypatch, tmp_path_factory):
    """From _Duplicates, filed in place of the library's copy: that one goes to the library's Duplicates folder
    first (an album only some of whose songs were found stays), and back again if filing fails."""
    from muzix import db
    from muzix.models import Root
    root, _ = folder
    lib = tmp_path_factory.mktemp("lib")
    old = lib / "Metal" / "Zyx Band" / QWERTY
    single = lib / "Metal" / "Zyx Band" / "Zyx Band - 2020 - Opening Qwerty"
    for d, songs in ((old, ("1. Opening Qwerty.mp3", "2. Closing Qwerty.mp3")), (single, ("1. Opening Qwerty.mp3", "2. B.mp3", "3. C.mp3"))):
        d.mkdir(parents=True)
        for f in songs:
            (d / f).write_bytes(b"old")
    (lib / "Duplicates" / "Zyx Band" / QWERTY).mkdir(parents=True)          # taken: it goes to (2)
    (root / "_Duplicates").mkdir()
    album(root / "_Duplicates")
    found = [{"path": f"{QWERTY}/1. Opening Qwerty.mp3", "why": "similar", "match": {"path": str(old / "1. Opening Qwerty.mp3")}},
             {"path": f"{QWERTY}/2. Closing Qwerty.mp3", "why": "similar", "match": {"path": str(old / "2. Closing Qwerty.mp3")}},
             {"path": f"{QWERTY}/1. Opening Qwerty.mp3", "why": "similar", "match": {"path": str(single / "1. Opening Qwerty.mp3")}}]
    monkeypatch.setattr(watch.duplicates, "check", lambda files, s: {"found": found, "skip": []})
    monkeypatch.setattr(watch, "match", lambda songs, name, ctx=None, sources=watch.SOURCES: ("none", "", None))
    assert watch.replaced(found) == [str(old)]
    aside = lib / "Duplicates" / "Zyx Band" / f"{QWERTY} (2)"
    with db.session() as s:
        s.add(Root(path=str(lib), kind="music"))
        s.commit()
    try:
        def broken(*a, **k):
            raise RuntimeError("beet import failed (1)")
        monkeypatch.setattr(watch.importer, "file_music", broken)
        with pytest.raises(RuntimeError):
            watch.import_watched(Ctx(), QWERTY, f"server:{root}", held="_Duplicates", how="replace")
        assert (old / "1. Opening Qwerty.mp3").read_bytes() == b"old" and not aside.exists()      # back where it was

        (root / "_Failed" / QWERTY).rename(root / "_Duplicates" / QWERTY)
        calls = []
        monkeypatch.setattr(watch.importer, "file_music", filed(calls))
        got = watch.import_watched(Ctx(), QWERTY, f"server:{root}", held="_Duplicates", how="replace")
    finally:
        with db.session() as s:
            s.query(Root).filter(Root.path == str(lib)).delete()
            s.commit()
    assert calls[0].get("duplicate") is None                                 # filed as any album
    assert not old.exists() and (aside / "2. Closing Qwerty.mp3").read_bytes() == b"old"
    assert single.is_dir() and got["replaced"] == [{"from": str(old), "to": str(aside)}]
    with pytest.raises(ValueError):
        watch.import_watched(Ctx(), QWERTY, f"server:{root}", held="_Failed", how="replace")


def test_why_an_artists_albums_were_set_aside_and_what_was_filed_says_so():
    """The admin page's word on a folder some of whose albums were set aside: why (as for an album set aside
    whole, from an import before "found" was kept too), and in the latest imports how many."""
    from muzix import db
    from muzix.api import watch as api
    from muzix.models import Job
    found = [{"path": "zyx-band/known-one/1. A.mp3", "why": "same",
              "match": {"title": "A", "artist": "Zyx Band", "album": "Known One", "format": "mp3",
                        "path": "/music/Rock/Zyx Band/Zyx Band - 2020 - Known One/1. A.mp3"}}]
    with db.session() as s:
        s.add(Job(type="import_watched", status="done", params={"name": "zyx-band"},
                  result={"albums": [], "aside": {"albums": ["known-one"], "songs": 2, "found": found}}))
        s.add(Job(type="import_watched", status="done", params={"name": "Old One"}, result={"duplicate": True}))
        s.commit()
        why = api._why(s, ["zyx-band", "Old One"])
        assert why["zyx-band"]["songs"] == 2
        assert why["zyx-band"]["found"][0]["song"] == "1. A.mp3"
        assert why["zyx-band"]["found"][0]["folder"] == "/music/Rock/Zyx Band/Zyx Band - 2020 - Known One"
        assert why["Old One"] == {"songs": 0, "replaces": [], "found": []}
        assert next(r for r in api._recent(s) if r["name"] == "zyx-band")["aside"] == 1



def _client():
    from types import SimpleNamespace

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from muzix.api import watch as api
    from muzix.security import admin_user
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[admin_user] = lambda: SimpleNamespace(id=1, is_admin=True)
    return TestClient(app)


def test_a_second_watch_folder_for_bandcamp_alone(folder, tmp_path_factory, monkeypatch):
    """Another watch folder beside the first, its albums matched with Bandcamp alone: each looked in and
    filed with its own key and way; the first stays where older apps read it; one taken away, the next is first."""
    root, submitted = folder
    bc = tmp_path_factory.mktemp("bandcamp-only")
    c = _client()
    got = c.put("/api/admin/watch", json={"folder": str(bc), "only": "bandcamp", "at": 5}).json()     # one past the last
    assert [(f["folder"], f["only"]) for f in got["folders"]] == [(str(root), ""), (str(bc), "bandcamp")]
    assert got["folder"] == str(root) and got["folders"][1]["key"] == f"server:{bc}"
    assert c.put("/api/admin/watch", json={"folder": str(bc), "at": 0}).status_code == 400          # watched already
    assert c.put("/api/admin/watch", json={"folder": str(bc), "only": "elsewhere", "at": 1}).status_code == 400

    album(root)
    album(bc, "Zyx Band - 2022 - On Bandcamp")
    monkeypatch.setattr(watch, "NOW_LOOK", 0)
    assert c.post("/api/admin/watch/now", json={"key": f"server:{bc}"}).json()["taken"] == ["Zyx Band - 2022 - On Bandcamp"]
    assert submitted[-1][1] == {"name": "Zyx Band - 2022 - On Bandcamp", "key": f"server:{bc}"}
    assert c.post("/api/admin/watch/now").json()["taken"] == [QWERTY]                 # no key: the first, as before
    assert submitted[-1][1]["key"] == f"server:{root}"
    assert watch.place(f"server:{bc}").only == "bandcamp" and watch.place().only == ""

    # its way changed, then the first taken away: the Bandcamp one is first
    got = c.put("/api/admin/watch", json={"folder": str(bc), "only": "", "at": 1}).json()
    assert got["folders"][1]["only"] == ""
    got = c.put("/api/admin/watch", json={"folder": "", "at": 0}).json()
    assert [f["folder"] for f in got["folders"]] == [str(bc)] and got["folder"] == str(bc)
    assert settings.get("watch_folder") == str(bc)


def test_a_computer_lets_this_server_watch_more_than_one_folder_from_0_4_24(folder, monkeypatch):
    """Muzix Desktop says yes to each folder (watch_pick, and no longer the one it replaces); one before 0.4.24
    knows one folder only: it gets that one, but not a second."""
    from muzix.api import watch as api
    from muzix.models import Peer
    root, _ = folder
    settings.set_many({"watch_folder": "", "watch_folders": []})
    with db.session() as s:
        s.add(Peer(server_id="zq-laptop", name="Laptop", kind="computer", address="", sent=True, received=True))
        s.commit()
    asked, old = [], {"on": False}

    class Tunnel:
        def ask(self, op, **args):
            asked.append((op, args))
            if op == "watch_pick" and old["on"]:
                raise watch.tunnel.Refused(f"Unknown request {op}")
            return {}
    monkeypatch.setattr(api.tunnel, "get", lambda pid: Tunnel())
    c = _client()
    try:
        c.put("/api/admin/watch", json={"folder": "/home/z/In", "computer": "zq-laptop"}).raise_for_status()
        c.put("/api/admin/watch", json={"folder": "/home/z/Bandcamp", "computer": "zq-laptop", "only": "bandcamp", "at": 1}).raise_for_status()
        c.put("/api/admin/watch", json={"folder": "/home/z/In2", "computer": "zq-laptop", "at": 0}).raise_for_status()
        assert asked == [("watch_pick", {"path": "/home/z/In", "was": ""}), ("watch_pick", {"path": "/home/z/Bandcamp", "was": ""}),
                         ("watch_pick", {"path": "/home/z/In2", "was": "/home/z/In"})]

        old["on"], asked[:] = True, []
        r = c.put("/api/admin/watch", json={"folder": "/home/z/In3", "computer": "zq-laptop", "at": 0})
        assert r.status_code == 409 and "0.4.24" in r.json()["detail"]
        c.put("/api/admin/watch", json={"folder": "", "at": 1}).raise_for_status()           # the Bandcamp one gone
        c.put("/api/admin/watch", json={"folder": "/home/z/In3", "computer": "zq-laptop", "at": 0}).raise_for_status()
        assert ("watch_set", {"path": "/home/z/In3"}) in asked
        assert [f["folder"] for f in watch.folders()] == ["/home/z/In3"]
    finally:
        with db.session() as s:
            s.query(Peer).filter(Peer.server_id == "zq-laptop").delete()
            s.commit()
