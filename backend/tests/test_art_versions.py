"""A changed picture gets a new address everywhere it's shown, so browsers don't keep the old one."""
import io

from PIL import Image

from muzix import art, db, manage, serial
from muzix.models import Album, Artist, Root, Track


def _png(colour) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (40, 40), colour).save(out, "PNG")
    return out.getvalue()


def test_a_new_picture_gets_a_new_address_and_keeps_it():
    with db.session() as s:
        pictured, plain = Artist(name="Pictured Artist"), Artist(name="Coverless Artist")
        root = Root(path="/art-v", kind="music")
        s.add_all([pictured, plain, root])
        s.flush()
        mine = Album(title="Own Picture", artist_name=pictured.name, artist_id=pictured.id, folder="/art-v/a", key="art-v-a", art="/art-v/a/cover.jpg")
        theirs = Album(title="Borrowed Cover", artist_name=plain.name, artist_id=plain.id, folder="/art-v/b", key="art-v-b", art="/art-v/b/cover.jpg")
        s.add_all([mine, theirs])
        s.flush()
        ids = {"pictured": pictured.id, "plain": plain.id, "mine": mine.id, "theirs": theirs.id}
        s.add(Track(root_id=root.id, path="/art-v/b/1.mp3", title="Song", album_id=theirs.id, artist_id=plain.id))

    def shown():
        with db.session() as s:
            song = s.query(Track).filter_by(path="/art-v/b/1.mp3").one()
            return {"pictured": serial.artist(s.get(Artist, ids["pictured"]))["art"],
                    "plain": serial.artist(s.get(Artist, ids["plain"]))["art"],
                    "mine": serial.album(s.get(Album, ids["mine"]))["art"],
                    "theirs": serial.album(s.get(Album, ids["theirs"]))["art"],
                    "song": serial.track(song)["art"]}

    first = shown()
    assert first["pictured"] == f"/api/art/artist/{ids['pictured']}?v=1"
    assert first["song"] == first["theirs"] == f"/api/art/album/{ids['theirs']}?v=1"

    manage.set_cover("artist", ids["pictured"], _png("red"))        # the artist's own picture
    after = shown()
    assert after["pictured"] == f"/api/art/artist/{ids['pictured']}?v=2"
    assert {k: v for k, v in after.items() if k != "pictured"} == {k: v for k, v in first.items() if k != "pictured"}

    # an album's cover (its folder isn't Muzix's to write, so the cover goes into Muzix's data):
    # the album, its songs, and the artist that shows that cover for want of a picture of its own
    manage.set_cover("album", ids["theirs"], _png("blue"))
    manage.set_cover("album", ids["mine"], _png("green"))
    after = shown()
    assert after["theirs"].endswith("?v=2") and after["song"] == after["theirs"]
    assert after["plain"].endswith("?v=2")
    assert after["mine"].endswith("?v=2") and after["pictured"].endswith("?v=2")     # has its own picture

    art._versions = None           # as after a restart
    assert shown() == after
