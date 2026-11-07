"""What the client has in common with the server (backend/muzix): how a song is read, where
metadata and covers are found, how tags are written and how an album is named and filed. The
server keeps its settings in its database; here the few the shared code asks for come from the
client's own (config.py, given with use_keys)."""

import os

import platformdirs

# the server's code keeps its scratch files under MUZIX_DATA (chiptunes read through a temp folder)
_scratch = os.path.join(platformdirs.user_cache_dir("muzix-desktop", appauthor=False), "server")
os.environ.setdefault("MUZIX_DATA", _scratch)

from muzix import env, formats, manage, network, providers, scanner, settings  # noqa: E402
from muzix.meta import tags, tagwrite  # noqa: E402

for _d in (env.DATA_DIR, env.CACHE_DIR):
    os.makedirs(_d, exist_ok=True)

ALPHABET = network.ALPHABET
clean_code = network.clean_code
PROTOCOL = network.PROTOCOL

_keys: dict[str, str] = {}


def use_keys(keys: dict[str, str]):
    """The API keys of the metadata sources, as set in the client."""
    _keys.clear()
    _keys.update({k: v for k, v in keys.items() if v})


def _setting(key: str):
    if key in ("discogs_token", "fanarttv_api_key", "brave_api_key"):
        return _keys.get(key, "")
    return settings.spec(key).default


settings.get = _setting

__all__ = ["formats", "manage", "providers", "scanner", "tags", "tagwrite", "use_keys", "ALPHABET", "clean_code",
           "PROTOCOL"]
