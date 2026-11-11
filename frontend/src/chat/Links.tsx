/** Albums and songs linked in the chat: the card in a message, the bigger card on hover (the cover,
 * its name and so on), and "More info" with its own little player. */

import { useQuery } from "@tanstack/react-query";
import { Disc3, ListEnd, Network, Pause, Play, SkipBack, SkipForward, X } from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { create } from "zustand";
import { queryClient } from "../actions";
import { api, fmtLong, fmtTime } from "../api";
import { Art, Modal } from "../components/ui";
import { engine } from "../player/engine";
import { fromTrack, type PlayItem } from "../store/player";
import { useUi } from "../store/ui";
import type { AlbumDetail } from "../types";
import { isTyping } from "../layout/TopBar";
import { type Preview, usePreview } from "./preview";
import { type ChatLink, type ChatSong, useChat } from "./store";

type FullLink = ChatLink & { tracks: ChatSong[] };

/** The server it's on, unless it's this one (then the cover gets no network mark). */
const elsewhere = (l: ChatLink) => (l.elsewhere ? l.place : null);

function where(l: ChatLink) {
  if (l.reach === "here") return l.elsewhere ? `In your library, from ${l.place}` : "In your library";
  if (l.reach === "network") return `From ${l.place}, played through your server`;
  return l.place ? `On ${l.place}` : "Not in your library";
}

// ------------------------------------------------------------ the card on hover

interface HoverState {
  link: ChatLink | null;
  rect: DOMRect | null;
  edge: number | null;          // the chat panel's left edge: the card stays clear of the panel
  set: (link: ChatLink | null, rect?: DOMRect | null, edge?: number | null) => void;
}

const useHover = create<HoverState>((set) => ({
  link: null, rect: null, edge: null, set: (link, rect = null, edge = null) => set({ link, rect, edge }),
}));

const touch = () => matchMedia("(hover: none)").matches;

/** A linked album or song in a message: opens "More info"; on hover, its cover large. */
export function LinkCard({ link, message, index }: { link: ChatLink; message: number; index: number }) {
  const setMore = useChat((s) => s.setMore);
  const showHover = useHover((s) => s.set);
  const timer = useRef<number | undefined>(undefined);
  const enter = (e: React.SyntheticEvent<HTMLElement>) => {
    if (touch()) return;
    const el = e.currentTarget;
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => {
      const dock = el.closest(".chatdock")?.getBoundingClientRect();
      showHover(link, el.getBoundingClientRect(), dock ? dock.left : null);
    }, 220);
  };
  const leave = () => {
    window.clearTimeout(timer.current);
    showHover(null);
  };
  useEffect(() => () => window.clearTimeout(timer.current), []);
  const sub = link.kind === "track" ? `Song · ${link.artist}` : `Album · ${link.artist}`;
  return (
    <button className={`chat-link ${link.reach === "away" ? "away" : ""}`} data-tip=""
            aria-label={`${link.title}, ${sub}. More info`}
            onMouseEnter={enter} onMouseLeave={leave} onFocus={enter} onBlur={leave}
            onClick={() => { leave(); setMore({ message, index, link }); }}>
      <Art src={link.cover} name={link.album?.title || link.title} size={96} peer={elsewhere(link)} />
      <span className="chat-link-text">
        <b className="ellipsis">{link.title}</b>
        <small className="ellipsis">{sub}</small>
      </span>
    </button>
  );
}

export function HoverCard() {
  const { link, rect, edge } = useHover();
  const box = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null);
  useLayoutEffect(() => {
    if (!link || !rect || !box.current) return setPos(null);
    const w = box.current.offsetWidth;
    const h = box.current.offsetHeight;
    // beside the chat, clear of it; to the right of the link when there's no room (the chat full screen)
    let left = (edge ?? rect.left) - w - 12;
    if (left < 8) left = Math.min(rect.right + 14, innerWidth - w - 8);
    const top = Math.max(8, Math.min(rect.top + rect.height / 2 - h / 2, innerHeight - h - 8));
    setPos({ left, top });
  }, [link, rect, edge]);
  useEffect(() => {
    if (!link) return;
    const hide = () => useHover.getState().set(null);
    window.addEventListener("scroll", hide, true);
    return () => window.removeEventListener("scroll", hide, true);
  }, [link]);
  if (!link) return null;
  return (
    <div ref={box} className="chat-hover" role="tooltip" style={pos ? { left: pos.left, top: pos.top } : { visibility: "hidden" }}>
      <Art src={link.cover} name={link.album?.title || link.title} size={300} peer={elsewhere(link)} />
      <b className="chat-hover-title">{link.title}</b>
      <span className="chat-hover-sub">{[link.artist, link.year].filter(Boolean).join(" · ")}</span>
      {link.kind === "track" && link.album && <span className="chat-hover-sub">From {link.album.title}</span>}
      {link.songs > 0 && link.kind === "album" && (
        <span className="chat-hover-sub">{link.songs} song{link.songs === 1 ? "" : "s"} · {fmtLong(link.length)}</span>
      )}
      <span className="chat-hover-where">{link.elsewhere && <Network size={12} />}{where(link)}</span>
    </div>
  );
}

// ------------------------------------------------------------ More info

/** The linked songs as Muzix's player takes them: this library's own songs as they are, another
 * server's as songs heard through this one (nothing is kept about them). */
async function asItems(link: FullLink): Promise<{ items: PlayItem[]; local: (number | null)[] }> {
  if (link.here_album) {
    const a = await queryClient.fetchQuery({ queryKey: ["album", link.here_album], queryFn: () => api.get<AlbumDetail>(`/api/albums/${link.here_album}`) });
    return { items: a.tracks.map(fromTrack), local: a.tracks.map((t) => t.id) };
  }
  const songs = link.tracks.filter((s) => s.stream);
  return {
    local: songs.map((s) => s.local),
    items: songs.map((s) => {
      const key = s.local ? `track:${s.local}` : `chat:${link.server}:${s.id}`;
      return {
        key, kind: s.local ? "track" as const : "online" as const, id: s.local ?? key, title: s.title, artist: s.artist || link.artist,
        album: link.album?.title, art: link.cover, duration: s.duration, src: s.stream!, peer: elsewhere(link),
        albumId: link.here_album, trackKind: "music" as const,
      };
    }),
  };
}

export function MoreInfoHost() {
  const more = useChat((s) => s.more);
  const setMore = useChat((s) => s.setMore);
  if (!more) return null;
  return <MoreInfo key={`${more.message}:${more.index}`} link={more.link} message={more.message} index={more.index} onClose={() => setMore(null)} />;
}

function MoreInfo({ link, message, index, onClose }: { link: ChatLink; message: number; index: number; onClose: () => void }) {
  const nav = useNavigate();
  const notify = useUi((s) => s.notify);
  const q = useQuery({
    queryKey: ["chat", "link", message, index],
    queryFn: () => api.get<FullLink>(`/api/chat/messages/${message}/links/${index}`),
  });
  const full = q.data;
  const songs = full?.tracks || [];
  const preview = usePreview(songs);
  const first = link.kind === "track" ? Math.max(0, songs.findIndex((s) => s.id === link.id)) : 0;
  const shown = full || link;
  const playable = songs.some((s) => s.stream);

  // Space plays and pauses this player while the box is open, not Muzix's
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.key !== " " || isTyping(e) || (e.target as HTMLElement)?.closest?.("button")) return;
      e.preventDefault();
      e.stopPropagation();
      if (preview.index < 0) preview.play(first);
      else preview.toggle();
    };
    window.addEventListener("keydown", key, true);
    return () => window.removeEventListener("keydown", key, true);
  }, [preview, first]);

  const toMuzix = async (queue: boolean) => {
    if (!full) return;
    const at = preview.handOver();
    const { items, local } = await asItems(full);
    if (!items.length) return;
    if (queue) {
      engine.enqueue(items);
      notify(`${full.title} is in the queue`);
      return;
    }
    // from the song the preview is on (or the linked song), where it got to
    const from = preview.index >= 0 ? at.index : first;
    const song = songs[from];
    let start = song?.local ? local.indexOf(song.local) : items.findIndex((it) => it.key === `chat:${full.server}:${song?.id}`);
    if (start < 0) start = 0;
    if (preview.index >= 0 && at.position > 1) items[start] = { ...items[start], resume: at.position };
    engine.play(items, start);
    onClose();
  };

  return (
    <Modal onClose={onClose} className="more-info">
      <button className="iconbtn mi-close" aria-label="Close" onClick={onClose}><X size={16} /></button>
      <div className="mi-head">
        <Art src={shown.cover} name={shown.album?.title || shown.title} size={300} peer={elsewhere(shown)} />
        <div className="mi-id">
          <h2 className="mi-title">{shown.title}</h2>
          <p className="mi-sub">{[shown.artist, shown.year].filter(Boolean).join(" · ")}</p>
          {link.kind === "track" && shown.album && <p className="mi-sub">From {shown.album.title}</p>}
          <p className="mi-where">{shown.elsewhere && <Network size={13} />}{where(shown)}</p>
          {shown.reach !== "away" && (
            <div className="row-actions mi-actions">
              <button className="btn accent" disabled={!full || !playable} onClick={() => toMuzix(false)}>
                <Play size={15} fill="currentColor" /> Play in Muzix
              </button>
              <button className="btn" disabled={!full || !playable} onClick={() => toMuzix(true)}><ListEnd size={15} /> Add to queue</button>
              {shown.here_album && (
                <button className="btn ghost" onClick={() => { onClose(); useChat.getState().close(); nav(`/album/${shown.here_album}`); }}>
                  <Disc3 size={15} /> Go to the album
                </button>
              )}
            </div>
          )}
        </div>
      </div>

      {shown.reach === "away" ? (
        <p className="mi-note">It isn't in your library, and it can't be played from here.</p>
      ) : q.isError ? (
        <p className="error-text mi-note">{(q.error as Error).message}</p>
      ) : (
        <>
          <PreviewBar preview={preview} songs={songs} first={first} />
          {preview.error && <p className="error-text mi-note">{preview.error}</p>}
          {preview.paused && <p className="mi-note">Your music is paused while you listen here, and goes on when you close this.</p>}
          <ol className="mi-tracks" aria-label="Songs">
            {!full && Array.from({ length: Math.min(link.songs || 4, 8) }, (_, i) => <li key={i} className="mi-track skeleton" aria-hidden />)}
            {songs.map((s, i) => {
              const on = preview.index === i;
              return (
                <li key={`${s.id}-${i}`}>
                  <button className={`mi-track ${on ? "on" : ""} ${link.kind === "track" && s.id === link.id ? "linked" : ""}`}
                          disabled={!s.stream} onClick={() => (on ? preview.toggle() : preview.play(i))}
                          aria-label={`${on && preview.playing ? "Pause" : "Play"} ${s.title}`} data-tip="">
                    <span className="mi-no">{on && preview.playing ? <span className="eq"><i /><i /><i /></span> : s.no || i + 1}</span>
                    <span className="mi-name">
                      <span className="ellipsis">{s.title}</span>
                      {s.artist && s.artist !== shown.artist && <small className="ellipsis">{s.artist}</small>}
                    </span>
                    <span className="mi-dur">{fmtTime(s.duration)}</span>
                  </button>
                </li>
              );
            })}
          </ol>
        </>
      )}
    </Modal>
  );
}

function PreviewBar({ preview, songs, first }: { preview: Preview; songs: ChatSong[]; first: number }) {
  const bar = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<number | null>(null);
  const song = preview.index >= 0 ? songs[preview.index] : songs[first];
  const duration = song?.duration || 0;
  const frac = duration ? Math.min(1, preview.position / duration) : 0;
  const at = (e: React.PointerEvent | React.MouseEvent) => {
    const r = bar.current!.getBoundingClientRect();
    return Math.max(0, Math.min(1, (e.clientX - r.left) / r.width));
  };
  const started = preview.index >= 0;
  return (
    <div className="mi-player" aria-label="Preview player">
      <div className="mi-controls">
        <button className="ctl" aria-label="Previous song" disabled={!started || preview.index === 0} onClick={() => preview.step(-1)}>
          <SkipBack size={17} fill="currentColor" />
        </button>
        <button className="ctl play" aria-label={preview.playing ? "Pause" : "Play"} disabled={!song?.stream}
                onClick={() => (started ? preview.toggle() : preview.play(first))}>
          {preview.playing ? <Pause size={18} fill="currentColor" /> : <Play size={18} fill="currentColor" />}
        </button>
        <button className="ctl" aria-label="Next song" disabled={!started || preview.index >= songs.length - 1} onClick={() => preview.step(1)}>
          <SkipForward size={17} fill="currentColor" />
        </button>
      </div>
      <div className="mi-now">
        <span className={`mi-now-title ellipsis ${preview.loading ? "loading" : ""}`}>{song ? song.title : "Loading…"}</span>
        <div className="progress">
          <span className="time">{fmtTime(preview.position)}</span>
          <div className="bar" ref={bar}
               onPointerMove={(e) => setHover(at(e))} onPointerLeave={() => setHover(null)}
               onClick={(e) => { if (!duration) return; if (started) preview.seek(at(e) * duration); }}
               data-tip={hover !== null && duration && started ? `Jump to ${fmtTime(hover * duration)}` : ""} data-tip-follow>
            <div className="track"><div className="fill" style={{ width: `${frac * 100}%` }} /></div>
            {started && <div className="knob" style={{ left: `${frac * 100}%` }} />}
          </div>
          <span className="time">{fmtTime(duration)}</span>
        </div>
      </div>
    </div>
  );
}
