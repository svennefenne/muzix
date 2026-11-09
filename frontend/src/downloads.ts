/** What's downloaded to the phone, in the app (android/.../Downloads.kt): albums, playlists, audiobooks,
 * episodes and the liked songs, each a collection with its songs, the page's data (what its page asks the
 * server for, kept so it opens offline) and its cover. Offline, the app shows only these. */

import { create } from "zustand";
import { fromTrack, type PlayItem } from "./store/player";
import type { Track } from "./types";

export interface Downloaded {
  id: string;                 // "album:12"
  kind: Collection["kind"];
  title: string;
  subtitle: string;
  art: string;
  path: string;               // its page
  total: number;
  done: number;
  failed: number;
  bytes: number;
}

export interface Collection {
  id: string;
  kind: "album" | "playlist" | "book" | "episode" | "liked";
  title: string;
  subtitle: string;
  art?: string | null;
  path: string;
  pages: Record<string, unknown>;     // the API's answers its page needs, by address
  items: PlayItem[];
}

interface DownloadsState {
  available: boolean;         // an app that downloads (0.9 on: it also opens the web version's admin pages in the browser)
  offline: boolean;           // the app can't reach the server: only what's downloaded shows
  list: Downloaded[];
  set: (s: Partial<DownloadsState>) => void;
}

export const useDownloads = create<DownloadsState>((set) => ({
  available: false,
  offline: false,
  list: [],
  set: (s) => set(s),
}));

export function useDownloaded(id: string): Downloaded | undefined {
  return useDownloads((s) => s.list.find((d) => d.id === id));
}

/** Whether a page is there offline: a downloaded collection's own page. */
export function openOffline(path: string): boolean {
  return useDownloads.getState().list.some((d) => d.path === path);
}

/** The liked songs as a download: kept up to date while it's on the phone (App.tsx). */
export function likedCollection(tracks: Track[]): Collection {
  return { id: "liked", kind: "liked", title: "Liked songs", subtitle: `${tracks.length} songs`, art: tracks[0]?.art, path: "/library/liked",
           pages: { "/api/likes/tracks": tracks }, items: tracks.map(fromTrack) };
}

export function fmtBytes(n: number): string {
  if (n >= 1e9) return `${(n / 1e9).toFixed(1)} GB`;
  if (n >= 1e6) return `${Math.round(n / 1e6)} MB`;
  return `${Math.max(0, Math.round(n / 1e3))} kB`;
}
