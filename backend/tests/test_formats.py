from muzix import formats


def test_extensions():
    assert formats.ext_of("/a/b/Song.MOD") == "mod"
    assert formats.ext_of("/a/mod.techno") == "mod"          # Amiga style prefix
    assert formats.ext_of("/a/b.c/noext") == ""
    assert formats.family("x.wv") == "decode"
    assert formats.family("x.mt2") == "module"
    assert formats.family("x.nsfe") == "gme"
    assert formats.family("x.ftm") == "furnace"
    assert formats.family("x.flac") == "native"
    assert formats.family("x.txt") is None


def test_requested_formats_are_supported():
    # the formats the project was built for
    for ext in "it mod s3m xm mt2 nsf gbs mid ftm ym vgm spc sid mp3 flac ogg m4a m4b".split():
        assert formats.family(ext) is not None, ext


def test_book_placeholder_tags():
    from muzix.books import real_tag
    assert real_tag("Unknown album (23/09/2012 20:00:01)") == ""
    assert real_tag("Unknown Artist") == ""
    assert real_tag("The Unknown Soldier") == "The Unknown Soldier"
    assert real_tag(None) == ""
