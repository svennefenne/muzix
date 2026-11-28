// What autoplay lined up leaves the queue (src/player/lined.ts), when autoplay is turned off or repeat on: an
// album on repeat went on to the similar songs autoplay had found before repeat was turned on (2026-11-28).
// Run with `npm test`.
import assert from "node:assert/strict";
import { test } from "node:test";
import { withoutLined } from "../src/player/lined.ts";
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
