"""The upload area: what came up shown by album (from the songs' tags, or their folder), and what
the latest imports did with it."""
import os
import wave
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from mutagen.wave import WAVE
from mutagen.id3 import TALB, TDRC, TIT2, TPE1
from sqlalchemy import delete

from muzix import db, env
from muzix.api import upload
from muzix.models import Album, Job, UploadedFile
from muzix.organize import duplicates
from muzix.security import admin_user


def song(path, title, artist="Kraftwerk", album="Computer World", year="1981"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with wave.open(path, "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(8000)
        w.writeframes(b"\0\0" * 800)
    if title:
        f = WAVE(path)
        f.add_tags()
        f.tags.add(TIT2(encoding=3, text=title))
        f.tags.add(TPE1(encoding=3, text=artist))
        f.tags.add(TALB(encoding=3, text=album))
        f.tags.add(TDRC(encoding=3, text=year))
        f.save()


def client():
    a = FastAPI()
    a.include_router(upload.router)
    a.dependency_overrides[admin_user] = lambda: SimpleNamespace(id=1, is_admin=True)
    return TestClient(a)


def test_a_batch_is_shown_by_album():
    batch = "20261107-120000-abcd"
    d = env.UPLOAD_DIR / batch
    with db.session() as s:
        s.execute(delete(UploadedFile).where(UploadedFile.batch == batch))
    saved = []
    for rel, title in (("CW/01.wav", "Numbers"), ("CW/02.wav", "Computer Love"), ("Loose/x.wav", ""),
                       ("CW/cover.jpg", None)):
        if title is None:
            os.makedirs(d / "CW", exist_ok=True)
            (d / rel).write_bytes(b"jpeg")
        else:
            song(str(d / rel), title)
        saved.append({"path": rel, "size": (d / rel).stat().st_size, "kind": upload.formats.family(rel) or "other"})
    with db.session() as s:
        duplicates.remember(s, batch, saved)
    got = next(b for b in client().get("/api/upload/batches").json() if b["batch"] == batch)
    assert [(a["artist"], a["album"], a["year"], a["songs"], a["formats"]) for a in got["albums"]] == [
        ("", "Loose", 0, 1, ["wav"]), ("Kraftwerk", "Computer World", 1981, 2, ["wav"])]
    assert {f["path"] for f in got["files"]} >= {"CW/cover.jpg"}


def test_the_latest_imports_say_where_the_albums_went():
    root = "/music/mp3"
    folder = f"{root}/Electronic/Kraftwerk/Kraftwerk - 1981 - Computer World"
    with db.session() as s:
        s.execute(delete(Job).where(Job.type == "import_upload"))
        al = Album(title="Computer World", artist_name="Kraftwerk", folder=folder, key="cw-test")
        s.add(al)
        s.flush()
        s.add(Job(type="import_upload", title="Import", status="done", params={"batch": "b1"},
                  result={"music": 7, "vgm": 0, "music_root": root, "left": ["CW/cover.jpg"],
                          "albums": [{"artist": "Kraftwerk", "album": "Computer World", "year": 1981, "genre": "Electronic",
                                      "folder": folder, "songs": 7}]}))
        album_id = al.id
    [imp] = client().get("/api/upload/imports").json()
    assert imp["status"] == "done" and imp["left"] == ["CW/cover.jpg"]
    assert imp["albums"][0]["where"] == "Electronic/Kraftwerk/Kraftwerk - 1981 - Computer World"
    assert imp["albums"][0]["album_id"] == album_id
