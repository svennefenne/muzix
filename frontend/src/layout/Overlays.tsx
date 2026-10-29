import { useQuery } from "@tanstack/react-query";
import { ChevronDown, Heart, History, ListMusic, MicVocal, Pause, Play, Plus, Repeat, Repeat1, Shuffle, SkipBack, SkipForward, X } from "lucide-react";
import { Fragment, useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, fmtNumber, fmtTime } from "../api";
import { playTracks, queryClient, toggleQueuedLike, usePlaylistPicker } from "../actions";
import { CastButton, CastNote } from "../components/CastButton";
import { hasLyrics, LyricsCard, LyricsLines, LyricsSource, noLyrics, tinted, useLyrics } from "../components/Lyrics";
import { useStationHistory } from "../components/StationHistory";
import { Art, Modal, Switch } from "../components/ui";
import { engine } from "../player/engine";
import { usePlayer, type PlayItem } from "../store/player";
import { useUi } from "../store/ui";
import { useActiveTheme } from "../theme/ThemeApplier";
import type { AlbumDetail, Home, Playlist } from "../types";
import { likeTip, nextTip, repeatTip, SeekBar, shuffleTip } from "./PlayerBar";
import { toggleFullscreen } from "./TopBar";

export function Footer() {
  const { user } = useUi();
  const theme = useActiveTheme();
  const home = useQuery({ queryKey: ["home"], queryFn: () => api.get<Home>("/api/home"), enabled: !!user });
  const jobs = useQuery({
    queryKey: ["jobs-mini"], enabled: !!user?.is_admin, refetchInterval: 8000,
    queryFn: () => api.get<{ type: string; status: string; title: string; progress: number }[]>("/api/admin/jobs", { limit: 5 }),
  });
  const running = (jobs.data || []).filter((j) => j.status === "running");
  const castOn = usePlayer((s) => s.castState === "connected");
  const castDevice = usePlayer((s) => s.castDevice);
  const lastScan = (jobs.data || []).find((j) => j.type === "scan");
  return (
    <footer className="footer">
      <span>Muzix</span><span className="sep">·</span>
      <span className="hide-sm" data-tip="The server Muzix plays from">Node {location.hostname}</span><span className="sep hide-sm">·</span>
      <Link to="/settings" data-tip="Your settings">{user?.username}</Link>
      {home.data && <><span className="sep hide-sm">·</span><span className="hide-sm" data-tip="Everything in the library">{fmtNumber(home.data.stats.tracks)} tracks · {fmtNumber(home.data.stats.vgm_tracks)} chiptunes · {home.data.stats.hours} h</span></>}
      <span className="sep">·</span>
      <span data-tip={theme.skin ? `${theme.skin.blurb}. The look follows the genre of what plays; pin one in Settings.` : "Genre skins are off; turn them on in Settings"}>
        {theme.skin ? `Skin: ${theme.skin.name}` : "Skin: off"}
      </span>
      {castOn && <><span className="sep">·</span><span data-tip="The speaker playing your music">Cast: {castDevice}</span></>}
      {running[0] && <><span className="sep">·</span><Link to="/admin/jobs" data-tip="Open the jobs page">{running[0].title} {Math.round(running[0].progress * 100)}%</Link></>}
      {!running[0] && lastScan?.status === "failed" && <><span className="sep">·</span><Link to="/admin/jobs" className="error-text" data-tip="See what went wrong">Last scan failed</Link></>}
      <div className="right">
        <button className="chip hide-sm" data-tip="Fill the whole screen" data-tip-key="F11" onClick={toggleFullscreen}>Go fullscreen! F11</button>
        <Link className="chip" to="/settings" data-tip="Light or dark, genre skins, color schemes">Appearance</Link>
      </div>
    </footer>
  );
}

export function QueueDrawer() {
  const { queueOpen, setQueueOpen, autoplay, setPref } = useUi();
  const { queue, index } = usePlayer();
  const [drag, setDrag] = useState<number | null>(null);
  const curRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (queueOpen) curRef.current?.scrollIntoView({ block: "center" });
  }, [queueOpen]);
  if (!queueOpen) return null;
  return (
    <aside className="drawer" aria-label="Queue">
      <div className="drawer-head">
        <div>
          <div className="kicker">Up next</div>
          <div className="h2" style={{ fontSize: 22 }}>Queue</div>
        </div>
        <div className="row-actions">
          {queue.length > 0 && <button className="btn small ghost" data-tip="Empty the queue" onClick={() => engine.clear()}>Clear</button>}
          <button className="mini" aria-label="Close the queue" onClick={() => setQueueOpen(false)}><X size={18} /></button>
        </div>
      </div>
      <div className="drawer-body">
        {queue.length === 0 && <div className="faint" style={{ padding: 16 }}>The queue is empty. Play something!</div>}
        {queue.map((it, i) => (
          <Fragment key={it.key + i}>
          {it.auto && !queue[i - 1]?.auto && (it.kind === "episode"
            ? <div className="kicker q-auto-head" data-tip="The podcast's autoplay is on: its next episode, in the order its page is sorted">Autoplay · next episode</div>
            : <div className="kicker q-auto-head" data-tip="Picked by the genre tags of what you played">Autoplay · similar music</div>)}
          <div ref={i === index ? curRef : undefined}
               className={`qrow ${i === index ? "current" : ""} ${drag === i ? "dragging" : ""}`}
               draggable onDragStart={() => setDrag(i)} onDragEnd={() => setDrag(null)}
               onDragOver={(e) => e.preventDefault()}
               onDrop={() => { if (drag !== null && drag !== i) engine.move(drag, i); setDrag(null); }}
               onClick={() => engine.jump(i)}>
            <Art src={it.art} name={it.album || it.title} size={64} />
            <div style={{ minWidth: 0 }}>
              <div className="ellipsis" style={{ fontWeight: 600, fontSize: 13.5, color: i === index ? "var(--primary)" : undefined }}>{it.title}</div>
              <div className="ellipsis dim" style={{ fontSize: 12 }}>{it.artist}</div>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
              <span className="faint mono" style={{ fontSize: 11 }}>{it.duration ? fmtTime(it.duration) : ""}</span>
              <button className="mini" aria-label={`Remove ${it.title} from the queue`} data-tip="Remove from the queue"
                      onClick={(e) => { e.stopPropagation(); engine.remove(i); }}><X size={14} /></button>
            </div>
          </div>
          </Fragment>
        ))}
        <div className="q-autoplay">
          <Switch checked={autoplay} onChange={(v) => setPref("autoplay", v)} label="Autoplay" />
          <div>
            <b>Autoplay</b>
            <div className="dim">When your music runs out, similar songs keep playing, picked by their genre tags.</div>
          </div>
        </div>
      </div>
    </aside>
  );
}

function Visualizer() {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const c = ref.current!;
    const g = c.getContext("2d")!;
    let raf = 0;
    const draw = () => {
      raf = requestAnimationFrame(draw);
      const w = (c.width = c.clientWidth * devicePixelRatio);
      const h = (c.height = c.clientHeight * devicePixelRatio);
      const f = engine.spectrum();
      g.clearRect(0, 0, w, h);
      if (!f) return;
      const bars = 64;
      const cs = getComputedStyle(document.documentElement);
      const grad = g.createLinearGradient(0, h, 0, 0);
      grad.addColorStop(0, cs.getPropertyValue("--secondary").trim());
      grad.addColorStop(1, cs.getPropertyValue("--primary").trim());
      g.fillStyle = grad;
      const bw = w / bars;
      for (let i = 0; i < bars; i++) {
        const v = f[Math.floor((i / bars) ** 1.6 * f.length * 0.85)] / 255;
        const bh = Math.max(2, v * h);
        g.fillRect(i * bw + 1, h - bh, bw - 3, bh);
      }
    };
    draw();
    return () => cancelAnimationFrame(raf);
  }, []);
  return <canvas ref={ref} className="viz" />;
}

/** Spotify-style controls for the full-screen player on phones. */
function PhoneTransport() {
  const showHistory = useStationHistory((s) => s.show);
  const s = usePlayer();
  const cur = s.current();
  const setQueueOpen = useUi((u) => u.setQueueOpen);
  const spoken = cur?.kind === "book" || cur?.kind === "episode";
  return (
    <div className="np-phone">
      <div className="np-transport">
        <button className={`ctl ${s.shuffle ? "on" : ""}`} aria-label="Shuffle" aria-pressed={s.shuffle} data-tip={shuffleTip(s.shuffle)}
                onClick={() => s.set({ shuffle: !s.shuffle })}><Shuffle size={22} /></button>
        <button className="ctl" aria-label={spoken ? "Back 15 seconds" : "Previous"} data-tip-key={spoken ? "←" : "P"}
                onClick={() => (spoken ? engine.seek(s.position - 15) : engine.prev())}><SkipBack size={30} fill="currentColor" /></button>
        <button className="ctl play" aria-label={s.playing ? "Pause" : "Play"} data-tip-key="Space" onClick={() => engine.toggle()}>
          {s.playing ? <Pause size={30} fill="currentColor" /> : <Play size={30} fill="currentColor" style={{ marginLeft: 3 }} />}
        </button>
        <button className="ctl" aria-label={spoken ? "Forward 30 seconds" : "Next"} data-tip={spoken ? "Forward 30 seconds" : nextTip(s)}
                data-tip-key={spoken ? "→" : "N"} onClick={() => (spoken ? engine.seek(s.position + 30) : engine.next())}><SkipForward size={30} fill="currentColor" /></button>
        <button className={`ctl ${s.repeat !== "off" ? "on" : ""}`} aria-label={`Repeat: ${s.repeat}`} data-tip={repeatTip(s.repeat)}
                onClick={() => s.set({ repeat: s.repeat === "off" ? "all" : s.repeat === "all" ? "one" : "off" })}>
          {s.repeat === "one" ? <Repeat1 size={22} /> : <Repeat size={22} />}
        </button>
      </div>
      <div className="np-extra">
        {cur?.kind === "track" ? (
          <button className={`ctl ${cur.liked ? "on" : ""}`} aria-label="Like" aria-pressed={!!cur.liked} data-tip={likeTip(!!cur.liked)}
                  onClick={() => toggleQueuedLike(cur)}>
            <Heart size={22} fill={cur.liked ? "currentColor" : "none"} />
          </button>
        ) : cur?.kind === "radio" ? (
          <button className="ctl" aria-label={`Played on ${cur.title}`} onClick={() => showHistory(String(cur.id), cur.title)}>
            <History size={22} />
          </button>
        ) : <span />}
        <CastButton size={22} />
        <button className="ctl" aria-label="Queue" data-tip="Queue: what plays next" onClick={() => setQueueOpen(true)}><ListMusic size={22} /></button>
      </div>
      <CastNote className="cast-note np-castnote" />
    </div>
  );
}

/** The big cover. With a song from an album playing, a tap turns it over to that album's
 * songs (tap one to play it); a tap anywhere outside turns it back. */
function FlipCover({ cur }: { cur: PlayItem | null }) {
  const [flipped, setFlipped] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const albumId = cur?.albumId ?? null;
  const album = useQuery({
    queryKey: ["album", albumId], enabled: flipped && !!albumId,
    queryFn: () => api.get<AlbumDetail>(`/api/albums/${albumId}`),
  });
  // another album playing shows its cover again
  useEffect(() => {
    setFlipped(false);
  }, [albumId]);
  useEffect(() => {
    if (!flipped) return;
    const away = (e: PointerEvent) => {
      if (!box.current?.contains(e.target as Node)) setFlipped(false);
    };
    document.addEventListener("pointerdown", away, true);
    return () => document.removeEventListener("pointerdown", away, true);
  }, [flipped]);
  const a = album.data;
  return (
    <div ref={box} className={`np-flip ${flipped ? "flipped" : ""}`}>
      <div className="np-flip-inner">
        <button className="np-face np-front" disabled={!albumId} tabIndex={flipped ? -1 : 0}
                aria-label={albumId ? `Show the songs on ${cur?.album || "this album"}` : undefined} onClick={() => setFlipped(true)}>
          <Art src={cur?.art} name={cur?.album || cur?.title} size={1200} />
        </button>
        <div className="np-face np-back" aria-hidden={!flipped}>
          <div className="np-back-head">
            <b className="ellipsis">{a?.title || cur?.album}</b>
            <span className="ellipsis">{[a?.artist, a?.year || null].filter(Boolean).join(" · ")}</span>
          </div>
          <ol className="np-back-list">
            {(a?.tracks || []).map((t, i) => {
              const on = cur?.key === `track:${t.id}`;
              return (
                <li key={t.id}>
                  <button className={`np-back-row ${on ? "on" : ""}`} tabIndex={flipped ? 0 : -1} aria-current={on || undefined}
                          onClick={() => playTracks(a!.tracks, i)}>
                    <span className="n">{on ? <span className="eq"><i /><i /><i /></span> : t.track_no || i + 1}</span>
                    <span className="ellipsis">{t.title}</span>
                    <span className="dur">{fmtTime(t.duration)}</span>
                  </button>
                </li>
              );
            })}
          </ol>
        </div>
      </div>
    </div>
  );
}

/** The full-screen player's way to the lyrics (lean-back: lyrics across the whole screen). */
function LyricsButton() {
  const cur = usePlayer((s) => (s.index >= 0 ? s.queue[s.index] : null));
  const q = useLyrics(cur);
  const open = useUi((s) => s.setLyricsSheet);
  if (!hasLyrics(q.data)) return null;
  return <button className="btn" onClick={() => open(true)}><MicVocal size={15} /> Lyrics</button>;
}

/** The lyrics full screen, as on Spotify's phone app: the cover's colour, big words, and the
 * song's time and play button at the bottom. */
export function LyricsSheet() {
  const open = useUi((s) => s.lyricsSheet);
  const setOpen = useUi((s) => s.setLyricsSheet);
  const cur = usePlayer((s) => (s.index >= 0 ? s.queue[s.index] : null));
  const playing = usePlayer((s) => s.playing);
  const q = useLyrics(cur);
  useEffect(() => {
    if (!open) return;
    const key = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      e.stopImmediatePropagation();     // the full-screen player underneath stays open
      setOpen(false);
    };
    window.addEventListener("keydown", key, true);
    return () => window.removeEventListener("keydown", key, true);
  }, [open, setOpen]);
  if (!open || !cur) return null;
  const look = tinted(q.data, "lyr-sheet");
  return (
    <div {...look} role="dialog" aria-label={`Lyrics: ${cur.title}`}>
      <div className="lyr-sheet-head">
        <button className="iconbtn" aria-label="Close the lyrics" data-tip-key="Esc" onClick={() => setOpen(false)}><ChevronDown size={20} /></button>
        <div className="lyr-sheet-title">
          <b className="ellipsis">{cur.title}</b>
          <span className="ellipsis">{cur.artist}</span>
        </div>
      </div>
      {q.data && hasLyrics(q.data)
        ? <LyricsLines lyrics={q.data} className="lyr-big" />
        : <p className="lyr-none">{noLyrics(cur, q)}</p>}
      <div className="lyr-sheet-foot">
        {q.data && <LyricsSource lyrics={q.data} />}
        <SeekBar />
        <button className="ctl play" aria-label={playing ? "Pause" : "Play"} data-tip-key="Space" onClick={() => engine.toggle()}>
          {playing ? <Pause size={26} fill="currentColor" /> : <Play size={26} fill="currentColor" style={{ marginLeft: 3 }} />}
        </button>
      </div>
    </div>
  );
}

export function NowPlaying() {
  const showHistory = useStationHistory((s) => s.show);
  const { nowPlayingOpen, setNowPlayingOpen, setLyricsSheet } = useUi();
  const cur = usePlayer((s) => (s.index >= 0 ? s.queue[s.index] : null));
  const live = usePlayer((s) => s.liveTitle);
  const theme = useActiveTheme();
  useEffect(() => {
    const key = (e: KeyboardEvent) => e.key === "Escape" && setNowPlayingOpen(false);
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [setNowPlayingOpen]);
  if (!nowPlayingOpen) return null;
  return (
    <div className="nowplaying">
      <div style={{ display: "flex", justifyContent: "space-between", padding: "18px 24px" }}>
        <div className="kicker">Now playing{theme.skin ? ` · ${theme.skin.name} skin · ${theme.skin.blurb}` : ""}</div>
        <button className="iconbtn" aria-label="Close the full-screen player" data-tip-key="Esc" onClick={() => setNowPlayingOpen(false)}><ChevronDown size={18} /></button>
      </div>
      <div className="nowplaying-body">
        <FlipCover cur={cur} />
        <div style={{ minWidth: 0 }}>
          {cur ? (
            <>
              <div className="kicker">{[cur.kind === "radio" ? "On air" : cur.system || cur.genre, cur.album].filter(Boolean).join(" · ")}</div>
              <div className="np-big-title">{live || cur.title}</div>
              <div className="lede" style={{ fontSize: 20 }}>
                {live ? cur.title : cur.artistId
                  ? <Link className="np-artist-link" to={`/artist/${cur.artistId}`} onClick={() => setNowPlayingOpen(false)}>{cur.artist}</Link>
                  : cur.artist}
              </div>
              <Visualizer />
              <div className="np-seek"><SeekBar /></div>
              <PhoneTransport />
              <div className="np-lyrics-card"><LyricsCard item={cur} phone onExpand={() => setLyricsSheet(true)} /></div>
              <div className="row-actions np-desktop-actions" style={{ marginTop: 18 }}>
                <button className="btn" data-tip="Previous song" data-tip-key="P" onClick={() => engine.prev()}>Previous</button>
                <button className="btn accent" data-tip="Play or pause" data-tip-key="Space" onClick={() => engine.toggle()}>Play / pause</button>
                <button className="btn" data-tip={nextTip(usePlayer.getState())} data-tip-key="N" onClick={() => engine.next()}>Next</button>
                {cur.kind === "radio" && (
                  <button className="btn" onClick={() => showHistory(String(cur.id), cur.title)}><History size={15} /> Played here</button>
                )}
                <LyricsButton />
                <CastButton className="btn" size={15} label />
              </div>
              <div className="np-desktop-actions"><CastNote /></div>
            </>
          ) : <div className="lede">Nothing is playing.</div>}
        </div>
      </div>
      <div />
    </div>
  );
}

export function PlaylistPicker() {
  const { trackIds, close } = usePlaylistPicker();
  const notify = useUi((s) => s.notify);
  const lists = useQuery({ queryKey: ["playlists"], queryFn: () => api.get<Playlist[]>("/api/playlists"), enabled: !!trackIds });
  const [name, setName] = useState("");
  if (!trackIds) return null;
  const add = async (pid: number, pname: string) => {
    await api.post(`/api/playlists/${pid}/tracks`, { track_ids: trackIds });
    queryClient.invalidateQueries({ queryKey: ["playlists"] });
    queryClient.invalidateQueries({ queryKey: ["playlist", pid] });
    notify(`Added to ${pname}`);
    close();
  };
  const create = async () => {
    if (!name.trim()) return;
    const p = await api.post<Playlist>("/api/playlists", { name: name.trim() });
    await add(p.id, p.name);
  };
  return (
    <Modal onClose={close}>
      <div className="kicker">{trackIds.length} song{trackIds.length === 1 ? "" : "s"}</div>
      <div className="h2" style={{ marginBottom: 16 }}>Add to playlist</div>
      <div className="list" style={{ marginBottom: 16 }}>
        {(lists.data || []).map((p) => (
          <button key={p.id} className="list-row" style={{ cursor: "pointer", textAlign: "left" }} onClick={() => add(p.id, p.name)}>
            <div className="grow"><b>{p.name}</b><div className="dim" style={{ fontSize: 12 }}>{p.track_count} songs</div></div>
            <Plus size={16} />
          </button>
        ))}
      </div>
      <div className="row-actions">
        <input className="input" placeholder="New playlist name" value={name} onChange={(e) => setName(e.target.value)}
               onKeyDown={(e) => e.key === "Enter" && create()} style={{ flex: 1 }} />
        <button className="btn accent" onClick={create}>Create</button>
      </div>
    </Modal>
  );
}

export function Toast() {
  const toast = useUi((s) => s.toast);
  const navigate = useNavigate();
  if (!toast) return null;
  const act = toast.action;
  return (
    <div className={`toast ${toast.kind}`} role="status">
      {toast.text}
      {act && <button className="toast-action" onClick={() => {
        useUi.setState({ toast: null });
        if (act.to) navigate(act.to);
        act.run?.();
      }}>{act.label}</button>}
    </div>
  );
}
