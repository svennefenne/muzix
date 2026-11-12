"""The Muzix window's player (3.2 in docs/app-plan.md): the page hands over the queue as it does to the
Android app (frontend/src/player/app.ts; the same messages as android/.../PlayerBridge.kt) and GStreamer
plays it, every format as it is and gapless: the next song is lined up while the one before still plays.
The player tells the page what plays and where, on each change and twice a second while it plays."""

import base64
import json
import logging
import os
import pathlib
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
# no proxy for the player's streams: they're the window's own server's, on 127.0.0.1 (relay.py). GIO would ask
# libproxy, and in the AppImage that throws an exception its C++ can't catch: the app ended on Play (0.4.18)
os.environ.setdefault("GIO_USE_PROXY_RESOLVER", "dummy")
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

    def __init__(self, headers, shown=lambda: True, for_speaker=lambda url: url, speakers=True, library=lambda: "server",
                 downloads=None, downloaded=lambda url: None, offline=lambda: False, signed_in=lambda: True,
                 last="", place=lambda: "", device_id=""):
        super().__init__()
        self.headers = headers              # (url) → the headers the window's own server wants from the player
        self.shown = shown                  # () → whether the window shows (the visualizer's spectrum only then)
        self.for_speaker = for_speaker      # a speaker's link, on the server's own address (relay.py)
        self.library = library              # () → the music the window shows: "server", or "local" (this computer's)
        self.downloads = downloads          # what's downloaded to this computer (downloads.py)
        self.downloaded = downloaded        # (url) → the song's downloaded file, if it's here
        self.offline = offline              # () → whether the server can't be reached (relay.py)
        self.signed_in = signed_in          # () → whether the server takes the player's requests yet (window.py)
        self.last = last                    # the file what played last is kept in, for the next start ("": none)
        self.place = place                  # () → the library that plays: this computer's, or a server's
        self.kept = (0.0, -1, False)        # when it was last kept, and what played then
        self.device_id = device_id          # the window's id as one of the account's devices (frontend/src/player/connect.ts)
        self.bin = Gst.ElementFactory.make(_playbin(), "muzix")
        if Gst.ElementFactory.find("souphttpsrc") is None:
            log.warning("GStreamer has no souphttpsrc here (libsoup didn't load): streams go through curlhttpsrc, "
                        "which can't seek in a podcast and stops in long streams")
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
        self.pending: dict | None = None    # what played before an update's restart (snapshot()), for the page's hello
        self.starts = 0                     # songs started so far (what's asked meanwhile wins over _carry_on)
        self.level, self.muted = 1.0, False
        self.turned = 0.0                   # when the volume was last set from here while a speaker plays
        self.failures = 0
        self.meta: dict = {}                # a station's song now (the page's "meta")
        # a Google Cast speaker (cast.py): while one plays, the songs go there one by one
        self.caster = Caster() if speakers else None
        if self.caster:
            self.caster.state.connect(lambda st, name: self._send(t="cast", state=st, device=name))
            self.caster.status.connect(self._state)
            self.caster.finished.connect(self._cast_next)
            self.caster.loudness.connect(self._speaker_volume)
        QTimer(self, interval=40, timeout=self._messages).start()
        self.ticking = QTimer(self, interval=500, timeout=self._state)
        # what's downloaded, told to the page once things settle (a song done, two more begun)
        self._telling = QTimer(self, singleShot=True, interval=500, timeout=self.send_downloads)
        if downloads:
            downloads.changed.connect(self._downloads_changed)

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
            elif t in ("server", "open", "cast", "update", "library", "folder"):
                self.command.emit(t, m)
        except Exception:       # a message that fails goes to the log; the window carries on
            log.exception("The page's %r failed", t)

    def _on_hello(self, m):
        # the page offers a newer Muzix Desktop for this system (frontend/src/appUpdate.ts), which opens in the browser
        system = "windows" if sys.platform == "win32" else "macos" if sys.platform == "darwin" else "linux"
        has = {"downloads": self.downloads.list(), "offline": self.offline()} if self.downloads else {}
        # after an update's restart: the queue as it was, handed to the page with the hello, then on from where it was
        resume, self.pending = self.pending, None
        if resume:
            self.queue, self.index, self.failures = resume["queue"], resume["index"], 0
        # nothing to play: what played last, which the page shows paused (frontend/src/player/last.ts)
        last = self._kept() if not self.queue else None
        self._send(t="hello", version=f"MuzixDesktop/{__version__}", saves=False, updates=True, opens=True,
                   desktop={"version": __version__, "platform": system},
                   device=platform.node() or "Computer", deviceId=self.device_id,
                   volume=self.caster.level if self.casting else self.level, library=self.library(),
                   queue=[it.get("muzix", "") for it in self.queue], index=self.index, state=self._state_msg(),
                   **({"last": last} if last else {}), **has)
        if self.caster:
            self.caster._tell()             # the Cast button: speakers about, or one playing
        if resume:
            self._carry_on(resume["position"], resume["playing"], self.starts)

    def _carry_on(self, at: float, play: bool, starts: int, tries: int = 100):
        """The song before the restart, from where it was, once the server takes the player's requests (or
        after ten seconds, offline, whatever plays from here); not if something else has started meanwhile."""
        if self.starts != starts:
            return
        if self.signed_in() or tries <= 0:
            return self._start(self.index, at, play)
        QTimer.singleShot(100, lambda: self._carry_on(at, play, starts, tries - 1))

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
            return self.caster.seek(at, self.want)
        self.bin.seek_simple(Gst.Format.TIME, Gst.SeekFlags.FLUSH | Gst.SeekFlags.ACCURATE, int(at * Gst.SECOND))
        self.ended = False

    def _on_jump(self, m):
        i = next((i for i, it in enumerate(self.queue) if it.get("key") == m.get("key")), None)
        if i is not None:
            self._start(i, 0, True)

    def _on_repeat(self, m):
        self.repeat = m.get("mode") or "off"

    def _on_volume(self, m):
        if self.casting:
            # the speaker's own volume, which the slider shows meanwhile (_speaker_volume); the window's stays
            self.turned = _now()
            return self.caster.volume(float(m.get("level") or 0) if "level" in m else self.caster.level, bool(m.get("muted")))
        self.muted = bool(m.get("muted"))
        if "level" in m:
            self.level = float(m.get("level") or 0)
        self.bin.set_property("volume", 0.0 if self.muted else max(0.0, min(1.0, float(m.get("value") or 0))))

    def _speaker_volume(self, level: float, muted: bool):
        """The speaker says its volume (connecting, its buttons, another app): the page's slider shows it. Not
        right after the slider was moved here: what comes back then is on its way to where the slider is."""
        if self.casting and _now() - self.turned > 2:
            self._send(t="volume", value=level, muted=muted)

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

    # downloads (downloads.py): a collection to have here, or not any more; the page's sign-in state, for
    # opening offline

    def _on_download(self, m):
        if self.downloads and isinstance(m.get("collection"), dict):
            self.downloads.add(m["collection"])

    def _on_undownload(self, m):
        if self.downloads:
            self.downloads.remove(str(m.get("id") or ""))

    def _on_signedIn(self, m):
        if self.downloads and isinstance(m.get("state"), dict):
            self.downloads.keep_state(m["state"])

    def _downloads_changed(self):
        self._telling.start()

    def notify(self, text: str):
        self._send(t="notify", text=text)

    def snapshot(self) -> dict:
        """What plays and where, for the next start to carry on from (an update's restart); not playing if a
        speaker plays it (the computer would start playing by itself)."""
        cur = self._current()
        at = self.position() - float(cur.get("offset") or 0) if cur else 0.0
        return {"queue": self.queue, "index": self.index, "position": max(0.0, at),
                "playing": self.want and not self.ended and not self.casting}

    def resume(self, s: dict):
        """Carry on from snapshot() once the page says hello (the queue goes to it then)."""
        queue = [it for it in s.get("queue") or [] if isinstance(it, dict) and it.get("url")]
        if queue:
            self.pending = {"queue": queue, "index": max(0, min(int(s.get("index") or 0), len(queue) - 1)),
                            "position": float(s.get("position") or 0), "playing": bool(s.get("playing"))}

    def send_downloads(self):
        """Everything downloaded, and whether the server can't be reached, for the page."""
        if self.downloads:
            self._send(t="downloads", list=self.downloads.list(), offline=self.offline())

    def _on_stop(self, m):
        if self.casting:
            self.caster.stop_media()
        self.bin.set_state(Gst.State.NULL)
        self.queue, self.index, self.want, self.ended = [], -1, False, False
        self.ticking.stop()
        self._state()
        if self.last:
            pathlib.Path(self.last).unlink(missing_ok=True)      # a queue cleared is forgotten

    # ------------------------------------------------------------ what played last, for the next start

    def keep(self, now: bool = False):
        """What plays and where, into the file: when the song or playing changes, every 15 seconds while it
        plays, and as the app quits (`now`). The page keeps it too, but its storage is written a while later."""
        cur = self._current()
        if not self.last or not cur:
            return
        playing = self.want and not self.ended
        if not now and (self.index, playing) == self.kept[1:] and time.time() - self.kept[0] < 15:
            return
        self.kept = (time.time(), self.index, playing)
        last = {"queue": [it.get("muzix", "") for it in self.queue], "index": self.index, "position": max(0.0, self.position()),
                "at": int(time.time() * 1000), "place": self.place()}
        try:
            path = pathlib.Path(self.last)
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(last))
            os.replace(tmp, path)
        except OSError as e:
            log.warning("Couldn't keep what played last: %s", e)

    def _kept(self) -> dict | None:
        """What played last, if it was in the library that shows now."""
        try:
            last = json.loads(pathlib.Path(self.last).read_text()) if self.last else None
        except (OSError, ValueError):
            return None
        if not isinstance(last, dict) or last.get("place") != self.place() or not last.get("queue"):
            return None
        return {k: last.get(k) for k in ("queue", "index", "position", "at")}

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
        self.caster.connect(uuid, there)

    def stop_casting(self):
        """The speaker lets go; the queue plays on here, from where it was."""
        cur = self._current()
        at = self.position() - float((cur or {}).get("offset") or 0)
        self.caster.disconnect()
        self._send(t="volume", value=self.level, muted=self.muted)      # the window's own volume again
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
        self.starts += 1
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
        self.bin.set_property("uri", self._uri(index))
        self.bin.set_state(Gst.State.PLAYING if play else Gst.State.PAUSED)
        self._item()
        self._state()

    def _uri(self, index: int) -> str:
        """Where the song at `index` plays from: its file, if it's downloaded (downloads.py), else the server."""
        it = self.queue[index]
        f = self.downloaded(it["url"])
        if not f:
            return it["url"]
        if float(it.get("offset") or 0) > 0:
            # a stream from part-way (?t=): the file, from there, its times the song's own
            self.start_at = max(self.start_at, float(it["offset"]))
            self.queue[index] = dict(it, offset=0.0)
        return pathlib.Path(f).as_uri()

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
            self.bin.set_property("uri", self._uri(nxt))

    def _source_setup(self, _bin, source):
        """The window's own server (relay.py) takes the window's secret as a header: GStreamer before 1.22 runs
        several cookies into one line, which loses them."""
        url = source.get_property("location") if source.find_property("location") is not None else ""
        wanted = self.headers(url or "")
        if wanted and source.find_property("extra-headers") is not None:
            extra = Gst.Structure.new_empty("extra-headers")
            for k, v in wanted.items():
                extra.set_value(k, v)
            source.set_property("extra-headers", extra)
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
                err, debug = msg.parse_error()
                log.info("GStreamer: %s", debug)
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
        self.keep()

    def release(self):
        self.keep(now=True)
        if self.caster:
            self.caster.stop()
        self.bin.set_state(Gst.State.NULL)
