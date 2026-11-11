import { QueryClient } from "@tanstack/react-query";
import { create } from "zustand";
import { api } from "./api";
import { engine } from "./player/engine";
import { fromTrack, usePlayer, type PlayItem } from "./store/player";
import { useUi } from "./store/ui";
import type { AlbumDetail, Track } from "./types";

export const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 30_000, retry: 1, refetchOnWindowFocus: false } },
});

/** Episodes were marked or played: the lists with their ticks, dots and progress are fetched again. */
export function podcastsChanged() {
  for (const key of ["podcast", "podcasts", "podcasts-latest", "podcasts-continue", "episode", "sidebar", "home"]) queryClient.invalidateQueries({ queryKey: [key] });
}

// an episode or audiobook played to its end, or left for another: its page and lists show where it got to
engine.onSaved = (item) => {
  if (item.kind === "episode") return podcastsChanged();
  for (const key of ["book", "books", "home"]) queryClient.invalidateQueries({ queryKey: [key] });
};

export async function playAlbum(id: number, opts: { shuffle?: boolean; startTrack?: number; queue?: boolean } = {}) {
  const a = await queryClient.fetchQuery({ queryKey: ["album", id], queryFn: () => api.get<AlbumDetail>(`/api/albums/${id}`) });
  if (opts.shuffle && a.track_count > a.tracks.length) return playRandom({ album_id: id, kind: "all", n: 300 });
  const tracks = a.tracks;
  const items = tracks.map(fromTrack);
  if (opts.queue) return engine.enqueue(items);
  if (opts.shuffle) return shuffled(items);
  const start = opts.startTrack ? Math.max(0, tracks.findIndex((t) => t.id === opts.startTrack)) : 0;
  engine.play(items, start);
}

/** Shuffle, as on Spotify: the songs in their order from a random one, with shuffle on, so it can be turned
 * off again (the rest then plays in order: player/cast.ts unshuffle). */
function shuffled(items: PlayItem[]) {
  engine.play(items, Math.floor(Math.random() * items.length));
  usePlayer.getState().set({ shuffle: true });
}

export function playTracks(tracks: Track[], index = 0, shuffle = false) {
  if (shuffle) return shuffled(tracks.map(fromTrack));
  engine.play(tracks.map(fromTrack), index);
}

export async function playRandom(params: Record<string, string | number | undefined>) {
  const tracks = await api.get<Track[]>("/api/random", { n: 100, ...params });
  if (!tracks.length) return useUi.getState().notify("Nothing to play here yet");
  playTracks(tracks);
}

export async function toggleLike(kind: "track" | "album" | "artist", id: number, liked: boolean) {
  if (liked) await api.del(`/api/likes/${kind}/${id}`);
  else await api.put(`/api/likes/${kind}/${id}`);
  queryClient.invalidateQueries();
  return !liked;
}

/** Likes or unlikes a song in the queue, and keeps that on its queue entry so every player shows it. */
export async function toggleQueuedLike(item: PlayItem) {
  const liked = await toggleLike("track", Number(item.id), !!item.liked);
  const s = usePlayer.getState();
  s.set({ queue: s.queue.map((q) => (q.key === item.key ? { ...q, liked } : q)) });
}

// "Add to playlist" picker
interface PickerState {
  trackIds: number[] | null;
  open: (ids: number[]) => void;
  close: () => void;
}
export const usePlaylistPicker = create<PickerState>((set) => ({
  trackIds: null,
  open: (ids) => set({ trackIds: ids }),
  close: () => set({ trackIds: null }),
}));
