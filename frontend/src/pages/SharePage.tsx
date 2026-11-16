/** A public link's page (/s/<token>, backend api/shares.py): what someone shared, to listen to in the browser
 * without an account. It has none of the app around it: its own small player (one <audio>), no plays
 * counted, nothing to download. A song that can't be sought in (converted or rendered as it plays) starts
 * again at the time asked for (?t=), as the app's player does. */

import { useQuery } from "@tanstack/react-query";
import { Pause, Play, SkipBack, SkipForward } from "lucide-react";
import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, fmtLong, fmtTime, sized } from "../api";
import { Logo } from "../components/Logo";
import { Art, Display, Loading } from "../components/ui";
import { ThemeApplier } from "../theme/ThemeApplier";

type Kind = "track" | "album" | "playlist" | "artist" | "podcast" | "episode";
interface Song { id: number; title: string; artist: string; album: string; duration: number; disc: number; no: number; art: string | null }
interface Ep { id: number; title: string; published: string | null; duration: number; art: string | null }
interface Shared {
  kind: Kind; title: string; sub: string; art: string | null; by: string; expires_at: string | null; site: string;
  description?: string; tracks?: Song[]; albums?: { id: number; title: string; year: number; art: string | null; tracks: Song[] }[];
  episodes?: Ep[];
}

interface Item { key: string; title: string; sub: string; art: string | null; duration: number; src: string; restart: boolean }

const KIND: Record<Kind, string> = { track: "Song", album: "Album", playlist: "Playlist", artist: "Artist", podcast: "Podcast", episode: "Podcast episode" };

const longDate = (iso: string) => new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "long", year: "numeric" });

export default function SharePage({ token }: { token: string }) {
  const q = useQuery({ queryKey: ["share", token], queryFn: () => api.get<Shared>(`/api/s/${token}`), retry: false, staleTime: Infinity });
  const d = q.data;
  useEffect(() => {
    if (d) document.title = `${d.title} · ${d.site}`;
  }, [d]);
  if (q.isError) return <Gone message={(q.error as Error).message} />;
  if (!d) return <div className="auth"><ThemeApplier /><Loading /></div>;
  return <Listen token={token} d={d} />;
}

function Gone({ message }: { message: string }) {
  return (
    <div className="auth">
      <ThemeApplier />
      <div className="auth-card">
        <div className="logo" style={{ marginBottom: 26 }}><Logo name="Muzix" /></div>
        <div className="kicker">Shared link</div>
        <Display l1="Gone" l2="quiet" small />
        <p className="lede">{(message || "This link has run out or was taken away").replace(/\.?$/, ".")} Ask whoever sent it for a new one.</p>
      </div>
    </div>
  );
}

function Listen({ token, d }: { token: string; d: Shared }) {
  const items = useMemo<Item[]>(() => {
    const songs = d.tracks ?? d.albums?.flatMap((a) => a.tracks) ?? [];
    if (songs.length) {
      return songs.map((s) => ({ key: `t${s.id}`, title: s.title, sub: s.artist, art: s.art ?? d.art, duration: s.duration,
                                 src: `/api/s/${token}/track/${s.id}`, restart: true }));
    }
    return (d.episodes ?? []).map((e) => ({ key: `e${e.id}`, title: e.title, sub: d.kind === "podcast" ? d.title : d.sub, art: e.art ?? d.art,
                                            duration: e.duration, src: `/api/s/${token}/episode/${e.id}`, restart: false }));
  }, [d, token]);
  const p = usePlayer(items, d.title);
  const total = items.reduce((n, it) => n + (it.duration || 0), 0);
  const isArtist = d.kind === "artist";
  const many = items.length > 1;
  const meta = [d.sub, many ? `${items.length} ${d.episodes ? "episodes" : "songs"}` : null, total ? fmtLong(total) : null].filter(Boolean);
  let at = 0;
  return (
    <div className="share-page">
      <ThemeApplier />
      <header className="share-top">
        <div className="logo"><Logo name={d.site} /></div>
      </header>
      <main className="page share-main">
        <div className="detail-head share-head">
          <Art src={d.art} name={d.title} size={600} round={isArtist} />
          <div style={{ minWidth: 0 }}>
            <div className="kicker">{KIND[d.kind]}<span className="sep">/</span>Shared by {d.by}</div>
            <Display l1={d.title} small />
            <div className="detail-meta">{meta.map((m, i) => <span key={i} className={i ? "dotsep" : ""}>{m}</span>)}</div>
            <div className="row-actions">
              <button className="btn accent" disabled={!items.length} onClick={() => p.toggle()}>
                {p.playing ? <><Pause size={15} fill="currentColor" /> Pause</> : <><Play size={15} fill="currentColor" /> {p.index >= 0 ? "Continue" : "Play"}</>}
              </button>
            </div>
          </div>
        </div>
        {d.description && <p className="lede share-desc">{d.description}</p>}
        {!items.length && <p className="dim">There's nothing to play here any more.</p>}
        {d.albums ? d.albums.map((a) => (
          <section key={a.id} className="share-album">
            <div className="share-album-head">
              <Art src={a.art} name={a.title} size={120} />
              <div style={{ minWidth: 0 }}>
                <div className="h3 ellipsis">{a.title}</div>
                <div className="faint">{[a.year || null, `${a.tracks.length} songs`].filter(Boolean).join(" · ")}</div>
              </div>
            </div>
            <Rows>{a.tracks.map((s) => { const i = at++; return <Row key={s.id} i={i} p={p} no={s.no || i + 1} title={s.title} sub={s.artist} time={s.duration} />; })}</Rows>
          </section>
        )) : d.tracks ? (
          <Rows>{d.tracks.map((s, i) => (
            <Fragment key={s.id}>
              {d.kind === "album" && s.disc > 0 && i > 0 && s.disc !== d.tracks![i - 1].disc && <li className="share-disc">Disc {s.disc}</li>}
              <Row i={i} p={p} no={d.kind === "album" ? s.no || i + 1 : i + 1} title={s.title}
                   sub={d.kind === "album" && s.artist === d.sub.split(" · ")[0] ? "" : s.artist} time={s.duration} />
            </Fragment>
          ))}</Rows>
        ) : (
          <Rows>{(d.episodes ?? []).map((e, i) => (
            <Row key={e.id} i={i} p={p} title={e.title} time={e.duration} sub={e.published ? longDate(e.published) : ""} />
          ))}</Rows>
        )}
        <p className="share-foot faint">
          Shared from {d.site}. Listen only{d.expires_at ? `; the link works until ${longDate(d.expires_at)}` : ""}.
        </p>
      </main>
      <Bar p={p} items={items} />
    </div>
  );
}

function Rows({ children }: { children: React.ReactNode }) {
  return <ol className="share-songs">{children}</ol>;
}

function Row({ i, p, no, title, sub, time }: { i: number; p: Player; no?: number; title: string; sub?: string; time: number }) {
  const on = p.index === i;
  return (
    <li>
      <button className={`share-row ${on ? "on" : ""}`} aria-current={on ? "true" : undefined} onClick={() => (on ? p.toggle() : p.play(i))}>
        <span className="share-no">{on && p.playing ? <Pause size={13} fill="currentColor" /> : on ? <Play size={13} fill="currentColor" /> : no ?? ""}</span>
        <span className="share-name">
          <span className="ellipsis">{title}</span>
          {sub && <span className="share-sub ellipsis">{sub}</span>}
        </span>
        <span className="share-time">{time ? fmtTime(time) : ""}</span>
      </button>
    </li>
  );
}

function Bar({ p, items }: { p: Player; items: Item[] }) {
  const it = p.index >= 0 ? items[p.index] : null;
  if (!it) return null;
  const length = p.duration;
  return (
    <div className="share-bar" role="region" aria-label="Player">
      <Art src={it.art} name={it.title} size={120} className="share-bar-art" />
      <div className="share-bar-id">
        <div className="ellipsis share-bar-title">{it.title}</div>
        <div className="ellipsis faint">{p.error ? <span className="error-text">{p.error}</span> : p.buffering ? "Loading…" : it.sub}</div>
      </div>
      <div className="share-bar-ctl">
        <button className="iconbtn" aria-label="Previous" disabled={p.index <= 0 && p.position < 3} onClick={() => p.prev()}><SkipBack size={18} fill="currentColor" /></button>
        <button className="btn accent round share-bar-play" aria-label={p.playing ? "Pause" : "Play"} onClick={() => p.toggle()}>
          {p.playing ? <Pause size={18} fill="currentColor" /> : <Play size={18} fill="currentColor" />}
        </button>
        <button className="iconbtn" aria-label="Next" disabled={p.index >= items.length - 1} onClick={() => p.next()}><SkipForward size={18} fill="currentColor" /></button>
      </div>
      <div className="share-bar-seek">
        <span className="mono">{fmtTime(p.position)}</span>
        <input type="range" min={0} max={Math.max(1, length)} step={1} value={Math.min(p.position, length || p.position)} disabled={!length}
               aria-label="Position" aria-valuetext={`${fmtTime(p.position)} of ${fmtTime(length)}`}
               onChange={(e) => p.seek(Number(e.currentTarget.value))} />
        <span className="mono">{length ? fmtTime(length) : "–:––"}</span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- the player

interface Player {
  index: number; playing: boolean; buffering: boolean; position: number; duration: number; error: string;
  play(i: number, at?: number): void; toggle(): void; next(): void; prev(): void; seek(to: number): void;
}

function usePlayer(items: Item[], collection: string): Player {
  const audio = useRef<HTMLAudioElement | null>(null);
  const offset = useRef(0);          // where the stream began, when it was started again at a time
  const [index, setIndex] = useState(-1);
  const [playing, setPlaying] = useState(false);
  const [buffering, setBuffering] = useState(false);
  const [position, setPosition] = useState(0);
  const [native, setNative] = useState(0);
  const [error, setError] = useState("");
  const now = useRef({ index, items });
  now.current = { index, items };

  const play = useCallback((i: number, at = 0) => {
    const a = audio.current;
    const it = now.current.items[i];
    if (!a || !it) return;
    setError("");
    setIndex(i);
    setPosition(at);
    offset.current = it.restart ? at : 0;
    a.src = it.restart && at > 0 ? `${it.src}?t=${at.toFixed(1)}` : it.src;
    if (!it.restart && at > 0) a.addEventListener("loadedmetadata", () => { a.currentTime = at; }, { once: true });
    a.play().catch(() => setPlaying(false));
  }, []);
  const next = useCallback(() => {
    const { index: i, items: xs } = now.current;
    if (i < xs.length - 1) play(i + 1);
  }, [play]);
  const prev = useCallback(() => {
    const a = audio.current;
    const { index: i } = now.current;
    if (a && offset.current + a.currentTime > 3) play(i, 0);
    else if (i > 0) play(i - 1);
  }, [play]);
  const toggle = useCallback(() => {
    const a = audio.current;
    if (!a) return;
    if (now.current.index < 0) return play(0);
    if (a.paused) a.play().catch(() => setPlaying(false));
    else a.pause();
  }, [play]);
  const seek = useCallback((to: number) => {
    const a = audio.current;
    const { index: i, items: xs } = now.current;
    const it = xs[i];
    if (!a || !it) return;
    const local = to - offset.current;
    const s = a.seekable;
    const reach = s.length ? s.end(s.length - 1) : 0;
    if (local >= 0 && (local <= reach || !it.restart)) a.currentTime = local;
    else play(i, to);              // converted as it plays: from there
    setPosition(to);
  }, [play]);

  useEffect(() => {
    const a = new Audio();
    a.preload = "auto";
    audio.current = a;
    const time = () => setPosition(offset.current + a.currentTime);
    const on = () => { setPlaying(true); setBuffering(false); };
    const off = () => setPlaying(false);
    const wait = () => setBuffering(true);
    const length = () => setNative(Number.isFinite(a.duration) ? a.duration : 0);
    const ended = () => {
      const { index: i, items: xs } = now.current;
      if (i < xs.length - 1) play(i + 1);
      else setPlaying(false);
    };
    const failed = () => {
      setBuffering(false);
      setPlaying(false);
      setError("This one won't play right now");
    };
    a.addEventListener("timeupdate", time);
    a.addEventListener("playing", on);
    a.addEventListener("pause", off);
    a.addEventListener("waiting", wait);
    a.addEventListener("durationchange", length);
    a.addEventListener("ended", ended);
    a.addEventListener("error", failed);
    return () => {
      a.pause();
      a.removeAttribute("src");
      a.load();
      audio.current = null;
    };
  }, [play]);

  // the lock screen, headphones and media keys
  useEffect(() => {
    const it = items[index];
    if (!it || !("mediaSession" in navigator)) return;
    const art = it.art ? new URL(sized(it.art, 512), location.href).href : undefined;
    navigator.mediaSession.metadata = new MediaMetadata({ title: it.title, artist: it.sub, album: collection,
                                                          artwork: art ? [{ src: art, sizes: "512x512" }] : [] });
    const set = (a: MediaSessionAction, h: MediaSessionActionHandler | null) => {
      try { navigator.mediaSession.setActionHandler(a, h); } catch { /* not this browser */ }
    };
    set("play", () => toggle());
    set("pause", () => toggle());
    set("previoustrack", () => prev());
    set("nexttrack", index < items.length - 1 ? () => next() : null);
    set("seekto", (e) => e.seekTime !== undefined && seek(e.seekTime));
  }, [items, index, collection, toggle, prev, next, seek]);

  // Space plays and pauses, as in the app
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.code !== "Space" || e.target instanceof HTMLInputElement || e.target instanceof HTMLButtonElement) return;
      e.preventDefault();
      toggle();
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [toggle]);

  const it = items[index];
  const duration = it?.duration || (native ? native + offset.current : 0);
  return { index, playing, buffering, position, duration, error, play, toggle, next, prev, seek };
}
