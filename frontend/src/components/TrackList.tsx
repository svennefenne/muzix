import { Clock, Disc3, Heart, ListEnd, ListPlus, ListStart, MoreHorizontal, Play, Trash2, User } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { fmtTime } from "../api";
import { playTracks, toggleLike, usePlaylistPicker } from "../actions";
import { engine } from "../player/engine";
import { fromTrack, usePlayer } from "../store/player";
import type { Track } from "../types";
import { Art, useMenu, type MenuItem } from "./ui";

/** As in Spotify: on a touch screen a tap on a row plays it; with a mouse it takes a
 * double-click. Taps on the row's own links and buttons do their own thing. */
export function rowTap(play: () => void) {
  return (e: React.MouseEvent) => {
    if (!window.matchMedia("(hover: none)").matches) return;
    if ((e.target as HTMLElement).closest("a, button")) return;
    play();
  };
}

interface Props {
  tracks: Track[];
  showArt?: boolean;
  showAlbum?: boolean;
  numbered?: "track" | "index";
  onRemove?: (t: Track) => void;
}

export function TrackList({ tracks, showArt, showAlbum = true, numbered = "index", onRemove }: Props) {
  const current = usePlayer((s) => (s.index >= 0 ? s.queue[s.index]?.key : null));
  const playing = usePlayer((s) => s.playing);
  const showMenu = useMenu((s) => s.show);
  const pick = usePlaylistPicker((s) => s.open);
  const nav = useNavigate();
  const [liked, setLiked] = useState<Record<number, boolean>>({});
  const multiDisc = new Set(tracks.map((t) => t.disc_no)).size > 1;
  const isLiked = (t: Track) => liked[t.id] ?? t.liked;
  const like = async (t: Track) => {
    const now = await toggleLike("track", t.id, isLiked(t));
    setLiked((l) => ({ ...l, [t.id]: now }));
  };

  // phones have no room for the heart, so liking lives in the menu too
  const menuFor = (t: Track): MenuItem[] => [
    { label: "Play next", icon: <ListStart size={16} />, onClick: () => engine.enqueue([fromTrack(t)], true) },
    { label: "Add to queue", icon: <ListEnd size={16} />, onClick: () => engine.enqueue([fromTrack(t)]) },
    { label: "Add to playlist…", icon: <ListPlus size={16} />, onClick: () => pick([t.id]) },
    { label: isLiked(t) ? "Remove from liked songs" : "Add to liked songs", icon: <Heart size={16} />, onClick: () => like(t) },
    { sep: true },
    ...(t.album_id ? [{ label: "Go to album", icon: <Disc3 size={16} />, onClick: () => nav(`/album/${t.album_id}`) }] : []),
    ...(t.artist_id ? [{ label: "Go to artist", icon: <User size={16} />, onClick: () => nav(`/artist/${t.artist_id}`) }] : []),
    ...(onRemove ? [{ sep: true }, { label: "Remove from playlist", icon: <Trash2 size={16} />, onClick: () => onRemove(t) }] : []),
  ];

  let lastDisc = -1;
  return (
    <div className="tracks" role="table">
      <div className={`trow head ${showAlbum ? "" : "no-album"}`} role="row">
        <div style={{ textAlign: "right" }}>#</div>
        <div>Title</div>
        {showAlbum && <div>Album</div>}
        <div className="t-dur"><Clock size={13} /></div>
        <div className="t-actions" />
      </div>
      {tracks.map((t, i) => {
        const isCur = current === `track:${t.id}`;
        const on = isLiked(t);
        const discHead = multiDisc && numbered === "track" && t.disc_no !== lastDisc;
        lastDisc = t.disc_no;
        return (
          <div key={`${t.id}-${t.item_id ?? i}`}>
            {discHead && <div className="kicker" style={{ margin: "16px 10px 6px" }}>Disc {t.disc_no || 1}</div>}
            <div className={`trow ${showAlbum ? "" : "no-album"} ${isCur ? "playing" : ""} ${isCur && !playing ? "paused" : ""}`}
                 role="row" onDoubleClick={() => playTracks(tracks, i)}
                 onClick={rowTap(() => (isCur ? !playing && engine.toggle() : playTracks(tracks, i)))}
                 onContextMenu={(e) => { e.preventDefault(); showMenu(e, menuFor(t)); }}>
              <div className="t-num">
                {isCur ? <span className="eq n"><i /><i /><i /></span>
                  : <span className="n">{numbered === "track" && t.track_no ? t.track_no : i + 1}</span>}
                <button className="p" aria-label={`Play ${t.title}`} onClick={() => playTracks(tracks, i)}>
                  <Play size={15} fill="currentColor" />
                </button>
              </div>
              <div className="t-main">
                {showArt && <Art src={t.art} name={t.album || t.title} size={64} />}
                <div style={{ minWidth: 0 }}>
                  <div className="t-title ellipsis">{t.title}</div>
                  <div className="t-artist ellipsis">
                    {t.artist_id ? <Link to={`/artist/${t.artist_id}`}>{t.artist}</Link> : t.artist}
                    {t.system && <span className="faint"> · {t.system}</span>}
                    {t.format && !["mp3", "flac", "m4a", "ogg", "opus"].includes(t.format) &&
                      <span className="badge" style={{ marginLeft: 8 }}>{t.format}</span>}
                  </div>
                </div>
              </div>
              {showAlbum && <div className="t-album ellipsis">{t.album_id ? <Link to={`/album/${t.album_id}`}>{t.album}</Link> : t.album}</div>}
              <div className="t-dur">{fmtTime(t.duration)}</div>
              <div className="t-actions">
                <button className={`mini t-like ${on ? "liked" : ""}`} aria-label={on ? "Unlike" : "Like"} onClick={() => like(t)}>
                  <Heart size={15} fill={on ? "currentColor" : "none"} />
                </button>
                <button className="mini t-more" aria-label={`More options for ${t.title}`} onClick={(e) => showMenu(e, menuFor(t))}>
                  <MoreHorizontal size={16} />
                </button>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
