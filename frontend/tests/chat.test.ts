// The chat's rules (src/chat/logic.ts). Run with `npm test` (node's own test runner; node strips the types).
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  type Conversation, dayLabel, isActive, MAX_LINKS, parseDraft, preview, runs, shortWhen, splitUrls, withLink,
} from "../src/chat/logic.ts";

const now = Date.parse("2026-11-11T15:00:00Z");
const conv = (at: string | null, unread = 0): Conversation => ({
  with: { server: "s", user: 1, name: "anna", place: "Plopp", here: true }, at, unread,
  last: { text: "hej", mine: false, links: 0 },
});

test("the chat button shows with something unread, something new this week, or the chat open", () => {
  assert.equal(isActive([], false, now), false);
  assert.equal(isActive(undefined, true, now), true);
  assert.equal(isActive([conv("2026-11-05T15:00:00Z")], false, now), true);          // six days ago
  assert.equal(isActive([conv("2026-11-03T15:00:00Z")], false, now), false);         // eight
  assert.equal(isActive([conv("2026-10-01T15:00:00Z", 2)], false, now), true);       // old, but unread
});

test("a conversation's last message in a line", () => {
  assert.equal(preview({ text: "hej\n  då", mine: false, links: 0 }), "hej då");
  assert.equal(preview({ text: "listen", mine: true, links: 1 }), "You: listen");
  assert.equal(preview({ text: "", mine: false, links: 1 }), "Sent a link");
  assert.equal(preview({ text: "", mine: true, links: 3 }), "You: Sent 3 links");
});

test("links in a draft: each once, and five at most", () => {
  const d = (id: number) => ({ kind: "album" as const, id, title: `A${id}`, sub: "", art: null });
  let links = withLink([], d(1));
  links = withLink(links, d(1));
  assert.deepEqual(links.map((l) => l.id), [1]);
  for (let i = 2; i <= 7; i++) links = withLink(links, d(i));
  assert.equal(links.length, MAX_LINKS);
  assert.deepEqual(links.map((l) => l.id), [3, 4, 5, 6, 7]);
  assert.deepEqual(withLink([d(1)], { ...d(1), kind: "track" }).length, 2);       // a song and an album with one id
});

test("what a data-link attribute holds", () => {
  assert.deepEqual(parseDraft('{"kind":"track","id":4,"title":"Song","sub":"Artist","art":"/api/art/album/2?v=1"}'),
    { kind: "track", id: 4, title: "Song", sub: "Artist", art: "/api/art/album/2?v=1" });
  assert.equal(parseDraft('{"kind":"book","id":4}'), null);
  assert.equal(parseDraft('{"kind":"album","id":"4"}'), null);
  assert.equal(parseDraft("not json"), null);
  assert.equal(parseDraft(null), null);
});

test("days and times", () => {
  const today = new Date(2026, 10, 11, 15, 0);
  assert.equal(dayLabel(new Date(2026, 10, 11, 9, 30).toISOString(), today), "Today");
  assert.equal(dayLabel(new Date(2026, 10, 10, 23, 59).toISOString(), today), "Yesterday");
  assert.equal(dayLabel(new Date(2026, 10, 8, 12, 0).toISOString(), today), "Sunday");
  assert.equal(dayLabel(new Date(2026, 9, 2, 12, 0).toISOString(), today), "2 Oct");
  assert.equal(dayLabel(new Date(2025, 9, 2, 12, 0).toISOString(), today), "2 Oct 2025");
  assert.equal(shortWhen(new Date(2026, 10, 11, 9, 5).toISOString(), today), "09:05");
  assert.equal(shortWhen(new Date(2026, 10, 8, 12, 0).toISOString(), today), "Sun");
  assert.equal(shortWhen(new Date(2026, 10, 10, 12, 0).toISOString(), today), "Yesterday");
  assert.equal(shortWhen(new Date(2026, 9, 2, 12, 0).toISOString(), today), "2 Oct");
  assert.equal(shortWhen(null, today), "");
});

test("web addresses in a message become links, without the full stop after them", () => {
  assert.deepEqual(splitUrls("see https://muzix.example/album/3. nice"), [
    { text: "see " }, { text: "https://muzix.example/album/3", url: "https://muzix.example/album/3" }, { text: ". nice" },
  ]);
  assert.deepEqual(splitUrls("no links here"), [{ text: "no links here" }]);
  assert.deepEqual(splitUrls("javascript:alert(1) ftp://x"), [{ text: "javascript:alert(1) ftp://x" }]);
});

test("messages in runs: by writer, by day, and five minutes apart", () => {
  const m = (mine: boolean, at: string) => ({ mine, sent_at: at });
  const out = runs([
    m(false, "2026-11-10T20:00:00Z"), m(false, "2026-11-10T20:02:00Z"), m(true, "2026-11-10T20:03:00Z"),
    m(true, "2026-11-10T20:30:00Z"), m(true, "2026-11-11T08:00:00Z"),
  ]);
  assert.deepEqual(out.map((r) => [r.day, r.items.length]), [
    ["2026-11-10T20:00:00Z", 2], [null, 1], [null, 1], ["2026-11-11T08:00:00Z", 1],
  ]);
});
