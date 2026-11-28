import type { PlayItem } from "../store/player";

type Repeat = "off" | "all" | "one";

/** What goes round with repeat on: the songs started together with the one playing (an album, a playlist: their
 * `from`), or with the last one before it that was (a song added after them plays now). null when nothing in the
 * queue was started so (a queue kept from before `from` was): then all of it goes round. */
export function loopOf(queue: PlayItem[], index: number): string | null {
  for (let i = Math.min(index, queue.length - 1); i >= 0; i--) {
    const from = queue[i]?.from;
    if (from) return from;
  }
  return null;
}

/** The queue's songs from `index` on, in the order they play. With repeat on: once round what was started (the
 * album, the playlist), from the song that plays, a song asked to play next first; songs added to the queue after
 * it wait until repeat is off. Otherwise the queue as it lies. The app and a Cast speaker are handed this order:
 * one round, which their own repeat goes round again. */
export function order(queue: PlayItem[], index: number, repeat: Repeat): number[] {
  if (index < 0 || index >= queue.length) return [];
  const all = [...queue.keys()];
  if (repeat !== "all") return all.slice(index);
  const loop = loopOf(queue, index);
  if (!loop) return [...all.slice(index), ...all.slice(0, index)];
  const out = [index];
  for (let i = index + 1; i < queue.length && queue[i].soon; i++) out.push(i);
  const goesRound = (i: number) => queue[i].from === loop && !out.includes(i);
  return [...out, ...all.slice(index + 1).filter(goesRound), ...all.slice(0, index).filter(goesRound)];
}

/** The song that comes after the one at `index`: null when the queue has run out. (Repeat one isn't asked here: a
 * song that ends starts over, but Next goes on.) */
export function nextOf(queue: PlayItem[], index: number, repeat: Repeat): number | null {
  const o = order(queue, index, repeat === "one" ? "off" : repeat);
  return o.length > 1 ? o[1] : repeat === "all" && o.length ? o[0] : null;
}

/** What repeat goes round, in words for its button: "the album" when that is one album. */
export function loopName(queue: PlayItem[], index: number): string {
  const loop = loopOf(queue, index);
  const albums = new Set(queue.filter((it) => (loop ? it.from === loop : true)).map((it) => it.albumId ?? it.album ?? ""));
  return albums.size === 1 && !albums.has("") ? "the album" : loop ? "what you started" : "the queue";
}

/** What the app is handed from `start` on, `n` songs at most: with repeat on, round after round (a song asked to play
 * next only in the first). The app keeps the songs it has played before them and goes back to its first when it gets
 * to the end, so it isn't left to get to the end: the page hands it more in time, and while the page sleeps (a phone's
 * screen off) the rounds last. */
export function handover(queue: PlayItem[], start: number, repeat: Repeat, n: number): number[] {
  const first = order(queue, start, repeat === "all" ? "all" : "off");
  if (repeat !== "all" || !first.length) return first.slice(0, n);
  const loop = loopOf(queue, start);
  const round = loop ? first.filter((i) => queue[i].from === loop) : first;
  const out = [...first];
  while (round.length && out.length < n) out.push(...round);
  return out.slice(0, n);
}
