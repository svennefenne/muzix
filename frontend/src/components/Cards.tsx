import { Pause, Play } from "lucide-react";
import { Link } from "react-router-dom";
import { playAlbum, playRandom } from "../actions";
import { linkData } from "../chat/store";
import { sized } from "../api";
import { engine } from "../player/engine";
import { usePlayer } from "../store/player";
import type { Album, Artist, Genre, Playlist } from "../types";
import { AdminCog, type ItemKind } from "./AdminMode";
import { Art } from "./ui";

export type Now = "" | "playing" | "paused";

/** Whether the playing song is the album's or the artist's: "playing", "paused", or "" (another's, or none). Its
 * card or row keeps its button showing, as pause while it plays (Cards.tsx, Browse.tsx). */
export function useNow(kind: "album" | "artist", id: number, peer?: string | null): Now {
  return usePlayer((s) => {
    const c = s.index >= 0 ? s.queue[s.index] : null;
    if (!c || (c.peer || null) !== (peer || null) || (kind === "album" ? c.albumId : c.artistId) !== id) return "";
    return s.playing || s.buffering ? "playing" : "paused";
  });
}

/** The album playing now keeps its button showing: pause while it plays, play on where it was once paused. */
export function AlbumCard({ a }: { a: Album }) {
  const now = useNow("album", a.id, a.peer);
  return (
    <Link to={`/album/${a.id}`} className={`card ${now ? "current" : ""}`} data-link={linkData("album", a.id, a.title, a.artist, a.art)}>
      <Art src={a.art} name={a.title} peer={a.peer} />
      <button className="play-fab" aria-label={now === "playing" ? `Pause ${a.title}` : `Play ${a.title}`}
              data-tip={now === "playing" ? "Pause" : now ? "Play on" : `Play ${a.title}`}
              onClick={(e) => { e.preventDefault(); e.stopPropagation(); if (now) engine.toggle(); else playAlbum(a.id); }}>
        {now === "playing" ? <Pause size={20} fill="currentColor" /> : <Play size={20} fill="currentColor" />}
      </button>
      <AdminCog kind="album" id={a.id} title={a.title} peer={a.peer} />
      <div className="card-title ellipsis">{a.title}</div>
      <div className="card-sub ellipsis">{[a.year || null, a.artist].filter(Boolean).join(" · ")}</div>
    </Link>
  );
}

/** The artist playing now keeps its button showing, as the album playing does (AlbumCard). */
export function ArtistCard({ a, to }: { a: Artist; to?: string }) {
  const now = useNow("artist", a.id);
  return (
    <Link to={to || `/artist/${a.id}`} className={`card ${now ? "current" : ""}`}>
      <Art src={a.art} name={a.name} round />
      <button className="play-fab" aria-label={now === "playing" ? `Pause ${a.name}` : `Play ${a.name}`}
              data-tip={now === "playing" ? "Pause" : now ? "Play on" : `Shuffle songs by ${a.name}`}
              onClick={(e) => { e.preventDefault(); e.stopPropagation(); if (now) engine.toggle(); else playRandom({ artist_id: a.id, kind: "all" }); }}>
        {now === "playing" ? <Pause size={20} fill="currentColor" /> : <Play size={20} fill="currentColor" />}
      </button>
      <AdminCog kind="artist" id={a.id} title={a.name} />
      <div className="card-title ellipsis" style={{ textAlign: "center" }}>{a.name}</div>
      <div className="card-sub ellipsis" style={{ textAlign: "center" }}>
        {a.album_count != null ? `${a.album_count} album${a.album_count === 1 ? "" : "s"}` : a.genre}
      </div>
    </Link>
  );
}

/** A playlist's card: four covers in a square, or one. */
export function MosaicCard({ to, name, art, sub, admin }: {
  to: string; name: string; art: string[]; sub: string; admin?: { kind: ItemKind; id: number };
}) {
  return (
    <Link to={to} className="card">
      <div className="art" style={{ display: "grid", gridTemplateColumns: art.length >= 4 ? "1fr 1fr" : "1fr" }}>
        {art.length >= 4
          ? art.slice(0, 4).map((u) => <img key={u} src={sized(u, 160)} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} />)
          : <Art src={art[0]} name={name} />}
      </div>
      {admin && <AdminCog kind={admin.kind} id={admin.id} title={name} />}
      <div className="card-title ellipsis">{name}</div>
      <div className="card-sub ellipsis">{sub}</div>
    </Link>
  );
}

export function PlaylistCard({ p }: { p: Playlist }) {
  return <MosaicCard to={`/playlist/${p.id}`} name={p.name} art={p.art} sub={`${p.track_count} songs`}
                     admin={{ kind: "playlist", id: p.id }} />;
}

export function GenreCard({ g, to }: { g: Genre; to?: string }) {
  return (
    <Link to={to || `/genre/${encodeURIComponent(g.name)}`} className="genre-card">
      <div className="mosaic">{g.art.slice(0, 4).map((u) => <img key={u} src={sized(u, 160)} alt="" loading="lazy" />)}</div>
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
