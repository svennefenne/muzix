"""The Muzix window's player (3.2 in docs/app-plan.md): the page hands over the queue as it does to the
Android app (frontend/src/player/app.ts; the same messages as android/.../PlayerBridge.kt) and GStreamer
plays it, every format as it is and gapless: the next song is lined up while the one before still plays.
The player tells the page what plays and where, on each change and twice a second while it plays."""

import base64
import json
import logging
import os
import platform
import re
import sys
import time

from PySide6.QtCore import QObject, QTimer, Signal

from . import __version__
from .cast import Caster

log = logging.getLogger(__name__)

def gst_packages() -> list[str]:
    """GStreamer's Python packages here (Windows and macOS): libs, plugins, the codecs' libraries, the
    runtime, the bindings... each its own (muzix-desktop.spec takes the same ones)."""
    import pkgutil
    return sorted({m.name for m in pkgutil.iter_modules() if m.ispkg and m.name.startswith("gstreamer_")})


def _gstreamer_wheels():
    """GStreamer from its Python packages (Windows and macOS): each tells where its parts are, and those
    paths have to be set before GStreamer is loaded. On Linux it's the system's."""
    import importlib
    for name in gst_packages():
        try:
            mod = importlib.import_module(name)
        except ImportError:
            continue
        for key, value in getattr(mod, "environment", {}).items():
            if isinstance(value, (list, tuple)):        # some give a list of paths
                value = os.pathsep.join(str(v) for v in value)
            # only what's there: some name a folder they don't have, and Windows won't take one that's missing
            value = os.pathsep.join(p for p in value.split(os.pathsep) if p and os.path.exists(p))
            if not value:
                continue
            if key == "PYTHONPATH":
                sys.path[:0] = [p for p in value.split(os.pathsep) if p not in sys.path]
            else:
                os.environ[key] = value + (os.pathsep + os.environ[key] if os.environ.get(key) else "")
            if key == "PATH" and hasattr(os, "add_dll_directory"):
                for d in value.split(os.pathsep):
                    if os.path.isdir(d):
                        os.add_dll_directory(d)


def _gstreamer_frozen():
    """In the built app (PyInstaller): GStreamer's plugins in their own folder only (its start-up hook points
    GStreamer at all of the app's files, and GStreamer would try each library as a plugin), and its
    registry where the user may write (an AppImage can't be written to)."""
    base = getattr(sys, "_MEIPASS", None)
    if base and os.path.isdir(os.path.join(base, "gst_plugins")):
        os.environ["GST_PLUGIN_PATH"] = os.path.join(base, "gst_plugins")
        import platformdirs
        cache = platformdirs.user_cache_dir("muzix-desktop", appauthor=False)
        os.makedirs(cache, exist_ok=True)
        os.environ["GST_REGISTRY"] = os.path.join(cache, "gstreamer-registry.bin")


_gstreamer_wheels()
_gstreamer_frozen()
try:
    import gi
    gi.require_version("Gst", "1.0")
    from gi.repository import Gst
    Gst.init(None)
except (ImportError, ValueError) as e:       # no GStreamer here: the page plays itself, as in a browser
    Gst = None
    log.warning("No GStreamer (%s): the window plays as a browser does", e)

AUDIO, SOFT_VOLUME = 0x2, 0x10          # playbin3's flags: sound only, its own volume
def _now() -> float:
    return time.monotonic()


BANDS = 256                             # as the page's analyser has them (frontend/src/player/engine.ts)
MAGNITUDES = re.compile(r"magnitude=\(float\)\{([^}]*)\}")


def _playbin() -> str:
    """playbin3 from GStreamer 1.22 on; before, its gapless doesn't hold (the Linux build's GStreamer is 1.20),
    and playbin does it."""
    return "playbin3" if Gst.version() >= (1, 22, 0, 0) else "playbin"


def available() -> bool:
    return Gst is not None and Gst.ElementFactory.find(_playbin()) is not None


class Player(QObject):
    sent = Signal(str)          # a message for the page
    changed = Signal()          # what plays, or how (the system's player: mpris.py)
    command = Signal(str, dict)  # one that isn't for the player (the window's: another server, a link)

    def __init__(self, cookies, shown=lambda: True, for_speaker=lambda url: url, speakers=True):
        super().__init__()
        self.cookies = cookies              # () → the cookies for the window's server ("name=value")
        self.shown = shown                  # () → whether the window shows (the visualizer's spectrum only then)
        self.for_speaker = for_speaker      # a speaker's link, on the server's own address (relay.py)
        self.bin = Gst.ElementFactory.make(_playbin(), "muzix")
        self.bin.set_property("flags", AUDIO | SOFT_VOLUME)
        if sink := os.environ.get("MUZIX_AUDIO_SINK"):      # another output (the tests: "fakesink sync=true")
            self.bin.set_property("audio-sink", Gst.parse_bin_from_description(sink, True))
        self.bin.connect("about-to-finish", self._about_to_finish)
        self.bin.connect("source-setup", self._source_setup)
        # the visualizer's spectrum: the page's analyser's bands, 30 times a second
        spectrum = Gst.ElementFactory.make("spectrum")
        if spectrum is not None:
            for k, v in (("bands", BANDS), ("threshold", -100), ("interval", 33_000_000), ("post-messages", True)):
                spectrum.set_property(k, v)
            self.bin.set_property("audio-filter", spectrum)
        self.bus = self.bin.get_bus()
        self.queue: list[dict] = []
        self.index = -1
        self.lined_up: int | None = None    # the next song, set going by about-to-finish
        self.repeat = "off"
        self.want = False                   # playing, as asked
        self.ended = False
        self.buffering = False
        self.start_at = 0.0                 # where to seek once the song is ready
        self.level, self.muted = 1.0, False
        self.failures = 0
        self.meta: dict = {}                # a station's song now (the page's "meta")
        # a Google Cast speaker (cast.py): while one plays, the songs go there one by one
        self.caster = Caster() if speakers else None
        if self.caster:
            self.caster.state.connect(lambda st, name: self._send(t="cast", state=st, device=name))
            self.caster.status.connect(self._state)
            self.caster.finished.connect(self._cast_next)
        QTimer(self, interval=40, timeout=self._messages).start()
        self.ticking = QTimer(self, interval=500, timeout=self._state)

    # ------------------------------------------------------------ the page's messages

    def handle(self, text: str):
        try:
            m = json.loads(text)
        except ValueError:
            return
        t = str(m.get("t"))
        try:
            if fn := getattr(self, "_on_" + t, None):
                fn(m)
            elif t in ("server", "open", "cast", "update"):
                self.command.emit(t, m)
        except Exception:       # a message that fails goes to the log; the window carries on
            log.exception("The page's %r failed", t)

    def _on_hello(self, m):
        # the page offers a newer Muzix Desktop for this system (frontend/src/appUpdate.ts), which opens in the browser
        system = "windows" if sys.platform == "win32" else "macos" if sys.platform == "darwin" else "linux"
        self._send(t="hello", version=f"MuzixDesktop/{__version__}", saves=False, updates=True, opens=True,
                   desktop={"version": __version__, "platform": system},
                   device=platform.node() or "Computer", volume=self.level,
                   queue=[it.get("muzix", "") for it in self.queue], index=self.index, state=self._state_msg())
        if self.caster:
            self.caster._tell()             # the Cast button: speakers about, or one playing

    def _on_load(self, m):
        self.queue = list(m.get("items") or [])
        self.failures = 0
        self._start(int(m.get("index") or 0), float(m.get("position") or 0), bool(m.get("play", True)))

    def _on_upcoming(self, m):
        # everything after the current song, replaced
        self.queue = self.queue[:self.index + 1] + list(m.get("items") or [])
        self.lined_up = None

    def _on_play(self, m):
        if self.index < 0 and self.queue:
            return self._start(0, 0, True)
        if self.ended:
            return self._start(self.index, 0, True)
        self.want = True
        if self.casting:
            self.caster.play()
        else:
            self.bin.set_state(Gst.State.PLAYING)
        self._state()

    def _on_pause(self, m):
        self.want = False
        if self.casting:
            self.caster.pause()
        else:
            self.bin.set_state(Gst.State.PAUSED)
        self._state()

    def _on_seek(self, m):
        cur = self._current()
        if cur is None:
            return
        at = max(0.0, float(m.get("position") or 0) - float(cur.get("offset") or 0))
        if self.casting:
            return self.caster.seek(at)
        self.bin.seek_simple(Gst.Format.TIME, Gst.SeekFlags.FLUSH | Gst.SeekFlags.ACCURATE, int(at * Gst.SECOND))
        self.ended = False

    def _on_jump(self, m):
        i = next((i for i, it in enumerate(self.queue) if it.get("key") == m.get("key")), None)
        if i is not None:
            self._start(i, 0, True)

    def _on_repeat(self, m):
        self.repeat = m.get("mode") or "off"

    def _on_volume(self, m):
        self.muted = bool(m.get("muted"))
        if "level" in m:
            self.level = float(m.get("level") or 0)
        if self.casting:
            return self.caster.volume(self.level, self.muted)        # the speaker's own
        self.bin.set_property("volume", 0.0 if self.muted else max(0.0, min(1.0, float(m.get("value") or 0))))

    def _on_speed(self, m):
        if self.casting:
            return
        rate = max(0.25, min(4.0, float(m.get("value") or 1)))
        ok, pos = self.bin.query_position(Gst.Format.TIME)
        self.bin.seek(rate, Gst.Format.TIME, Gst.SeekFlags.FLUSH | Gst.SeekFlags.ACCURATE,
                      Gst.SeekType.SET, pos if ok else 0, Gst.SeekType.NONE, 0)

    def _on_meta(self, m):
        self.meta = {"title": m.get("title") or "", "artist": m.get("artist") or ""}
        self.changed.emit()

    def _on_stop(self, m):
        if self.casting:
            self.caster.stop_media()
        self.bin.set_state(Gst.State.NULL)
        self.queue, self.index, self.want, self.ended = [], -1, False, False
        self.ticking.stop()
        self._state()

    # ------------------------------------------------------------ a speaker

    @property
    def casting(self) -> bool:
        return bool(self.caster and self.caster.active)

    def cast_to(self, uuid: str):
        """The queue moves to a speaker, from where it plays here (as far as it got by the time the
        speaker answers)."""
        cur = self._current()
        here = self.position() - float((cur or {}).get("offset") or 0)
        asked = _now()

        def there():
            if self._current() is None:
                return self._state()
            at = here + (_now() - asked if self.want else 0)
            self._start(self.index, max(0.0, at), self.want)
            self.caster.volume(self.level, self.muted)
        self.caster.connect(uuid, there)

    def stop_casting(self):
        """The speaker lets go; the queue plays on here, from where it was."""
        cur = self._current()
        at = self.position() - float((cur or {}).get("offset") or 0)
        self.caster.disconnect()
        if cur is not None:
            self._start(self.index, max(0.0, at), self.want)

    def _cast_next(self):
        nxt = self._next_index()
        if nxt is None:
            self.ended, self.want = True, False
            return self._state()
        self._start(nxt, 0, True)

    # ------------------------------------------------------------ the keys (the system's player)

    def toggle(self):
        (self._on_pause if self.want else self._on_play)({})

    def next(self):
        if self.index + 1 < len(self.queue):
            self._start(self.index + 1, 0, True)

    def prev(self):
        """Back to the song's start, or a little in, to the song before, as the page does."""
        if self.position() - float((self._current() or {}).get("offset") or 0) > 4 or self.index <= 0:
            self._on_seek({"position": float((self._current() or {}).get("offset") or 0)})
        else:
            self._start(self.index - 1, 0, True)

    def seek_to(self, seconds: float):
        self._on_seek({"position": seconds})

    def position(self) -> float:
        return self._state_msg()["position"]

    def status(self) -> str:
        return "Stopped" if self.index < 0 else "Playing" if self.want and not self.ended else "Paused"

    def now(self) -> dict:
        """What plays, as the system's player shows it: the station's song, for a station."""
        cur = dict(self._current() or {})
        if self.meta.get("title"):
            cur.update(self.meta)
        return cur

    # ------------------------------------------------------------ playing

    def _current(self) -> dict | None:
        return self.queue[self.index] if 0 <= self.index < len(self.queue) else None

    def _start(self, index: int, at: float, play: bool):
        if not 0 <= index < len(self.queue):
            return
        self.bin.set_state(Gst.State.NULL)
        self.index, self.lined_up, self.ended = index, None, False
        self.meta = {}
        it = self.queue[index]
        self.start_at = at or float(it.get("resume") or 0)
        self.want = play
        if self.casting:
            at, self.start_at = self.start_at, 0.0
            live = bool(it.get("live"))
            self.caster.load(self.for_speaker(it.get("cast") or it["url"]), it.get("castMime") or "audio/flac",
                             dict(it, art=self.for_speaker(it.get("art") or "")), at, play, live)
            self._item()
            return self._state()
        self.bin.set_property("uri", it["url"])
        self.bin.set_state(Gst.State.PLAYING if play else Gst.State.PAUSED)
        self._item()
        self._state()

    def _next_index(self) -> int | None:
        if self.repeat == "one":
            return self.index
        if self.index + 1 < len(self.queue):
            return self.index + 1
        return 0 if self.repeat == "all" and self.queue else None

    def _about_to_finish(self, _bin):
        """GStreamer's streaming thread, as the song nears its end: the next one lined up, gapless."""
        nxt = self._next_index()
        if nxt is not None:
            self.lined_up = nxt
            self.bin.set_property("uri", self.queue[nxt]["url"])

    def _source_setup(self, _bin, source):
        """The window's server takes the window's cookies (the login, and the window's own secret)."""
        if source.find_property("cookies") is not None:
            source.set_property("cookies", self.cookies())
        if source.find_property("user-agent") is not None:
            source.set_property("user-agent", f"MuzixDesktop/{__version__}")

    def _messages(self):
        while (msg := self.bus.pop()) is not None:
            t = msg.type
            if t == Gst.MessageType.STREAM_START:
                if self.lined_up is not None:           # the next song plays now
                    self.index, self.lined_up = self.lined_up, None
                    self.meta = {}
                    self.failures = 0
                    self._item()
                    resume = float(self._current().get("resume") or 0)
                    if resume > 0.5:
                        self.start_at = resume
                self._state()
            elif t == Gst.MessageType.ASYNC_DONE:
                if self.start_at > 0.5:
                    at, self.start_at = self.start_at, 0.0
                    self.bin.seek_simple(Gst.Format.TIME, Gst.SeekFlags.FLUSH | Gst.SeekFlags.ACCURATE, int(at * Gst.SECOND))
                self._state()
            elif t == Gst.MessageType.EOS:
                self.ended, self.want = True, False
                self.bin.set_state(Gst.State.PAUSED)
                self._state()
            elif t == Gst.MessageType.BUFFERING:
                self.buffering = msg.parse_buffering() < 100
                self._state()
            elif t == Gst.MessageType.STATE_CHANGED and msg.src == self.bin:
                self._state()
            elif t == Gst.MessageType.ELEMENT and self.want and self.shown():
                self._spectrum(msg)
            elif t == Gst.MessageType.ERROR:
                err, _ = msg.parse_error()
                self._failed(err.message)
        if self.want and not self.ticking.isActive():
            self.ticking.start()
        elif not self.want and self.ticking.isActive():
            self.ticking.stop()

    def _failed(self, why: str):
        """A song that won't play is skipped, so the queue goes on; after three in a row (the server is down,
        say) it stops trying."""
        cur = self._current() or {}
        log.warning("Couldn't play %s: %s", cur.get("title"), why)
        self._send(t="error", key=cur.get("key", ""), title=cur.get("title", ""), message=why)
        self.failures += 1
        nxt = self.index + 1
        if self.failures < 3 and nxt < len(self.queue):
            self._start(nxt, 0, True)
        else:
            self.bin.set_state(Gst.State.NULL)
            self.want = False
            self._state()

    # ------------------------------------------------------------ what plays, for the page

    def _spectrum(self, msg):
        """The bands in dB, as the page's analyser gives them: 0..255 between -100 and -30 dB."""
        s = msg.get_structure()
        if s is None or s.get_name() != "spectrum":
            return
        m = MAGNITUDES.search(s.to_string())        # PyGObject can't read the list itself
        if not m:
            return
        out = bytes(max(0, min(255, int((float(x) + 100) / 70 * 255))) for x in m.group(1).split(","))
        self._send(t="spectrum", bands=base64.b64encode(out).decode())

    def _send(self, **msg):
        self.sent.emit(json.dumps(msg))

    def _item(self):
        cur = self._current()
        if cur:
            self._send(t="item", key=cur.get("key", ""), offset=float(cur.get("offset") or 0), muzix=cur.get("muzix", ""))

    def _state_msg(self) -> dict:
        cur = self._current() or {}
        if self.casting:
            return {"t": "state", "key": cur.get("key", ""), "position": float(cur.get("offset") or 0) + self.caster.position(),
                    "duration": float(cur.get("duration") or 0), "playing": self.want and not self.ended,
                    "buffering": self.caster.buffering(), "seekable": not cur.get("live"), "ended": self.ended,
                    "left": max(0, len(self.queue) - self.index - 1)}
        ok, pos = self.bin.query_position(Gst.Format.TIME)
        okd, dur = self.bin.query_duration(Gst.Format.TIME)
        seek = Gst.Query.new_seeking(Gst.Format.TIME)
        seekable = self.bin.query(seek) and seek.parse_seeking()[1]
        return {"t": "state", "key": cur.get("key", ""),
                "position": float(cur.get("offset") or 0) + (pos / Gst.SECOND if ok and pos >= 0 else 0),
                "duration": float(cur.get("duration") or 0) or (dur / Gst.SECOND if okd and dur > 0 else 0),
                "playing": self.want and not self.ended, "buffering": self.want and self.buffering,
                "seekable": bool(seekable), "ended": self.ended, "left": max(0, len(self.queue) - self.index - 1)}

    def _state(self):
        self.sent.emit(json.dumps(self._state_msg()))
        self.changed.emit()

    def release(self):
        if self.caster:
            self.caster.stop()
        self.bin.set_state(Gst.State.NULL)
