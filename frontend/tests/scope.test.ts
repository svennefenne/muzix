// The search field's sections (src/search/scope.ts): each section searches its own, a * first everything.
import assert from "node:assert/strict";
import { test } from "node:test";
import { parseQuery, sectionOf, shownScope } from "../src/search/scope.ts";

test("a page's section, by its address", () => {
  for (const [path, scope] of [
    ["/library", "music"], ["/library/artists/4", "music"], ["/artist/4", "music"], ["/genre/Metal", "music"], ["/tag/doom", "music"],
    ["/vgm", "vgm"], ["/vgm/systems/snes", "vgm"], ["/audiobooks/3", "audiobooks"], ["/podcasts/episode/9", "podcasts"],
    ["/radio", "radio"],
    // in no section: everything
    ["/", "all"], ["/settings", "all"], ["/library/liked", "all"], ["/library/playlists", "all"], ["/playlist/2", "all"],
    ["/admin/upload", "all"], ["/vgmfoo", "all"],
  ] as const) assert.equal(sectionOf(path), scope, path);
  assert.equal(sectionOf("/album/7"), null);      // the album's page says: music's or VGM's
});

test("a * first searches everything, else the section", () => {
  assert.deepEqual(parseQuery("  abba ", "music"), { q: "abba", scope: "music" });
  assert.deepEqual(parseQuery("*abba", "podcasts"), { q: "abba", scope: "all" });
  assert.deepEqual(parseQuery(" * abba", "radio"), { q: "abba", scope: "all" });
  assert.deepEqual(parseQuery("*", "vgm"), { q: "", scope: "all" });
});

test("a section turned off has nothing to search: everything instead", () => {
  const modules = { vgm: true, audiobooks: false, podcasts: true, radio: false, network: true };
  assert.equal(shownScope("audiobooks", modules), "all");
  assert.equal(shownScope("radio", modules), "all");
  assert.equal(shownScope("podcasts", modules), "podcasts");
  assert.equal(shownScope("music", modules), "music");
});
