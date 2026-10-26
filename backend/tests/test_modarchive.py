"""The Mod Archive through its XML API: nothing without a key of one's own, folders from its
genres and artists, modules a page at a time, and the key kept out of the log."""
import logging

import pytest

from muzix import modarchive, online, settings

GENRES = """<?xml version="1.0" encoding="UTF-8"?><modarchive><parent><id>1</id><text>Electronic</text><children>
<child><id>2</id><text>Electronic - Ambient</text><files>2843</files></child>
<child><id>6</id><text>Electronic - Dance</text><files>4120</files></child>
<child><id>99</id><text>Empty</text><files>0</files></child>
</children></parent></modarchive>"""

MODULES = """<?xml version="1.0" encoding="UTF-8"?><modarchive><results>812</results><totalpages>3</totalpages>
<module><id>182782</id><filename>4mat_-_broken_heart.xm</filename><format>XM</format><bytes>61760</bytes>
<songtitle><![CDATA[&lt;3 broken heart &lt;3]]></songtitle><genretext>Chiptune</genretext>
<artist_info><artists>1</artists><artist><id>69171</id><alias>4-Mat</alias></artist></artist_info></module>
<module><id>140500</id><filename>egg_plant.xm</filename><bytes>530975</bytes><songtitle>&lt;&lt; EGG PLANT &gt;&gt;</songtitle>
<artist_info><artists>0</artists><guessed_artist><alias>Elwood</alias></guessed_artist></artist_info></module>
</modarchive>"""

BAD_KEY = """<?xml version="1.0" encoding="UTF-8"?><modarchive><error>Invalid Key</error></modarchive>"""


class Page:
    status_code = 200
    def __init__(self, text): self.text = text
    def raise_for_status(self): pass


def test_nothing_without_a_key(monkeypatch):
    settings.set_many({"modarchive_api_key": ""})
    monkeypatch.setattr(online, "_get", lambda url: pytest.fail("asked the API without a key"))
    src = online.source("modarchive")
    assert "API key" in online.about(src)
    assert [d["path"] for d in online.listing(src, "")["dirs"]] == ["letters", "genres", "ratings", "artists"]
    assert len(online.listing(src, "letters")["dirs"]) == 26           # these need no API
    with pytest.raises(online.OnlineError, match="API key"):
        online.listing(src, "letters/A")


def test_folders_and_modules(monkeypatch):
    settings.set_many({"modarchive_api_key": "s3cret"})
    asked = []

    def get(url):
        asked.append(url)
        return Page(GENRES if "view_genres" in url else BAD_KEY if "query=Z" in url else MODULES)
    monkeypatch.setattr(online, "_get", get)
    online._listings.clear()
    src = online.source("modarchive")
    assert online.about(src) == src.about
    genres = online.listing(src, "genres")
    assert genres["dirs"] == [{"name": "Electronic - Ambient", "path": "genres/2", "count": 2843},
                              {"name": "Electronic - Dance", "path": "genres/6", "count": 4120}]
    d = online.listing(src, "genres/6")
    assert asked[-1] == "https://api.modarchive.org/xml-tools.php?key=s3cret&request=search&type=genre&query=6&page=1"
    assert d["crumbs"][-1] == {"name": "Electronic - Dance", "path": "genres/6"} and d["more"]
    first, second = d["files"]
    assert first == {"name": "4mat_-_broken_heart.xm", "path": "module/182782/4mat_-_broken_heart.xm", "size": 61760,
                     "title": "<3 broken heart <3", "artist": "4-Mat", "genre": "Chiptune", "kind": "tune",
                     "format": "xm", "chip": True}
    assert second["artist"] == "Elwood"                                  # a guessed artist
    online.listing(src, "genres/6", page=2)
    assert asked[-1].endswith("&page=3")
    assert modarchive.download_url(["module", "182782", "x.xm"]) == "https://api.modarchive.org/downloads.php?moduleid=182782"
    with pytest.raises(online.OnlineError, match="didn't accept the API key"):
        online.listing(src, "letters/Z")
    row = {"title": "4mat_-_broken_heart", "artist": "", "album": "182782"}
    modarchive.label(["module", "182782", "4mat_-_broken_heart.xm"], row)
    assert (row["title"], row["artist"], row["album"]) == ("<3 broken heart <3", "4-Mat", "")
    settings.set_many({"modarchive_api_key": ""})


def test_the_key_stays_out_of_the_log(caplog):
    with caplog.at_level(logging.INFO, logger="httpx"):
        logging.getLogger("httpx").info('HTTP Request: %s %s "%s"', "GET",
                                        "https://api.modarchive.org/xml-tools.php?key=s3cret&request=view_genres", "HTTP/1.1 200 OK")
    assert "s3cret" not in caplog.text and "key=…" in caplog.text
    assert online.hide_keys("…?key=abc&x=1") == "…?key=…&x=1"
