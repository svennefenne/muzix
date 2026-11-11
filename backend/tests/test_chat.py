"""The Library Network's chat: private messages between people here and on linked servers, with
albums and songs linked in them. The other server ("Friend") is a stand-in that answers as one."""
import hashlib
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, update

from muzix import art, chat, db, limits, network
from muzix.api import chat as chat_api, connect, network as network_api
from muzix.models import Album, Artist, ChatMessage, Peer, Root, Track, User
from muzix.security import current_user

KEY = "friendkey" * 5          # what Friend shows us
OURS = "ourkey" * 7            # what we show Friend


class Friend:
    """A linked server with one person on it, dora (7): what it got handed, and what waits there."""

    def __init__(self):
        self.got, self.waiting, self.asked_after = [], [], []
        self.down = self.old = False

    def handle(self, req: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("no route to host")
        if self.old:
            return httpx.Response(404, json={"detail": "Not Found"})
        assert req.headers["authorization"] == f"Bearer {OURS}"
        if req.url.path == "/api/network/chat/people":
            return httpx.Response(200, json=[{"id": 7, "name": "dora"}])
        if req.url.path == "/api/network/chat" and req.method == "POST":
            body = json.loads(req.content)
            if body["to_user"] != 7:
                return httpx.Response(404, json={"detail": "There's nobody by that name here"})
            self.got.append(body)
            return httpx.Response(200, json={"ok": True, "name": "dora"})
        if req.url.path == "/api/network/chat":
            after = int(req.url.params["after"])
            self.asked_after.append(after)
            return httpx.Response(200, json={"messages": [m for m in self.waiting if m["id"] > after], "more": False})
        return httpx.Response(404)


@pytest.fixture(scope="module")
def world():
    """anna, bo and cia (who left herself out of the chat) here; an album of ours; Friend linked,
    with an album of its own mirrored here; and a server we're not linked with."""
    with db.session() as s:
        s.execute(delete(ChatMessage))
        users = {n: User(username=f"chat-{n}", password_hash="x", prefs={"chat_hidden": True} if n == "cia" else {})
                 for n in ("anna", "bo", "cia", "eve")}
        root, theirs = Root(path="/chat-music", kind="music"), Root(path="peer:friend-server", kind="peer")
        ar = Artist(name="Chat Band")
        s.add_all([*users.values(), root, theirs, ar])
        s.flush()
        friend = Peer(server_id="friend-server", name="Friend", address="https://friend.example", sent=True,
                      received=True, key=OURS, their_key=hashlib.sha256(KEY.encode()).hexdigest())
        s.add(friend)
        s.flush()
        ours = Album(title="Our Record", artist_name=ar.name, artist_id=ar.id, folder="/chat-music/a", key="chat-a",
                     art="/chat-music/a/cover.jpg", year=1999)
        mirrored = Album(title="Their Record", artist_name=ar.name, artist_id=ar.id, folder="peer:friend-server/albums/77",
                         key="peer:friend-server:77", art="peer:friend-server/albums/77/3", year=2004, peer_id=friend.id)
        s.add_all([ours, mirrored])
        s.flush()
        songs = [Track(root_id=root.id, path=f"/chat-music/a/{n}.flac", title=f"Ours {n}", artist=ar.name, album_id=ours.id,
                       artist_id=ar.id, track_no=n, duration=100.0 + n, format="flac") for n in (1, 2)]
        songs += [Track(root_id=theirs.id, path=f"peer:friend-server/tracks/{500 + n}", title=f"Theirs {n}", artist=ar.name,
                        album_id=mirrored.id, artist_id=ar.id, track_no=n, duration=200.0, format="mp3", peer_id=friend.id)
                  for n in (1, 2)]
        s.add_all(songs)
        s.flush()
        return {**{n: SimpleNamespace(id=u.id, username=u.username, prefs=u.prefs) for n, u in users.items()},
                "peer": friend.id, "ours": ours.id, "mirrored": mirrored.id, "songs": [t.id for t in songs]}


@pytest.fixture
def friend(monkeypatch):
    f = Friend()
    transport = httpx.MockTransport(f.handle)
    monkeypatch.setattr(network, "_client", lambda follow=False: httpx.Client(transport=transport))
    chat._people.clear()
    return f


@pytest.fixture
def notes(monkeypatch):
    """What the account's open pages were told (api/connect.py)."""
    told = []
    monkeypatch.setattr(connect, "tell", lambda uid, msg: told.append((uid, msg)))
    return told


@pytest.fixture(autouse=True)
def fresh():
    with db.session() as s:
        s.execute(delete(ChatMessage))
        s.execute(update(Peer).where(Peer.server_id == "friend-server").values(chat_after=0))
        s.execute(update(Album).values(hidden=False))


def view(network_on=True):
    """A page's session (db.get_db_with_copies), for a reader with the network's music on or off."""
    s = db.SessionLocal()
    s.info["hide"] = s.info["copies"] = True
    s.info["viewer"] = SimpleNamespace(network=network_on)
    return s


def friend_peer():
    with db.session() as s:
        p = s.scalar(select(Peer).where(Peer.server_id == "friend-server"))
        s.expunge(p)
        return p


def test_people_here_and_on_linked_servers(world, friend):
    found = {(p["server"], p["name"]): p for p in chat.people(world["anna"])}
    here = network.server_id()
    assert (here, "chat-bo") in found and found[(here, "chat-bo")]["here"]
    assert (here, "chat-anna") not in found and (here, "chat-cia") not in found      # not herself; cia left
    dora = found[("friend-server", "dora")]
    assert dora["user"] == 7 and dora["place"] == "Friend" and not dora["here"]

    chat._people.clear()
    friend.down = True
    assert not [p for p in chat.people(world["anna"]) if p["server"] == "friend-server"]


def test_a_conversation_here(world, friend, notes):
    here = network.server_id()
    with view() as v:
        sent = chat.send(world["anna"], here, world["bo"].id, "  hej bo  ", [], v)
    assert sent["mine"] and sent["text"] == "hej bo" and sent["delivered"]
    assert {uid for uid, m in notes} == {world["anna"].id, world["bo"].id} and notes[0][1]["event"] == "new"

    (c,) = chat.conversations(world["bo"])["conversations"]
    assert c["with"]["name"] == "chat-anna" and c["with"]["here"] and c["unread"] == 1 and not c["last"]["mine"]
    assert chat.conversations(world["bo"])["unread"] == 1
    assert chat.conversations(world["anna"])["conversations"][0]["unread"] == 0

    with view() as v:
        chat.send(world["bo"], here, world["anna"].id, "hej anna", [], v)
        t = chat.thread(world["bo"], here, world["anna"].id, v)
    assert [(m["text"], m["mine"]) for m in t["messages"]] == [("hej bo", False), ("hej anna", True)]
    assert chat.read(world["bo"], here, world["anna"].id) == 0
    assert chat.conversations(world["bo"])["unread"] == 0
    # eve sees none of it
    assert chat.conversations(world["eve"])["conversations"] == []

    with view() as v, pytest.raises(chat.ChatError, match="Write something"):
        chat.send(world["anna"], here, world["bo"].id, "   ", [], v)
    with view() as v, pytest.raises(chat.ChatError, match="That's you"):
        chat.send(world["anna"], here, world["anna"].id, "me", [], v)


def test_who_left_the_chat_takes_no_new_messages_but_can_be_answered(world, friend, notes):
    here = network.server_id()
    with view() as v:
        with pytest.raises(chat.ChatError, match="isn't taking messages") as e:
            chat.send(world["anna"], here, world["cia"].id, "hi?", [], v)
        assert e.value.status == 403
        chat.send(world["cia"], here, world["anna"].id, "hi anna, it's cia", [], v)
        assert chat.send(world["anna"], here, world["cia"].id, "hi cia", [], v)["text"] == "hi cia"


def test_links_say_where_the_music_is(world, friend, notes):
    here = network.server_id()
    with view() as v:
        sent = chat.send(world["anna"], here, world["bo"].id, "listen",
                         [{"kind": "album", "id": world["ours"]}, {"kind": "track", "id": world["songs"][3]}], v)
    with db.session() as s:
        album, song = s.scalar(select(ChatMessage.links).where(ChatMessage.id == sent["id"]))
    assert (album["server"], album["id"], album["title"], album["year"]) == (here, world["ours"], "Our Record", 1999)
    assert album["art"] == art.version("album", world["ours"]) and album["place"] == network.name()
    assert [t["title"] for t in album["tracks"]] == ["Ours 1", "Ours 2"] and album["tracks"][0]["id"] == world["songs"][0]
    # a song mirrored from Friend is Friend's: its ids there
    assert (song["server"], song["id"], song["album"], song["art"], song["place"]) == \
        ("friend-server", 502, {"id": 77, "title": "Their Record"}, 3, "Friend")
    assert [t["id"] for t in song["tracks"]] == [501, 502]

    # bo has both here: the album page, the song, our covers
    a, t = sent["links"]
    assert (a["reach"], a["here_album"], a["cover"]) == ("here", world["ours"], art.url("album", world["ours"]))
    assert (t["reach"], t["here_track"], t["here_album"]) == ("here", world["songs"][3], world["mirrored"])
    assert (a["songs"], a["length"]) == (2, 203)
    with view() as v:
        full = chat.resolve(v, song, tracks=True)
    assert [(x["local"], x["stream"]) for x in full["tracks"]] == \
        [(world["songs"][2], f"/api/stream/{world['songs'][2]}"), (world["songs"][3], f"/api/stream/{world['songs'][3]}")]

    with view() as v, pytest.raises(chat.ChatError, match="isn't in your library"):
        chat.send(world["anna"], here, world["bo"].id, "", [{"kind": "album", "id": 999999}], v)


def link_to(server, album=99, art_version=2):
    return chat.clean_link({"kind": "album", "server": server, "id": album, "title": "Elsewhere", "artist": "Someone",
                            "year": 2020, "album": {"id": album, "title": "Elsewhere"}, "art": art_version,
                            "tracks": [{"id": 900, "title": "Far", "artist": "Someone", "duration": 61.5, "disc": 1, "no": 1}],
                            "place": "Somewhere"})


def test_what_isnt_here_plays_through_the_server_its_on(world, friend):
    with view() as v:
        got = chat.resolve(v, link_to("friend-server"), tracks=True)
        away = chat.resolve(v, link_to("stranger-server"), tracks=True)
    assert (got["reach"], got["here_album"], got["place"]) == ("network", None, "Friend")
    assert got["cover"] == "/api/art/network/friend-server/album/99?v=2"
    assert got["tracks"][0]["stream"] == "/api/chat/stream/friend-server/900" and got["tracks"][0]["local"] is None
    # a server we're not linked with: what it is, nothing to play
    assert (away["reach"], away["cover"], away["place"], away["tracks"][0]["stream"]) == ("away", None, "Somewhere", None)


def test_what_the_admin_hid_here_isnt_fetched_from_elsewhere(world, friend):
    their = chat.clean_link({"kind": "album", "server": "friend-server", "id": 77, "title": "Their Record",
                             "album": {"id": 77, "title": "Their Record"}, "art": 3,
                             "tracks": [{"id": 501, "title": "Theirs 1"}]})
    with view(network_on=False) as v:          # their music left out of the library: still heard from Friend
        got = chat.resolve(v, their, tracks=True)
    assert (got["reach"], got["here_album"]) == ("network", None)
    assert got["tracks"][0]["stream"] == "/api/chat/stream/friend-server/501"
    with db.session() as s:
        s.execute(update(Album).where(Album.id == world["mirrored"]).values(hidden=True))
    with view() as v:
        got = chat.resolve(v, their, tracks=True)
    assert (got["reach"], got["cover"], got["tracks"][0]["stream"]) == ("away", None, None)


def test_an_account_with_limits_gets_a_link_only_as_this_server_has_it_for_them(world, friend):
    def limited():
        s = view()
        s.info["viewer"] = SimpleNamespace(network=True, limits=limits.Limits(tags=("death metal",)))
        return s
    with limited() as v:
        far = chat.resolve(v, link_to("friend-server"), tracks=True)
        ours = chat.resolve(v, chat.clean_link({"kind": "album", "server": network.server_id(), "id": world["ours"],
                                                "album": {"id": world["ours"], "title": "Our Record"},
                                                "tracks": [{"id": world["songs"][0], "title": "Ours 1"}]}), tracks=True)
    # nothing from elsewhere, where its artist's genres can't be checked; what's here as the hook lets them
    assert (far["reach"], far["cover"], far["tracks"][0]["stream"]) == ("away", None, None)
    assert ours["reach"] == "here" and ours["tracks"][0]["stream"] == f"/api/stream/{world['songs'][0]}"

    app = FastAPI()
    app.include_router(chat_api.router)
    app.include_router(chat_api.art_router)
    who = SimpleNamespace(id=world["anna"].id, username="chat-anna", prefs={}, limits={"tags": ["death metal"]})
    app.dependency_overrides[current_user] = lambda: who
    app.dependency_overrides[chat_api.stream_user] = lambda: who
    c = TestClient(app)
    assert c.get("/api/chat/stream/friend-server/900").status_code == 404
    assert c.get("/api/art/network/friend-server/album/99?v=2").status_code == 404


def test_writing_to_someone_on_a_linked_server(world, friend, notes):
    with view() as v:
        sent = chat.send(world["anna"], "friend-server", 7, "hej dora", [{"kind": "album", "id": world["ours"]}], v,
                         name="dora")
    assert sent["delivered"] and [uid for uid, _ in notes] == [world["anna"].id]
    (body,) = friend.got
    assert (body["from_user"], body["from_name"], body["to_user"], body["text"]) == (world["anna"].id, "chat-anna", 7, "hej dora")
    assert body["id"] == sent["id"] and body["links"][0]["title"] == "Our Record"
    (c,) = chat.conversations(world["anna"])["conversations"]
    assert c["with"] == {"server": "friend-server", "user": 7, "name": "dora", "place": "Friend", "here": False}

    with view() as v:
        with pytest.raises(chat.ChatError, match="nobody by that name") as e:
            chat.send(world["anna"], "friend-server", 8, "anyone?", [], v)
        assert e.value.status == 404
        with pytest.raises(chat.ChatError, match="isn't linked"):
            chat.send(world["anna"], "stranger-server", 1, "hello?", [], v)
        friend.old = True
        with pytest.raises(chat.ChatError, match="without the chat"):
            chat.send(world["anna"], "friend-server", 7, "still there?", [], v)
    with db.session() as s:          # the ones that didn't go aren't kept
        assert s.scalars(select(ChatMessage.text)).all() == ["hej dora"]


def test_a_message_that_doesnt_get_there_waits_until_its_server_asks(world, friend, notes):
    friend.down = True
    with view() as v:
        sent = chat.send(world["anna"], "friend-server", 7, "are you there?", [], v, name="dora")
    assert not sent["delivered"]
    got = chat.waiting(friend_peer(), 0)
    assert [m["text"] for m in got["messages"]] == ["are you there?"] and not got["more"]
    assert (world["anna"].id, "delivered") in [(uid, m["event"]) for uid, m in notes]
    with view() as v:
        assert chat.thread(world["anna"], "friend-server", 7, v)["messages"][0]["delivered"]
    assert chat.waiting(friend_peer(), sent["id"])["messages"] == []


def test_a_linked_server_hands_over_its_peoples_messages(world, friend, notes):
    app = FastAPI()
    app.include_router(network_api.router)
    c = TestClient(app)
    ok = {"Authorization": f"Bearer {KEY}"}
    msg = {"id": 41, "from_user": 7, "from_name": "dora", "to_user": world["bo"].id, "text": "hej bo",
           "sent_at": "2026-11-11T12:00:00+00:00",
           "links": [link_to("friend-server"), {"kind": "playlist", "id": 1}, {"kind": "album", "id": "x"}]}
    assert c.post("/api/network/chat", json=msg).status_code == 401
    r = c.post("/api/network/chat", json=msg, headers=ok)
    assert r.status_code == 200 and r.json()["name"] == "chat-bo"
    assert c.post("/api/network/chat", json=msg, headers=ok).status_code == 200      # again: kept once
    with db.session() as s:
        (m,) = s.scalars(select(ChatMessage).where(ChatMessage.origin == "friend-server")).all()
        assert (m.origin_id, m.from_place, m.to_name, len(m.links)) == (41, "Friend", "chat-bo", 1)   # the odd links dropped
    assert [(uid, n["with"]["name"], n["with"]["place"]) for uid, n in notes] == [(world["bo"].id, "dora", "Friend")]
    (conv,) = chat.conversations(world["bo"])["conversations"]
    assert conv["unread"] == 1 and conv["with"]["server"] == "friend-server"

    assert c.post("/api/network/chat", json={**msg, "id": 42, "to_user": world["cia"].id}, headers=ok).status_code == 403
    assert c.post("/api/network/chat", json={**msg, "id": 43, "to_user": 999999}, headers=ok).status_code == 404
    assert c.post("/api/network/chat", json={**msg, "id": "x"}, headers=ok).status_code == 400

    names = [p["name"] for p in c.get("/api/network/chat/people", headers=ok).json()]
    assert "chat-bo" in names and "chat-cia" not in names
    assert c.get("/api/network/chat?after=0", headers=ok).json() == {"messages": [], "more": False}


def test_catching_up_with_a_linked_server(world, friend, notes):
    friend.waiting = [{"id": i, "from_user": 7, "from_name": "dora", "to_user": world["bo"].id, "text": f"missed {i}",
                       "sent_at": "2026-11-11T10:00:00+00:00", "links": []} for i in (5, 6)]
    friend.waiting.append({"id": 9, "from_user": 7, "from_name": "dora", "to_user": world["cia"].id, "text": "to cia",
                           "links": []})
    chat.catch_up(world["peer"])
    with view() as v:
        t = chat.thread(world["bo"], "friend-server", 7, v)
    assert [m["text"] for m in t["messages"]] == ["missed 5", "missed 6"]
    assert friend_peer().chat_after == 9            # past the one cia doesn't take, too
    chat.catch_up(world["peer"])
    assert friend.asked_after == [0, 9]


def test_more_info_for_the_people_in_the_conversation_only(world, friend, notes):
    here = network.server_id()
    with view() as v:
        sent = chat.send(world["anna"], here, world["bo"].id, "", [{"kind": "album", "id": world["ours"]}], v)
    app = FastAPI()
    app.include_router(chat_api.router)
    who = {"user": world["bo"]}
    app.dependency_overrides[current_user] = lambda: who["user"]
    c = TestClient(app)
    got = c.get(f"/api/chat/messages/{sent['id']}/links/0").json()
    assert got["title"] == "Our Record" and [t["stream"] for t in got["tracks"]] == [f"/api/stream/{i}" for i in world["songs"][:2]]
    assert c.get(f"/api/chat/messages/{sent['id']}/links/1").status_code == 404
    who["user"] = world["eve"]
    assert c.get(f"/api/chat/messages/{sent['id']}/links/0").status_code == 404

    who["user"] = world["anna"]
    r = c.post(f"/api/chat/with/{here}/{world['bo'].id}", json={"text": "x", "links": [{"kind": "book", "id": 1}]})
    assert r.status_code == 422
    assert c.get("/api/chat").json()["conversations"][0]["with"]["name"] == "chat-bo"
