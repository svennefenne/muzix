import { create } from "zustand";
import { api } from "../api";
import type { BrowsePref, LibraryView, Prefs, User } from "../types";

type Mode = "system" | "light" | "dark";

interface UiState {
  user: User | null;
  siteName: string;
  scheme: string;
  mode: Mode;
  genreSkins: boolean;
  skinLock: string;              // "" follows the music
  skinRules: Record<string, string>;
  visualizer: boolean;
  quality: NonNullable<Prefs["quality"]>;
  libraryView: LibraryView;
  browse: Record<string, BrowsePref>;
  sidebarCollapsed: boolean;
  npPanel: boolean;
  queueOpen: boolean;
  nowPlayingOpen: boolean;
  toast: { text: string; kind: "info" | "error"; id: number } | null;
  setUser: (u: User | null) => void;
  setPref: <K extends keyof Prefs>(key: K, value: Prefs[K]) => void;
  setBrowse: (key: string, patch: BrowsePref) => void;
  setQueueOpen: (v: boolean) => void;
  setNowPlayingOpen: (v: boolean) => void;
  notify: (text: string, kind?: "info" | "error") => void;
}

const LOCAL = "muzix.prefs";

function localPrefs(): Prefs {
  try {
    return JSON.parse(localStorage.getItem(LOCAL) || "{}");
  } catch {
    return {};
  }
}

let saveTimer: number | undefined;
let pending: Prefs = {};

function persist(prefs: Prefs) {
  try {
    localStorage.setItem(LOCAL, JSON.stringify({ ...localPrefs(), ...prefs }));
  } catch {
    /* private mode */
  }
  pending = { ...pending, ...prefs };
  window.clearTimeout(saveTimer);
  saveTimer = window.setTimeout(() => {
    const body = pending;
    pending = {};
    if (useUi.getState().user) api.patch("/api/me/prefs", body).catch(() => {});
  }, 600);
}

const initial = localPrefs();

export const useUi = create<UiState>((set, get) => ({
  user: null,
  siteName: "Muzix",
  scheme: initial.scheme || "muzix",
  mode: initial.mode || "system",
  genreSkins: initial.genre_skins ?? true,
  skinLock: initial.skin_lock || "",
  skinRules: {},
  visualizer: initial.visualizer ?? true,
  quality: initial.quality || "original",
  libraryView: initial.library_view || "albums",
  browse: initial.browse || {},
  sidebarCollapsed: initial.sidebar_collapsed ?? false,
  npPanel: initial.np_panel ?? true,
  queueOpen: false,
  nowPlayingOpen: false,
  toast: null,
  setUser: (u) => {
    set({ user: u });
    const p = u?.prefs || {};
    set({
      scheme: p.scheme ?? get().scheme,
      mode: p.mode ?? get().mode,
      genreSkins: p.genre_skins ?? get().genreSkins,
      skinLock: p.skin_lock ?? get().skinLock,
      visualizer: p.visualizer ?? get().visualizer,
      quality: p.quality ?? get().quality,
      libraryView: p.library_view ?? get().libraryView,
      browse: p.browse ?? get().browse,
      sidebarCollapsed: p.sidebar_collapsed ?? get().sidebarCollapsed,
      npPanel: p.np_panel ?? get().npPanel,
    });
  },
  setPref: (key, value) => {
    const map: Partial<Record<keyof Prefs, keyof UiState>> = {
      scheme: "scheme", mode: "mode", genre_skins: "genreSkins", skin_lock: "skinLock",
      visualizer: "visualizer", quality: "quality", library_view: "libraryView",
      sidebar_collapsed: "sidebarCollapsed", np_panel: "npPanel",
    };
    const field = map[key];
    if (field) set({ [field]: value } as Partial<UiState>);
    persist({ [key]: value } as Prefs);
  },
  setBrowse: (key, patch) => {
    const browse = { ...get().browse, [key]: { ...get().browse[key], ...patch } };
    set({ browse });
    persist({ browse });
  },
  setQueueOpen: (v) => set({ queueOpen: v }),
  setNowPlayingOpen: (v) => set({ nowPlayingOpen: v }),
  notify: (text, kind = "info") => {
    const id = Date.now();
    set({ toast: { text, kind, id } });
    window.setTimeout(() => {
      if (get().toast?.id === id) set({ toast: null });
    }, kind === "error" ? 6000 : 3500);
  },
}));

export function savePref<K extends keyof Prefs>(key: K, value: Prefs[K]) {
  persist({ [key]: value } as Prefs);
}
