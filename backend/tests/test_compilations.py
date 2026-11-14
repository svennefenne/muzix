"""Own compilations (organize/compilation.py): a folder of songs from different albums, filed as one album by
Various Artists named after the folder: from the watch folder's _Compilations, or a folder of an upload marked so."""
import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import mediafile
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from muzix import db, env, settings, watch
from muzix.api import upload
from muzix.organize import compilation, importer
from muzix.security import admin_user

HAS_FFMPEG = bool(shutil.which("ffmpeg"))
HAS_BEETS = HAS_FFMPEG and (Path(sys.executable).parent / "beet").exists()


class Ctx:
    def __init__(self):
        self.lines = []

    def log(self, line):
        self.lines.append(line)

    def update(self, *a):
        pass


def mp3(path: Path, **tags):
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100", "-t", "1",
                    *[x for k, v in tags.items() for x in ("-metadata", f"{k}={v}")], str(path)], check=True)


def mixed(folder: Path):
    """Three songs from three albums by three artists, numbered as their own albums have them."""
    for name, artist, album, no, year in (("01 Qwop.mp3", "Zyx Band", "Qwerty Songs", "7", "1984"),
                                          ("02 Asdf.mp3", "Plonk Duo", "Asdf Hits", "3", "1991"),
                                          ("03 Hjkl.mp3", "Mork Choir", "Hjkl", "11", "2003")):
        mp3(folder / name, artist=artist, album_artist=artist, album=album, track=no, date=year,
            title=name[3:-4], MusicBrainz_Album_Id="1111-2222", MusicBrainz_Album_Type="single")


def test_named_by_its_folder():
    assert compilation.title_of("Summer Mix") == ("Summer Mix", 0)
    assert compilation.title_of("Various Artists - 2024 - Summer Mix") == ("Summer Mix", 2024)
    assert compilation.title_of("VA - Summer Mix") == ("Summer Mix", 0)
    assert compilation.title_of("Summer Mix (2019)") == ("Summer Mix", 2019)
    assert compilation.title_of("Best of 1999 - Part 2") == ("Best of 1999 - Part 2", 0)
    assert compilation.title_of("1999") == ("1999", 1999)       # a name that's a year: still its name


@pytest.mark.skipif(not HAS_FFMPEG, reason="needs ffmpeg")
def test_its_songs_tagged_as_one_album(tmp_path):
    folder = tmp_path / "VA - Qwerty Mix"
    mixed(folder)
    mp3(folder / "CD2" / "01 Extra.mp3", artist="Zyx Band", album="Elsewhere", track="4", date="1999", title="Extra")
    got = compilation.make(folder)
    assert got == {"album": "Qwerty Mix", "year": 2003, "songs": 4}
    tags = {p.name: mediafile.MediaFile(str(p)) for p in folder.rglob("*.mp3")}
    assert {n: (m.album, m.albumartist, m.comp, m.disc, m.track, m.tracktotal, m.year, m.original_year)
            for n, m in tags.items()} == {
        "01 Qwop.mp3": ("Qwerty Mix", "Various Artists", True, 1, 1, 3, 2003, 1984),
        "02 Asdf.mp3": ("Qwerty Mix", "Various Artists", True, 1, 2, 3, 2003, 1991),
        "03 Hjkl.mp3": ("Qwerty Mix", "Various Artists", True, 1, 3, 3, 2003, 2003),
        "01 Extra.mp3": ("Qwerty Mix", "Various Artists", True, 2, 1, 1, 2003, 1999)}
    qwop = tags["01 Qwop.mp3"]
    assert (qwop.artist, qwop.title, qwop.mb_albumid, qwop.albumtypes) == ("Zyx Band", "Qwop", None, ["album", "compilation"])


@pytest.mark.skipif(not HAS_BEETS, reason="needs beets (pip install -e './backend[organize]') and ffmpeg")
def test_filed_with_beets_as_one_album_of_various_artists(tmp_path, monkeypatch):
    """Not split by its songs' albums into songs by themselves: one album, Genre/Various Artists/<it>."""
    from muzix.models import Root
    lib, src = tmp_path / "lib", tmp_path / "in" / "Various Artists - 2020 - Qwerty Mix"
    lib.mkdir()
    mixed(src)
    beets = tmp_path / "beets"
    beets.mkdir()
    (beets / "lastfm-cache.json").write_text(json.dumps({**{f"artist\x1f{a}": [["rock", 100]]
                                                            for a in ("zyx band", "plonk duo", "mork choir")},
                                                         "album\x1fvarious artists\x1fqwerty mix": [["rock", 100]]}))
    monkeypatch.setattr(env, "BEETS_DIR", beets)
    monkeypatch.setattr(importer, "BEET", str(Path(sys.executable).parent / "beet"))
    was = {k: settings.get(k) for k in ("upload_genre_folders", "upload_fetch_art")}
    settings.set_many({"upload_genre_folders": True, "upload_fetch_art": False})
    with db.session() as s:
        s.add(Root(path=str(lib), kind="music", upload_target=True))
    try:
        compilation.make(src)
        got = importer.file_music(Ctx(), src, "own-test", autotag=False, own=True)
    finally:
        settings.set_many(was)
        with db.session() as s:
            s.query(Root).filter(Root.path == str(lib)).delete()
    there = lib / "Rock" / "Various Artists" / "Various Artists - 2020 - Qwerty Mix"
    assert sorted(p.name for p in there.iterdir()) == ["1. Zyx Band - Qwerty Mix - Qwop (2020).mp3",
                                                         "2. Plonk Duo - Qwerty Mix - Asdf (2020).mp3",
                                                         "3. Mork Choir - Qwerty Mix - Hjkl (2020).mp3"]
    assert [(a["artist"], a["album"], a["songs"]) for a in got["albums"]] == [("Various Artists", "Qwerty Mix", 3)]


# ---------------------------------------------------------------- the watch folder's _Compilations

@pytest.fixture
def watched(tmp_path, monkeypatch):
    settings.set_many({"watch_folder": str(tmp_path), "watch_computer": "", "watch_folders": []})
    monkeypatch.setattr(watch.env, "UPLOAD_DIR", tmp_path.parent / (tmp_path.name + "-uploads"))
    submitted = []
    monkeypatch.setattr(watch.jobs, "submit", lambda *a, **k: submitted.append((a, k)) or 1)
    yield tmp_path, submitted
    settings.set_many({"watch_folder": "", "watch_computer": "", "watch_folders": []})


def test_the_watch_folder_has_one_for_compilations_and_takes_them(watched, monkeypatch):
    root, submitted = watched
    now = [1000.0]
    monkeypatch.setattr(watch.time, "time", lambda: now[0])
    monkeypatch.setattr(watch, "_busy", lambda key: set())
    watch._seen.clear()
    watch.check()
    assert (root / "_Compilations").is_dir() and not submitted          # made, for the admin to find
    (root / "_Compilations" / "Summer Mix").mkdir()
    (root / "_Compilations" / "Summer Mix" / "01 a.mp3").write_bytes(b"\xff\xfb" + b"0" * 4000)
    watch.check()
    assert watch.state()["waiting"] == ["_Compilations/Summer Mix"]
    now[0] += watch.SETTLE
    watch.check()
    (args, params), = submitted
    assert args == ("import_watched", "Watch folder: Summer Mix (own compilation)")
    assert params == {"name": "Summer Mix", "key": f"server:{root}", "held": "_Compilations"}


def test_a_compilation_from_the_watch_folder_is_filed_as_one(watched, monkeypatch):
    root, _ = watched
    folder = root / "_Compilations" / "Summer Mix"
    folder.mkdir(parents=True)
    (folder / "01 a.mp3").write_bytes(b"\xff\xfb" + b"0" * 4000)
    (folder / "cover.jpg").write_bytes(b"jpeg")
    made, calls = [], []
    monkeypatch.setattr(watch.compilation, "make", lambda f: made.append(f) or {"album": "Summer Mix", "songs": 1})
    monkeypatch.setattr(watch.duplicates, "check", lambda *a: pytest.fail("its songs may well be in the library"))

    def file_music(ctx, source, batch, autotag=None, own=False, **k):
        calls.append((source, autotag, own))
        (source / "01 a.mp3").unlink()
        return {"albums": [{"artist": "Various Artists", "album": "Summer Mix", "folder": "/lib/x", "songs": 1}]}
    monkeypatch.setattr(watch.importer, "file_music", file_music)
    got = watch.import_watched(Ctx(), "Summer Mix", f"server:{root}", held="_Compilations")
    assert made == [folder] and calls == [(folder, False, True)]
    assert got["match"] == "own" and got["albums"][0]["match"] == "own"
    assert not folder.exists() and (root / "_Done" / "Summer Mix" / "cover.jpg").exists()


# ---------------------------------------------------------------- an upload's folder marked one

BATCH = "20261114-120000-own1"


def client():
    a = FastAPI()
    a.include_router(upload.router)
    a.dependency_overrides[admin_user] = lambda: SimpleNamespace(id=1, is_admin=True)
    return TestClient(a)


@pytest.fixture
def batch():
    d = env.UPLOAD_DIR / BATCH
    yield d
    shutil.rmtree(d, ignore_errors=True)
    importer.own_file(BATCH).unlink(missing_ok=True)


@pytest.mark.skipif(not HAS_FFMPEG, reason="needs ffmpeg")
def test_an_uploads_folder_marked_a_compilation(batch):
    mixed(batch / "Mixes" / "Qwerty Mix (2010)")
    mp3(batch / "Mixes" / "Qwerty Mix (2010)" / "CD2" / "01 x.mp3", artist="Zyx Band", album="Elsewhere", title="X")
    saved = [{"path": str(p.relative_to(batch)), "size": p.stat().st_size, "kind": "native"} for p in batch.rglob("*.mp3")]
    with db.session() as s:
        upload.duplicates.remember(s, BATCH, saved)                 # their tags, as an upload keeps them
    c = client()
    got = c.put(f"/api/upload/batch/{BATCH}/compilation", json={"folder": "Mixes/Qwerty Mix (2010)/CD2"}).json()
    assert got["compilations"] == ["Mixes/Qwerty Mix (2010)/CD2"]
    got = c.put(f"/api/upload/batch/{BATCH}/compilation", json={"folder": "Mixes/Qwerty Mix (2010)"}).json()
    assert got["compilations"] == ["Mixes/Qwerty Mix (2010)"]               # the one marked last, not one in it
    assert [(a["artist"], a["album"], a["year"], a["songs"], a["compilation"]) for a in got["albums"]] == [
        ("Various Artists", "Qwerty Mix", 2010, 4, True)]
    assert c.put(f"/api/upload/batch/{BATCH}/compilation", json={"folder": "../etc"}).status_code == 404
    got = c.put(f"/api/upload/batch/{BATCH}/compilation", json={"folder": "Mixes/Qwerty Mix (2010)", "on": False}).json()
    assert got["compilations"] == [] and not importer.own_file(BATCH).exists()
    assert all(not a["compilation"] for a in got["albums"]) and len(got["albums"]) == 4     # by their own albums
    with db.session() as s:
        upload.duplicates.forget(s, BATCH)


@pytest.mark.skipif(not HAS_FFMPEG, reason="needs ffmpeg")
def test_an_upload_files_its_compilations_by_themselves_then_the_rest(batch, monkeypatch):
    mixed(batch / "Qwerty Mix")
    mp3(batch / "Zyx Band - Real Album" / "01.mp3", artist="Zyx Band", album="Real Album", title="One")
    importer.own_file(BATCH).write_text(json.dumps(["Qwerty Mix"]))
    calls = []

    def file_music(ctx, source, batch_, autotag=None, own=False, **k):
        calls.append((Path(source).name, batch_, autotag, own,
                      sorted(mediafile.MediaFile(str(p)).album for p in Path(source).rglob("*.mp3"))))
        for p in list(Path(source).rglob("*.mp3")):
            p.unlink()
        return {"albums": [{"artist": "x", "album": Path(source).name}], "report": "ok", "music_root": "/lib"}
    monkeypatch.setattr(importer, "file_music", file_music)
    monkeypatch.setattr(importer.jobs, "submit", lambda *a, **k: 1)
    got = importer.import_upload(Ctx(), BATCH)
    assert calls == [("Qwerty Mix", f"{BATCH}-own0", False, True, ["Qwerty Mix"] * 3),
                     (BATCH, BATCH, None, False, ["Real Album"])]
    assert [a.get("match") for a in got["albums"]] == ["own", None]
    assert not batch.exists() and not importer.own_file(BATCH).exists()
