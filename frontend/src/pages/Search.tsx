/** Search's page: everything found for what's typed, in the section searched (search/scope.ts): the one the
 * search field was in (?in=), or everything with a * first. On a phone, the Search tab, from the section
 * it was opened in (layout/Mobile.tsx). */

import { useQuery } from "@tanstack/react-query";
import { ArrowRight } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { GenreItems } from "../components/Browse";
import { AlbumCard, ArtistCard } from "../components/Cards";
import { RecentSearches, rememberSearch } from "../components/RecentSearches";
import { TrackList } from "../components/TrackList";
import { Art, Empty, Kicker, Section } from "../components/ui";
import { isScope, parseQuery, type Scope, SCOPE_NAMES, shownScope } from "../search/scope";
import { useUi } from "../store/ui";
import type { Genre, RecentKind, SearchResults, Station } from "../types";
import { EpisodeRow } from "./Podcasts";
import { StationGrid } from "./Radio";

const HINTS: Record<Scope, string> = {
  all: "Music, games, audiobooks, your podcasts and stations…",
  music: "Artists, songs, albums…",
  vgm: "Games, tunes, composers…",
  audiobooks: "Titles, authors, series…",
  podcasts: "Your podcasts and their episodes…",
  radio: "Stations, saved or any…",
};

/** A search result that goes into recent searches when it's opened or played (not its admin menu). */
function Remember({ kind, id, children }: { kind: RecentKind; id: number; children: ReactNode }) {
  return (
    <div className="contents" onClickCapture={(e) => { if (!(e.target as Element).closest(".admin-cog, .menu")) rememberSearch(kind, id); }}>
      {children}
    </div>
  );
}

export default function SearchPage() {
  const [params, setParams] = useSearchParams();
  const modules = useUi((s) => s.modules);
  const asked = params.get("in");
  const here = shownScope(isScope(asked) ? asked : "all", modules);
  const [text, setText] = useState(params.get("q") || "");
  const { q: qs, scope } = parseQuery(params.get("q") || "", here);
  useEffect(() => {
    const t = window.setTimeout(() => setParams(text ? { q: text, in: here } : { in: here }, { replace: true }), 250);
    return () => window.clearTimeout(t);
  }, [text, here, setParams]);
  const q = useQuery({
    queryKey: ["search", qs, scope], enabled: qs.length > 1,
    queryFn: () => api.get<SearchResults>("/api/search", { q: qs, scope, limit: 24 }),
  });
  // radio's: every station (radio-browser), after the saved ones
  const any = useQuery({
    queryKey: ["search-stations", qs], enabled: scope === "radio" && qs.length > 1, staleTime: 60_000,
    queryFn: () => api.get<Station[]>("/api/radio/search", { q: qs, limit: 30 }),
  });
  const saved = useQuery({ queryKey: ["stations"], enabled: scope === "radio" || scope === "all", queryFn: () => api.get<Station[]>("/api/radio/stations") });
  const r = q.data;
  const podcasts = r?.podcasts || [], episodes = r?.episodes || [], stations = r?.stations || [];
  const others = (any.data || []).filter((st) => !stations.some((m) => m.uuid && m.uuid === st.uuid));
  const nothing = r && !r.artists.length && !r.albums.length && !r.tracks.length && !r.books.length && !podcasts.length
    && !episodes.length && !stations.length && !(scope === "radio" && (any.isFetching || others.length));
  // Spotify-style "Browse all" while nothing is typed: music's genres
  const browse = !qs && (here === "all" || here === "music");
  const genres = useQuery({ queryKey: ["genres", "albums"], queryFn: () => api.get<Genre[]>("/api/genres", { sort: "albums", limit: 500 }), enabled: browse });
  const [desktop] = useState(() => window.matchMedia("(min-width: 861px)").matches);
  const music = r?.albums.filter((a) => a.kind !== "vgm") || [];
  const games = r?.albums.filter((a) => a.kind === "vgm") || [];
  return (
    <div className="page wide">
      <Kicker parts={["Search", SCOPE_NAMES[scope]]} />
      <input className="input searchbox" autoFocus={desktop} placeholder={HINTS[here]} value={text}
             aria-label={`Search ${SCOPE_NAMES[here]}`} onChange={(e) => setText(e.target.value)} />
      {here !== "all" && <p className="help search-scope">Searching {SCOPE_NAMES[here]}: <kbd className="keychip star">*</kbd> first searches everything.</p>}
      {!qs && <RecentSearches />}
      {browse && genres.data && genres.data.length > 0 && (
        <Section title="Browse all"><GenreItems items={genres.data} display="gallery" linkTo={(g) => `/library/genres/${encodeURIComponent(g.name)}`} /></Section>
      )}
      {nothing && <Empty title={`Nothing found for "${qs}"`} />}
      {r && r.artists.length > 0 && (
        <Section title="Artists">
          <div className="scroller">{r.artists.map((a) => <Remember key={a.id} kind="artist" id={a.id}><ArtistCard a={a} /></Remember>)}</div>
        </Section>
      )}
      {r && r.tracks.length > 0 && (
        <Section title={scope === "vgm" ? "Tunes" : "Songs"}><TrackList tracks={r.tracks.slice(0, 10)} showArt onPlay={(t) => rememberSearch("track", t.id)} /></Section>
      )}
      {music.length > 0 && (
        <Section title="Albums">
          <div className="grid">{music.map((a) => <Remember key={a.id} kind="album" id={a.id}><AlbumCard a={a} /></Remember>)}</div>
        </Section>
      )}
      {games.length > 0 && (
        <Section title="Games">
          <div className="grid">{games.map((a) => <Remember key={a.id} kind="album" id={a.id}><AlbumCard a={a} /></Remember>)}</div>
        </Section>
      )}
      {r && r.books.length > 0 && (
        <Section title="Audiobooks">
          <div className="grid">{r.books.map((b) => (
            <Link key={b.id} to={`/audiobooks/${b.id}`} className="card" onClick={() => rememberSearch("book", b.id)}>
              <Art src={b.art} name={b.title} peer={b.peer} />
              <div className="card-title ellipsis">{b.title}</div>
              <div className="card-sub ellipsis">{b.author || "Unknown author"}</div>
            </Link>
          ))}</div>
        </Section>
      )}
      {podcasts.length > 0 && (
        <Section title="Podcasts">
          <div className="grid">{podcasts.map((f) => (
            <Link key={f.id} to={`/podcasts/${f.id}`} className="card">
              <Art src={f.image || null} name={f.title} />
              <div className="card-title ellipsis">{f.title}</div>
              <div className="card-sub ellipsis">{f.author || "Podcast"}</div>
            </Link>
          ))}</div>
        </Section>
      )}
      {episodes.length > 0 && (
        <Section title="Episodes"><div className="list">{episodes.map((e) => <EpisodeRow key={e.id} e={e} />)}</div></Section>
      )}
      {scope === "podcasts" && qs.length > 1 && (
        <Link className="btn" to={`/podcasts?${new URLSearchParams({ find: qs })}`}>Find new podcasts: “{qs}” <ArrowRight size={14} /></Link>
      )}
      {stations.length > 0 && (
        <Section title="Saved stations"><StationGrid list={stations.map((s) => ({ ...s, uuid: s.uuid || "" }))} saved={saved.data || stations} /></Section>
      )}
      {others.length > 0 && <Section title="Stations"><StationGrid list={others} saved={saved.data || stations} /></Section>}
    </div>
  );
}
