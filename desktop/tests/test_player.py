"""The Muzix window's player (player.py): the page's queue plays, and the next song follows gapless."""
import json
import os
import struct
import time
import wave

import pytest
from PySide6.QtCore import QCoreApplication, QEventLoop

from muzix_desktop import player

pytestmark = pytest.mark.skipif(not player.available(), reason="no GStreamer here")


def _until(app, done, most: float = 8.0):
    """The player plays on (Qt's events) until done(), or `most` seconds: a busy computer is slower. Not
    app.exec(): a quit another test's timer still has would end the wait early."""
    end = time.monotonic() + most
    while not done() and time.monotonic() < end:
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)
        time.sleep(0.005)


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
    loudness = player.Signal(float, bool)

    def __init__(self):
        super().__init__()
        self.active, self.name, self.did, self.at = False, "Kitchen", [], 0.0
        self.level, self.muted = 0.3, False

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
    assert "volume" not in speaker.did      # the speaker keeps its own volume: the window's isn't put on it
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


def test_what_played_last_is_kept_for_the_next_start(tmp_path, monkeypatch):
    monkeypatch.setenv("MUZIX_AUDIO_SINK", "fakesink sync=true")
    for name in ("a", "b"):
        _song(str(tmp_path / f"{name}.wav"), 3.0)
    app = QCoreApplication.instance() or QCoreApplication([])
    items = [{"key": k, "url": f"file://{tmp_path}/{k}.wav", "title": k.upper(), "duration": 3.0, "muzix": f'{{"key":"{k}"}}'}
             for k in ("a", "b")]
    last = str(tmp_path / "last.json")
    place = ["server"]
    old = player.Player(lambda url: {}, speakers=False, last=last, place=lambda: place[0])
    old.handle(json.dumps({"t": "load", "index": 1, "position": 0, "play": True, "items": items}))
    _until(app, lambda: old.position() > 1.0)
    old.handle(json.dumps({"t": "pause"}))
    at = old.position()
    old.release()                                   # the app quits

    new = player.Player(lambda url: {}, speakers=False, last=last, place=lambda: place[0])
    got = []
    new.sent.connect(lambda s: got.append(json.loads(s)))
    new.handle(json.dumps({"t": "hello"}))
    hello = next(m for m in got if m["t"] == "hello")
    assert hello["queue"] == [] and hello["last"]["queue"] == [it["muzix"] for it in items]
    assert hello["last"]["index"] == 1 and abs(hello["last"]["position"] - at) < 0.3 and hello["last"]["at"] > 0
    assert not new.want                             # shown paused by the page, nothing plays yet

    place[0] = "local"                              # another library: not its songs
    got.clear()
    new.handle(json.dumps({"t": "hello"}))
    assert "last" not in next(m for m in got if m["t"] == "hello")
    place[0] = "server"
    new.handle(json.dumps({"t": "load", "index": 0, "position": 0, "play": False, "items": items}))
    new.handle(json.dumps({"t": "stop"}))           # a queue cleared is forgotten
    assert not os.path.exists(last)
    new.release()


def test_seeks_one_after_another_are_one_once_they_settle(tmp_path, monkeypatch):
    # +15 pressed again and again: one seek, to where the last one goes, made once they stop; meanwhile the
    # player says it's there already, so the page's next +15 counts from it
    monkeypatch.setenv("MUZIX_AUDIO_SINK", "fakesink sync=true")
    _song(str(tmp_path / "a.wav"), 12.0)
    app = QCoreApplication.instance() or QCoreApplication([])
    p = player.Player(lambda url: {}, speakers=False)
    made = []
    seek = p.bin.seek_simple
    p.bin.seek_simple = lambda fmt, flags, at: (made.append(at / player.Gst.SECOND), seek(fmt, flags, at))[1]
    p.handle(json.dumps({"t": "load", "index": 0, "position": 0, "play": True,
                         "items": [{"key": "a", "url": f"file://{tmp_path}/a.wav", "title": "A", "duration": 12.0}]}))
    _until(app, lambda: p.position() > 0.3)
    for at in (3, 5, 7, 9):
        p.handle(json.dumps({"t": "seek", "position": at}))
        assert p._state_msg()["position"] == at
        _until(app, lambda: False, most=0.1)
    assert made == []
    _until(app, lambda: bool(made) and p.position() > 9.2)
    last = p._state_msg()
    p.release()
    assert made == [9.0]
    assert last["playing"] and 9.2 < last["position"] < 11


def _stand_still(p):
    """The sound output stops taking it, as PipeWire did: the sink's pad blocks, the position stays."""
    pad = p.bin.get_property("audio-sink").get_by_name("out").get_static_pad("sink")
    return pad, pad.add_probe(player.Gst.PadProbeType.BLOCK_DOWNSTREAM, lambda *_: player.Gst.PadProbeReturn.OK)


def test_a_song_that_stands_still_while_it_plays_starts_again_where_it_stood(tmp_path, monkeypatch):
    monkeypatch.setenv("MUZIX_AUDIO_SINK", "fakesink name=out sync=true")
    monkeypatch.setattr(player, "STALL", 0.8)
    _song(str(tmp_path / "a.wav"), 8.0)
    app = QCoreApplication.instance() or QCoreApplication([])
    p = player.Player(lambda url: {}, speakers=False)
    got, revived = [], []
    p.sent.connect(lambda s: got.append(json.loads(s)))
    revive = p._revive
    p._revive = lambda at: (revived.append(at), revive(at))
    p.handle(json.dumps({"t": "load", "index": 0, "position": 0, "play": True,
                         "items": [{"key": "a", "url": f"file://{tmp_path}/a.wav", "title": "A", "duration": 8.0}]}))
    _until(app, lambda: p.position() > 1.0)
    pad, probe = _stand_still(p)
    _until(app, lambda: False, most=0.6)            # what had passed plays out
    stood = p.position()
    _until(app, lambda: False, most=0.3)
    assert abs(p.position() - stood) < 0.05 and p._state_msg()["playing"]       # it says it plays, and stands
    _until(app, lambda: bool(revived))
    pad.remove_probe(probe)                         # the new sound output takes it
    _until(app, lambda: p.position() > stood + 0.5 and p.revived == 0)       # on again: tries counted anew
    last = p._state_msg()
    p.release()
    assert len(revived) == 1 and abs(revived[0] - stood) < 0.05
    assert p.revived == 0
    assert last["playing"] and stood + 0.5 < last["position"] < stood + 3      # on from where it stood
    assert [m["key"] for m in got if m["t"] == "item"] == ["a"]                 # no new song for the page
    assert not [m for m in got if m["t"] == "error"]


def test_a_song_that_stands_still_however_its_started_stops_and_says_so(tmp_path, monkeypatch):
    monkeypatch.setenv("MUZIX_AUDIO_SINK", "fakesink name=out sync=true")
    monkeypatch.setattr(player, "STALL", 0.5)
    _song(str(tmp_path / "a.wav"), 8.0)
    app = QCoreApplication.instance() or QCoreApplication([])
    p = player.Player(lambda url: {}, speakers=False)
    got = []
    p.sent.connect(lambda s: got.append(json.loads(s)))
    p.handle(json.dumps({"t": "load", "index": 0, "position": 0, "play": True,
                         "items": [{"key": "a", "url": f"file://{tmp_path}/a.wav", "title": "A", "duration": 8.0}]}))
    _until(app, lambda: p.position() > 1.0)
    _stand_still(p)
    _until(app, lambda: not p.want, most=12)
    last = p._state_msg()
    p.release()
    assert p.revived == player.REVIVALS
    assert [m["title"] for m in got if m["t"] == "error"] == ["A"]
    assert not last["playing"] and last["position"] > 1.0
