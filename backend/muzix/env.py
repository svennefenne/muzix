"""Process environment: where Muzix keeps its data and how it is served.

Everything a user changes at runtime lives in the database (see settings.py);
this module only covers what has to be known before the database exists.
"""

import os
from pathlib import Path

DATA_DIR = Path(os.environ.get("MUZIX_DATA", "/config")).resolve()
HOST = os.environ.get("MUZIX_HOST", "0.0.0.0")
PORT = int(os.environ.get("MUZIX_PORT", "8080"))
STATIC_DIR = Path(os.environ.get("MUZIX_STATIC", Path(__file__).parent / "static"))
# Folders offered as library roots on first run (the Docker image mounts them)
DEFAULT_ROOTS = os.environ.get("MUZIX_DEFAULT_ROOTS", "/music:music,/vgm:vgm,/audiobooks:audiobooks")
SOUNDFONT = os.environ.get("MUZIX_SOUNDFONT", "/usr/share/sounds/sf2/FluidR3_GM.sf2")
DEV = os.environ.get("MUZIX_DEV") == "1"

DB_PATH = DATA_DIR / "muzix.db"
CACHE_DIR = DATA_DIR / "cache"          # rendered/transcoded audio
ART_DIR = DATA_DIR / "art"              # resized cover art
PODCAST_DIR = DATA_DIR / "podcasts"     # downloaded episodes
UPLOAD_DIR = DATA_DIR / "uploads"       # staging area for the upload pipeline
BEETS_DIR = DATA_DIR / "beets"          # beets config/db used by uploads
SECRET_FILE = DATA_DIR / "secret.key"


def ensure_dirs():
    for d in (DATA_DIR, CACHE_DIR, ART_DIR, PODCAST_DIR, UPLOAD_DIR, BEETS_DIR):
        d.mkdir(parents=True, exist_ok=True)


def secret_key() -> bytes:
    """A per-install signing key, created on first start."""
    ensure_dirs()
    if not SECRET_FILE.exists():
        SECRET_FILE.write_bytes(os.urandom(48))
        SECRET_FILE.chmod(0o600)
    return SECRET_FILE.read_bytes()
