"""A server's watch folder on this computer (sharing.py): its admin may pick one only when Settings → Servers
allows it, and then reads and moves files in that folder alone; a move never overwrites or deletes."""
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
    assert sharing._set("srv", {"path": incoming}) == {"path": incoming} and server.watch_folder == incoming

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


def test_its_say_so_and_the_folder_kept_between_runs(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "PATH", str(tmp_path / "settings.json"))
    monkeypatch.setattr(config, "CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(config, "_current", None)
    c = config.load()
    c.servers.append(config.Server(address="https://muzix.example", server_id="srv", name="Plopp", key="k", state="linked",
                                   watch=True, watch_folder="/home/me/Incoming"))
    config.save()
    monkeypatch.setattr(config, "_current", None)            # Muzix Desktop started again
    s = config.load().server("srv")
    assert s.watch is True and s.watch_folder == "/home/me/Incoming"
