"""Muzix Desktop without a window: the catalog a server mirrors, linking only over HTTPS, and Fix
Metadata & Artwork writing an album's tags, renaming or filing it, and undoing that."""
import os
import shutil
import subprocess

import pytest

from muzix_desktop import catalog, config, fixer, sharing
from muzix_desktop.shared import tags

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg to make songs")


@pytest.fixture(autouse=True)
def fresh_config(monkeypatch):
    c = config.Config()
    monkeypatch.setattr(config, "_current", c)
    monkeypatch.setattr(config, "save", lambda: None)
    return c


def song(path, title, n, seconds, artist="kraftwerk", album="computer world"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", f"sine=frequency={300 + n * 50}:duration={seconds}",
                    "-metadata", f"title={title}", "-metadata", f"artist={artist}", "-metadata", f"album={album}",
                    "-metadata", f"track={n}", path], check=True)


@pytest.fixture
def album(tmp_path):
    folder = tmp_path / "music" / "Kraftwerk - Computer World"
    for n, seconds in ((1, 3), (2, 5), (3, 4)):
        song(str(folder / f"0{n} track{n}.mp3"), f"track{n}", n, seconds)
    return folder


THEIRS = {"title": "Computer World", "artist": "Kraftwerk", "year": 1981, "genre": "Electronic", "source": "test",
          "tracks": [{"disc": 1, "no": 1, "title": "Computer World", "length": 3},
                     {"disc": 1, "no": 2, "title": "Pocket Calculator", "length": 5},
                     {"disc": 1, "no": 3, "title": "Numbers", "length": 4}]}


def test_the_catalog_is_what_a_server_mirrors(album, tmp_path):
    cat = catalog.Catalog(str(tmp_path / "index.db"))
    assert cat.scan([(str(tmp_path / "music"), "music")])
    assert cat.counts() == {"albums": 1, "tracks": 3}
    page = cat.page("tracks", 0, 2)
    assert page["fields"] == catalog.FIELDS["tracks"] and len(page["rows"]) == 2 and page["next"] == page["rows"][-1][0]
    rows = page["rows"] + cat.page("tracks", page["next"], 2)["rows"]
    tracks = [dict(zip(catalog.FIELDS["tracks"], r)) for r in rows]
    assert {t["title"] for t in tracks} == {"track1", "track2", "track3"}
    assert len({t["album_id"] for t in tracks}) == 1 and tracks[0]["artist_ref"] == "kraftwerk"
    al = dict(zip(catalog.FIELDS["albums"], cat.page("albums")["rows"][0]))
    assert al["title"] == "computer world" and al["art"] == 0
    # only shared songs are ever read for a server
    one = next(t for t in tracks if t["title"] == "track1")
    assert cat.path_of(one["id"]) == str(album / "01 track1.mp3")
    assert cat.path_of(99999) is None
    # unchanged files aren't read again, and ids stay
    assert not cat.scan([(str(tmp_path / "music"), "music")])
    assert [r[0] for r in cat.page("tracks")["rows"]] == [t["id"] for t in tracks]
    # a folder no longer shared: its songs leave the catalog
    assert cat.scan([])
    assert cat.counts() == {"albums": 0, "tracks": 0} and cat.path_of(one["id"]) is None


def test_servers_are_reached_over_https_only(monkeypatch):
    monkeypatch.delenv("MUZIX_DESKTOP_INSECURE", raising=False)
    assert sharing.clean_address("muzix.example.com/") == "https://muzix.example.com"
    with pytest.raises(sharing.LinkError, match="HTTPS"):
        sharing.clean_address("http://muzix.example.com")
    with pytest.raises(sharing.LinkError, match="HTTPS"):
        sharing.clean_address("http://127.0.0.1:8080")
    monkeypatch.setenv("MUZIX_DESKTOP_INSECURE", "1")
    assert sharing.clean_address("http://127.0.0.1:8080") == "http://127.0.0.1:8080"
    with pytest.raises(sharing.LinkError):
        sharing.clean_address("http://muzix.example.com")     # only this computer, for tests


def test_songs_pair_by_length_then_by_order():
    songs = [fixer.Song(path=f"/a/{n}.mp3", track_no=n, duration=d) for n, d in ((1, 200), (2, 61), (3, 300))]
    theirs = [{"no": 1, "title": "A", "length": 60}, {"no": 2, "title": "B", "length": 199}, {"no": 3, "title": "C", "length": 0}]
    got = {s.path: t["title"] for s, t in fixer.pair(songs, theirs)}
    assert got == {"/a/1.mp3": "B", "/a/2.mp3": "A", "/a/3.mp3": "C"}
    assert all(t is None for _, t in fixer.pair(songs, theirs[:1]) if _.track_no != 2)


def _state(folder):
    out = {}
    for d, _, names in os.walk(folder):
        for n in names:
            p = os.path.join(d, n)
            if p.endswith(".mp3"):
                t = tags.read(p)
                out[os.path.relpath(p, folder)] = (t.title, t.artist, t.albumartist, t.album, t.track_no, t.year)
            else:
                out[os.path.relpath(p, folder)] = None
    return out


@pytest.mark.parametrize("mode", ["tags", "rename", "library"])
def test_an_album_is_fixed_and_put_back(album, tmp_path, fresh_config, mode):
    fresh_config.organize, fresh_config.library = mode, str(tmp_path / "library")
    os.makedirs(fresh_config.library)
    before = _state(tmp_path)
    [a] = fixer.albums_from([str(album)])
    assert a.title == "computer world" and a.whole_folder and len(a.songs) == 3
    done = fixer.apply(a, THEIRS, fixer.pair(a.songs, THEIRS["tracks"]), b"\xff\xd8fake-jpeg")
    after = _state(tmp_path)
    if mode == "tags":
        assert done.target == str(album)
        assert after["music/Kraftwerk - Computer World/02 track2.mp3"] == \
            ("Pocket Calculator", "Kraftwerk", "Kraftwerk", "Computer World", 2, 1981)
        assert "music/Kraftwerk - Computer World/cover.jpg" in after
    elif mode == "rename":
        assert done.target == str(tmp_path / "music" / "Kraftwerk - 1981 - Computer World")
        assert "music/Kraftwerk - 1981 - Computer World/2. Kraftwerk - Computer World - Pocket Calculator (1981).mp3" in after
    else:
        assert done.target == str(tmp_path / "library" / "Electronic" / "Kraftwerk" / "Kraftwerk - 1981 - Computer World")
        assert not os.path.exists(album)
        assert "library/Electronic/Kraftwerk/Kraftwerk - 1981 - Computer World/1. Kraftwerk - Computer World - " \
               "Computer World (1981).mp3" in after
    fixer.undo(done)
    assert _state(tmp_path) == before


def test_a_folder_with_other_music_keeps_its_name(album, fresh_config):
    fresh_config.organize = "rename"
    song(str(album / "other.mp3"), "other", 9, 2, album="something else")
    a = next(x for x in fixer.albums_from([str(album / f"0{n} track{n}.mp3") for n in (1, 2, 3)]))
    assert not a.whole_folder
    done = fixer.apply(a, THEIRS, fixer.pair(a.songs, THEIRS["tracks"]), None)
    assert done.target == str(album) and os.path.exists(album / "other.mp3")
    assert os.path.exists(album / "3. Kraftwerk - Computer World - Numbers (1981).mp3")
    fixer.undo(done)
    assert os.path.exists(album / "03 track3.mp3")
