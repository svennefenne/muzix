"""This computer's music as the window's library (step 4 in docs/app-plan.md): Muzix's own server code
(../backend), run here as a process of its own on 127.0.0.1 with a data folder of its own, over the
folders in Settings. It has one account, made the first time and used only by the window (relay.py
signs its requests in with that account's token). It never changes the music files: the window has no
admin pages, and nothing else in the server writes to the library's folders. Game music needs a server
for now, so VGM folders are left to the sharing."""

import getpass
import logging
import os
import secrets
import socket
import subprocess
import sys
import threading
import time

import httpx

from . import config

log = logging.getLogger(__name__)

DIR = os.path.join(config.DATA_DIR, "library")
# what this library does: music (and podcasts and radio while there's no server: step 6); game music,
# audiobooks and the Library Network need a server for now
MODULES = {"vgm": False, "audiobooks": False, "network": False, "podcasts": True, "radio": True}


def _command() -> list[str]:
    """This app again, as the library's server (--library: __main__.py, launch.py)."""
    if getattr(sys, "frozen", False):
        return [sys.executable, "--library"]
    return [sys.executable, "-m", "muzix_desktop", "--library"]


class Library:
    def __init__(self, cfg: config.Config):
        self.cfg = cfg
        self.proc: subprocess.Popen | None = None
        self.port = 0
        self.ready = threading.Event()

    @property
    def address(self) -> str:
        return f"http://127.0.0.1:{self.port}" if self.port else ""

    @property
    def token(self) -> str:
        return self.cfg.library_token

    # ------------------------------------------------------------ the process

    def start(self, then=None):
        """The library's server, if it isn't running; then() (from another thread) once it answers and
        is signed in."""
        if self.proc is not None and self.proc.poll() is None:
            if then:
                threading.Thread(target=lambda: (self.ready.wait(60), then()), daemon=True).start()
            return
        self.ready.clear()
        self.port = self._port()
        os.makedirs(DIR, exist_ok=True)
        env = dict(os.environ, MUZIX_DATA=DIR, MUZIX_HOST="127.0.0.1", MUZIX_PORT=str(self.port),
                   MUZIX_DEFAULT_ROOTS="", MUZIX_STATIC=os.path.join(DIR, "no-web-pages"))
        log_file = open(os.path.join(DIR, "server.log"), "ab")
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        # its input stays open while this app runs (libserve.py)
        self.proc = subprocess.Popen(_command(), env=env, stdin=subprocess.PIPE, stdout=log_file, stderr=subprocess.STDOUT,
                                     creationflags=flags)
        log.info("The local library starts on port %d", self.port)

        def up():
            try:
                self._wait()
                self._sign_in()
                self.sync()
                self.ready.set()
            except Exception:
                log.exception("The local library didn't start")
                return
            if then:
                then()

        threading.Thread(target=up, name="library", daemon=True).start()

    def stop(self):
        p, self.proc = self.proc, None
        self.ready.clear()
        if p is not None and p.poll() is None:
            p.terminate()
            try:
                p.wait(10)
            except subprocess.TimeoutExpired:
                p.kill()

    def _port(self) -> int:
        """The same port as last time if it's free (the window keeps nothing by it, but logs read better)."""
        for port in (self.cfg.library_port, 0):
            s = socket.socket()
            try:
                s.bind(("127.0.0.1", port))
                port = s.getsockname()[1]
            except OSError:
                continue
            finally:
                s.close()
            if port != self.cfg.library_port:
                self.cfg.library_port = port
                config.save()
            return port
        raise OSError("No port for the local library")

    def _wait(self, seconds: float = 60):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if self.proc is None or self.proc.poll() is not None:
                raise RuntimeError(f"The local library's server stopped (see {os.path.join(DIR, 'server.log')})")
            try:
                if httpx.get(self.address + "/api/health", timeout=2).json().get("ok"):
                    return
            except (httpx.HTTPError, ValueError):
                pass
            time.sleep(0.3)
        raise TimeoutError("The local library's server didn't answer")

    # ------------------------------------------------------------ its account

    def _api(self, method: str, path: str, **kw) -> httpx.Response:
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        return httpx.request(method, self.address + path, headers=headers, timeout=30, **kw)

    def _sign_in(self):
        """The library's own account: made the first time (with its setup: the modules), signed in after."""
        with config._lock:
            if self.token and self._api("GET", "/api/me").status_code == 200:
                return
            state = httpx.get(self.address + "/api/auth/state", timeout=10).json()
            name = getpass.getuser() or "me"
            if state.get("needs_setup"):
                self.cfg.library_password = secrets.token_urlsafe(24)
                c = httpx.Client(base_url=self.address, timeout=30)
                c.post("/api/auth/setup", json={"username": name, "password": self.cfg.library_password,
                                                "device": "Muzix window"}).raise_for_status()
                c.post("/api/setup/finish", json={"folders": [], "modules": MODULES, "settings": {}}).raise_for_status()
            r = httpx.post(self.address + "/api/auth/token", timeout=30, json={
                "username": name, "password": self.cfg.library_password, "device": "Muzix window"})
            r.raise_for_status()
            self.cfg.library_token = r.json()["token"]
            config.save()

    # ------------------------------------------------------------ its folders

    def sync(self):
        """The library's folders as Settings has them: added, and gone (the files stay where they are)."""
        if not self.address or not self.token:
            return
        want = {os.path.normpath(f.path) for f in self.cfg.folders if f.kind == "music"}
        have = {r["path"]: r["id"] for r in self._api("GET", "/api/admin/roots").json() if r.get("kind") == "music"}
        for path in want - set(have):
            r = self._api("POST", "/api/admin/roots", json={"path": path, "kind": "music"})
            if r.status_code not in (200, 409):
                log.warning("The local library didn't take %s: %s", path, r.text[:200])
        for path in set(have) - want:
            self._api("DELETE", f"/api/admin/roots/{have[path]}")

    # ------------------------------------------------------------ into the account (step 6)

    def move_to_account(self, server: str, session: str) -> int:
        """Podcasts and stations kept here while there was no server, into the account on `server` (signed in
        with `session`): each one the server takes is gone from here, so nothing moves twice. How many moved."""
        if not os.path.exists(os.path.join(DIR, "muzix.db")) or not self.cfg.library_password:
            return 0
        started = self.proc is None or self.proc.poll() is not None
        if started:
            self.start()
        moved = 0
        try:
            if not self.ready.wait(60):
                return 0
            account = httpx.Client(base_url=server, timeout=60, headers={"Cookie": f"muzix_session={session}"})
            for feed in self._api("GET", "/api/podcasts").json():
                if account.post("/api/podcasts", json={"url": feed["url"]}).status_code == 200:
                    self._api("DELETE", f"/api/podcasts/{feed['id']}")
                    moved += 1
            for st in self._api("GET", "/api/radio/stations").json():
                body = {k: st.get(k) or (0 if k == "bitrate" else "") for k in
                        ("name", "url", "uuid", "homepage", "favicon", "tags", "country", "codec", "bitrate")}
                if account.post("/api/radio/stations", json=body).status_code == 200:
                    self._api("DELETE", f"/api/radio/stations/{st['id']}")
                    moved += 1
        except (httpx.HTTPError, ValueError, KeyError) as e:
            log.warning("Moving podcasts and stations into the account stopped: %s", e)
        finally:
            if started and self.cfg.library != "local":
                self.stop()
        if moved:
            log.info("Moved %d podcasts and stations into the account on %s", moved, server)
        return moved

    def rescan(self):
        if self.ready.is_set():
            threading.Thread(target=lambda: self._api("POST", "/api/admin/scan", json={}), daemon=True).start()
