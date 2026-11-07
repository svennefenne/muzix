"""The Library Network: linking two servers takes both admins' codes."""
import json
import re

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete

from muzix import db, network
from muzix.api import network as api
from muzix.models import Peer, Setting
from muzix.security import admin_user


@pytest.fixture(autouse=True)
def jobs(monkeypatch):
    """No catalogs fetched or dropped for real (mirror.py): what was asked for, in order."""
    asked = []
    with db.session() as s:
        s.execute(delete(Peer))
        s.execute(delete(Setting).where(Setting.key == "network_code"))
    network._tries.clear()
    monkeypatch.setattr(network, "fetch", lambda peer_id, who: asked.append(("fetch", who)))
    monkeypatch.setattr(network, "drop", lambda sid, who: asked.append(("drop", who)))
    return asked


class Other:
    """Another Muzix server at https://other.example, as the network sees it."""

    def __init__(self, code="BBBBB-CCCCC-DDDDD-EEEEE"):
        self.code, self.id = code, "other-server-id"
        self.keys = {}          # what it handed out → server id
        self.theirs = None      # the key it shows us
        self.asked = False      # our admin handed over its code
        self.unlinked = []

    def handle(self, req: httpx.Request) -> httpx.Response:
        if req.url.path == "/api/network/hello":
            return httpx.Response(200, json={"protocol": 1, "server_id": self.id, "name": "Other", "open": True})
        if req.url.path == "/api/network/link":
            body = json.loads(req.content)
            if network.clean_code(body["code"]) != network.clean_code(self.code):
                return httpx.Response(403, json={"detail": "That isn't this server's sharing code"})
            self.asked, self.theirs = True, body["key"]
            key = "o" * 40
            self.keys[key] = body["server_id"]
            return httpx.Response(200, json={"server_id": self.id, "name": "Other", "key": key, "linked": self.entered})
        if req.url.path == "/api/network/unlink":
            self.unlinked.append(req.headers["authorization"])
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(404)

    entered = False     # its admin has entered our code

    def enters_our_code(self, code):
        """Its admin enters our code: it hands it to us."""
        self.entered = True
        return network.receive({"protocol": 1, "code": code, "server_id": self.id, "name": "Other",
                                "address": "https://other.example", "key": "t" * 40}, "203.0.113.9")


@pytest.fixture
def other(monkeypatch):
    o = Other()
    transport = httpx.MockTransport(o.handle)
    monkeypatch.setattr(network, "_client", lambda follow=False: httpx.Client(transport=transport, follow_redirects=follow))
    return o


def peers():
    with db.session() as s:
        return [network.peer_json(p) for p in s.query(Peer)]


def test_a_code_is_four_groups_of_five_letters_and_digits_that_dont_mix_up():
    c = network.new_code()
    assert re.fullmatch(r"[A-HJKMNP-Z2-9]{5}(-[A-HJKMNP-Z2-9]{5}){3}", c)
    assert network.code() == c
    assert network.clean_code(f"[{c.lower()}]") == c.replace("-", "")
    assert network.new_code() != c


def test_addresses_as_typed():
    assert network.clean_address("10.9.77.15:8484") == "http://10.9.77.15:8484"
    assert network.clean_address("192.168.1.5") == "http://192.168.1.5"
    assert network.clean_address("muzix.example.com/") == "https://muzix.example.com"
    assert network.clean_address("http://box.local:8080/muzix/") == "http://box.local:8080/muzix"
    with pytest.raises(network.NetworkError):
        network.clean_address("ftp://x")
    with pytest.raises(network.NetworkError):
        network.clean_address("  ")


def test_both_admins_enter_the_others_code(other, jobs):
    ours = network.new_code()

    # ours enters its address and code: a request there, waiting for its admin here
    p = network.link("other.example", other.code.lower(), "https://muzix.example")
    assert other.asked and p["state"] == "waiting" and p["address"] == "https://other.example"
    assert network.caller(f"Bearer {other.theirs}") is None         # no calls before the link
    assert jobs == []

    # its admin enters ours: linked, and each side calls the other with the keys traded last
    got = other.enters_our_code(ours)
    assert got["linked"] and got["server_id"] == network.server_id()
    assert [q["state"] for q in peers()] == ["linked"]
    assert network.caller(f"Bearer {got['key']}").server_id == other.id
    assert network.caller("Bearer " + "x" * 40) is None
    assert jobs == [("fetch", "Other")]                                # its library, fetched

    # ours ends it: gone here (its library too), and it's told with the key it gave us
    network.unlink(peers()[0]["id"])
    assert peers() == [] and other.unlinked == ["Bearer " + "t" * 40]
    assert jobs[-1] == ("drop", "Other")


def test_its_request_first_then_ours_links(other, jobs):
    ours = network.new_code()
    got = other.enters_our_code(ours)
    assert not got["linked"]
    (p,) = peers()
    assert p["state"] == "asked" and p["address"] == "https://other.example" and p["name"] == "Other"
    assert network.caller(f"Bearer {got['key']}") is None

    assert network.link(p["address"], other.code, "https://muzix.example")["state"] == "linked"
    assert jobs == [("fetch", "Other")]


def test_wrong_codes(other):
    ours = network.new_code()
    with pytest.raises(network.NetworkError, match="isn't its sharing code"):
        network.link("other.example", "AAAAA-AAAAA-AAAAA-AAAAA", "")
    with pytest.raises(network.NetworkError, match="20 letters"):
        network.link("other.example", "ABC", "")

    def ask(code, ip="198.51.100.7"):
        return network.receive({"protocol": 1, "code": code, "server_id": "someone", "key": "k" * 40}, ip)

    for _ in range(network.TRIES):
        with pytest.raises(network.Refused) as e:
            ask("AAAAA-AAAAA-AAAAA-AAAAA")
        assert e.value.status == 403
    with pytest.raises(network.Refused) as e:      # that address has to wait, even with the right one
        ask(ours)
    assert e.value.status == 429
    assert not ask(ours, ip="198.51.100.8")["linked"]
    assert peers()[0]["state"] == "asked"


def test_off_means_no_new_links(other):
    network.turn_off()
    with pytest.raises(network.Refused) as e:
        other.enters_our_code("")
    assert e.value.status == 403
    with pytest.raises(network.NetworkError, match="Turn the Library Network on"):
        network.link("other.example", other.code, "")


def test_the_routes():
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[admin_user] = lambda: object()
    c = TestClient(app)
    hello = c.get("/api/network/hello").json()
    assert hello["protocol"] == 1 and hello["server_id"] == network.server_id() and not hello["open"]

    code = c.post("/api/network/code").json()["code"]
    assert c.get("/api/network/hello").json()["open"]
    assert c.get("/api/network").json()["code"] == code

    r = c.post("/api/network/link", json={"protocol": 1, "code": code, "server_id": "someone-else",
                                          "name": "Friend", "address": "friend.example", "key": "f" * 40})
    assert r.status_code == 200 and not r.json()["linked"]
    (p,) = c.get("/api/network").json()["peers"]
    assert (p["name"], p["address"], p["state"]) == ("Friend", "https://friend.example", "asked")

    assert c.post("/api/network/unlink", headers={"Authorization": "Bearer " + "f" * 40}).status_code == 401
    assert c.post("/api/network/unlink", headers={"Authorization": f"Bearer {r.json()['key']}"}).status_code == 200
    assert c.get("/api/network").json()["peers"] == []

    # the catalog is for linked servers only
    assert c.get("/api/network/catalog/tracks").status_code == 401
    assert c.get("/api/network/catalog/tracks", headers={"Authorization": f"Bearer {r.json()['key']}"}).status_code == 401
