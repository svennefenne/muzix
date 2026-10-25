import { useQuery } from "@tanstack/react-query";
import { ExternalLink, Play, Shuffle } from "lucide-react";
import { useState } from "react";
import { Link, NavLink, Route, Routes, useParams, useSearchParams } from "react-router-dom";
import { api, fmtTime } from "../api";
import { Art, Display, Empty, Kicker, Loading, Section } from "../components/ui";
import { rowTap } from "../components/TrackList";
import { engine } from "../player/engine";
import { sp } from "../player/spotify";
import type { PlayItem } from "../store/player";
import { useUi } from "../store/ui";

interface SpStatus { configured: boolean; linked: boolean; display_name: string; product: string; redirect_uri: string }
interface SpImage { url: string }
interface SpArtist { id: string; name: string }
interface SpAlbum { id: string; name: string; images: SpImage[]; artists: SpArtist[]; release_date?: string; uri: string; tracks?: { items: SpTrack[] } }
interface SpTrack { id: string; name: string; uri: string; duration_ms: number; artists: SpArtist[]; album?: SpAlbum; is_playable?: boolean }
interface SpPlaylist { id: string; name: string; images: SpImage[] | null; owner: { display_name: string }; tracks?: { total: number }; items?: { total: number }; description: string }

const img = (imgs?: SpImage[] | null) => imgs?.[0]?.url || null;

/** Spotify tracks → queue items. Genres for the skins are looked up when a track plays. */
function toItems(tracks: SpTrack[], album?: SpAlbum): PlayItem[] {
  return tracks.map((t) => {
    const al = t.album || album;
    return {
      key: `spotify:${t.id}`, kind: "spotify", id: t.uri, title: t.name, artist: t.artists.map((a) => a.name).join(", "),
      album: al?.name, art: img(al?.images), duration: t.duration_ms / 1000, src: "", spotifyUri: t.uri,
      spotifyArtist: t.artists[0]?.name, tags: [],
    } as PlayItem;
  });
}

async function playSp(tracks: SpTrack[], index = 0, album?: SpAlbum, shuffle = false) {
  let list = tracks.filter((t) => t && t.uri && t.is_playable !== false);
  if (shuffle) list = [...list].sort(() => Math.random() - 0.5);
  engine.play(toItems(list, album), shuffle ? 0 : Math.max(0, list.indexOf(tracks[index])));
}

function SpTrackList({ tracks, album }: { tracks: SpTrack[]; album?: SpAlbum }) {
  return (
    <div className="tracks">
      {tracks.filter(Boolean).map((t, i) => (
        <div key={`${t.id}-${i}`} className="trow" onDoubleClick={() => playSp(tracks, i, album)} onClick={rowTap(() => playSp(tracks, i, album))}>
          <div className="t-num"><span className="n">{i + 1}</span>
            <button className="p" aria-label={`Play ${t.name}`} onClick={() => playSp(tracks, i, album)}><Play size={15} fill="currentColor" /></button></div>
          <div className="t-main">
            <Art src={img((t.album || album)?.images)} name={t.name} size={64} />
            <div style={{ minWidth: 0 }}><div className="t-title ellipsis">{t.name}</div><div className="t-artist ellipsis">{t.artists.map((a) => a.name).join(", ")}</div></div>
          </div>
          <div className="t-album ellipsis">{(t.album || album)?.name}</div>
          <div className="t-dur">{fmtTime(t.duration_ms / 1000)}</div>
          <div />
        </div>
      ))}
    </div>
  );
}

function Grid({ items }: { items: { id: string; to: string; title: string; sub: string; art: string | null }[] }) {
  return (
    <div className="grid">
      {items.map((x) => (
        <Link key={x.id} to={x.to} className="card">
          <Art src={x.art} name={x.title} />
          <div className="card-title ellipsis">{x.title}</div>
          <div className="card-sub ellipsis">{x.sub}</div>
        </Link>
      ))}
    </div>
  );
}

function Playlists() {
  const q = useQuery({ queryKey: ["sp-playlists"], queryFn: () => sp<{ items: SpPlaylist[] }>("me/playlists?limit=50") });
  if (!q.data) return <Loading />;
  return <Grid items={q.data.items.filter(Boolean).map((p) => ({ id: p.id, to: `/spotify/playlist/${p.id}`, title: p.name,
    sub: `${(p.tracks || p.items)?.total ?? ""} songs · ${p.owner.display_name}`, art: img(p.images) }))} />;
}

function Albums() {
  const q = useQuery({ queryKey: ["sp-albums"], queryFn: () => sp<{ items: { album: SpAlbum }[] }>("me/albums?limit=50") });
  if (!q.data) return <Loading />;
  return <Grid items={q.data.items.map(({ album: a }) => ({ id: a.id, to: `/spotify/album/${a.id}`, title: a.name,
    sub: a.artists.map((x) => x.name).join(", "), art: img(a.images) }))} />;
}

function LikedSongs() {
  const q = useQuery({ queryKey: ["sp-liked"], queryFn: () => sp<{ items: { track: SpTrack }[] }>("me/tracks?limit=50") });
  if (!q.data) return <Loading />;
  const tracks = q.data.items.map((i) => i.track);
  return (
    <>
      <div className="row-actions" style={{ marginBottom: 14 }}>
        <button className="btn accent" onClick={() => playSp(tracks)}><Play size={15} fill="currentColor" /> Play</button>
        <button className="btn" onClick={() => playSp(tracks, 0, undefined, true)}><Shuffle size={15} /> Shuffle</button>
      </div>
      <SpTrackList tracks={tracks} />
    </>
  );
}

function Recent() {
  const q = useQuery({ queryKey: ["sp-recent"], queryFn: () => sp<{ items: { track: SpTrack }[] }>("me/player/recently-played?limit=50") });
  if (!q.data) return <Loading />;
  return <SpTrackList tracks={q.data.items.map((i) => i.track)} />;
}

function Search() {
  const [params, setParams] = useSearchParams();
  const term = params.get("q") || "";
  const [text, setText] = useState(term);
  const q = useQuery({ queryKey: ["sp-search", term], enabled: !!term,
    queryFn: () => sp<{ tracks: { items: SpTrack[] }; albums: { items: SpAlbum[] }; playlists: { items: SpPlaylist[] } }>(`search?type=track,album,playlist&limit=10&q=${encodeURIComponent(term)}`) });
  return (
    <>
      <input className="input" placeholder="Search Spotify" value={text} onChange={(e) => setText(e.target.value)}
             onKeyDown={(e) => e.key === "Enter" && setParams({ q: text })} style={{ maxWidth: 420, marginBottom: 10 }} />
      {q.data && (
        <>
          <Section title="Songs"><SpTrackList tracks={q.data.tracks.items.slice(0, 10)} /></Section>
          <Section title="Albums"><Grid items={q.data.albums.items.filter(Boolean).map((a) => ({ id: a.id, to: `/spotify/album/${a.id}`, title: a.name, sub: a.artists.map((x) => x.name).join(", "), art: img(a.images) }))} /></Section>
          <Section title="Playlists"><Grid items={q.data.playlists.items.filter(Boolean).map((p) => ({ id: p.id, to: `/spotify/playlist/${p.id}`, title: p.name, sub: p.owner.display_name, art: img(p.images) }))} /></Section>
        </>
      )}
    </>
  );
}

function PlaylistView() {
  const { id } = useParams();
  const meta = useQuery({ queryKey: ["sp-pl", id], queryFn: () => sp<SpPlaylist>(`playlists/${id}?fields=name,description,images,owner(display_name)`) });
  const items = useQuery({ queryKey: ["sp-pl-tracks", id], queryFn: async () => {
    // newer apps read /items, older ones /tracks
    try {
      return await sp<{ items: { track?: SpTrack; item?: SpTrack }[] }>(`playlists/${id}/items?limit=100`);
    } catch {
      return sp<{ items: { track?: SpTrack; item?: SpTrack }[] }>(`playlists/${id}/tracks?limit=100`);
    }
  } });
  if (!meta.data || !items.data) return <Loading />;
  const tracks = items.data.items.map((i) => i.track || i.item).filter((t): t is SpTrack => !!t && !!t.uri);
  return (
    <>
      <div className="detail-head">
        <Art src={img(meta.data.images)} name={meta.data.name} size={600} />
        <div>
          <Kicker parts={["Spotify playlist", meta.data.owner.display_name, `${tracks.length} songs`]} />
          <Display l1={meta.data.name} small />
          <div className="row-actions">
            <button className="btn accent" onClick={() => playSp(tracks)}><Play size={15} fill="currentColor" /> Play</button>
            <button className="btn" onClick={() => playSp(tracks, 0, undefined, true)}><Shuffle size={15} /> Shuffle</button>
          </div>
        </div>
      </div>
      <SpTrackList tracks={tracks} />
    </>
  );
}

function AlbumView() {
  const { id } = useParams();
  const q = useQuery({ queryKey: ["sp-album", id], queryFn: () => sp<SpAlbum>(`albums/${id}`) });
  if (!q.data) return <Loading />;
  const a = q.data;
  const tracks = a.tracks?.items || [];
  return (
    <>
      <div className="detail-head">
        <Art src={img(a.images)} name={a.name} size={600} />
        <div>
          <Kicker parts={["Spotify album", a.release_date?.slice(0, 4), `${tracks.length} songs`]} />
          <Display l1={a.name} small />
          <div className="detail-meta"><b>{a.artists.map((x) => x.name).join(", ")}</b></div>
          <div className="row-actions"><button className="btn accent" onClick={() => playSp(tracks, 0, a)}><Play size={15} fill="currentColor" /> Play</button></div>
        </div>
      </div>
      <SpTrackList tracks={tracks} album={a} />
    </>
  );
}

export default function Spotify() {
  const user = useUi((s) => s.user);
  const [params] = useSearchParams();
  const st = useQuery({ queryKey: ["sp-status"], queryFn: () => api.get<SpStatus>("/api/spotify/status") });
  if (!st.data) return <div className="page"><Loading /></div>;
  const s = st.data;
  const error = params.get("error");
  if (!s.configured || !s.linked) {
    return (
      <div className="page">
        <Kicker parts={["Spotify", s.configured ? "Ready to link" : "Not set up"]} />
        <Display l1="Spotify" l2="in Muzix" />
        <p className="lede">Your Spotify playlists, saved albums and liked songs, played right here (Spotify Premium) and dressed up by the genre skins.</p>
        {error && <p className="error-text">Spotify said: {error}</p>}
        {!s.configured ? (
          <div className="panel" style={{ maxWidth: 720 }}>
            <div className="h3" style={{ marginBottom: 10 }}>One-time setup{user?.is_admin ? "" : " (ask your admin)"}</div>
            <ol className="dim" style={{ lineHeight: 1.8, paddingLeft: 18 }}>
              <li>Open <a className="accent" href="https://developer.spotify.com/dashboard" target="_blank" rel="noreferrer">developer.spotify.com/dashboard <ExternalLink size={12} /></a> and create an app (Web API + Web Playback SDK).</li>
              <li>Add this Redirect URI: <code className="mono" style={{ color: "var(--primary)" }}>{s.redirect_uri}</code><br />
                <span className="faint">Spotify only accepts HTTPS addresses, so use your reverse proxy's address. Set it as "Public URL" on the admin page.</span></li>
              <li>Copy the app's Client ID into Admin → Settings → Spotify.</li>
            </ol>
            {user?.is_admin && <Link className="btn accent" to="/admin/settings#Spotify">Open admin settings</Link>}
          </div>
        ) : <a className="btn primary" href="/api/spotify/login">Connect Spotify</a>}
      </div>
    );
  }
  const tabs = [["", "Playlists"], ["albums", "Albums"], ["liked", "Liked songs"], ["recent", "Recently played"], ["search", "Search"]];
  return (
    <div className="page wide">
      <Kicker parts={["Spotify", s.display_name, s.product === "premium" ? "Premium" : "Free: browse only"]} />
      <Display l1="Spotify" small />
      <nav className="subnav">
        {tabs.map(([to, label]) => <NavLink key={to} to={`/spotify${to ? "/" + to : ""}`} end className={({ isActive }) => (isActive ? "active" : "")}>{label}</NavLink>)}
        <button onClick={async () => { await api.del("/api/spotify/link"); st.refetch(); }}>Unlink</button>
      </nav>
      <Routes>
        <Route index element={<Playlists />} />
        <Route path="albums" element={<Albums />} />
        <Route path="liked" element={<LikedSongs />} />
        <Route path="recent" element={<Recent />} />
        <Route path="search" element={<Search />} />
        <Route path="playlist/:id" element={<PlaylistView />} />
        <Route path="album/:id" element={<AlbumView />} />
        <Route path="*" element={<Empty title="Not found" />} />
      </Routes>
    </div>
  );
}
