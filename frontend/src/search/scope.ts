/** Which section the search field searches: the one it's in (music, VGM, audiobooks, podcasts, radio), or
 * everything on a page that's in none (home, settings, liked songs, playlists), or with a * typed first.
 * The server's /api/search finds what its `scope` asks for (backend/muzix/api/library.py). */

import type { Modules } from "../types";

export type Scope = "all" | "music" | "vgm" | "audiobooks" | "podcasts" | "radio";

export const SCOPES: Scope[] = ["all", "music", "vgm", "audiobooks", "podcasts", "radio"];

/** As the search field names it: "Search music", "Search everything". */
export const SCOPE_NAMES: Record<Scope, string> = {
  all: "everything", music: "music", vgm: "VGM", audiobooks: "audiobooks", podcasts: "podcasts", radio: "radio",
};

/** The section a page is in, by its address. null: the page says itself (an album's: music's or VGM's). */
export function sectionOf(path: string): Scope | null {
  if (/^\/album\//.test(path)) return null;
  if (/^\/library\/(liked|playlists)/.test(path)) return "all";
  if (/^\/(library|artist|genre|tag)(\/|$)/.test(path)) return "music";
  if (/^\/vgm(\/|$)/.test(path)) return "vgm";
  if (/^\/audiobooks(\/|$)/.test(path)) return "audiobooks";
  if (/^\/podcasts(\/|$)/.test(path)) return "podcasts";
  if (/^\/radio(\/|$)/.test(path)) return "radio";
  return "all";
}

export function isScope(s: string | null | undefined): s is Scope {
  return !!s && (SCOPES as string[]).includes(s);
}

/** What's typed, searched where: a * first searches everything, else the section the field is in. */
export function parseQuery(text: string, here: Scope): { q: string; scope: Scope } {
  const t = text.trim();
  return t.startsWith("*") ? { q: t.slice(1).trim(), scope: "all" } : { q: t, scope: here };
}

/** A section that's turned off on the server (modules.ts) has nothing to search; everything leaves its out. */
export function shownScope(scope: Scope, modules: Modules): Scope {
  return scope === "all" || scope === "music" || modules[scope] ? scope : "all";
}
