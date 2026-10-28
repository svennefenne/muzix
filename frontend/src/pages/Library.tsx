import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { ChevronRight, Disc3, Heart, ListPlus, Mic2, Play, Plus, Shuffle, Tags, Trash2, UserRound } from "lucide-react";
import { Fragment, useCallback, useEffect, useState, type ReactNode } from "react";
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
import { Art, Display, Empty, Kicker, Loading, Modal, Section, useInView } from "../components/ui";
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

function usePaged<T>(key: unknown[], path: string, params: Record<string, string | number | boolean | undefined>, size = 60) {
  return useInfiniteQuery({
    queryKey: [...key, params],
    queryFn: ({ pageParam }) => api.get<Paged<T>>(path, { ...params, limit: size, offset: pageParam }),
    initialPageParam: 0,
    getNextPageParam: (last, all) => {
      const n = all.reduce((s, p) => s + p.items.length, 0);
      return n < last.total ? n : undefined;
    },
  });
}

/** Loads more pages as the end of the list scrolls into view. */
function Infinite<T>({ q, children, empty }: { q: ReturnType<typeof usePaged<T>>; children: (items: T[]) => ReactNode; empty?: ReactNode }) {
  const more = useCallback(() => { if (q.hasNextPage && !q.isFetchingNextPage) q.fetchNextPage(); }, [q]);
  const sentinel = useInView(more, !!q.hasNextPage);
  const items = q.data?.pages.flatMap((p) => p.items) || [];
  if (q.isLoading) return <Loading />;
  if (!items.length) return <>{empty || <Empty title="Nothing here yet">Add music folders on the admin page and scan them.</Empty>}</>;
  return (
    <>
      {children(items)}
      <div ref={sentinel} style={{ height: 1 }} />
    </>
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

function BrowseShell({ view, title, kicker, crumbs, browse, sorts, actions, children }: {
  view: LibraryView; title: string; kicker: (string | number | null | undefined | false)[]; crumbs?: [string, string?][];
  browse: ReturnType<typeof useBrowse>; sorts: [string, string][]; actions?: ReactNode; children: ReactNode;
}) {
  const nav = useNavigate();
  const setPref = useUi((s) => s.setPref);
  return (
    <div className="page wide">
      <Kicker parts={kicker} />
      <Display l1={title} small />
      <LibraryNav />
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
  const q = usePaged<Artist>(["artists", "genre", genre], "/api/artists", { genre, sort: b.sort }, 100);
  const total = q.data?.pages[0]?.total;
  return (
    <BrowseShell view="genres" title={genre} kicker={["Genre", total !== undefined && `${fmtNumber(total)} artists`]}
                 crumbs={[["Genres", "/library/genres"], [genre]]} browse={b} sorts={ARTIST_SORTS}
                 actions={<button className="btn" onClick={() => playRandom({ genre })}><Shuffle size={15} /> Shuffle {genre}</button>}>
      <Infinite q={q}>{(items) => <ArtistItems items={items} display={b.display} linkTo={(a) => `/library/genres/${enc(genre)}/${a.id}`} />}</Infinite>
    </BrowseShell>
  );
}

export function LibraryArtists() {
  const b = useBrowse("library.artists", ARTIST_SORTS, "name", "artists");
  const q = usePaged<Artist>(["artists", "all"], "/api/artists", { sort: b.sort }, 100);
  const total = q.data?.pages[0]?.total;
  return (
    <BrowseShell view="artists" title="Library" kicker={["Library", total !== undefined && `${fmtNumber(total)} artists`]} browse={b} sorts={ARTIST_SORTS}
                 actions={<button className="btn" onClick={() => playRandom({ kind: "music" })}><Shuffle size={15} /> Shuffle all</button>}>
      <Infinite q={q}>{(items) => <ArtistItems items={items} display={b.display} linkTo={(a) => `/library/artists/${a.id}`} />}</Infinite>
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
  const q = usePaged<Album>(["albums", "all"], "/api/albums", { kind: "music", sort: b.sort });
  const total = q.data?.pages[0]?.total;
  return (
    <BrowseShell view="albums" title="Library" kicker={["Library", total !== undefined && `${fmtNumber(total)} albums`]} browse={b} sorts={ALBUM_SORTS}
                 actions={<button className="btn" onClick={() => playRandom({ kind: "music" })}><Shuffle size={15} /> Shuffle all</button>}>
      <Infinite q={q}>{(items) => <AlbumItems items={items} display={b.display} />}</Infinite>
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
        <Art src={a.art} name={a.title} size={600} />
        <div style={{ minWidth: 0 }}>
          <Kicker parts={[a.kind === "vgm" ? "Game / collection" : "Album", a.genre, formats]} />
          <Display l1={a.title} small />
          <div className="detail-meta">
            {a.artist_id ? <Link to={`/artist/${a.artist_id}`}><b>{a.artist}</b></Link> : <b>{a.artist}</b>}
            {a.year > 0 && <span className="dotsep">{a.year}</span>}
            <span className="dotsep">{a.track_count} songs, {fmtLong(a.duration)}</span>
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
            <AdminCog kind="album" id={a.id} title={a.title} className="inline" />
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
      <div className="faint mono" style={{ fontSize: 11, marginTop: 14, letterSpacing: ".08em" }} data-tip="Where the album's files are on the server">{a.folder}</div>
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
      <Kicker parts={["Playlist file", `${p.tracks.length} songs`, missing > 0 && `${missing} not in the library`]} />
      <Display l1={p.name} small />
      <div className="row-actions" style={{ marginBottom: 18 }}>
        <button className="btn accent" disabled={!p.tracks.length} onClick={() => playTracks(p.tracks, 0)}><Play size={15} fill="currentColor" /> Play</button>
        <button className="btn" disabled={!p.tracks.length} onClick={() => playTracks(p.tracks, 0, true)}><Shuffle size={15} /> Shuffle</button>
        <AdminCog kind="fileplaylist" id={p.id} title={p.name} className="inline" />
      </div>
      <TrackList tracks={p.tracks} showArt />
      <div className="faint mono" style={{ fontSize: 11, marginTop: 14, letterSpacing: ".08em" }}>{p.path}</div>
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
              <Art src={b.art} name={b.title} />
              <div className="card-title ellipsis">{b.title}</div>
              <div className="card-sub ellipsis">{b.author || "Unknown author"}</div>
            </Link>
          ))}</div>
        </Section>
      )}
    </div>
  );
}
