"""The window's player as the desktop's own player on Linux (MPRIS, over D-Bus): what plays shows in the
desktop's media controls, and the media keys, headsets and the controls there play, pause, skip and seek.
Gio from PyGObject, as the player has it; Qt's event loop runs GLib's, so its calls come in on the
window's thread."""

import hashlib
import logging
import os
import threading

import httpx

from . import config

log = logging.getLogger(__name__)

try:
    from gi.repository import Gio, GLib
except ImportError:
    Gio = None

PATH = "/org/mpris/MediaPlayer2"
XML = """
<node>
  <interface name="org.mpris.MediaPlayer2">
    <method name="Raise"/><method name="Quit"/>
    <property name="CanQuit" type="b" access="read"/><property name="CanRaise" type="b" access="read"/>
    <property name="HasTrackList" type="b" access="read"/><property name="Identity" type="s" access="read"/>
    <property name="DesktopEntry" type="s" access="read"/>
    <property name="SupportedUriSchemes" type="as" access="read"/><property name="SupportedMimeTypes" type="as" access="read"/>
  </interface>
  <interface name="org.mpris.MediaPlayer2.Player">
    <method name="Next"/><method name="Previous"/><method name="Pause"/><method name="PlayPause"/>
    <method name="Stop"/><method name="Play"/>
    <method name="Seek"><arg direction="in" name="Offset" type="x"/></method>
    <method name="SetPosition"><arg direction="in" name="TrackId" type="o"/><arg direction="in" name="Position" type="x"/></method>
    <method name="OpenUri"><arg direction="in" name="Uri" type="s"/></method>
    <signal name="Seeked"><arg name="Position" type="x"/></signal>
    <property name="PlaybackStatus" type="s" access="read"/><property name="Rate" type="d" access="read"/>
    <property name="Metadata" type="a{sv}" access="read"/><property name="Volume" type="d" access="read"/>
    <property name="Position" type="x" access="read"/><property name="MinimumRate" type="d" access="read"/>
    <property name="MaximumRate" type="d" access="read"/><property name="CanGoNext" type="b" access="read"/>
    <property name="CanGoPrevious" type="b" access="read"/><property name="CanPlay" type="b" access="read"/>
    <property name="CanPause" type="b" access="read"/><property name="CanSeek" type="b" access="read"/>
    <property name="CanControl" type="b" access="read"/>
  </interface>
</node>
"""
US = 1_000_000          # MPRIS counts in microseconds


class Mpris:
    def __init__(self, player, show, headers):
        self.player, self.show, self.headers = player, show, headers
        self.bus = None
        self.sent: dict = {}            # what the desktop was last told
        self.art: dict[str, str] = {}   # a cover's address → its file here (the desktop can't sign in)
        self.dir = os.path.join(config.DATA_DIR, "covers")
        if Gio is None:
            return
        try:
            self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        except GLib.Error as e:
            log.warning("No session bus (%s): no media keys", e.message)
            return
        node = Gio.DBusNodeInfo.new_for_xml(XML)
        for iface in node.interfaces:
            self.bus.register_object(PATH, iface, self._call, self._get, None)
        Gio.bus_own_name_on_connection(self.bus, "org.mpris.MediaPlayer2.muzix", Gio.BusNameOwnerFlags.NONE, None, None)
        player.changed.connect(self._changed)

    # ------------------------------------------------------------ the desktop asks

    def _call(self, conn, sender, path, iface, method, params, invocation):
        p = self.player
        if method in ("Raise", "OpenUri"):
            self.show()
        elif method in ("Play", "Pause", "PlayPause"):
            if method == "PlayPause" or (method == "Play") != (p.status() == "Playing"):
                p.toggle()
        elif method == "Stop":
            if p.status() == "Playing":
                p.toggle()
        elif method == "Next":
            p.next()
        elif method == "Previous":
            p.prev()
        elif method == "Seek":
            p.seek_to(max(0.0, p.position() + params.unpack()[0] / US))
        elif method == "SetPosition":
            p.seek_to(max(0.0, params.unpack()[1] / US))
        invocation.return_value(None)

    def _get(self, conn, sender, path, iface, prop):
        return self._props(iface).get(prop)

    def _props(self, iface: str) -> dict:
        if iface == "org.mpris.MediaPlayer2":
            return {"CanQuit": GLib.Variant("b", False), "CanRaise": GLib.Variant("b", True),
                    "HasTrackList": GLib.Variant("b", False), "Identity": GLib.Variant("s", "Muzix"),
                    "DesktopEntry": GLib.Variant("s", "muzix-desktop"),
                    "SupportedUriSchemes": GLib.Variant("as", []), "SupportedMimeTypes": GLib.Variant("as", [])}
        p = self.player
        has = p.index >= 0
        return {"PlaybackStatus": GLib.Variant("s", p.status()), "Rate": GLib.Variant("d", 1.0),
                "Metadata": GLib.Variant("a{sv}", self._metadata()), "Volume": GLib.Variant("d", p.level),
                "Position": GLib.Variant("x", int(p.position() * US) if has else 0),
                "MinimumRate": GLib.Variant("d", 1.0), "MaximumRate": GLib.Variant("d", 1.0),
                "CanGoNext": GLib.Variant("b", p.index + 1 < len(p.queue)), "CanGoPrevious": GLib.Variant("b", has),
                "CanPlay": GLib.Variant("b", has), "CanPause": GLib.Variant("b", has),
                "CanSeek": GLib.Variant("b", has), "CanControl": GLib.Variant("b", True)}

    def _metadata(self) -> dict:
        it = self.player.now()
        if not it:
            return {"mpris:trackid": GLib.Variant("o", "/org/mpris/MediaPlayer2/TrackList/NoTrack")}
        key = hashlib.sha1((it.get("key") or "").encode()).hexdigest()[:16]
        md = {"mpris:trackid": GLib.Variant("o", f"/org/muzix/track/{key}"),
              "xesam:title": GLib.Variant("s", it.get("title") or ""),
              "xesam:artist": GLib.Variant("as", [it["artist"]] if it.get("artist") else []),
              "xesam:album": GLib.Variant("s", it.get("album") or "")}
        if float(it.get("duration") or 0) > 0:
            md["mpris:length"] = GLib.Variant("x", int(float(it["duration"]) * US))
        if art := self._cover(it.get("art") or ""):
            md["mpris:artUrl"] = GLib.Variant("s", art)
        return md

    def _cover(self, url: str) -> str:
        """The cover as a file here (the desktop fetches it itself, without the window's login), fetched
        once; the desktop hears of it when it's there."""
        if not url:
            return ""
        if url in self.art:
            return self.art[url]
        self.art[url] = ""
        path = os.path.join(self.dir, hashlib.sha1(url.encode()).hexdigest()[:24] + ".jpg")

        def fetch():
            try:
                if not os.path.exists(path):
                    r = httpx.get(url, headers=self.headers(url), timeout=15)
                    r.raise_for_status()
                    os.makedirs(self.dir, exist_ok=True)
                    with open(path, "wb") as f:
                        f.write(r.content)
                self.art[url] = "file://" + path
                GLib.idle_add(lambda: (self._changed(), False)[1])
            except (httpx.HTTPError, OSError) as e:
                log.info("No cover for the desktop's player (%s)", e)

        threading.Thread(target=fetch, daemon=True).start()
        return ""

    # ------------------------------------------------------------ the desktop hears

    def _changed(self):
        if self.bus is None:
            return
        now = self._props("org.mpris.MediaPlayer2.Player")
        moved = {k: v for k, v in now.items() if k != "Position" and self.sent.get(k) != v}
        # a jump in the song (not its playing on), as MPRIS wants it told
        pos = now["Position"].unpack()
        if abs(pos - self.sent.get("_pos", 0) - self._expected()) > 2 * US:
            self.bus.emit_signal(None, PATH, "org.mpris.MediaPlayer2.Player", "Seeked", GLib.Variant("(x)", (pos,)))
        self.sent["_pos"], self.sent["_at"] = pos, GLib.get_monotonic_time()
        if not moved:
            return
        self.sent.update(moved)
        self.bus.emit_signal(None, PATH, "org.freedesktop.DBus.Properties", "PropertiesChanged",
                             GLib.Variant("(sa{sv}as)", ("org.mpris.MediaPlayer2.Player", moved, [])))

    def _expected(self) -> int:
        """How far the song should have played since the desktop was last told, in microseconds."""
        if self.player.status() != "Playing" or "_at" not in self.sent:
            return 0
        return GLib.get_monotonic_time() - self.sent["_at"]
