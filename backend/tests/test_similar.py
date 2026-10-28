"""Autoplay: once the queue runs out, songs like what played keep the music going."""
from muzix import db
from muzix.api import library as api
from muzix.models import Album, Artist, PlayEvent, Root, Track, User


def test_autoplay_picks_songs_by_artists_tagged_alike():
    with db.session() as s:
        u = User(username="autoplayer", password_hash="x")
        root = Root(path="/similar", kind="music")
        s.add_all([u, root])
        s.flush()
        artists = {
            "seed": Artist(name="Seed Thrash", genre="Metal", tags=[["thrash metal", 100], ["heavy metal", 50]]),
            "alike": Artist(name="Other Thrash", genre="Metal", tags=[["thrash metal", 90], ["speed metal", 40]]),
            "near": Artist(name="Heavy Band", genre="Metal", tags=[["heavy metal", 100]]),
            "far": Artist(name="Pop Star", genre="Pop", tags=[["pop", 100], ["dance", 60]]),
        }
        s.add_all(artists.values())
        s.flush()
        songs = {}
        for key, a in artists.items():
            al = Album(title=f"{a.name} LP", artist_name=a.name, artist_id=a.id, genre=a.genre,
                       folder=f"/similar/{key}", key=f"similar-{key}")
            s.add(al)
            s.flush()
            songs[key] = []
            for n in range(4):
                t = Track(root_id=root.id, path=f"/similar/{key}/{n}.mp3", title=f"{a.name} {n}", artist=a.name,
                          genre=a.genre, album_id=al.id, artist_id=a.id)
                s.add(t)
                s.flush()
                songs[key].append(t.id)
        chips = []
        for n, system in enumerate(["NES", "NES", "Game Boy"]):
            t = Track(root_id=root.id, path=f"/similar/vgm/{n}.nsf", title=f"Tune {n}", kind="vgm", format="nsf",
                      extra={"system": system})
            s.add(t)
            s.flush()
            chips.append(t.id)
        s.add(PlayEvent(user_id=u.id, track_id=songs["alike"][0]))
        uid = u.id

    def similar(**body):
        with db.session() as s:
            return api.similar(api.Seeds(**body), db=s, user=s.get(User, uid))

    seeds = songs["seed"][:2]
    queued = songs["seed"][2:3]
    got = similar(seeds=seeds, exclude=queued, n=6)
    ids = [t["id"] for t in got]
    assert len(ids) == len(set(ids)) == 6
    assert not set(ids) & {*seeds, *queued, songs["alike"][0]}       # not the seeds, the queue, nor just played
    by = {t["artist"] for t in got}
    assert "Other Thrash" in by
    # the tags lead: thrash before plain heavy metal, and pop only once nothing alike is left
    alike = [t["artist"] for t in got if t["artist"] != "Pop Star"]
    assert len(alike) >= 5

    nes = similar(seeds=[chips[0]], n=5)
    assert [t["id"] for t in nes] == [chips[1]]                         # game music: the same chip only

    assert api.likeness({"a": 1}, {"a": 0.5}) == 1.0
    assert api.likeness({"a": 1}, {"b": 1}) == 0.0
