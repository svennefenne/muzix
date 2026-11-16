// What the merge window offers to add (src/components/mergeCandidates.ts). Run with `npm test`.
import assert from "node:assert/strict";
import { test } from "node:test";
import { type Candidate, mergeCandidates, SHOWN } from "../src/components/mergeCandidates.ts";

// Entombed on Plopp, as the albums list gives them (oldest first): the other disc of Inferno / Averno is 17th
const years = [1989, 1990, 1991, 1992, 1993, 1994, 1996, 1997, 1997, 1997, 1997, 1998, 1999, 2000, 2001, 2003, 2004, 2005, 2006, 2007];
const entombed: Candidate[] = years.map((year, k) => ({ id: k + 1, title: k === 16 ? "Averno" : `Album ${k + 1}`, artist: "Entombed", year, kind: "music" }));
const first = { year: 2004 };

test("the artist's albums nearest the first one's year come first, though it has many", () => {
  const got = mergeCandidates(first, entombed, [], "", new Set());
  assert.equal(got.length, SHOWN);
  assert.equal(got[0].title, "Averno");                     // was past the twelfth, so never offered
  assert.deepEqual(got.slice(1, 5).map((x) => x.year), [2003, 2005, 2006, 2001]);
});

test("what's typed is offered first: search hits, and the artist's albums that match", () => {
  const elsewhere = { id: 99, title: "Averno Live", artist: "Someone", year: 2010, kind: "music" };
  const got = mergeCandidates(first, entombed, [elsewhere, entombed[16]], "averno", new Set());
  assert.deepEqual(got.map((x) => x.id), [99, 17]);            // each once, the artist's own not lost behind the others
  assert.deepEqual(mergeCandidates(first, entombed, [], "a", new Set()).length, SHOWN);   // one letter: no search yet
});

test("not offered: albums already in, a friend's, and chip music", () => {
  const friend = { id: 50, title: "Averno", artist: "Entombed", year: 2004, kind: "music", peer: "Ankan" };
  const chip = { id: 51, title: "Averno", artist: "Entombed", year: 2004, kind: "vgm" };
  const got = mergeCandidates(first, [friend, chip, ...entombed], [], "averno", new Set([17]));
  assert.deepEqual(got, []);
});
