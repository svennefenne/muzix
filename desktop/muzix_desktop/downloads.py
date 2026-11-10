"""What's downloaded to this computer (2.4 in docs/app-plan.md, as android/.../Downloads.kt has it on the
phone): albums, playlists, audiobooks, episodes and the liked songs, each a collection the page hands over
(frontend/src/downloads.ts) with its songs, the page's data and its cover. The songs are files in the data
folder, found by the song's address on the server without the host or the quality, so the player plays
them from here at home, outside and offline alike (player.py). Offline, the pages' data and covers are the
window's answers to the page (relay.py). They come through the window's own server, with its login."""

import hashlib
import json
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from PySide6.QtCore import QObject, Signal

log = logging.getLogger(__name__)


def song_path(url: str) -> str | None:
    """A song's place in the downloads: its address on the server without the host or the quality; a stream
    started part-way (?t=) is the same song."""
    path = urlsplit(url).path
    return path if path.startswith("/api/") else None


def _name(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:24]


class Downloads(QObject):
    changed = Signal()          # what's downloaded, or how far it has come (from any thread)

    def __init__(self, folder: str, headers=lambda url: {}, origin: str = ""):
        super().__init__()
        self.dir = folder
        self.headers = headers              # (url) → what the window's own server wants (relay.py)
        self.origin = origin                # the window's own server, where the page's addresses are
        self.audio = os.path.join(folder, "audio")
        self.art = os.path.join(folder, "art")
        os.makedirs(self.audio, exist_ok=True)
        os.makedirs(self.art, exist_ok=True)
        self.lock = threading.RLock()
        # collections by id ("album:12"): {id, kind, title, subtitle, art, path, pages: {api path: data}, items: [keys]};
        # songs by key ("track:12"): {url, path, file, bytes, state: queued | done | failed}
        self.collections: dict[str, dict] = {}
        self.songs: dict[str, dict] = {}
        try:
            with open(os.path.join(folder, "downloads.json")) as f:
                kept = json.load(f)
            self.collections, self.songs = kept.get("collections", {}), kept.get("songs", {})
        except (OSError, ValueError):
            pass
        self.pool = ThreadPoolExecutor(2, thread_name_prefix="download")
        self.http = httpx.Client(timeout=httpx.Timeout(30, read=120), follow_redirects=True)
        self.resumed = False

    # ------------------------------------------------------------ what the page asks

    def add(self, c: dict):
        """A collection to have here (again: the liked songs change), its songs downloaded now."""
        cid = c.get("id")
        if not cid:
            return
        items = c.get("items") or []
        record = {k: v for k, v in c.items() if k != "items"}
        record["items"] = [it.get("key") for it in items if it.get("key")]
        with self.lock:
            before = self.collections.get(cid)
            self.collections[cid] = record
            new = []
            for it in items:
                key, path = it.get("key"), song_path(it.get("url") or "")
                if not key or not path:
                    continue
                s = self.songs.get(key)
                if s is None or s.get("state") == "failed":     # a failed one tries again
                    self.songs[key] = {"url": it["url"], "path": path, "file": _name(path), "bytes": 0, "state": "queued"}
                    new.append(key)
            self._save()
        for key in new:
            self.pool.submit(self._fetch, key)
        # songs gone from it (a song no longer liked) go, unless another collection has them
        if before:
            self._forget(before.get("items") or [])
        if c.get("art"):
            self.pool.submit(self._keep_art, c["art"])
        self.changed.emit()

    def remove(self, cid: str):
        with self.lock:
            gone = self.collections.pop(cid, None)
            self._save()
        if gone:
            self._forget(gone.get("items") or [])
            self.changed.emit()

    def _forget(self, keys: list[str]):
        with self.lock:
            kept = {k for c in self.collections.values() for k in c.get("items") or []}
            for key in [k for k in keys if k not in kept]:
                s = self.songs.pop(key, None)
                if s:
                    for f in (s["file"], s["file"] + ".part"):
                        try:
                            os.remove(os.path.join(self.audio, f))
                        except OSError:
                            pass
            self._save()

    def list(self) -> list[dict]:
        """Everything downloaded, for the page: each collection with how far it has come and its size."""
        with self.lock:
            out = []
            for c in self.collections.values():
                got = [self.songs[k] for k in c.get("items") or [] if k in self.songs]
                out.append({"id": c.get("id"), "kind": c.get("kind"), "title": c.get("title", ""), "subtitle": c.get("subtitle", ""),
                            "art": c.get("art") or "", "path": c.get("path", ""), "total": len(c.get("items") or []),
                            "done": sum(s["state"] == "done" for s in got), "failed": sum(s["state"] == "failed" for s in got),
                            "bytes": sum(s.get("bytes", 0) for s in got)})
            return out

    # ------------------------------------------------------------ the songs

    def file(self, url: str) -> str | None:
        """The downloaded file of the song at `url`, if it's here."""
        path = song_path(url)
        if not path:
            return None
        with self.lock:
            s = next((s for s in self.songs.values() if s["path"] == path and s["state"] == "done"), None)
        f = s and os.path.join(self.audio, s["file"])
        return f if f and os.path.isfile(f) else None

    def _fetch(self, key: str):
        with self.lock:
            s = self.songs.get(key)
            if not s or s["state"] != "queued":
                return
            url, name = s["url"], s["file"]
        part = os.path.join(self.audio, name + ".part")
        u = urlsplit(url)
        query = urlencode([(k, v) for k, v in parse_qsl(u.query) if k != "t"])     # the whole song, not from part-way
        url = urlunsplit(u._replace(query=query))
        got, state = 0, "failed"
        try:
            with self.http.stream("GET", url, headers=self.headers(url)) as r:
                r.raise_for_status()
                with open(part, "wb") as f:
                    for chunk in r.iter_bytes(1 << 16):
                        if key not in self.songs:      # taken off while it came
                            raise InterruptedError
                        f.write(chunk)
                        got += len(chunk)
            os.replace(part, os.path.join(self.audio, name))
            state = "done"
        except InterruptedError:
            pass
        except (httpx.HTTPError, OSError) as e:
            log.warning("Couldn't download %s: %s", url, e)
        if state != "done":
            try:
                os.remove(part)
            except OSError:
                pass
        with self.lock:
            if key in self.songs:
                self.songs[key].update(state=state, bytes=got if state == "done" else 0)
                self._save()
        self.changed.emit()

    # ------------------------------------------------------------ offline, the pages from here

    def keep_state(self, state: dict):
        """The page's sign-in state, kept so the window opens offline. Signed in, what didn't finish last time
        goes on (the window's own server has the login now)."""
        with open(os.path.join(self.dir, "state.json"), "w") as f:
            json.dump(state, f)
        if not self.resumed:
            self.resumed = True
            with self.lock:
                left = [k for k, s in self.songs.items() if s.get("state") == "queued"]
            for key in left:
                self.pool.submit(self._fetch, key)

    def answer(self, path: str) -> tuple[str, bytes] | None:
        """The answer to a GET of the API while the server can't be reached (`path` with its query), or None."""
        bare = path.split("?")[0]
        if bare == "/api/auth/state":
            try:
                with open(os.path.join(self.dir, "state.json")) as f:
                    state = json.load(f)
            except (OSError, ValueError):
                return None
            return "application/json", json.dumps(dict(state, offline=True)).encode()
        if bare.startswith("/api/art/"):
            f = os.path.join(self.art, _name(bare))
            if os.path.isfile(f):
                with open(f, "rb") as fh:
                    return "image/jpeg", fh.read()
            return None
        with self.lock:
            for c in self.collections.values():
                pages = c.get("pages") or {}
                if path in pages or bare in pages:
                    return "application/json", json.dumps(pages.get(path, pages.get(bare))).encode()
        return None

    def _keep_art(self, art: str):
        bare = art.split("?")[0]
        f = os.path.join(self.art, _name(bare))
        if os.path.isfile(f):
            return
        url = art if "://" in art else self.origin + art
        try:
            r = self.http.get(url, headers=self.headers(url))
            if r.status_code == 200:
                with open(f, "wb") as fh:
                    fh.write(r.content)
        except httpx.HTTPError:
            pass

    def _save(self):
        tmp = os.path.join(self.dir, "downloads.json.tmp")
        with open(tmp, "w") as f:
            json.dump({"collections": self.collections, "songs": self.songs}, f)
        os.replace(tmp, os.path.join(self.dir, "downloads.json"))

    def stop(self):
        self.pool.shutdown(wait=False, cancel_futures=True)
