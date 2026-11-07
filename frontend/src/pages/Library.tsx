import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { ChevronRight, Disc3, Heart, ListPlus, Mic2, Play, Plus, Shuffle, Tags, Trash2, UserRound } from "lucide-react";
import { Fragment, useCallback, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { Link, Navigate, NavLink, useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api, fmtLong, fmtNumber, sized } from "../api";
import { playAlbum, playRandom, playTracks, queryClient, toggleLike, usePlaylistPicker } from "../actions";
import {
  ALBUM_SORTS, AlbumItems, ARTIST_SORTS, ArtistItems, DisplaySwitch, GENRE_SORTS, GenreItems, Segmented, SortMenu,
  useBrowse, type Choice,
} from "../components/Browse";
import { AdminCog } from "../components/AdminMode";
import { AlbumCard, ArtistCard, MosaicCard, PlaylistCard } from "../components/Cards";
import { RecentSearches, rememberSearch } from "../components/RecentSearches";
import { TrackList } from "../components/TrackList";
import { Art, Display, Empty, FromPeer, Kicker, Loading, Modal, Section, useInView } from "../components/ui";
import { useUi } from "../store/ui";
import type {
  Album, AlbumDetail, Artist, ArtistDetail, FilePlaylist, FilePlaylistDetail, Genre, LibraryView, Paged, Playlist, RecentKind, SearchResults,
  TagDetail, Track,
} from "../types";

function LibraryNav() {
  const { pathname } = useLocation();
  const browsing = !/^\/library\/(liked|playlists)/.test(pathname);
  return (
    <nav className="subnav">
      <Link to="/library" className={browsing ? "active" : ""}>Browse</Link>
      <NavLink to="/library/liked" className={({ isActive }) => (isActive ? "active" : "")}>Liked songs</NavLink>
      <NavLink to="/library/playlists" className={({ isActive }) => (isActive ? "active" : "")}>Playlists</NavLink>
    </nav>
  );
}

interface PageAt { offset: number; limit: number }

/** A list a page at a time, from `start` on (a letter jumped to): the pages after it load as the end
 * comes into view, the ones before it as the top does. */
function usePaged<T>(key: unknown[], path: string, params: Record<string, string | number | boolean | undefined>, size = 60,
                     start = 0) {
  return useInfiniteQuery({
    queryKey: [...key, params, start],
    queryFn: ({ pageParam }) => api.get<Paged<T>>(path, { ...params, limit: pageParam.limit, offset: pageParam.offset }),
    initialPageParam: { offset: start, limit: size } as PageAt,
    getNextPageParam: (last, _all, at): PageAt | undefined => {
      const n = at.offset + last.items.length;
      return last.items.length && n < last.total ? { offset: n, limit: size } : undefined;
    },
    getPreviousPageParam: (_first, _all, at): PageAt | undefined => {
      const from = Math.max(0, at.offset - size);
      return at.offset > 0 ? { offset: from, limit: at.offset - from } : undefined;
    },
  });
}

/** The page's scroller (the frame), the bars that stick to its top, and where their bottom is. */
function scrollerOf(el: HTMLElement | null) {
  const scroller = el?.closest<HTMLElement>(".frame-scroll") || null;
  const bars = scroller?.querySelector<HTMLElement>(".browse-sticky") || null;
  const line = (bars || scroller)?.getBoundingClientRect()[bars ? "bottom" : "top"] ?? 0;
  return { scroller, bars, line };
}

const STUCK_PADDING = 18;      // .browse-sticky.stuck's padding (base.css)

interface Jump { seq: number; at: number }      // the nth jump, to this place in the whole list
const ITEMS = ":scope > .grid > *, .lrow";      // a list's items, as gallery or grid cards or as rows

/** Loads more pages as the end of the list scrolls into view (and earlier ones at its top, after a
 * jump). `onTop` hears the place in the whole list of the first item under the bars; a new `jump`
 * brings the item it's to up to the bars. */
function Infinite<T>({ q, children, empty, onTop, jump }: {
  q: ReturnType<typeof usePaged<T>>; children: (items: T[]) => ReactNode; empty?: ReactNode;
  onTop?: (index: number) => void; jump?: Jump;
}) {
  const more = useCallback(() => { if (q.hasNextPage && !q.isFetchingNextPage) q.fetchNextPage(); }, [q]);
  const before = useCallback(() => { if (q.hasPreviousPage && !q.isFetchingPreviousPage) q.fetchPreviousPage(); }, [q]);
  const sentinel = useInView(more, !!q.hasNextPage);
  const top = useInView(before, !!q.hasPreviousPage);
  const list = useRef<HTMLDivElement>(null);
  const items = q.data?.pages.flatMap((p) => p.items) || [];
  const first = (q.data?.pageParams[0] as PageAt | undefined)?.offset ?? 0;

  // pages put in above: what was on screen stays where it was
  const was = useRef({ first, height: 0 });
  useLayoutEffect(() => {
    const { scroller } = scrollerOf(list.current);
    if (!scroller) return;
    if (first < was.current.first && was.current.height)
      scroller.scrollBy({ top: scroller.scrollHeight - was.current.height, behavior: "instant" });
    was.current = { first, height: scroller.scrollHeight };
  });

  // a letter picked: its first item just under the bars (earlier pages may be here already)
  const jumped = useRef<number | undefined>(undefined);
  const target = useRef<number | undefined>(undefined);
  useLayoutEffect(() => {
    if (!jump || jump.seq === jumped.current || !list.current) return;
    const node = list.current.querySelectorAll<HTMLElement>(ITEMS)[jump.at - first];
    if (jump.at < first || !node) return;         // its page isn't here yet
    jumped.current = jump.seq;
    target.current = jump.at;
    const { scroller, bars } = scrollerOf(list.current);
    if (!scroller) return;
    // the bars as they are once stuck (they're taller then), and the item's row right under them
    const barsHeight = bars ? bars.offsetHeight + (bars.classList.contains("stuck") ? 0 : STUCK_PADDING) : 0;
    const top = node.getBoundingClientRect().top - scroller.getBoundingClientRect().top - barsHeight - 6;
    scroller.scrollBy({ top, behavior: "instant" });
  });

  useEffect(() => {
    if (!onTop || !list.current) return;
    const { scroller } = scrollerOf(list.current);
    if (!scroller) return;
    let frame = 0;
    const look = () => {
      frame = 0;
      const nodes = list.current?.querySelectorAll<HTMLElement>(ITEMS);
      if (!nodes?.length) return;
      const { line } = scrollerOf(list.current);
      let lo = 0, hi = nodes.length - 1;
      while (lo < hi) {             // the first one mostly out from under the bars
        const mid = (lo + hi) >> 1;
        const r = nodes[mid].getBoundingClientRect();
        if (r.bottom > line + r.height * 0.35) hi = mid;
        else lo = mid + 1;
      }
      // a row of cards can hold the end of one letter and the start of the next: the one jumped
      // to is the one looked at while its row is the top one
      const rowTop = nodes[lo].getBoundingClientRect().top;
      let end = lo;
      while (end + 1 < nodes.length && Math.abs(nodes[end + 1].getBoundingClientRect().top - rowTop) < 2) end++;
      const t = target.current;
      onTop(t !== undefined && t >= first + lo && t <= first + end ? t : first + lo);
    };
    const later = () => { if (!frame) frame = requestAnimationFrame(look); };
    later();
    scroller.addEventListener("scroll", later, { passive: true });
    return () => { scroller.removeEventListener("scroll", later); if (frame) cancelAnimationFrame(frame); };
  }, [onTop, first, items.length]);

  if (q.isLoading) return <Loading />;
  if (!items.length) return <>{empty || <Empty title="Nothing here yet">Add music folders on the admin page and scan them.</Empty>}</>;
  return (
    <div className="paged" ref={list}>
      {/* nothing shows here while earlier pages load: whatever it was would push the list down */}
      {q.hasPreviousPage && <div ref={top} className="paged-before" />}
      {children(items)}
      <div ref={sentinel} style={{ height: 1 }} />
    </div>
  );
}

// ---------------------------------------------------------------- jumping to a letter

interface Letter { letter: string; offset: number }      // where a run of names under a letter starts
const AZ = "ABCDEFGHIJKLMNOPQRSTUVWXYZ".split("");
const SIGNS = "#";       // digits and signs: they sort first
const OTHER = "…";       // Å, Ä, Ö and other scripts: they sort after Z

/** A list's first letters to jump to (sorted by name; another sort turns to it on a jump), and
 * the letter being looked at. The jump is kept in the address (?at=), so Back comes to it again. */
function useLetters(of: "albums" | "artists", params: Record<string, string | number | undefined>,
                    browse: ReturnType<typeof useBrowse>, alpha: string[]) {
  const [search, setSearch] = useSearchParams();
  const sorted = alpha.includes(browse.sort);
  const by = sorted ? browse.sort : alpha[0];
  const at = sorted ? Number(search.get("at")) || 0 : 0;
  const [jump, setJump] = useState<Jump>();
  const [top, setTop] = useState(at);
  const q = useQuery({ queryKey: ["letters", of, params, by], staleTime: 60_000,
                       queryFn: () => api.get<Letter[]>("/api/letters", { of, ...params, sort: by }) });
  const go = (offset: number) => {
    if (!sorted) browse.setSort(by);
    setSearch((p) => { const n = new URLSearchParams(p); if (offset) n.set("at", String(offset)); else n.delete("at"); return n; },
              { replace: true });
    setTop(offset);
    setJump((j) => ({ seq: (j?.seq ?? 0) + 1, at: offset }));
  };
  const letters = q.data || [];
  const active = sorted ? [...letters].reverse().find((l) => l.offset <= top)?.letter : undefined;
  const bar = <LetterBar letters={letters} active={active} onJump={(l) => go(l.offset)}
                         hint={sorted ? undefined : `Sorts by ${by === "artist" ? "artist" : "name"}`} />;
  return {
    at, jump, bar, onTop: sorted ? setTop : undefined,
    // another sort starts the list from its top again
    browse: { ...browse, setSort: (v: string) => {
      browse.setSort(v);
      setSearch((p) => { const n = new URLSearchParams(p); n.delete("at"); return n; }, { replace: true });
    } },
  };
}

function LetterBar({ letters, active, onJump, hint }: { letters: Letter[]; active?: string; onJump: (l: Letter) => void; hint?: string }) {
  const bar = useRef<HTMLElement>(null);
  // on a narrow screen the row scrolls sideways: the letter being looked at stays in it
  useEffect(() => {
    const row = bar.current;
    const on = row?.querySelector<HTMLElement>("button.on");
    if (!row || !on || row.scrollWidth <= row.clientWidth) return;
    const left = on.offsetLeft - row.clientWidth / 2 + on.offsetWidth / 2;
    row.scrollTo({ left, behavior: "smooth" });
  }, [active]);
  // where each letter jumps to: its first run ("#" has a short second one after Z: { | ~)
  const at = new Map<string, Letter>();
  for (const l of letters) if (!at.has(l.letter)) at.set(l.letter, l);
  const shown = [...(at.has(SIGNS) ? [SIGNS] : []), ...AZ, ...(at.has(OTHER) ? [OTHER] : [])];
  return (
    <nav className="letters" aria-label="Jump to a letter" ref={bar}>
      {shown.map((letter) => {
        const l = at.get(letter);
        return (
          <button key={letter} className={letter === active ? "on" : ""} disabled={!l} aria-current={letter === active || undefined}
                  data-tip={!l ? undefined : [letter === OTHER ? "Å, Ä, Ö and other scripts" : letter === SIGNS ? "Digits and signs" : "",
                                              hint].filter(Boolean).join(" · ") || undefined}
                  aria-label={letter === OTHER ? "Other letters: Å, Ä, Ö and other scripts" : letter === SIGNS ? "Digits and signs" : undefined}
                  onClick={() => l && onJump(l)}>
            {letter}
          </button>
        );
      })}
    </nav>
  );
}

// ---------------------------------------------------------------- browsing: Genre → Artist → Album

const VIEWS: Choice<LibraryView>[] = [
  { value: "genres", label: "Genre", icon: <Tags size={14} />, title: "Genres, then their artists, then albums" },
  { value: "artists", label: "Artist", icon: <Mic2 size={14} />, title: "Artists, then their albums" },
  { value: "albums", label: "Album", icon: <Disc3 size={14} />, title: "All albums" },
];
const enc = encodeURIComponent;

/** /library opens the view used last. */
export function LibraryHome() {
  const view = useUi((s) => s.libraryView);
  return <Navigate to={`/library/${view}`} replace />;
}

function Crumbs({ items }: { items: [string, string?][] }) {
  return (
    <nav className="crumbs" aria-label="You are here">
      {items.map(([label, to], i) => (
        <Fragment key={i}>
          {i > 0 && <ChevronRight size={13} />}
          {to ? <Link to={to}>{label}</Link> : <span>{label}</span>}
        </Fragment>
      ))}
    </nav>
  );
}

/** Whether the bars right after `edge` are stuck to the top of the frame (the edge scrolled past it). */
function useStuck() {
  const edge = useRef<HTMLDivElement>(null);
  const [on, setOn] = useState(false);
  useEffect(() => {
    const el = edge.current;
    const root = el?.closest(".frame-scroll");
    if (!el || !root) return;
    const io = new IntersectionObserver(([e]) => setOn(!e.isIntersecting && e.boundingClientRect.top < (e.rootBounds?.top ?? 0)),
                                        { root, threshold: 0 });
    io.observe(el);
    return () => io.disconnect();
  }, []);
  return { edge, on };
}

function BrowseShell({ view, title, kicker, crumbs, browse, sorts, actions, letters, children }: {
  view: LibraryView; title: string; kicker: (string | number | null | undefined | false)[]; crumbs?: [string, string?][];
  browse: ReturnType<typeof useBrowse>; sorts: [string, string][]; actions?: ReactNode; letters?: ReactNode; children: ReactNode;
}) {
  const nav = useNavigate();
  const setPref = useUi((s) => s.setPref);
  const stuck = useStuck();
  return (
    <div className="page wide">
      <Kicker parts={kicker} />
      <Display l1={title} small />
      <LibraryNav />
      {/* the view and its letters stay at the top of the frame as the list scrolls under them */}
      <div ref={stuck.edge} aria-hidden />
      <div className={`browse-sticky ${stuck.on ? "stuck" : ""}`}>
        <div className="toolbar browsebar">
          <div className="tool">
            <span className="seg-label">View</span>
            <Segmented label="View" value={view} options={VIEWS} onChange={(v) => { setPref("library_view", v); nav(`/library/${v}`); }} />
          </div>
          <SortMenu value={browse.sort} options={sorts} onChange={browse.setSort} />
          <div className="grow" />
          {actions}
          <DisplaySwitch value={browse.display} onChange={browse.setDisplay} />
        </div>
        {letters}
      </div>
      {crumbs && <Crumbs items={crumbs} />}
      {children}
    </div>
  );
}

export function LibraryGenres() {
  const b = useBrowse("library.genres", GENRE_SORTS, "albums", "genres");
  const q = useQuery({ queryKey: ["genres", b.sort], queryFn: () => api.get<Genre[]>("/api/genres", { sort: b.sort, limit: 500 }) });
  return (
    <BrowseShell view="genres" title="Library" kicker={["Library", q.data && `${q.data.length} genres`]} browse={b} sorts={GENRE_SORTS}
                 actions={<button className="btn" onClick={() => playRandom({ kind: "music" })}><Shuffle size={15} /> Shuffle all</button>}>
      {q.data ? (q.data.length ? <GenreItems items={q.data} display={b.display} linkTo={(g) => `/library/genres/${enc(g.name)}`} />
        : <Empty title="No genres yet">Genres come from the genre folders and tags of your music.</Empty>) : <Loading />}
    </BrowseShell>
  );
}

export function LibraryGenreArtists() {
  const { genre = "" } = useParams();
  const b = useBrowse("library.genre-artists", ARTIST_SORTS, "albums", "artists");
  const l = useLetters("artists", { genre }, b, ["name"]);
  const q = usePaged<Artist>(["artists", "genre", genre], "/api/artists", { genre, sort: b.sort }, 100, l.at);
  const total = q.data?.pages[0]?.total;
  return (
    <BrowseShell view="genres" title={genre} kicker={["Genre", total !== undefined && `${fmtNumber(total)} artists`]}
                 crumbs={[["Genres", "/library/genres"], [genre]]} browse={l.browse} sorts={ARTIST_SORTS} letters={l.bar}
                 actions={<button className="btn" onClick={() => playRandom({ genre })}><Shuffle size={15} /> Shuffle {genre}</button>}>
      <Infinite q={q} onTop={l.onTop} jump={l.jump}>
        {(items) => <ArtistItems items={items} display={b.display} linkTo={(a) => `/library/genres/${enc(genre)}/${a.id}`} />}
      </Infinite>
    </BrowseShell>
  );
}

export function LibraryArtists() {
  const b = useBrowse("library.artists", ARTIST_SORTS, "name", "artists");
  const l = useLetters("artists", {}, b, ["name"]);
  const q = usePaged<Artist>(["artists", "all"], "/api/artists", { sort: b.sort }, 100, l.at);
  const total = q.data?.pages[0]?.total;
  return (
    <BrowseShell view="artists" title="Library" kicker={["Library", total !== undefined && `${fmtNumber(total)} artists`]} browse={l.browse}
                 sorts={ARTIST_SORTS} letters={l.bar}
                 actions={<button className="btn" onClick={() => playRandom({ kind: "music" })}><Shuffle size={15} /> Shuffle all</button>}>
      <Infinite q={q} onTop={l.onTop} jump={l.jump}>
        {(items) => <ArtistItems items={items} display={b.display} linkTo={(a) => `/library/artists/${a.id}`} />}
      </Infinite>
    </BrowseShell>
  );
}

/** One artist's albums, reached from the Genre or the Artist view. */
export function LibraryArtistAlbums() {
  const { id = "", genre } = useParams();
  const b = useBrowse("library.artist-albums", ALBUM_SORTS, "year", "albums");
  const artist = useQuery({ queryKey: ["artist", Number(id)], queryFn: () => api.get<ArtistDetail>(`/api/artists/${id}`) });
  const q = usePaged<Album>(["albums", "artist", id], "/api/albums", { kind: "all", artist_id: id, sort: b.sort });
  const name = artist.data?.name || "…";
  const total = q.data?.pages[0]?.total;
  const crumbs: [string, string?][] = genre
    ? [["Genres", "/library/genres"], [genre, `/library/genres/${enc(genre)}`], [name]]
    : [["Artists", "/library/artists"], [name]];
  return (
    <BrowseShell view={genre ? "genres" : "artists"} title={name} crumbs={crumbs} browse={b} sorts={ALBUM_SORTS}
                 kicker={["Artist", artist.data?.genre, total !== undefined && `${fmtNumber(total)} albums`]}
                 actions={<>
                   <button className="btn" onClick={() => playRandom({ artist_id: Number(id), kind: "all" })}><Shuffle size={15} /> Shuffle</button>
                   <Link className="btn" to={`/artist/${id}`} data-tip="Top songs and more"><UserRound size={15} /> Artist page</Link>
                 </>}>
      <Infinite q={q}>{(items) => <AlbumItems items={items} display={b.display} />}</Infinite>
    </BrowseShell>
  );
}

export function LibraryAlbums() {
  const b = useBrowse("library.albums", ALBUM_SORTS, "added", "albums");
  const l = useLetters("albums", { kind: "music" }, b, ["name", "artist"]);
  const q = usePaged<Album>(["albums", "all"], "/api/albums", { kind: "music", sort: b.sort }, 60, l.at);
  const total = q.data?.pages[0]?.total;
  return (
    <BrowseShell view="albums" title="Library" kicker={["Library", total !== undefined && `${fmtNumber(total)} albums`]} browse={l.browse}
                 sorts={ALBUM_SORTS} letters={l.bar}
                 actions={<button className="btn" onClick={() => playRandom({ kind: "music" })}><Shuffle size={15} /> Shuffle all</button>}>
      <Infinite q={q} onTop={l.onTop} jump={l.jump}>{(items) => <AlbumItems items={items} display={b.display} />}</Infinite>
    </BrowseShell>
  );
}

export function Liked() {
  const q = useQuery({ queryKey: ["liked"], queryFn: () => api.get<Track[]>("/api/likes/tracks") });
  return (
    <div className="page wide">
      <Kicker parts={["Library", q.data && `${q.data.length} songs`]} />
      <Display l1="Liked" l2="songs" small />
      <LibraryNav />
      {q.data?.length ? (
        <>
          <div className="row-actions" style={{ marginBottom: 18 }}>
            <button className="btn accent" onClick={() => playTracks(q.data!, 0)}><Play size={15} fill="currentColor" /> Play</button>
            <button className="btn" onClick={() => playTracks(q.data!, 0, true)}><Shuffle size={15} /> Shuffle</button>
          </div>
          <TrackList tracks={q.data} showArt />
        </>
      ) : q.data ? <Empty title="No liked songs yet">Tap the heart on any song.</Empty> : <Loading />}
    </div>
  );
}

export function Playlists() {
  const q = useQuery({ queryKey: ["playlists"], queryFn: () => api.get<Playlist[]>("/api/playlists") });
  const files = useQuery({ queryKey: ["file-playlists"], queryFn: () => api.get<FilePlaylist[]>("/api/file-playlists") });
  // "+" in the library panel lands here with { create: true }
  const loc = useLocation();
  const [creating, setCreating] = useState(() => Boolean((loc.state as { create?: boolean } | null)?.create));
  const [name, setName] = useState("");
  const nav = useNavigate();
  const create = async () => {
    const p = await api.post<Playlist>("/api/playlists", { name: name.trim() || "New playlist" });
    queryClient.invalidateQueries({ queryKey: ["playlists"] });
    queryClient.invalidateQueries({ queryKey: ["sidebar"] });
    nav(`/playlist/${p.id}`);
  };
  return (
    <div className="page wide">
      <Kicker parts={["Library", q.data && `${q.data.length} playlists`]} />
      <Display l1="Playlists" small />
      <LibraryNav />
      <div className="toolbar"><button className="btn accent" onClick={() => setCreating(true)}><Plus size={15} /> New playlist</button></div>
      {q.data?.length ? <div className="grid">{q.data.map((p) => <PlaylistCard key={p.id} p={p} />)}</div>
        : q.data ? <Empty title="No playlists yet">Make one, then add songs from any track's menu.</Empty> : <Loading />}
      {files.data && files.data.length > 0 && (
        <Section title="From your music folders">
          <div className="grid">
            {files.data.map((f) => <MosaicCard key={f.id} to={`/playlist/file/${f.id}`} name={f.name} art={f.art} sub={`${f.tracks} songs`}
                                         admin={{ kind: "fileplaylist", id: f.id }} />)}
          </div>
        </Section>
      )}
      {creating && (
        <Modal onClose={() => setCreating(false)}>
          <div className="h2" style={{ marginBottom: 14 }}>New playlist</div>
          <input className="input" autoFocus placeholder="Name" value={name} onChange={(e) => setName(e.target.value)} onKeyDown={(e) => e.key === "Enter" && create()} />
          <div className="row-actions" style={{ marginTop: 16, justifyContent: "flex-end" }}>
            <button className="btn ghost" onClick={() => setCreating(false)}>Cancel</button>
            <button className="btn accent" onClick={create}>Create</button>
          </div>
        </Modal>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- detail pages

export function AlbumPage() {
  const { id } = useParams();
  const q = useQuery({ queryKey: ["album", Number(id)], queryFn: () => api.get<AlbumDetail>(`/api/albums/${id}`) });
  const pick = usePlaylistPicker((s) => s.open);
  const [liked, setLiked] = useState<boolean | null>(null);
  const [extra, setExtra] = useState<Track[]>([]);
  useEffect(() => { setLiked(null); setExtra([]); }, [id]);
  if (!q.data) return <div className="page"><Loading /></div>;
  const a = q.data;
  const isLiked = liked ?? a.liked;
  const formats = a.formats.map((f) => f.toUpperCase()).join(" / ");
  const tint = a.colors[0];
  return (
    <div style={tint ? { background: `radial-gradient(120% 480px at 30% 0, ${tint}30, transparent 75%)` } : undefined}>
    <div className="page">
      <div className="detail-head">
        <Art src={a.art} name={a.title} size={600} peer={a.peer} />
        <div style={{ minWidth: 0 }}>
          <Kicker parts={[a.kind === "vgm" ? "Game / collection" : "Album", a.genre, formats]} />
          <Display l1={a.title} small />
          <div className="detail-meta">
            {a.artist_id ? <Link to={`/artist/${a.artist_id}`}><b>{a.artist}</b></Link> : <b>{a.artist}</b>}
            {a.year > 0 && <span className="dotsep">{a.year}</span>}
            <span className="dotsep">{a.track_count} songs, {fmtLong(a.duration)}</span>
            {a.peer && <FromPeer peer={a.peer} />}
          </div>
          {a.artist_tags.length > 0 && <TagLinks tags={a.artist_tags.slice(0, 6)} />}
          <div className="row-actions">
            <button className="btn accent" onClick={() => playAlbum(a.id)}><Play size={15} fill="currentColor" /> Play</button>
            <button className="btn" data-tip="Play the album in random order" onClick={() => playAlbum(a.id, { shuffle: true })}><Shuffle size={15} /> Shuffle</button>
            <button className={`btn ${isLiked ? "accent" : ""}`} data-tip={isLiked ? "Saved in your library: click to remove it" : "Save the album to your library"}
                    onClick={async () => setLiked(await toggleLike("album", a.id, isLiked))}>
              <Heart size={15} fill={isLiked ? "currentColor" : "none"} /> {isLiked ? "Saved" : "Save"}
            </button>
            <button className="btn" onClick={() => pick(a.tracks.map((t) => t.id))}><ListPlus size={15} /> Add to playlist</button>
            <AdminCog kind="album" id={a.id} title={a.title} className="inline" peer={a.peer} />
          </div>
        </div>
      </div>
      <TrackList tracks={[...a.tracks, ...extra]} showAlbum={false} numbered="track" />
      {a.track_count > a.tracks.length + extra.length && (
        <div className="row-actions" style={{ marginTop: 14 }}>
          <span className="dim">Showing {fmtNumber(a.tracks.length + extra.length)} of {fmtNumber(a.track_count)} songs</span>
          <button className="btn small" onClick={async () => {
            const more = await api.get<AlbumDetail>(`/api/albums/${a.id}`, { offset: a.tracks.length + extra.length, limit: 1000 });
            setExtra([...extra, ...more.tracks]);
          }}>Show more</button>
        </div>
      )}
      {a.folder && <div className="faint mono" style={{ fontSize: 11, marginTop: 14, letterSpacing: ".08em" }} data-tip="Where the album's files are on the server">{a.folder}</div>}
      {a.more.length > 0 && (
        <Section kicker="More from" title={a.artist}>
          <div className="scroller">{a.more.map((m) => <AlbumCard key={m.id} a={m} />)}</div>
        </Section>
      )}
    </div>
    </div>
  );
}

export function ArtistPage() {
  const { id } = useParams();
  const q = useQuery({ queryKey: ["artist", Number(id)], queryFn: () => api.get<ArtistDetail>(`/api/artists/${id}`) });
  if (!q.data) return <div className="page"><Loading /></div>;
  const a = q.data;
  return (
    <div className="page">
      <div className="detail-head">
        <Art src={a.art} name={a.name} size={600} round />
        <div>
          <Kicker parts={["Artist", a.genre, `${a.albums.length} albums`]} />
          <Display l1={a.name} small />
          {a.tags.length > 0 && <TagLinks tags={a.tags} />}
          <div className="row-actions">
            <button className="btn accent" data-tip="Play the top songs" onClick={() => playTracks(a.top_tracks, 0)}><Play size={15} fill="currentColor" /> Play</button>
            <button className="btn" data-tip={`Shuffle every song by ${a.name}`} onClick={() => playRandom({ artist_id: a.id, kind: "all" })}><Shuffle size={15} /> Shuffle</button>
            <AdminCog kind="artist" id={a.id} title={a.name} className="inline" />
          </div>
        </div>
      </div>
      <Section kicker={a.top_tracks.length ? "Most played" : ""} title="Top songs">
        <TrackList tracks={a.top_tracks} showArt />
      </Section>
      <Section kicker="Discography" title="Albums">
        <div className="grid">{a.albums.map((x) => <AlbumCard key={x.id} a={x} />)}</div>
      </Section>
    </div>
  );
}

export function GenrePage() {
  const { name = "" } = useParams();
  const q = usePaged<Album>(["genre-albums", name], "/api/albums", { kind: "music", genre: name, sort: "artist" });
  const artists = useQuery({ queryKey: ["genre-artists", name], queryFn: () => api.get<Paged<Artist>>("/api/artists", { genre: name, sort: "albums", limit: 24 }) });
  return (
    <div className="page wide">
      <Kicker parts={["Genre", q.data && `${fmtNumber(q.data.pages[0].total)} albums`]} />
      <Display l1={name} small />
      <div className="row-actions" style={{ marginBottom: 10 }}>
        <button className="btn accent" onClick={() => playRandom({ genre: name })}><Shuffle size={15} /> Shuffle {name}</button>
      </div>
      {artists.data && artists.data.items.length > 0 && (
        <Section title="Artists"><div className="scroller">{artists.data.items.map((a) => <ArtistCard key={a.id} a={a} />)}</div></Section>
      )}
      <Section title="Albums"><Infinite q={q}>{(items) => <div className="grid">{items.map((a) => <AlbumCard key={a.id} a={a} />)}</div>}</Infinite></Section>
    </div>
  );
}

/** Genre tags as links to everything else that carries them. */
function TagLinks({ tags }: { tags: string[] }) {
  return (
    <div className="tags">
      {tags.map((t) => <Link className="tag" key={t} to={`/tag/${encodeURIComponent(t)}`} data-tip={`Everything tagged ${t}`}>{t}</Link>)}
    </div>
  );
}

/** Everything carrying a tag: its artists, some of its albums, and every song. */
export function TagPage() {
  const { name = "" } = useParams();
  const path = `/api/tags/${encodeURIComponent(name)}`;
  const info = useQuery({ queryKey: ["tag", name], queryFn: () => api.get<TagDetail>(path) });
  const songs = usePaged<Track>(["tag-tracks", name], `${path}/tracks`, {}, 100);
  const loaded = songs.data?.pages.flatMap((p) => p.items) || [];
  const d = info.data;
  return (
    <div className="page wide">
      <Kicker parts={["Tag", d && `${fmtNumber(d.tracks)} songs`, d && `${fmtNumber(d.albums)} albums`]} />
      <Display l1={name} small />
      <div className="row-actions" style={{ marginBottom: 10 }}>
        <button className="btn accent" disabled={!loaded.length} onClick={() => playTracks(loaded, 0)}><Play size={15} fill="currentColor" /> Play</button>
        <button className="btn" disabled={!loaded.length} onClick={() => playRandom({ tag: name, kind: "all" })}><Shuffle size={15} /> Shuffle</button>
      </div>
      {d && d.artists.length > 0 && (
        <Section title="Artists"><div className="scroller">{d.artists.map((a) => <ArtistCard key={a.id} a={a} />)}</div></Section>
      )}
      {d && d.album_list.length > 0 && (
        <Section title="Albums"><div className="scroller">{d.album_list.map((a) => <AlbumCard key={a.id} a={a} />)}</div></Section>
      )}
      <Section title="Songs">
        <Infinite q={songs} empty={<Empty title="No songs with this tag">Nothing in your library carries it right now.</Empty>}>
          {(items) => <TrackList tracks={items} showArt />}
        </Infinite>
      </Section>
    </div>
  );
}

/** A playlist file from the music folders: read-only, with the songs the scan could find. */
export function FilePlaylistPage() {
  const { id } = useParams();
  const q = useQuery({ queryKey: ["file-playlist", Number(id)], queryFn: () => api.get<FilePlaylistDetail>(`/api/file-playlists/${id}`) });
  if (!q.data) return <div className="page"><Loading /></div>;
  const p = q.data;
  const missing = p.entries - p.tracks.length;
  return (
    <div className="page">
      <Kicker parts={["Playlist file", `${p.tracks.length} songs`, missing > 0 && `${missing} not in the library`, p.peer && `From ${p.peer}`]} />
      <Display l1={p.name} small />
      <div className="row-actions" style={{ marginBottom: 18 }}>
        <button className="btn accent" disabled={!p.tracks.length} onClick={() => playTracks(p.tracks, 0)}><Play size={15} fill="currentColor" /> Play</button>
        <button className="btn" disabled={!p.tracks.length} onClick={() => playTracks(p.tracks, 0, true)}><Shuffle size={15} /> Shuffle</button>
        <AdminCog kind="fileplaylist" id={p.id} title={p.name} className="inline" peer={p.peer} />
      </div>
      <TrackList tracks={p.tracks} showArt />
      {p.path && <div className="faint mono" style={{ fontSize: 11, marginTop: 14, letterSpacing: ".08em" }}>{p.path}</div>}
    </div>
  );
}

export function PlaylistPage() {
  const { id } = useParams();
  const nav = useNavigate();
  const user = useUi((s) => s.user);
  const q = useQuery({ queryKey: ["playlist", Number(id)], queryFn: () => api.get<Playlist>(`/api/playlists/${id}`) });
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState("");
  if (!q.data) return <div className="page"><Loading /></div>;
  const p = q.data;
  const mine = p.owner_id === user?.id;
  const reload = () => {
    queryClient.invalidateQueries({ queryKey: ["playlist", p.id] });
    queryClient.invalidateQueries({ queryKey: ["playlists"] });
  };
  return (
    <div className="page">
      <div className="detail-head">
        <div className="art" style={{ display: "grid", gridTemplateColumns: p.art.length >= 4 ? "1fr 1fr" : "1fr" }}>
          {p.art.length >= 4 ? p.art.slice(0, 4).map((u) => <img key={u} src={sized(u, 300)} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} />)
            : <Art src={p.art[0]} name={p.name} size={600} />}
        </div>
        <div>
          <Kicker parts={["Playlist", p.public ? "Shared" : "Private", `${p.track_count} songs`, fmtLong(p.duration)]} />
          <Display l1={p.name} small />
          {p.description && <p className="lede">{p.description}</p>}
          <div className="row-actions">
            <button className="btn accent" disabled={!p.tracks?.length} onClick={() => playTracks(p.tracks!, 0)}><Play size={15} fill="currentColor" /> Play</button>
            <button className="btn" disabled={!p.tracks?.length} onClick={() => playTracks(p.tracks!, 0, true)}><Shuffle size={15} /> Shuffle</button>
            {mine && <button className="btn" onClick={() => { setName(p.name); setEditing(true); }}>Rename</button>}
            <AdminCog kind="playlist" id={p.id} title={p.name} className="inline" />
            {mine && <button className="btn danger" onClick={async () => {
              if (!confirm(`Delete the playlist "${p.name}"? The songs stay in your library.`)) return;
              await api.del(`/api/playlists/${p.id}`);
              queryClient.invalidateQueries({ queryKey: ["playlists"] });
              nav("/library/playlists");
            }}><Trash2 size={15} /> Delete</button>}
          </div>
        </div>
      </div>
      {p.tracks?.length ? <TrackList tracks={p.tracks} showArt
        onRemove={mine ? async (t) => { await api.del(`/api/playlists/${p.id}/items/${t.item_id}`); reload(); } : undefined} />
        : <Empty title="This playlist is empty">Add songs with "Add to playlist" from any song's menu.</Empty>}
      {editing && (
        <Modal onClose={() => setEditing(false)}>
          <div className="h2" style={{ marginBottom: 14 }}>Rename playlist</div>
          <input className="input" autoFocus value={name} onChange={(e) => setName(e.target.value)} />
          <div className="row-actions" style={{ marginTop: 16, justifyContent: "flex-end" }}>
            <button className="btn accent" onClick={async () => {
              await api.patch(`/api/playlists/${p.id}`, { name, description: p.description, public: p.public });
              setEditing(false);
              reload();
            }}>Save</button>
          </div>
        </Modal>
      )}
    </div>
  );
}

/** A search result that goes into recent searches when it's opened or played (not its admin menu). */
function Remember({ kind, id, children }: { kind: RecentKind; id: number; children: ReactNode }) {
  return (
    <div className="contents" onClickCapture={(e) => { if (!(e.target as Element).closest(".admin-cog, .menu")) rememberSearch(kind, id); }}>
      {children}
    </div>
  );
}

export function SearchPage() {
  const [params, setParams] = useSearchParams();
  const [text, setText] = useState(params.get("q") || "");
  const qs = params.get("q") || "";
  useEffect(() => {
    const t = window.setTimeout(() => setParams(text ? { q: text } : {}, { replace: true }), 250);
    return () => window.clearTimeout(t);
  }, [text, setParams]);
  const q = useQuery({
    queryKey: ["search", qs], enabled: qs.length > 1,
    queryFn: () => api.get<SearchResults>("/api/search", { q: qs, limit: 24 }),
  });
  const r = q.data;
  // Spotify-style "Browse all" while nothing is typed
  const genres = useQuery({ queryKey: ["genres", "albums"], queryFn: () => api.get<Genre[]>("/api/genres", { sort: "albums", limit: 500 }), enabled: !qs });
  const [desktop] = useState(() => window.matchMedia("(min-width: 861px)").matches);
  return (
    <div className="page wide">
      <Kicker parts={["Search the library"]} />
      <input className="input searchbox" autoFocus={desktop} placeholder="Artists, songs, albums, audiobooks…" value={text}
             onChange={(e) => setText(e.target.value)} />
      {!qs && <RecentSearches />}
      {!qs && genres.data && genres.data.length > 0 && (
        <Section title="Browse all"><GenreItems items={genres.data} display="gallery" linkTo={(g) => `/library/genres/${enc(g.name)}`} /></Section>
      )}
      {r && !r.artists.length && !r.albums.length && !r.tracks.length && !r.books.length && <Empty title={`Nothing found for "${qs}"`} />}
      {r && r.artists.length > 0 && (
        <Section title="Artists">
          <div className="scroller">{r.artists.map((a) => <Remember key={a.id} kind="artist" id={a.id}><ArtistCard a={a} /></Remember>)}</div>
        </Section>
      )}
      {r && r.tracks.length > 0 && (
        <Section title="Songs"><TrackList tracks={r.tracks.slice(0, 10)} showArt onPlay={(t) => rememberSearch("track", t.id)} /></Section>
      )}
      {r && r.albums.length > 0 && (
        <Section title="Albums">
          <div className="grid">{r.albums.map((a) => <Remember key={a.id} kind="album" id={a.id}><AlbumCard a={a} /></Remember>)}</div>
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
    </div>
  );
}
