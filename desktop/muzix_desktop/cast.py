"""Google Cast speakers for the window's player (3.4 in docs/app-plan.md): the speakers on the network
(pychromecast), and one of them playing the queue song by song, with the signed links the page makes
for speakers (frontend/src/player/cast.ts), as casting from Chrome does. pychromecast talks to the
speaker from its own threads; everything here reaches the window's thread as Qt signals, and commands go
to the speaker one after the other on a thread of their own.

Each command waits for the speaker's answer (half a second and more from a group of speakers), so the ones
waiting are kept few: a new volume or place in the song takes the place of one still waiting (a slider
dragged sends dozens), a new song or a stop drops what waited for the old one, and letting go of the
speaker drops everything. The volume is the speaker's own: it's read when connecting and as it changes
(its buttons, another app), never set to the window's."""

import logging
import threading

from PySide6.QtCore import QObject, Signal

log = logging.getLogger(__name__)

try:
    import pychromecast
    import zeroconf
    from pychromecast.discovery import CastBrowser, SimpleCastListener
except ImportError:
    pychromecast = None


class Caster(QObject):
    speakers = Signal()             # the list changed
    state = Signal(str, str)        # unavailable | available | connecting | connected, and the speaker's name
    status = Signal()               # the speaker's player changed
    finished = Signal()             # the song played to its end on the speaker
    loudness = Signal(float, bool)  # the speaker's own volume (0 to 1) and whether it's muted

    def __init__(self):
        super().__init__()
        self.found: dict = {}           # uuid → CastInfo
        self.cc = None                  # the speaker connected to
        self.media = None               # its status (pychromecast's MediaStatus)
        self.name = ""
        self.connecting = False
        self.level, self.muted = 0.0, False     # the speaker's volume, as it last said
        self.waiting: list[tuple[str, object]] = []     # (kind, what to do) for the speaker, in order
        self.lock = threading.Condition()
        self.closing = False
        self.worker = threading.Thread(target=self._work, name="cast", daemon=True)
        self.worker.start()
        self.zc = None
        self.browser = None
        if pychromecast is None:
            log.warning("No pychromecast: no casting")
            return
        try:
            self.zc = zeroconf.Zeroconf()
            self.browser = CastBrowser(SimpleCastListener(self._seen, self._gone, self._seen), self.zc)
            self.browser.start_discovery()
        except OSError as e:
            log.warning("Can't look for speakers (%s)", e)

    def _seen(self, uuid, _service=None):
        if self.browser and uuid in self.browser.devices:
            self.found[uuid] = self.browser.devices[uuid]
        self.speakers.emit()
        self._tell()

    def _gone(self, uuid, _service=None, _info=None):
        self.found.pop(uuid, None)
        self.speakers.emit()
        self._tell()

    def _tell(self):
        if self.cc is not None:
            self.state.emit("connected", self.name)
        elif self.connecting:
            self.state.emit("connecting", self.name)
        else:
            self.state.emit("available" if self.found else "unavailable", "")

    def list(self) -> list[tuple[str, str]]:
        """(uuid, name) of each speaker found, by name."""
        return sorted(((u, i.friendly_name) for u, i in self.found.items()), key=lambda x: x[1].lower())

    @property
    def active(self) -> bool:
        return self.cc is not None

    # ------------------------------------------------------------ one command after the other

    def _submit(self, kind: str, fn, instead_of: tuple[str, ...] = ()):
        """`fn` for the speaker, after what waits; the ones waiting of the kinds in `instead_of` go."""
        with self.lock:
            if instead_of:
                self.waiting = [w for w in self.waiting if w[0] not in instead_of]
            self.waiting.append((kind, fn))
            self.lock.notify()

    def _work(self):
        while True:
            with self.lock:
                while not self.waiting:
                    if self.closing:
                        return
                    self.lock.wait()
                kind, fn = self.waiting.pop(0)
            try:
                fn()
            except Exception as e:      # the speaker didn't answer in time, or is gone: the next one may work
                log.warning("The speaker didn't take %s: %s", kind, e or e.__class__.__name__)

    # ------------------------------------------------------------ connecting

    def connect(self, uuid: str, then):
        """To the speaker; then() on the window's thread once it's there."""
        info = self.found.get(uuid)
        if info is None or self.connecting:
            return
        self.connecting, self.name = True, info.friendly_name
        self._tell()
        done = _Once(then)

        def run():
            try:
                cc = pychromecast.get_chromecast_from_cast_info(info, self.zc)
                cc.wait(timeout=15)
                listener = _Listener(self)
                cc.media_controller.register_status_listener(listener)
                cc.register_status_listener(listener)
                self.cc = cc
                self.level = -1.0               # not known yet: what it says first is told
                if cc.status is not None:
                    listener.new_cast_status(cc.status)
            except Exception as e:      # the speaker is gone, or won't talk: told, and nothing changes here
                log.warning("Couldn't connect to %s: %s", info.friendly_name, e)
            self.connecting = False
            self._tell()
            if self.cc is not None:
                done.call.emit()

        self._submit("connect", run)

    def disconnect(self):
        """The speaker stops (its receiver closes), and the music comes back here: before anything that waits."""
        cc, self.cc, self.media = self.cc, None, None
        self._tell()
        if cc is not None:
            def quit_():
                try:
                    cc.quit_app()
                finally:
                    cc.disconnect(timeout=5)
            self._submit("quit", quit_, instead_of=("load", "seek", "play", "pause", "stop", "volume"))

    # ------------------------------------------------------------ playing there

    def load(self, url: str, mime: str, it: dict, at: float, play: bool, live: bool):
        cc = self.cc
        if cc is None:
            return
        art = it.get("art") or None
        meta = {"metadataType": 3, "title": it.get("title") or "", "artist": it.get("artist") or "",
                "albumName": it.get("album") or "", "images": [{"url": art}] if art else []}
        self._submit("load", lambda: cc.media_controller.play_media(
            url, mime, title=it.get("title") or "", thumb=art, current_time=at or None, autoplay=play,
            stream_type="LIVE" if live else "BUFFERED", metadata=meta),
            instead_of=("load", "seek", "play", "pause", "stop"))       # what waited was for the song before

    def play(self):
        self._do("play", lambda mc: mc.play(), instead_of=("play", "pause"))

    def pause(self):
        self._do("pause", lambda mc: mc.pause(), instead_of=("play", "pause"))

    def stop_media(self):
        self._do("stop", lambda mc: mc.stop(), instead_of=("load", "seek", "play", "pause", "stop"))

    def seek(self, seconds: float, playing: bool = True):
        """To a place in the song (the last one asked for, when several wait); paused, it stays paused there
        (the speaker starts playing after a seek by itself)."""
        def go(mc):
            mc.seek(max(0.0, seconds))
            if not playing:
                mc.pause()
        self._do("seek", go, instead_of=("seek",))

    def volume(self, level: float, muted: bool):
        """The speaker's volume (the last one asked for, when several wait): only what differs from what it has."""
        cc = self.cc
        if cc is None:
            return
        level = max(0.0, min(1.0, level))

        def go():
            if abs(level - self.level) >= 0.005:
                cc.set_volume(level)
            if muted != self.muted:
                cc.set_volume_muted(muted)
        self._submit("volume", go, instead_of=("volume",))

    def _do(self, kind: str, fn, instead_of: tuple[str, ...] = ()):
        cc = self.cc
        if cc is not None:
            self._submit(kind, lambda: fn(cc.media_controller), instead_of)

    # what the speaker plays, as the page is told it
    def position(self) -> float:
        return float(self.media.adjusted_current_time or 0) if self.media else 0.0

    def playing(self) -> bool:
        return bool(self.media) and self.media.player_state in ("PLAYING", "BUFFERING")

    def buffering(self) -> bool:
        return bool(self.media) and self.media.player_state == "BUFFERING"

    def stop(self):
        """The app quits: the speaker is let go first (a few seconds at most), so it doesn't play on alone."""
        if self.browser:
            self.browser.stop_discovery()
        if self.cc is not None:
            self.disconnect()
        with self.lock:
            self.closing = True
            self.lock.notify()
        self.worker.join(timeout=8)


class _Once(QObject):
    """A call back on the window's thread."""
    call = Signal()

    def __init__(self, fn):
        super().__init__()
        self.call.connect(fn)


class _Listener:
    """The speaker's media status and its own (its volume), from pychromecast's thread."""

    def __init__(self, caster: Caster):
        self.caster = caster

    def new_media_status(self, status):
        before = self.caster.media
        self.caster.media = status
        self.caster.status.emit()
        if status.player_state == "IDLE" and status.idle_reason == "FINISHED" and \
                (before is None or before.player_state != "IDLE"):
            self.caster.finished.emit()

    def new_cast_status(self, status):
        level, muted = float(status.volume_level or 0), bool(status.volume_muted)
        if (level, muted) != (self.caster.level, self.caster.muted):
            self.caster.level, self.caster.muted = level, muted
            self.caster.loudness.emit(level, muted)

    def load_media_failed(self, queue_item_id, error_code):
        log.warning("The speaker couldn't play it (%s)", error_code)
