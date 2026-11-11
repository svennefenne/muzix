"""Muzix Desktop updating itself when Update asks (updater.py): the newest release for the system,
downloaded and checked, put in where the app is, and the app started again once it has ended."""
import base64
import hashlib
import os
import signal
import socket
import subprocess
import threading
import time
from types import SimpleNamespace

import httpx
import pytest
import uvicorn
from PySide6.QtCore import QCoreApplication
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from muzix_desktop import __version__, updater

NEW = b"\x7fELF the new Muzix Desktop" * 1000


def _release(tag: str, files: dict[str, bytes], origin: str, **kw) -> dict:
    return {"tag_name": tag, "draft": False, "prerelease": False, **kw,
            "assets": [{"name": n, "size": len(b), "digest": "sha256:" + hashlib.sha256(b).hexdigest(),
                        "browser_download_url": f"{origin}/download/{tag}/{n}"} for n, b in files.items()]}


def _feed(releases, files: dict[str, bytes]) -> tuple[str, uvicorn.Server]:
    """A stand-in for GitHub: its releases, and their files."""
    async def listing(request: Request):
        return JSONResponse(releases(origin))

    async def download(request: Request):
        return Response(files[request.path_params["name"]], media_type="application/octet-stream")

    app = Starlette(routes=[Route("/releases", listing), Route("/download/{tag}/{name}", download)])
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    origin = f"http://127.0.0.1:{s.getsockname()[1]}"
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", lifespan="off"))
    threading.Thread(target=server.run, kwargs={"sockets": [s]}, daemon=True).start()
    for _ in range(50):
        try:
            httpx.get(origin + "/releases", timeout=1)
            break
        except httpx.HTTPError:
            time.sleep(0.1)
    return origin, server


def _until(done, most: float = 10.0):
    end = time.monotonic() + most
    while not done() and time.monotonic() < end:
        time.sleep(0.05)


class _Now:
    """The updater's background work, done at once (its signals then arrive with no event loop)."""

    def __init__(self, target, **kw):
        self.target = target

    def start(self):
        self.target()


def test_the_newest_release_for_the_system():
    o = "https://github.com/svennefenne/muzix/releases"
    linux = updater.FILES["linux"]
    releases = [_release("android-v0.11.0", {"muzix-android.apk": b"apk"}, o),
                _release("desktop-v0.4.10", {linux: b"ten"}, o),
                _release("desktop-v0.4.9", {linux: b"nine"}, o),
                _release("desktop-v0.5.0", {linux: b"draft"}, o, draft=True),
                _release("desktop-v0.6.0", {updater.FILES["windows"]: b"windows only"}, o)]
    best = updater.newest(releases, linux)
    assert best == {"version": "0.4.10", "url": f"{o}/download/desktop-v0.4.10/{linux}", "size": 3,
                    "sha256": hashlib.sha256(b"ten").hexdigest()}
    assert updater.trusted(best["url"])
    assert not updater.trusted("https://example.com/desktop-v0.4.10/" + linux)
    assert not updater.trusted(f"https://github.com/someone/else/releases/download/desktop-v0.4.10/{linux}")
    assert updater.newest(releases, "nothing") is None


def test_the_new_start_leaves_this_runs_folders_behind(monkeypatch):
    monkeypatch.setattr(updater.sys, "_MEIPASS", "/tmp/.mount_muzix1/usr/lib/muzix-desktop/_internal", raising=False)
    env = updater.child_env({"APPIMAGE": "/home/u/Applications/Muzix.AppImage", "APPDIR": "/tmp/.mount_muzix1",
                             "OWD": "/home/u", "ARGV0": "Muzix.AppImage", "HOME": "/home/u", "TARGET_APPIMAGE": "/home/u/Muzix.AppImage",
                             "_PYI_ARCHIVE_FILE": "/tmp/.mount_muzix1/usr/lib/muzix-desktop/muzix-desktop", "_PYI_PARENT_PROCESS_LEVEL": "-1",
                             "PATH": "/tmp/.mount_muzix1/usr/bin:/usr/bin", "LD_LIBRARY_PATH": "/tmp/.mount_muzix1/usr/lib/muzix-desktop/_internal",
                             "LD_LIBRARY_PATH_ORIG": "/opt/lib", "GST_PLUGIN_SYSTEM_PATH_1_0": "/tmp/.mount_muzix1/usr/lib/gst",
                             "QT_QPA_PLATFORMTHEME": "xdgdesktopportal", "XDG_DATA_DIRS": "/tmp/.mount_muzix10/share:/usr/share"})
    assert env == {"HOME": "/home/u", "PATH": "/usr/bin", "LD_LIBRARY_PATH": "/opt/lib", "QT_QPA_PLATFORMTHEME": "xdgdesktopportal",
                   "XDG_DATA_DIRS": "/tmp/.mount_muzix10/share:/usr/share",       # another mount's, not this one's
                   "PYINSTALLER_RESET_ENVIRONMENT": "1", "APPIMAGELAUNCHER_DISABLE": "1"}


def test_windows_runs_the_installer_silently_then_the_app():
    script = base64.b64decode(updater.windows_script(4242, r"C:\Users\Kim's\AppData\Local\muzix-desktop\update\setup.exe",
                                                     r"C:\Users\Kim's\AppData\Local\Programs\Muzix Desktop",
                                                     r"C:\Users\Kim's\AppData\Local\Programs\Muzix Desktop\Muzix Desktop.exe",
                                                     ["--minimized"])).decode("utf-16-le").splitlines()
    assert script == [
        "Wait-Process -Id 4242 -Timeout 120 -ErrorAction SilentlyContinue",
        (r"""Start-Process -FilePath 'C:\Users\Kim''s\AppData\Local\muzix-desktop\update\setup.exe' -ArgumentList """
         r"""'/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CURRENTUSER /DIR="C:\Users\Kim''s\AppData\Local\Programs\Muzix Desktop"' -Wait"""),
        r"Remove-Item -LiteralPath 'C:\Users\Kim''s\AppData\Local\muzix-desktop\update\setup.exe' -ErrorAction SilentlyContinue",
        r"Start-Process -FilePath 'C:\Users\Kim''s\AppData\Local\Programs\Muzix Desktop\Muzix Desktop.exe' -ArgumentList '--minimized'"]


def _waiter():
    """A process that ends when told: the app, as the little program waits for it."""
    return subprocess.Popen(["sleep", "30"])


def test_linux_starts_the_new_appimage_once_the_app_has_ended(tmp_path):
    app = tmp_path / "Muzix Desktop.AppImage"
    app.write_text(f'#!/bin/sh\necho "$@" > "{tmp_path}/started"\n')
    app.chmod(0o755)
    old = _waiter()
    subprocess.Popen(["/bin/sh", "-c", updater.LINUX, "muzix-update", str(old.pid), str(app), "--minimized"])
    time.sleep(0.6)
    assert not (tmp_path / "started").exists()        # not while the app runs
    old.send_signal(signal.SIGTERM)
    old.wait()
    _until(lambda: (tmp_path / "started").exists())
    assert (tmp_path / "started").read_text() == "--minimized\n"


def test_macos_swaps_the_app_for_the_new_one(tmp_path):
    apps = tmp_path / "Applications"
    (apps / "Muzix Desktop.app" / "Contents").mkdir(parents=True)
    (apps / "Muzix Desktop.app" / "Contents" / "version").write_text("0.4.6")
    (apps / ".muzix-update" / "Muzix Desktop.app" / "Contents").mkdir(parents=True)
    (apps / ".muzix-update" / "Muzix Desktop.app" / "Contents" / "version").write_text("0.4.7")
    opener = tmp_path / "open"
    opener.write_text(f'#!/bin/sh\necho "$@" > "{tmp_path}/opened"\n')
    opener.chmod(0o755)
    old = _waiter()
    subprocess.Popen(["/bin/sh", "-c", updater.MACOS, "muzix-update", str(old.pid), str(apps / "Muzix Desktop.app"),
                      str(apps / ".muzix-update" / "Muzix Desktop.app"), str(opener)])
    time.sleep(0.6)
    assert (apps / "Muzix Desktop.app" / "Contents" / "version").read_text() == "0.4.6"
    old.send_signal(signal.SIGTERM)
    old.wait()
    _until(lambda: (tmp_path / "opened").exists())
    assert (apps / "Muzix Desktop.app" / "Contents" / "version").read_text() == "0.4.7"
    assert sorted(os.listdir(apps)) == ["Muzix Desktop.app"]
    assert (tmp_path / "opened").read_text() == f"-a {apps / 'Muzix Desktop.app'} --args\n"


@pytest.mark.skipif(updater.SYSTEM != "linux", reason="the AppImage is Linux's")
def test_update_downloads_the_newer_release_puts_it_in_and_starts_it(tmp_path, monkeypatch):
    QCoreApplication.instance() or QCoreApplication([])
    major, minor, patch = updater._version(__version__)
    linux = updater.FILES["linux"]
    listed, files = {linux: NEW}, {linux: NEW}
    tags = [f"desktop-v{__version__}"]
    origin, server = _feed(lambda o: [_release(t, listed, o) for t in tags], files)
    monkeypatch.setenv("MUZIX_UPDATES", origin + "/releases")
    monkeypatch.setattr(updater, "FEED", origin + "/releases")
    monkeypatch.setattr(updater.config, "DATA_DIR", str(tmp_path / "data"))
    appimage = tmp_path / "Applications" / "Muzix.AppImage"
    appimage.parent.mkdir()
    appimage.write_bytes(b"\x7fELF the old one")
    monkeypatch.setenv("APPIMAGE", str(appimage))
    started, opened = [], []
    monkeypatch.setattr(updater.subprocess, "Popen", lambda cmd, **kw: started.append((cmd, kw)))
    monkeypatch.setattr(updater, "threading", SimpleNamespace(Thread=_Now))
    monkeypatch.setattr(updater, "QDesktopServices", SimpleNamespace(openUrl=lambda url: opened.append(url.toString())))
    url = f"https://github.com/svennefenne/muzix/releases/download/desktop-v{major}.{minor}.{patch + 1}/{linux}"
    shown, ended, told = [False], [], []
    u = updater.Updater(lambda: shown[0], lambda: ended.append(1), told.append)
    assert u.able and u.target == str(appimage)

    # nothing newer: it says so, and nothing happens
    assert u.now(url)
    assert told == ["Downloading the new Muzix Desktop. It starts again by itself when it's done.",
                    f"Muzix Desktop {__version__} is the newest one."]
    assert appimage.read_bytes() == b"\x7fELF the old one" and not started and not ended and not u.working

    # a newer one: downloaded and put in (the running app keeps its own file), then started once this app ends,
    # in the tray as this one was
    tags.append(f"desktop-v{major}.{minor}.{patch + 1}")
    with open(appimage, "rb") as running:
        assert u.now(url)
        assert appimage.read_bytes() == NEW and os.access(appimage, os.X_OK)
        assert running.read() == b"\x7fELF the old one"
    assert not os.path.exists(tmp_path / "data" / "update" / linux)
    (cmd, kw), = started
    assert cmd[:2] == ["/bin/sh", "-c"] and cmd[3:] == ["muzix-update", str(os.getpid()), str(appimage), "--minimized"]
    assert kw["start_new_session"] and kw["env"]["APPIMAGELAUNCHER_DISABLE"] == "1" and "APPIMAGE" not in kw["env"]
    assert ended == [1] and u.going
    assert u.now(url) and len(started) == 1        # only once

    # with the window up, the new one opens it too
    started.clear()
    appimage.write_bytes(b"\x7fELF the old one")
    shown[0] = True
    v = updater.Updater(lambda: shown[0], lambda: ended.append(2), told.append)
    assert v.now(url)
    assert started[0][0][3:] == ["muzix-update", str(os.getpid()), str(appimage)] and ended == [1, 2]

    # a file that isn't the release's (as GitHub's digest says) is left out, and the browser downloads it
    appimage.write_bytes(b"\x7fELF the old one")
    files[linux] = b"something else"
    told.clear()
    w = updater.Updater(lambda: True, lambda: ended.append(3), told.append)
    assert w.now(url)
    assert appimage.read_bytes() == b"\x7fELF the old one" and ended == [1, 2] and opened == [url]
    assert told[-1] == "Couldn't update Muzix Desktop (the download isn't the release's file). The new one downloads in your browser instead."
    server.should_exit = True


def test_where_it_doesnt_update_itself_the_browser_downloads_it(monkeypatch):
    QCoreApplication.instance() or QCoreApplication([])
    monkeypatch.delenv("APPIMAGE", raising=False)
    u = updater.Updater(lambda: False, lambda: None)
    assert not u.able and not u.now("https://github.com/svennefenne/muzix/releases/download/desktop-v9/x")
