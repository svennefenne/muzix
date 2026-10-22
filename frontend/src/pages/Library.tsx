import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { Heart, ListPlus, Play, Plus, Shuffle, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Link, NavLink, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api, fmtLong, fmtNumber } from "../api";
import { playAlbum, playRandom, playTracks, queryClient, toggleLike, usePlaylistPicker } from "../actions";
import { AlbumCard, ArtistCard, GenreCard, PlaylistCard } from "../components/Cards";
import { TrackList } from "../components/TrackList";
import { Art, Display, Empty, Kicker, Loading, Modal, Section, useInView } from "../components/ui";
import { useUi } from "../store/ui";
import type { Album, AlbumDetail, Artist, ArtistDetail, Genre, Paged, Playlist, Track } from "../types";

function LibraryNav() {
  const items = [["/library", "Albums"], ["/library/artists", "Artists"], ["/library/genres", "Genres"],
    ["/library/liked", "Liked songs"], ["/library/playlists", "Playlists"]];
  return (
    <nav className="subnav">
      {items.map(([to, label]) => <NavLink key={to} to={to} end className={({ isActive }) => (isActive ? "active" : "")}>{label}</NavLink>)}
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

function InfiniteGrid<T>({ q, render, small }: { q: ReturnType<typeof usePaged<T>>; render: (x: T) => React.ReactNode; small?: boolean }) {
  const more = useCallback(() => { if (q.hasNextPage && !q.isFetchingNextPage) q.fetchNextPage(); }, [q]);
  const sentinel = useInView(more, !!q.hasNextPage);
  const items = q.data?.pages.flatMap((p) => p.items) || [];
  if (q.isLoading) return <Loading />;
  if (!items.length) return <Empty title="Nothing here yet">Add music folders on the admin page and scan them.</Empty>;
  return (
    <>
      <div className={`grid ${small ? "small" : ""}`}>{items.map(render)}</div>
      <div ref={sentinel} style={{ height: 1 }} />
    </>
  );
}

export function Albums() {
  const [params, setParams] = useSearchParams();
  const sort = params.get("sort") || "added";
  const q = usePaged<Album>(["albums"], "/api/albums", { kind: "music", sort });
  const total = q.data?.pages[0]?.total;
  return (
    <div className="page wide">
      <Kicker parts={["Library", total !== undefined && `${fmtNumber(total)} albums`]} />
      <Display l1="Library" small />
      <LibraryNav />
      <div className="toolbar">
        <span className="dim">Sort by</span>
        <select className="select" style={{ width: 170 }} value={sort} onChange={(e) => setParams({ sort: e.target.value })}>
          <option value="added">Recently added</option>
          <option value="name">Title</option>
          <option value="artist">Artist</option>
          <option value="year">Year</option>
        </select>
        <div className="grow" />
        <button className="btn" onClick={() => playRandom({ kind: "music" })}><Shuffle size={15} /> Shuffle all</button>
      </div>
      <InfiniteGrid q={q} render={(a) => <AlbumCard key={a.id} a={a} />} />
    </div>
  );
}

export function Artists() {
  const [sort, setSort] = useState("name");
  const q = usePaged<Artist>(["artists"], "/api/artists", { sort }, 100);
  return (
    <div className="page wide">
      <Kicker parts={["Library", q.data && `${fmtNumber(q.data.pages[0].total)} artists`]} />
      <Display l1="Artists" small />
      <LibraryNav />
      <div className="toolbar">
        <span className="dim">Sort by</span>
        <select className="select" style={{ width: 170 }} value={sort} onChange={(e) => setSort(e.target.value)}>
          <option value="name">Name</option>
          <option value="albums">Most albums</option>
        </select>
      </div>
      <InfiniteGrid q={q} small render={(a) => <ArtistCard key={a.id} a={a} />} />
    </div>
  );
}

export function Genres() {
  const q = useQuery({ queryKey: ["genres"], queryFn: () => api.get<Genre[]>("/api/genres") });
  return (
    <div className="page wide">
      <Kicker parts={["Library", q.data && `${q.data.length} genres`]} />
      <Display l1="Genres" small />
      <LibraryNav />
      {q.data ? <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(230px, 1fr))" }}>
        {q.data.map((g) => <GenreCard key={g.name} g={g} />)}
      </div> : <Loading />}
    </div>
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
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const nav = useNavigate();
  const create = async () => {
    const p = await api.post<Playlist>("/api/playlists", { name: name.trim() || "New playlist" });
    queryClient.invalidateQueries({ queryKey: ["playlists"] });
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
          {a.artist_tags.length > 0 && <div className="tags">{a.artist_tags.slice(0, 6).map((t) => <span className="tag" key={t}>{t}</span>)}</div>}
          <div className="row-actions">
            <button className="btn accent" onClick={() => playAlbum(a.id)}><Play size={15} fill="currentColor" /> Play</button>
            <button className="btn" onClick={() => playAlbum(a.id, { shuffle: true })}><Shuffle size={15} /> Shuffle</button>
            <button className={`btn ${isLiked ? "accent" : ""}`} onClick={async () => setLiked(await toggleLike("album", a.id, isLiked))}>
              <Heart size={15} fill={isLiked ? "currentColor" : "none"} /> {isLiked ? "Saved" : "Save"}
            </button>
            <button className="btn" onClick={() => pick(a.tracks.map((t) => t.id))}><ListPlus size={15} /> Add to playlist</button>
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
      <div className="faint mono" style={{ fontSize: 11, marginTop: 14, letterSpacing: ".08em" }}>{a.folder}</div>
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
          {a.tags.length > 0 && <div className="tags">{a.tags.map((t) => <span className="tag" key={t}>{t}</span>)}</div>}
          <div className="row-actions">
            <button className="btn accent" onClick={() => playTracks(a.top_tracks, 0)}><Play size={15} fill="currentColor" /> Play</button>
            <button className="btn" onClick={() => playRandom({ artist_id: a.id, kind: "all" })}><Shuffle size={15} /> Shuffle</button>
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
      <Section title="Albums"><InfiniteGrid q={q} render={(a) => <AlbumCard key={a.id} a={a} />} /></Section>
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
          {p.art.length >= 4 ? p.art.slice(0, 4).map((u) => <img key={u} src={`${u}?s=300`} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} />)
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
    queryFn: () => api.get<{ artists: Artist[]; albums: Album[]; tracks: Track[] }>("/api/search", { q: qs, limit: 24 }),
  });
  const r = q.data;
  return (
    <div className="page wide">
      <Kicker parts={["Search the library"]} />
      <input className="input" autoFocus placeholder="Artists, albums, songs, chiptunes…" value={text}
             onChange={(e) => setText(e.target.value)} style={{ height: 54, fontSize: 20, margin: "12px 0 8px" }} />
      {r && !r.artists.length && !r.albums.length && !r.tracks.length && <Empty title={`Nothing found for "${qs}"`} />}
      {r && r.tracks.length > 0 && <Section title="Songs"><TrackList tracks={r.tracks.slice(0, 10)} showArt /></Section>}
      {r && r.artists.length > 0 && <Section title="Artists"><div className="scroller">{r.artists.map((a) => <ArtistCard key={a.id} a={a} />)}</div></Section>}
      {r && r.albums.length > 0 && <Section title="Albums"><div className="grid">{r.albums.map((a) => <AlbumCard key={a.id} a={a} />)}</div></Section>}
    </div>
  );
}
