"""The window's player as Windows' own (its media overlay, the System Media Transport Controls): what plays
shows above the volume and on the lock screen, and the media keys play, pause and skip. A desktop app
gets the controls through a Windows MediaPlayer of its own that plays nothing (pywinrt). Windows calls
from threads of its own; the presses reach the window's thread as a Qt signal."""

import logging

from PySide6.QtCore import QObject, Signal

log = logging.getLogger(__name__)

try:
    from winrt.windows.foundation import Uri
    from winrt.windows.media import MediaPlaybackStatus, MediaPlaybackType, SystemMediaTransportControlsButton
    from winrt.windows.media.playback import MediaPlayer
    from winrt.windows.storage.streams import RandomAccessStreamReference
except ImportError:
    MediaPlayer = None


class Smtc(QObject):
    pressed = Signal(int)

    def __init__(self, player, show, cookies, art=lambda url: url):
        super().__init__()
        self.player, self.art = player, art
        self.sent: tuple = ()
        if MediaPlayer is None:
            log.warning("No pywinrt: no media keys")
            return
        self.mp = MediaPlayer()
        self.mp.command_manager.is_enabled = False          # its controls are ours, not its own playing's
        c = self.controls = self.mp.system_media_transport_controls
        c.is_enabled = c.is_play_enabled = c.is_pause_enabled = c.is_next_enabled = c.is_previous_enabled = True
        c.add_button_pressed(lambda _sender, args: self.pressed.emit(int(args.button)))
        self.pressed.connect(self._pressed)
        player.changed.connect(self._changed)

    def _pressed(self, button: int):
        p = self.player
        b = SystemMediaTransportControlsButton
        if button in (b.PLAY, b.PAUSE) and (button == b.PLAY) != (p.status() == "Playing"):
            p.toggle()
        elif button == b.STOP and p.status() == "Playing":
            p.toggle()
        elif button == b.NEXT:
            p.next()
        elif button == b.PREVIOUS:
            p.prev()

    def _changed(self):
        p = self.player
        it = p.now()
        now = (p.status(), it.get("key"), it.get("title"), it.get("artist"))
        if now == self.sent:
            return
        self.sent = now
        c = self.controls
        c.playback_status = {"Playing": MediaPlaybackStatus.PLAYING, "Paused": MediaPlaybackStatus.PAUSED}.get(
            p.status(), MediaPlaybackStatus.STOPPED)
        u = c.display_updater
        u.type = MediaPlaybackType.MUSIC
        u.music_properties.title = it.get("title") or ""
        u.music_properties.artist = it.get("artist") or ""
        u.music_properties.album_title = it.get("album") or ""
        art = self.art(it.get("art") or "")
        u.thumbnail = RandomAccessStreamReference.create_from_uri(Uri(art)) if art.startswith("http") else None
        u.update()
