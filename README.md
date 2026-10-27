# Muzix

A self-hosted, Spotify-style player for everything you own: your music library,
chiptunes and tracker modules, audiobooks, podcasts and internet radio, with
your Spotify account built in. Runs as one Docker container (made for Unraid).

**The app dresses up for what's playing.** Put on death metal and the whole
interface turns into a death metal record: bone-on-blood blackletter, a thorned
frame, gritty covers and embers rising with the bass. Psytrance gets UV neon and
a fractal mandala, chiptunes get pixel fonts, CRT scanlines and a warp starfield,
jazz gets Blue Note duotones. There are 25 genre skins, and when none applies
you choose from 98 colour schemes, each with a light and a dark version.

## Features

- **Music library**: albums, artists, genres, playlists, likes, play history,
  full-text search, album colours, gapless-feeling queue with prefetch.
- **Every format**: MP3, FLAC, Ogg/Opus, M4A, M4B, WavPack (up to 384 kHz),
  APE, WMA, plus chip music and trackers:
  | Family | Formats | Played by |
  |---|---|---|
  | Trackers | MOD, XM, IT, S3M, MT2 (MadTracker 2), MTM, MED, 669… | libopenmpt |
  | Consoles | NSF/NSFe (NES), GBS (Game Boy), SPC (SNES), GYM, HES, KSS, AY, SAP | Game_Music_Emu |
  | Master System & Game Gear | SGC | Game_Music_Emu 0.6 beta's SGC player (built from [DeaDBeeF's copy](https://github.com/DeaDBeeF-Player/deadbeef/tree/master/plugins/gme)) |
  | Atari 8-bit, digitized | SAP types D, S and R (libgme plays B and C) | ASAP (in zxtune123) |
  | Sound chip logs | VGM/VGZ, from any of the hundred-odd chips VGM logs (arcade, PC-98, X68000, Mega Drive…) | libvgm (in zxtune123) |
  | Commodore 64 | SID | sidplayfp |
  | Atari ST | YM | StSound (`ymtool`) |
  | FamiTracker | FTM, 0CC, DNM, FUR | Furnace |
  | ZX Spectrum | PT3, PT2, STC, ST3, STP, ASC, PSC, SQT, FTC, TFC, TS, PSG, VTX, DST, DMM, COP… | zxtune123 ([ZXTune](https://github.com/vitamin-caig/zxtune)) |
  | More Amiga & PC | AHX, HivelyTracker, Future Composer, Face The Music, Game Music Creator, Images Music System, ChipTracker, Quadra Composer, TCB Tracker (Atari ST), Funktracker, Liquid Tracker, Farbrausch V2 | zxtune123 |
  | Amiga custom players | TFMX, Jochen Hippel, SoundMon, Delta Music, SidMon, Sonic Arranger, Digital Mugician, Art Of Noise, JamCracker, David Whittaker, Rob Hubbard, Ben Daglish, Jason Page… (200 or so) | [UADE](https://gitlab.com/uade-music-player/uade), which runs each song's own replay code on an emulated Amiga |
  | MIDI | MID, KAR, RMI | FluidSynth + General MIDI soundfont |

  Multi-song files (NSF, GBS, SID, FamiTracker...) show every song as its own track. Amiga songs
  whose samples live in a second file (TFMX's `mdat.`/`smpl.`) need both side by side.
- **Looping chiptunes**: game music usually loops forever. On the admin page,
  choose "play the loop N times" (intro + N × loop + fade, using the file's own
  loop points) or "play for a fixed time", the fade length and a cap. Tracker
  modules have their own repeat count.
- **Online chiptune archives** (VGM → Online archives): browse and play
  straight from HVSC (C64), Modland (trackers), ASMA (Atari 8-bit), Joshw's
  NES, Game Boy, SNES, PC Engine and MSX rips, ZXArt (ZX Spectrum), VGMRips
  (arcade, consoles and Japanese computers, played with libvgm), The Mod
  Archive and scene.org. The Mod Archive needs an API key of your own (they
  hand them out on their forum; add it on the admin page). Search every
  archive (or one) by title, artist, year or system ("hubbard", "mega man nes",
  "1988 atari"), and shuffle all of them, one, or a folder. HVSC, Modland and
  ASMA are searched through the complete lists they publish, kept in a small
  index in the cache and fetched again once a week. Muzix fetches a
  folder when you open it and a tune when you play it (game sets come as .7z or
  .zip and are unpacked for you, with song names and lengths from their
  playlists), and keeps up to 5 GB of recent downloads. It never crawls the
  archives in the background.
- **Audiobooks**: .m4b with chapters or folders of files, resume position,
  speed control, finished/unfinished.
- **Podcasts**: subscribe by URL or from the Apple Podcasts directory, top
  charts, OPML import/export, resume, downloads (automatic if you like).
- **Internet radio**: tens of thousands of stations from radio-browser.info,
  saved stations, live "now playing" titles.
- **Spotify**: your playlists, saved albums and liked songs in Muzix style,
  played inside Muzix with the Web Playback SDK (Premium), genre skins included.
- **Cast to speakers**: send the queue to a Chromecast Audio, Nest or Home
  speaker or a speaker group (audio only). The speaker streams straight from
  Muzix, lossless where it can, and keeps going when your phone sleeps.
- **Admin page**: library folders with a folder browser, scans and jobs with
  logs, users, and every setting with an explanation.
- **Admin mode** (the wrench in the top bar, admins only): a cog on every album,
  song, artist, audiobook, podcast, playlist and station, with
  - *Edit metadata*: the fields (an album with all its songs) side by side with
    what MusicBrainz, Discogs, Deezer, iTunes and your linked Spotify know, to
    fill in with one click; a picked album brings that source's cover along,
    a picked artist their picture. Otherwise covers come from those sources,
    fanart.tv, a web image search, a picture's address or a file. Discogs (a
    free personal token), fanart.tv (a free API key) and the web search (a
    Brave Search API key, $5 of free searches a month) need keys on the admin
    page. An album's songs are paired with the picked album's by their length,
    so a title can't land on the wrong song. Tags are written into the files,
    and an album in a music folder is filed again by its new tags: a new genre
    (or any save of an album in Uncategorized) moves it to that genre's folder,
    found the way uploads are filed ("Doom Metal" goes to Metal), and the edit
    window says beforehand where it goes; Duplicates and Other formats keep
    theirs. Chip and tracker files, audiobooks and podcasts keep their edits
    in Muzix. A new artist name goes into all their songs in the background
    (their albums stay in their genre folders): the edit window says
    beforehand which folders move and whether the name joins an artist already
    there, and Muzix says when it's done.
  - *Undo*: every saved edit can be undone, from the message after saving, the
    edit window or Admin → Edits: tags, file names, folders and covers go back
    exactly as they were, unless something has changed them since.
  - *Hide from library*: gone from every page for everyone; Admin → Hidden &
    trash shows it again.
  - *Delete*: the files move to a `.muzix-trash` folder on their share, to put
    back or delete for good from Admin → Hidden & trash.
- **Upload area**: drop files or whole folders in the browser. Music is matched
  with MusicBrainz (beets), gets cover art and a main genre, and is filed as
  `Genre/Artist/Artist - Year - Album/1. Artist - Album - Title (Year).ext`.
  Chiptunes go to your VGM folder.
- Spotify-style layout in the Deck Force look: your library on the left, the
  page in a frame, what's playing on the right (toggle it from the player bar),
  player and status line below. Works on phones too.

## Install on Unraid

1. Add the template: Docker → *Add Container* → *Template repositories*, add
   `https://github.com/svennefenne/muzix`, or copy `unraid/muzix.xml` to
   `/boot/config/plugins/dockerMan/templates-user/`.
2. Check the paths: appdata → `/config`, your music share → `/music`,
   audiobooks → `/audiobooks`, books → `/books` (its `Audiobooks` sub-folder is
   used). "Library folders on first start" says which
   sub-folders become music / VGM / audiobook folders (changeable later).
3. Start it and open `http://<server>:8080`. The first visit creates the admin
   account and starts the first scan.

Plain Docker:

```sh
docker run -d --name muzix -p 8080:8080 \
  -v /mnt/user/appdata/muzix:/config \
  -v /mnt/user/media/musik:/music \
  -v /mnt/user/media/audiobooks:/audiobooks:ro \
  -v /mnt/user/media/books:/books:ro \
  -e MUZIX_DEFAULT_ROOTS="/music/mp3:music,/music/all-mods:vgm,/music/amiga-mods:vgm,/music/Game Soundtracks:vgm,/audiobooks:audiobooks,/books/Audiobooks:audiobooks" \
  -e PUID=99 -e PGID=100 \
  ghcr.io/svennefenne/muzix:latest
```

### HTTPS and Spotify

Put Muzix behind your reverse proxy (SWAG, Nginx Proxy Manager, Traefik...) and
set **Admin → Settings → General → Public URL** to its HTTPS address. Then:

1. Create an app at <https://developer.spotify.com/dashboard> (Web API and Web
   Playback SDK).
2. Add the redirect URI `https://<your muzix address>/api/spotify/callback`.
3. Paste the app's Client ID into **Admin → Settings → Spotify** and press
   *Connect Spotify* on the Spotify tab.

Playing Spotify inside Muzix needs Spotify Premium; without it you can still browse.

New Spotify apps run in *Development mode*: the app owner needs Premium, and
at most five Spotify accounts can use the app. Add other people's accounts
under *User Management* in the app's dashboard.

**"Authentication failed" when playing Spotify:** Spotify's player runs in a
frame from `sdk.scdn.co` and has to reach `apresolve.spotify.com`,
`spclient.wg.spotify.com` and `dealer.spotify.com`. Ad and tracker blockers
such as AdGuard and Privacy Badger block those, so allow your Muzix address in
them (AdGuard: turn off protection for the site; Privacy Badger: disable it for
the site). The browser also needs DRM: in Firefox, *Settings → General → Play
DRM-controlled content*. The browser console (F12) shows blocked Spotify
requests as "CORS request did not succeed".

### Casting to speakers

The Cast button appears in the player when a Google Cast speaker is on your
network. It works from Chrome on Android, Windows, macOS, Linux and ChromeOS,
on Muzix's HTTPS address (not on iPhone or iPad, and not over plain http).
The speaker fetches the audio itself with links signed for a day, so it has to
reach that address too: a local DNS entry pointing it at your server keeps the
audio inside your network. Files the speaker plays as they are (MP3, AAC,
FLAC up to 96 kHz, Ogg, WAV) are sent unchanged; everything else, chiptunes
included, arrives as FLAC. Spotify songs are skipped on the speaker.

### Android app (prototype)

`android/` holds a small Android app: Muzix's own web interface from your
server, as it looks in a browser, with Android's media player (Media3) behind
it. The page hands the queue to that player the way it does to a Cast speaker,
so songs go on with the screen off, the lock screen and notification show the
player, and headsets, Bluetooth and cars can skip and pause. The first start
asks for the server's address (http on the local network works too); "Change
server" in the account menu asks again. The Cast button (or the output switcher
in the notification) moves the queue to a Google Cast speaker and back, with the
same signed links as casting from Chrome, so the app has to be connected to
Muzix's https address for it. Spotify playback isn't in the app; open Muzix in
Chrome for that.

Install it from <https://github.com/svennefenne/muzix/releases/latest/download/muzix-android.apk>
(the phone asks once to allow installs from the browser); later versions install
over it. GitHub Actions builds and signs it whenever `android/` changes
(`.github/workflows/android.yml`), with the key in the repository's secrets
`ANDROID_KEYSTORE_BASE64`, `ANDROID_KEYSTORE_PASSWORD` and `ANDROID_KEY_ALIAS`;
Android only updates an app signed with the same key, so keep a copy of it. To
build it yourself:

```sh
cd android && ./gradlew assembleRelease    # JDK 17+ and the Android SDK (platform 36.1)
# app/build/outputs/apk/release/app-release.apk, signed with the key that
# ~/.config/muzix-android/keystore.properties names (or the debug key without it)
```

## Keyboard

| Key | Action |
|---|---|
| Space | play / pause |
| ← / → | seek 5 s (Shift: 30 s) |
| N / P | next / previous |
| M | mute |
| Q / E | previous / next section |
| / | search |

## Development

```sh
# backend (Python 3.12+), serves the API on :18080
cd backend && python -m venv ../.venv && ../.venv/bin/pip install -e '.[dev,organize]'
MUZIX_DATA=/tmp/muzix MUZIX_PORT=18080 ../.venv/bin/python -m muzix
../.venv/bin/pytest

# frontend (Node 22): dev server on :5173 proxies /api to :18080
cd frontend && npm install && npm run dev
```

The colour schemes are generated with `scripts/import_palettes.py` from a checkout
of claude-desktop-extra. The Docker image (`Dockerfile`) builds the web interface,
compiles `ymtool` and installs the players.

## Credits

See [THIRD_PARTY.md](THIRD_PARTY.md). Muzix itself is MIT licensed.
