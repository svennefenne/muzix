"""Google Cast speakers for the window's player (3.4 in docs/app-plan.md): the speakers on the network
(pychromecast), and one of them playing the queue song by song, with the signed links the page makes
for speakers (frontend/src/player/cast.ts), as casting from Chrome does. pychromecast talks to the
speaker from its own threads; everything here reaches the window's thread as Qt signals, and commands go
to the speaker one after the other on a thread of their own."""

import logging
from concurrent.futures import ThreadPoolExecutor

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

    def __init__(self):
        super().__init__()
        self.found: dict = {}           # uuid → CastInfo
        self.cc = None                  # the speaker connected to
        self.media = None               # its status (pychromecast's MediaStatus)
        self.name = ""
        self.connecting = False
        self.work = ThreadPoolExecutor(max_workers=1, thread_name_prefix="cast")
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
                cc.media_controller.register_status_listener(_Listener(self))
                self.cc = cc
            except Exception as e:      # the speaker is gone, or won't talk: told, and nothing changes here
                log.warning("Couldn't connect to %s: %s", info.friendly_name, e)
            self.connecting = False
            self._tell()
            if self.cc is not None:
                done.call.emit()

        self.work.submit(run)

    def disconnect(self):
        """The speaker stops (its receiver closes), and the music comes back here."""
        cc, self.cc, self.media = self.cc, None, None
        self._tell()
        if cc is not None:
            self.work.submit(lambda: (cc.quit_app(), cc.disconnect(timeout=5)))

    # ------------------------------------------------------------ playing there

    def load(self, url: str, mime: str, it: dict, at: float, play: bool, live: bool):
        cc = self.cc
        if cc is None:
            return
        art = it.get("art") or None
        meta = {"metadataType": 3, "title": it.get("title") or "", "artist": it.get("artist") or "",
                "albumName": it.get("album") or "", "images": [{"url": art}] if art else []}
        self.work.submit(lambda: cc.media_controller.play_media(
            url, mime, title=it.get("title") or "", thumb=art, current_time=at or None, autoplay=play,
            stream_type="LIVE" if live else "BUFFERED", metadata=meta))

    def play(self):
        self._do(lambda mc: mc.play())

    def pause(self):
        self._do(lambda mc: mc.pause())

    def stop_media(self):
        self._do(lambda mc: mc.stop())

    def seek(self, seconds: float):
        self._do(lambda mc: mc.seek(max(0.0, seconds)))

    def volume(self, level: float, muted: bool):
        cc = self.cc
        if cc is not None:
            self.work.submit(lambda: (cc.set_volume(max(0.0, min(1.0, level))), cc.set_volume_muted(muted)))

    def _do(self, fn):
        cc = self.cc
        if cc is not None:
            self.work.submit(lambda: fn(cc.media_controller))

    # what the speaker plays, as the page is told it
    def position(self) -> float:
        return float(self.media.adjusted_current_time or 0) if self.media else 0.0

    def playing(self) -> bool:
        return bool(self.media) and self.media.player_state in ("PLAYING", "BUFFERING")

    def buffering(self) -> bool:
        return bool(self.media) and self.media.player_state == "BUFFERING"

    def stop(self):
        if self.browser:
            self.browser.stop_discovery()
        if self.cc is not None:
            self.disconnect()
        self.work.shutdown(wait=False)


class _Once(QObject):
    """A call back on the window's thread."""
    call = Signal()

    def __init__(self, fn):
        super().__init__()
        self.call.connect(fn)


class _Listener:
    """The speaker's media status, from pychromecast's thread."""

    def __init__(self, caster: Caster):
        self.caster = caster

    def new_media_status(self, status):
        before = self.caster.media
        self.caster.media = status
        self.caster.status.emit()
        if status.player_state == "IDLE" and status.idle_reason == "FINISHED" and \
                (before is None or before.player_state != "IDLE"):
            self.caster.finished.emit()

    def load_media_failed(self, queue_item_id, error_code):
        log.warning("The speaker couldn't play it (%s)", error_code)
