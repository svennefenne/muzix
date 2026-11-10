"""The window's player as macOS' own (Now Playing, in Control Center and on the lock screen): what plays
shows there, and the media keys, AirPods and the controls there play, pause, skip and seek (pyobjc's
MediaPlayer framework). The presses reach the window's thread as a Qt signal."""

import logging

from PySide6.QtCore import QObject, Signal

log = logging.getLogger(__name__)

try:
    import MediaPlayer as MP
except ImportError:
    MP = None


class NowPlaying(QObject):
    pressed = Signal(str, float)

    def __init__(self, player, show, headers, art=lambda url: url):
        super().__init__()
        self.player = player
        self.sent: tuple = ()
        if MP is None:
            log.warning("No pyobjc MediaPlayer: no media keys")
            return
        self.info = MP.MPNowPlayingInfoCenter.defaultCenter()
        cc = MP.MPRemoteCommandCenter.sharedCommandCenter()
        ok = MP.MPRemoteCommandHandlerStatusSuccess
        for command, name in ((cc.playCommand(), "play"), (cc.pauseCommand(), "pause"),
                              (cc.togglePlayPauseCommand(), "toggle"), (cc.nextTrackCommand(), "next"),
                              (cc.previousTrackCommand(), "prev")):
            command.setEnabled_(True)
            command.addTargetWithHandler_(lambda _e, n=name: (self.pressed.emit(n, 0.0), ok)[1])
        seek = cc.changePlaybackPositionCommand()
        seek.setEnabled_(True)
        seek.addTargetWithHandler_(lambda e: (self.pressed.emit("seek", float(e.positionTime())), ok)[1])
        self.pressed.connect(self._pressed)
        player.changed.connect(self._changed)

    def _pressed(self, what: str, at: float):
        p = self.player
        if what == "toggle" or (what in ("play", "pause") and (what == "play") != (p.status() == "Playing")):
            p.toggle()
        elif what == "next":
            p.next()
        elif what == "prev":
            p.prev()
        elif what == "seek":
            p.seek_to(at)

    def _changed(self):
        p = self.player
        it = p.now()
        now = (p.status(), it.get("key"), it.get("title"), int(p.position()) if p.status() != "Playing" else 0)
        if now == self.sent:
            return
        self.sent = now
        self.info.setNowPlayingInfo_({
            MP.MPMediaItemPropertyTitle: it.get("title") or "",
            MP.MPMediaItemPropertyArtist: it.get("artist") or "",
            MP.MPMediaItemPropertyAlbumTitle: it.get("album") or "",
            MP.MPMediaItemPropertyPlaybackDuration: float(it.get("duration") or 0),
            MP.MPNowPlayingInfoPropertyElapsedPlaybackTime: float(p.position()),
            MP.MPNowPlayingInfoPropertyPlaybackRate: 1.0 if p.status() == "Playing" else 0.0,
        })
        self.info.setPlaybackState_({"Playing": MP.MPNowPlayingPlaybackStatePlaying,
                                     "Paused": MP.MPNowPlayingPlaybackStatePaused}.get(p.status(), MP.MPNowPlayingPlaybackStateStopped))
