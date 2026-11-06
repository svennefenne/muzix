"""The Android app's newest version, for its Update in the user menu: the highest android-v*
release on GitHub that has the APK (.github/workflows/android.yml publishes them). Asked for at
most once an hour; while GitHub can't be reached, the last answer stands and it's asked again
in ten minutes."""

import logging
import re
import threading
import time

import httpx
from fastapi import APIRouter, Depends

from .. import enrich, env
from ..models import User
from ..security import current_user

router = APIRouter(prefix="/api/android", tags=["android"])
log = logging.getLogger(__name__)

APK = "muzix-android.apk"
TAG = re.compile(r"^android-v(\d+(?:\.\d+)*)$")
FRESH = 3600        # seconds an answer is kept
RETRY = 600         # seconds before GitHub is asked again after it failed

_lock = threading.Lock()
_latest: dict | None = None
_next = 0.0


def _version(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in v.split("."))


def newest(releases: list[dict]) -> dict | None:
    """{version, url} of the highest android-v* release with the APK, drafts and pre-releases left out."""
    best = None
    for r in releases:
        m = TAG.match(r.get("tag_name") or "")
        if not m or r.get("draft") or r.get("prerelease"):
            continue
        asset = next((a for a in r.get("assets") or [] if a.get("name") == APK), None)
        if asset and (best is None or _version(m[1]) > _version(best["version"])):
            best = {"version": m[1], "url": asset["browser_download_url"]}
    return best


def _releases() -> list[dict]:
    headers = {"User-Agent": enrich.UA, "Accept": "application/vnd.github+json"}
    with httpx.Client(headers=headers, timeout=10, follow_redirects=True) as c:
        r = c.get(f"https://api.github.com/repos/{env.APP_REPO}/releases", params={"per_page": 30})
        r.raise_for_status()
        return r.json()


def latest() -> dict | None:
    global _latest, _next
    with _lock:
        if time.time() >= _next:
            try:
                _latest = newest(_releases())
                _next = time.time() + FRESH
            except (httpx.HTTPError, ValueError, KeyError, TypeError) as e:
                log.warning("Couldn't ask GitHub for the Android app's newest version: %s", e)
                _next = time.time() + RETRY
        return _latest


@router.get("/latest")
def latest_app(user: User = Depends(current_user)):
    return latest() or {"version": None, "url": None}
