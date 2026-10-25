"""ZX Spectrum tunes: the formats zxtune123 plays, ZXArt as an online archive, and fixing the WAV
header of a render that had to be stopped."""
import os
import shutil
import struct
import tempfile
import wave

import pytest

from muzix import formats, online, render, settings, zxart
from muzix.lengths import play_plan

AUTHORS = """<?xml version="1.0" encoding="UTF-8"?><response><responseStatus>success</responseStatus><responseData>
<totalAmount>2</totalAmount><authors>
<author><id>19720</id><title>nq</title><tunesQuantity>40</tunesQuantity><realName>Ivan Roshin</realName></author>
<author><id>7744</id><title>MmcM</title><tunesQuantity>99</tunesQuantity></author>
</authors></responseData></response>"""

TOP = """<?xml version="1.0" encoding="UTF-8"?><response><responseStatus>success</responseStatus><responseData>
<totalAmount>29564</totalAmount><tunes>
<tune><id>74340</id><title>AsSuRed</title><originalFileName><![CDATA[MmcM - AsSuRed (2000).pt3]]></originalFileName>
<year>2000</year><time>3:46.65</time><authors><id>7744</id></authors></tune>
<tune><id>60891</id><title>synchronization</title><originalFileName><![CDATA[nq - synchronization (2015).pt3]]></originalFileName>
<year>2015</year><time>8:33.80</time><authors><id>19720</id></authors></tune>
<tune><id>193641</id><title>SPAZM</title><originalFileName><![CDATA[Demon - SPAZM (1996).$m]]></originalFileName>
<year>1996</year><time>4:13.95</time><authors><id>1</id></authors></tune>
<tune><id>552316</id><title>Duran</title><originalFileName><![CDATA[Jammer - Duran (2025).aks]]></originalFileName></tune>
</tunes></responseData></response>"""


def test_zx_formats():
    for name in ("song.pt3", "song.stc", "song.asc", "song.tfc", "song.sqt", "SONG.PT2", "x.$m.zx"):
        assert formats.family(name) == "zxtune", name
    assert formats.system_for("pt3") == "ZX Spectrum"
    assert formats.family("song.ay") == "gme"              # libgme keeps .ay
    assert "zxtune" in formats.RENDERED
    # like tracker modules: once through, unless the repeat count says more
    settings.set_many({"module_repeats": 1})
    assert play_plan("zxtune", {"natural": 100.0}, 100.0) == (100.0, 0.0)
    settings.set_many({"module_repeats": 2, "chip_fade": 8})
    assert play_plan("zxtune", {"natural": 100.0}, 100.0) == (208.0, 8.0)
    settings.set_many({"module_repeats": 1})


def test_file_names_fill_in_for_silent_tunes():
    from muzix.meta.chip import ZX_NAME
    m = ZX_NAME.match("Ziutek - Beat to the pulp (2015) (RetroKomp-Load Error 2015, 1)")
    assert (m["artist"], m["title"], m["year"]) == ("Ziutek", "Beat to the pulp", "2015")
    m = ZX_NAME.match("X-agon - Warhawk-Atari800(Rob-Hubbard)")
    assert (m["artist"], m["title"], m["year"]) == ("X-agon", "Warhawk-Atari800(Rob-Hubbard)", None)
    assert ZX_NAME.match("ICECLIM6") is None


def test_amiga_formats():
    for name in ("aces high.ahx", "hexplosion.hvl", "c-pack.smod", "znt01.fc", "amos.gmc", "beast.ims",
                 "whittaker.emod", "sunset.667", "cannonfodder.tcb", "battleship.fnk", "background.liq",
                 "banjo man.v2m", "AHX.Song", "FC14.tune"):
        assert formats.family(name) == "zxtune", name
    assert formats.system_for("ahx") == "Amiga / PC tracker" and formats.system_for("tcb") == "Atari ST"
    assert formats.ext_of("FTM.A_WALK_IN_THE_DARK") == "ftm"
    d = tempfile.mkdtemp(prefix="muzix-amiga-")
    face, fami, kris, mod = (os.path.join(d, n) for n in ("FTM.ROCK", "song.ftm", "title.mod", "plain.mod"))
    open(face, "wb").write(b"FTMN\x03\x10" + b"\0" * 100)
    open(fami, "wb").write(b"FamiTracker Module" + b"\0" * 100)
    open(kris, "wb").write(b"\0" * 952 + b"KRIS" + b"\0" * 100)
    open(mod, "wb").write(b"\0" * 1080 + b"M.K.")
    assert formats.sniff(face, formats.ext_of(face)) == "ftmn" and formats.family("ftmn") == "zxtune"
    assert formats.sniff(fami, "ftm") == "ftm" and formats.family("ftm") == "furnace"
    assert formats.sniff(kris, "mod") == "kris" and formats.family("kris") == "zxtune"
    assert formats.sniff(mod, "mod") == "mod"


def test_zxart_names_its_files_so_they_play():
    assert zxart.file_name("1", "nq - synchronization (2015).pt3", "") == "nq - synchronization (2015).pt3"
    assert zxart.file_name("1", "Demon - SPAZM (1996).$m", "") == "Demon - SPAZM (1996).$m.zx"
    assert zxart.file_name("1", "Ending.c", "") == "Ending.c.zx"
    assert zxart.file_name("1", "a/b?: c.pt3", "") == "a_b__ c.pt3"
    assert zxart.file_name("1", "Jammer - Duran.aks", "") == "Jammer - Duran.aks"   # not playable: stays hidden
    assert zxart.file_name("7", "", "") == "7.zx"


def test_zxart_folders(monkeypatch):
    pages = {"action:authors": AUTHORS, "action:topTunes": TOP}

    class Page:
        status_code = 200
        def __init__(self, text): self.text = text
        def raise_for_status(self): pass
    asked = []

    def get(url):
        asked.append(url)
        return Page(next(v for k, v in pages.items() if k in url))
    monkeypatch.setattr(online, "_get", get)
    online._listings.clear()
    src = online.source("zxart")
    root = online.listing(src, "")
    assert [d["path"] for d in root["dirs"]] == ["authors", "parties", "top"]
    top = online.listing(src, "top")
    assert top["crumbs"] == [{"name": "Top tunes", "path": "top"}]
    # the top list keeps its order; the .aks isn't something Muzix plays
    assert [f["title"] for f in top["files"]] == ["AsSuRed", "synchronization", "SPAZM"]
    assert top["other"] == 1
    first = top["files"][0]
    assert first["artist"] == "MmcM" and first["year"] == 2000 and abs(first["duration"] - 226.65) < 0.01
    assert first["path"] == "tune/74340/MmcM - AsSuRed (2000).pt3" and first["chip"] and first["format"] == "pt3"
    assert top["files"][2]["path"].endswith(".$m.zx")
    authors = online.listing(src, "authors")
    assert [d["name"] for d in authors["dirs"]] == ["MmcM", "nq (Ivan Roshin)"]
    assert zxart.folder_names["authors/19720"] == "nq"
    assert zxart.file_url(["tune", "74340", "x.pt3"]) == "https://zxart.ee/file/id:74340"
    assert zxart.api_url(["authors", "19720"]).endswith("action:tunes/authorId:19720")
    assert zxart.api_url(["authors", "../x"]) is None
    # opened tunes take ZXArt's names, not the file's decorated ones
    row = {"title": "BeYoNd TiMe ... h! f4nz!", "artist": "MmcM^Sa9e 070820131313", "album": "x", "year": 0}
    zxart.label(["tune", "74340", "x.pt3"], row)
    assert (row["title"], row["artist"], row["year"]) == ("AsSuRed", "MmcM", 2000)


def test_a_stopped_render_gets_a_proper_wav_header():
    d = tempfile.mkdtemp(prefix="muzix-zx-")
    wav = os.path.join(d, "x.wav")
    header = (b"RIFF" + struct.pack("<I", 36) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 2, 44100, 176400, 4, 16)
              + b"data" + struct.pack("<I", 0))
    open(wav, "wb").write(header + b"\x01\x00" * 2 * 44100 + b"\x07\x07\x07")   # a second, and a torn frame
    render.fix_wav_header(wav)
    with wave.open(wav) as w:
        assert (w.getframerate(), w.getnchannels(), w.getnframes()) == (44100, 2, 44100)


ZX_TOOL = shutil.which("zxtune123")


@pytest.mark.skipif(not ZX_TOOL, reason="zxtune123 isn't installed (it is in the Docker image)")
def test_zxtune_renders_and_measures():
    from muzix.meta import chip
    d = tempfile.mkdtemp(prefix="muzix-zx-")
    junk = os.path.join(d, "clip.ts")
    open(junk, "wb").write(b"\x47" * 4096)
    with pytest.raises(chip.NotATune):
        chip.read_zxtune(junk, "ts")
