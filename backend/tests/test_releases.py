"""Album, EP or single (releases.py): MusicBrainz's release group type from the tags, else a guess from the title
and the length; an admin's choice over both."""
from sqlalchemy import delete, select

from muzix import db, releases, serial
from muzix.models import Album


def test_the_tags_type_first():
    for tag, kind in (("album", "album"), ("ep", "ep"), ("single", "single"), ("album,live", "album"),
                      ("album/compilation", "album"), ("ep,remix", "ep"), ("broadcast", "album"), ("Single", "single")):
        assert releases.classify(tag, "Anything", 12, 3000) == (kind, False), tag
    # the tags win over the length: a long single (a 25-minute remix set) and a short album
    assert releases.classify("single", "Long Mix", 4, 40 * 60) == ("single", False)
    assert releases.classify("album", "Short", 2, 300) == ("album", False)


def test_without_tags_the_title_then_the_length():
    for title, kind in (("Keep It EP", "ep"), ("Keep It (EP)", "ep"), ("Keep It [E.P.]", "ep"), ("Keep It - Single", "single"),
                        ("Keep It (Single)", "single")):
        assert releases.classify("", title, 10, 50 * 60) == (kind, True), title
    for title in ("Deep Step", "Single Ladies Forever", "EP 2 Remastered", "Repeat"):
        assert releases.classify("", title, 10, 50 * 60) == ("album", True), title
    assert releases.classify("", "Two Songs", 2, 8 * 60) == ("single", True)
    assert releases.classify("", "Five Songs", 5, 22 * 60) == ("ep", True)
    assert releases.classify("", "Five Long Songs", 5, 45 * 60) == ("album", True)
    assert releases.classify("none", "Ten Songs", 10, 45 * 60) == ("album", True)     # read, and no type there


def test_albums_get_their_type_and_an_admins_choice_wins():
    with db.session() as s:
        tagged = Album(title="Releases Tagged", folder="/rel/a", key="rel-a", release_tag="ep", track_count=12, duration=3000)
        short = Album(title="Releases Short", folder="/rel/b", key="rel-b", track_count=2, duration=400)
        chosen = Album(title="Releases Chosen", folder="/rel/c", key="rel-c", track_count=2, duration=400, release_set="album")
        s.add_all([tagged, short, chosen])
        s.flush()
        releases.update(s)
        s.flush()
        got = {a.title: (serial.album(a)["release_type"], serial.album(a)["release_guessed"])
               for a in s.scalars(select(Album).where(Album.key.like("rel-%")))}
        s.execute(delete(Album).where(Album.key.like("rel-%")))
    assert got == {"Releases Tagged": ("ep", False), "Releases Short": ("single", True), "Releases Chosen": ("album", False)}


def test_an_admin_sets_the_type_and_takes_it_back():
    from muzix.api import manage as api
    with db.session() as s:
        a = Album(title="Releases Set", folder="/rel/d", key="rel-d", track_count=12, duration=3000, release_type="album",
                  release_guessed=True)
        s.add(a)
        s.flush()
        aid = a.id
    try:
        with db.session() as s:
            assert api.set_release(aid, api.Release(type="ep"), db=s) == {"release_type": "ep", "release_guessed": False}
        with db.session() as s:
            assert api.set_release(aid, api.Release(type=""), db=s) == {"release_type": "album", "release_guessed": True}
    finally:
        with db.session() as s:
            s.execute(delete(Album).where(Album.key == "rel-d"))


GROUPS = [   # as MusicBrainz's release group search gives them
    {"title": "Keep It", "primary-type": "Album", "secondary-types": ["Live"],
     "artist-credit": [{"name": "Someone Else", "artist": {"name": "Someone Else"}}]},
    {"title": "Keep It", "primary-type": "EP", "artist-credit": [{"name": "Releases Band", "artist": {"name": "Releases Band"}}]},
    {"title": "Keep It (Remixes)", "primary-type": "Single", "artist-credit": [{"name": "Releases Band"}]},
]


def test_a_musicbrainz_release_group_of_the_same_title_by_the_same_artist():
    assert releases.match(GROUPS, "Releases Band", "Keep It") == "ep"
    assert releases.match(GROUPS, "releases band", "Keep It EP") == "ep"      # the title without its EP
    assert releases.match(GROUPS, "Someone Else", "Keep It!") == "album,live"
    assert releases.match(GROUPS, "Releases Band", "Keep") == ""
    assert releases.match(GROUPS, "Nobody", "Keep It") == ""


def test_an_artists_guessed_albums_are_looked_up_once():
    from muzix.models import Artist
    asked = []

    def ask(artist, title):
        asked.append(title)
        return GROUPS if title == "Keep It" else []
    with db.session() as s:
        ar = Artist(name="Releases Band")
        s.add(ar)
        s.flush()
        s.add_all([
            Album(title="Keep It", artist_id=ar.id, folder="/rel/e", key="rel-e", track_count=12, duration=3000,
                  release_type="album", release_guessed=True),
            Album(title="Unknown Thing", artist_id=ar.id, folder="/rel/f", key="rel-f", track_count=12, duration=3000,
                  release_type="album", release_guessed=True),
            Album(title="Tagged Thing", artist_id=ar.id, folder="/rel/g", key="rel-g", release_tag="single",
                  release_type="single", release_guessed=False),
        ])
        aid = ar.id
    try:
        with db.session() as s:
            assert releases.unchecked(s, aid)
        assert releases.check_now(aid, ask) == 2
        assert sorted(asked) == ["Keep It", "Unknown Thing"]           # not the one its tags tell
        with db.session() as s:
            got = {a.title: (a.release_type, a.release_guessed, a.release_checked is not None)
                   for a in s.scalars(select(Album).where(Album.key.like("rel-%")))}
            assert not releases.unchecked(s, aid)
        assert got == {"Keep It": ("ep", False, True), "Unknown Thing": ("album", True, True),
                       "Tagged Thing": ("single", False, False)}
        assert releases.check_now(aid, ask) == 0 and len(asked) == 2      # once
    finally:
        with db.session() as s:
            s.execute(delete(Album).where(Album.key.like("rel-%")))
            s.execute(delete(Artist).where(Artist.id == aid))
