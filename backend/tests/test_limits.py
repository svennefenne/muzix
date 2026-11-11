"""What an admin leaves out for one account (limits.py): by genre tag with its subgenres, by genre folder,
by artist, untagged artists of a genre folder, and whole sections. For that account the music isn't
there anywhere, and there's no way round it through the API; the account can't change it either."""
from types import SimpleNamespace

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from muzix import db, limits, modules, scanner
from muzix.api import admin, auth, books as books_api, library, me, stream
from muzix.models import Album, Artist, AuthSession, Book, Playlist, PlaylistItem, Root, Track, User
from muzix.security import hash_password

METAL, POP = "Limits Metal", "Limits Pop"
ARTISTS = {
    # name: (genre folder, tags)
    "Rotting Hymn": (METAL, [["death metal", 100], ["metal", 40]]),
    "Gothenburg Sound": (METAL, [["Melodic-Death Metal", 100]]),      # a subgenre, spelled otherwise
    "Iron Saint": (METAL, [["heavy metal", 100], ["metalcore", 20]]),
    "Basement Thrash": (METAL, []),                                    # no tags yet
    "Pop Star": (POP, [["pop", 100]]),
    "Symphonic Choir": (POP, [["symphonic metal", 36], ["death metal", 3]]),    # only a little death metal
    "Let Through": (METAL, [["death metal", 100]]),
    "Limits Various": ("", []),
}


@pytest.fixture
def lib(tmp_path):
    """Two albums each by death metal, melodic death metal, heavy metal, untagged and pop artists, a
    compilation with a death metal song on it, an album without a genre folder, a chiptune, a book;
    the listener whose music is limited and the admin."""
    names = (*ARTISTS, "Nobody Knows")
    with db.session() as s:
        s.execute(delete(Root).where(Root.path == str(tmp_path)))
        s.execute(delete(User).where(User.username.in_(["limits-wife", "limits-owner"])))
        s.execute(delete(Album).where(Album.key.like("limits-%")))
        s.execute(delete(Artist).where(Artist.name.in_(names)))
        root = Root(path=str(tmp_path), kind="music")
        wife = User(username="limits-wife", password_hash=hash_password("secret1"))
        owner = User(username="limits-owner", password_hash=hash_password("secret2"), is_admin=True)
        s.add_all([root, wife, owner])
        s.flush()
        made = {"root": root.id, "wife": wife.id, "owner": owner.id, "artist": {}, "album": {}, "track": {}}

        def song(album: Album, title: str, artist: str, kind="music"):
            path = tmp_path / f"{title}.mp3"
            path.write_bytes(b"ID3" + b"\0" * 64)
            t = Track(root_id=root.id, path=str(path), title=title, artist=artist, albumartist=album.artist_name,
                      album=album.title, album_id=album.id, artist_id=album.artist_id, kind=kind, format="mp3",
                      genre=album.genre, duration=60)
            s.add(t)
            s.flush()
            made["track"][title] = t.id

        def album(title: str, artist: str | None, genre: str, kind="music"):
            a = Album(title=title, artist_name=artist or "", artist_id=made["artist"].get(artist), genre=genre,
                      kind=kind, key=f"limits-{title}", folder=str(tmp_path / title), art="")
            s.add(a)
            s.flush()
            made["album"][title] = a.id
            return a

        for name, (genre, tags) in ARTISTS.items():
            a = Artist(name=name, genre=genre, tags=tags)
            s.add(a)
            s.flush()
            made["artist"][name] = a.id
        for name, (genre, _) in ARTISTS.items():
            if name != "Limits Various":
                al = album(f"{name} I", name, genre)
                song(al, f"{name} song", name)
                al = album(f"{name} II", name, genre)
                song(al, f"{name} other song", name)
        comp = album("Limits Hits", "Limits Various", METAL)
        song(comp, "Comp death", "Rotting Hymn")
        song(comp, "Comp heavy", "Iron Saint")
        pop_comp = album("Limits Pop Hits", "Limits Various", POP)
        song(pop_comp, "Pop comp death", "Rotting Hymn")
        song(pop_comp, "Pop comp pop", "Pop Star")
        nobody = Artist(name="Nobody Knows", genre="")
        s.add(nobody)
        s.flush()
        made["artist"]["Nobody Knows"] = nobody.id
        song(album("Limits Unsorted", "Nobody Knows", ""), "Unsorted song", "Nobody Knows")
        song(album("Limits Chips", None, "VGM", kind="vgm"), "Chip song", "", kind="vgm")
        b = Book(root_id=root.id, path=str(tmp_path / "book"), title="Limits book")
        s.add(b)
        s.flush()
        made["book"] = b.id
        pl = Playlist(user_id=owner.id, name="Limits mix", public=True)
        s.add(pl)
        s.flush()
        s.add_all([PlaylistItem(playlist_id=pl.id, track_id=made["track"][t], position=i)
                   for i, t in enumerate(["Rotting Hymn song", "Iron Saint song"])])
        made["playlist"] = pl.id
        for who in ("wife", "owner"):
            s.add(AuthSession(token=f"limits-{who}-token", user_id=made[who]))
    scanner.rebuild_search()
    limits.forget()
    yield made
    with db.session() as s:
        s.execute(delete(Album).where(Album.key.like("limits-%")))
        s.execute(delete(Artist).where(Artist.name.in_(names)))
        s.execute(delete(Root).where(Root.id == made["root"]))
        s.execute(delete(User).where(User.username.in_(["limits-wife", "limits-owner"])))
    limits.forget()


def limit(lib, **rules):
    """Leave these out for the listener, as an admin would."""
    with db.session() as s:
        s.get(User, lib["wife"]).limits = limits.clean(rules) or None
    limits.forget()


def seen(model, rules: dict | None = None) -> set[int]:
    """What a page shows someone with these limits."""
    s = db.SessionLocal()
    s.info["hide"] = True
    s.info["viewer"] = SimpleNamespace(network=True, limits=limits.of(SimpleNamespace(limits=limits.clean(rules))))
    try:
        return set(s.scalars(select(model.id)))
    finally:
        s.close()


def names(lib, kind, ids):
    return sorted(n for n, i in lib[kind].items() if i in ids)


@pytest.fixture
def app():
    app = FastAPI()
    for r in (auth.router, library.router, me.router, stream.router, admin.router):
        app.include_router(r)
    app.include_router(books_api.router, dependencies=[Depends(modules.needed("audiobooks"))])
    app.include_router(books_api.art_router, dependencies=[Depends(modules.needed("audiobooks"))])
    return app


def client(app, who):
    return TestClient(app, headers={"authorization": f"Bearer limits-{who}-token"})


# ---------------------------------------------------------------- what's left out

def test_a_tag_leaves_out_its_artists_and_their_subgenres_everywhere(lib):
    rules = {"tags": ["Death Metal"], "allow": [lib["artist"]["Let Through"]]}
    artists, albums, tracks = seen(Artist, rules), seen(Album, rules), seen(Track, rules)
    gone = {"Rotting Hymn", "Gothenburg Sound"}
    assert names(lib, "artist", set(lib["artist"].values()) - artists) == sorted(gone)
    assert names(lib, "album", set(lib["album"].values()) - albums) == sorted(f"{a} {n}" for a in gone for n in ("I", "II"))
    # their songs on other artists' compilations too; the compilations themselves stay
    assert names(lib, "track", set(lib["track"].values()) - tracks) == sorted(
        ["Comp death", "Pop comp death", "Gothenburg Sound other song", "Gothenburg Sound song",
         "Rotting Hymn other song", "Rotting Hymn song"])
    assert {lib["album"]["Limits Hits"], lib["album"]["Let Through I"], lib["album"]["Iron Saint I"]} <= albums
    # only an artist's main tags count, unless the admin says any of them do
    assert lib["artist"]["Symphonic Choir"] in artists
    assert lib["artist"]["Symphonic Choir"] not in seen(Artist, {**rules, "every_tag": True})
    # a tag is a whole word: "metal" isn't "metalcore", and nothing is left out without limits
    assert lib["artist"]["Iron Saint"] in seen(Artist, {"tags": ["core"]})
    assert set(lib["album"].values()) <= seen(Album)


def test_untagged_artists_of_a_genre_folder_can_be_left_out_too(lib):
    rules = {"tags": ["death metal"], "untagged": [METAL]}
    assert lib["artist"]["Basement Thrash"] not in seen(Artist, rules)
    albums = seen(Album, rules)
    assert lib["album"]["Basement Thrash I"] not in albums
    # the compilation artist has no tags either: its compilations in that folder go, the others stay
    assert lib["album"]["Limits Hits"] not in albums and lib["album"]["Limits Pop Hits"] in albums
    assert lib["artist"]["Limits Various"] in seen(Artist, rules)
    assert {lib["album"]["Iron Saint I"], lib["album"]["Pop Star I"], lib["album"]["Limits Unsorted"]} <= albums


def test_a_genre_folder_and_music_without_one_and_single_artists(lib):
    rules = {"genres": [METAL, ""], "allow": [lib["artist"]["Let Through"]]}
    albums, artists, tracks = seen(Album, rules), seen(Artist, rules), seen(Track, rules)
    assert names(lib, "album", albums & set(lib["album"].values())) == sorted(
        ["Let Through I", "Let Through II", "Limits Chips", "Limits Pop Hits", "Pop Star I", "Pop Star II",
         "Symphonic Choir I", "Symphonic Choir II"])
    assert lib["artist"]["Iron Saint"] not in artists and lib["artist"]["Nobody Knows"] not in artists
    assert lib["artist"]["Let Through"] in artists and lib["artist"]["Limits Various"] in artists
    # an artist left out by folder is left out of other folders' compilations; chiptunes aren't music
    assert lib["track"]["Pop comp death"] not in tracks and lib["track"]["Chip song"] in tracks
    one = {"artists": [lib["artist"]["Pop Star"]]}
    assert lib["album"]["Pop Star I"] not in seen(Album, one) and lib["track"]["Pop comp pop"] not in seen(Track, one)
    assert lib["album"]["Limits Pop Hits"] in seen(Album, one)


# ---------------------------------------------------------------- through the API

def test_theres_no_way_round_it_through_the_api(app, lib):
    limit(lib, tags=["death metal"])
    wife, owner = client(app, "wife"), client(app, "owner")
    hymn, hymn_album, hymn_song = lib["artist"]["Rotting Hymn"], lib["album"]["Rotting Hymn I"], lib["track"]["Rotting Hymn song"]
    assert wife.get(f"/api/artists/{hymn}").status_code == 404
    assert wife.get(f"/api/albums/{hymn_album}").status_code == 404
    assert wife.get(f"/api/stream/{hymn_song}").status_code == 404
    assert wife.get(f"/api/art/album/{hymn_album}").status_code == 404
    assert wife.get(f"/api/art/artist/{hymn}").status_code == 404
    assert wife.post("/api/plays", json={"track_id": hymn_song}).status_code == 404
    assert wife.put(f"/api/likes/album/{hymn_album}").status_code == 404
    assert wife.get(f"/api/tracks/{hymn_song}/lyrics").status_code == 404
    assert wife.get("/api/tracks", params={"ids": f"{hymn_song},{lib['track']['Iron Saint song']}"}).json()[0]["title"] == "Iron Saint song"
    # not found, not listed, not counted
    found = wife.get("/api/search", params={"q": "Rotting Hymn"}).json()
    assert not found["artists"] and not found["albums"] and not found["tracks"]
    assert owner.get("/api/search", params={"q": "Rotting Hymn"}).json()["artists"]
    listed = wife.get("/api/albums", params={"genre": METAL, "limit": 100}).json()
    assert hymn_album not in {a["id"] for a in listed["items"]} and lib["album"]["Iron Saint I"] in {a["id"] for a in listed["items"]}
    genre = {g["name"]: g for g in wife.get("/api/genres", params={"limit": 1000}).json()}[METAL]
    mine = {g["name"]: g for g in owner.get("/api/genres", params={"limit": 1000}).json()}[METAL]
    # Rotting Hymn, Gothenburg Sound and Let Through (not let through here): two albums each
    assert mine["albums"] - genre["albums"] == 6 and mine["artists"] - genre["artists"] == 3
    home, home_all = wife.get("/api/home").json(), owner.get("/api/home").json()
    assert home_all["stats"]["albums"] - home["stats"]["albums"] == 6
    assert home_all["stats"]["artists"] - home["stats"]["artists"] == 3
    assert home_all["stats"]["tracks"] - home["stats"]["tracks"] == 8
    assert wife.get("/api/tags/death metal").json()["artists"] == [] or all(
        a["id"] not in (hymn, lib["artist"]["Gothenburg Sound"]) for a in wife.get("/api/tags/death metal").json()["artists"])
    # the radio, shuffle and someone else's playlist leave them out too
    for _ in range(5):
        picked = {t["id"] for t in wife.post("/api/similar", json={"seeds": [lib["track"]["Iron Saint song"]], "n": 50}).json()}
        assert hymn_song not in picked and lib["track"]["Comp death"] not in picked
        assert hymn_song not in {t["id"] for t in wife.get("/api/random", params={"genre": METAL, "n": 500}).json()}
    assert wife.post("/api/similar", json={"seeds": [hymn_song]}).json() == []
    mix = wife.get(f"/api/playlists/{lib['playlist']}").json()
    assert [t["title"] for t in mix["tracks"]] == ["Iron Saint song"]
    assert [t["title"] for t in owner.get(f"/api/playlists/{lib['playlist']}").json()["tracks"]] == ["Rotting Hymn song", "Iron Saint song"]
    assert owner.get(f"/api/stream/{hymn_song}").status_code == 200


def test_the_account_cant_change_it_or_see_it(app, lib):
    limit(lib, tags=["death metal"])
    wife = client(app, "wife")
    # a preference can't undo it, nor can the admin's own requests
    wife.patch("/api/me/prefs", json={"limits": None, "network": True})
    assert wife.put(f"/api/admin/users/{lib['wife']}/limits", json={}).status_code == 403
    assert wife.get(f"/api/albums/{lib['album']['Rotting Hymn I']}").status_code == 404
    # nothing about the account says it's limited
    state, mine = wife.get("/api/auth/state").json(), wife.get("/api/me").json()
    assert "limits" not in state["user"] and "limits" not in mine and "death metal" not in str(state) + str(mine)


def test_a_section_can_be_turned_off_for_one_account(app, lib):
    limit(lib, sections=["vgm", "audiobooks"])
    wife, owner = client(app, "wife"), client(app, "owner")
    state = wife.get("/api/auth/state").json()["modules"]
    assert state["vgm"] is False and state["audiobooks"] is False and state["podcasts"] is True
    assert owner.get("/api/auth/state").json()["modules"]["vgm"] is True
    assert wife.get("/api/books").json()["detail"] == "The Audiobooks module is turned off on this server"
    assert owner.get("/api/books").status_code == 200
    assert wife.get(f"/api/art/book/{lib['book']}").status_code == 404
    assert wife.get(f"/api/albums/{lib['album']['Limits Chips']}").status_code == 404
    assert wife.get("/api/vgm/systems").json() == []
    assert wife.get("/api/home").json()["stats"]["vgm_tracks"] == 0
    assert wife.get(f"/api/albums/{lib['album']['Rotting Hymn I']}").status_code == 200


# ---------------------------------------------------------------- the admin's side

def test_the_admin_sets_limits_and_sees_what_they_leave_out(app, lib):
    owner = client(app, "owner")
    choices = owner.get("/api/admin/limits/choices").json()
    assert {"name": METAL, "albums": 11, "artists": 6} in choices["genres"]
    assert {g["name"] for g in choices["genres"]} >= {"", POP}
    assert {t["name"] for t in choices["tags"]} >= {"death metal", "melodic death metal", "heavy metal"}
    assert [a["name"] for a in owner.get("/api/admin/limits/artists", params={"q": "hymn"}).json()] == ["Rotting Hymn"]

    body = {"tags": ["Death Metal", "death-metal", ""], "allow": [lib["artist"]["Let Through"]], "untagged": [METAL],
            "sections": ["radio", "nonsense"], "genres": []}
    seen = owner.post("/api/admin/limits/preview", json=body).json()
    assert seen["albums"] >= 7 and seen["songs"] >= 9 and seen["artists"] >= 3
    assert {"Rotting Hymn", "Gothenburg Sound", "Basement Thrash"} <= set(seen["examples"])
    saved = owner.put(f"/api/admin/users/{lib['wife']}/limits", json=body).json()
    assert saved == {"genres": [], "tags": ["death metal"], "untagged": [METAL], "sections": ["radio"], "every_tag": False,
                     "artists": [], "allow": [{"id": lib["artist"]["Let Through"], "name": "Let Through"}]}
    users = {u["username"]: u for u in owner.get("/api/admin/users").json()}
    assert users["limits-wife"]["limits"] == saved and users["limits-owner"]["limits"]["tags"] == []
    assert client(app, "wife").get(f"/api/albums/{lib['album']['Basement Thrash I']}").status_code == 404
    # cleared, everything is back at once
    owner.put(f"/api/admin/users/{lib['wife']}/limits", json={})
    with db.session() as s:
        assert s.get(User, lib["wife"]).limits is None
    assert client(app, "wife").get(f"/api/albums/{lib['album']['Basement Thrash I']}").status_code == 200
