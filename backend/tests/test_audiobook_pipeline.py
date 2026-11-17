"""Audiobooks coming in (audiobook/): what in a folder is one book, one .m4b made of it with chapters and tags,
filed as Genre/Author/Series/Vol N - Year - Title, and read back by the scanner; the sources are stood in for."""
import json
import os
import shutil
import subprocess

import pytest
from mutagen.id3 import ID3, TALB, TIT2, TPE1, TPE2, TRCK
from mutagen.mp4 import MP4
from sqlalchemy import delete, select

from muzix import books, db, jobs
from muzix.audiobook import group, make, pipeline, place, sources
from muzix.models import Book, Root


def tone(path, seconds=3, title="", album="", artist="", albumartist="", track=0, codec="mp3"):
    if not shutil.which("ffmpeg"):
        pytest.skip("needs ffmpeg")       # the CI's runner has none; the image and a dev machine do
    os.makedirs(os.path.dirname(path), exist_ok=True)
    args = ["-c:a", "libmp3lame", "-b:a", "64k"] if codec == "mp3" else ["-c:a", "aac", "-b:a", "64k"]
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", "-ac", "1",
                    *args, path], check=True)
    if codec == "mp3":
        t = ID3()
        for frame, v in ((TIT2, title), (TALB, album), (TPE1, artist), (TPE2, albumartist)):
            if v:
                t.add(frame(encoding=3, text=v))
        if track:
            t.add(TRCK(encoding=3, text=str(track)))
        t.save(path)
    return path


@pytest.fixture
def upload(tmp_path):
    """An upload: a book in three mp3 files with a disc folder, another one file, and a book cut in m4b chapters."""
    u = tmp_path / "up"
    for i in (1, 2):
        tone(str(u / "Leviathan Wakes" / f"{i:02d} Chapter {i}.mp3"), title=f"Chapter {i}", album="Leviathan Wakes",
             artist="James S. A. Corey", track=i)
    tone(str(u / "Leviathan Wakes" / "CD2" / "03 Epilogue.mp3"), title="Epilogue", album="Leviathan Wakes",
         artist="James S. A. Corey", track=3)
    tone(str(u / "Veritas Ferrum.mp3"), seconds=4, album="Veritas Ferrum", artist="David Annandale")
    for i in (1, 2):
        tone(str(u / "Vol 5 - 2024 - Wind and Truth" / f"Wind and Truth - {i:03d}.m4b"), codec="aac")
    return u


def test_what_is_one_book(upload):
    found = {os.path.basename(b.home or b.files[0].path): b for b in group.scan(str(upload))}
    assert sorted(found) == ["Leviathan Wakes", "Veritas Ferrum.mp3", "Vol 5 - 2024 - Wind and Truth"]
    lw = found["Leviathan Wakes"]
    assert len(lw.files) == 3 and lw.guess.title == "Leviathan Wakes" and lw.guess.authors == ["James S. A. Corey"]
    wt = found["Vol 5 - 2024 - Wind and Truth"]
    assert len(wt.files) == 2 and wt.guess.title == "Wind and Truth" and wt.guess.year == "2024"
    assert found["Veritas Ferrum.mp3"].home is None


def test_folder_names_say_what_they_can():
    assert group.from_folder("Vol 2.5 - 2012 - Gods of Risk {Erik Davies}") == \
        {"narrator": "Erik Davies", "vol": "2.5", "year": "2012", "title": "Gods of Risk"}
    assert group.from_folder("2011 - The Martian") == {"year": "2011", "title": "The Martian"}
    assert group.from_folder("Book 08 - Guards Guards") == {"vol": "08", "title": "Guards Guards"}


def found(title, author, **kw):
    return sources.Found(title=title, authors=[author], narrators=kw.pop("narrators", ["A Reader"]), **kw)


def test_one_m4b_with_a_chapter_a_file_and_the_tags(upload, tmp_path):
    lw = next(b for b in group.scan(str(upload)) if b.home and b.home.endswith("Leviathan Wakes"))
    f = found("Leviathan Wakes", "James S.A. Corey", series="The Expanse", vol="1", year="2011", language="english",
              description="<p>Two ships.</p>")
    out = make.make([p.path for p in lw.files], f, "Science Fiction", "en", str(tmp_path / "book"), home=lw.home)
    assert out["chapters"] == 3 and not out["copied"] and abs(out["seconds"] - 9) < 0.5
    t = MP4(out["file"]).tags
    assert t["\xa9nam"] == ["Leviathan Wakes"] and t["aART"] == ["James S.A. Corey"] and t["\xa9wrt"] == ["A Reader"]
    assert bytes(t["----:com.apple.iTunes:SERIES"][0]) == b"The Expanse" and bytes(t["----:com.apple.iTunes:LANGUAGE"][0]) == b"en"
    meta = json.load(open(tmp_path / "book" / "metadata.json"))
    assert [c["title"] for c in meta["chapters"]] == ["Chapter 1", "Chapter 2", "Epilogue"]
    assert meta["series"] == ["The Expanse #1"] and meta["description"] == "Two ships."
    assert os.path.exists(lw.files[0].path)          # make() leaves the originals; the pipeline deletes them


def test_aac_files_are_joined_as_they_are(upload, tmp_path):
    wt = next(b for b in group.scan(str(upload)) if b.home and "Wind" in b.home)
    out = make.make([p.path for p in wt.files], found("Wind and Truth", "Brandon Sanderson"), "Fantasy", "en",
                    str(tmp_path / "wt"))
    assert out["copied"] and out["chapters"] == 2


def test_audibles_chapters_for_a_book_whose_own_say_nothing(upload, tmp_path):
    vf = next(b for b in group.scan(str(upload)) if not b.home)
    f = found("Veritas Ferrum", "David Annandale",
              chapters={"runtime": 4, "chapters": [{"start": 0, "title": "Opening"}, {"start": 2, "title": "The Iron"}]})
    make.make([p.path for p in vf.files], f, "Warhammer", "en", str(tmp_path / "vf"))
    meta = json.load(open(tmp_path / "vf" / "metadata.json"))
    assert [c["title"] for c in meta["chapters"]] == ["Opening", "The Iron"]


def test_where_a_book_goes(tmp_path):
    f = found("Wind and Truth", "Brandon Sanderson", series="The Stormlight Archive", vol="5", year="2024")
    assert place.target(str(tmp_path), f, "Fantasy") == \
        str(tmp_path / "Fantasy" / "Brandon Sanderson" / "The Stormlight Archive" / "Vol 5 - 2024 - Wind and Truth")
    (tmp_path / "Fantasy" / "Brandon Sanderson" / "The Stormlight Archive" / "Vol 5 - 2024 - Wind and Truth").mkdir(parents=True)
    f2 = found("Wind and Truth", "Brandon Sanderson", series="The Stormlight Archive", vol="5", year="2024",
               narrators=["Kate Reading"])
    assert place.target(str(tmp_path), f2, "Fantasy").endswith("Vol 5 - 2024 - Wind and Truth {Kate Reading}")
    assert place.target(str(tmp_path), found("The Martian", "Andy Weir", year="2011"), "Science Fiction") == \
        str(tmp_path / "Science Fiction" / "Andy Weir" / "2011 - The Martian")


def test_genres_and_languages():
    assert place.genre_of(found("x", "y", categories=[["Science Fiction & Fantasy", "Fantasy", "Epic"]])) == "Fantasy"
    assert place.genre_of(found("x", "y", categories=[["Mystery, Thriller & Suspense", "Thriller & Suspense"]])) == "Thriller & Crime"
    assert place.genre_of(found("x", "y", categories=[["Biographies & Memoirs", "Memoirs"]])) == "Biography"
    assert place.genre_of(found("x", "y", warhammer=True)) == "Warhammer"
    assert place.genre_of(found("x", "y")) == "Uncategorized"
    assert place.language_code("english") == "en" and place.language_code("Svenska") == "sv" and place.language_code("") == ""


@pytest.fixture
def library(tmp_path):
    root = tmp_path / "Audiobooks"
    root.mkdir()
    with db.session() as s:
        s.execute(delete(Book))
        s.execute(delete(Root).where(Root.kind == "audiobooks"))
        s.add(Root(path=str(root), kind="audiobooks", name="Audiobooks", upload_target=True))
    yield root
    with db.session() as s:
        s.execute(delete(Book))
        s.execute(delete(Root).where(Root.kind == "audiobooks"))


class Ctx:
    def __init__(self):
        self.lines = []

    def log(self, line):
        self.lines.append(line)

    def update(self, *a, **k):
        pass

    def check(self):
        pass


def test_an_upload_filed_and_scanned(upload, library, monkeypatch):
    known = {"Leviathan Wakes": found("Leviathan Wakes", "James S.A. Corey", series="The Expanse", vol="1", year="2011",
                                      language="english", categories=[["Science Fiction & Fantasy", "Science Fiction"]],
                                      sources=["audible"], sure=True),
             "Veritas Ferrum": found("Veritas Ferrum", "David Annandale", series="The Horus Heresy", year="2012",
                                     warhammer=True, sources=["wiki"], sure=True)}
    monkeypatch.setattr(sources, "identify", lambda g: known.get(g.title) or found(g.title, "Brandon Sanderson",
                                                                                     year=g.year, sources=[], sure=False))
    monkeypatch.setattr(jobs, "submit", lambda *a, **k: 0)
    out = pipeline.file_books(Ctx(), upload, "a test")
    assert not out["failed"] and len(out["books"]) == 3
    assert sorted(b["folder"] for b in out["books"]) == [
        "Science Fiction/James S.A. Corey/The Expanse/Vol 1 - 2011 - Leviathan Wakes",
        "Uncategorized/Brandon Sanderson/2024 - Wind and Truth",
        "Warhammer/David Annandale/The Horus Heresy/2012 - Veritas Ferrum"]
    assert not any(f for _, _, fs in os.walk(upload) for f in fs)          # the originals went once filed

    books.scan_books(Ctx())
    with db.session() as s:
        got = {b.title: b for b in s.scalars(select(Book))}
        lw = got["Leviathan Wakes"]
        assert (lw.author, lw.series, lw.series_part, lw.genre, lw.language, lw.year, lw.review) == \
            ("James S.A. Corey", "The Expanse", "1", "Science Fiction", "en", 2011, False)
        assert len(lw.chapters) == 3
        assert got["Wind and Truth"].review is True          # no source knew it: the admin looks


def test_a_book_the_library_has_goes_to_duplicates(upload, library, monkeypatch):
    with db.session() as s:
        s.add(Book(root_id=s.scalar(select(Root.id).where(Root.kind == "audiobooks")), path="/x/Veritas Ferrum.m4b",
                   title="Veritas Ferrum", author="David Annandale", narrator="A Reader", duration=4))
    monkeypatch.setattr(sources, "identify", lambda g: found(g.title, "David Annandale", sources=["wiki"], sure=True))
    monkeypatch.setattr(jobs, "submit", lambda *a, **k: 0)
    out = pipeline.file_books(Ctx(), upload, "a test")
    vf = next(b for b in out["books"] if b["title"] == "Veritas Ferrum")
    assert vf["folder"].startswith("_Duplicates/") and vf["duplicate_of"]


# ---------------------------------------------------------------- the admin's side, and the Audiobooks page's

@pytest.fixture
def api():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from muzix.api import bookadmin, books as books_api
    from muzix.models import AuthSession, User
    from muzix.security import hash_password
    with db.session() as s:
        s.execute(delete(User).where(User.username == "book-admin"))
        u = User(username="book-admin", password_hash=hash_password("secret1"), is_admin=True)
        s.add(u)
        s.flush()
        s.add(AuthSession(token="book-admin-token", user_id=u.id))
    app = FastAPI()
    app.include_router(bookadmin.router)
    app.include_router(books_api.router)
    yield TestClient(app, headers={"authorization": "Bearer book-admin-token"})
    with db.session() as s:
        s.execute(delete(User).where(User.username == "book-admin"))


def test_needs_a_look_picked_and_filed(upload, library, monkeypatch, api):
    known = {"Leviathan Wakes": found("Leviathan Wakes", "James S.A. Corey", series="The Expanse", vol="1", year="2011",
                                      language="english", categories=[["Science Fiction & Fantasy", "Science Fiction"]],
                                      sources=["audible"], sure=True)}
    monkeypatch.setattr(sources, "identify", lambda g: known.get(g.title) or found(g.title, "Nobody", year=g.year, sources=[], sure=False))
    monkeypatch.setattr(jobs, "submit", lambda *a, **k: 0)
    pipeline.file_books(Ctx(), upload, "a test")
    books.scan_books(Ctx())

    facets = api.get("/api/books/facets").json()
    assert {g["name"]: g["count"] for g in facets["genres"]} == {"Science Fiction": 1, "Uncategorized": 2}
    assert [b["title"] for b in api.get("/api/books", params={"genre": "Science Fiction"}).json()["items"]] == ["Leviathan Wakes"]
    assert api.get("/api/books", params={"language": "en"}).json()["total"] == 1

    review = api.get("/api/admin/books/review").json()
    wt = next(b for b in review if b["title"] == "Wind and Truth")
    assert "Leviathan Wakes" not in [b["title"] for b in review]
    monkeypatch.setattr(sources, "audible_get", lambda asin: {"asin": asin, "title": "Wind and Truth", "authors": ["Brandon Sanderson"]})
    monkeypatch.setattr(sources, "identify", lambda g: found("Wind and Truth", "Brandon Sanderson", series="The Stormlight Archive",
                                                            vol="5", year="2024", language="english", asin=g.asin,
                                                            categories=[["Science Fiction & Fantasy", "Fantasy", "Epic"]],
                                                            sources=["audible"], sure=True))
    got = api.post(f"/api/admin/books/{wt['id']}/match", json={"asin": "B0TEST"}).json()
    want = library / "Fantasy" / "Brandon Sanderson" / "The Stormlight Archive" / "Vol 5 - 2024 - Wind and Truth" / "Wind and Truth.m4b"
    assert got["path"] == str(want) and want.is_file()                 # renamed as it's called now, and moved there
    assert MP4(str(want)).tags["\xa9gen"] == ["Fantasy"]
    assert not (library / "Uncategorized" / "Nobody" / "2024 - Wind and Truth").exists()
    assert "Wind and Truth" not in [b["title"] for b in api.get("/api/admin/books/review").json()]
    with db.session() as s:
        b = s.get(Book, wt["id"])
        assert (b.series, b.series_part, b.genre, b.review) == ("The Stormlight Archive", "5", "Fantasy", False)

    vf = next(b for b in api.get("/api/admin/books/review").json() if b["title"] == "Veritas Ferrum")
    assert api.post(f"/api/admin/books/{vf['id']}/ok").json() == {"ok": True}
    assert api.get("/api/admin/books/review").json() == []


def test_a_series_across_its_authors(library, api):
    with db.session() as s:
        root = s.scalar(select(Root.id).where(Root.kind == "audiobooks"))
        for part, title, author in (("1", "Horus Rising", "Dan Abnett"), ("2", "False Gods", "Graham McNeill"),
                                    ("3", "Galaxy in Flames", "Ben Counter")):
            s.add(Book(root_id=root, path=f"/x/{title}.m4b", title=title, author=author, series="The Horus Heresy",
                       series_part=part, genre="Warhammer", language="en", duration=3600))
    items = api.get("/api/books", params={"series": "The Horus Heresy"}).json()["items"]
    assert [b["series_part"] for b in items] == ["1", "2", "3"]
    detail = api.get(f"/api/books/{items[1]['id']}").json()
    assert [b["title"] for b in detail["in_series"]] == ["Horus Rising", "False Gods", "Galaxy in Flames"]
    assert detail["next"]["title"] == "Galaxy in Flames"


def test_duplicates_kept_or_thrown_away(upload, library, monkeypatch, api):
    with db.session() as s:
        s.add(Book(root_id=s.scalar(select(Root.id).where(Root.kind == "audiobooks")), path="/x/Veritas Ferrum.m4b",
                   title="Veritas Ferrum", author="David Annandale", narrator="A Reader", duration=4))
    monkeypatch.setattr(sources, "identify", lambda g: found(g.title, "David Annandale", year="2012", sources=["wiki"], sure=True,
                                                            warhammer=True))
    monkeypatch.setattr(jobs, "submit", lambda *a, **k: 0)
    pipeline.file_books(Ctx(), upload, "a test")
    dupes = api.get("/api/admin/books/duplicates").json()
    assert [d["title"] for d in dupes] == ["Veritas Ferrum"] and dupes[0]["library"]["title"] == "Veritas Ferrum"
    kept = api.post("/api/admin/books/duplicates", json={"name": dupes[0]["name"], "how": "keep"}).json()
    assert kept["folder"] == "Warhammer/David Annandale/2012 - Veritas Ferrum"
    assert (library / kept["folder"] / "Veritas Ferrum.m4b").is_file()
    assert api.get("/api/admin/books/duplicates").json() == []


def test_a_length_that_wrapped_is_read_from_the_frames():
    # Disquiet Gods: 31.6 h at 44.1 kHz is more than 2³² samples, and its header said 4.6 h
    a = {"codec_name": "aac", "sample_rate": "44100", "nb_frames": "4906220"}
    assert round(make.length({"format": {"duration": "16530.657234"}}, a)) == 113922
    assert make.length({"format": {"duration": "113922.2"}}, a) == 113922.2      # read right: left as it is
    assert make.length({"format": {"duration": "3600"}}, {**a, "nb_frames": "100000"}) == 3600   # not a wrap
