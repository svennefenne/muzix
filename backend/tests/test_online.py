"""Online archives: reading their folder pages, staying inside them, unpacking game rips safely,
and naming a rip's songs from its NEZplug .m3u."""
import os
import tempfile
import time
import zipfile

import pytest

from muzix import online

APACHE = """<table><tr><th><a href="?C=N;O=D">Name</a></th><th><a href="?C=M;O=A">Last modified</a></th></tr>
<tr><td><a href="/HVSC/C64Music/MUSICIANS/H/">Parent Directory</a></td></tr>
<tr><td><a href="Commando.sid">Commando.sid</a></td><td align="right">2021-12-22 20:06  </td><td align="right"> 12K</td></tr>
<tr><td><a href="Thing%20on%20a%20Spring.sid">Thing on a Spring.sid</a></td><td align="right">2021-12-22 20:06  </td><td align="right">3.5M</td></tr>
<tr><td><a href="Sub%20Folder/">Sub Folder/</a></td><td align="right">2021-12-22 20:06  </td><td align="right">  - </td></tr>
<tr><td><a href="readme.txt">readme.txt</a></td><td align="right">2021-12-22 20:06  </td><td align="right">200</td></tr>
</table>"""

NGINX = """<pre><a href="../">../</a>
<a href="Mega%20Man%202%20%5bRockMan%202%5d%20(1988)(Capcom)%5bNES%5d.7z">Mega Man 2 [RockMan 2] (1988)(Capcom)[NES].7z</a>     2013-07-14 12:00    51234
<a href="https://elsewhere.example/x.mod">elsewhere</a>
<a href="a/">a/</a>                                                  2013-07-14 12:00       -
</pre>"""


def test_folder_pages_are_read():
    got = {n: (folder, size) for n, folder, size in online.parse_index(APACHE)}
    assert got == {"Commando.sid": (False, 12 * 1024), "Thing on a Spring.sid": (False, int(3.5 * 1024 ** 2)),
                   "Sub Folder": (True, 0), "readme.txt": (False, 200)}
    got = {n: (folder, size) for n, folder, size in online.parse_index(NGINX)}
    assert got == {"Mega Man 2 [RockMan 2] (1988)(Capcom)[NES].7z": (False, 51234), "a": (True, 0)}


def test_listing_keeps_what_plays(monkeypatch):
    class Page:
        status_code, text = 200, APACHE
        def raise_for_status(self): pass
    asked = []
    monkeypatch.setattr(online, "_get", lambda url: asked.append(url) or Page())
    src = online.source("hvsc")
    d = online.listing(src, "MUSICIANS/H/Hubbard_Rob")
    assert asked == ["https://hvsc.brona.dk/HVSC/C64Music/MUSICIANS/H/Hubbard_Rob/"]
    assert [f["name"] for f in d["files"]] == ["Commando.sid", "Thing on a Spring.sid"]
    assert d["files"][0] == {"name": "Commando.sid", "path": "MUSICIANS/H/Hubbard_Rob/Commando.sid",
                             "kind": "tune", "size": 12 * 1024, "format": "sid", "chip": True}
    assert d["dirs"] == [{"name": "Sub Folder", "path": "MUSICIANS/H/Hubbard_Rob/Sub Folder"}]
    assert d["other"] == 1
    assert [c["path"] for c in d["crumbs"]] == ["MUSICIANS", "MUSICIANS/H", "MUSICIANS/H/Hubbard_Rob"]
    online.listing(src, "MUSICIANS/H/Hubbard_Rob")
    assert len(asked) == 1          # kept for a while


def test_paths_stay_inside_the_archive():
    for bad in ("../etc/passwd", "a/../../b", "a/./b", "a\\..\\b"):
        with pytest.raises(online.OnlineError):
            online.parts(bad)
    src = online.source("nsf")
    assert online.remote_url(src, ["m", "Mega Man 2 [RM2] (1988)[NES].7z"], False) == \
        "https://nsf.joshw.info/m/Mega%20Man%202%20%5BRM2%5D%20(1988)%5BNES%5D.7z"
    assert online.local_path(src, ["m", "x.7z"]).endswith("online/nsf/m/x.7z")
    with pytest.raises(online.OnlineError):
        online.fetch(src, "m/readme.txt")       # only tunes and archives are downloaded


def test_archives_unpack_only_their_tunes_and_only_inside():
    d = tempfile.mkdtemp(prefix="muzix-online-")
    z = os.path.join(d, "set.zip")
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("../evil.mod", b"x")
        f.writestr("/abs.mod", b"x")
        f.writestr("disk/song.mod", b"x")
        f.writestr("disk/info.txt", b"x")
        f.writestr("game.m3u", b"x")
    out = online.unpack(z)
    found = sorted(os.path.relpath(os.path.join(r, n), out) for r, _, fs in os.walk(out) for n in fs)
    assert found == ["disk/song.mod", "game.m3u"]
    assert not os.path.exists(os.path.join(d, "evil.mod"))


def test_nezplug_playlists_name_and_time_the_songs():
    d = tempfile.mkdtemp(prefix="muzix-online-")
    nsf = os.path.join(d, "game.nsf")
    open(nsf, "wb").write(b"NESM")
    with open(os.path.join(d, "game.m3u"), "w") as f:
        f.write("# made by hand\n"
                "game.nsf::NSF,2,Title,0:41,-,5\n"
                "game.nsf::NSF,$0A,Stage 1\\, part two,1:02:03\n"
                "other.nsf::NSF,1,Not this one,1:00\n"
                "game.nsf::NSF,1,Opening,12\n")
    rows = [{"subsong": i, "title": f"#{i + 1}", "duration": 0, "extra": {"loop": 9}} for i in range(12)]
    got = online._with_playlist(nsf, rows)
    assert [(r["subsong"], r["title"], r["duration"], r["track_no"]) for r in got] == [
        (1, "Title", 41, 1), (10, "Stage 1, part two", 3723, 2), (0, "Opening", 12, 3)]
    assert got[0]["extra"] == {"length": 41, "fade": 5}
    # KSS counts decimal tracks from 0
    kss = os.path.join(d, "msx.m3u")
    open(kss, "w").write("msx.kss::KSS,3,Theme,1:00\n")
    assert online.read_nezplug(kss, "kss")[0][1] == 3
    assert online.read_nezplug(kss, "nsf")[0][1] == 2


def test_the_cache_drops_the_oldest_downloads_first(monkeypatch, tmp_path):
    monkeypatch.setattr(online, "cache_dir", lambda: tmp_path)
    old = tmp_path / "nsf" / "a" / "old.7z"
    new = tmp_path / "nsf" / "a" / "new.7z"
    old.parent.mkdir(parents=True)
    old.write_bytes(b"x" * 600)
    (tmp_path / "nsf" / "a" / "old.7z.d").mkdir()
    (tmp_path / "nsf" / "a" / "old.7z.d" / "old.nsf").write_bytes(b"x" * 600)
    new.write_bytes(b"x" * 600)
    os.utime(old, (time.time() - 100, time.time() - 100))
    assert online.prune(limit=1000) == (1, 1)
    assert not old.exists() and not (tmp_path / "nsf" / "a" / "old.7z.d").exists() and new.exists()
