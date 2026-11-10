# Muzix

A self-hosted, Spotify-style player for everything you own: your music library,
chiptunes and tracker modules, audiobooks, podcasts and internet radio. Runs as
one Docker container (made for Unraid).

**The app dresses up for what's playing.** Put on death metal and the whole
interface turns into a death metal record: bone-on-blood blackletter, a thorned
frame and embers rising with the bass. Psytrance gets UV neon and a fractal
mandala, chiptunes get pixel fonts, CRT scanlines and a warp starfield, jazz gets
Blue Note colours and art deco type. The covers always stay as they are: a skin
dresses the interface around them. There are 25 genre skins, and when none
applies you choose from 98 colour schemes, each with a light and a dark version.

## Features

- **Music library**: albums, artists, genres, playlists, likes, play history,
  full-text search, album colours, a gapless queue (the next song loads
  while one plays and takes over the moment it ends). On mobile data (Chrome
  on Android says when) the song that plays and the next two are downloaded
  whole, so a tunnel or a dead spot doesn't stop the music; a song without a
  copy waits for the connection and carries on where it stopped, instead of
  being skipped.
  F5 (or Ctrl+R) while music plays refreshes the page without a break in it.
  A real reload (the browser's button, Ctrl+F5, a new version of Muzix) keeps
  the queue and carries on where the music was, playing if it played (a
  browser that wants a click first asks for one).
  Search remembers what you pick from its results, as Spotify does: they show
  as recent searches in the empty search box and on the Search page, each to
  remove, on every device you sign in on.
- **Lyrics**, as on Spotify: synced lines that follow the song on the cover's
  colour, in the now playing panel (the microphone gives them the whole panel)
  and full screen on phones. They come from an .lrc file beside the song
  (uploads bring theirs along), the song's own tags, or LRCLIB (lrclib.net), a
  free lyrics database, which can be turned off on the admin page.
- **Autoplay**: when the queue runs out, similar songs keep playing, picked by
  the genre tags of what you chose (game music: more from the same chips).
  Turn it off in the queue or in Settings.
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
  A blue dot, as on Spotify, marks episodes out since you subscribed that you
  haven't started, and podcasts that have one; new episodes also show at the
  top of the home page.
  Each podcast remembers its own order (newest or oldest first) and whether
  finished episodes are hidden; an episode's menu marks it, or every older one,
  as finished. With a podcast's Autoplay on, the next unplayed episode in that
  order plays when one ends (with none left that way, the nearest one the other
  way). The player skips 15 seconds back and on and steps to the episode before
  or after, and an episode left halfway carries on there when you go back to it.
  Continue listening, at the top of the podcasts page, has the episodes you've
  started and not finished, the latest first.
  An episode opens its own page with the full show notes: links work and
  timestamps (12:34) play from there.
- **Internet radio**: tens of thousands of stations from radio-browser.info,
  saved stations, live "now playing" titles.
- **Cast to speakers**: send the queue to a Chromecast Audio, Nest or Home
  speaker or a speaker group (audio only). The speaker streams straight from
  Muzix, lossless where it can, and keeps going when your phone sleeps.
- **Admin page**: library folders with a folder browser, scans and jobs with
  logs, users, and every setting with an explanation.
- **Admin mode** (a switch in the user menu, admins only): a cog on every album,
  song, artist, audiobook, podcast, playlist and station, with
  - *Edit metadata*: the fields (an album with all its songs) side by side with
    what MusicBrainz, Discogs, Bandcamp, Deezer and iTunes
    know, to fill in with one click; a picked album brings that source's cover
    along, a picked artist their picture. Otherwise covers come from those
    sources, fanart.tv, a web image search, a picture's address or a file.
    Discogs (a free personal token), fanart.tv (a free API key) and the web
    search (a Brave Search API key, $5 of free searches a month) need keys on
    the admin page. An album's songs are paired with the picked album's by their
    length, so a title can't land on the wrong song. Tags are written into the
    files, and an album in a music folder is filed again by its new tags: a new
    genre (or any save of an album in Uncategorized) moves it to that genre's
    folder, found the way uploads are filed ("Doom Metal" goes to Metal), and
    the edit window says beforehand where it goes; Duplicates and Other formats
    keep theirs. Chip and tracker files, audiobooks and podcasts keep their
    edits in Muzix. A new artist name goes into all their songs in the
    background (their albums stay in their genre folders): the edit window says
    beforehand which folders move and whether the name joins an artist already
    there, and Muzix says when it's done.
  - *Undo*: every saved edit can be undone, from the message after saving, the
    edit window or Admin → Edits: tags, file names, folders and covers go back
    exactly as they were, unless something has changed them since.
  - *Hide from library*: gone from every page for everyone; Admin → Hidden &
    trash shows it again.
  - *Delete*: the files move to a `.muzix-trash` folder on their share, to put
    back or delete for good from Admin → Hidden & trash.
  - *Edit tags* (an artist's): take genre tags off that artist alone or add
    your own; later lookups keep to it.
  - *Merge with another album* (an album's): albums that belong together (a
    reissue's bonus disc and the album itself) become one, each a disc of its
    own, in the first one's folder, filed and named again ("2-1. …"); what
    else the others' folders held goes to the trash. One edit, to undo.
- **Tags** (Admin → Tags): every genre tag the artists carry (from Last.fm or
  MusicBrainz), how many have it and which ones. Remove a tag everywhere,
  rename it or merge spellings into one ("hip-hop" and "hiphop" into
  "hip hop"), and sort tags that aren't genres into categories (a country, a
  mood…), shown on a row of their own on the artist's page or not at all.
  The tags as they came are kept, so later lookups follow the rules and each
  one can be taken back.
- **Upload area**: drop files or whole folders in the browser. Music is matched
  with MusicBrainz (beets), gets cover art and a main genre, and is filed as
  `Genre/Artist/Artist - Year - Album/1. Artist - Album - Title (Year).ext`.
  Chiptunes go to your VGM folder. Before anything goes up, a duplicate check
  (switch it off on the upload page) lists files uploaded before or waiting to
  be imported, and songs the library seems to have already by their names; you
  skip them or upload them anyway.
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
   account, then the setup: the folders your music is in (the mounted ones are
   suggested, others can be browsed to), the modules this server runs, its name
   and public address, and each module's own settings. The first scan starts
   when it's done. *Skip setup* takes the mounted folders with every module on.

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

### Modules

Music is Muzix itself; the rest are modules a server can run or leave out:
VGM, Audiobooks, Podcasts, Radio and the Library Network. They're
chosen in the setup and turned on or off later under *Admin → Modules*, where
each module also has its settings (and its folders). A module that's off is
gone from the menus, its pages say it's off, its content is left out of every
list and search, its requests answer 404 and its background work (scans, feed
refreshes, syncing with linked servers) waits. Nothing of it is deleted: turned
on again, it's all back, and it catches up on what it missed. Servers from
before modules have every module on.

### HTTPS

Put Muzix behind your reverse proxy (SWAG, Nginx Proxy Manager, Traefik...) and
set **Admin → Settings → General → Public URL** to its HTTPS address. Podcast
links and the Library Network use it, and casting needs it.

### Your devices

As with Spotify, every place you're signed in (a browser tab, the Android app)
is one of your devices, and they see each other. While one plays, the others
show what it plays ("Playing on Chrome on Linux") and their controls work it:
pause, skip and seek, and an album chosen there plays where the music is. The
device button in the player (the Cast button, when no other device is online)
lists your devices and Google Cast speakers; choosing one moves the music there,
where it was. The app plays on with its screen off and can be controlled from
your other devices meanwhile. A device that goes away is waited for 45 seconds
(a reload); after that nothing plays, and any of them can carry on from there.

### Casting to speakers

The Cast button appears in the player when a Google Cast speaker is on your
network. It works from Chrome on Android, Windows, macOS, Linux and ChromeOS,
on Muzix's HTTPS address (not on iPhone or iPad, and not over plain http).
The speaker fetches the audio itself with links signed for a day, so it has to
reach that address too: a local DNS entry pointing it at your server keeps the
audio inside your network. Files the speaker plays as they are (MP3, AAC,
FLAC up to 96 kHz, Ogg, WAV) are sent unchanged; everything else, chiptunes
included, arrives as FLAC.

### Library Network

Muzix servers can link their libraries: a friend's music, chiptunes, audiobooks
and playlist files join yours, and yours theirs. In *Admin → Library Network*,
turn it on to get this server's sharing code (`XXXXX-XXXXX-XXXXX-XXXXX`). To
link, enter the other server's address (`192.168.1.20:8484` or
`muzix.example.com`) and its code; then its admin enters yours. It takes both
codes, and the servers check them with each other. After that they talk with
keys traded while linking. A new code leaves the existing links in place, and
turning the network off stops new ones.

Each server keeps a copy of the others' catalogs: it fetches them when the link
is made, every night, and on *Sync now*. Their albums show up in your library,
search and artist pages; an artist you both have gets one page. Only a server's
own library is shared, never what it gets from others, and nothing its admin hid.
What's from another server has a small network mark on its cover, and its page
says whose it is ("From Kompisens Muzix"). Another server's items can be hidden
here (admin mode's cog offers only that) but not edited or deleted. Unlinking,
from either side, takes its music out of the other's library.

The files stay where they are. When one of them plays, your server fetches it
from the other one and passes it on, so the app, Cast speakers, seeking and the
quality settings work as with your own; chiptunes are rendered by the server
that has them. Covers and artist pictures are fetched once and kept like yours,
and lyrics come from the other server's files. A server that doesn't answer is
left alone for a minute at a time, so pages don't wait on it. Both servers must
be able to reach each other, and over the internet that should be HTTPS.

An album more than one library has is listed once. It's the same album when the
album artist and title match (case, accents, punctuation and a leading "The"
aside; for a various-artists compilation the year too) or the MusicBrainz release
does; an audiobook by its author and title. The copy listed is the *main
library's*, chosen under *Admin → Library Network* (this server's to begin
with); when the main library doesn't have it, this server's, then the others in
the order they were linked. Songs someone liked, put in a playlist or played keep
the copy they were, so nothing moves under anyone's feet.

Everyone on a server sees the network's music. Whoever wants only the server's
own library turns *Settings → Other libraries → Music from linked servers*
off; for them every copy of the server's own albums is listed again, whatever
the main library.

### Muzix Desktop: listening, and sharing from a computer

Muzix Desktop (`desktop/`, Windows, macOS and Linux) is Muzix on the computer: a
window with the web interface (it comes with the app) and a player of its own
behind it, GStreamer, which plays every format as it is and gapless and feeds the
visualizer. It casts to Google Cast speakers, the media keys and the system's own
media controls work (MPRIS on Linux, the media overlay on Windows, Now Playing on
macOS), and it's one of the account's devices for Muzix Connect. It uses the
server's address at home while that answers and its public address otherwise.
Closing the window leaves it in the system tray, playing on.

Someone without a server of their own can also share folders on their computer with
the servers they listen on: Muzix Desktop (`desktop/`) runs in the background on
Windows, macOS and Linux, from an icon in the system tray. In its *Settings* they
add the folders to share and a server's HTTPS address and sharing code; the
server's admin then accepts the computer under *Admin → Library Network* by
entering the code the client shows. While the computer is on, its music is in
the server's library like a linked server's (covers, search, Cast, quality
settings); while it's off, its albums are hidden, with nothing deleted, and
they're back when it's on. A computer can't be called, so the client keeps a
connection open to each server (a websocket), and the server asks through it for
the catalog, a song's file (kept in the server's cache once played) or a cover.
Only the computers a server's admin accepted are in its library, and their music
isn't passed on to that server's own links.

The tray menu also has *Fix Metadata & Artwork*: a small window, always on top,
that albums are dropped on. Each gets the suggestions of the sources chosen in
*Settings* (MusicBrainz, Deezer, iTunes, Bandcamp, Discogs, fanart.tv, web
images: the same as the server's Edit metadata), and the one picked is written
into the songs' tags with its cover. Depending on *Settings → Files* the songs are
then left as they are, renamed where they are, or filed into a library folder the
way the server files uploads (`Genre/Artist/Artist - Year - Album`). Every fix
can be undone from its card.

Builds for each system are on the
[releases page](https://github.com/svennefenne/muzix/releases) as
`desktop-v…`; `desktop/README.md` has the details.

### Android app

`android/` holds the Android app: Muzix's web interface, as it looks in a
browser, with Android's media player (Media3) behind it. From 0.9.0 the
interface comes with the app (a server whose API it doesn't know shows its own,
and the app says which to update), so the app opens without the server. The page hands the queue to that player the way it does to a Cast speaker,
so songs go on with the screen off, the lock screen and notification show the
player, and headsets, Bluetooth and cars can skip and pause. The first start
asks for the server's address (http on the local network works too); "Change
server" in the account menu asks again. The Cast button (or the output switcher
in the notification) moves the queue to a Google Cast speaker and back, with the
same signed links as casting from Chrome, so the app has to be connected to
Muzix's https address for it. Away from wifi (or on a phone's hotspot) the app downloads the
song that plays and the next two into its cache (1 GB at most), so the music
plays on through tunnels; a dropped connection is waited out, never skipped.
The app saves where episodes and audiobooks got to by itself (every 15 seconds,
on pause, and when its card is closed), as the page sleeps with the screen off.
When it crashes, it tells the server the next time it starts: the crash shows
in the server's log next to the web interface's own errors.

The app uses the server's address at home while it answers and its public
address (Admin → General → Public URL) otherwise, and moves between them as the
phone changes networks, the music playing on. Albums, playlists, audiobooks,
episodes and the liked songs download to the phone (Download on their pages;
Settings → Downloads for the format, Smaller or Original, and wifi only).
Offline, the app shows what's downloaded and plays it from the phone. Admin
pages are the web version's: the app's "Admin on the server" opens them in the
browser. Each phone is its own login, with settings of its own. From 0.10.0 the
app also plays the phone's own music, with no server at all: "Play this phone's
music" on its address screen picks the folders, and the app reads their tags
itself (the files are only read). From 0.10.1 the app starts with the phone's
music when it has no server, asking first for the folder with the music
(without one, podcasts and radio play), and a switch in the user menu, "This
phone's music", goes between the phone's music and the server's.

Install it from <https://github.com/svennefenne/muzix/releases/latest/download/muzix-android.apk>
(the phone asks once to allow installs from the browser); later versions install
over it. From 0.8.0 the app updates itself: when a newer release is out (the
server asks GitHub once an hour; another repository's with `MUZIX_APP_REPO`), the
account menu offers "Update the app", and the app downloads it and opens
Android's installer (the first time, Android asks to allow installs from Muzix).
The server's address is changed under Settings → The app. GitHub Actions builds and signs it whenever `android/` changes
(`.github/workflows/android.yml`), with the key in the repository's secrets
`ANDROID_KEYSTORE_BASE64`, `ANDROID_KEYSTORE_PASSWORD` and `ANDROID_KEY_ALIAS`;
Android only updates an app signed with the same key, so keep a copy of it. To
build it yourself:

```sh
cd frontend && npm ci && npm run build      # the web interface the app carries
cd ../android && ./gradlew assembleRelease # JDK 17+ and the Android SDK (platform 36.1)
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
