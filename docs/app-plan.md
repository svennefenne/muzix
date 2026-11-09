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
- In the app there's no admin mode and no Admin page; admins get "Edit on the server", which opens that
  item in the web version.
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
