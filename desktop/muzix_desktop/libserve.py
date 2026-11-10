"""This computer's library's server (library.py starts it: --library), run before anything of the client's
own is loaded: the client points the server's code at its own settings (shared.py), and the library's
server keeps its in its database. It goes when the app does, even when the app didn't get to stop it:
the app holds the other end of its input, which closes then."""

import os
import threading


def run():
    def app_gone():
        try:
            while os.read(0, 1024):
                pass
        except OSError:         # no input to watch (a console started it by hand)
            return
        os._exit(0)

    threading.Thread(target=app_gone, name="app-gone", daemon=True).start()
    from muzix.__main__ import main
    return main()
