import gzip
import struct

from muzix.meta import chip


def pad(s: str, n: int) -> bytes:
    return s.encode().ljust(n, b"\0")


def test_nsf():
    data = b"NESM\x1a\x01" + bytes([12, 1]) + b"\0" * 6 + pad("Mega Man 2", 32) + pad("Takashi Tateishi", 32) + pad("1988 Capcom", 32)
    data = data.ljust(0x80, b"\0")
    i = chip.read_nsf(data)
    assert (i.title, i.artist, i.year, len(i.subsongs)) == ("Mega Man 2", "Takashi Tateishi", 1988, 12)


def test_gbs():
    data = b"GBS\x01" + bytes([5, 1]) + b"\0" * 10 + pad("Tetris", 32) + pad("Hirokazu Tanaka", 32) + pad("1989 Nintendo", 32)
    i = chip.read_gbs(data)
    assert (i.title, i.artist, i.year, len(i.subsongs)) == ("Tetris", "Hirokazu Tanaka", 1989, 5)


def test_sgc():
    data = (b"SGC\x1a\x01" + b"\0" * 0x1F + bytes([0, 9, 0, 0, 1])).ljust(0x40, b"\0")
    data += pad("Home Alone", 32) + pad("<?>", 32) + pad("1992 Sega", 32)
    i = chip.read_sgc(data)
    assert (i.title, i.artist, i.year, i.system, len(i.subsongs)) == ("Home Alone", "", 1992, "Game Gear", 9)


def test_sap_times():
    """TIME gives each song's length: one that ends by itself, or (LOOP) one pass of a looping song."""
    head = ('SAP\r\nAUTHOR "Michael Hedley"\r\nNAME "Mediator"\r\nDATE "1985"\r\nSONGS 3\r\nDEFSONG 1\r\n'
            'TYPE D\r\nINIT AF22\r\nPLAYER 5897\r\nTIME 00:28.88 LOOP\r\nTIME 01:02.50\r\n')
    i = chip.read_sap(head.encode() + b"\xff\xff\x00\x10TIME 9:99")
    assert (i.title, i.artist, i.year, i.system) == ("Mediator", "Michael Hedley", 1985, "Atari 8-bit")
    assert [(s.index, s.duration, s.loop, s.natural) for s in i.subsongs] == [
        (0, 28.88, 28.88, None), (1, 62.5, None, 62.5), (2, None, None, None)]
    assert chip.sap_header(head.encode())["TYPE"] not in chip.SAP_LIBGME   # digitized: ASAP plays it


def test_sid():
    data = b"PSID" + struct.pack(">HHHHHHHI", 2, 0x7C, 0, 0, 0, 3, 1, 0) + pad("Commando", 32) + pad("Rob Hubbard", 32) + pad("1985 Elite", 32)
    data = data.ljust(0x7C, b"\0")
    i = chip.read_sid(data)
    assert (i.title, i.artist, i.year, len(i.subsongs)) == ("Commando", "Rob Hubbard", 1985, 3)


def test_vgm_loop_points():
    gd3_strings = "\0".join(["Green Hill Zone", "", "Sonic the Hedgehog", "", "Sega Mega Drive", "", "Masato Nakamura", "", "1991", "me", ""]) + "\0"
    gd3_body = gd3_strings.encode("utf-16-le")
    header = bytearray(0x40)
    header[0:4] = b"Vgm "
    total, loop = 44100 * 90, 44100 * 60
    struct.pack_into("<IIII", header, 0x14, 0x40 - 0x14, total, 0, loop)
    data = bytes(header) + b"Gd3 " + struct.pack("<II", 0x100, len(gd3_body)) + gd3_body
    for blob in (data, gzip.compress(data)):
        i = chip.read_vgm(blob)
        s = i.subsongs[0]
        assert (i.title, i.album, i.artist, i.system, i.year) == ("Green Hill Zone", "Sonic the Hedgehog", "Masato Nakamura", "Sega Mega Drive", 1991)
        assert (round(s.intro), round(s.loop)) == (30, 60)


def test_ym_loop_frame():
    body = b"YM6!LeOnArD!" + struct.pack(">IIH", 3000, 1, 0) + struct.pack(">IHIH", 2000000, 50, 500, 0)
    body += b"Cuddly\0Jochen Hippel\0ripped\0"
    i = chip.read_ym(body)
    s = i.subsongs[0]
    assert (i.title, i.artist, round(i.duration)) == ("Cuddly", "Jochen Hippel", 60)
    assert (s.intro, s.loop) == (10.0, 50.0)


def test_famitracker_song_list():
    def block(name: bytes, version: int, body: bytes) -> bytes:
        return name.ljust(16, b"\0") + struct.pack("<II", version, len(body)) + body
    info = pad("Spring OST", 32) + pad("Aeitia", 32) + pad("2017", 32)
    header = bytes([1]) + b"Level 1\0Boss\0"
    data = b"FamiTracker Module" + struct.pack("<I", 0x0440) + block(b"INFO", 1, info) + block(b"HEADER", 3, header) + b"END"
    i = chip.read_ftm(data)
    assert (i.title, i.artist, i.year) == ("Spring OST", "Aeitia", 2017)
    assert [s.title for s in i.subsongs] == ["Level 1", "Boss"]


def test_a_sap_copy_names_the_song_asap_should_play(tmp_path):
    from muzix import render
    src = tmp_path / "x.sap"
    src.write_bytes(b"SAP\r\nSONGS 8\r\nDEFSONG 6\r\nTYPE D\r\nTIME 00:28.88 LOOP\r\n\xff\xff\x00\x10DEFSONG 6")
    out = render.sap_song(str(src), 3, str(tmp_path))
    data = open(out, "rb").read()
    assert data == b"SAP\r\nSONGS 8\r\nDEFSONG 3\r\nTYPE D\r\nTIME 00:28.88 LOOP\r\n\xff\xff\x00\x10DEFSONG 6"
    assert chip.sap_header(data)["DEFSONG"] == "3"
