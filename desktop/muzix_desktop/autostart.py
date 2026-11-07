"""Starting Muzix Desktop when the user logs in: a Run key on Windows, a LaunchAgent on macOS and an
autostart entry on Linux (freedesktop)."""

import os
import plistlib
import sys

NAME = "Muzix Desktop"
LABEL = "se.svennefenne.muzix-desktop"


def command() -> list[str]:
    """How this program is started: its AppImage, the app itself when it's built, else Python with the package."""
    if os.environ.get("APPIMAGE"):      # an AppImage runs from a new temporary folder each time
        return [os.environ["APPIMAGE"]]
    if getattr(sys, "frozen", False):
        exe = sys.executable
        if sys.platform == "darwin" and ".app/Contents/MacOS/" in exe:
            return ["/usr/bin/open", "-a", exe.split(".app/")[0] + ".app"]
        return [exe]
    return [sys.executable, "-m", "muzix_desktop"]


def _linux_file() -> str:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "autostart", "muzix-desktop.desktop")


def _mac_file() -> str:
    return os.path.expanduser(f"~/Library/LaunchAgents/{LABEL}.plist")


def enabled() -> bool:
    if sys.platform == "win32":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as k:
                winreg.QueryValueEx(k, NAME)
            return True
        except OSError:
            return False
    return os.path.exists(_mac_file() if sys.platform == "darwin" else _linux_file())


def set_enabled(on: bool):
    cmd = command()
    if sys.platform == "win32":
        import subprocess
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0,
                            winreg.KEY_SET_VALUE) as k:
            if on:
                winreg.SetValueEx(k, NAME, 0, winreg.REG_SZ, subprocess.list2cmdline(cmd))
            else:
                try:
                    winreg.DeleteValue(k, NAME)
                except OSError:
                    pass
        return
    path = _mac_file() if sys.platform == "darwin" else _linux_file()
    if not on:
        try:
            os.remove(path)
        except OSError:
            pass
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if sys.platform == "darwin":
        with open(path, "wb") as f:
            plistlib.dump({"Label": LABEL, "ProgramArguments": cmd, "RunAtLoad": True}, f)
    else:
        quoted = " ".join(f'"{c}"' if " " in c else c for c in cmd)
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"[Desktop Entry]\nType=Application\nName={NAME}\nExec={quoted}\nIcon=muzix-desktop\n"
                    "X-GNOME-Autostart-enabled=true\nTerminal=false\n")
