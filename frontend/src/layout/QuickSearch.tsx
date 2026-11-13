/** The search field in the top bar: results show up while you type, from the section it's in (search/scope.ts),
 * or from everything with a * first. */

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ArrowRight, Play, Search, X } from "lucide-react";
import { Fragment, useEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { playTracks } from "../actions";
import { engine } from "../player/engine";
import { useSearchHere } from "../search/here";
import { parseQuery, SCOPE_NAMES } from "../search/scope";
import { fromEpisode, fromStation } from "../store/player";
import { linkData } from "../chat/store";
import { clearSearches, forgetSearch, picked, rememberSearch, useRecentSearches } from "../components/RecentSearches";
import { Art } from "../components/ui";
import type { RecentKind, SearchResults, Station } from "../types";

interface Hit {
  key: string; group: string; title: string; sub: string; art: string | null; round?: boolean; icon?: ReactNode; go: () => void;
  peer?: string | null;
  ref?: { kind: RecentKind; id: number };     // remembered in recent searches when picked
}

/** A line at the foot of the results: all of them, or the podcast directory's. */
interface Action { key: string; label: string; go: () => void }

let field: HTMLInputElement | null = null;

/** Focus the quick search if it's on screen (it hides on phones). */
export function focusQuickSearch(): boolean {
  if (!field || field.offsetParent === null) return false;
  field.focus();
  field.select();
  return true;
}

export function QuickSearch() {
  const [text, setText] = useState("");
  const [typed, setTyped] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const box = useRef<HTMLDivElement>(null);
  const nav = useNavigate();

  useEffect(() => {
    field = input.current;
    return () => { field = null; };
  }, []);
  useEffect(() => {
    const t = window.setTimeout(() => setTyped(text), 140);
    return () => window.clearTimeout(t);
  }, [text]);
  useEffect(() => {
    const away = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", away);
    return () => document.removeEventListener("mousedown", away);
  }, []);

  const here = useSearchHere();
  const { q, scope } = parseQuery(typed, here);
  const res = useQuery({
    queryKey: ["quicksearch", q, scope], enabled: q.length >= 2, staleTime: 30_000, placeholderData: keepPreviousData,
    queryFn: () => api.get<SearchResults>("/api/search", { q, scope, limit: 6 }),
  });
  // radio's: every station (radio-browser), after the saved ones
  const stations = useQuery({
    queryKey: ["quicksearch-stations", q], enabled: scope === "radio" && q.length >= 2, staleTime: 60_000,
    queryFn: () => api.get<Station[]>("/api/radio/search", { q, limit: 6 }),
  });

  const hits = useMemo<Hit[]>(() => {
    const r = res.data;
    if (!r) return [];
    const music = r.albums.filter((a) => a.kind !== "vgm").slice(0, 4);
    const games = r.albums.filter((a) => a.kind === "vgm").slice(0, 3);
    return [
      ...r.artists.slice(0, 4).map((a) => ({
        key: `ar${a.id}`, group: "Artists", ref: { kind: "artist" as const, id: a.id }, title: a.name, sub: a.tags.slice(0, 3).join(", ") || a.genre || "Artist",
        art: a.art, round: true, go: () => nav(`/library/artists/${a.id}`),
      })),
      ...r.tracks.slice(0, 5).map((t, i) => ({
        key: `t${t.id}`, group: "Songs", ref: { kind: "track" as const, id: t.id }, title: t.title,
        sub: [t.artist, t.kind === "vgm" ? t.system : null, t.album].filter(Boolean).join(" · "),
        art: t.art, icon: <Play size={14} fill="currentColor" />, go: () => playTracks(r.tracks.slice(0, 5), i), peer: t.peer,
      })),
      ...music.map((a) => ({
        key: `al${a.id}`, group: "Albums", ref: { kind: "album" as const, id: a.id }, title: a.title, sub: [a.artist, a.year || null].filter(Boolean).join(" · "),
        art: a.art, go: () => nav(`/album/${a.id}`), peer: a.peer,
      })),
      ...games.map((a) => ({
        key: `al${a.id}`, group: "Games", ref: { kind: "album" as const, id: a.id }, title: a.title, sub: [a.artist, `${a.track_count} tunes`].filter(Boolean).join(" · "),
        art: a.art, go: () => nav(`/album/${a.id}`), peer: a.peer,
      })),
      ...r.books.slice(0, 3).map((b) => ({
        key: `b${b.id}`, group: "Audiobooks", ref: { kind: "book" as const, id: b.id }, title: b.title, sub: [b.author, b.series].filter(Boolean).join(" · ") || "Audiobook",
        art: b.art, go: () => nav(`/audiobooks/${b.id}`), peer: b.peer,
      })),
      ...(r.podcasts || []).slice(0, 4).map((f) => ({
        key: `p${f.id}`, group: "Podcasts", title: f.title, sub: f.author || "Podcast", art: f.image || null,
        go: () => nav(`/podcasts/${f.id}`),
      })),
      ...(r.episodes || []).slice(0, 5).map((e) => ({
        key: `e${e.id}`, group: "Episodes", title: e.title, sub: e.feed_title || "Episode", art: e.image || null,
        icon: <Play size={14} fill="currentColor" />, go: () => engine.play([fromEpisode(e)]),
      })),
      ...(r.stations || []).slice(0, 5).map((st) => ({
        key: `s${st.id}`, group: "Saved stations", title: st.name, sub: [st.country, st.tags].filter(Boolean).join(" · ") || "Station",
        art: st.favicon || null, icon: <Play size={14} fill="currentColor" />, go: () => engine.play([fromStation(st)]),
      })),
      ...(stations.data || []).filter((st) => !(r.stations || []).some((m) => m.uuid && m.uuid === st.uuid)).slice(0, 5)
        .map((st) => ({
          key: `d${st.uuid}`, group: "Stations", title: st.name, sub: [st.country, st.tags].filter(Boolean).join(" · ") || "Station",
          art: st.favicon || null, icon: <Play size={14} fill="currentColor" />, go: () => engine.play([fromStation(st)]),
        })),
    ];
  }, [res.data, stations.data, nav]);

  // with nothing typed, the dropdown lists recent searches instead
  const recent = useRecentSearches();
  const recentHits = useMemo<Hit[]>(() => (recent.data || []).slice(0, 8).map((e) => {
    const p = picked(e, nav);
    return { key: `r${p.kind}${p.id}`, group: "Recent searches", title: p.title, sub: p.sub, art: p.art, round: p.round,
             go: p.go, ref: { kind: p.kind, id: p.id }, peer: p.peer };
  }), [recent.data, nav]);
  const recentMode = !text.trim();
  const list = recentMode ? recentHits : hits;
  const actions: Action[] = recentMode ? [] : [
    { key: "all", label: `All results for “${q}”`, go: () => nav(`/search?${new URLSearchParams({ q, in: scope })}`) },
    ...(scope === "podcasts" ? [{ key: "find", label: `Find new podcasts: “${q}”`, go: () => nav(`/podcasts?${new URLSearchParams({ find: q })}`) }] : []),
  ];

  useEffect(() => {
    setActive(0);
  }, [q, scope, recentMode]);
  useEffect(() => {
    document.getElementById(`qs-${active}`)?.scrollIntoView({ block: "nearest" });
  }, [active]);

  const close = () => {
    setOpen(false);
    setText("");
    input.current?.blur();
  };
  const pick = (i: number) => {
    if (i < list.length) {
      const ref = list[i].ref;
      if (ref) rememberSearch(ref.kind, ref.id);
      list[i].go();
    } else actions[i - list.length]?.go();
    close();
  };
  const key = (e: KeyboardEvent<HTMLInputElement>) => {
    const n = list.length + actions.length;    // results end with the "all results" line (and the directory's)
    if (e.key === "ArrowDown" && n) { e.preventDefault(); setOpen(true); setActive((a) => (a + 1) % n); }
    else if (e.key === "ArrowUp" && n) { e.preventDefault(); setActive((a) => (a - 1 + n) % n); }
    else if (e.key === "Enter" && (recentMode ? list.length > 0 : q.length >= 2)) { e.preventDefault(); pick(active); }
    else if (e.key === "Escape") { e.preventDefault(); if (text) setText(""); else close(); }
  };

  const showing = open && (recentMode ? recentHits.length > 0 : q.length >= 2);
  return (
    <div className={`qsearch ${showing ? "open" : ""}`} ref={box}>
      <Search size={14} className="qs-icon" />
      <input ref={input} type="search" placeholder={`Search ${SCOPE_NAMES[here]}`} value={text} spellCheck={false} autoComplete="off"
             role="combobox" aria-label="Search the library" aria-expanded={showing} aria-controls="qs-pop"
             aria-activedescendant={showing ? `qs-${active}` : undefined}
             onFocus={() => setOpen(true)} onChange={(e) => { setText(e.target.value); setOpen(true); }} onKeyDown={key} />
      {!text && <span className="keychip qs-key" aria-hidden>/</span>}
      {showing && (
        <div className="qs-pop" id="qs-pop" role="listbox" aria-label={recentMode ? "Recent searches" : "Search results"}>
          <div className="qs-scope">
            {scope === "all" ? <>Searching <b>everything</b></> : <>Searching <b>{SCOPE_NAMES[scope]}</b> · <kbd className="keychip star">*</kbd> first searches everything</>}
          </div>
          {!recentMode && res.data && !hits.length && !stations.isFetching && <div className="qs-empty">Nothing found for “{q}”</div>}
          {list.map((h, i) => (
            <Fragment key={h.key}>
              {(i === 0 || list[i - 1].group !== h.group) && <div className="qs-group">{h.group}</div>}
              <div id={`qs-${i}`} role="option" aria-selected={i === active} className={`qs-item ${i === active ? "on" : ""}`}
                   data-link={h.ref && (h.ref.kind === "album" || h.ref.kind === "track") ? linkData(h.ref.kind, h.ref.id, h.title, h.sub, h.art) : undefined}
                   onMouseEnter={() => setActive(i)} onMouseDown={(e) => e.preventDefault()} onClick={() => pick(i)}>
                <Art src={h.art} name={h.title} size={96} round={h.round} peer={h.peer} />
                <span className="qs-text">
                  <span className="qs-title ellipsis">{h.title}</span>
                  <span className="qs-sub ellipsis">{h.sub}</span>
                </span>
                {recentMode ? (
                  <button className="qs-x" aria-label={`Remove ${h.title} from recent searches`} data-tip="Remove from recent searches"
                          onClick={(e) => { e.stopPropagation(); if (h.ref) forgetSearch(h.ref.kind, h.ref.id); }}><X size={15} /></button>
                ) : h.icon}
              </div>
            </Fragment>
          ))}
          <div className="qs-actions">
            {recentMode ? (
              <button className="qs-all" onMouseDown={(e) => e.preventDefault()} onClick={clearSearches}>Clear recent searches</button>
            ) : actions.map((a, j) => {
              const i = list.length + j;
              return (
                <button key={a.key} id={`qs-${i}`} role="option" aria-selected={active === i} className={`qs-all ${active === i ? "on" : ""}`}
                        onMouseEnter={() => setActive(i)} onMouseDown={(e) => e.preventDefault()} onClick={() => pick(i)}>
                  {a.label} <ArrowRight size={14} />
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
