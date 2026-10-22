/** Shared pieces for browsing pages: the view/display switchers, the sort menu
 * and albums, artists and genres shown as a list, a grid or a gallery. */

import { Grid3x3, LayoutGrid, List, Play } from "lucide-react";
import type { CSSProperties, ReactNode } from "react";
import { Link } from "react-router-dom";
import { fmtLong, fmtNumber } from "../api";
import { playAlbum, playRandom } from "../actions";
import { useUi } from "../store/ui";
import type { Album, Artist, DisplayMode, Genre } from "../types";
import { AlbumCard, ArtistCard, GenreCard } from "./Cards";
import { Art } from "./ui";

export interface Choice<T extends string> { value: T; label: string; icon?: ReactNode; title?: string }

export function Segmented<T extends string>({ value, options, onChange, label, iconsOnPhone }: {
  value: T; options: Choice<T>[]; onChange: (v: T) => void; label: string; iconsOnPhone?: boolean;
}) {
  return (
    <div className={`seg ${iconsOnPhone ? "icons-sm" : ""}`} role="radiogroup" aria-label={label}>
      {options.map((o) => (
        <button key={o.value} role="radio" aria-checked={o.value === value} title={o.title || o.label}
                className={o.value === value ? "on" : ""} onClick={() => onChange(o.value)}>
          {o.icon}<span>{o.label}</span>
        </button>
      ))}
    </div>
  );
}

export const DISPLAY_MODES: Choice<DisplayMode>[] = [
  { value: "list", label: "List", icon: <List size={14} />, title: "List: one row per item, with details" },
  { value: "grid", label: "Grid", icon: <Grid3x3 size={14} />, title: "Grid: smaller covers, more on screen" },
  { value: "gallery", label: "Gallery", icon: <LayoutGrid size={14} />, title: "Gallery: large cover art" },
];

export function DisplaySwitch({ value, onChange }: { value: DisplayMode; onChange: (v: DisplayMode) => void }) {
  return <Segmented label="Display" value={value} options={DISPLAY_MODES} onChange={onChange} iconsOnPhone />;
}

export function SortMenu({ value, options, onChange }: { value: string; options: [string, string][]; onChange: (v: string) => void }) {
  return (
    <label className="sortmenu">
      <span className="seg-label">Sort</span>
      <select className="select" value={value} onChange={(e) => onChange(e.target.value)}>
        {options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
      </select>
    </label>
  );
}

/** Sort and display mode for one page, remembered per user. */
export function useBrowse(key: string, sorts: [string, string][], defaultSort = sorts[0][0], displayKey = key) {
  const browse = useUi((s) => s.browse);
  const setBrowse = useUi((s) => s.setBrowse);
  const saved = browse[key]?.sort;
  const sort = saved && sorts.some(([v]) => v === saved) ? saved : defaultSort;
  const display: DisplayMode = browse[displayKey]?.display || "gallery";
  return {
    sort, display,
    setSort: (v: string) => setBrowse(key, { sort: v }),
    setDisplay: (v: DisplayMode) => setBrowse(displayKey, { display: v }),
  };
}

export const ALBUM_SORTS: [string, string][] = [
  ["added", "Recently added"], ["name", "Title"], ["artist", "Artist"],
  ["year", "Newest first"], ["year_asc", "Oldest first"], ["played", "Most played"],
];
export const ARTIST_SORTS: [string, string][] = [
  ["name", "Name"], ["albums", "Most albums"], ["added", "Recently added"], ["played", "Most played"],
];
export const GENRE_SORTS: [string, string][] = [["albums", "Most albums"], ["artists", "Most artists"], ["name", "Name"]];

// ---------------------------------------------------------------- list rows

/** A list with a header row; `cols` and `colsSm` are grid-template-columns. */
export function Rows({ head, cols, colsSm, children }: { head: ReactNode[]; cols: string; colsSm: string; children: ReactNode }) {
  const style = { "--cols": cols, "--cols-sm": colsSm } as CSSProperties;
  return (
    <div className="lrows" style={style}>
      <div className="lrow head" aria-hidden>{head}</div>
      {children}
    </div>
  );
}

function PlayThumb({ art, name, round, onPlay }: { art: string | null; name: string; round?: boolean; onPlay?: () => void }) {
  return (
    <div className="l-thumb">
      <Art src={art} name={name} size={96} round={round} />
      {onPlay && (
        <button className={`l-play ${round ? "round" : ""}`} aria-label={`Play ${name}`}
                onClick={(e) => { e.preventDefault(); e.stopPropagation(); onPlay(); }}>
          <Play size={15} fill="currentColor" />
        </button>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- albums, artists, genres

export function AlbumItems({ items, display, vgm }: { items: Album[]; display: DisplayMode; vgm?: boolean }) {
  if (display !== "list")
    return <div className={`grid ${display === "grid" ? "compact" : ""}`}>{items.map((a) => <AlbumCard key={a.id} a={a} />)}</div>;
  return (
    <Rows cols="48px minmax(0, 2fr) minmax(0, 1.4fr) 64px minmax(0, 1fr) 64px 92px" colsSm="44px minmax(0, 1fr) 60px"
          head={["", vgm ? "Game" : "Album", vgm ? "Composer" : "Artist", "Year", vgm ? "Formats" : "Genre", vgm ? "Tunes" : "Songs", "Length"]
            .map((h, i) => <span key={i} className={i >= 2 && i !== 5 ? "l-opt" : i === 5 ? "l-num" : ""}>{h}</span>)}>
      {items.map((a) => (
        <Link key={a.id} to={`/album/${a.id}`} className="lrow">
          <PlayThumb art={a.art} name={a.title} onPlay={() => playAlbum(a.id)} />
          <div className="l-main">
            <div className="l-title ellipsis">{a.title}</div>
            <div className="l-sub ellipsis l-sm">{[a.artist, a.year || null].filter(Boolean).join(" · ")}</div>
          </div>
          <span className="l-col ellipsis l-opt">{a.artist}</span>
          <span className="l-col l-opt">{a.year || ""}</span>
          <span className="l-col ellipsis l-opt">{vgm ? a.formats.map((f) => f.toUpperCase()).join(", ") : a.genre}</span>
          <span className="l-num">{fmtNumber(a.track_count)}</span>
          <span className="l-num l-opt">{a.duration >= 60 ? fmtLong(a.duration) : a.duration > 0 ? "< 1 min" : ""}</span>
        </Link>
      ))}
    </Rows>
  );
}

export function ArtistItems({ items, display, linkTo }: { items: Artist[]; display: DisplayMode; linkTo?: (a: Artist) => string }) {
  if (display !== "list")
    return (
      <div className={`grid ${display === "grid" ? "compact" : ""}`}>
        {items.map((a) => <ArtistCard key={a.id} a={a} to={linkTo?.(a)} />)}
      </div>
    );
  return (
    <Rows cols="48px minmax(0, 2fr) minmax(0, 1.5fr) 80px" colsSm="44px minmax(0, 1fr) 60px"
          head={["", "Artist", "Genre", "Albums"].map((h, i) => <span key={i} className={i === 2 ? "l-opt" : i === 3 ? "l-num" : ""}>{h}</span>)}>
      {items.map((a) => (
        <Link key={a.id} to={linkTo?.(a) || `/artist/${a.id}`} className="lrow">
          <PlayThumb art={a.art} name={a.name} round onPlay={() => playRandom({ artist_id: a.id, kind: "all" })} />
          <div className="l-main">
            <div className="l-title ellipsis">{a.name}</div>
            <div className="l-sub ellipsis l-sm">{a.tags.slice(0, 3).join(", ") || a.genre}</div>
            <div className="l-sub ellipsis l-lg">{a.tags.slice(0, 4).join(", ")}</div>
          </div>
          <span className="l-col ellipsis l-opt">{a.genre}</span>
          <span className="l-num">{a.album_count ?? ""}</span>
        </Link>
      ))}
    </Rows>
  );
}

export function GenreItems({ items, display, linkTo }: { items: Genre[]; display: DisplayMode; linkTo?: (g: Genre) => string }) {
  if (display !== "list")
    return (
      <div className={`grid genres ${display === "grid" ? "compact" : ""}`}>
        {items.map((g) => <GenreCard key={g.name} g={g} to={linkTo?.(g)} />)}
      </div>
    );
  return (
    <Rows cols="48px minmax(0, 2fr) 90px 90px 90px" colsSm="44px minmax(0, 1fr) 70px"
          head={["", "Genre", "Artists", "Albums", "Songs"].map((h, i) => <span key={i} className={i === 2 || i === 4 ? "l-num l-opt" : i === 3 ? "l-num" : ""}>{h}</span>)}>
      {items.map((g) => (
        <Link key={g.name} to={linkTo?.(g) || `/genre/${encodeURIComponent(g.name)}`} className="lrow">
          <div className="l-thumb mosaic">{g.art.slice(0, 4).map((u) => <img key={u} src={`${u}?s=96`} alt="" loading="lazy" />)}</div>
          <div className="l-main"><div className="l-title ellipsis">{g.name}</div></div>
          <span className="l-num l-opt">{g.artists != null ? fmtNumber(g.artists) : ""}</span>
          <span className="l-num">{fmtNumber(g.albums)}</span>
          <span className="l-num l-opt">{fmtNumber(g.tracks)}</span>
        </Link>
      ))}
    </Rows>
  );
}
