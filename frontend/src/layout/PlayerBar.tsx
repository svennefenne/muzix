import { Heart, ListMusic, Maximize2, Pause, Play, Repeat, Repeat1, Shuffle, SkipBack, SkipForward, Volume1, Volume2, VolumeX } from "lucide-react";
import { useRef, useState } from "react";
import { Link } from "react-router-dom";
import { fmtTime } from "../api";
import { toggleLike } from "../actions";
import { Art } from "../components/ui";
import { engine } from "../player/engine";
import { usePlayer } from "../store/player";
import { useUi } from "../store/ui";

export function SeekBar() {
  const position = usePlayer((s) => s.position);
  const duration = usePlayer((s) => s.duration);
  const cur = usePlayer((s) => (s.index >= 0 ? s.queue[s.index] : null));
  const ref = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<number | null>(null);
  const live = cur?.kind === "radio";
  const frac = live ? 1 : duration ? Math.min(1, position / duration) : 0;
  const at = (e: React.PointerEvent | React.MouseEvent) => {
    const r = ref.current!.getBoundingClientRect();
    return Math.max(0, Math.min(1, (e.clientX - r.left) / r.width));
  };
  return (
    <div className="progress">
      <span className="time">{live ? "LIVE" : fmtTime(position)}</span>
      <div className={`bar ${live ? "live" : ""}`} ref={ref}
           onPointerMove={(e) => setHover(at(e))} onPointerLeave={() => setHover(null)}
           onClick={(e) => !live && duration && engine.seek(at(e) * duration)}
           title={hover !== null && duration && !live ? fmtTime(hover * duration) : undefined}>
        <div className="track"><div className="fill" style={{ width: `${frac * 100}%` }} /></div>
        {!live && <div className="knob" style={{ left: `${frac * 100}%` }} />}
      </div>
      <span className="time">{live ? "" : fmtTime(duration)}</span>
    </div>
  );
}

function qualityLabel(cur: ReturnType<typeof usePlayer.getState>["queue"][number] | null) {
  if (!cur) return "";
  if (cur.kind === "radio") return "RADIO";
  if (cur.kind === "spotify") return "SPOTIFY";
  if (cur.trackKind === "vgm") return (cur.format || "").toUpperCase();
  return (cur.format || "").toUpperCase();
}

export function PlayerBar() {
  const s = usePlayer();
  const cur = s.current();
  const { queueOpen, setQueueOpen, setNowPlayingOpen } = useUi();
  const [liked, setLiked] = useState<Record<string, boolean>>({});
  const isLiked = cur ? liked[cur.key] ?? !!cur.liked : false;
  const VolIcon = s.muted || s.volume === 0 ? VolumeX : s.volume < 0.5 ? Volume1 : Volume2;
  const spoken = cur?.kind === "book" || cur?.kind === "episode";

  return (
    <div className="player" aria-label="Player">
      <div className="np">
        {cur ? (
          <>
            <Art src={cur.art} name={cur.album || cur.title} size={160} onClick={() => setNowPlayingOpen(true)} />
            <div className="np-text">
              <div className="np-title ellipsis">
                {cur.albumId ? <Link to={`/album/${cur.albumId}`}>{s.liveTitle || cur.title}</Link> : (s.liveTitle || cur.title)}
              </div>
              <div className="np-sub ellipsis">
                {s.liveTitle ? cur.title : cur.artistId ? <Link to={`/artist/${cur.artistId}`}>{cur.artist}</Link> : cur.artist}
                {s.error && <span className="error-text"> · {s.error}</span>}
              </div>
            </div>
            {cur.kind === "track" && (
              <button className={`mini ${isLiked ? "liked" : ""}`} aria-label="Like"
                      onClick={async () => setLiked({ ...liked, [cur.key]: await toggleLike("track", Number(cur.id), isLiked) })}>
                <Heart size={16} fill={isLiked ? "currentColor" : "none"} />
              </button>
            )}
          </>
        ) : <span className="faint mono" style={{ fontSize: 11, letterSpacing: ".2em" }}>NOTHING PLAYING</span>}
      </div>

      <div className="controls">
        <div className="buttons">
          <button className={`ctl ${s.shuffle ? "on" : ""}`} aria-label="Shuffle" onClick={() => s.set({ shuffle: !s.shuffle })}>
            <Shuffle size={17} />
          </button>
          <button className="ctl" aria-label={spoken ? "Back 15 seconds" : "Previous"}
                  onClick={() => (spoken ? engine.seek(s.position - 15) : engine.prev())}>
            <SkipBack size={19} fill="currentColor" />
          </button>
          <button className="ctl play" aria-label={s.playing ? "Pause" : "Play"} onClick={() => engine.toggle()}>
            {s.playing ? <Pause size={19} fill="currentColor" /> : <Play size={19} fill="currentColor" style={{ marginLeft: 2 }} />}
          </button>
          <button className="ctl" aria-label={spoken ? "Forward 30 seconds" : "Next"}
                  onClick={() => (spoken ? engine.seek(s.position + 30) : engine.next())}>
            <SkipForward size={19} fill="currentColor" />
          </button>
          <button className={`ctl ${s.repeat !== "off" ? "on" : ""}`} aria-label={`Repeat: ${s.repeat}`}
                  onClick={() => s.set({ repeat: s.repeat === "off" ? "all" : s.repeat === "all" ? "one" : "off" })}>
            {s.repeat === "one" ? <Repeat1 size={17} /> : <Repeat size={17} />}
          </button>
        </div>
        <SeekBar />
      </div>

      <div className="right-ctl">
        {cur && <span className="quality">{qualityLabel(cur)}</span>}
        {spoken && (
          <select className="select" style={{ width: 74, height: 30, fontSize: 12 }} value={s.speed} aria-label="Speed"
                  onChange={(e) => s.set({ speed: Number(e.target.value) })}>
            {[0.75, 1, 1.15, 1.25, 1.5, 1.75, 2].map((v) => <option key={v} value={v}>{v}×</option>)}
          </select>
        )}
        <button className={`ctl ${queueOpen ? "on" : ""}`} aria-label="Queue" onClick={() => setQueueOpen(!queueOpen)}>
          <ListMusic size={18} />
        </button>
        <button className="ctl" aria-label="Mute" onClick={() => s.set({ muted: !s.muted })}><VolIcon size={18} /></button>
        <input className="range vol" type="range" min={0} max={1} step={0.01} value={s.muted ? 0 : s.volume}
               aria-label="Volume" onChange={(e) => s.set({ volume: Number(e.target.value), muted: false })} />
        <button className="ctl" aria-label="Now playing" onClick={() => setNowPlayingOpen(true)}><Maximize2 size={16} /></button>
      </div>
    </div>
  );
}
