---
name: Muzix
description: A self-hosted player for everything you own, restyled for whatever is on air.
colors:
  midnight-navy: "#0a1020"
  deep-navy: "#060a15"
  navy-panel: "#121b2e"
  navy-panel-raised: "#1f2738"
  navy-panel-high: "#2d3341"
  bone: "#f1e7d0"
  bone-dim: "#aca79b"
  bone-faint: "#87847f"
  marigold: "#f2a93b"
  on-marigold: "#0b0b0f"
  vermilion: "#e4572e"
  on-vermilion: "#0b0b0f"
  coral-red: "#ef5350"
  on-coral-red: "#0b0b0f"
  saffron: "#f2c14e"
  jade: "#4fb286"
  hairline: "#1c263b"
  hairline-strong: "#29344d"
  frame-line: "#212a41"
  paper: "#f6efe1"
  paper-white: "#fffaf0"
  ink: "#1a2238"
  marigold-deep: "#c9781b"
  vermilion-deep: "#c8431f"
typography:
  display:
    fontFamily: "Saira, system-ui, sans-serif"
    fontSize: "clamp(44px, 7.4cqi, 104px)"
    fontWeight: 900
    lineHeight: 0.9
    letterSpacing: "0.01em"
  headline:
    fontFamily: "Saira, system-ui, sans-serif"
    fontSize: "26px"
    fontWeight: 900
    lineHeight: 1.05
    letterSpacing: "0.01em"
  title:
    fontFamily: "Saira, system-ui, sans-serif"
    fontSize: "17px"
    fontWeight: 800
    lineHeight: 1.2
  panel-title:
    fontFamily: "Saira, system-ui, sans-serif"
    fontSize: "13px"
    fontWeight: 800
    lineHeight: 1
    letterSpacing: "0.07em"
  body:
    fontFamily: "Saira, system-ui, sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.45
  button:
    fontFamily: "Saira, system-ui, sans-serif"
    fontSize: "12px"
    fontWeight: 800
    lineHeight: 1
    letterSpacing: "0.1em"
  chip:
    fontFamily: "Saira, system-ui, sans-serif"
    fontSize: "11px"
    fontWeight: 700
    lineHeight: 1
    letterSpacing: "0.06em"
  label:
    fontFamily: "JetBrains Mono, ui-monospace, monospace"
    fontSize: "11px"
    fontWeight: 500
    lineHeight: 1.4
    letterSpacing: "0.32em"
  status:
    fontFamily: "JetBrains Mono, ui-monospace, monospace"
    fontSize: "9.5px"
    fontWeight: 500
    lineHeight: 1
    letterSpacing: "0.12em"
rounded:
  tag: "4px"
  control: "6px"
  art: "7px"
  row: "8px"
  base: "10px"
  frame: "14px"
  pill: "99px"
spacing:
  dock-gap: "8px"
  item-gap: "12px"
  grid-gap: "18px"
  page-inline: "32px"
  page-block-start: "34px"
  section: "38px"
components:
  button:
    backgroundColor: "{colors.navy-panel}"
    textColor: "{colors.bone}"
    typography: "{typography.button}"
    rounded: "{rounded.control}"
    height: "38px"
    padding: "0 16px"
  button-hover:
    textColor: "{colors.marigold}"
  button-primary:
    backgroundColor: "{colors.vermilion}"
    textColor: "{colors.on-vermilion}"
    typography: "{typography.button}"
    rounded: "{rounded.control}"
    height: "38px"
    padding: "0 16px"
  button-accent:
    backgroundColor: "{colors.marigold}"
    textColor: "{colors.on-marigold}"
    typography: "{typography.button}"
    rounded: "{rounded.control}"
    height: "38px"
    padding: "0 16px"
  button-small:
    height: "30px"
    padding: "0 11px"
  icon-button:
    backgroundColor: "{colors.navy-panel}"
    textColor: "{colors.bone}"
    rounded: "{rounded.pill}"
    size: "32px"
  input:
    backgroundColor: "{colors.deep-navy}"
    textColor: "{colors.bone}"
    rounded: "{rounded.control}"
    height: "38px"
    padding: "0 12px"
  search:
    backgroundColor: "{colors.navy-panel}"
    textColor: "{colors.bone}"
    rounded: "{rounded.pill}"
    height: "40px"
    padding: "0 34px 0 38px"
  chip-filter:
    backgroundColor: "transparent"
    textColor: "{colors.bone-dim}"
    typography: "{typography.chip}"
    rounded: "{rounded.pill}"
    height: "28px"
    padding: "0 11px"
  chip-filter-on:
    backgroundColor: "{colors.bone}"
    textColor: "{colors.midnight-navy}"
  chip-section:
    backgroundColor: "color-mix(in srgb, #f1e7d0 12%, transparent)"
    textColor: "{colors.bone}"
    rounded: "{rounded.pill}"
    height: "32px"
    padding: "0 14px"
  library-row:
    textColor: "{colors.bone}"
    rounded: "{rounded.row}"
    padding: "6px 8px"
  library-row-active:
    backgroundColor: "color-mix(in srgb, #f2a93b 16%, transparent)"
    textColor: "{colors.marigold}"
  quick-tile:
    backgroundColor: "color-mix(in srgb, #f1e7d0 10%, transparent)"
    textColor: "{colors.bone}"
    rounded: "{rounded.control}"
    height: "60px"
  frame:
    backgroundColor: "color-mix(in srgb, #0a1020 42%, transparent)"
    rounded: "{rounded.frame}"
---

# Design System: Muzix

## Overview

**Creative North Star: "The Late-Night Broadcast"**

Muzix is a station on the air after midnight, and it restyles itself for every show. The top bar is the station's dial: the striped logo, then the sections (Music, VGM, Audiobooks, Podcasts, Radio, Spotify) as pills to tune to. The footer is the station's status line, set in tiny spaced-out monospace: the host name, track counts, the skin on air, a fullscreen hint. Between them sits the screen itself, a thin rounded frame floating on a nebula backdrop, with the library to its left and what's playing to its right. When the music changes genre, the whole station re-dresses for the show: death metal brings bone and blood with blackletter type, a chiptune brings CRT scanlines and pixel type, jazz brings Blue Note duotones.

The house look, used when no skin is on air, is night-time warm: Bone text on Midnight Navy, Marigold for whatever is live, Vermilion for the one thing to do next, and a soft nebula of jade, marigold and vermilion glow behind everything. Headings are loud (heavy condensed capitals); everything around them is quiet. The layout follows Spotify's arrangement, so nobody has to learn where things are; the personality lives in the type, the colour, the skins and the broadcast furniture (stripes, section pills, mono labels, status line).

Density is a listener's density, not a dashboard's: generous page margins, large covers, and lists that breathe at about 60px per row. The interface is built to be left running on a screen as much as to be operated.

**Key Characteristics:**
- Every colour, font and corner comes from role variables that the 98 colour schemes and 25 genre skins swap out. Nothing in a component is hard-wired to the house palette.
- Heavy uppercase display type for headings; tiny spaced monospace for labels and status; a plain sans for everything you read or press.
- The frame: one 1px hairline panel with 14px corners, inset 8px from the window, holding the page; the side docks share its edge.
- Broadcast furniture: the section pills in the top bar, the footer status line, the five-colour stripes.
- Quiet, precise controls: small outlined buttons, round icon buttons, pill chips. They never outshout the headings or the cover art.

## Colors

The house palette is warm light on deep night: one hot accent for what's live, one for what to do, on navy panels that sit barely above the background. These are the defaults of the "Muzix" colour scheme (dark). Each of the other 97 schemes and each genre skin supplies the same nine source roles (background, surface, text, primary, secondary, error, warning, success, border), and the app derives the rest from them.

### Primary
- **Marigold** (#f2a93b): what is live or selected. Used for the focus ring, the now-playing ring, the active row in the library, a toggle that's on, link hover, the selection highlight and the home button when you're home. In the light scheme it deepens to **Marigold Deep** (#c9781b). Text on it is near-black **On Marigold** (#0b0b0f).

### Secondary
- **Vermilion** (#e4572e): the one main action on a view ("Shuffle everything", a primary button) and the warm half of the nebula. In the light scheme it is **Vermilion Deep** (#c8431f). Text on it is near-black **On Vermilion** (#0b0b0f); on Vermilion Deep it turns white.

### Tertiary
- **Jade** (#4fb286): success and the "ready" dot; also the cool corner of the nebula glow.
- **Saffron** (#f2c14e): warnings, and the second logo stripe.
- **Coral Red** (#ef5350): errors, destructive hovers, and the fourth logo stripe. Error notices carry near-black **On Coral Red** (#0b0b0f) text.

### Neutral
- **Midnight Navy** (#0a1020): the page background, under the nebula.
- **Deep Navy** (#060a15): the darkest well, for text inputs and recessed areas.
- **Navy Panel** (#121b2e): surfaces: buttons, menus, drawers, modals. It's usually mixed with the page at 80–96% so the nebula shows through.
- **Navy Panel Raised** (#1f2738) and **Navy Panel High** (#2d3341): hovered rows, progress tracks, chip counters.
- **Bone** (#f1e7d0): primary text, the play button, the first logo stripe.
- **Bone Dim**: secondary text such as artists, subtitles and help (7.8:1 on Midnight Navy).
- **Bone Faint**: the quietest text, such as the footer status line, captions, group labels and times (5.1:1 on Midnight Navy, 4.6:1 on Navy Panel).
- **Hairline** (#1c263b), **Hairline Strong** (#29344d) and **Frame Line** (#212a41): dividers, control outlines and the frame border.
- The light scheme swaps in **Paper** (#f6efe1), **Paper White** (#fffaf0) and **Ink** (#1a2238).

### Named Rules
**The Roles-Not-Hex Rule.** Components take colour only from the role variables (`--bg`, `--surface`, `--text`, `--primary`, `--secondary`, their derived shades and `--stripe-1…6`). A hex code in a component breaks 122 themes at once. The one exception is the bento tiles, which keep a fixed dark plate (#10131c with #f6f1e7 text) under their duotone photos.

**The 4.5 Floor Rule.** Dim and faint text are the text colour faded toward the background, but only as far as still reads at 4.5:1 on both the background and the surface. Text on an accent is near-black or white, whichever reads better. Red error text moves toward white (or black, on light schemes) until it reads at 4.5:1, and a red notice's colour is nudged until its text does. A scheme whose own text falls below 4.5:1 has it lifted to 7:1, so dim and faint text can still step down from it.

**The On-Air Rule.** Marigold means "this is live" (playing, selected, focused, on). Vermilion means "do this". Neither is used as decoration on a quiet surface.

## Typography

**Display Font:** Saira (with system-ui, sans-serif). Each skin swaps it: Pirata One, UnifrakturCook, Metal Mania, Audiowide, Press Start 2P, Cinzel, Bebas Neue, Righteous and others, all self-hosted.
**Body Font:** Saira (with system-ui, sans-serif). A few skins swap it too (punk uses Special Elite).
**Label/Mono Font:** JetBrains Mono (with ui-monospace).

**Character:** a squared, slightly technical sans that reads as a console when set heavy and in capitals, and stays plain and legible at body sizes. The monospace is the station's voice for labels and telemetry, never for prose.

### Hierarchy
- **Display** (900, clamp(44px, 7.4cqi, 104px), 0.9): page titles such as "Good morning, fenne" or an album name. Two lines: the first in Bone, the second in Marigold. It scales with the frame's width, not the window's, and is uppercase unless the skin says otherwise. On phones it is 34px.
- **Headline** (900, 26px, 1.05): section titles ("Jump back in", "Recently added"); 21px on phones.
- **Title** (800, 17px, 1.2): panel and card titles.
- **Panel title** (800, 13px, 0.07em, uppercase): the docks' headings ("Your library", the album in the now playing panel).
- **Body** (400, 15px, 1.45): running text; ledes are 16px in Bone Dim, at most 560px wide.
- **Label** (JetBrains Mono 500, 11px, 0.32em, uppercase): the kicker above a page title or section, segments separated by a dimmed dot.
- **Status** (JetBrains Mono 500, 9.5px, 0.12em, uppercase): the footer status line, tile kickers, captions.

### Named Rules
**The Two Voices Rule.** The display font shouts and the monospace whispers; the UI font carries everything in between. Nothing else gets a fourth voice.

**The Kicker Placement Rule.** Kickers sit above page titles and section titles, as they do now. They never go on cards, rows, dialogs or controls.

## Layout

The desktop is a fixed shell of four rows: the top bar (58px), the workspace, the player bar (76px) and the footer status line (26px). Safe-area insets pad all of it.

- **Top bar:** one row: the logo, the section pills (424px with their names), the home button and the search (up to 440px, giving way first when space runs short), and your controls pushed to the right.
- **Workspace:**
  - Columns, with 8px gaps and 8px side padding: "Your library" (304px), the frame (the rest), and the now playing panel (340px, toggled from the player bar).
  - The library folds to a 72px strip of covers when you ask, or on its own below 1100px.
- **Pages:**
  - Inside the frame, pages are centred at 1180px (wide pages 1480px), padded 34px on top, 32px at the sides and 64px at the bottom.
  - Sections are 38px apart, card grids gap at 18px, and rows of covers scroll sideways in 168px columns.
- **Container queries:** pages respond to the frame's width, not the window's, because the docks take varying room.
  - Below 900px, quick tiles go from four columns to two.
  - Below 820px, the bento goes to two columns.
  - Below 700px, the hero drops its featured cover.

Breakpoints give up the least useful parts first:
- Below 1500px the fullscreen button goes.
- Below 1440px the docks narrow (272px and 300px).
- Below about 1280px the section pills drop their names for icons (with the names as tooltips); below 1000px the logo shrinks to its stripes.
- Below 1180px the now playing panel goes.
- Below 1100px the library folds.
- At 860px and under, the phone layout takes over:
  - One edge-to-edge column with no frame at all.
  - A slim header (logo, search, avatar).
  - A floating mini player above a four-item tab bar.
  - Swipeable chip and cover rows, two-column quick tiles, and the album cover centred above the details.

**The Frame Rule.** On desktop, every page lives inside the frame. On phones there is no frame, by the owner's decision.

## Elevation & Depth

Muzix is flat at rest. Depth comes from three things:
- Tonal layering: panels are the background mixed with a little surface.
- The nebula backdrop glowing through translucent panels.
- The frame's hairline with an inner 1px shadow line.

Shadows belong to two things only: artwork, which is physical like a record sleeve, and layers that float above the page, such as menus, the queue drawer, modals, search results and toasts. Skin backdrops (embers, snow, film grain, CRT scanlines) add atmosphere behind the frame, never on top of controls.

### Shadow Vocabulary
- **Sleeve** (`box-shadow: 0 6px 18px #0005`): every cover in grids and rows.
- **Hero sleeve** (`box-shadow: 0 20px 60px #000a`): the tilted featured cover on Home and the album page's cover (`0 18px 50px #000b`).
- **Panel sleeve** (`box-shadow: 0 16px 40px #0009`): the cover in the now playing panel.
- **Popover** (`box-shadow: 0 20px 50px #000c`): menus; search results use `0 24px 60px #000a`.
- **Drawer** (`box-shadow: 0 30px 80px #000c`): the queue.
- **Modal** (`box-shadow: 0 40px 100px #000d`).
- **Frame line** (`box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--bg) 60%, transparent)`): the frame and docks' inner edge.

### Named Rules
**The Flat Studio Rule.** Panels, rows, chips and buttons never cast shadows. If something needs to look raised, it is either a cover or a floating layer.

## Shapes

The house shape is a gently rounded rectangle on a 1px hairline:
- **Frame and docks:** 14px corners, also used for the drawer and modals.
- **Default radius:** 10px, used for tiles, menus and empty states. Skins override it from 0 (black metal, punk) to 28px on the softest skins.
- **Covers:** 0.7 × that radius (7px by default).
- **Buttons, inputs and quick tiles:** 6px.
- **Library rows:** 8px.
- **Badges and footer chips:** 4px.
- **Pills:** search, filter chips and section chips are fully round, and so are icon buttons and avatars.

The recurring motif is **the stripes**: five vertical colour bars with 2px gaps, coloured from Bone, Saffron, Marigold, Coral Red and Jade (plus a sixth in Vermilion on tiles). They make the logo mark (26×30px, with the name's capitals exactly as tall) and the right edge of the Home tiles and VGM cards. Skins replace the frame's edge with their own: thorns, frost, rivets, gaffer tape, neon, pixel steps, art deco corners, double rules, ornaments, film sprockets, rope, a checkerboard band or bubbly 28px corners.

## Components

### Buttons
Small, outlined and exact; they recede until you need them.
- **Shape:** 6px corners, 38px tall (30px small), labels in 12px heavy capitals spaced at 0.1em.
- **Default:** a translucent Navy Panel with a Hairline Strong outline and Bone text.
- **Primary:** Vermilion with near-black text, one per view, for the main action.
- **Accent:** Marigold with near-black text, for "Play" on album pages.
- **Ghost:** no fill or outline until hovered. Danger buttons turn Coral Red on hover.
- **Hover / Focus:** the outline and label turn Marigold (fills brighten instead), pressing nudges the button 1px down, and focus shows a 2px Marigold ring 2px out. Disabled buttons drop to 50% opacity.
- **Icon buttons:** 32px circles (40px for Home) with a 1px outline; hover turns the outline and icon Marigold, press scales to 0.94, and "on" keeps them Marigold.

### Chips
- **Filter chips** (library dock and sub-navigation): pill outline in Hairline Strong with dim 11–12px capitals; hover brightens to Bone; selected fills solid Bone with navy text.
- **Section chips** (Home): borderless pills, Bone at 12% opacity, 13px semibold, turning 20% on hover. The phone's Shuffle chip is solid Marigold.
- **Badges and footer chips:** 18px tall, 4px corners, mono 9–10px capitals in a hairline outline.

### Cards / Containers
- **The frame:** the page's home. A 1px Frame Line border, 14px corners, Midnight Navy at 42% (78% under light skins) so the nebula shows, and an inner hairline. Skins decorate its edge.
- **Docks** (library, now playing): the same border, corners and fill as the frame. They scroll inside themselves, with no decoration.
- **Panels** (admin and settings): a Hairline border with the default radius, Navy Panel at 82% and 20px padding.
- **Bento tiles:** a fixed dark plate showing a grayscale photo collage under a duotone wash in the tile's colour, halftone dots, the stripes at the right edge, and a mono kicker over a heavy display title in warm white. Hover lifts them 2px and tints the border Marigold.
- **Quick tiles:** a 60px row of cover and title on Bone at 10%, with 6px corners and no shadow.
- **Covers:** square, 7px corners, Sleeve shadow; a missing cover becomes a two-colour gradient from a hue derived from the name, with initials set in the display font.

### Inputs / Fields
- **Style:** 38px tall, 6px corners, a Deep Navy well with a Hairline Strong outline, Bone text 14px, labels 12px bold Bone Dim above, help text 12px Bone Faint below.
- **Search:** a 40px pill on translucent Navy Panel with a search icon on the left and a `/` key hint on the right. Its results drop down beneath it, grouped under mono labels.
- **Focus:** the outline turns Marigold, with no glow.
- **Switches and ranges:** a 40×22px track that fills Marigold when on. Range sliders have 4px tracks and a 13px Bone thumb; seek bars turn Marigold on hover and show a striped Coral Red fill when the stream is live.

### Navigation
- **Top bar:** striped logo (links Home), the section pills (13px semibold on Bone at 10%, the current section solid Marigold), a round home button (Marigold when you're home) beside the search, and on the right a now-playing button with a progress ring, the light/dark toggle, fullscreen and the account pill (avatar plus name; Settings, Admin and Sign out live in its menu).
- **Your library (left dock):**
  - Header row with a panel title and a "+" for a new playlist, then filter chips, then rows.
  - Each row is a 48px cover with a 14px bold title and a 12.5px dim subtitle ("Playlist · 12 songs").
  - Hover tints the row with Bone at 7% and reveals a play button over the cover. The current page's row is tinted Marigold at 16% with a Marigold title.
  - Folded, it is a strip of covers that open their page.
- **Phone:** a translucent, blurred tab bar (Home, Search, Library, More) with 10.5px labels. The active item is Bone with a heavier icon stroke, and More opens a bottom sheet.

### Now Playing Panel (signature)
The right dock is the broadcast's on-air card. The big cover opens the full-screen player. Below it:
- The track in 26px display capitals, the artist in dim semibold, and a heart.
- One line naming the skin on air with its tagline ("**Blues** skin · Juke joints at midnight").
- A link to the album.
- Under a hairline, "Next in queue": five 40px rows with mono durations.

With nothing playing, it invites a shuffle.

### Status Line (signature)
The footer status line runs in 9.5px mono capitals in Bone Faint: "MUZIX · NODE · USER · 870 TRACKS · 42 CHIPTUNES · 61 H · SKIN: BLUES", with a fullscreen hint and an appearance link on the right. It is what makes Muzix feel like a station rather than a file browser, and it stays on every desktop screen.

## Do's and Don'ts

### Do:
- **Do** take every colour, font and radius from the theme variables (`--bg`, `--surface`, `--text`, `--primary`, `--secondary`, `--font-display`, `--font-ui`, `--font-mono`, `--radius`, `--display-case`) so all 98 colour schemes and 25 genre skins work.
- **Do** check new UI under the house scheme, a light skin (punk, classical, country, pop, comedy or kids) and a skin that decorates the frame (death metal's thorns, soundtrack's film strip, punk's tape).
- **Do** keep pages inside the frame on desktop and edge to edge on phones.
- **Do** size page content against the frame with container queries (`cqi`, `@container page`), not the window.
- **Do** take dim, faint, on-accent and error text from the theme (`--text-dim`, `--text-faint`, `--on-primary`, `--on-secondary`, `--error-text`, and `--on-error` on `--error-solid`); never pick a text colour for an accent by hand.
- **Do** keep controls quiet: 38px buttons with 12px labels, 32px icon buttons, outlines before fills, and one Vermilion action per view.
- **Do** keep the broadcast furniture on every desktop screen: the striped logo, the section pills, the footer status line.

### Don't:
- **Don't** hard-code the house hex values in a component; the one sanctioned exception is the bento tiles' fixed dark plate.
- **Don't** put a frame, border or rounded panel around the page on phones.
- **Don't** add shadows to the frame, docks, rows, chips or buttons; shadows are for covers and floating layers.
- **Don't** add kickers to cards, rows, dialogs or controls; they belong above page and section titles.
- **Don't** use the display font or heavy capitals for body copy, or monospace for prose.
- **Don't** add gradient, chrome or textured text outside a skin's headline treatment; the house display type is solid Bone and Marigold.
- **Don't** let Marigold decorate quiet surfaces; it marks what is live, selected or focused.
