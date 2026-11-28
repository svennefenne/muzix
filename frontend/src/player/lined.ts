import type { PlayItem } from "../store/player";

/** The queue without what autoplay lined up and hasn't played yet: its similar songs (no `feedId`), or one
 * podcast's next episodes (that feed's). What has played, and everything chosen, stays. Autoplay turned off, or
 * repeat turned on (an album on repeat starts over after its last song, not after the songs autoplay found). */
export function withoutLined(queue: PlayItem[], index: number, feedId?: number): PlayItem[] {
  const lined = (it: PlayItem) => !!it.auto && (feedId === undefined ? it.kind !== "episode" : it.feedId === feedId);
  return queue.filter((it, i) => i <= index || !lined(it));
}
