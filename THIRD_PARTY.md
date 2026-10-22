# Third-party work in Muzix

## Colour schemes

`frontend/src/theme/palettes.json` holds 97 dual light/dark palettes from
[claude-desktop-extra](https://github.com/patrickjaja/claude-desktop-extra)
(MIT, © 2026 Patrick Jaja). 84 of them come from the
[Noctalia community-palettes](https://github.com/noctalia-dev/community-palettes)
collection (no license file at the time of writing), which in turn ports
well-known open themes such as Catppuccin, Nord, Gruvbox, Rose Pine,
Tokyo Night, Kanagawa, Everforest and Solarized (each under its own,
usually MIT, license).

## Fonts (SIL Open Font License, bundled through @fontsource)

Saira, JetBrains Mono, Pirata One, UnifrakturCook, Metal Mania, New Rocker,
Monoton, Orbitron, Audiowide, Press Start 2P, VT323, Poiret One, Limelight,
Cinzel, Cormorant Garamond, Rye, Righteous, Shrikhand, Permanent Marker, Bungee,
Special Elite, Fredoka, Bangers, Lilita One, Bebas Neue.

## Players and libraries in the Docker image

| Component | License | Use |
|---|---|---|
| FFmpeg | LGPL/GPL | decoding, transcoding |
| libopenmpt | BSD | tracker modules |
| Game_Music_Emu (libgme) | LGPL | console chip music |
| sidplayfp / libsidplayfp | GPL | Commodore 64 SID |
| FluidSynth + FluidR3_GM soundfont | LGPL / MIT | MIDI |
| Furnace | GPL | FamiTracker / Furnace songs |
| StSound (`ymtool` builds on it) | MIT | Atari ST YM |
| beets, mediafile, mutagen | MIT / GPL | tagging uploads, reading tags |
| FastAPI, SQLAlchemy, Pillow, httpx, feedparser | MIT / BSD | backend |
| React, TanStack Query, Zustand, lucide | MIT / ISC | web interface |

The players run as separate programs or are loaded as shared libraries; their
sources are available from their projects and from Debian.

## Services

- [MusicBrainz](https://musicbrainz.org) (artist genres, upload matching),
  [Cover Art Archive](https://coverartarchive.org), optionally Last.fm.
- [radio-browser.info](https://www.radio-browser.info) (radio directory).
- Apple Podcasts search API (podcast directory and charts).
- Spotify Web API and Web Playback SDK.
