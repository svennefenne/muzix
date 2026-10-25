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

/** WCAG contrast ratio between two colours (1 to 21). */
export function contrast(a: string, b: string) {
  const [x, y] = [lum(hexToRgb(a)), lum(hexToRgb(b))].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
}

/** Black or white, whichever reads better on `hex`. */
export function onColor(hex: string) {
  return contrast("#0b0b0f", hex) >= contrast("#ffffff", hex) ? "#0b0b0f" : "#ffffff";
}

export function mix(a: string, b: string, t: number) {
  const x = hexToRgb(a);
  const y = hexToRgb(b);
  const c = x.map((v, i) => Math.round(v + (y[i] - v) * t));
  return "#" + c.map((v) => v.toString(16).padStart(2, "0")).join("");
}

/** The text colour faded `t` of the way to the background, but no further than still
 * reads at 4.5:1 on both the background and the surface (some schemes start out low). */
function fade(c: Colors, t: number) {
  for (; t > 0; t -= 0.01) {
    const f = mix(c.text, c.bg, t);
    if (Math.min(contrast(f, c.bg), contrast(f, c.surface)) >= 4.5) return f;
  }
  return c.text;
}

/** `hex` moved toward `to` just far enough to read at `ratio` on each colour in `on`. */
function legible(hex: string, to: string, on: string[], ratio = 4.5) {
  for (let t = 0; t <= 1; t += 0.02) {
    const c = mix(hex, to, t);
    if (on.every((b) => contrast(c, b) >= ratio)) return c;
  }
  return to;
}

/** CSS custom properties for a set of colours. */
export function cssVars(raw: Colors): Record<string, string> {
  const ink = onColor(raw.bg) === "#ffffff" ? "#ffffff" : "#000000";
  // a few imported schemes set their text below 4.5:1; those are lifted to 7:1 so the
  // dim and faint shades still have room to step down from it
  const weak = Math.min(contrast(raw.text, raw.bg), contrast(raw.text, raw.surface)) < 4.5;
  const c = weak ? { ...raw, text: legible(raw.text, ink, [raw.bg, raw.surface], 7) } : raw;
  const dark = isDark(c.bg);
  const onError = onColor(c.error);
  return {
    "--bg": c.bg,
    "--bg-deep": mix(c.bg, dark ? "#000000" : "#ffffff", dark ? 0.35 : 0.5),
    "--surface": c.surface,
    "--surface-2": mix(c.surface, c.text, dark ? 0.06 : 0.04),
    "--surface-3": mix(c.surface, c.text, dark ? 0.12 : 0.08),
    "--text": c.text,
    "--text-dim": fade(c, 0.3),
    "--text-faint": fade(c, 0.55),
    "--primary": c.primary,
    "--on-primary": onColor(c.primary),
    "--secondary": c.secondary,
    "--on-secondary": onColor(c.secondary),
    "--error": c.error,
    "--error-text": legible(c.error, ink, [c.bg, c.surface]),   // red words on the page
    "--error-solid": legible(c.error, onError === "#ffffff" ? "#000000" : "#ffffff", [onError]),   // a red notice
    "--on-error": onError,
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
