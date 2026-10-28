/** "Your library": the left panel of the desktop layout, after Spotify's. Section chips
 * filter a list of what you saved, follow, listen to or played lately; a chip also
 * leads to its full section page. Collapses to a strip of covers. */

import { useQuery } from "@tanstack/react-query";
import { ChevronRight, Heart, Library, PanelLeftClose, Play, Plus } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import { api } from "../api";
import { playAlbum, playTracks } from "../actions";
import { Art, NewDot } from "../components/ui";
import { engine } from "../player/engine";
import { sp } from "../player/spotify";
import { fromStation } from "../store/player";
import { useUi } from "../store/ui";
import type { FilePlaylistDetail, Playlist, SidebarData } from "../types";

type Chip = "playlists" | "albums" | "artists" | "vgm" | "books" | "podcasts" | "radio" | "spotify";

const CHIPS: { id: Chip; label: string; browse: [string, string] }[] = [
  { id: "playlists", label: "Playlists", browse: ["/library/playlists", "All playlists"] },
  { id: "albums", label: "Albums", browse: ["/library/albums", "Browse all albums"] },
  { id: "artists", label: "Artists", browse: ["/library/artists", "Browse all artists"] },
  { id: "vgm", label: "VGM", browse: ["/vgm", "Browse all VGM"] },
  { id: "books", label: "Books", browse: ["/audiobooks", "All audiobooks"] },
  { id: "podcasts", label: "Podcasts", browse: ["/podcasts", "Find podcasts"] },
  { id: "radio", label: "Radio", browse: ["/radio", "Find stations"] },
  { id: "spotify", label: "Spotify", browse: ["/spotify", "Open Spotify"] },
];

interface Row {
  key: string; chip: Chip; title: string; sub: string; art: ReactNode;
  to?: string; onOpen?: () => void; onPlay?: () => void;
  dot?: string;              // a blue dot before the subtitle (or on the cover, folded), saying this
}

/** True while the media query matches (the panel collapses on narrower windows). */
function useMedia(query: string) {
  const [match, setMatch] = useState(() => window.matchMedia(query).matches);
  useEffect(() => {
    const m = window.matchMedia(query);
    const on = () => setMatch(m.matches);
    m.addEventListener("change", on);
    return () => m.removeEventListener("change", on);
  }, [query]);
  return match;
}

function remember(): Chip | "" {
  try { return (localStorage.getItem("muzix.libchip") as Chip) || ""; } catch { return ""; }
}

async function playPlaylist(id: number) {
  const p = await api.get<Playlist>(`/api/playlists/${id}`);
  if (p.tracks?.length) playTracks(p.tracks, 0);
}

async function playFilePlaylist(id: number) {
  const p = await api.get<FilePlaylistDetail>(`/api/file-playlists/${id}`);
  if (p.tracks.length) playTracks(p.tracks, 0);
}

export function Sidebar() {
  const { sidebarCollapsed, setPref } = useUi();
  const narrow = useMedia("(max-width: 1100px)");
  const collapsed = sidebarCollapsed || narrow;
  const [chip, setChip] = useState<Chip | "">(remember);
  const nav = useNavigate();
  const data = useQuery({ queryKey: ["sidebar"], queryFn: () => api.get<SidebarData>("/api/sidebar"), refetchInterval: 60_000 });
  const spStatus = useQuery({ queryKey: ["sp-status"], queryFn: () => api.get<{ linked: boolean }>("/api/spotify/status") });
  const spLists = useQuery({
    queryKey: ["sp-sidebar"], enabled: chip === "spotify" && !!spStatus.data?.linked, staleTime: 300_000,
    queryFn: () => sp<{ items: { id: string; name: string; images: { url: string }[] | null; owner: { display_name: string } }[] }>("me/playlists?limit=50"),
  });

  const pick = (c: Chip) => {
    const next = chip === c ? "" : c;
    setChip(next);
    try { localStorage.setItem("muzix.libchip", next); } catch { /* private mode */ }
  };

  const d = data.data;
  const rows: Row[] = [];
  if (d) {
    rows.push({ key: "liked", chip: "playlists", title: "Liked songs", sub: `Playlist · ${d.liked_songs} songs`,
                art: <div className="lib-liked"><Heart size={18} fill="currentColor" /></div>, to: "/library/liked" });
    for (const p of d.playlists)
      rows.push({ key: `p${p.id}`, chip: "playlists", title: p.name, sub: "Playlist", art: <Art src={p.art} name={p.name} size={96} />,
                  to: `/playlist/${p.id}`, onPlay: () => playPlaylist(p.id) });
    for (const f of d.file_playlists || [])
      rows.push({ key: `fp${f.id}`, chip: "playlists", title: f.name, sub: `Playlist file · ${f.tracks} songs`,
                  art: <Art src={f.art} name={f.name} size={96} />, to: `/playlist/file/${f.id}`, onPlay: () => playFilePlaylist(f.id) });
    for (const b of d.books)
      rows.push({ key: `b${b.id}`, chip: "books", title: b.title, sub: `Audiobook · ${Math.round(b.progress * 100)} %`,
                  art: <Art src={b.art} name={b.title} size={96} />, to: `/audiobooks/${b.id}` });
    for (const a of d.albums)
      rows.push({ key: `a${a.id}`, chip: "albums", title: a.title, sub: `Album · ${a.artist}`, art: <Art src={a.art} name={a.title} size={96} />,
                  to: `/album/${a.id}`, onPlay: () => playAlbum(a.id) });
    for (const a of d.games)
      rows.push({ key: `g${a.id}`, chip: "vgm", title: a.title, sub: `Game · ${a.artist || "VGM"}`, art: <Art src={a.art} name={a.title} size={96} />,
                  to: `/album/${a.id}`, onPlay: () => playAlbum(a.id) });
    for (const p of d.podcasts)
      rows.push({ key: `f${p.id}`, chip: "podcasts", title: p.title, sub: `Podcast${p.author ? ` · ${p.author}` : ""}`,
                  art: <Art src={p.art} name={p.title} size={96} />, to: `/podcasts/${p.id}`, dot: p.new ? "New episodes" : undefined });
    for (const s of d.stations)
      rows.push({ key: `s${s.id}`, chip: "radio", title: s.name, sub: `Station${s.country ? ` · ${s.country}` : ""}`,
                  art: <Art src={s.favicon || null} name={s.name} size={96} />, onOpen: () => engine.play([fromStation(s)], 0) });
    for (const a of d.artists)
      rows.push({ key: `r${a.id}`, chip: "artists", title: a.name, sub: "Artist", art: <Art src={a.art} name={a.name} size={96} round />,
                  to: `/library/artists/${a.id}` });
  }
  for (const p of spLists.data?.items || [])
    rows.push({ key: `sp${p.id}`, chip: "spotify", title: p.name, sub: `Spotify · ${p.owner?.display_name || "playlist"}`,
                art: <Art src={p.images?.[0]?.url || null} name={p.name} size={96} />, to: `/spotify/playlist/${p.id}` });

  // the strip of covers has no chips, so it always shows everything
  const filter = collapsed ? "" : chip;
  const shown = filter ? rows.filter((r) => r.chip === filter) : rows.filter((r) => r.chip !== "spotify");
  const chips = CHIPS.filter((c) => c.id !== "spotify" || spStatus.data?.linked);
  const browse = filter ? CHIPS.find((c) => c.id === filter)!.browse : null;

  return (
    <aside className={`dock sidepanel ${collapsed ? "collapsed" : ""}`} aria-label="Your library">
      <div className="lib-head">
        <button className="lib-title" onClick={() => (narrow ? nav("/library") : setPref("sidebar_collapsed", !sidebarCollapsed))}
                data-tip={narrow ? "Open your library" : collapsed ? "Show your library" : "Collapse to covers"} aria-expanded={!collapsed}>
          {collapsed ? <Library size={20} /> : <PanelLeftClose size={18} />}
          <span>Your library</span>
        </button>
        <button className="iconbtn lib-add" data-tip="New playlist" aria-label="New playlist"
                onClick={() => nav("/library/playlists", { state: { create: true } })}><Plus size={16} /></button>
      </div>
      <div className="lib-chips" role="toolbar" aria-label="Show">
        {chips.map((c) => (
          <button key={c.id} className={`lib-chip ${chip === c.id ? "on" : ""}`} aria-pressed={chip === c.id} onClick={() => pick(c.id)}>
            {c.label}
          </button>
        ))}
      </div>
      <div className="lib-list">
        {browse && (
          <NavLink to={browse[0]} end className="lib-row lib-browse" data-tip={collapsed ? browse[1] : undefined}>
            <div className="lib-art lib-browse-icon"><ChevronRight size={18} /></div>
            <div className="lib-text"><div className="lib-name">{browse[1]}</div></div>
          </NavLink>
        )}
        {shown.map((r) => {
          const body = (
            <>
              <div className="lib-art">
                {r.art}
                {(r.onPlay || r.onOpen) && (
                  <span className="lib-play" aria-hidden data-tip={`Play ${r.title}`}><Play size={16} fill="currentColor" /></span>
                )}
                {r.dot && collapsed && <NewDot label={r.dot} />}
              </div>
              <div className="lib-text">
                <div className="lib-name ellipsis">{r.title}</div>
                <div className="lib-sub ellipsis">{r.dot && <NewDot label={r.dot} />}{r.sub}</div>
              </div>
            </>
          );
          return r.to ? (
            <NavLink key={r.key} to={r.to} end className="lib-row" data-tip={collapsed ? [r.title, r.sub].filter(Boolean).join(" · ") : undefined}
                     onClick={(e) => { if ((e.target as HTMLElement).closest(".lib-play") && r.onPlay) { e.preventDefault(); r.onPlay(); } }}>
              {body}
            </NavLink>
          ) : (
            <button key={r.key} className="lib-row" data-tip={`Play ${r.title}`} onClick={r.onOpen}>{body}</button>
          );
        })}
        {d && !shown.length && !collapsed && (
          <p className="lib-empty">
            {chip ? "Nothing here yet." : "Albums you play or like, playlists, audiobooks you listen to and saved stations show up here."}
          </p>
        )}
      </div>
    </aside>
  );
}
