/** Recent searches, as on Spotify: what you picked from search results, newest first.
 * The server keeps them per user, so they follow you between devices. */

import { useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";
import { useNavigate, type NavigateFunction } from "react-router-dom";
import { api } from "../api";
import { playTracks, queryClient } from "../actions";
import type { RecentKind, RecentSearch } from "../types";
import { Art, Section } from "./ui";

export interface Picked {
  kind: RecentKind; id: number; title: string; sub: string; art: string | null; round?: boolean; go: () => void;
}

const KEY = ["recent-searches"];
const changed = () => queryClient.invalidateQueries({ queryKey: KEY });

export function rememberSearch(kind: RecentKind, id: number) {
  api.post("/api/search/recent", { kind, id }).then(changed).catch(() => {});
}

export function forgetSearch(kind: RecentKind, id: number) {
  api.del(`/api/search/recent/${kind}/${id}`).then(changed).catch(() => {});
}

export function clearSearches() {
  api.del("/api/search/recent").then(changed).catch(() => {});
}

export function useRecentSearches() {
  return useQuery({ queryKey: KEY, queryFn: () => api.get<RecentSearch[]>("/api/search/recent"), staleTime: 30_000 });
}

/** A recent search as a row: what it is, and what picking it again does. */
export function picked(e: RecentSearch, nav: NavigateFunction): Picked {
  switch (e.kind) {
    case "artist":
      return { kind: "artist", id: e.item.id, title: e.item.name, sub: "Artist", art: e.item.art, round: true,
               go: () => nav(`/library/artists/${e.item.id}`) };
    case "album":
      return { kind: "album", id: e.item.id, title: e.item.title, sub: `${e.item.kind === "vgm" ? "Game" : "Album"} · ${e.item.artist}`,
               art: e.item.art, go: () => nav(`/album/${e.item.id}`) };
    case "track":
      return { kind: "track", id: e.item.id, title: e.item.title, sub: `Song · ${e.item.artist}`, art: e.item.art,
               go: () => playTracks([e.item]) };
    case "book":
      return { kind: "book", id: e.item.id, title: e.item.title, sub: `Audiobook${e.item.author ? ` · ${e.item.author}` : ""}`,
               art: e.item.art, go: () => nav(`/audiobooks/${e.item.id}`) };
  }
}

/** The Search page's list while nothing is typed (the phone's way in). */
export function RecentSearches() {
  const nav = useNavigate();
  const q = useRecentSearches();
  if (!q.data?.length) return null;
  return (
    <Section title="Recent searches">
      <div className="recent-list">
        {q.data.slice(0, 20).map((e) => {
          const p = picked(e, nav);
          return (
            <div key={`${p.kind}${p.id}`} className="recent-row">
              <button className="recent-open" onClick={() => { rememberSearch(p.kind, p.id); p.go(); }}>
                <Art src={p.art} name={p.title} size={96} round={p.round} />
                <span className="qs-text">
                  <span className="qs-title ellipsis">{p.title}</span>
                  <span className="qs-sub ellipsis">{p.sub}</span>
                </span>
              </button>
              <button className="recent-x" aria-label={`Remove ${p.title} from recent searches`} title="Remove"
                      onClick={() => forgetSearch(p.kind, p.id)}><X size={16} /></button>
            </div>
          );
        })}
      </div>
      <button className="btn small ghost recent-clear" onClick={clearSearches}>Clear recent searches</button>
    </Section>
  );
}
