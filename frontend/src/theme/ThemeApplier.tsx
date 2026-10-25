/** Applies the active palette or genre skin to <html> and draws the backdrop. */

import { useEffect, useMemo, useState } from "react";
import { usePlayer } from "../store/player";
import { useUi } from "../store/ui";
import { Backdrop } from "./Backdrop";
import { cssVars, palette, type Colors } from "./palettes";
import { pickSkin, SKIN_BY_ID, SYSTEM_ACCENTS, type Skin } from "./skins";

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
  colors: Colors;
  dark: boolean;
}

export function useActiveTheme(): ActiveTheme {
  const { scheme, mode, genreSkins, skinLock, skinRules } = useUi();
  const current = usePlayer((s) => (s.index >= 0 ? s.queue[s.index] : null));
  const systemDark = useSystemDark();
  return useMemo(() => {
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
      return { skin, colors, dark: true };
    }
    const dark = mode === "dark" || (mode === "system" && systemDark);
    const p = palette(scheme);
    return { skin: null, colors: dark ? p.dark : p.light, dark };
  }, [scheme, mode, genreSkins, skinLock, skinRules, current?.key, current?.system, systemDark]);
}

export function ThemeApplier() {
  const theme = useActiveTheme();

  useEffect(() => {
    const root = document.documentElement;
    const vars = cssVars(theme.colors);
    root.classList.add("theme-fade");
    for (const [k, v] of Object.entries(vars)) root.style.setProperty(k, v);
    const s = theme.skin;
    root.dataset.skin = s?.id || "";
    root.dataset.headline = s?.headline || "none";
    root.dataset.frame = s?.frame || "plain";
    root.dataset.artfx = s?.artfx || "none";
    root.dataset.backdrop = s?.backdrop || "space";
    root.style.setProperty("--font-display", s?.display || "'Saira', system-ui, sans-serif");
    root.style.setProperty("--font-ui", s?.ui || "'Saira', system-ui, sans-serif");
    root.style.setProperty("--radius", `${s?.radius ?? 10}px`);
    root.style.setProperty("--display-case", s ? (s.uppercase ? "uppercase" : "none") : "uppercase");
    document.querySelector('meta[name="theme-color"]')?.setAttribute("content", theme.colors.bg);
    const t = window.setTimeout(() => root.classList.remove("theme-fade"), 900);
    return () => window.clearTimeout(t);
  }, [theme]);

  return <Backdrop kind={theme.skin?.backdrop || "space"} />;
}
