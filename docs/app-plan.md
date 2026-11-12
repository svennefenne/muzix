# The Muzix app: plan

Agreed on 2026-11-09. Today Muzix is a server with a web player, plus an Android shell around that web
player and a desktop tray client that shares folders. It becomes two things:

- **The server** (the Docker container): the music file manager and library, and a web version of the app.
- **The Muzix app** (Android, Linux, Windows and Mac; iOS later): plays from a server, or from a local
  library on the phone or computer with no server at all.

The Muzix Library Network works as it does today.

## The server

- Its role is the music files and the library. The web UI does what Admin does today for everything to do
  with the files: overview, folders, upload, tags, edits, hidden & trash, network, modules, jobs, users, and
  the server's settings (scan, transcode, chiptune loops, podcasts and radio, metadata keys).
- It serves a web version of the app, built from the same React code. Admin mode (the cogs) and the Admin
  page are in the web version only.
- Appearance (the default colour scheme, genre skins, the skin map) moves to the app's settings.
- **Spotify goes, entirely**: the module, the web player, the client id in Settings and Setup, the stored
  Spotify logins, Spotify as a source in Edit metadata and for artist pictures and covers.
- New: **device logins** (each signed-in device listed on the account, each can be signed out) and an
  **API version** the apps check.

## The app

- The same React UI everywhere. It always talks to "a Muzix API": a server's, or a local one inside the app.
- One library at a time: a saved server, or "this device".
  - A server has a home address (10.9.77.15:8484, unencrypted, accepted) and an outside one; the app uses
    the home one while it answers.
  - Signing in takes the address, username and password, and gives the device its own login.
- Settings are stored per device. The password and "music from linked servers" stay on the account. The
  first sign-in after the upgrade copies the account's current settings to the device.
- **On the account (the server)**: likes, playlists and history for the server's music; podcasts and radio,
  always, even while the local library is on; Muzix Connect across phone, desktop app and web.
- **In the local library**: likes, playlists and history for local music, and the same pages as the server.
  - Genres come from the files' tags.
  - Covers, artist pictures and lyrics come from Deezer, MusicBrainz and LRCLIB and are only shown: the
    files aren't changed.
- **Downloads**: albums, playlists, audiobooks and episodes, and liked songs automatically if wanted.
  - As the original, or smaller (Opus, about 160 kbit/s): smaller on the phone and original on the computer
    to begin with.
  - Game music downloads as the server renders it.
  - Offline, the app shows only what's downloaded.
- Casting works with local music too: the app serves the file to the speaker over the network.
- Admins get "Edit on the server": the web version's admin for that item.
- With no server at all: podcasts and radio are kept in the app and move into the account at a later
  sign-in. Game music and the online archives need a server for now.
- Versions: the server says its API version. An app that is too old asks to be updated; a server that is
  too old, and the app says what's missing.

### Android

- Today's Kotlin app grows: the UI comes inside the app, and Media3 plays, casts and downloads.
- The new app upgrades the old one in place (same package, same signing key).
- The local library is written in Kotlin: you pick folders (the system's folder picker) and the app reads
  the tags itself, not through the phone's media index.
- The phone doesn't share its music to the network.

### The computer

- Muzix Desktop (Python and Qt) grows, and replaces the tray client. The tray icon stays.
- Its own player: gapless, every format without converting, and it feeds the visualizer. The candidate is
  GStreamer (playbin3, with a spectrum element; wheels for Windows and macOS since 1.28).
- The local library runs Muzix's own backend code locally. Casting through pychromecast.
- One list of folders, each with a "share to the network" switch. Fix Metadata stays.
- **The window's UI is still open.** The user wants to stay away from Chromium where possible because of
  tearing and flicker while scrolling (NVIDIA, niri on Wayland). Three tests decide it:
  1. Muzix in Chromium with niri's `wait-for-frame-completion-before-queueing`.
  2. discord.com/app in Chromium against Vesktop.
  3. Muzix in Firefox.

  If only Muzix's heavy pages flicker, in Firefox too, it's Muzix's own effects: fix those (the web
  version gains too) and use QtWebEngine. If the artifacts stay with QtWebEngine as well, the UI becomes
  Qt Quick (QML), a second UI to keep up beside React. WebView2 (Chromium) on Windows is fine either way.

### Color schemes of your own

The user's own schemes, as in Hooden (decided 2026-11-10; api/schemes.py, theme/schemes.ts, pages/SchemeEditor.tsx):
made from any scheme, with colours for the dark and the light version (or one of them), the titles' and
the rest's fonts, titles in capitals or not, a genre skin's lettering, corners, glass, a frame, a backdrop
and a picture (one for phones too, darkened and blurred as wished). The whole app shows it while it's
made. They're the account's, on every device; a device uses one as its scheme ("custom:<id>"), kept in
the browser for the first paint, and it shows when no genre skin does. Shared, everyone on the server can
use it or copy it to change. With the app's own library they come from the server (an account path), and
with no server there are none yet. The server keeps only colours, the app's own names, numbers in their
ranges and pictures uploaded to it (WebP, at most 2560 px), since they're drawn on other people's devices.

### Distribution

GitHub releases as today, with an in-app notice of new versions. Google Play maybe later.

## Order

1. The server's groundwork, Spotify out (below).
2. Android against a server: the UI in the app, settings per device (Appearance among them), downloads,
   Connect.
3. The computer against a server: casting, media keys, Connect.
4. The local library on the computer.
5. The local library on Android.
6. Podcasts and radio with no server.
7. The visualizer on Android: the player's spectrum sent to the UI.

Supporter: a small step of its own after 2 (where Appearance moves into the app), once the price and the
shop are decided (below).

Later: game music with no server, the computer first (ZXTune is native everywhere; UADE is Unix only;
GPL engines inside the app make the app GPL). iOS. Google Play.

## Step 3 in detail

The computer against a server. Muzix Desktop (the tray app) gets a window.

### 3.1 The window

- A window with the app's own web interface (it comes with the app), shown by QtWebEngine.
- A small server inside the app, on 127.0.0.1, serves the interface and passes `/api/…` and the
  Connect socket on to the Muzix server; the login cookie stays with the window. Only the window may
  use it (a secret cookie for each run).
- The first start asks for the server's address, as the Android app does; at home and away as there
  (the server's public address). The sign-in names the computer.
- Closing the window leaves Muzix in the tray; the tray's menu opens it again. Admin opens the web
  version in the browser.

### 3.2 The player

- The app plays, not the page: the page hands over the queue as it does to the Android app (the same
  messages). Gapless, every format as it is.
- GStreamer (playbin3) everywhere (decided 2026-11-09). Its Python packages: macOS has them (1.28),
  Windows only as a preview (1.29, until 1.30 is out), Linux none: there it's the system's GStreamer.
  Linux first.
- The visualizer gets the player's spectrum.
- Seeks one after another (+15 again and again) are one, made 0.4 s after the last; meanwhile the player
  says it's there already, so the next +15 counts from it (0.4.22).
- A song that says it plays but stands still for 5 s (not buffering) is started again where it stood,
  its sound output new; after three tries that don't play on, it pauses and says it couldn't play
  (0.4.22). On 2026-11-12 the AppImage (GStreamer 1.20 and PulseAudio 15.99 from Ubuntu 22.04) on
  PipeWire 1.6.11 stood still after +15 five times in seven seconds: PipeWire logged OVERFLOW at each,
  its buffer for the app stayed empty and the stream waited, until the app was restarted. Not
  reproduced since, with the same libraries.

### 3.3 Media keys and the system's player

MPRIS on Linux, the media overlay on Windows, Now Playing on macOS: what plays, and the keys.

### 3.4 Casting

The Cast button lists the speakers on the network (pychromecast); the queue goes to the speaker with
its signed links, as from Chrome. The volume is the speaker's own while it plays (0.4.20): the slider
shows it, connecting doesn't change it, and the window's own comes back when the speaker is let go. Each
command waits for the speaker's answer, so the ones waiting are kept few: a new volume or place in the
song replaces one still waiting, and Stop casting goes before everything (until 0.4.19 a slider dragged
sent every step, a second apiece, and a stop waited behind them).

### 3.5 Packaging

The AppImage, the Windows installer and the Mac app with QtWebEngine and the player; the desktop build
builds the web interface first.

- Linux: PyGObject built against the build machine's GStreamer; PyInstaller takes the plugins that play
  sound (`hooksconfig` in muzix-desktop.spec), and the app points GStreamer at those only.
- Windows and macOS: GStreamer's own Python packages, packed as they are; the app sets their paths before
  GStreamer loads (player.py).
- Qt's parts the window doesn't use are left out (3D, charts, Quick's controls, QML, most languages).
- TLS trusts certifi's certificates, which go along with the app, not the system's: the AppImage's OpenSSL
  looks where Ubuntu keeps them (/usr/lib/ssl), which Arch and CachyOS don't have. Until 0.4.20 the
  window's sockets (Muzix Connect) didn't, so there the app never joined the account's devices.
- `--check` (run on each build) asks for the web interface, QtWebEngine, GStreamer with the decoders of
  the common formats, the Cast speakers' library and the system's media controls.

### 3.6 Downloads (0.4.0)

As on the phone (2.4): the page hands over a collection and downloads.py keeps its songs as files in the
data folder, through the window's own server with its login, and its page's data and cover. The player
plays a song from its file whenever it's there, by its address on the server without the host or the
quality (from part-way too: the file, from there); this computer's own library, under the same
addresses, is never looked up. When neither address answers, the window's server answers for the server
with what's downloaded (the sign-in state, the pages, the covers) and says so to the page, looking again
every 30 seconds. The original files by default; no wifi setting.

### 3.7 Updates (0.4.6)

Update the app in the account menu (shown when the server says a newer version is out; until then the
menu has Check for updates, which has the server ask GitHub there and then, from 0.4.16) is all the user
does; the app does the rest in the background and opens nothing (updater.py). It asks GitHub for its
newest release, downloads the file for its system (checked against GitHub's digest and size), and a
small program waits for the app to end, puts the new version in and starts it again. The new start
carries on where the old one was (0.4.8): resume.json in the data folder has the page and what played
(the queue, where in the song, playing or not), the window keeps its place and size (saved on every
quit), and it comes back in the tray only if that's where it was. The queue goes to the page with its
hello, then plays on. Nothing happens before Update is chosen; a copy that can't update itself says so.

- Linux: the AppImage file is replaced by renaming over it; the running app carries on from the old
  file until it ends. The new start gets the environment without the old mount's paths and
  PyInstaller's, and with AppImageLauncher asking nothing.
- Windows: the installer runs with /VERYSILENT /CURRENTUSER into the app's own folder, then the app starts.
- macOS: the zip is unpacked beside the app (ditto), and the app is swapped for it.
- Run from source, as PyInstaller's bare folder, or where it can't write: it says it can't.

## Step 4 in detail

This computer's music in Muzix Desktop, with no server, or beside one.

- Muzix's own server code runs as a process of the app's (library.py), on 127.0.0.1, with a data
  folder of its own, over the folders in Settings (one list: each also has a Share switch for the
  servers). Game music needs a server for now, so VGM folders are for sharing only.
- It has one account, made the first time (named after the computer's user) and used only by the app;
  the window's own server (relay.py) signs its requests in with that account's token.
- With a server too, what's the account's stays the server's: podcasts, radio, the account's devices and
  Muzix Connect (relay.py's ACCOUNT); the rest is this computer's: the library, its likes, playlists
  and history.
- It never changes the music files: the window has no admin pages, and nothing else in the server writes
  to the library's folders. Genres come from the files' tags; covers, artist pictures and lyrics from
  Deezer, MusicBrainz and LRCLIB, kept in its own data folder.
- Casting: the app serves the songs to the speaker over the local network, its signed links only. The
  account's episodes and stations play from the server, so from 0.4.2 their links carry the server's own
  signature (asked for with the window's login and kept for the day) instead of this library's.
- The address screen offers "Play this computer's music instead"; the tray's "Muzix library…" switches, and
  from 0.3.1 the user menu's switch "This computer's music" too.
- From 0.3.2 the window with no server starts with this computer's music, not the address screen, as the
  Android app does: with no music folder yet it asks for one first ("Choose a folder", "Not now", "Use a
  Muzix server"; not when it starts in the tray), and Home and the user menu offer "Add a music folder"
  (it lands in Settings' folders, shared too while sharing is on).
  The library's server goes when the app does.

## Step 5 in detail

This phone's music in the Android app (0.10.0), with no server, or beside one.

- The address screen offers "Play this phone's music": the system's folder picker, and the app may read
  that folder from then on (more folders can be added there).
- From 0.10.1 an app with no server starts with this phone's music, not the address screen. With no
  folder yet it asks for one first ("Choose a folder", "Not now", "Use a Muzix server"), at each start
  until there is one; without one, podcasts and radio play, and Home and the user menu offer "Add a music
  folder".
- The user menu (the More sheet on a phone) has a switch, "This phone's music": on, the phone's library;
  off, the server's again (its address screen if there's none). The phone's library has no Sign out.
- The app reads the folders itself (LocalLibrary.kt): each song's tags from the file (the system's
  MediaMetadataRetriever, not the phone's media index), the year from the folder's name when the tags
  have none, the cover from the folder's picture or the tags. A database of its own holds them, with
  this library's likes, playlists, plays and recent searches. The files are only read.
- A little web server inside the app, on 127.0.0.1 (LocalServer.kt), serves the web interface and this
  library in the server's own requests and answers (LocalApi.kt): home, albums, artists, genres,
  search, songs (a range of the file), covers, likes, playlists, autoplay. Lyrics come from LRCLIB and
  artist pictures from Deezer, shown only. Only the app gets in: a secret for each run.
- With a server too, podcasts, radio and the account's devices stay the server's: passed on with the
  app's login there, and the sidebar's podcasts and stations come from there.
- The downloads (2.4) are only the server's: no Download buttons while the library is this phone's, and
  from 0.10.3 its songs are never taken for a downloaded server song under the same address.
- From 0.10.2 Settings' "The app" lists this library's folders, each with its songs, to take out again
  (the files stay on the phone; its songs leave the library with their likes, plays and places in
  playlists). A folder the phone can't read for now (a card taken out) keeps its songs till it can.
- Casting (0.10.4): a speaker can't reach 127.0.0.1, so the queue's links go to it on the phone's address
  on the wifi, where a second listener gives out only the audio, by links signed with a token new for each
  run (GET /api/cast/token); the account's episodes and stations are passed on to the server with the
  app's login. The phone has to stay on that wifi while it casts its own songs.
- Muzix Connect (0.10.5; Muzix Desktop 0.4.1 too): a device showing its own library is still one of the
  account's devices (the phone's server passes the page's socket on to the server, with the app's login),
  and the user's choices of 2026-11-10 hold: what it plays is seen and controlled from the others (and it
  controls theirs), but a queue moves only between devices that show the same library: the device picker
  greys the others out, saying which music they show, and the server refuses such a move too. Another
  library's songs are shown without their covers, likes or links; music chosen while another library
  plays elsewhere plays here, and it can't go into that queue.

## Step 6 and 7 in detail

- 6, the computer: with no server, this computer's library (step 4) keeps the podcasts and stations itself
  (it's Muzix's own server code); when the window signs in to a server, they move into the account
  there (subscribed and saved there, then gone here, so nothing moves twice: library.py).
- 6, Android: with no server, the app keeps them itself (LocalShows.kt, in the server's own requests):
  podcasts found through Apple's directory and read from their feeds on the phone, episodes and stations
  played from their own addresses, the places in episodes kept. Signed in to a server later, they move
  into the account the same way; one the server can't take stays on the phone.
- 7: the Android app's player tees off the sound on its way to the speaker (Spectrum.kt) and works out
  the analyser's 256 bands 30 times a second, while the page shows; the page's visualizer takes them as
  it takes Muzix Desktop's.

## Supporter

Not decided in full yet: the price and the shop come first. The idea, from 2026-11-09:

- "Support the project", not a premium version: everything works without it, and the genre skins are the
  thank-you. The code stays open (MIT), so anyone can build it without the lock, and that's said openly.
- Without a key: every colour scheme and two or three skins, so the idea shows. No trials, no reminders.
- With a key: every skin, the skin map, and a Supporter mark in the account menu.
- The key goes on the server (the admin enters it, and every user there has skins) or into the app (for
  the local library).
- Paid once, not a subscription, maybe pay what you want above a lowest price. A shop that handles EU VAT
  and sends keys (Lemon Squeezy, Paddle). Their keys are checked online once, when entered; keys signed by
  us would work offline but need a small signing step of our own after each purchase.
- The Library Network stays free: it's worth more the more servers are in it, and taking money for sharing
  music between people's servers is a legal risk.

## Step 1 in detail

Each part ships on its own; the web version keeps working throughout.

### 1.1 Spotify out

- Server: the Spotify API (sign-in, tokens, the genre lookups for skins), the module and its setting, the
  client id, Spotify in the setup wizard, Spotify as a source in Edit metadata (search, artist pictures,
  covers).
- Database: the stored Spotify logins (`spotify_links`) and the two Spotify settings are removed when the
  new version starts. Likes, playlists and history never held Spotify items, so nothing else changes.
- Web: the Spotify page and player, Spotify items in the queue, the sidebar and menu entries, the module in
  Setup and Admin → Modules, Spotify in Edit metadata.
- README and the product docs. (The Android app's Spotify filter for queues from other devices goes with
  step 2's Android changes.)

### 1.2 API version

`GET /api/health` gives `api`, a whole number raised with each change an app has to know about. The apps
carry the lowest and highest they work with.

### 1.3 Device logins

- `POST /api/auth/token` (username, password, the device's name) gives a token for an app. Every request
  that takes the cookie takes `Authorization: Bearer <token>` too: the API, streams, the Connect socket.
- Each login (cookie or token) has a name: the app's device name, or the browser and system for the web.
- Settings → Devices: each signed-in device with when it was last seen, and Sign out for each.

Moved to step 2, where the app needs them: settings per device (Appearance among them), and how the UI
inside the app reaches a server.

## Step 2 in detail

### 2.1 Settings per device

Server and web only, so it ships on its own.

- Each login keeps its own settings (`sessions.prefs`): colour scheme, light/dark, skins, sound quality,
  autoplay, views. "Music from linked servers" stays on the account.
- A login without settings of its own starts from the account's, once: the first sign-in after the
  upgrade looks as before, on every device.
- Appearance leaves Admin: the server's default colour scheme, light/dark and genre skins settings go, and
  the skin map (extra genre → skin rules) becomes a setting of the device's own, in Settings → Appearance.

### 2.2 The UI inside the app

- The app carries the web UI (the same build as the server's) and serves it itself, on the server's own
  address: the web view's requests there that aren't `/api/…` get the app's files. So the page keeps its
  links as they are, its login cookie and the Connect socket, and needs no cross-origin rules. A later
  local library is served the same way, from inside the app.
- The app knows the API versions its UI works with. On connecting and at each start it reads the
  server's (`/api/health`). A server too old or too new for it shows its own web interface, as the app
  did before, and the app says which one to update (the server's own interface has the app's update
  button).
- A server that doesn't answer: the app's interface says so, with Try again and Another server.
- In the app there's no Admin page; admins get "Admin on the server" in the user menu, which opens the
  web version's Admin. Admin mode (the cog on every item) is a switch in the user menu, in the apps too
  (from Android 0.10.16 and desktop 0.4.15), on the server's music only: the app's own library has
  nothing to edit. (Up to 0.10.0 a wrench beside the user menu opened the page shown, in the web
  version in admin mode; from then until 0.10.15 the apps had no admin mode.)
- The sign-in tells the server the phone's name, so Settings → Devices tells two phones apart.

### 2.3 At home and away

- The server tells its outside address (Admin → the public address). The app keeps both: the one typed
  in, if it's on the local network, and the outside one.
- On starting and when the network changes, the app tries the home address first (a short wait) and
  otherwise uses the outside one; the login goes with it to either.
- The player's links follow: a song queued at home plays on from the outside address after leaving.

### 2.4 Downloads and offline

- A Download button on albums, playlists, audiobooks, episodes and the liked songs (which then stay in
  step: a song liked is downloaded, one unliked goes); Settings: the format (Original, or Smaller: Opus
  at the server's bitrate, the default on the phone) and only on wifi.
- The app downloads (Media3's downloader: in the background, with a notification, picking up where it
  stopped) and keeps what the pages need to show them: the page's data and the covers.
- Offline, the app shows a Downloads page: what's downloaded, opened and played from the phone. Library
  pages that aren't downloaded say they need the server.
- Settings → Downloads: what's on the phone, its size, and removing it.

### 2.5 The rest, and the release

- The app's own connection to the other devices (ConnectLink) loses its Spotify filter.
- The app becomes 0.9.0 and upgrades the old one in place.
