/** An artist's releases by type, as on Spotify: a chip for each type with its count, Album (13), EP (2),
 * Singles (9). With none picked, albums, then EPs, then singles, below each other; a chip shows its own
 * alone (again: all). Which each is: backend/muzix/releases.py (the tags, a guess, or an admin's choice). */

import { useState, type ReactNode } from "react";
import type { Album } from "../types";

export type Release = "album" | "ep" | "single";

const RELEASES: { id: Release; label: string }[] = [
  { id: "album", label: "Album" }, { id: "ep", label: "EP" }, { id: "single", label: "Singles" },
];

/** A game's (VGM) is an album here: the types are music's. */
export const releaseOf = (a: Album): Release => (a.kind === "vgm" ? "album" : a.release_type || "album");

/** What a card or row says of it: "EP" or "Single"; an album, nothing. */
export const releaseLabel = (a: Album) => ({ album: "", ep: "EP", single: "Single" })[releaseOf(a)];

export function Discography({ albums, children }: { albums: Album[]; children: (items: Album[]) => ReactNode }) {
  const [picked, setPicked] = useState<Release | null>(null);
  const groups = RELEASES.map((r) => ({ ...r, items: albums.filter((a) => releaseOf(a) === r.id) })).filter((g) => g.items.length);
  if (groups.length < 2) return <>{children(albums)}</>;      // one type only: nothing to pick
  const shown = picked ? groups.filter((g) => g.id === picked) : groups;
  return (
    <>
      <div className="disco-chips" role="toolbar" aria-label="Show">
        {groups.map((g) => (
          <button key={g.id} className={`lib-chip ${picked === g.id ? "on" : ""}`} aria-pressed={picked === g.id}
                  onClick={() => setPicked(picked === g.id ? null : g.id)}>
            {g.label} ({g.items.length})
          </button>
        ))}
      </div>
      {shown.map((g) => (
        <div key={g.id} className="disco-group">
          {!picked && <h3 className="h3 disco-title">{g.label} <span className="faint">({g.items.length})</span></h3>}
          {children(g.items)}
        </div>
      ))}
    </>
  );
}
