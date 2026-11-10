# Muzix Desktop

Muzix on the computer: a window for listening to your Muzix server, which stays in
the system tray (the menu bar on a Mac) when it's closed. It also shares folders on
your computer with the servers you choose, while the computer is on, and it fixes
albums' tags and covers. The tray's menu has:

- **Open Muzix**: the window. Its web interface comes with the app; a small server
  inside it, on 127.0.0.1, serves that and passes everything else on to your Muzix
  server, at its address at home while that answers and its public address
  otherwise (the server's *Public URL*). With no server yet it shows this computer's
  music, asking first for the folder that has it (*Use a Muzix server* there, or the
  user menu's switch, asks for the server's address).
- **Muzix library…**: another server, or this computer's music: the folders in
  *Settings → Sharing*, played with no server at all (Muzix's own server code runs
  inside the app for them, on 127.0.0.1, and never changes the files). With a server
  too, podcasts, radio and Muzix Connect stay the server account's.
- **Fix Metadata & Artwork**: a small window that stays on top. Drop album folders
  on it; each gets suggestions from the sources chosen in Settings, you pick one,
  check how its songs pair with your files and which cover to use, and *Apply*.
  *Undo* puts everything back.
- **Start sharing / Stop sharing**
- **Settings**: shared folders, servers, metadata sources and what may happen to
  the files.
- **Quit**

## Installing

Download the file for your system from the newest `desktop-v…` release on the
[releases page](https://github.com/svennefenne/muzix/releases).

- **Windows**: run `muzix-desktop-windows-x64-setup.exe`. It installs Muzix Desktop
  for you (no administrator needed) with a Start menu entry, and it's uninstalled
  from Windows' list of apps. The installer isn't signed, so Windows may say it
  protected your PC: choose *More info → Run anyway*.
- **macOS** (Apple silicon): unzip `muzix-desktop-macos-arm64.zip` and move
  *Muzix Desktop* to Applications. The app isn't notarized: the first time,
  right-click it and choose *Open*, then *Open* again.
- **Linux**: `muzix-desktop-linux-x86_64.AppImage` is the whole app in one file.
  Make it executable (in the file's properties, or `chmod +x`) and start it. With
  AppImageLauncher installed, it offers to move the file to `~/Applications` and
  add it to the menu. On GNOME, tray icons need the *AppIndicator and
  KStatusNotifierItem Support* extension.

When a newer version is out, the Muzix window's account menu offers *Update the
app*: it downloads the new file for your system in your browser (the server asks
GitHub once an hour). Install it as above, over the old one.

*Settings → Sharing → Start Muzix Desktop minimized when I log in* keeps it
running: at login it opens no window, only its tray icon. The icon is grey while
nobody listens to your music and in colour while someone does; hovering over it
says what plays, on which server, and how much has been sent today.

## Sharing with a server

1. *Settings → Sharing*: add the folders to share. Mark folders of game music and
   tracker modules as VGM.
2. *Settings → Servers → + Add*: the server's address (it must be HTTPS) and its
   sharing code, which its admin finds under *Admin → Library Network*.
3. Give the admin this computer's code, shown at the top of *Servers*. They enter
   it on the server to accept the computer, as admins of two servers do to link.

Then your music is in that server's library while this computer is on, and hidden
while it's off. Nothing on your computer is changed by sharing, and the server
can read only the songs in the shared folders.

## Fix Metadata & Artwork

*Settings → Metadata & artwork* chooses the sources (MusicBrainz with the Cover
Art Archive, Deezer, iTunes, Bandcamp, Discogs, fanart.tv and Brave image search;
the last three need your own key or token). *Settings → Files* says what happens
after the tags are written:

- only tags and artwork change;
- the songs and the album folder are renamed where they are; or
- the album is filed into your library folder as `Genre/Artist/Artist - Year - Album`.

Songs are named `1. Artist - Album - Title (Year)`, like the server names uploads.
A folder that has other music besides the album keeps its name and place.

## Development

```sh
cd desktop
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt pyinstaller pytest
# the window's player is GStreamer, through PyGObject: on Linux the system's (python-gobject and the
# gstreamer plugins), linked into the venv; without it the window plays as a browser does
ln -s /usr/lib/python3.*/site-packages/gi .venv/lib/python3.*/site-packages/
.venv/bin/python -m muzix_desktop          # run it
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests
.venv/bin/pyinstaller muzix-desktop.spec   # build into dist/
```

The desktop workflow packs that: an installer for Windows (Inno Setup,
`packaging/windows/muzix-desktop.iss`), an AppImage for Linux
(`packaging/linux/build-appimage.sh`; the workflow pins appimagetool and the
AppImage runtime by checksum) and the .app zipped for macOS. The installer is installed, checked
and uninstalled again before it's published.

It shares the server's code (`../backend`): reading songs, the metadata sources,
writing tags and filing albums. Its side of the server connection is in
`muzix_desktop/sharing.py`, the server's in `backend/muzix/tunnel.py`. To try it
against a server on this computer over plain http, set
`MUZIX_DESKTOP_INSECURE=1` (it allows `localhost` and `127.0.0.1` only).

Settings live in the user's config folder (`muzix-desktop/settings.json`), the
index of shared songs in the data folder (`muzix-desktop/index.db`).
