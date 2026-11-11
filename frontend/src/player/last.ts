/** What played last, for the next time the page or the app starts with nothing to play: it shows paused
 * where it was, and Play carries on. Three places may know it: this device (engine.ts rememberLast), the
 * Android app's player (LastPlayed.kt: the page sleeps while the phone plays on), and Muzix Connect on the
 * server (what the account played last on any device, until the server restarts). Whichever is newest
 * counts: one put in place gives way to a newer one that comes after it, until it's played or changed. */

import { usePlayer, type PlayItem } from "../store/player";

let placed: { queue: PlayItem[]; at: number } | null = null;

/** Whether what played last at `at` (ms) may be put in place now. */
export function mayPlace(at: number) {
  const s = usePlayer.getState();
  if (!s.queue.length) return true;
  return !!placed && s.queue === placed.queue && !s.playing && !s.buffering && at > placed.at;
}

/** `queue`, about to be the player's, is what played last at `at` (ms), only shown so far. */
export function place(queue: PlayItem[], at: number) {
  placed = { queue, at };
}

/** When what's in place played, while it's only shown: kept as it was, not made newer by being shown. */
export function placedAt(): number | null {
  const s = usePlayer.getState();
  return placed && s.queue === placed.queue && !s.playing && !s.buffering ? placed.at : null;
}
