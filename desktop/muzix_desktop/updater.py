"""Muzix Desktop updates itself when Update the app in the account menu asks (frontend/src/appUpdate.ts),
in the background, opening nothing: it asks GitHub for its newest release (.github/workflows/desktop.yml
publishes them), downloads the file for this system, checks it against GitHub's digest, puts it in and
starts again where it was: the window in its place on the same page, or only in the tray, and what played
playing on from where it was (resume.json, read by the new start: resumed()).

- Linux: the AppImage it runs from is replaced (the running app carries on from the old file until it ends).
- Windows: the installer runs silently for this user, into the folder the app is in.
- macOS: the app in its folder is swapped for the new one.

Run from source, as PyInstaller's bare folder, or from a place it can't write to, it can't update itself,
and says so."""

import base64
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import urlsplit

import httpx
from PySide6.QtCore import QObject, Signal

from . import __version__, config

log = logging.getLogger(__name__)

REPO = "svennefenne/muzix"
# a test's own releases: an address that answers as GitHub's API does
FEED = os.environ.get("MUZIX_UPDATES") or f"https://api.github.com/repos/{REPO}/releases"
FILES = {"linux": "muzix-desktop-linux-x86_64.AppImage", "windows": "muzix-desktop-windows-x64-setup.exe",
         "macos": "muzix-desktop-macos-arm64.zip"}
SYSTEM = "windows" if sys.platform == "win32" else "macos" if sys.platform == "darwin" else "linux"

# the new start, once this app has ended: Linux's AppImage (replaced already) as it is, or macOS' app
# swapped for the new one first (the old one back if that fails)
LINUX = """pid=$1 app=$2; shift 2
while kill -0 "$pid" 2>/dev/null; do sleep 0.2; done
exec "$app" "$@"
"""
MACOS = """pid=$1 app=$2 new=$3 open=$4; shift 4
while kill -0 "$pid" 2>/dev/null; do sleep 0.2; done
rm -rf "$app.old"
if mv "$app" "$app.old"; then
  if mv "$new" "$app"; then rm -rf "$app.old"; else mv "$app.old" "$app"; fi
fi
rm -rf "$(dirname "$new")"
exec "$open" -a "$app" --args "$@"
"""


RESUME = "resume.json"      # in the data folder's update/: what the new start carries on with
FRESH = 10 * 60             # seconds it's good for (a start long after isn't the update's)


def resumed() -> dict | None:
    """What the app was doing when an update started it again (Updater._staged), once: the page it was on
    and what played."""
    path = os.path.join(config.DATA_DIR, "update", RESUME)
    try:
        with open(path, encoding="utf-8") as f:
            kept = json.load(f)
        os.remove(path)
    except (OSError, ValueError):
        return None
    return kept if isinstance(kept, dict) and time.time() - float(kept.get("at") or 0) < FRESH else None


def _version(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in v.split(".") if x.isdigit())


def newest(releases: list[dict], file: str) -> dict | None:
    """{version, url, size, sha256} of the highest desktop-v* release with `file`, drafts and pre-releases
    left out (as the server's backend/muzix/api/android.py finds it)."""
    best = None
    for r in releases:
        m = re.fullmatch(r"desktop-v(\d+(?:\.\d+)*)", r.get("tag_name") or "")
        if not m or r.get("draft") or r.get("prerelease"):
            continue
        asset = next((a for a in r.get("assets") or [] if a.get("name") == file), None)
        if asset and (best is None or _version(m[1]) > _version(best["version"])):
            digest = asset.get("digest") or ""
            best = {"version": m[1], "url": asset.get("browser_download_url") or "", "size": asset.get("size") or 0,
                    "sha256": digest[7:] if digest.startswith("sha256:") else ""}
    return best


def trusted(url: str) -> bool:
    """A release's own file on GitHub (or, in a test, on its stand-in)."""
    if re.fullmatch(rf"https://github\.com/{REPO}/releases/download/desktop-v[\w.-]+/muzix-desktop-[\w.-]+", url):
        return True
    test = urlsplit(os.environ.get("MUZIX_UPDATES") or "")
    return bool(test.netloc) and urlsplit(url)[:2] == test[:2]


def _writable(folder: str) -> bool:
    """Whether this user may put files in `folder` (os.access can't tell on Windows)."""
    try:
        with tempfile.TemporaryFile(dir=folder):
            return True
    except OSError:
        return False


def target() -> str | None:
    """What an update replaces: the AppImage, the installed app's folder (its uninstaller beside it) or the
    app bundle; None where the app doesn't update itself."""
    if SYSTEM == "linux":
        path = os.environ.get("APPIMAGE") or ""
        path = os.path.realpath(path) if path else ""
        return path if path and os.path.isfile(path) and _writable(os.path.dirname(path)) else None
    if not getattr(sys, "frozen", False):
        return None
    exe = sys.executable
    if SYSTEM == "windows":
        folder = os.path.dirname(exe)
        return folder if os.path.isfile(os.path.join(folder, "unins000.exe")) and _writable(folder) else None
    if ".app/Contents/MacOS/" in exe:
        app = exe.split(".app/")[0] + ".app"
        return app if _writable(os.path.dirname(app)) else None
    return None


def child_env(env: dict | None = None) -> dict:
    """The environment of the new start: without what this run added (the AppImage's runtime and mount,
    AppImageLauncher's, PyInstaller's), and with AppImageLauncher asking nothing."""
    env = dict(os.environ if env is None else env)
    gone = [p for p in (env.get("APPDIR"), getattr(sys, "_MEIPASS", None)) if p]
    for k in [k for k in env if k.startswith("_PYI_")] + ["APPIMAGE", "APPDIR", "OWD", "ARGV0", "TARGET_APPIMAGE"]:
        env.pop(k, None)
    if "LD_LIBRARY_PATH_ORIG" in env:        # PyInstaller's bootloader keeps what was there
        env["LD_LIBRARY_PATH"] = env.pop("LD_LIBRARY_PATH_ORIG")
    for k, v in list(env.items()):
        parts = v.split(os.pathsep)
        kept = [p for p in parts if not any(p == g or p.startswith(g.rstrip("/\\") + os.sep) for g in gone)]
        if len(kept) != len(parts):
            if kept:
                env[k] = os.pathsep.join(kept)
            else:
                del env[k]
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"      # a new app, not this one's child
    env["APPIMAGELAUNCHER_DISABLE"] = "1"
    return env


def windows_script(pid: int, setup: str, folder: str, exe: str, args: list[str]) -> str:
    """PowerShell's -EncodedCommand: once this app has ended, the installer silently into its folder, then
    the app again."""
    def q(s: str) -> str:
        return "'" + s.replace("'", "''") + "'"
    silently = '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CURRENTUSER /DIR="' + folder + '"'
    lines = [f"Wait-Process -Id {pid} -Timeout 120 -ErrorAction SilentlyContinue",
             f"Start-Process -FilePath {q(setup)} -ArgumentList {q(silently)} -Wait",
             f"Remove-Item -LiteralPath {q(setup)} -ErrorAction SilentlyContinue",
             f"Start-Process -FilePath {q(exe)}" + (f" -ArgumentList {q(' '.join(args))}" if args else "")]
    return base64.b64encode("\n".join(lines).encode("utf-16-le")).decode()


def download(http: httpx.Client, release: dict, to: str):
    """The release's file to `to`, checked against its size and GitHub's digest; one already there that
    matches the digest is kept."""
    if release["sha256"] and os.path.isfile(to):
        h = hashlib.sha256()
        with open(to, "rb") as f:
            while chunk := f.read(1 << 20):
                h.update(chunk)
        if h.hexdigest() == release["sha256"]:
            return
    part = to + ".part"
    h, got = hashlib.sha256(), 0
    with http.stream("GET", release["url"]) as r:
        r.raise_for_status()
        with open(part, "wb") as f:
            for chunk in r.iter_bytes(1 << 20):
                f.write(chunk)
                h.update(chunk)
                got += len(chunk)
    if (release["size"] and got != release["size"]) or (release["sha256"] and h.hexdigest() != release["sha256"]):
        os.remove(part)
        raise ValueError("the download isn't the release's file")
    os.replace(part, to)


def place_appimage(path: str, appimage: str):
    """The new AppImage where the old one is: renamed over it, so the running app keeps the old file."""
    os.chmod(path, 0o755)
    folder = os.path.dirname(appimage)
    if os.stat(path).st_dev != os.stat(folder).st_dev:
        near = os.path.join(folder, ".muzix-desktop-update")
        shutil.copyfile(path, near)
        os.chmod(near, 0o755)
        os.remove(path)
        path = near
    os.replace(path, appimage)


def unpack_app(zip_path: str, app: str) -> str:
    """macOS: the downloaded app unpacked beside the old one (ditto keeps its links and rights)."""
    stage = os.path.join(os.path.dirname(app), ".muzix-update")
    shutil.rmtree(stage, ignore_errors=True)
    os.makedirs(stage)
    subprocess.run(["/usr/bin/ditto", "-x", "-k", zip_path, stage], check=True, timeout=600)
    os.remove(zip_path)
    found = [n for n in os.listdir(stage) if n.endswith(".app")]
    if not found:
        raise ValueError("the download has no app in it")
    return os.path.join(stage, found[0])


class Updater(QObject):
    staged = Signal(str)            # (from the download's thread) this version is ready to go in
    failed = Signal(str)            # (from it too) what went wrong
    up_to_date = Signal()           # (from it too) there's nothing newer

    def __init__(self, shown, handover, quit, tell=lambda text: None):
        super().__init__()
        self.shown = shown          # () → the window is up (the new start opens it too)
        self.handover = handover    # () → what the new start carries on with: the page, what plays
        self.quit = quit            # ends the app
        self.tell = tell            # (text) → the page shows it
        self.target = target()
        self.dir = os.path.join(config.DATA_DIR, "update")
        self.new_app = ""           # macOS: the new version, unpacked
        self.setup = ""             # Windows: its installer
        self.working = False
        self.going = False
        self.staged.connect(self._staged)
        self.failed.connect(self._failed)
        self.up_to_date.connect(self._newest)

    @property
    def able(self) -> bool:
        return self.target is not None

    def now(self):
        """Update, from the account menu: the new version downloaded in the background, put in and started."""
        if not self.able:
            self.tell("This copy of Muzix Desktop can't update itself: it isn't installed, or it can't write "
                      "to its folder. Install the new version from Muzix's releases on GitHub.")
            return
        if not self.working and not self.going:
            self.working = True
            self.tell("Updating Muzix Desktop in the background. It starts again where it was when it's done.")
            threading.Thread(target=self._work, name="update", daemon=True).start()

    # ------------------------------------------------------------ in the background

    def _work(self):
        try:
            headers = {"User-Agent": f"MuzixDesktop/{__version__}"}
            with httpx.Client(headers=headers, timeout=httpx.Timeout(30, read=120), follow_redirects=True) as http:
                r = http.get(FEED, params={"per_page": 30}, headers={"Accept": "application/vnd.github+json"})
                r.raise_for_status()
                best = newest(r.json(), FILES[SYSTEM])
                if not best or _version(best["version"]) <= _version(__version__):
                    return self.up_to_date.emit()
                if not trusted(best["url"]):
                    raise ValueError(f"its file isn't GitHub's: {best['url']}")
                log.info("Updating Muzix Desktop to %s: downloading it", best["version"])
                os.makedirs(self.dir, exist_ok=True)
                path = os.path.join(self.dir, FILES[SYSTEM])
                download(http, best, path)
            if SYSTEM == "linux":
                place_appimage(path, self.target)
            elif SYSTEM == "macos":
                self.new_app = unpack_app(path, self.target)
            else:
                self.setup = path
            self.staged.emit(best["version"])
        except Exception as e:      # GitHub, the network, the disk
            log.warning("Couldn't update Muzix Desktop: %s", e)
            self.failed.emit(str(e) or type(e).__name__)

    # ------------------------------------------------------------ back here

    def _newest(self):
        self.working = False
        self.tell(f"Muzix Desktop {__version__} is the newest one.")

    def _failed(self, error: str):
        self.working = False
        self.tell(f"Couldn't update Muzix Desktop ({error}). Try Update again in a while.")

    def _staged(self, version: str):
        """The new version in: a little program waits for this one to end, puts it in and starts it."""
        self.working = False
        pid, args = str(os.getpid()), ([] if self.shown() else ["--minimized"])
        if SYSTEM == "linux":
            cmd = ["/bin/sh", "-c", LINUX, "muzix-update", pid, self.target, *args]
        elif SYSTEM == "macos":
            cmd = ["/bin/sh", "-c", MACOS, "muzix-update", pid, self.target, self.new_app, "/usr/bin/open", *args]
        else:
            script = windows_script(int(pid), self.setup, self.target, sys.executable, args)
            cmd = ["powershell.exe", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-EncodedCommand", script]
        try:
            with open(os.path.join(self.dir, RESUME), "w", encoding="utf-8") as f:
                json.dump({"at": time.time(), **self.handover()}, f)
        except (OSError, TypeError, ValueError) as e:      # it starts again all the same, on Home
            log.warning("Couldn't keep where Muzix Desktop was: %s", e)
        try:
            with open(os.path.join(self.dir, "update.log"), "ab") as out:
                kw = ({"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP}
                      if SYSTEM == "windows" else {"start_new_session": True})
                subprocess.Popen(cmd, env=child_env(), stdin=subprocess.DEVNULL, stdout=out, stderr=out, close_fds=True, **kw)
        except OSError as e:
            log.warning("Couldn't start Muzix Desktop %s: %s", version, e)
            self.tell(f"Couldn't start the new Muzix Desktop ({e}). It's there the next time Muzix Desktop starts.")
            return
        log.info("Muzix Desktop %s is in: starting again", version)
        self.going = True
        self.quit()
