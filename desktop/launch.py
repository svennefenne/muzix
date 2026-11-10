"""What the built app starts (PyInstaller runs a script, not a package)."""
import sys

if "--library" in sys.argv:
    # this computer's library's server (muzix_desktop/library.py): the server's own code, untouched by the
    # client's (see muzix_desktop/__main__.py)
    from muzix_desktop.libserve import run
    sys.exit(run())

from muzix_desktop.app import main

sys.exit(main())
