"""The parts of Muzix a server can do without, each a module that's on or off for the whole
server (Admin → Modules, or the setup on a new server). Music is Muzix itself and never off.

A module that's off is out of sight, not gone: its pages and requests answer that it's off,
whatever it holds is left out of every list (db.py), and its background work waits. Turned on
again, everything is back as it was."""

from dataclasses import dataclass

from fastapi import HTTPException

from . import settings


@dataclass(frozen=True)
class Module:
    key: str
    label: str
    about: str
    kinds: tuple[str, ...] = ()       # the library folders it scans (Root.kind)
    settings: tuple[str, ...] = ()    # its settings (settings.SCHEMA), the ones the setup asks first
    more: tuple[str, ...] = ()        # its settings that the setup tucks away under "More"


MODULES = (
    Module("vgm", "VGM", "Chiptunes and tracker music from your folders, and the online archives: "
           "HVSC, Modland, VGMRips, ZXArt and more.", kinds=("vgm",),
           settings=("chip_loop_mode", "chip_loops", "chip_length", "modarchive_api_key"),
           more=("chip_fade", "chip_max_length", "module_repeats", "sid_songlengths", "soundfont")),
    Module("audiobooks", "Audiobooks", "Audiobooks from your folders, with chapters, and each listener's "
           "place kept.", kinds=("audiobooks",)),
    Module("podcasts", "Podcasts", "Podcast feeds to follow, with new episodes on the home page.",
           settings=("podcast_refresh_hours", "podcast_keep_days")),
    Module("radio", "Radio", "Internet radio stations from all over the world (radio-browser.info).",
           settings=("radio_country",)),
    Module("network", "Library Network", "Link with friends' Muzix servers and share your libraries: their "
           "music plays here, yours there."),
)
BY_KEY = {m.key: m for m in MODULES}
# the settings that belong to a module: the admin's Settings page leaves them to Admin → Modules
OWNER = {key: m.key for m in MODULES for key in (*m.settings, *m.more)}


def setting(key: str) -> str:
    return f"module_{key}"


def on(key: str) -> bool:
    return bool(settings.get(setting(key)))


def states() -> dict[str, bool]:
    return {m.key: on(m.key) for m in MODULES}


def off() -> set[str]:
    return {m.key for m in MODULES if not on(m.key)}


def kinds() -> set[str]:
    """The kinds of library folder scanned: music's, and those of the modules that are on."""
    return {"music", *(k for m in MODULES if on(m.key) for k in m.kinds)}


def needed(key: str):
    """A FastAPI dependency: the request is for a module that's on."""
    label = BY_KEY[key].label

    def check():
        if not on(key):
            raise HTTPException(404, f"The {label} module is turned off on this server")
    return check
