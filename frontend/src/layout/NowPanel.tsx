/** The right-hand "Now playing" panel of the desktop layout (Spotify's Now Playing view):
 * the cover, what's playing, the skin it put on, and what comes next. */

import { Heart, ListMusic, Maximize2, Shuffle, X } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { fmtTime } from "../api";
import { playRandom, toggleLike } from "../actions";
import { Art } from "../components/ui";
import { engine } from "../player/engine";
import { usePlayer } from "../store/player";
import { useUi } from "../store/ui";
import { useActiveTheme } from "../theme/ThemeApplier";

export function NowPanel() {
  const { setPref, setNowPlayingOpen, setQueueOpen } = useUi();
  const queue = usePlayer((s) => s.queue);
  const index = usePlayer((s) => s.index);
  const live = usePlayer((s) => s.liveTitle);
  const theme = useActiveTheme();
  const [liked, setLiked] = useState<Record<string, boolean>>({});
  const cur = index >= 0 ? queue[index] : null;
  const next = queue.slice(index + 1, index + 6);
  const isLiked = cur ? liked[cur.key] ?? !!cur.liked : false;

  return (
    <aside className="dock nppanel" aria-label="Now playing">
      <div className="np-head">
        <h2 className="np-heading ellipsis">{cur?.album || "Now playing"}</h2>
        {cur && <button className="iconbtn" title="Full-screen player" aria-label="Full-screen player" onClick={() => setNowPlayingOpen(true)}><Maximize2 size={14} /></button>}
        <button className="iconbtn" title="Hide this panel" aria-label="Hide the now playing panel" onClick={() => setPref("np_panel", false)}><X size={15} /></button>
      </div>
      {cur ? (
        <div className="np-scroll">
          <button className="np-cover" onClick={() => setNowPlayingOpen(true)} aria-label="Open the full-screen player">
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
                      onClick={async () => setLiked({ ...liked, [cur.key]: await toggleLike("track", Number(cur.id), isLiked) })}>
                <Heart size={18} fill={isLiked ? "currentColor" : "none"} />
              </button>
            )}
          </div>
          {theme.skin && (
            <p className="np-skin"><b>{theme.skin.name}</b> skin · {theme.skin.blurb}</p>
          )}
          {cur.albumId && <Link className="np-albumlink" to={`/album/${cur.albumId}`}>Go to the album</Link>}

          <section className="np-next">
            <div className="np-next-head">
              <h3>Next in queue</h3>
              <button className="np-link" onClick={() => setQueueOpen(true)}><ListMusic size={14} /> Open queue</button>
            </div>
            {next.length ? next.map((it, i) => (
              <button key={it.key + i} className="np-qrow" onClick={() => engine.jump(index + 1 + i)}>
                <Art src={it.art} name={it.album || it.title} size={96} />
                <span className="np-qtext"><span className="ellipsis">{it.title}</span><small className="ellipsis">{it.artist}</small></span>
                <small className="np-qdur">{it.duration ? fmtTime(it.duration) : ""}</small>
              </button>
            )) : <p className="np-quiet">Nothing after this one.</p>}
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
