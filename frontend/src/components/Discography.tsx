/** An artist's releases by type, as on Spotify: a chip for each type with its count, Album (13), EP (2),
 * Singles (9), at the right of the section's heading (`title`; without one, a row of their own at the right).
 * With none picked, albums, then EPs, then singles, below each other; a chip shows its own alone (again: all).
 * The chip picked is in the address (?type=single): back from a single opened there comes back to the singles.
 * Which each is: backend/muzix/releases.py (the tags, a guess, or an admin's choice). */

import type { ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import type { Album } from "../types";
import { Section } from "./ui";

export type Release = "album" | "ep" | "single";

const RELEASES: { id: Release; label: string }[] = [
  { id: "album", label: "Album" }, { id: "ep", label: "EP" }, { id: "single", label: "Singles" },
];

/** A game's (VGM) is an album here: the types are music's. */
export const releaseOf = (a: Album): Release => (a.kind === "vgm" ? "album" : a.release_type || "album");

/** What a card or row says of it: "EP" or "Single"; an album, nothing. */
export const releaseLabel = (a: Album) => ({ album: "", ep: "EP", single: "Single" })[releaseOf(a)];

export function Discography({ albums, title, children }: {
  albums: Album[]; title?: string; children: (items: Album[]) => ReactNode;
}) {
  const [params, setParams] = useSearchParams();
  const groups = RELEASES.map((r) => ({ ...r, items: albums.filter((a) => releaseOf(a) === r.id) })).filter((g) => g.items.length);
  const picked = groups.find((g) => g.id === params.get("type"))?.id ?? null;
  // the page's own address, not a step of its own: back goes to where the page was opened from
  const setPicked = (r: Release | null) => setParams((p) => {
    const next = new URLSearchParams(p);
    if (r) next.set("type", r);
    else next.delete("type");
    return next;
  }, { replace: true });
  const many = groups.length > 1;         // one type only: nothing to pick
  const shown = picked ? groups.filter((g) => g.id === picked) : groups;
  const chips = many && (
    <div className={`disco-chips ${title ? "at-head" : ""}`} role="toolbar" aria-label="Show">
      {groups.map((g) => (
        <button key={g.id} className={`lib-chip ${picked === g.id ? "on" : ""}`} aria-pressed={picked === g.id}
                onClick={() => setPicked(picked === g.id ? null : g.id)}>
          {g.label} ({g.items.length})
        </button>
      ))}
    </div>
  );
  const body = !many ? children(albums) : shown.map((g) => (
    <div key={g.id} className="disco-group">
      {!picked && <h3 className="h3 disco-title">{g.label} <span className="faint">({g.items.length})</span></h3>}
      {children(g.items)}
    </div>
  ));
  return title ? <Section title={title} more={chips || undefined}>{body}</Section> : <>{chips}{body}</>;
}
