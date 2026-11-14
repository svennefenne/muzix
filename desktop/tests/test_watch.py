"""A server's watch folder on this computer (sharing.py): its admin may pick one only when Settings → Servers
allows it, and then reads and moves files in that folder alone; a move never overwrites. An album it filed
whole is deleted, one set aside it threw away goes to the trash; nothing outside the folder, nor its own."""
import os

import pytest

from muzix_desktop import config, sharing


@pytest.fixture
def server(monkeypatch, tmp_path):
    c = config.Config()
    s = config.Server(address="https://muzix.example", server_id="srv", name="Plopp", key="k", state="linked")
    c.servers.append(s)
    monkeypatch.setattr(config, "_current", c)
    monkeypatch.setattr(config, "save", lambda: None)
    return s


def test_nothing_without_its_say_so(server, tmp_path):
    with pytest.raises(PermissionError):
        sharing._browse("srv", {"path": str(tmp_path)})
    with pytest.raises(PermissionError):
        sharing._set("srv", {"path": str(tmp_path)})
    with pytest.raises(PermissionError):
        sharing._browse("someone else", {"path": str(tmp_path)})


def test_picked_listed_fetched_and_moved(server, tmp_path):
    server.watch = True
    (tmp_path / "Incoming" / "Zyx - Qwerty" / "CD1").mkdir(parents=True)
    (tmp_path / "Incoming" / "Zyx - Qwerty" / "CD1" / "1. Song.flac").write_bytes(b"flac")
    (tmp_path / "Incoming" / "loose.mp3").write_bytes(b"mp3")
    (tmp_path / "Incoming" / "_Done").mkdir()
    (tmp_path / "secret.txt").write_text("not the server's")

    got = sharing._browse("srv", {"path": str(tmp_path)})
    assert got["folders"] == ["Incoming"] and got["path"] == str(tmp_path)
    incoming = str(tmp_path / "Incoming")
    assert sharing._set("srv", {"path": incoming}) == {"path": incoming} and server.watch_folders == [incoming]

    listed = {e["name"]: e["files"] for e in sharing._list("srv", {"path": incoming})}
    assert set(listed) == {"Zyx - Qwerty", "loose.mp3"}                     # its own _Done left alone
    assert listed["Zyx - Qwerty"][0][:2] == ["Zyx - Qwerty/CD1/1. Song.flac", 4]
    assert sharing.watched("srv", incoming, "", "Zyx - Qwerty/CD1/1. Song.flac").endswith("1. Song.flac")
    for rel in ("../secret.txt", "/etc/passwd"):
        with pytest.raises(PermissionError):
            sharing.watched("srv", incoming, "", rel)
    with pytest.raises(PermissionError):
        sharing._list("srv", {"path": str(tmp_path)})                       # only the folder picked

    os.makedirs(os.path.join(incoming, "_Done", "Zyx - Qwerty"))            # one there already: no overwriting
    assert sharing._move("srv", {"path": incoming, "name": "Zyx - Qwerty", "to": "_Done"}) == {"moved": True}
    assert os.path.exists(os.path.join(incoming, "_Done", "Zyx - Qwerty (2)", "CD1", "1. Song.flac"))
    assert sharing._move("srv", {"path": incoming, "name": "loose.mp3", "to": "_Duplicates"}) == {"moved": True}
    assert sharing._list("srv", {"path": incoming, "held": "_Duplicates"})[0]["name"] == "loose.mp3"
    assert sharing._move("srv", {"path": incoming, "name": "loose.mp3", "held": "_Duplicates", "to": "_Failed"})["moved"]
    for bad in ({"name": "../x", "to": "_Done"}, {"name": "x", "to": "Elsewhere"}):
        with pytest.raises(PermissionError):
            sharing._move("srv", {"path": incoming, **bad})

    server.watch = False                                                     # taken back
    with pytest.raises(PermissionError):
        sharing._list("srv", {"path": incoming})


def test_own_compilations_have_a_folder_of_their_own(server, tmp_path):
    """_Compilations: made when the server first looks in it, its folders listed, fetched and deleted as any."""
    server.watch = True
    incoming = tmp_path / "Incoming"
    incoming.mkdir()
    sharing._set("srv", {"path": str(incoming)})
    assert sharing._list("srv", {"path": str(incoming), "held": "_Compilations"}) == []
    assert (incoming / "_Compilations").is_dir()
    assert sharing._list("srv", {"path": str(incoming)}) == []              # not an album itself
    (incoming / "_Compilations" / "Summer Mix").mkdir()
    (incoming / "_Compilations" / "Summer Mix" / "01 a.mp3").write_bytes(b"mp3")
    listed = sharing._list("srv", {"path": str(incoming), "held": "_Compilations"})
    assert listed == [{"name": "Summer Mix", "files": [["Summer Mix/01 a.mp3", 3, listed[0]["files"][0][2]]]}]
    assert sharing._delete("srv", {"path": str(incoming), "held": "_Compilations", "name": "Summer Mix"}) == {"deleted": True}
    assert not (incoming / "_Compilations" / "Summer Mix").exists()


def test_its_say_so_and_the_folder_kept_between_runs(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "PATH", str(tmp_path / "settings.json"))
    monkeypatch.setattr(config, "CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(config, "_current", None)
    c = config.load()
    c.servers.append(config.Server(address="https://muzix.example", server_id="srv", name="Plopp", key="k", state="linked",
                                   watch=True, watch_folders=["/home/me/Incoming", "/home/me/Bandcamp"]))
    config.save()
    monkeypatch.setattr(config, "_current", None)            # Muzix Desktop started again
    s = config.load().server("srv")
    assert s.watch is True and s.watch_folders == ["/home/me/Incoming", "/home/me/Bandcamp"]

    # as Muzix Desktop before 0.4.24 kept it: its one folder
    (tmp_path / "settings.json").write_text(
        '{"servers": [{"address": "https://muzix.example", "server_id": "srv", "name": "Plopp", "key": "k", '
        '"state": "linked", "watch": true, "watch_folder": "/home/me/Incoming"}]}')
    monkeypatch.setattr(config, "_current", None)
    assert config.load().server("srv").watch_folders == ["/home/me/Incoming"]


def test_an_album_filed_whole_is_deleted_one_thrown_away_goes_to_the_trash(server, tmp_path, monkeypatch):
    server.watch = True
    incoming = tmp_path / "Incoming"
    (incoming / "Zyx - Qwerty" / "CD1").mkdir(parents=True)
    (incoming / "Zyx - Qwerty" / "CD1" / "1. Song.flac").write_bytes(b"flac")
    (incoming / "_Duplicates" / "Zyx - Again").mkdir(parents=True)
    (incoming / "_Duplicates" / "Zyx - Again" / "1. Song.flac").write_bytes(b"flac")
    (tmp_path / "secret.txt").write_text("not the server's")
    server.watch_folders = [str(incoming)]
    trashed = []
    monkeypatch.setattr(sharing.QFile, "moveToTrash", lambda path: trashed.append(path) or True)

    at = {"path": str(incoming)}
    assert sharing._delete("srv", {**at, "name": "Zyx - Qwerty"}) == {"deleted": True}
    assert not (incoming / "Zyx - Qwerty").exists()
    assert sharing._delete("srv", {**at, "name": "Zyx - Qwerty"}) == {"deleted": False}          # gone already
    assert sharing._trash("srv", {**at, "name": "Zyx - Again", "held": "_Duplicates"}) == {"trashed": True}
    assert trashed == [str(incoming / "_Duplicates" / "Zyx - Again")]
    monkeypatch.setattr(sharing.QFile, "moveToTrash", lambda path: False)
    with pytest.raises(OSError):
        sharing._trash("srv", {**at, "name": "Zyx - Again", "held": "_Duplicates"})
    for bad in ({"name": "../secret.txt"}, {"name": ".."}, {"name": "_Duplicates"}, {"name": ""}, {"name": "x", "held": "Elsewhere"}):
        with pytest.raises(PermissionError):
            sharing._delete("srv", {**at, **bad})
    with pytest.raises(PermissionError):
        sharing._delete("srv", {"path": str(tmp_path), "name": "secret.txt"})                     # only the folder picked
    assert (tmp_path / "secret.txt").exists() and (incoming / "_Duplicates").exists()
    server.watch = False
    with pytest.raises(PermissionError):
        sharing._delete("srv", {**at, "name": "Zyx - Again", "held": "_Duplicates"})


def test_of_a_folder_of_albums_those_the_library_has_go_aside_under_its_name(server, tmp_path):
    server.watch = True
    incoming = tmp_path / "Incoming"
    for part in ("known-one", "known-two/CD1", "new-one", "Live: Somewhere"):
        (incoming / "zyx-band" / part).mkdir(parents=True)
        (incoming / "zyx-band" / part / "1. Song.flac").write_bytes(b"flac")
    (incoming / "_Duplicates" / "zyx-band" / "known-one").mkdir(parents=True)        # set aside before: (2)
    (tmp_path / "secret").mkdir()
    server.watch_folders = [str(incoming)]
    at = {"path": str(incoming), "name": "zyx-band", "to": "_Duplicates"}

    (incoming / "zyx-band" / "out").symlink_to(tmp_path / "secret")
    assert sharing._aside("srv", {**at, "parts": ["known-one", "known-two/CD1", "gone", "Live: Somewhere"]}) == {"moved": 3}
    aside = incoming / "_Duplicates" / "zyx-band"
    assert (aside / "known-one (2)" / "1. Song.flac").exists() and (aside / "known-two" / "CD1" / "1. Song.flac").exists()
    assert sorted(p.name for p in (incoming / "zyx-band").iterdir()) == ["known-two", "new-one", "out"]
    for bad in ({"parts": ["../../secret"]}, {"parts": [".."]}, {"parts": [""]}, {"parts": ["/etc"]}, {"parts": ["out"]},
                {"parts": ["a\\b"]}, {"to": "Elsewhere"},
                {"name": "../secret"}, {"name": "_Duplicates"}):
        with pytest.raises(PermissionError):
            sharing._aside("srv", {**at, "parts": ["new-one"], **bad})
    assert (incoming / "zyx-band" / "new-one").is_dir() and (tmp_path / "secret").is_dir()



def test_more_than_one_folder_each_picked_and_let_go(server, tmp_path):
    """Muzix Desktop 0.4.24 on: the server's admin may have more than one watch folder here (another for
    Bandcamp alone, say), each picked (watch_pick) and let go of when replaced or taken away; a server before
    that has one (watch_set: that one alone)."""
    server.watch = True
    one, two, three = (str(tmp_path / n) for n in ("In", "Bandcamp", "In2"))
    for d in (one, two, three):
        os.makedirs(d)
    sharing._pick("srv", {"path": one})
    sharing._pick("srv", {"path": two})
    assert server.watch_folders == [one, two]
    assert sharing._list("srv", {"path": two}) == [] and sharing._list("srv", {"path": one}) == []
    sharing._pick("srv", {"path": three, "was": one})                     # the first one replaced
    assert server.watch_folders == [two, three]
    with pytest.raises(PermissionError):
        sharing._list("srv", {"path": one})
    sharing._pick("srv", {"path": "", "was": two})                        # taken away
    assert server.watch_folders == [three]
    with pytest.raises(PermissionError):
        sharing._pick("srv", {"path": str(tmp_path / "nowhere")})
    sharing._set("srv", {"path": one})                                    # a server before 0.4.24: its one
    assert server.watch_folders == [one]
    server.watch = False
    with pytest.raises(PermissionError):
        sharing._pick("srv", {"path": two})
