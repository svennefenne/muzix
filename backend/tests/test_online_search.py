"""Searching and shuffling the online archives: system names pick archives (but "mega" and
"super" stay title words), the published lists become an index, and a game set's random
song stays the same song."""
import json
import tempfile
from pathlib import Path

import pytest

from muzix import env, online, online_index, online_search
from muzix.online_search import parse_query, _archives, _fits

SONGLENGTHS = """[Database]
; /MUSICIANS/H/Hubbard_Rob/Commando.sid
abc=4:04
; /MUSICIANS/H/Hubbard_Rob/Monty_on_the_Run.sid
def=5:50
; /GAMES/A-F/Commando_Arcade.sid
ghi=1:00
"""
ALLMODS = "1000\tTFMX/Chris Huelsbeck/mdat.turrican\n900\tTFMX/Chris Huelsbeck/smpl.turrican\n" \
          "2000\tProtracker/4-Mat/madness.mod\n10\tHVSC/MUSICIANS/H/Hubbard_Rob/x.sid\n5\tAd Lib/x/y.d00\n"
ASMA = json.dumps({"productions": [
    {"title": "Warhawk", "release_date": "1986-06", "author_nicks": [{"name": "Rob Hubbard"}],
     "download_links": [{"url": "https://asma.atari.org/asma/Composers/Hubbard_Rob/Warhawk.sap"}]},
    {"title": "No link", "download_links": [{"url": "https://elsewhere/x.sap"}]}]})


def test_system_names_pick_archives():
    def ids(q):
        text, picked, year = parse_query(q)
        return text, [a.id for a in _archives(None, picked)], year
    assert ids("hubbard c64") == (["hubbard"], ["hvsc"], "")
    assert ids("mega man nes 1988") == (["mega", "man"], ["nsf"], "1988")
    assert ids("tetris game boy") == (["tetris"], ["gbs"], "")
    text, archives, _ = ids("super mario")
    assert text == ["super", "mario"] and len(archives) == len(online.SOURCES)
    assert ids("sonic mega drive")[1] == ["vgmrips"]


def test_results_from_an_archives_own_search_are_checked():
    hit = {"title": "Mega Man 2", "name": "Mega Man 2 (1988-12-24)(Capcom)[NES].7z", "artist": ""}
    assert _fits(hit, ["mega", "man"], "1988")
    assert not _fits(hit, ["mega", "man"], "1990")
    assert not _fits(hit, ["zelda"], "")
    assert _fits({"title": "Dizzy", "year": 1992}, ["diz"], "1992")


@pytest.fixture()
def index(monkeypatch):
    monkeypatch.setattr(env, "CACHE_DIR", Path(tempfile.mkdtemp(prefix="muzix-ix-")))
    lists = {"hvsc": SONGLENGTHS, "modland": ALLMODS, "asma": ASMA}
    monkeypatch.setattr(online_index, "_fetch_list", lambda source: lists[source])
    for source in lists:
        online_index.build(source)


def test_the_published_lists_become_an_index(index):
    files, total = online_index.search("hvsc", ["comm"])
    assert total == 2 and {f["title"] for f in files} == {"Commando", "Commando Arcade"}
    assert files[0]["path"].endswith(".sid") and files[0]["name"] in ("Commando.sid", "Commando_Arcade.sid")
    assert online_index.folders("hvsc", ["hubbard"]) == [{"name": "Rob Hubbard", "path": "MUSICIANS/H/Hubbard_Rob"}]
    files, _ = online_index.search("modland", ["turrican"])
    # the song, not its sample file; Modland's own HVSC copy and formats Muzix doesn't play are left out
    assert [(f["path"], f["title"], f["artist"]) for f in files] == [("TFMX/Chris Huelsbeck/mdat.turrican", "turrican", "Chris Huelsbeck")]
    assert online_index.search("modland", ["hubbard"])[1] == 0
    files, _ = online_index.search("asma", ["warhawk", "1986"])
    assert files == [{"name": "Warhawk.sap", "path": "Composers/Hubbard_Rob/Warhawk.sap", "title": "Warhawk",
                      "artist": "Rob Hubbard", "year": 1986}]
    assert {f["path"] for f in online_index.sample("hvsc", "MUSICIANS/H", 10)} == {
        "MUSICIANS/H/Hubbard_Rob/Commando.sid", "MUSICIANS/H/Hubbard_Rob/Monty_on_the_Run.sid"}
    assert len(online_index.sample("modland", "", 10)) == 2


def test_a_sets_random_song_is_kept(monkeypatch):
    rows = [{"member": f"{i}.vgz", "subsong": -1, "title": f"song {i}"} for i in range(5)]
    monkeypatch.setattr(online, "open_file", lambda src, path: online.Opened("set", rows))
    src = online.source("vgmrips")
    assert online.find(src, "files/x.zip", "*7", -1)["title"] == "song 2"
    assert online.find(src, "files/x.zip", "*7", -1)["title"] == "song 2"
    assert online.find(src, "files/x.zip", "2.vgz", -1)["title"] == "song 2"
