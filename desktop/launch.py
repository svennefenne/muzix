"""What the built app starts (PyInstaller runs a script, not a package)."""
import sys

from muzix_desktop.app import main

sys.exit(main())
