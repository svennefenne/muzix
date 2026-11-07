# Muzix Desktop

A small app for people who listen on someone else's Muzix server but want to add
their own music to it: it shares folders on your computer with the servers you
choose, while the computer is on, and it fixes albums' tags and covers. It runs in
the background, from an icon in the system tray (the menu bar on a Mac):

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

- **Windows**: unzip `muzix-desktop-windows-x64.zip` somewhere (Documents, say)
  and start `Muzix Desktop.exe` in it. The app isn't signed, so Windows may say it
  protected your PC: choose *More info → Run anyway*.
- **macOS** (Apple silicon): unzip `muzix-desktop-macos-arm64.zip` and move
  *Muzix Desktop* to Applications. The app isn't notarized: the first time,
  right-click it and choose *Open*, then *Open* again.
- **Linux**: unpack `muzix-desktop-linux-x86_64.tar.gz` and start
  `muzix-desktop/muzix-desktop`. On GNOME, tray icons need the *AppIndicator and
  KStatusNotifierItem Support* extension.

*Settings → Sharing → Start Muzix Desktop when I log in* keeps it running.

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
.venv/bin/python -m muzix_desktop          # run it
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests
.venv/bin/pyinstaller muzix-desktop.spec   # build into dist/
```

It shares the server's code (`../backend`): reading songs, the metadata sources,
writing tags and filing albums. Its side of the server connection is in
`muzix_desktop/sharing.py`, the server's in `backend/muzix/tunnel.py`. To try it
against a server on this computer over plain http, set
`MUZIX_DESKTOP_INSECURE=1` (it allows `localhost` and `127.0.0.1` only).

Settings live in the user's config folder (`muzix-desktop/settings.json`), the
index of shared songs in the data folder (`muzix-desktop/index.db`).
