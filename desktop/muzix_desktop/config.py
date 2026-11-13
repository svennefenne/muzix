"""What the client keeps between runs: this computer's id and sharing code, the servers it shares
with, the folders it shares, and how Fix Metadata & Artwork works. One JSON file in the user's
config folder, readable by the user only (it holds the servers' keys)."""

import json
import os
import platform
import secrets
import threading
import uuid
from dataclasses import asdict, dataclass, field

import platformdirs

from . import shared

CONFIG_DIR = platformdirs.user_config_dir("muzix-desktop", appauthor=False)
DATA_DIR = platformdirs.user_data_dir("muzix-desktop", appauthor=False)
PATH = os.path.join(CONFIG_DIR, "settings.json")

# where Fix Metadata & Artwork looks, as on the server (backend/muzix/providers.py)
SOURCES = (
    ("musicbrainz", "MusicBrainz", "Albums and their songs, with covers from the Cover Art Archive"),
    ("deezer", "Deezer", "Albums, songs and large covers"),
    ("itunes", "iTunes", "Albums, songs and large covers"),
    ("bandcamp", "Bandcamp", "Independent releases"),
    ("discogs", "Discogs", "Releases of every edition. Its covers need a personal token"),
    ("fanarttv", "fanart.tv", "Covers in high quality. Needs an API key"),
    ("web", "Web image search", "Brave Search images, when the music sources have no cover. Needs an API key"),
)
KEYS = {"discogs": ("discogs_token", "Discogs personal token"),
        "fanarttv": ("fanarttv_api_key", "fanart.tv API key"),
        "web": ("brave_api_key", "Brave Search API key")}

# what Fix Metadata & Artwork may do with the files
ORGANIZE = {
    "tags": "Only change the tags and artwork, leave every file and folder as it is",
    "rename": "Rename the songs and the album folder where they are",
    "library": "File the album into my library folder: Genre / Artist / Artist - Year - Album",
}


def new_code() -> str:
    """A sharing code, made the way a server makes its own."""
    alphabet = shared.ALPHABET
    return "-".join("".join(secrets.choice(alphabet) for _ in range(5)) for _ in range(4))


@dataclass
class Server:
    address: str                # https://…
    server_id: str
    name: str
    key: str                    # what this computer shows when it connects
    state: str = "waiting"      # waiting (for its admin's yes) | linked | removed
    watch: bool = False         # its admin may pick folders here for its watch folders (sharing.py)
    # the ones picked: the server reads and moves files only in them
    watch_folders: list[str] = field(default_factory=list)


@dataclass
class Folder:
    path: str
    kind: str = "music"         # music | vgm
    share: bool = True          # shared with the servers too (the local library has every folder: library.py)


@dataclass
class Config:
    computer_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    code: str = field(default_factory=new_code)
    name: str = field(default_factory=lambda: platform.node() or "My computer")
    sharing: bool = True
    servers: list[Server] = field(default_factory=list)
    folders: list[Folder] = field(default_factory=list)
    sources: dict[str, bool] = field(default_factory=lambda: {k: k not in ("fanarttv", "web") for k, *_ in SOURCES})
    keys: dict[str, str] = field(default_factory=dict)     # discogs_token, fanarttv_api_key, brave_api_key
    organize: str = "tags"
    library: str = ""           # the library folder ("library")
    embed_cover: bool = True    # the cover into each song too, not only cover.jpg beside them
    autostart: bool = False
    seen_hint: bool = False     # the Fix Metadata window's "check Settings first"
    # the server listened to in the Muzix window (window.py): its address at home and outside
    listen_home: str = ""
    listen_away: str = ""
    window_port: int = 0        # the window's own server on 127.0.0.1 (relay.py): the same each run
    window_geometry: str = ""   # the window's place and size as it was left (Qt's saveGeometry, base64)
    # the library the window shows: the server's, or this computer's folders (library.py)
    library: str = "server"     # server | local
    library_port: int = 0
    library_password: str = ""  # the local library's own account (made the first time, used only here)
    library_token: str = ""

    def server(self, server_id: str) -> Server | None:
        return next((s for s in self.servers if s.server_id == server_id), None)

    def enabled_sources(self) -> set[str]:
        """The sources switched on that can work (the ones that need a key have one)."""
        return {k for k, on in self.sources.items()
                if on and (k not in KEYS or k == "discogs" or self.keys.get(KEYS[k][0]))}


_lock = threading.RLock()
_current: Config | None = None


def load() -> Config:
    global _current
    with _lock:
        if _current is not None:
            return _current
        try:
            with open(PATH, encoding="utf-8") as f:
                raw = json.load(f)
        except (OSError, ValueError):
            raw = {}
        c = Config()
        for k, v in raw.items():
            if k == "servers":
                c.servers = [Server(**{f: s.get(f, "") for f in ("address", "server_id", "name", "key")},
                                    state=s.get("state") or "waiting", watch=s.get("watch") is True,
                                    # before 0.4.24: the one folder picked
                                    watch_folders=[f for f in s.get("watch_folders") or [s.get("watch_folder")]
                                                   if isinstance(f, str) and f]) for s in v]
            elif k == "folders":
                c.folders = [Folder(path=f["path"], kind=f.get("kind") or "music", share=f.get("share", True) is not False)
                             for f in v]
            elif k == "sources":
                c.sources.update({s: bool(on) for s, on in v.items()})
            elif hasattr(c, k):
                setattr(c, k, v)
        _current = c
        if not raw:
            save()
        return c


def save():
    with _lock:
        c = _current
        if c is None:
            return
        os.makedirs(CONFIG_DIR, exist_ok=True)
        tmp = PATH + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(asdict(c), f, indent=2, ensure_ascii=False)
        os.replace(tmp, PATH)
