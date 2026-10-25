/** Genre skins: the whole app restyled after what's playing.
 *
 * A skin sets a palette, display/UI fonts and a few visual treatments that
 * styles.css and skins.css key on (data-* attributes on <html>), plus an
 * animated backdrop drawn by <Backdrop/>. Which skin plays comes from the
 * track's genre folder, its artist's detailed genre tags and, for VGM, the
 * system it's from.
 */

import type { Colors } from "./palettes";

export type Headline = "none" | "drip" | "frost" | "chrome" | "stamp" | "neon" | "pixel" | "deco" | "glitch" | "marquee" | "spray" | "comic" | "crayon";
export type FrameStyle = "plain" | "thorns" | "frost" | "rivets" | "tape" | "neon" | "pixel" | "deco" | "double" | "ornate" | "film" | "rope" | "checker" | "bubbly";
export type ArtFx = "none" | "grit" | "mono" | "duotone" | "sepia" | "neon" | "pixel" | "warm";
export type BackdropKind = "none" | "embers" | "snow" | "lightning" | "smoke" | "xerox" | "halftone" | "aurora" | "fractal" | "grid" | "sunset" | "stars" | "groove" | "marble" | "paper" | "rasta" | "checker" | "bubbles" | "film" | "dust";

export interface Skin {
  id: string;
  name: string;
  blurb: string;               // shown in the footer / appearance settings
  colors: Colors;
  display: string;             // headline font stack
  ui?: string;                 // body font override
  headline: Headline;
  frame: FrameStyle;
  artfx: ArtFx;
  backdrop: BackdropKind;
  radius?: number;             // corner radius override (px)
  uppercase?: boolean;         // display text in capitals
}

const c = (bg: string, surface: string, text: string, primary: string, secondary: string,
           border: string, error = "#ef4444", warning = "#f59e0b", success = "#22c55e"): Colors =>
  ({ bg, surface, text, primary, secondary, border, error, warning, success });

export const SKINS: Skin[] = [
  { id: "death-metal", name: "Death metal", blurb: "Bone, blood and blackletter",
    colors: c("#0b0706", "#170d0b", "#e8ddcc", "#b3120d", "#6e0b07", "#4a221b", "#ff3b30", "#c28a2c", "#6b8f3a"),
    display: "'Pirata One', 'UnifrakturCook', serif", headline: "drip", frame: "thorns", artfx: "grit", backdrop: "embers", radius: 2 },
  { id: "black-metal", name: "Black metal", blurb: "Corpse paint and frozen forests",
    colors: c("#050505", "#0f0f0f", "#ececec", "#d8d8d8", "#7c7c7c", "#333333", "#bdbdbd", "#a0a0a0", "#c8c8c8"),
    display: "'UnifrakturCook', 'Pirata One', serif", headline: "frost", frame: "frost", artfx: "mono", backdrop: "snow", radius: 0 },
  { id: "heavy-metal", name: "Heavy metal", blurb: "Chrome, leather and lightning",
    colors: c("#0c0e13", "#171b25", "#f4f4f6", "#e6c35c", "#c8102e", "#4b5266", "#ff4d4d", "#ffb703", "#7bd389"),
    display: "'Metal Mania', 'New Rocker', serif", headline: "chrome", frame: "rivets", artfx: "none", backdrop: "lightning", radius: 4, uppercase: true },
  { id: "doom", name: "Doom & stoner", blurb: "Occult haze from 1971",
    colors: c("#120a16", "#1d1222", "#f0d9b5", "#e8772e", "#8e44ad", "#523359", "#ff5e5b", "#f4a261", "#9bc53d"),
    display: "'New Rocker', 'Rye', serif", headline: "marquee", frame: "double", artfx: "warm", backdrop: "smoke", radius: 6 },
  { id: "punk", name: "Punk", blurb: "Xerox, tape and safety pins",
    colors: c("#f2efe6", "#ffffff", "#111111", "#ff2e88", "#ffe600", "#111111", "#e60000", "#ff9f1c", "#1a8f3c"),
    display: "'Permanent Marker', 'Special Elite', cursive", ui: "'Special Elite', monospace", headline: "stamp", frame: "tape", artfx: "mono", backdrop: "xerox", radius: 0, uppercase: true },
  { id: "rock", name: "Rock", blurb: "Tour posters and worn denim",
    colors: c("#16110d", "#221a14", "#f3e3c3", "#e3a23b", "#b5452b", "#4d3a2a", "#e5533d", "#f2c14e", "#7fb069"),
    display: "'Bebas Neue', 'Saira', sans-serif", headline: "stamp", frame: "double", artfx: "warm", backdrop: "halftone", radius: 6, uppercase: true },
  { id: "prog", name: "Prog", blurb: "Floating islands and gatefold sleeves",
    colors: c("#0e1621", "#16222f", "#eaf2e8", "#7fd1b9", "#e3b04b", "#3a5163", "#f07167", "#f6bd60", "#84a98c"),
    display: "'Righteous', 'Saira', sans-serif", headline: "none", frame: "ornate", artfx: "none", backdrop: "aurora", radius: 18 },
  { id: "psytrance", name: "Psytrance", blurb: "UV paint and fractal mandalas",
    colors: c("#07020f", "#120726", "#f6eeff", "#ff2bd6", "#19f0ff", "#4a2a7a", "#ff4d6d", "#fff200", "#39ff14"),
    display: "'Audiowide', 'Orbitron', sans-serif", headline: "neon", frame: "neon", artfx: "neon", backdrop: "fractal", radius: 14, uppercase: true },
  { id: "synthwave", name: "Synthwave", blurb: "Sunsets on a neon grid",
    colors: c("#140a26", "#1f1238", "#ffeaff", "#ff4fd8", "#2de2e6", "#5a2d82", "#ff5c8a", "#ffb347", "#72f1b8"),
    display: "'Monoton', 'Audiowide', sans-serif", headline: "neon", frame: "neon", artfx: "neon", backdrop: "sunset", radius: 10, uppercase: true },
  { id: "electronic", name: "Electronic", blurb: "Acid green on black",
    colors: c("#050607", "#0d1113", "#e6ffe9", "#3cff6e", "#00b3ff", "#1f3a28", "#ff4f4f", "#ffd23f", "#3cff6e"),
    display: "'Orbitron', 'Audiowide', sans-serif", headline: "glitch", frame: "plain", artfx: "none", backdrop: "grid", radius: 4, uppercase: true },
  { id: "ambient", name: "Ambient & chill", blurb: "Slow light over still water",
    colors: c("#0f1a1e", "#16252b", "#e3f1f0", "#8fd3c7", "#b9a6e3", "#2c4249", "#f28482", "#f6bd60", "#84dcc6"),
    display: "'Poiret One', 'Saira', sans-serif", headline: "none", frame: "plain", artfx: "none", backdrop: "aurora", radius: 22 },
  { id: "hip-hop", name: "Hip-hop", blurb: "Gold chains and fresh paint",
    colors: c("#0e0e0e", "#181818", "#ffffff", "#ffd400", "#ff3b3b", "#333333", "#ff3b3b", "#ffd400", "#3ddc84"),
    display: "'Bungee', 'Bebas Neue', sans-serif", headline: "spray", frame: "plain", artfx: "none", backdrop: "halftone", radius: 8, uppercase: true },
  { id: "jazz", name: "Jazz", blurb: "Blue Note duotones and smoke",
    colors: c("#0d1b2a", "#13263a", "#f4efe6", "#4cc9f0", "#f7b32b", "#2b4a6b", "#ef476f", "#f7b32b", "#06d6a0"),
    display: "'Limelight', 'Poiret One', serif", headline: "deco", frame: "deco", artfx: "duotone", backdrop: "smoke", radius: 2 },
  { id: "blues", name: "Blues", blurb: "Juke joints at midnight",
    colors: c("#1a120c", "#24190f", "#f2e3c6", "#3d7cc9", "#d4a24c", "#4a3626", "#d1495b", "#edae49", "#66a182"),
    display: "'Rye', 'New Rocker', serif", headline: "marquee", frame: "double", artfx: "sepia", backdrop: "smoke", radius: 4 },
  { id: "soul", name: "Soul & funk", blurb: "1974, orange and brown",
    colors: c("#2a1608", "#3a1f0c", "#ffeccc", "#ff8c1a", "#e63946", "#6b3b16", "#e63946", "#ffd166", "#90be6d"),
    display: "'Shrikhand', 'Righteous', cursive", headline: "none", frame: "bubbly", artfx: "warm", backdrop: "groove", radius: 24 },
  { id: "classical", name: "Classical", blurb: "Marble halls and gilt edges",
    colors: c("#f5f1e8", "#fffdf8", "#2b2620", "#8c6d2f", "#5b3a29", "#d9cfbd", "#9b2226", "#b08900", "#3a5a40"),
    display: "'Cinzel', 'Cormorant Garamond', serif", ui: "'Cormorant Garamond', serif", headline: "deco", frame: "ornate", artfx: "none", backdrop: "marble", radius: 2, uppercase: true },
  { id: "country", name: "Country & folk", blurb: "Kraft paper and campfires",
    colors: c("#f3e6cf", "#fbf3e3", "#3b2414", "#b5541b", "#4f6d3a", "#c9a978", "#a4161a", "#bc6c25", "#4f6d3a"),
    display: "'Rye', 'Cinzel', serif", headline: "stamp", frame: "rope", artfx: "sepia", backdrop: "paper", radius: 6, uppercase: true },
  { id: "reggae", name: "Reggae", blurb: "Red, gold and green",
    colors: c("#0f140c", "#172014", "#f6f1e1", "#f5c518", "#1fa34a", "#3a4a2a", "#d7263d", "#f5c518", "#1fa34a"),
    display: "'Lilita One', 'Righteous', sans-serif", headline: "none", frame: "plain", artfx: "warm", backdrop: "rasta", radius: 16 },
  { id: "ska", name: "Ska", blurb: "Two-tone checkerboard",
    colors: c("#0d0d0d", "#161616", "#fafafa", "#e10600", "#fafafa", "#6a6a6a", "#e10600", "#ffd400", "#4caf50"),
    display: "'Bebas Neue', 'Bungee', sans-serif", headline: "stamp", frame: "checker", artfx: "mono", backdrop: "checker", radius: 0, uppercase: true },
  { id: "pop", name: "Pop", blurb: "Bubblegum and glitter",
    colors: c("#fff0f7", "#ffffff", "#2a1238", "#ff3e9a", "#7b5cff", "#f3c6e0", "#ff3d68", "#ffb000", "#00c48c"),
    display: "'Fredoka', 'Saira', sans-serif", headline: "none", frame: "bubbly", artfx: "none", backdrop: "bubbles", radius: 26 },
  { id: "soundtrack", name: "Soundtrack", blurb: "Letterbox, film grain and gold",
    colors: c("#070708", "#111114", "#e8e2d4", "#d4af37", "#8a1c1c", "#2c2a28", "#c1121f", "#d4af37", "#6a994e"),
    display: "'Bebas Neue', 'Cinzel', sans-serif", headline: "marquee", frame: "film", artfx: "none", backdrop: "film", radius: 0, uppercase: true },
  { id: "vgm", name: "Chiptune", blurb: "8-bit sprites and CRT glow",
    colors: c("#0f0f23", "#1b1b3a", "#e8f4ff", "#ffcc00", "#00e0ff", "#4040a0", "#ff4d4d", "#ffcc00", "#41f75d"),
    display: "'Press Start 2P', 'VT323', monospace", ui: "'VT323', monospace", headline: "pixel", frame: "pixel", artfx: "pixel", backdrop: "stars", radius: 0, uppercase: true },
  { id: "world", name: "World", blurb: "Woven colour and warm sun",
    colors: c("#1a0f0a", "#26160e", "#f7e8d3", "#e07a2e", "#2a9d8f", "#5a3a26", "#e63946", "#f4a261", "#2a9d8f"),
    display: "'Righteous', 'Lilita One', sans-serif", headline: "none", frame: "rope", artfx: "warm", backdrop: "dust", radius: 12 },
  { id: "comedy", name: "Comedy", blurb: "Ben-Day dots and POW",
    colors: c("#fff7d6", "#ffffff", "#111111", "#ff2a2a", "#1e6bff", "#111111", "#ff2a2a", "#ffb800", "#00b050"),
    display: "'Bangers', 'Bungee', cursive", headline: "comic", frame: "double", artfx: "none", backdrop: "halftone", radius: 4, uppercase: true },
  { id: "kids", name: "Children's", blurb: "Crayons and soap bubbles",
    colors: c("#fffaf0", "#ffffff", "#2d2a4a", "#ff7a59", "#4cc3ff", "#e9dcc8", "#ff5c5c", "#ffd23f", "#7ad151"),
    display: "'Fredoka', 'Lilita One', sans-serif", headline: "crayon", frame: "bubbly", artfx: "none", backdrop: "bubbles", radius: 28 },
];

export const SKIN_BY_ID = new Map(SKINS.map((s) => [s.id, s]));

// VGM systems get their own accent on top of the chiptune skin
export const SYSTEM_ACCENTS: Record<string, Partial<Colors>> = {
  "Game Boy": { bg: "#0f1f0f", surface: "#1a301a", text: "#e0f8d0", primary: "#88c070", secondary: "#c4f0a8", border: "#346856" },
  "Commodore 64": { bg: "#2a2a7a", surface: "#3a3a9a", text: "#d8d8ff", primary: "#a0a0ff", secondary: "#ffffff", border: "#6c6cd0" },
  "NES / Famicom": { primary: "#e40058", secondary: "#f8b800" },
  "Super Nintendo": { primary: "#b7a8ff", secondary: "#f25c54" },
  "Sega Mega Drive / Genesis": { primary: "#2b6cff", secondary: "#ff3b3b" },
  "Amiga / PC tracker": { bg: "#0055aa", surface: "#1a6ac0", text: "#ffffff", primary: "#ff8800", secondary: "#ffffff", border: "#80b0ff" },
  "Atari ST": { primary: "#9be564", secondary: "#e4e4e4" },
  "ZX Spectrum": { primary: "#00d7d7", secondary: "#d7d700" },
};

// ---------------------------------------------------------------- choosing a skin

/** Ordered rules: first match wins. Patterns are tested against the
 * lower-cased artist tags and genre of what's playing. */
const RULES: [RegExp, string][] = [
  [/black metal|blackgaze|depressive|dsbm/, "black-metal"],
  [/death metal|deathcore|grindcore|goregrind|brutal death|melodeath|death 'n' roll/, "death-metal"],
  [/doom|stoner|sludge|drone metal|occult/, "doom"],
  [/thrash|speed metal|heavy metal|nwobhm|power metal|glam metal|hair metal|traditional metal/, "heavy-metal"],
  [/metalcore|nu metal|groove metal|industrial metal|\bmetal\b/, "heavy-metal"],
  [/punk|hardcore|oi!|riot grrrl|crust/, "punk"],
  [/psytrance|psychedelic trance|goa|psybient|psychill|full-on|dark psy|forest psy|psydub|\bpsy\b/, "psytrance"],
  [/synthwave|retrowave|outrun|synth-?pop|new wave|darkwave|italo/, "synthwave"],
  [/ambient|chillout|chill-out|downtempo|trip-?hop|lounge|new age/, "ambient"],
  [/techno|house|trance|edm|drum and bass|drum'n'bass|dnb|jungle|dubstep|electro|idm|breakbeat|electronic/, "electronic"],
  [/progressive rock|prog rock|\bprog\b|art rock|symphonic rock/, "prog"],
  [/hip.?hop|\brap\b|trap|grime|boom bap/, "hip-hop"],
  [/\bska\b|two.?tone|rocksteady/, "ska"],
  [/reggae|dancehall|\bdub\b|roots/, "reggae"],
  [/\bblues\b|delta blues|chicago blues/, "blues"],
  [/jazz|bebop|swing|big band|fusion|bossa/, "jazz"],
  [/funk|disco|\bsoul\b|motown|r&b|rhythm and blues|neo-soul/, "soul"],
  [/classical|baroque|opera|symphon|orchestral|chamber|romantic era|contemporary classical/, "classical"],
  [/soundtrack|film score|\bscore\b|\bost\b|musical/, "soundtrack"],
  [/country|bluegrass|americana|western|\bfolk\b|singer-songwriter|visor|celtic/, "country"],
  [/world|latin|balkan|afro|flamenco|tango|salsa|cuban/, "world"],
  [/comedy|humou?r|stand-up|parody/, "comedy"],
  [/children|\bkids\b|barn/, "kids"],
  [/pop|schlager|dansband|eurodance|bubblegum/, "pop"],
  [/rock|grunge|alternative|indie|garage|britpop|emo/, "rock"],
];

// genre folders (from the library's organisation) when tags don't decide
const FOLDER_SKIN: Record<string, string> = {
  "Metal": "heavy-metal", "Rock": "rock", "Pop": "pop", "Psytrance": "psytrance", "Electronic": "electronic",
  "Hip-Hop": "hip-hop", "Jazz & Blues": "jazz", "Soul & R&B": "soul", "Country & Folk": "country",
  "Classical": "classical", "Soundtrack": "soundtrack", "Reggae & Ska": "reggae", "World": "world",
  "Comedy": "comedy", "Children's": "kids", "VGM": "vgm",
};

export interface SkinContext {
  kind?: string;          // music | vgm | book | episode | radio | spotify
  genre?: string;
  tags?: string[];
  system?: string;
}

export function pickSkin(ctx: SkinContext | null, extraRules: Record<string, string> = {}): string | null {
  if (!ctx) return null;
  if (ctx.kind === "vgm") return "vgm";
  if (ctx.kind === "book" || ctx.kind === "episode") return null;
  const tags = [...(ctx.tags || []), ctx.genre || ""].map((t) => t.toLowerCase()).filter(Boolean);
  const text = tags.join(" | ");
  for (const [tag, skin] of Object.entries(extraRules)) {
    if (SKIN_BY_ID.has(skin) && tags.some((t) => t.includes(tag.toLowerCase()))) return skin;
  }
  // the artist's strongest tags are more specific than the folder genre
  const specific = (ctx.tags || []).slice(0, 4).map((t) => t.toLowerCase()).join(" | ");
  for (const [re, skin] of RULES) if (re.test(specific)) return skin;
  if (ctx.genre && FOLDER_SKIN[ctx.genre]) return FOLDER_SKIN[ctx.genre];
  for (const [re, skin] of RULES) if (re.test(text)) return skin;
  return null;
}
