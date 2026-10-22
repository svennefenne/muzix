import { QueryClient } from "@tanstack/react-query";
import { create } from "zustand";
import { api } from "./api";
import { engine } from "./player/engine";
import { fromTrack } from "./store/player";
import { useUi } from "./store/ui";
import type { AlbumDetail, Track } from "./types";

export const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 30_000, retry: 1, refetchOnWindowFocus: false } },
});

export async function playAlbum(id: number, opts: { shuffle?: boolean; startTrack?: number; queue?: boolean } = {}) {
  const a = await queryClient.fetchQuery({ queryKey: ["album", id], queryFn: () => api.get<AlbumDetail>(`/api/albums/${id}`) });
  if (opts.shuffle && a.track_count > a.tracks.length) return playRandom({ album_id: id, kind: "all", n: 300 });
  let tracks = a.tracks;
  if (opts.shuffle) tracks = [...tracks].sort(() => Math.random() - 0.5);
  const items = tracks.map(fromTrack);
  if (opts.queue) return engine.enqueue(items);
  const start = opts.startTrack ? Math.max(0, tracks.findIndex((t) => t.id === opts.startTrack)) : 0;
  engine.play(items, start);
}

export function playTracks(tracks: Track[], index = 0, shuffle = false) {
  let list = tracks;
  if (shuffle) {
    list = [...tracks].sort(() => Math.random() - 0.5);
    index = 0;
  }
  engine.play(list.map(fromTrack), index);
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
