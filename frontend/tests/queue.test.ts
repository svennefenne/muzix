// What autoplay lined up leaves the queue (src/player/lined.ts), when autoplay is turned off or repeat on: an
// album on repeat went on to the similar songs autoplay had found before repeat was turned on (2026-11-28).
// Run with `npm test`.
import assert from "node:assert/strict";
import { test } from "node:test";
import { withoutLined } from "../src/player/lined.ts";
import { handover, loopName, nextOf, order } from "../src/player/order.ts";
import type { PlayItem } from "../src/store/player.ts";

const song = (title: string, auto = false): PlayItem =>
  ({ key: `track:${title}`, kind: "track", id: title, title, artist: "", duration: 200, src: "", auto });
const episode = (title: string, feedId: number, auto = false): PlayItem =>
  ({ key: `episode:${title}`, kind: "episode", id: title, title, artist: "", duration: 200, src: "", feedId, auto });

const titles = (q: PlayItem[]) => q.map((it) => it.title);

test("the album on repeat goes round without the songs autoplay found after it", () => {
  const queue = [song("1"), song("2"), song("3"), song("Other 1", true), song("Other 2", true)];
  assert.deepEqual(titles(withoutLined(queue, 1)), ["1", "2", "3"]);
});

test("an autoplay song that has played (or plays now) stays; one chosen after it too", () => {
  const queue = [song("1"), song("Other 1", true), song("Other 2", true), song("Chosen"), song("Other 3", true)];
  assert.deepEqual(titles(withoutLined(queue, 1)), ["1", "Other 1", "Chosen"]);
});

test("a podcast's next episodes are its own: they go only when that podcast's autoplay is turned off", () => {
  const queue = [song("1"), episode("Ep 1", 7), episode("Ep 2", 7, true), song("Other", true)];
  assert.deepEqual(titles(withoutLined(queue, 0)), ["1", "Ep 1", "Ep 2"]);
  assert.deepEqual(titles(withoutLined(queue, 0, 7)), ["1", "Ep 1", "Other"]);
});

// Repeat goes round what was started — the album, the playlist — not the queue (src/player/order.ts, 2026-11-28).

const started = (from: string, ...names: string[]) =>
  names.map((t): PlayItem => ({ ...song(t), from, albumId: from === "album" ? 7 : undefined }));
const added = (t: string, soon = false): PlayItem => ({ ...song(t), soon });

test("repeat goes round the album that was started; songs added after it wait, autoplay's too", () => {
  const queue = [...started("album", "1", "2", "3"), added("Added"), { ...song("Similar", true) }];
  assert.equal(nextOf(queue, 2, "all"), 0);                        // after the album's last song: its first
  assert.deepEqual(order(queue, 1, "all"), [1, 2, 0]);             // one round, from the song that plays
  assert.equal(nextOf(queue, 2, "off"), 3);                        // without repeat the queue goes on
  assert.equal(loopName(queue, 1), "the album");
});

test("a song asked to play next plays next, repeat or not, then the album goes on", () => {
  const queue = [...started("album", "1", "2"), added("Asked", true), ...started("album", "3")];
  assert.deepEqual(order(queue, 1, "all"), [1, 2, 3, 0]);
  const heard = queue.map((it) => ({ ...it, soon: false }));       // played once: on the next round it waits
  assert.deepEqual(order(heard, 1, "all"), [1, 3, 0]);
});

test("an added song playing when repeat is turned on: what was started before it goes round", () => {
  const queue = [...started("list", "a", "b"), added("Added"), added("Later")];
  assert.equal(nextOf(queue, 2, "all"), 0);
  assert.equal(loopName(queue, 2), "what you started");
});

test("a queue nothing was started in goes round as a whole, from the song that plays", () => {
  const queue = [song("x"), song("y"), song("z")];
  assert.deepEqual(order(queue, 1, "all"), [1, 2, 0]);
  assert.equal(nextOf(queue, 2, "off"), null);
  assert.equal(nextOf(queue, 2, "one"), null);                     // repeat one: Next still goes on (nothing here)
});

test("the app is handed round after round of the album, from the song that plays, the asked one only once", () => {
  // "Play next" on song 2 puts the asked one right after it
  const queue = [...started("album", "1", "2"), added("Asked", true), ...started("album", "3"), added("Added")];
  // the album started at song 2: the app's own repeat would go back to song 2, so it gets the rounds instead
  assert.deepEqual(titles(handover(queue, 1, "all", 9).map((i) => queue[i])), ["2", "Asked", "3", "1", "2", "3", "1", "2", "3"]);
  assert.deepEqual(titles(handover(queue, 1, "off", 9).map((i) => queue[i])), ["2", "Asked", "3", "Added"]);
  assert.deepEqual(handover(queue, 1, "one", 3), [1, 2, 3]);       // repeat one: the app repeats the song itself
});
