# PyInstaller: Muzix Desktop as one folder per platform (an .app on macOS).
#   cd desktop && pyinstaller muzix-desktop.spec
import os
import re
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

here = os.path.abspath(".")
version = re.search(r'__version__ = "(.+?)"', open(os.path.join(here, "muzix_desktop", "__init__.py")).read()).group(1)
backend = os.path.abspath("../backend")
# Muzix's icon: every size drawn for Windows, the big one for the others (made into .icns on a Mac)
icon = os.path.join(here, "muzix_desktop", "assets", "icon.ico" if sys.platform == "win32" else "icon.png")

datas = [(os.path.join(here, "muzix_desktop", "assets"), "muzix_desktop/assets")]
datas += collect_data_files("beetsplug.lastgenre")       # the genre tree the filing rules use
datas += collect_data_files("mediafile")
datas += collect_data_files("certifi")

a = Analysis(
    ["launch.py"],
    pathex=[here, backend],
    datas=datas,
    hiddenimports=["muzix.organize.beetsplug.musicorg", "beetsplug.lastgenre"] + collect_submodules("muzix.meta"),
    # the server's web side isn't needed here
    excludes=["uvicorn", "uvloop", "tkinter", "matplotlib", "IPython", "PySide6.QtQuick", "PySide6.QtQml",
              "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
              "PySide6.Qt3DCore", "PySide6.QtQuick3D", "PySide6.QtMultimedia", "PySide6.QtCharts",
              "PySide6.QtDataVisualization", "PySide6.QtPdf"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="Muzix Desktop" if sys.platform != "linux" else "muzix-desktop",
    console=False,
    icon=icon,
)
coll = COLLECT(exe, a.binaries, a.datas, name="Muzix Desktop" if sys.platform != "linux" else "muzix-desktop")
if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="Muzix Desktop.app",
        icon=icon,
        bundle_identifier="se.svennefenne.muzix-desktop",
        info_plist={"LSUIElement": True, "NSHighResolutionCapable": True,
                    "CFBundleShortVersionString": version, "CFBundleVersion": version},
    )
