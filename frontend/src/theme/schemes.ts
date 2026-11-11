/** Colour schemes of the users' own (backend/muzix/api/schemes.py), as in Hooden: made from one of the
 * schemes, with colours for dark and light, fonts, corners, glass, a frame, a backdrop and a picture. A
 * device uses one by its pref "custom:<id>"; the ones it has met are kept here (and in the browser, so
 * the first paint has it), and the editor's draft is shown in place of everything while it's open. */

import { create } from "zustand";
import { api } from "../api";
import { palette, type Colors } from "./palettes";
import type { BackdropKind, FrameStyle, Headline } from "./skins";

export interface SchemeData {
  base: string;
  modes: "both" | "dark" | "light";
  dark: Colors;
  light: Colors;
  display: string;
  ui: string;
  caps: boolean;
  headline: Headline;
  radius: number;
  glass: number;
  frame: FrameStyle;
  backdrop: BackdropKind | "space";
  picture: { desktop: string; mobile: string; dim: number; blur: number; size: "cover" | "contain" | "tile" };
}

export interface Scheme {
  id: number;
  name: string;
  data: SchemeData;
  shared: boolean;
  mine: boolean;
  owner: { id: number; name: string };
  uses: number;
}

export const CUSTOM = "custom:";

/** The fonts the app carries (styles/fonts.ts), for titles. */
export const DISPLAY_FONTS: { id: string; name: string; css: string }[] = [
  ["saira", "Saira", "'Saira', system-ui, sans-serif"],
  ["bebas-neue", "Bebas Neue", "'Bebas Neue', 'Saira', sans-serif"],
  ["orbitron", "Orbitron", "'Orbitron', 'Saira', sans-serif"],
  ["audiowide", "Audiowide", "'Audiowide', 'Saira', sans-serif"],
  ["monoton", "Monoton", "'Monoton', 'Audiowide', sans-serif"],
  ["bungee", "Bungee", "'Bungee', 'Saira', sans-serif"],
  ["righteous", "Righteous", "'Righteous', 'Saira', sans-serif"],
  ["lilita-one", "Lilita One", "'Lilita One', 'Saira', sans-serif"],
  ["fredoka", "Fredoka", "'Fredoka', 'Saira', sans-serif"],
  ["shrikhand", "Shrikhand", "'Shrikhand', 'Righteous', cursive"],
  ["bangers", "Bangers", "'Bangers', 'Bungee', cursive"],
  ["permanent-marker", "Permanent Marker", "'Permanent Marker', cursive"],
  ["poiret-one", "Poiret One", "'Poiret One', 'Saira', sans-serif"],
  ["limelight", "Limelight", "'Limelight', serif"],
  ["cinzel", "Cinzel", "'Cinzel', serif"],
  ["rye", "Rye", "'Rye', serif"],
  ["new-rocker", "New Rocker", "'New Rocker', serif"],
  ["metal-mania", "Metal Mania", "'Metal Mania', serif"],
  ["pirata-one", "Pirata One", "'Pirata One', serif"],
  ["unifrakturcook", "UnifrakturCook", "'UnifrakturCook', serif"],
  ["press-start-2p", "Press Start 2P", "'Press Start 2P', monospace"],
  ["vt323", "VT323", "'VT323', monospace"],
].map(([id, name, css]) => ({ id, name, css }));

/** And for everything else: the ones that read at body sizes. */
export const UI_FONTS: { id: string; name: string; css: string }[] = [
  ["saira", "Saira", "'Saira', system-ui, sans-serif"],
  ["fredoka", "Fredoka", "'Fredoka', 'Saira', sans-serif"],
  ["cormorant-garamond", "Cormorant Garamond", "'Cormorant Garamond', serif"],
  ["special-elite", "Special Elite", "'Special Elite', monospace"],
  ["vt323", "VT323", "'VT323', monospace"],
].map(([id, name, css]) => ({ id, name, css }));

export const FRAMES: [FrameStyle, string][] = [
  ["plain", "Plain"], ["neon", "Neon"], ["double", "Double line"], ["ornate", "Ornate"], ["deco", "Art deco"],
  ["frost", "Frost"], ["thorns", "Thorns"], ["rivets", "Rivets"], ["tape", "Tape"], ["rope", "Rope"],
  ["film", "Film strip"], ["checker", "Checkerboard"], ["bubbly", "Bubbly"], ["pixel", "Pixels"],
];

export const HEADLINES: [Headline, string][] = [
  ["none", "Plain"], ["neon", "Neon"], ["chrome", "Chrome"], ["stamp", "Stamp"], ["marquee", "Marquee"], ["deco", "Art deco"],
  ["glitch", "Glitch"], ["spray", "Spray paint"], ["comic", "Comic"], ["crayon", "Crayon"], ["drip", "Drip"], ["frost", "Frost"],
  ["pixel", "Pixels"],
];

export const BACKDROPS: [BackdropKind | "space", string][] = [
  ["space", "Nebula"], ["none", "None"], ["stars", "Stars"], ["aurora", "Aurora"], ["sunset", "Sunset grid"], ["grid", "Grid"],
  ["fractal", "Fractal"], ["embers", "Embers"], ["snow", "Snow"], ["lightning", "Lightning"], ["smoke", "Smoke"],
  ["dust", "Dust"], ["bubbles", "Bubbles"], ["groove", "Groove"], ["film", "Film"], ["rasta", "Waves"], ["checker", "Checkers"],
  ["halftone", "Halftone"], ["xerox", "Xerox"], ["marble", "Marble"], ["paper", "Paper"],
];

export const fontCss = (id: string, list = DISPLAY_FONTS) => list.find((f) => f.id === id)?.css ?? list[0].css;

/** A palette's nine colours, without stripes of its own (a scheme of the user's takes them from the colours). */
function roles(c: Colors): Colors {
  const { stripes, ...rest } = c;
  void stripes;
  return rest;
}

/** A scheme to start from: the colours of one of the app's, the house's look for the rest. */
export function fromPalette(slug: string): SchemeData {
  const p = palette(slug);
  return {
    base: p.slug, modes: "both", dark: roles(p.dark), light: roles(p.light), display: "saira", ui: "saira", caps: true,
    headline: "none", radius: 10, glass: 42, frame: "plain", backdrop: "space",
    picture: { desktop: "", mobile: "", dim: 35, blur: 0, size: "cover" },
  };
}

const KEPT = "muzix.schemes";

function kept(): Record<number, Scheme> {
  try {
    return JSON.parse(localStorage.getItem(KEPT) || "{}");
  } catch {
    return {};
  }
}

interface SchemesState {
  known: Record<number, Scheme>;      // the ones this device has met
  missing: Set<number>;               // gone, or not shared any more
  draft: SchemeData | null;           // the editor's, shown in place of everything while it's open
  meet: (list: Scheme[]) => void;
  setDraft: (d: SchemeData | null) => void;
}

export const useSchemes = create<SchemesState>((set, get) => ({
  known: kept(),
  missing: new Set(),
  draft: null,
  meet: (list) => {
    const known = { ...get().known };
    for (const s of list) known[s.id] = s;
    set({ known });
    try {
      localStorage.setItem(KEPT, JSON.stringify(known));
    } catch {
      /* private mode */
    }
  },
  setDraft: (draft) => set({ draft }),
}));

const asking = new Set<number>();

/** A scheme a device uses, fetched (again) when it hasn't got it, or to hear of changes. */
export function fetchScheme(id: number) {
  if (asking.has(id)) return;
  asking.add(id);
  api.get<Scheme>(`/api/schemes/${id}`)
    .then((s) => useSchemes.getState().meet([s]))
    .catch(() => useSchemes.setState((st) => ({ missing: new Set([...st.missing, id]) })))
    .finally(() => asking.delete(id));
}

export function customId(scheme: string): number | null {
  return scheme.startsWith(CUSTOM) ? Number(scheme.slice(CUSTOM.length)) || null : null;
}
