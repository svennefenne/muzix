"""The apps' newest versions, for Update in the user menu: the highest android-v* release on GitHub
that has the APK (.github/workflows/android.yml publishes them), and the highest desktop-v* release
with Muzix Desktop's file for the computer's system (desktop.yml). GitHub's releases are asked for at
most once an hour; while GitHub can't be reached, the last answer stands and it's asked again in ten
minutes. Check for updates in the apps asks now (`fresh`), at most once a minute."""

import logging
import re
import threading
import time

import httpx
from fastapi import APIRouter, Depends, HTTPException

from .. import enrich, env
from ..models import User
from ..security import current_user

router = APIRouter(prefix="/api/android", tags=["android"])
desktop_router = APIRouter(prefix="/api/desktop", tags=["desktop"])
log = logging.getLogger(__name__)

APK = "muzix-android.apk"
DESKTOP = {"linux": "muzix-desktop-linux-x86_64.AppImage", "windows": "muzix-desktop-windows-x64-setup.exe",
           "macos": "muzix-desktop-macos-arm64.zip"}
FRESH = 3600        # seconds an answer is kept
RETRY = 600         # seconds before GitHub is asked again after it failed
AGAIN = 60          # seconds between two checks someone asked for (GitHub allows 60 an hour)

_lock = threading.Lock()
_latest: list[dict] | None = None     # GitHub's releases, as last heard
_next = 0.0
_asked = 0.0        # when GitHub was last asked


def _version(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in v.split("."))


def newest(releases: list[dict], app: str = "android", file: str = APK) -> dict | None:
    """{version, url} of the highest `app`-v* release with `file`, drafts and pre-releases left out."""
    tag = re.compile(rf"^{app}-v(\d+(?:\.\d+)*)$")
    best = None
    for r in releases:
        m = tag.match(r.get("tag_name") or "")
        if not m or r.get("draft") or r.get("prerelease"):
            continue
        asset = next((a for a in r.get("assets") or [] if a.get("name") == file), None)
        if asset and (best is None or _version(m[1]) > _version(best["version"])):
            best = {"version": m[1], "url": asset["browser_download_url"]}
    return best


def _releases() -> list[dict]:
    headers = {"User-Agent": enrich.UA, "Accept": "application/vnd.github+json"}
    with httpx.Client(headers=headers, timeout=10, follow_redirects=True) as c:
        r = c.get(f"https://api.github.com/repos/{env.APP_REPO}/releases", params={"per_page": 30})
        r.raise_for_status()
        return r.json()


def _known(fresh: bool = False) -> list[dict]:
    """GitHub's releases; `fresh`: asked now (unless it was within the minute), and an error if it can't be."""
    global _latest, _next, _asked
    with _lock:
        if time.time() >= _next or (fresh and time.time() - _asked >= AGAIN):
            _asked = time.time()
            try:
                _latest = _releases()
                _next = time.time() + FRESH
            except (httpx.HTTPError, ValueError, KeyError, TypeError) as e:
                log.warning("Couldn't ask GitHub for the apps' newest versions: %s", e)
                _next = time.time() + RETRY
                if fresh:
                    raise HTTPException(502, "GitHub couldn't be reached to check for updates: try again in a while")
        return _latest or []


def latest() -> dict | None:
    return newest(_known())


@router.get("/latest")
def latest_app(fresh: bool = False, user: User = Depends(current_user)):
    return newest(_known(fresh)) or {"version": None, "url": None}


@desktop_router.get("/latest")
def latest_desktop(platform: str, fresh: bool = False, user: User = Depends(current_user)):
    """Muzix Desktop's newest version for a system: linux, windows or macos."""
    file = DESKTOP.get(platform)
    return (newest(_known(fresh), "desktop", file) if file else None) or {"version": None, "url": None}
