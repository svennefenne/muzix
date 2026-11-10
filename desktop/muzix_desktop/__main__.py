import sys

if "--library" in sys.argv:
    # this computer's library's server (library.py), before anything of the client's own: the client points
    # the server's code at its own settings (shared.py), and the library's server keeps its in its database
    from .libserve import run
    sys.exit(run())

from .app import main

sys.exit(main())
