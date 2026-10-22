import { useQuery } from "@tanstack/react-query";
import { ChevronDown, Plus, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, fmtNumber, fmtTime } from "../api";
import { queryClient, usePlaylistPicker } from "../actions";
import { Art, Modal } from "../components/ui";
import { engine } from "../player/engine";
import { usePlayer } from "../store/player";
import { useUi } from "../store/ui";
import { useActiveTheme } from "../theme/ThemeApplier";
import type { Home, Playlist } from "../types";
import { SeekBar } from "./PlayerBar";
import { toggleFullscreen } from "./TopBar";

export function Footer() {
  const { user } = useUi();
  const theme = useActiveTheme();
  const home = useQuery({ queryKey: ["home"], queryFn: () => api.get<Home>("/api/home"), enabled: !!user });
  const jobs = useQuery({
    queryKey: ["jobs-mini"], enabled: !!user?.is_admin, refetchInterval: 8000,
    queryFn: () => api.get<{ status: string; title: string; progress: number }[]>("/api/admin/jobs", { limit: 5 }),
  });
  const running = (jobs.data || []).filter((j) => j.status === "running");
  return (
    <footer className="footer">
      <span>Muzix</span><span className="sep">·</span>
      <span className="hide-sm">Node {location.hostname}</span><span className="sep hide-sm">·</span>
      <Link to="/settings">{user?.username}</Link>
      {home.data && <><span className="sep hide-sm">·</span><span className="hide-sm">{fmtNumber(home.data.stats.tracks)} tracks · {fmtNumber(home.data.stats.vgm_tracks)} chiptunes · {home.data.stats.hours} h</span></>}
      <span className="sep">·</span>
      <span>{theme.skin ? `Skin: ${theme.skin.name}` : "Skin: off"}</span>
      {running[0] && <><span className="sep">·</span><Link to="/admin/jobs">{running[0].title} {Math.round(running[0].progress * 100)}%</Link></>}
      <div className="right">
        <button className="chip hide-sm" onClick={toggleFullscreen}>Go fullscreen! F11</button>
        <Link className="chip" to="/settings">Appearance</Link>
      </div>
    </footer>
  );
}

export function QueueDrawer() {
  const { queueOpen, setQueueOpen } = useUi();
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
          {queue.length > 0 && <button className="btn small ghost" onClick={() => engine.clear()}>Clear</button>}
          <button className="mini" aria-label="Close" onClick={() => setQueueOpen(false)}><X size={18} /></button>
        </div>
      </div>
      <div className="drawer-body">
        {queue.length === 0 && <div className="faint" style={{ padding: 16 }}>The queue is empty. Play something!</div>}
        {queue.map((it, i) => (
          <div key={it.key + i} ref={i === index ? curRef : undefined}
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
              <button className="mini" aria-label="Remove" onClick={(e) => { e.stopPropagation(); engine.remove(i); }}><X size={14} /></button>
            </div>
          </div>
        ))}
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

export function NowPlaying() {
  const { nowPlayingOpen, setNowPlayingOpen } = useUi();
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
        <button className="iconbtn" aria-label="Close" onClick={() => setNowPlayingOpen(false)}><ChevronDown size={18} /></button>
      </div>
      <div className="nowplaying-body">
        <Art src={cur?.art} name={cur?.album || cur?.title} size={1200} />
        <div style={{ minWidth: 0 }}>
          {cur ? (
            <>
              <div className="kicker">{[cur.kind === "radio" ? "On air" : cur.system || cur.genre, cur.album].filter(Boolean).join(" · ")}</div>
              <div className="np-big-title">{live || cur.title}</div>
              <div className="lede" style={{ fontSize: 20 }}>{live ? cur.title : cur.artist}</div>
              <Visualizer />
              <div style={{ marginTop: 24, maxWidth: 640 }}><SeekBar /></div>
              <div className="row-actions" style={{ marginTop: 18 }}>
                <button className="btn" onClick={() => engine.prev()}>Previous</button>
                <button className="btn accent" onClick={() => engine.toggle()}>Play / pause</button>
                <button className="btn" onClick={() => engine.next()}>Next</button>
              </div>
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
  if (!toast) return null;
  return <div className={`toast ${toast.kind}`} role="status">{toast.text}</div>;
}
