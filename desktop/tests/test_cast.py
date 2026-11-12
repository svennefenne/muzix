"""Casting from the window's player (cast.py): commands for the speaker wait their turn without piling up,
and the volume is the speaker's own."""
import gc
import threading
import time

import pytest
from PySide6.QtCore import QCoreApplication

from muzix_desktop import cast, player


class Media:
    def __init__(self, log, gate):
        self.log, self.gate = log, gate

    def _do(self, what):
        self.gate.wait(5)               # the speaker takes its time to answer
        self.log.append(what)

    def play(self):
        self._do("play")

    def pause(self):
        self._do("pause")

    def stop(self):
        self._do("stop")

    def seek(self, at):
        self._do(f"seek {at:g}")

    def play_media(self, url, mime, **kw):
        self._do(f"load {url}")


class Speaker:
    """A speaker as pychromecast shows it, answering only once `gate` is set."""

    def __init__(self):
        self.log, self.gate = [], threading.Event()
        self.media_controller = Media(self.log, self.gate)

    def set_volume(self, level):
        self.gate.wait(5)
        self.log.append(f"volume {level:g}")

    def set_volume_muted(self, muted):
        self.log.append(f"muted {muted}")

    def quit_app(self):
        self.log.append("quit")

    def disconnect(self, timeout=None):
        self.log.append("disconnect")


@pytest.fixture
def caster(monkeypatch):
    monkeypatch.setattr(cast, "pychromecast", None)        # no looking for speakers on the network
    QCoreApplication.instance() or QCoreApplication([])
    c = cast.Caster()
    c.cc = Speaker()
    c.level = 0.5
    yield c
    c.cc = None
    c.stop()


def settled(c, most=3.0):
    end = time.time() + most
    while time.time() < end:
        with c.lock:
            if not c.waiting:
                time.sleep(0.05)
                return
        time.sleep(0.01)


def test_a_dragged_slider_ends_where_it_was_let_go(caster):
    sp = caster.cc
    caster.volume(0.48, False)
    time.sleep(0.05)                                       # on its way: the speaker hasn't answered yet
    for level in (0.45, 0.4, 0.3, 0.2, 0.1):
        caster.volume(level, False)
    sp.gate.set()
    settled(caster)
    assert sp.log == ["volume 0.48", "volume 0.1"]         # the one on its way, then where it ended: none between


def test_only_what_differs_is_sent(caster):
    sp = caster.cc
    sp.gate.set()
    caster.volume(0.5, False)                              # what the speaker has already (its own word, echoed)
    settled(caster)
    assert sp.log == []
    caster.volume(0.5, True)
    settled(caster)
    assert sp.log == ["muted True"]


def test_stop_and_letting_go_dont_wait_behind_the_rest(caster):
    sp = caster.cc
    caster.volume(0.4, False)                              # on its way
    time.sleep(0.05)
    caster.volume(0.3, False)
    caster.seek(30)
    caster.seek(60)
    caster.pause()
    caster.disconnect()                                    # Stop casting
    sp.gate.set()
    settled(caster)
    assert sp.log == ["volume 0.4", "quit", "disconnect"]  # nothing else that waited is sent to a speaker let go


def test_the_last_place_in_the_song_and_a_new_song(caster):
    sp = caster.cc
    sp.gate.set()
    caster.pause()
    settled(caster)
    sp.gate.clear()
    caster.seek(10)                                        # on its way
    time.sleep(0.05)
    caster.seek(20)
    caster.seek(30, playing=False)
    sp.gate.set()
    settled(caster)
    assert sp.log == ["pause", "seek 10", "seek 30", "pause"]      # paused, it stays paused there
    sp.log.clear()
    sp.gate.clear()
    caster.seek(40)
    time.sleep(0.05)
    caster.seek(50)
    caster.load("http://x/next", "audio/flac", {"title": "Next"}, 0, True, False)
    sp.gate.set()
    settled(caster)
    assert sp.log == ["seek 40", "load http://x/next"]     # the place asked for in the song before isn't the next one's


@pytest.mark.skipif(not player.available(), reason="no GStreamer here")
def test_the_speakers_volume_not_the_windows(caster, monkeypatch):
    import json
    QCoreApplication.instance() or QCoreApplication([])
    p = player.Player(lambda url: {}, speakers=False)
    p.caster = caster
    got = []
    p.sent.connect(lambda s: got.append(json.loads(s)))
    caster.loudness.connect(p._speaker_volume)
    sp = caster.cc
    sp.gate.set()
    p.level = 1.0                                          # the window's own
    listener = cast._Listener(caster)

    class Status:
        volume_level, volume_muted = 0.35, False
    listener.new_cast_status(Status)                       # the speaker says its volume: the slider shows it
    assert [m for m in got if m["t"] == "volume"] == [{"t": "volume", "value": 0.35, "muted": False}]
    p.handle(json.dumps({"t": "volume", "level": 0.35, "value": 0.2, "muted": False}))     # the page's echo
    settled(caster)
    assert sp.log == [] and p.level == 1.0
    p.handle(json.dumps({"t": "volume", "level": 0.2, "value": 0.1, "muted": False}))      # the slider, here
    settled(caster)
    assert sp.log == ["volume 0.2"] and p.level == 1.0     # the speaker's, and the window's own is kept

    got.clear()
    Status.volume_level = 0.21                              # what comes back right after: not put on the slider
    listener.new_cast_status(Status)
    assert not [m for m in got if m["t"] == "volume"]
    p.stop_casting()
    assert {"t": "volume", "value": 1.0, "muted": False} in got        # the window's own volume again
    # the player goes here, on this thread: left in a cycle with the speaker, Python would take it (and its
    # timers) from whichever thread collects next
    caster.loudness.disconnect(p._speaker_volume)
    p.caster = None
    p.release()
    del p
    gc.collect()
