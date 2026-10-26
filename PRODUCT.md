# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

- **The owner**, who built Muzix and runs it on their Unraid server for their own collection: a beets-organized music library of about 70,000 tracks, about 15,000 chiptune and tracker files, audiobooks, podcasts, internet radio and a Spotify Premium account. Most decisions are tried against this library first.
- **Family and friends** with accounts on the owner's server (muzix.plopp.io). They didn't set it up and don't know how the folders are organized; they need to find something and press play without any admin knowledge.
- **Other self-hosters** who install it from the public GitHub repository (Docker image, Unraid template) for their own libraries. Nothing may assume the owner's folders, genres or setup.

## Product Purpose

Muzix is a self-hosted, Spotify-style player for everything you own: your music library, chiptunes and tracker modules, audiobooks, podcasts and internet radio, with your Spotify account built in, in one app with one queue. It succeeds when its users reach for it instead of Spotify's own app, Plex, Jellyfin or Navidrome, a separate audiobook app, a podcast app and a chiptune player.

## Positioning

- **The app dresses up for what's playing.** Genre skins restyle the whole interface for the music (death metal turns it into a death metal record, chiptunes get pixel fonts and CRT scanlines, jazz gets Blue Note duotones). When no skin applies, users choose from 98 colour schemes, each with a light and a dark version.
- **Everything in one place.** The music library, VGM, audiobooks, podcasts, radio and Spotify share one library, search, queue and player.
- **Chiptunes done right.** Every tracker and console format plays natively, a game's loop points are honoured (intro, N loops, fade) and multi-song files show each song as its own track. VGM is a first-class section, not an afterthought.
- **Built around a real organizing pipeline.** Uploads are matched with MusicBrainz (beets), get cover art and a main genre, and are filed as `Genre/Artist/Artist - Year - Album/…`, the same scheme as the owner's library.

## Operating Context

- **Desktop at home:** big screen, mouse and keyboard (Space, arrows, N/P, M, Q/E, `/`), often fullscreen (F11).
- **Phone:** used as an app installed on the home screen, on the go or around the house, with a Spotify-style phone layout (tab bar, mini player).
- **Lean-back:** left running on a screen as a now-playing display (full-screen player, visualizer, skins).
- **Administration:** library folders, scans and jobs, uploads, users and settings are handled by whoever runs the server, usually only the owner.
- **Hosting:** one Docker container, usually behind a reverse proxy with HTTPS (Spotify playback needs it). Libraries live on NAS shares, so scans and folder listings can be slow.

## Capabilities and Constraints

- **Formats:** MP3, FLAC, Ogg/Opus, M4A, M4B, WavPack, APE and WMA; trackers (MOD, XM, IT, S3M, MT2…), console music (NSF, GBS, SPC, VGM…), SID, YM, FamiTracker/Furnace and MIDI.
- **Accounts:** multiple users with an admin role. Each user's preferences follow them (colour scheme, light/dark/system mode, skin lock, panel states).
- **Spotify:** playback inside Muzix needs Premium and the Web Playback SDK. New Spotify apps run in Development mode (no artist genres, short search results, at most five accounts), and ad and tracker blockers can break playback.
- **Terminology:**
  - *Library*: the user's music.
  - *VGM*: chiptunes, trackers and game soundtracks.
  - *Genre skins*, or just *skins*.
  - *Colour schemes*.
  - *Library folders*: roots, each of kind music, VGM or audiobooks.
  - *Your library*: the left panel with saved and recent items.

## Brand Commitments

- **Name:** Muzix.
- **Logo:** a cassette made of the five colour stripes, notched on top so it also reads as an M, and the name, with the name's capitals exactly as tall as the cassette. (Before 2026-10-26 it was five vertical stripes, which looked too much like other players' spectrum-bar marks, CLIAmp's in particular; keep away from bars of varying height.)
- **Look:** modelled on the owner's site *Unlimited Deck Force*. The reference screenshot is outside the repo, at `~/Projects/muzix-testdata/design-ref/deckforce-home.png`.
- **Binding (from the owner):**
  - The layout follows Spotify's arrangement while the Deck Force style stays intact. That style covers the colours, fonts, genre skins, frame lines, kicker labels, the now-playing ticker and the footer status line.
  - On phones, nothing frames the screen.
- **License and credits:** Muzix is MIT licensed. Colour schemes come from claude-desktop-extra (MIT) and noctalia's community palettes, which are credited in THIRD_PARTY.md.

## Evidence on Hand

- The owner's real library, used for testing on the server.
- A local test set outside the repo, at `~/Projects/muzix-testdata`: a Jazz & Blues subset, VGM files and audiobooks.
- The README feature list and install guide.
- There are no testimonials, user counts, benchmarks or press. Don't invent any.

## Product Principles

1. **One player for everything.** A new kind of audio joins the same library, search, queue and player; it never becomes an app within the app.
2. **The music sets the mood.** Skins are the identity, so every layout and component has to work under every skin, light and dark, and every frame style.
3. **Familiar where it's a tool.** Navigation and playback follow Spotify's conventions so nobody has to learn them. Personality lives in the skins, the type and the details.
4. **Owner first, never owner-only.** Defaults may fit the owner's library, but nothing hard-codes their folders, genres or setup. Settings live on the admin page, with an explanation for each.
5. **Every room of the house.** Desktop, phone and a lean-back display are all primary; none is a degraded version of another.
