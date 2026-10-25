"""Playlist files: album playlists are skipped; the rest find their songs by path, by the end
of a path from another computer, or by artist and title once the files have been renamed."""
import os
import tempfile
import time

from muzix import db, playlists
from muzix.models import FilePlaylist, FilePlaylistItem, Root, Setting, Track
from sqlalchemy import select


class Ctx:
    """Logs the way a real job does: through a database connection of its own."""
    def log(self, line):
        with db.session() as s:
            s.add(Setting(key=f"test-log-{time.monotonic_ns()}", value=line))


def test_playlist_files_are_read_and_matched():
    d = tempfile.mkdtemp(prefix="muzix-pl-")
    lib = os.path.join(d, "Rock", "Muse", "Muse - 1999 - Showbiz")
    os.makedirs(lib)
    with db.session() as s:
        root = Root(path=d + "/pl-root", kind="music")
        s.add(root)
        s.flush()
        rid = root.id
        songs = {}
        for n, title in enumerate(["Sunburn", "Muscle Museum", "Unintended"], 1):
            p = os.path.join(lib, f"{n}. Muse - Showbiz - {title} (1999).mp3")
            t = Track(root_id=rid, path=p, title=title, artist="Muse", albumartist="Muse", duration=200 + n)
            s.add(t)
            s.flush()
            songs[title] = t.id
    w = lambda name, text, enc="utf-8": open(os.path.join(d, name), "w", encoding=enc).write(text) and os.path.join(d, name)
    album = os.path.join(lib, "00 - showbiz.m3u")
    open(album, "w").write("01 - Sunburn.mp3\n02 - Muscle Museum.mp3\n")
    old = w("Muse old.m3u", "#EXTM3U\n#EXTINF:201,Muse - Sunburn\nD:\\Mp3\\Muse - Showbiz\\01 - Sunburn.mp3\n"
                            "Muse - Showbiz\\muse - showbiz - 03 - unintended.mp3\nhttp://radio.example/stream\n", "cp1252")
    pls = w("mix.pls", f"[playlist]\nFile1={lib}/2. Muse - Showbiz - Muscle Museum (1999).mp3\nNumberOfEntries=1\n")

    found = [(rid, album), (rid, old), (rid, pls)]
    with db.session() as s:
        assert playlists.scan(Ctx(), found, [rid]) == 2
        kept = {p.name: p for p in s.scalars(select(FilePlaylist).where(FilePlaylist.root_id == rid))}
        assert set(kept) == {"Muse old", "mix"}
        items = lambda name: [i.track_id for i in s.scalars(select(FilePlaylistItem).where(
            FilePlaylistItem.playlist_id == kept[name].id).order_by(FilePlaylistItem.position))]
        assert items("Muse old") == [songs["Sunburn"], songs["Unintended"]]
        assert kept["Muse old"].entries == 3
        assert items("mix") == [songs["Muscle Museum"]]

    os.remove(pls)   # a playlist file that's gone disappears on the next scan
    with db.session() as s:
        playlists.scan(Ctx(), [(rid, old)], [rid])
        assert [p.name for p in s.scalars(select(FilePlaylist).where(FilePlaylist.root_id == rid))] == ["Muse old"]


def test_generic_names_take_the_folders_name():
    n = playlists.display_name
    assert n("/m/Other formats/Rush - 1976 - 2112/playlist.m3u") == "Rush - 1976 - 2112"
    assert n("/m/Other formats/The Sugarhill Records Story/_Playlist.m3u") == "The Sugarhill Records Story"
    assert n("/m/The Sugarhill Records Story/Disc 2/_Playlist.m3u") == "The Sugarhill Records Story - Disc 2"
    assert n("/m/x/[PLAYLIST] We Are Reasonable People.m3u") == "We Are Reasonable People"
    assert n("/m/x/[PLAYLIST] - Kid Koala - Carpal Tunnel Syndrome.m3u") == "Kid Koala - Carpal Tunnel Syndrome"
    assert n("/m/Symphony X-[1994]-Dance Macabre-Demo/-=[PLAYLIST]=-.m3u") == "Symphony X-[1994]-Dance Macabre-Demo"
    assert n("/m/x/Playlist for running.m3u") == "Playlist for running"
    assert n("/m/x/soft.m3u") == "soft"
