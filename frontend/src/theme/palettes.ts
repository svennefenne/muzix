/** Colour schemes: Muzix's own plus the 97 dual light/dark palettes of
 * claude-desktop-extra (github.com/patrickjaja/claude-desktop-extra, MIT;
 * its community palettes come from github.com/noctalia-dev/community-palettes). */

import raw from "./palettes.json";

export interface Colors {
  bg: string;
  surface: string;
  text: string;
  primary: string;
  secondary: string;
  error: string;
  warning: string;
  success: string;
  border: string;
}

export interface Palette {
  slug: string;
  name: string;
  category: "muzix" | "builtin" | "gaming" | "community";
  dark: Colors;
  light: Colors;
}

const MUZIX: Palette = {
  slug: "muzix",
  name: "Muzix",
  category: "muzix",
  dark: {
    bg: "#0a1020", surface: "#121b2e", text: "#f1e7d0", primary: "#f2a93b", secondary: "#e4572e",
    error: "#ef5350", warning: "#f2c14e", success: "#4fb286", border: "#33405c",
  },
  light: {
    bg: "#f6efe1", surface: "#fffaf0", text: "#1a2238", primary: "#c9781b", secondary: "#c8431f",
    error: "#c62828", warning: "#a8770e", success: "#2e7d5b", border: "#c9bea6",
  },
};

export const PALETTES: Palette[] = [MUZIX, ...(raw as Palette[])];
export const BY_SLUG = new Map(PALETTES.map((p) => [p.slug, p]));

export function palette(slug: string | undefined): Palette {
  return (slug && BY_SLUG.get(slug)) || MUZIX;
}

// ---------------------------------------------------------------- colour maths

export function hexToRgb(hex: string): [number, number, number] {
  const h = hex.replace("#", "");
  const n = parseInt(h.length === 3 ? h.split("").map((c) => c + c).join("") : h, 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function lum([r, g, b]: [number, number, number]) {
  const f = (c: number) => {
    c /= 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
}

export function isDark(hex: string) {
  return lum(hexToRgb(hex)) < 0.25;
}

/** Black or white, whichever reads better on `hex`. */
export function onColor(hex: string) {
  return lum(hexToRgb(hex)) > 0.35 ? "#0b0b0f" : "#ffffff";
}

export function mix(a: string, b: string, t: number) {
  const x = hexToRgb(a);
  const y = hexToRgb(b);
  const c = x.map((v, i) => Math.round(v + (y[i] - v) * t));
  return "#" + c.map((v) => v.toString(16).padStart(2, "0")).join("");
}

/** CSS custom properties for a set of colours. */
export function cssVars(c: Colors): Record<string, string> {
  const dark = isDark(c.bg);
  return {
    "--bg": c.bg,
    "--bg-deep": mix(c.bg, dark ? "#000000" : "#ffffff", dark ? 0.35 : 0.5),
    "--surface": c.surface,
    "--surface-2": mix(c.surface, c.text, dark ? 0.06 : 0.04),
    "--surface-3": mix(c.surface, c.text, dark ? 0.12 : 0.08),
    "--text": c.text,
    "--text-dim": mix(c.text, c.bg, 0.3),
    "--text-faint": mix(c.text, c.bg, 0.55),
    "--primary": c.primary,
    "--on-primary": onColor(c.primary),
    "--secondary": c.secondary,
    "--on-secondary": onColor(c.secondary),
    "--error": c.error,
    "--warning": c.warning,
    "--success": c.success,
    "--border": mix(c.border, c.bg, dark ? 0.55 : 0.35),
    "--border-strong": mix(c.border, c.bg, 0.25),
    "--frame": mix(c.border, c.bg, dark ? 0.45 : 0.3),
    "--glow": c.primary + "55",
    "--stripe-1": c.text,
    "--stripe-2": c.warning,
    "--stripe-3": c.primary,
    "--stripe-4": c.error,
    "--stripe-5": c.success,
    "--stripe-6": c.secondary,
    "color-scheme": dark ? "dark" : "light",
  };
}
