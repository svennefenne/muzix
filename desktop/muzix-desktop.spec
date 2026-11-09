# PyInstaller: Muzix Desktop as one folder per platform (an .app on macOS).
#   cd desktop && pyinstaller muzix-desktop.spec
import os
import re
import sys

import importlib.util

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

# the web interface the window shows (relay.py): the frontend's build, without its source maps and the
# older font files (QtWebEngine takes woff2)
web = os.path.abspath("../frontend/dist")
if not os.path.isfile(os.path.join(web, "index.html")):
    sys.exit("The web interface isn't built: cd frontend && npm ci && npm run build")
for root, _dirs, files in os.walk(web):
    for f in files:
        if not f.endswith((".map", ".woff")):
            datas.append((os.path.join(root, f), os.path.join("muzix_desktop", "web", os.path.relpath(root, web))))

# GStreamer from its Python packages (Windows, macOS), as they are: player.py sets their paths at the start
for name in ("gstreamer_libs", "gstreamer_plugins", "gstreamer_python"):
    spec = importlib.util.find_spec(name)
    if spec and spec.submodule_search_locations:
        datas.append((list(spec.submodule_search_locations)[0], name))

a = Analysis(
    ["launch.py"],
    pathex=[here, backend],
    datas=datas,
    hiddenimports=["muzix.organize.beetsplug.musicorg", "beetsplug.lastgenre"] + collect_submodules("muzix.meta")
                  # the window's own server (relay.py) and the speakers (cast.py) load parts of themselves by name
                  + collect_submodules("uvicorn") + collect_submodules("websockets") + collect_submodules("zeroconf")
                  + collect_submodules("pychromecast"),
    # the server's own web side isn't needed here
    excludes=["uvloop", "tkinter", "matplotlib", "IPython", "PySide6.Qt3DCore", "PySide6.QtQuick3D",
              "PySide6.QtMultimedia", "PySide6.QtCharts", "PySide6.QtDataVisualization"],
    noarchive=False,
    # GStreamer from the system (Linux): only what plays sound, not its video, Qt or GTK parts
    hooksconfig={"gstreamer": {"include_plugins": [
        "coreelements", "playback", "typefindfunctions", "app", "audioconvert", "audioresample", "volume", "autodetect",
        "pulseaudio", "pipewire", "alsa", "spectrum", "audiofx", "soup", "curl", "icydemux", "id3demux", "apetag",
        "audioparsers", "ogg", "opus", "opusparse", "vorbis", "flac", "mpg123", "isomp4", "matroska", "wavparse",
        "wavpack", "libav", "aiff", "adaptivedemux2", "hls", "dash", "taglib", "gio"]}},
)
# Qt's parts the window doesn't use, which come along with QtWebEngine's (PyInstaller takes nearly all of
# Qt with it): 3D, charts, multimedia, Quick's controls, QML's imports, and Chromium's languages other
# than English and Swedish
UNUSED = ("3D", "Charts", "DataVisualization", "Graphs", "Labs", "Location", "Multimedia", "Pdf", "Quick3D",
          "QuickControls2", "QuickDialogs2", "QuickEffects", "QuickLayouts", "QuickParticles", "QuickShapes",
          "QuickTemplates2", "QuickTest", "QuickTimeline", "QuickVectorImage", "RemoteObjects", "Scxml", "Sensors",
          "SerialPort", "SerialBus", "ShaderTools", "SpatialAudio", "Sql", "StateMachine", "Test", "TextToSpeech",
          "VirtualKeyboard", "WaylandCompositor", "WebEngineQuick", "WebView", "WebChannelQuick", "QmlDesignSupport",
          "QmlLocalStorage", "QmlXmlListModel", "QmlNetwork", "PositioningQuick", "WebSockets", "Bluetooth", "Nfc",
          "HttpServer", "Protobuf", "Grpc", "Designer", "Help", "UiTools")
unused = re.compile(r"(?:^|[/\\])(?:lib)?Qt6?(?:%s)\w*(?:\.|[/\\]|$)" % "|".join(UNUSED))
qml = re.compile(r"PySide6[/\\]Qt[/\\]qml[/\\]")
locale = re.compile(r"(qtwebengine_locales[/\\](?!en-US|sv)[^/\\]+\.pak|translations[/\\]\w+_(?!sv|en)\w+\.qm)$")
a.binaries = [b for b in a.binaries if not (unused.search(b[0]) or qml.search(b[0]))]
a.datas = [d for d in a.datas if not (unused.search(d[0]) or qml.search(d[0]) or locale.search(d[0]))]

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
        info_plist={"NSHighResolutionCapable": True,     # in the Dock: the Muzix window is the app
                    "CFBundleShortVersionString": version, "CFBundleVersion": version},
    )
