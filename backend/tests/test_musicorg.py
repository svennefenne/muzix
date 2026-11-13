"""The musicorg beets plugin's main genre: what it goes by."""

import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("beets", reason="needs beets (pip install -e './backend[organize]'); it's in the Docker image")
sys.path.insert(0, str(Path(__file__).parents[1] / "muzix" / "organize"))
from beets import config  # noqa: E402
from beetsplug import musicorg  # noqa: E402

# Bandcamp's tags of The Operator Sound INC.'s Esoteric Audio for Spaceage Witchcraft (its genre first, the
# place left out), which MusicBrainz matched with no genres and Last.fm's "space age pop" filed in Pop
ESOTERIC = ["Electronic", "Experimental", "Space-Age", "dungeon synth", "easy listening", "esoteric", "exotica", "goth",
            "library music", "modular", "modular synth", "psych", "sci-fi", "soundtrack"]


class Item(dict):
    def __init__(self, orig):
        super().__init__(mo_orig_path=orig, mo_orig_genre="")
        self.path, self.artist, self.genres = orig.encode(), "The Operator Sound INC.", []


class Album(dict):
    albumartist, album, comp, mb_albumid, albumtypes = "The Operator Sound INC.", "Esoteric Audio", False, "d7d7", []

    def __init__(self, items):
        super().__init__(mo_mb_genres="[]")
        self._items = items

    def items(self):
        return self._items


class LastFm:
    failed = 0

    def album(self, artist, album):
        return []

    def artist(self, artist):
        return [("space age pop", 100), ("modular synth", 67)]


@pytest.fixture
def plugin(tmp_path):
    config["directory"] = str(tmp_path / "lib")
    yield musicorg.MusicOrgPlugin()
    config["musicorg"]["bandcamp_tags"] = ""


def test_bandcamps_tags_count_with_its_genre_first(plugin, tmp_path):
    album = Album([Item("/up/b/op/esoteric/1. Switchboard.mp3"), Item("/up/b/op/esoteric/2. Hold.mp3")])
    scores, _ = plugin.score_album(album, LastFm())
    assert scores.most_common(1)[0][0] == "Pop"                     # as it was filed: Last.fm alone

    (tmp_path / "bc.json").write_text(json.dumps({"/up/b/op/esoteric": ESOTERIC}))
    config["musicorg"]["bandcamp_tags"] = str(tmp_path / "bc.json")
    scores, evidence = plugin.score_album(album, LastFm())
    assert scores.most_common(1)[0][0] == "Electronic" and round(scores["Electronic"]) == 130 and round(scores["Pop"]) == 75
    assert "bc:Electronic=60" in evidence and "bc:dungeon synth=15" in evidence

    # a disc's folder: the album's tags are its parent's
    disc = Album([Item("/up/b/op/esoteric/CD1/1. Switchboard.mp3")])
    assert plugin.score_album(disc, LastFm())[0].most_common(1)[0][0] == "Electronic"


class Rock(LastFm):
    """Last.fm's word on another artist of the same name (Nevo, Altera, Sasi...)."""

    def artist(self, artist):
        return [("rock", 100), ("hard rock", 60)]


PSY = ["Electronic", "Progressive Trance", "Psychedelic", "Psychedelic Trance", "Psytrance", "downtempo"]


@pytest.mark.parametrize("tags, lastfm, genre", [
    (PSY, Rock(), "Psytrance"),                                       # Last.fm's namesake doesn't outvote it
    (["Electronic", "Full On Trance", "Psychedelic Goa Trance"], LastFm(), "Psytrance"),
    (["Electronic", "darkpsy", "forest"], Rock(), "Psytrance"),
    (["Electronic", "Experimental", "forest", "dungeon synth"], LastFm(), "Electronic"),    # "forest" alone: a wood
    (["Electronic", "Trance", "Deep Techno"], LastFm(), "Electronic"),                     # trance, not psytrance
])
def test_what_bandcamp_tags_psytrance_is_psytrance(plugin, tmp_path, tags, lastfm, genre):
    (tmp_path / "bc.json").write_text(json.dumps({"/up/b/psy/album": tags}))
    config["musicorg"]["bandcamp_tags"] = str(tmp_path / "bc.json")
    album = Album([Item("/up/b/psy/album/1. Song.mp3")])
    got, decided, _scores, evidence = plugin.main_genre(album, lastfm)
    assert got == genre and decided == (genre == "Psytrance")
    assert ("bc:psytrance decides" in evidence) == decided
