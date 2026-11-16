/** Which albums the merge window offers to add (MergeAlbums.tsx), in order. What's typed comes first: the
 * library search's hits and the artist's own albums that match it. Without a search, the artist's albums
 * nearest the first one's year come first (a double album's other disc, a reissue's bonus disc), not their
 * oldest: an artist with many albums had the one wanted past the list's end. */

export interface Candidate { id: number; title: string; artist: string; year: number; kind: string; peer?: string | null }

export const SHOWN = 12;

export function mergeCandidates<T extends Candidate>(first: { year: number }, sameArtist: T[], found: T[], term: string,
                                                     taken: Set<number>): T[] {
  const q = term.trim().toLowerCase();
  const near = (x: T) => (x.year && first.year ? Math.abs(x.year - first.year) : 9999);
  const own = sameArtist
    .filter((x) => !q || `${x.title} ${x.artist}`.toLowerCase().includes(q))
    .sort((x, y) => near(x) - near(y));          // stable: the same distance keeps the server's order
  const seen = new Set<number>();
  return [...(q.length > 1 ? found : []), ...own].filter((x) => {
    if (taken.has(x.id) || x.peer || x.kind !== "music" || seen.has(x.id)) return false;
    seen.add(x.id);
    return true;
  }).slice(0, SHOWN);
}
