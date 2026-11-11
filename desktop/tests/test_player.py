"""The Muzix window's player (player.py): the page's queue plays, and the next song follows gapless."""
import json
import os
import struct
import wave

import pytest
from PySide6.QtCore import QCoreApplication, QTimer

from muzix_desktop import player

pytestmark = pytest.mark.skipif(not player.available(), reason="no GStreamer here")


def _until(app, done, most: float = 8.0):
    """The player plays on (Qt's loop) until done(), or `most` seconds: a busy computer is slower."""
    def look():
        if done():
            app.quit()
    t = QTimer(interval=50, timeout=look)
    t.start()
    QTimer.singleShot(int(most * 1000), app.quit)
    app.exec()
    t.stop()


def _song(path: str, seconds: float):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(struct.pack("<h", 1000) * int(8000 * seconds))


def test_the_queue_plays_on_gapless(tmp_path, monkeypatch):
    monkeypatch.setenv("MUZIX_AUDIO_SINK", "fakesink sync=true")
    for name in ("a", "b"):
        _song(str(tmp_path / f"{name}.wav"), 1.5)
    app = QCoreApplication.instance() or QCoreApplication([])
    p = player.Player(lambda url: {}, speakers=False)
    got = []
    p.sent.connect(lambda s: got.append(json.loads(s)))
    items = [{"key": k, "url": f"file://{tmp_path}/{k}.wav", "title": k.upper(), "duration": 1.5, "muzix": k} for k in ("a", "b")]
    p.handle(json.dumps({"t": "load", "index": 0, "position": 0, "play": True, "items": items}))
    _until(app, lambda: p._state_msg()["key"] == "b" and p.position() > 0.3)
    last = p._state_msg()
    p.release()
    assert [m["key"] for m in got if m["t"] == "item"] == ["a", "b"]
    assert not [m for m in got if m["t"] == "error"]
    assert last["key"] == "b" and 0.3 < last["position"] < 1.5 and last["playing"]


def test_after_an_updates_restart_it_plays_on_from_where_it_was(tmp_path, monkeypatch):
    monkeypatch.setenv("MUZIX_AUDIO_SINK", "fakesink sync=true")
    for name in ("a", "b"):
        _song(str(tmp_path / f"{name}.wav"), 3.0)
    app = QCoreApplication.instance() or QCoreApplication([])
    items = [{"key": k, "url": f"file://{tmp_path}/{k}.wav", "title": k.upper(), "duration": 3.0, "muzix": k} for k in ("a", "b")]
    old = player.Player(lambda url: {}, speakers=False)
    old.handle(json.dumps({"t": "load", "index": 1, "position": 0, "play": True, "items": items}))
    _until(app, lambda: old.position() > 1.2)
    was = json.loads(json.dumps(old.snapshot()))        # as resume.json keeps it
    old.release()
    assert was["index"] == 1 and was["playing"] and 1.2 < was["position"] < 3

    # the new start: the page's hello gets the queue, and once the server takes the player's requests (the
    # page's first call has the login) it plays on from there
    signed_in = [False]
    new = player.Player(lambda url: {}, speakers=False, signed_in=lambda: signed_in[0])
    new.resume(was)
    got = []
    new.sent.connect(lambda s: got.append(json.loads(s)))
    new.handle(json.dumps({"t": "hello"}))
    hello = next(m for m in got if m["t"] == "hello")
    assert hello["queue"] == ["a", "b"] and hello["index"] == 1
    _until(app, lambda: False, most=0.4)
    assert not [m for m in got if m["t"] == "item"]       # not before the login
    signed_in[0] = True
    _until(app, lambda: new._state_msg()["playing"] and new.position() > was["position"] + 0.2)
    last = new._state_msg()
    new.release()
    assert last["key"] == "b" and last["playing"] and last["position"] > was["position"]
    assert [m["key"] for m in got if m["t"] == "item"] == ["b"]


class _Speaker(player.QObject):
    """A Cast speaker that does as it's told, and remembers what."""
    speakers, state, status, finished = (player.Signal(), player.Signal(str, str), player.Signal(), player.Signal())

    def __init__(self):
        super().__init__()
        self.active, self.name, self.did, self.at = False, "Kitchen", [], 0.0

    def connect(self, uuid, then):
        self.active = True
        then()

    def disconnect(self):
        self.active = False
        self.did.append("disconnect")

    def load(self, url, mime, it, at, play, live):
        self.did.append(("load", url, round(at, 1) > 0, play))
        self.at = 0.0

    def __getattr__(self, name):        # play, pause, seek, volume, stop_media, _tell, stop
        return lambda *a: self.did.append(name)

    def position(self):
        return self.at

    def buffering(self):
        return False


def test_a_speaker_takes_the_queue_and_gives_it_back(tmp_path, monkeypatch):
    monkeypatch.setenv("MUZIX_AUDIO_SINK", "fakesink sync=true")
    monkeypatch.setattr(player, "Caster", _Speaker)
    for name in ("a", "b"):
        _song(str(tmp_path / f"{name}.wav"), 3)
    app = QCoreApplication.instance() or QCoreApplication([])
    p = player.Player(lambda url: {}, for_speaker=lambda url: url.replace("http://127.0.0.1:1", "https://muzix.example.com"))
    items = [{"key": k, "url": f"file://{tmp_path}/{k}.wav", "cast": f"http://127.0.0.1:1/api/stream/{k}?q=cast&ct=t",
              "castMime": "audio/flac", "title": k, "duration": 3} for k in ("a", "b")]
    p.handle(json.dumps({"t": "load", "index": 0, "position": 0, "play": True, "items": items}))
    _until(app, lambda: p.position() > 0.5)
    p.cast_to("kitchen")                    # where it plays here, on the speaker's own address
    speaker = p.caster
    assert speaker.did[0] == ("load", "https://muzix.example.com/api/stream/a?q=cast&ct=t", True, True)
    p.handle(json.dumps({"t": "pause"}))
    assert "pause" in speaker.did
    p.handle(json.dumps({"t": "play"}))
    speaker.finished.emit()                 # the song ended there: the next one, there
    assert speaker.did[-1][:2] == ("load", "https://muzix.example.com/api/stream/b?q=cast&ct=t")
    speaker.at = 1.2
    p.stop_casting()                        # back here, from where the speaker was
    _until(app, lambda: p.position() > 1.4)
    st = p._state_msg()
    p.release()
    assert "disconnect" in speaker.did and st["key"] == "b" and 1.4 < st["position"] < 2.9 and st["playing"]
