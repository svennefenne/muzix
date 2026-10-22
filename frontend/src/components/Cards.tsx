import { Play } from "lucide-react";
import { Link } from "react-router-dom";
import { playAlbum, playRandom } from "../actions";
import type { Album, Artist, Genre, Playlist } from "../types";
import { Art } from "./ui";

export function AlbumCard({ a }: { a: Album }) {
  return (
    <Link to={`/album/${a.id}`} className="card">
      <Art src={a.art} name={a.title} />
      <button className="play-fab" aria-label={`Play ${a.title}`}
              onClick={(e) => { e.preventDefault(); e.stopPropagation(); playAlbum(a.id); }}>
        <Play size={20} fill="currentColor" />
      </button>
      <div className="card-title ellipsis">{a.title}</div>
      <div className="card-sub ellipsis">{[a.year || null, a.artist].filter(Boolean).join(" · ")}</div>
    </Link>
  );
}

export function ArtistCard({ a, to }: { a: Artist; to?: string }) {
  return (
    <Link to={to || `/artist/${a.id}`} className="card">
      <Art src={a.art} name={a.name} round />
      <button className="play-fab" aria-label={`Play ${a.name}`}
              onClick={(e) => { e.preventDefault(); e.stopPropagation(); playRandom({ artist_id: a.id, kind: "all" }); }}>
        <Play size={20} fill="currentColor" />
      </button>
      <div className="card-title ellipsis" style={{ textAlign: "center" }}>{a.name}</div>
      <div className="card-sub ellipsis" style={{ textAlign: "center" }}>
        {a.album_count != null ? `${a.album_count} album${a.album_count === 1 ? "" : "s"}` : a.genre}
      </div>
    </Link>
  );
}

export function PlaylistCard({ p }: { p: Playlist }) {
  return (
    <Link to={`/playlist/${p.id}`} className="card">
      <div className="art" style={{ display: "grid", gridTemplateColumns: p.art.length >= 4 ? "1fr 1fr" : "1fr" }}>
        {p.art.length >= 4
          ? p.art.slice(0, 4).map((u) => <img key={u} src={`${u}?s=160`} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} />)
          : <Art src={p.art[0]} name={p.name} />}
      </div>
      <div className="card-title ellipsis">{p.name}</div>
      <div className="card-sub ellipsis">{p.track_count} songs</div>
    </Link>
  );
}

export function GenreCard({ g, to }: { g: Genre; to?: string }) {
  return (
    <Link to={to || `/genre/${encodeURIComponent(g.name)}`} className="genre-card">
      <div className="mosaic">{g.art.slice(0, 4).map((u) => <img key={u} src={`${u}?s=160`} alt="" loading="lazy" />)}</div>
      <div>
        <div className="h3">{g.name}</div>
        <div className="card-sub">{g.artists != null ? `${g.artists} artists · ` : ""}{g.albums} albums</div>
      </div>
    </Link>
  );
}

export function AlbumRow({ albums }: { albums: Album[] }) {
  return <div className="scroller">{albums.map((a) => <AlbumCard key={a.id} a={a} />)}</div>;
}
