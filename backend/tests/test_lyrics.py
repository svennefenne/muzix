"""Lyrics: .lrc files beside songs, lyrics in tags, LRCLIB, and .lrc files following their songs."""
import os
import struct
import tempfile

import httpx
from mutagen.flac import FLAC
from mutagen.id3 import ID3, SYLT, USLT

from muzix import db, lyrics, manage, settings
from muzix.models import Album, Artist, Root, Track

LRC = """[ar:Test Band]
[ti:Test Song]
[offset:+500]
[00:12.50]Second line
[00:01.00][00:30.00]Chorus line
[00:05.25]<00:05.25>Word <00:06.00>by <00:06.50>word
"""


def test_lrc_text_becomes_timed_lines():
    synced, lines = lyrics.parse(LRC)
    assert synced
    assert lines == [{"t": 0.5, "text": "Chorus line"}, {"t": 4.75, "text": "Word by word"},
                     {"t": 12.0, "text": "Second line"}, {"t": 29.5, "text": "Chorus line"}]
    synced, lines = lyrics.parse("First line\r\n\r\nSecond line\n\n")
    assert not synced and [line["text"] for line in lines] == ["First line", "", "Second line"]
    assert lyrics.parse("") == (False, [])


def test_placeholders_are_not_lyrics():
    for text in ("Instrumental", "[Instrumental]", "Soundtrack", "(Original Score)", "♪", "[00:01.00]♪\n[00:20.00]",
                 "No lyrics found", "-"):
        got = lyrics._answer("tags", text)
        assert got["lines"] == [] and got["instrumental"] and not got["synced"], text
    assert lyrics._answer("tags", "")["source"] is None
    assert lyrics._answer("tags", "Soundtrack of my life\nSing it")["lines"][0]["text"] == "Soundtrack of my life"


def _mp3(path):
    """A few silent MPEG-1 layer III frames: enough for mutagen to call it an MP3."""
    frame = b"\xff\xfb\x90\x64" + bytes(413)
    with open(path, "wb") as f:
        f.write(frame * 8)


def _flac(path):
    info = struct.pack(">HH", 4096, 4096) + bytes(6) + ((44100 << 44) | (1 << 41) | (15 << 36) | 44100).to_bytes(8, "big") + bytes(16)
    with open(path, "wb") as f:
        f.write(b"fLaC" + bytes([0x80]) + len(info).to_bytes(3, "big") + info)


def test_lyrics_beside_a_song_and_in_its_tags():
    d = tempfile.mkdtemp(prefix="muzix-lyrics-")
    song = os.path.join(d, "1. Song.mp3")
    _mp3(song)
    assert lyrics.sidecar(song) is None
    open(os.path.join(d, "1. song.LRC"), "w", encoding="utf-8-sig").write(LRC)
    assert lyrics.sidecar(song) == os.path.join(d, "1. song.LRC")
    assert lyrics.read_text(lyrics.sidecar(song)).startswith("[ar:")       # the byte order mark is gone

    tags = ID3()
    tags.add(USLT(encoding=3, lang="eng", desc="", text="Plain words\nMore words"))
    tags.save(song)
    assert lyrics.from_tags(song) == "Plain words\nMore words"
    tags.add(SYLT(encoding=3, lang="eng", format=2, type=1, text=[("Timed", 1500), ("Later", 62250)]))
    tags.save(song)
    assert lyrics.parse(lyrics.from_tags(song)) == (True, [{"t": 1.5, "text": "Timed"}, {"t": 62.25, "text": "Later"}])

    flac = os.path.join(d, "2. Song.flac")
    _flac(flac)
    f = FLAC(flac)
    f["LYRICS"] = "[00:02.00]From a FLAC"
    f.save()
    assert lyrics.parse(lyrics.from_tags(flac))[1] == [{"t": 2.0, "text": "From a FLAC"}]


def test_lrclib_is_asked_once(monkeypatch):
    asked = []

    def handle(req: httpx.Request):
        asked.append((req.url.path, dict(req.url.params)))
        if req.url.path.endswith("/get"):
            return httpx.Response(404, json={"code": 404})
        title = req.url.params["track_name"]
        if title == "Unknown Song":
            return httpx.Response(200, json=[])
        return httpx.Response(200, json=[
            {"duration": 300.0, "syncedLyrics": "[00:01.00]Live version", "plainLyrics": "Live version"},
            {"duration": 201.0, "syncedLyrics": None, "plainLyrics": "Plain words"},
            {"duration": 199.0, "syncedLyrics": "[00:01.00]Studio version", "plainLyrics": "Studio version"},
        ])
    monkeypatch.setattr(lyrics, "_client", lambda: httpx.Client(transport=httpx.MockTransport(handle)))
    settings.set_many({"lyrics_online": True})

    d = tempfile.mkdtemp(prefix="muzix-lrclib-")
    with db.session() as s:
        root = Root(path=d, kind="music")
        ar = Artist(name="Lyrics Band")
        s.add_all([root, ar])
        s.flush()
        al = Album(title="Words", artist_name=ar.name, artist_id=ar.id, folder=d, key="lyrics-words")
        s.add(al)
        s.flush()
        known = Track(root_id=root.id, path=os.path.join(d, "1.mp3"), title="Known Song", artist=ar.name,
                      album="Words", album_id=al.id, artist_id=ar.id, duration=200.4)
        unknown = Track(root_id=root.id, path=os.path.join(d, "2.mp3"), title="Unknown Song", artist=ar.name,
                        album="Words", album_id=al.id, artist_id=ar.id, duration=100)
        chip = Track(root_id=root.id, path=os.path.join(d, "3.nsf"), title="Level 1", artist="Composer",
                     kind="vgm", subsong=0, duration=90)
        s.add_all([known, unknown, chip])
        s.flush()
        ids = known.id, unknown.id, chip.id

    def get(i):
        with db.session() as s:
            return lyrics.for_track(s, s.get(Track, i))

    first = get(ids[0])
    assert first["source"] == "lrclib" and first["synced"]
    assert first["lines"] == [{"t": 1.0, "text": "Studio version"}]          # the one as long as the song
    assert asked[0] == ("/api/get", {"artist_name": "Lyrics Band", "track_name": "Known Song",
                                     "album_name": "Words", "duration": "200"})
    assert get(ids[0]) == first and len(asked) == 2                          # kept: not asked again
    nothing = get(ids[1])
    assert nothing["source"] is None and nothing["lines"] == []
    get(ids[1])
    assert len(asked) == 4                                                    # not found is kept too
    assert get(ids[2])["source"] is None and len(asked) == 4                  # game music isn't looked up


def test_lyrics_files_follow_their_songs():
    d = tempfile.mkdtemp(prefix="muzix-carry-")
    up, lib = os.path.join(d, "upload", "Album"), os.path.join(d, "lib", "Album")
    os.makedirs(up)
    os.makedirs(lib)
    for name in ("01 First.mp3", "01 First.lrc", "02 Second.mp3", "Band - Second.lrc", "notes.lrc"):
        open(os.path.join(up, name), "w").write(name)
    moves = {os.path.join(up, "01 First.mp3"): os.path.join(lib, "1. Band - Album - First (2000).mp3"),
             os.path.join(up, "02 Second.mp3"): os.path.join(lib, "2. Band - Album - Second (2000).mp3")}
    titles = {os.path.join(up, "01 First.mp3"): "First", os.path.join(up, "02 Second.mp3"): "Second"}
    assert lyrics.carry(moves, titles) == 2
    assert sorted(os.listdir(lib)) == ["1. Band - Album - First (2000).lrc", "2. Band - Album - Second (2000).lrc"]
    assert sorted(os.listdir(up)) == ["01 First.mp3", "02 Second.mp3", "notes.lrc"]     # no song for this one

    # renaming songs in Muzix (an album edit, its undo) takes their lyrics along
    folder, target = lib, os.path.join(d, "lib", "Album (2001)")
    old = os.path.join(lib, "1. Band - Album - First (2000).mp3")
    open(old, "w").write("song")
    new = os.path.join(target, "1. Band - Album - First (2001).mp3")
    manage._refile(folder, target, {old: new})
    assert sorted(os.listdir(target)) == ["1. Band - Album - First (2001).lrc", "1. Band - Album - First (2001).mp3",
                                          "2. Band - Album - Second (2000).lrc"]
    manage._refile(target, folder, {new: old})
    assert "1. Band - Album - First (2000).lrc" in os.listdir(folder)
