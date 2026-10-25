import type { CastState } from "../player/cast";
import { create } from "zustand";
import type { Book, Episode, Station, Track } from "../types";

export type ItemKind = "track" | "book" | "episode" | "radio" | "spotify";

export interface PlayItem {
  key: string;
  kind: ItemKind;
  id: number | string;
  title: string;
  artist: string;
  album?: string;
  art?: string | null;
  duration: number;           // 0 = unknown / live
  src: string;
  genre?: string;
  tags?: string[];
  system?: string;
  trackKind?: "music" | "vgm";
  albumId?: number | null;
  artistId?: number | null;
  format?: string;
  castNative?: boolean;       // a Cast speaker can take the file as it is (and seek in it)
  liked?: boolean;
  resume?: number;            // start here (seconds)
  bookId?: number;
  partOffset?: number;        // a book part's start within the whole book
  spotifyUri?: string;
  spotifyArtist?: string;     // first artist, for the genre lookup
}

export function fromTrack(t: Track): PlayItem {
  return {
    key: `track:${t.id}`, kind: "track", id: t.id, title: t.title,
    artist: t.artist || t.albumartist, album: t.album, art: t.art, duration: t.duration,
    src: t.stream, genre: t.genre, tags: t.tags, system: t.system, trackKind: t.kind,
    albumId: t.album_id, artistId: t.artist_id, format: t.format, castNative: t.cast_native, liked: t.liked,
  };
}

export function fromBook(b: Book, from = b.position): PlayItem[] {
  const parts = b.parts || [];
  const start = Math.max(0, parts.findIndex((p, i) => from < p.offset + p.duration || i === parts.length - 1));
  return parts.slice(start).map((p, i) => ({
    key: `book:${b.id}:${p.position}`, kind: "book" as const, id: b.id, title: parts.length > 1 ? p.title : b.title,
    artist: b.author, album: b.title, art: b.art, duration: p.duration, src: p.stream,
    bookId: b.id, partOffset: p.offset, resume: i === 0 ? Math.max(0, from - p.offset) : 0,
  }));
}

export function fromEpisode(e: Episode, feedTitle?: string, feedImage?: string): PlayItem {
  return {
    key: `episode:${e.id}`, kind: "episode", id: e.id, title: e.title,
    artist: feedTitle || e.feed_title || "", art: e.image || feedImage || null, duration: e.duration,
    src: e.stream, resume: e.finished ? 0 : e.position,
  };
}

export function fromStation(s: Station): PlayItem {
  const q = new URLSearchParams({ url: s.url });
  if (s.uuid) q.set("uuid", s.uuid);
  return {
    key: `radio:${s.uuid || s.url}`, kind: "radio", id: s.uuid || s.url, title: s.name,
    artist: [s.country, s.codec && `${s.codec} ${s.bitrate ? s.bitrate + "k" : ""}`].filter(Boolean).join(" · "),
    art: s.favicon || null, duration: 0, src: `/api/radio/play?${q}`,
    tags: (s.tags || "").split(",").map((t) => t.trim()).filter(Boolean), album: s.url,
  };
}

type Repeat = "off" | "all" | "one";

interface PlayerState {
  queue: PlayItem[];
  index: number;
  playing: boolean;
  buffering: boolean;
  position: number;
  duration: number;
  volume: number;
  muted: boolean;
  shuffle: boolean;
  repeat: Repeat;
  speed: number;
  liveTitle: string;          // radio "now playing"
  error: string;
  castState: CastState;       // Google Cast speakers nearby / connected
  castDevice: string;         // the connected speaker's name
  current: () => PlayItem | null;
  set: (p: Partial<PlayerState>) => void;
}

const saved = (() => {
  try {
    return JSON.parse(localStorage.getItem("muzix.player") || "{}");
  } catch {
    return {};
  }
})();

export const usePlayer = create<PlayerState>((set, get) => ({
  queue: [],
  index: -1,
  playing: false,
  buffering: false,
  position: 0,
  duration: 0,
  volume: saved.volume ?? 0.8,
  muted: false,
  shuffle: saved.shuffle ?? false,
  repeat: saved.repeat ?? "off",
  speed: 1,
  liveTitle: "",
  error: "",
  castState: "unavailable",
  castDevice: "",
  current: () => {
    const { queue, index } = get();
    return index >= 0 && index < queue.length ? queue[index] : null;
  },
  set: (p) => {
    set(p);
    if ("volume" in p || "shuffle" in p || "repeat" in p) {
      const s = get();
      try {
        localStorage.setItem("muzix.player", JSON.stringify({ volume: s.volume, shuffle: s.shuffle, repeat: s.repeat }));
      } catch {
        /* ignore */
      }
    }
  },
}));
