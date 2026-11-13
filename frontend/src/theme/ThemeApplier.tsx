/** Applies the active palette, the user's own scheme or a genre skin to <html> and draws the backdrop
 * (and an own scheme's picture). */

import { type CSSProperties, useEffect, useMemo, useState } from "react";
import { usePlayer } from "../store/player";
import { useUi } from "../store/ui";
import { Backdrop } from "./Backdrop";
import { cssVars, palette, type Colors } from "./palettes";
import { customId, fetchScheme, fontCss, type SchemeData, UI_FONTS, useSchemes } from "./schemes";
import { pickSkin, SKIN_BY_ID, SYSTEM_ACCENTS, type Skin } from "./skins";

const SAIRA = "'Saira', system-ui, sans-serif";

function useSystemDark() {
  const mq = useMemo(() => window.matchMedia("(prefers-color-scheme: dark)"), []);
  const [dark, setDark] = useState(mq.matches);
  useEffect(() => {
    const on = (e: MediaQueryListEvent) => setDark(e.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, [mq]);
  return dark;
}

export interface ActiveTheme {
  skin: Skin | null;
  custom: SchemeData | null;      // the user's own scheme (theme/schemes.ts)
  colors: Colors;
  dark: boolean;
}

export function useActiveTheme(): ActiveTheme {
  const { scheme, mode, genreSkins, skinLock, skinRules } = useUi();
  const current = usePlayer((s) => (s.index >= 0 ? s.queue[s.index] : null));
  const systemDark = useSystemDark();
  const draft = useSchemes((s) => s.draft);
  const id = customId(scheme);
  const own = useSchemes((s) => (id && !s.missing.has(id) ? s.known[id]?.data ?? null : null));
  return useMemo(() => {
    const wantDark = mode === "dark" || (mode === "system" && systemDark);
    const ownLook = (x: SchemeData): ActiveTheme => {
      const dark = x.modes === "dark" || (x.modes === "both" && wantDark);
      return { skin: null, custom: x, colors: dark ? x.dark : x.light, dark };
    };
    // the scheme being made shows over everything, a skin too
    if (draft) return ownLook(draft);
    let skin: Skin | null = null;
    if (skinLock && SKIN_BY_ID.has(skinLock)) skin = SKIN_BY_ID.get(skinLock)!;
    else if (genreSkins && current) {
      const kind = current.kind === "track" || current.kind === "online" ? current.trackKind : current.kind;
      const id = pickSkin({ kind, genre: current.genre, tags: current.tags, system: current.system }, skinRules);
      skin = id ? SKIN_BY_ID.get(id) || null : null;
    }
    if (skin) {
      let colors = skin.colors;
      if (skin.id === "vgm" && current?.system && SYSTEM_ACCENTS[current.system])
        colors = { ...colors, ...SYSTEM_ACCENTS[current.system] };
      return { skin, custom: null, colors, dark: true };
    }
    if (own) return ownLook(own);
    const p = palette(scheme);
    return { skin: null, custom: null, colors: wantDark ? p.dark : p.light, dark: wantDark };
  }, [scheme, mode, genreSkins, skinLock, skinRules, current?.key, current?.system, systemDark, draft, own]);
}

/** An own scheme's picture, behind everything in place of the backdrop: a phone's own if it has one. */
function SchemePicture({ p }: { p: SchemeData["picture"] }) {
  const style = {
    "--pic": `url("${p.desktop || p.mobile}")`, "--pic-phone": `url("${p.mobile || p.desktop}")`,
    "--pic-dim": p.dim / 100, "--pic-blur": `${p.blur}px`,
  } as CSSProperties;
  return <div className={`scheme-picture fit-${p.size}`} style={style} aria-hidden="true" />;
}

export function ThemeApplier() {
  const theme = useActiveTheme();
  const id = customId(useUi((s) => s.scheme));
  const potato = useUi((s) => s.potato);
  useEffect(() => {
    if (id) fetchScheme(id);      // as it is now (its owner may have changed it)
  }, [id]);
  useEffect(() => {
    document.documentElement.classList.toggle("potato", potato);    // base.css: no blur, nothing moving
  }, [potato]);

  useEffect(() => {
    const root = document.documentElement;
    const vars = cssVars(theme.colors);
    root.classList.add("theme-fade");
    for (const [k, v] of Object.entries(vars)) root.style.setProperty(k, v);
    const s = theme.skin;
    const x = theme.custom;
    root.dataset.skin = s?.id || "";
    root.dataset.headline = s?.headline || x?.headline || "none";
    root.dataset.frame = s?.frame || x?.frame || "plain";
    root.dataset.backdrop = s?.backdrop || (x && pictured(x) ? "none" : x?.backdrop) || "space";
    root.style.setProperty("--font-display", s?.display || (x ? fontCss(x.display) : SAIRA));
    root.style.setProperty("--font-ui", s?.ui || (x ? fontCss(x.ui, UI_FONTS) : SAIRA));
    root.style.setProperty("--radius", `${s?.radius ?? x?.radius ?? 10}px`);
    root.style.setProperty("--display-case", s ? (s.uppercase ? "uppercase" : "none") : x && !x.caps ? "none" : "uppercase");
    // how much of the backdrop shows through the frame
    if (x) root.style.setProperty("--frame-bg", `color-mix(in srgb, var(--bg) ${x.glass}%, transparent)`);
    else root.style.removeProperty("--frame-bg");
    document.querySelector('meta[name="theme-color"]')?.setAttribute("content", theme.colors.bg);
    const t = window.setTimeout(() => root.classList.remove("theme-fade"), 900);
    return () => window.clearTimeout(t);
  }, [theme]);

  const x = theme.custom;
  return (
    <>
      <Backdrop kind={theme.skin?.backdrop || (x && pictured(x) ? "none" : x?.backdrop) || "space"} still={potato} />
      {x && pictured(x) && <SchemePicture p={x.picture} />}
    </>
  );
}

const pictured = (x: SchemeData) => !!(x.picture.desktop || x.picture.mobile);
