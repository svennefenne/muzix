"""Amiga custom formats through UADE: which files go to it, SidMon's .sid told from the C64's,
the sample files a song needs fetched beside it, and how long a song plays."""
import os
import shutil
import tempfile

import pytest

from muzix import formats, online, settings
from muzix.lengths import play_plan

FOLDER = """<pre><a href="../">../</a>
<a href="mdat.unicorn">mdat.unicorn</a>   2008-07-06 06:21  14K
<a href="smpl.unicorn">smpl.unicorn</a>   2008-07-06 06:21  90K
<a href="mdat.turrican">mdat.turrican</a>   2008-07-06 06:21  20K
<a href="smpl.turrican">smpl.turrican</a>   2008-07-06 06:21  120K
<a href="bob4.ins">bob4.ins</a>   2008-07-06 06:21  30K
<a href="bob4a.dum">bob4a.dum</a>   2008-07-06 06:21  3K
<a href="bob4b.dum">bob4b.dum</a>   2008-07-06 06:21  3K
<a href="readme.txt">readme.txt</a>   2008-07-06 06:21  1K
</pre>"""


def test_which_files_uade_plays():
    for name in ("mdat.unicorn", "5th gear.hip", "amberstar.hip7", "x.bp", "jpn.empiresoccer94", "bob4a.dum",
                 "agravain.dmu", "alfred chicken.dw", "budokan.rh", "action section.aon", "DW.Title"):
        assert formats.family(name) == "uade", name
    for name in ("smpl.unicorn", "smp.empiresoccer94", "bob4.ins", "README.md", "Thumbs.db", "notes.dat"):
        assert formats.family(name) is None, name
    # names other players have keep them
    assert formats.family("x.ahx") == "zxtune" and formats.family("x.mod") == "module" and formats.family("x.ym") == "ym"
    for fam, exts in formats.FAMILIES.items():
        assert fam == "uade" or not exts & formats.UADE, fam
    assert formats.system_for("hip") == "Amiga / PC tracker" and formats.system_for("hst") == "Atari ST"


def test_sidmon_is_told_from_the_c64():
    d = tempfile.mkdtemp(prefix="muzix-uade-")
    c64, sidmon = os.path.join(d, "commando.sid"), os.path.join(d, "scoopex.sid")
    open(c64, "wb").write(b"PSID\x00\x02" + b"\0" * 200)
    open(sidmon, "wb").write(b"\x41\xfa" + b"\0" * 200)
    assert formats.sniff(c64, "sid") == "sid"
    assert formats.sniff(sidmon, "sid") == "sidmon" and formats.family("sidmon") == "uade"


def test_sample_files_come_along(monkeypatch):
    class Page:
        status_code, text = 200, FOLDER
        def raise_for_status(self): pass
    monkeypatch.setattr(online, "_get", lambda url: Page())
    online._listings.clear()
    src = online.source("modland")
    assert online.song_core("mdat.unicorn") == online.song_core("smpl.unicorn") == "unicorn"
    assert online.song_core("bob4a.dum") == "bob4a"
    assert online.companions(src, "TFMX/Chris Huelsbeck/mdat.unicorn") == ["smpl.unicorn"]
    assert online.companions(src, "Infogrames/x/bob4a.dum") == ["bob4.ins"]
    assert online.companions(src, "Hippel/x/5th gear.hip") == []


def test_how_long_a_uade_song_plays():
    settings.set_many({"chip_loop_mode": "time", "chip_length": 180, "chip_fade": 8})
    assert play_plan("uade", {}, 0) == (180, 8)
    assert play_plan("uade", {"natural": 26.9}, 0) == (26.9, 0.0)      # it ended by itself
    settings.set_many({"chip_loop_mode": "loops"})
    assert play_plan("uade", {}, 0) == (180, 8)                          # no loop points to count
    settings.set_many({"chip_loop_mode": "time"})


@pytest.mark.skipif(not shutil.which("uade123"), reason="uade123 isn't installed (it is in the Docker image)")
def test_uade_turns_away_what_it_cannot_play():
    from muzix.meta import chip
    d = tempfile.mkdtemp(prefix="muzix-uade-")
    junk = os.path.join(d, "notes.hip")
    open(junk, "wb").write(b"not a song" * 100)
    with pytest.raises(chip.NotATune):
        chip.read_uade(junk, "hip")
