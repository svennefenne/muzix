import os
import tempfile

import pytest


@pytest.fixture(autouse=True, scope="session")
def muzix_db():
    """A throwaway database so settings work."""
    d = tempfile.mkdtemp(prefix="muzix-test-")
    os.environ["MUZIX_DATA"] = d
    from muzix import db, env
    env.DATA_DIR = env.Path(d)
    env.DB_PATH = env.DATA_DIR / "muzix.db"
    env.SECRET_FILE = env.DATA_DIR / "secret.key"
    for name in ("CACHE_DIR", "ART_DIR", "PODCAST_DIR", "UPLOAD_DIR", "BEETS_DIR", "SCHEME_DIR", "AVATAR_DIR"):
        setattr(env, name, env.DATA_DIR / name.lower().replace("_dir", ""))
    db.init(f"sqlite:///{env.DB_PATH}")
    # an artist's page asks MusicBrainz for its albums' types (releases.py): not from the tests
    from muzix import releases
    releases.ask_musicbrainz = lambda artist, title: []
    yield
