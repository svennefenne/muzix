# PyInstaller: Muzix Desktop as one folder per platform (an .app on macOS).
#   cd desktop && pyinstaller muzix-desktop.spec
import os
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

here = os.path.abspath(".")
backend = os.path.abspath("../backend")
icon = os.path.join(here, "muzix_desktop", "assets", "icon.png")

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
                    "CFBundleShortVersionString": os.environ.get("MUZIX_DESKTOP_VERSION", "0.1.0")},
    )
