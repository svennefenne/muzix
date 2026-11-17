/** The sleep timer: what plays fades out and pauses after a while, or at the end of the chapter (a book's) or of what
 * plays (a song, an episode). The page runs it, and hands it to the app's own player too (player/app.ts), which runs
 * it with the screen off and the page asleep; the page then only keeps the count. */

import { create } from "zustand";
import { api } from "../api";
import { queryClient } from "../actions";
import { usePlayer } from "../store/player";
import { useUi } from "../store/ui";
import type { Book } from "../types";
import { appPlayer } from "./app";
import { engine } from "./engine";

export const SLEEP_MINUTES = [15, 30, 45, 60];
const FADE = 30;            // seconds the volume takes to go, at a time
const END_FADE = 2;         // and at a chapter's end, which would take the last words with it

export interface SleepTimer {
  ends: number | null;      // by time: when (ms)
  key: string | null;       // or at the end of this item…
  pos: number | null;       // …at this point in it (a chapter's end), else its own end
  label: string;            // "End of the chapter", "30 min"
}

const OFF: SleepTimer = { ends: null, key: null, pos: null, label: "" };
export const useSleep = create<SleepTimer>(() => OFF);

let ticker: ReturnType<typeof setInterval> | null = null;

/** The app's player runs it (Android, Muzix Desktop): it fades and pauses, the page doesn't. */
const native = () => appPlayer.active && appPlayer.sleeps;

function start(t: SleepTimer) {
  useSleep.setState(t);
  engine.setFade(1);
  appPlayer.sleep({ at: t.ends, key: t.key, pos: t.pos, fade: t.ends ? FADE : END_FADE });
  if (!ticker) ticker = setInterval(tick, 250);
}

export function sleepIn(minutes: number) {
  start({ ends: Date.now() + minutes * 60_000, key: null, pos: null, label: `${minutes} min` });
}

/** What "the end" means for what plays now: its chapter's, for a book. */
export function endLabel() {
  const cur = usePlayer.getState().current();
  return cur?.kind === "book" ? "End of the chapter" : cur?.kind === "episode" ? "End of the episode" : "End of the song";
}

export async function sleepAtEnd() {
  const cur = usePlayer.getState().current();
  if (!cur || cur.kind === "radio") return;
  let pos: number | null = null;
  if (cur.kind === "book" && cur.bookId) {
    const id = cur.bookId;
    const b = await queryClient.fetchQuery({ queryKey: ["book", id], queryFn: () => api.get<Book>(`/api/books/${id}`), staleTime: 60_000 });
    const off = cur.partOffset || 0;
    const at = off + usePlayer.getState().position;
    const chapters = b.chapters || [];
    const i = chapters.reduce((acc, c, j) => (c.start <= at + 0.5 ? j : acc), -1);
    const end = i + 1 < chapters.length ? chapters[i + 1].start - off : null;     // where the next chapter starts
    if (end !== null && end > 0 && end < cur.duration - 1) pos = end;               // else this part's end
  }
  start({ ends: null, key: cur.key, pos, label: endLabel() });
}

export function cancelSleep() {
  if (ticker) clearInterval(ticker);
  ticker = null;
  useSleep.setState(OFF);
  engine.setFade(1);
  appPlayer.sleep({ at: null, key: null, pos: null, fade: 0 });
}

/** Seconds left (real ones: a book at 1.5× gets to a chapter's end sooner); null when it waits for an item's end. */
export function sleepLeft(t: SleepTimer = useSleep.getState()): number | null {
  if (t.ends !== null) return (t.ends - Date.now()) / 1000;
  const p = usePlayer.getState();
  const cur = p.current();
  if (t.key === null) return null;
  if (!cur || cur.key !== t.key) return 0;            // it ended or was left: what came after doesn't play on
  const pos = t.pos ?? (cur.duration > 0 ? cur.duration - 0.25 : null);
  return pos === null ? null : (pos - p.position) / (cur.kind === "track" ? 1 : p.speed || 1);
}

function tick() {
  const t = useSleep.getState();
  if (t.ends === null && t.key === null) return cancelSleep();
  const left = sleepLeft(t);
  if (left === null) return;
  const fade = t.ends !== null ? FADE : END_FADE;
  if (native()) {
    if (left < -5) done(false);        // the app paused it (it says so; this is in case it couldn't)
    return;
  }
  engine.setFade(left >= fade ? 1 : Math.max(0, left / fade));
  if (left <= 0) {
    engine.pause();
    done(true);
  }
}

function done(say: boolean) {
  if (ticker) clearInterval(ticker);
  ticker = null;
  useSleep.setState(OFF);
  // the volume as it was, once the pause has taken (a moment for a speaker)
  setTimeout(() => engine.setFade(1), 400);
  if (say) useUi.getState().notify("Sleep timer: paused");
}

if (typeof window !== "undefined") window.addEventListener("muzix:slept", () => done(true));

// something else put on to play (another book, an album) isn't what the end was waited for: the timer goes, before
// the app is handed the new queue (a skip within the queue does end the song, and pauses)
usePlayer.subscribe((s, prev) => {
  const t = useSleep.getState();
  if (t.key !== null && s.queue !== prev.queue && !s.queue.some((it) => it.key === t.key)) cancelSleep();
});
