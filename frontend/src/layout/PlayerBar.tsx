import { Heart, ListMusic, Maximize2, PanelRight, Pause, Play, Repeat, Repeat1, Shuffle, SkipBack, SkipForward, Volume1, Volume2, VolumeX } from "lucide-react";
import { useRef, useState } from "react";
import { Link } from "react-router-dom";
import { fmtTime } from "../api";
import { toggleQueuedLike } from "../actions";
import { CastButton, CastNote } from "../components/CastButton";
import { Art } from "../components/ui";
import { engine } from "../player/engine";
import { usePlayer, type PlayItem, type Repeat as RepeatMode } from "../store/player";
import { useUi } from "../store/ui";

// what the transport's buttons do right now, for their tooltips (here and in the full-screen player)
export const shuffleTip = (on: boolean) => (on ? "Shuffle is on: click to play in order" : "Shuffle: play in random order");
export const repeatTip = (r: RepeatMode) => ({
  off: "Repeat is off: click to repeat the queue",
  all: "Repeating the queue: click to repeat just this song",
  one: "Repeating this song: click to turn repeat off",
})[r];
export const likeTip = (on: boolean) => (on ? "Remove from your liked songs" : "Save to your liked songs");

export function nextTip(s: { queue: PlayItem[]; index: number; shuffle: boolean; repeat: RepeatMode }) {
  if (s.shuffle && s.queue.length > 1) return "Next: a random song from the queue";
  const next = s.queue[s.index + 1] ?? (s.repeat === "all" ? s.queue[0] : undefined);
  return next ? `Next: ${next.title}${next.artist ? ` · ${next.artist}` : ""}` : "Next";
}

const QUALITY: Record<string, string> = { lossless: "lossless FLAC", high: "Opus at 160-192 kbit/s", low: "Opus at 96 kbit/s" };

/** What the badge by the volume means: the file, and how it reaches you. */
function qualityTip(cur: PlayItem, quality: string) {
  if (cur.kind === "radio") return "A live radio station";
  if (cur.kind === "spotify") return "Played by Spotify";
  const f = (cur.format || "").toUpperCase();
  if (cur.trackKind === "vgm") return `${f}: game music, played by an emulator of its chips`;
  const file = `${f} file${cur.detail ? ` (${cur.detail})` : ""}`;
  return quality === "original" || !QUALITY[quality] ? `${file}, played as it is`
    : `${file}, converted to ${QUALITY[quality]} for streaming (see Settings)`;
}

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
           data-tip={hover !== null && duration && !live ? `Jump to ${fmtTime(hover * duration)}` : ""} data-tip-follow>
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
  const { queueOpen, setQueueOpen, setNowPlayingOpen, npPanel, setPref, quality } = useUi();
  const VolIcon = s.muted || s.volume === 0 ? VolumeX : s.volume < 0.5 ? Volume1 : Volume2;
  const spoken = cur?.kind === "book" || cur?.kind === "episode";

  return (
    <div className="player" aria-label="Player">
      <div className="np">
        {cur ? (
          <>
            <button className="np-art" aria-label="Open the full-screen player" data-tip="Open the full-screen player" onClick={() => setNowPlayingOpen(true)}>
              <Art src={cur.art} name={cur.album || cur.title} size={160} />
            </button>
            <div className="np-text">
              <div className="np-title ellipsis">
                {cur.albumId ? <Link to={`/album/${cur.albumId}`}>{s.liveTitle || cur.title}</Link>
                  : cur.kind === "episode" ? <Link to={`/podcasts/episode/${cur.id}`}>{cur.title}</Link> : (s.liveTitle || cur.title)}
              </div>
              <div className="np-sub ellipsis">
                {s.liveTitle ? cur.title : cur.artistId ? <Link to={`/artist/${cur.artistId}`}>{cur.artist}</Link> : cur.artist}
                {s.error && <span className="error-text"> · {s.error}</span>}
              </div>
              <CastNote />
            </div>
            {cur.kind === "track" && (
              <button className={`mini ${cur.liked ? "liked" : ""}`} aria-label="Like" aria-pressed={!!cur.liked} data-tip={likeTip(!!cur.liked)}
                      onClick={() => toggleQueuedLike(cur)}>
                <Heart size={16} fill={cur.liked ? "currentColor" : "none"} />
              </button>
            )}
          </>
        ) : <span className="faint mono" style={{ fontSize: 11, letterSpacing: ".2em" }}>NOTHING PLAYING</span>}
      </div>

      <div className="controls">
        <div className="buttons">
          <button className={`ctl ${s.shuffle ? "on" : ""}`} aria-label="Shuffle" aria-pressed={s.shuffle} data-tip={shuffleTip(s.shuffle)}
                  onClick={() => s.set({ shuffle: !s.shuffle })}>
            <Shuffle size={17} />
          </button>
          <button className="ctl" aria-label={spoken ? "Back 15 seconds" : "Previous"}
                  data-tip={spoken ? "Back 15 seconds" : s.position > 4 ? "Back to the start of the song" : "Previous"} data-tip-key={spoken ? "←" : "P"}
                  onClick={() => (spoken ? engine.seek(s.position - 15) : engine.prev())}>
            <SkipBack size={19} fill="currentColor" />
          </button>
          <button className="ctl play" aria-label={s.playing ? "Pause" : "Play"} data-tip-key="Space" onClick={() => engine.toggle()}>
            {s.playing ? <Pause size={19} fill="currentColor" /> : <Play size={19} fill="currentColor" style={{ marginLeft: 2 }} />}
          </button>
          <button className="ctl" aria-label={spoken ? "Forward 30 seconds" : "Next"}
                  data-tip={spoken ? "Forward 30 seconds" : nextTip(s)} data-tip-key={spoken ? "→" : "N"}
                  onClick={() => (spoken ? engine.seek(s.position + 30) : engine.next())}>
            <SkipForward size={19} fill="currentColor" />
          </button>
          <button className={`ctl ${s.repeat !== "off" ? "on" : ""}`} aria-label={`Repeat: ${s.repeat}`} data-tip={repeatTip(s.repeat)}
                  onClick={() => s.set({ repeat: s.repeat === "off" ? "all" : s.repeat === "all" ? "one" : "off" })}>
            {s.repeat === "one" ? <Repeat1 size={17} /> : <Repeat size={17} />}
          </button>
        </div>
        <SeekBar />
      </div>

      <div className="right-ctl">
        {cur && <span className="quality" data-tip={qualityTip(cur, quality)}>{qualityLabel(cur)}</span>}
        {spoken && (
          <select className="select" style={{ width: 74, height: 30, fontSize: 12 }} value={s.speed} aria-label="Speed" data-tip="Playback speed"
                  onChange={(e) => s.set({ speed: Number(e.target.value) })}>
            {[0.75, 1, 1.15, 1.25, 1.5, 1.75, 2].map((v) => <option key={v} value={v}>{v}×</option>)}
          </select>
        )}
        <CastButton />
        <button className={`ctl np-toggle ${npPanel ? "on" : ""}`} aria-label="Now playing panel" aria-pressed={npPanel}
                data-tip={npPanel ? "Hide the now playing panel" : "Show the now playing panel"} onClick={() => setPref("np_panel", !npPanel)}>
          <PanelRight size={18} />
        </button>
        <button className={`ctl ${queueOpen ? "on" : ""}`} aria-label="Queue" aria-pressed={queueOpen} data-tip={queueOpen ? "Hide the queue" : "Queue: what plays next"}
                onClick={() => setQueueOpen(!queueOpen)}>
          <ListMusic size={18} />
        </button>
        <button className="ctl" aria-label={s.muted ? "Unmute" : "Mute"} aria-pressed={s.muted} data-tip-key="M" onClick={() => s.set({ muted: !s.muted })}><VolIcon size={18} /></button>
        <input className="range vol" type="range" min={0} max={1} step={0.01} value={s.muted ? 0 : s.volume}
               aria-label="Volume" data-tip={s.muted ? "Volume: muted" : `Volume: ${Math.round(s.volume * 100)}%`} onChange={(e) => s.set({ volume: Number(e.target.value), muted: false })} />
        <button className="ctl" aria-label="Full-screen player" onClick={() => setNowPlayingOpen(true)}><Maximize2 size={16} /></button>
      </div>
    </div>
  );
}
