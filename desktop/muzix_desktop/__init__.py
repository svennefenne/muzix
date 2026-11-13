"""Muzix Desktop: the Muzix window, for listening to a Muzix server; it also shares folders on this
computer with Muzix servers (the Library Network) and fixes albums' metadata and artwork. It stays in
the system tray."""

__version__ = "0.4.29"


def ensure_streams():
    """Somewhere to write for what writes to stdout and stderr: without a console (the built app for Windows)
    they're None, and logging setups that ask them isatty() fail ("Unable to configure formatter")."""
    import os
    import sys
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))
