/** The right-hand "Now playing" panel of the desktop layout (Spotify's Now Playing view):
 * the cover, what's playing, the skin it put on, and what comes next. */

import { Heart, History, ListMusic, Maximize2, Shuffle, X } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { fmtTime } from "../api";
import { playRandom, toggleLike } from "../actions";
import { useStationHistory } from "../components/StationHistory";
import { Art } from "../components/ui";
import { engine } from "../player/engine";
import { usePlayer } from "../store/player";
import { useUi } from "../store/ui";
import { useActiveTheme } from "../theme/ThemeApplier";
import { likeTip } from "./PlayerBar";

export function NowPanel() {
  const { setPref, setNowPlayingOpen, setQueueOpen, autoplay } = useUi();
  const queue = usePlayer((s) => s.queue);
  const index = usePlayer((s) => s.index);
  const live = usePlayer((s) => s.liveTitle);
  const theme = useActiveTheme();
  const showHistory = useStationHistory((s) => s.show);
  const [liked, setLiked] = useState<Record<string, boolean>>({});
  const cur = index >= 0 ? queue[index] : null;
  const next = queue.slice(index + 1, index + 6);
  const isLiked = cur ? liked[cur.key] ?? !!cur.liked : false;

  return (
    <aside className="dock nppanel" aria-label="Now playing">
      <div className="np-head">
        <h2 className="np-heading ellipsis">{cur?.album || "Now playing"}</h2>
        {cur && <button className="iconbtn" aria-label="Full-screen player" onClick={() => setNowPlayingOpen(true)}><Maximize2 size={14} /></button>}
        <button className="iconbtn" data-tip="Hide this panel" aria-label="Hide the now playing panel" onClick={() => setPref("np_panel", false)}><X size={15} /></button>
      </div>
      {cur ? (
        <div className="np-scroll">
          <button className="np-cover" onClick={() => setNowPlayingOpen(true)} aria-label="Open the full-screen player" data-tip="Open the full-screen player">
            <Art src={cur.art} name={cur.album || cur.title} size={600} />
          </button>
          <div className="np-id">
            <div className="np-idtext">
              <div className="np-track">{live || cur.title}</div>
              <div className="np-artist">
                {live ? cur.title : cur.artistId ? <Link to={`/library/artists/${cur.artistId}`}>{cur.artist}</Link> : cur.artist}
              </div>
            </div>
            {cur.kind === "track" && (
              <button className={`ctl ${isLiked ? "on" : ""}`} aria-label={isLiked ? "Remove from liked songs" : "Add to liked songs"} aria-pressed={isLiked}
                      data-tip={likeTip(isLiked)}
                      onClick={async () => setLiked({ ...liked, [cur.key]: await toggleLike("track", Number(cur.id), isLiked) })}>
                <Heart size={18} fill={isLiked ? "currentColor" : "none"} />
              </button>
            )}
          </div>
          {theme.skin && (
            <p className="np-skin" data-tip="The look follows the genre of what plays; pin one or turn them off in Settings">
              <b>{theme.skin.name}</b> skin · {theme.skin.blurb}
            </p>
          )}
          {cur.albumId && <Link className="np-albumlink" to={`/album/${cur.albumId}`}>Go to the album</Link>}
          {cur.kind === "episode" && <Link className="np-albumlink" to={`/podcasts/episode/${cur.id}`}>Go to the episode</Link>}
          {cur.kind === "radio" && (
            <button className="np-link np-albumlink" onClick={() => showHistory(String(cur.id), cur.title)}>
              <History size={14} /> Played on this station
            </button>
          )}

          <section className="np-next">
            <div className="np-next-head">
              <h3>Next in queue</h3>
              <button className="np-link" onClick={() => setQueueOpen(true)}><ListMusic size={14} /> Open queue</button>
            </div>
            {next.length ? next.map((it, i) => (
              <button key={it.key + i} className="np-qrow" data-tip={`Play now: ${it.title}`} onClick={() => engine.jump(index + 1 + i)}>
                <Art src={it.art} name={it.album || it.title} size={96} />
                <span className="np-qtext"><span className="ellipsis">{it.title}</span><small className="ellipsis">{it.artist}</small></span>
                <small className="np-qdur">{it.duration ? fmtTime(it.duration) : ""}</small>
              </button>
            )) : <p className="np-quiet">{autoplay && cur.kind === "track" ? "Autoplay is finding similar songs to play next." : "Nothing after this one."}</p>}
          </section>
        </div>
      ) : (
        <div className="np-empty">
          <p>Play something and it shows up here, with what comes next.</p>
          <button className="btn" onClick={() => playRandom({ kind: "music" })}><Shuffle size={15} /> Shuffle everything</button>
        </div>
      )}
    </aside>
  );
}
