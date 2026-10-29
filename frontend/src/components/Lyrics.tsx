/** Lyrics as on Spotify: the song's words on its cover's colour, the line being sung lit, the
 * ones already sung dimmed, a click on a line to go there. A card in the now playing panel, the
 * whole panel with the microphone button, and full screen (the phone's way, and lean-back). */

import { useQuery } from "@tanstack/react-query";
import { Maximize2, MicVocal, Music2 } from "lucide-react";
import { type CSSProperties, type ReactNode, useEffect, useRef } from "react";
import { api } from "../api";
import { engine } from "../player/engine";
import { usePlayer, type PlayItem } from "../store/player";
import { useUi } from "../store/ui";
import type { LyricLine, Lyrics } from "../types";

export function useLyrics(item: PlayItem | null) {
  const id = item?.kind === "track" ? item.id : null;
  return useQuery({
    queryKey: ["lyrics", id], enabled: id !== null, staleTime: Infinity, retry: false,
    queryFn: () => api.get<Lyrics>(`/api/tracks/${id}/lyrics`),
  });
}

export const hasLyrics = (l?: Lyrics) => !!l && l.lines.length > 0;

/** Why there are no lyrics to show. */
export function noLyrics(item: PlayItem | null, q: { data?: Lyrics; isFetching: boolean }) {
  return !item ? "Nothing is playing" : item.kind !== "track" ? "Lyrics are for songs from the library"
    : q.isFetching ? "Looking for lyrics…" : q.data?.instrumental ? "An instrumental: no words to show" : "No lyrics found for this song";
}

function hsl(hex: string): [number, number, number] {
  const n = parseInt(hex.slice(1), 16);
  const [r, g, b] = [(n >> 16) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255];
  const max = Math.max(r, g, b), min = Math.min(r, g, b), l = (max + min) / 2, d = max - min;
  if (!d) return [0, 0, l];
  const s = d / (1 - Math.abs(2 * l - 1));
  const h = max === r ? ((g - b) / d) % 6 : max === g ? (b - r) / d + 2 : (r - g) / d + 4;
  return [(h * 60 + 360) % 360, s, l];
}

/** The colour behind the words: the cover's most colourful one, deep enough for white words. */
export function lyricsTint(colors: string[]): string | undefined {
  let best: [number, number, number] | undefined;
  let most = -1;
  for (const c of colors) {
    if (!/^#[0-9a-f]{6}$/i.test(c)) continue;
    const [h, s, l] = hsl(c);
    const chroma = s * (1 - Math.abs(2 * l - 1));
    if (chroma > most) {
      most = chroma;
      best = [h, s, l];
    }
  }
  if (!best) return undefined;
  const [h, s] = best;
  return s < 0.1 ? `hsl(${Math.round(h)} ${Math.round(s * 100)}% 22%)` : `hsl(${Math.round(h)} ${Math.round(Math.min(s, 0.62) * 100)}% 29%)`;
}

/** Props that dress an element in the lyrics' colours: the cover's tint, or the skin's own. */
export function tinted(l?: Lyrics, base = ""): { className: string; style?: CSSProperties } {
  const tint = l && lyricsTint(l.colors);
  return tint ? { className: `${base} lyr-tinted`, style: { "--lyr-bg": tint } as CSSProperties } : { className: base };
}

/** The line being sung: the last one whose time has come (a moment early, as the voice starts). */
function lineAt(lines: LyricLine[], pos: number) {
  let lo = 0, hi = lines.length - 1, at = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if ((lines[mid].t ?? 0) <= pos + 0.2) {
      at = mid;
      lo = mid + 1;
    } else hi = mid - 1;
  }
  return at;
}

const still = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/** The words. Synced ones follow the song and scroll along, unless the listener scrolls them:
 * then they're left alone for a few seconds. `seek`: a click on a line plays from there. */
export function LyricsLines({ lyrics, seek = true, className = "" }: { lyrics: Lyrics; seek?: boolean; className?: string }) {
  const box = useRef<HTMLDivElement>(null);
  const held = useRef(0);
  const now = usePlayer((s) => (lyrics.synced ? lineAt(lyrics.lines, s.position) : -1));
  useEffect(() => {
    if (box.current) box.current.scrollTop = 0;
  }, [lyrics]);
  useEffect(() => {
    const el = box.current;
    const line = el?.children[Math.max(now, 0)] as HTMLElement | undefined;
    if (!el || !line || now < 0 || Date.now() < held.current) return;
    el.scrollTo({ top: line.offsetTop - el.clientHeight * 0.3, behavior: still() ? "auto" : "smooth" });
  }, [now]);
  const hold = () => {
    held.current = Date.now() + 4000;
  };
  return (
    <div ref={box} className={`lyr-lines ${lyrics.synced ? "synced" : ""} ${className}`}
         onWheel={hold} onTouchMove={hold} onKeyDown={hold}>
      {lyrics.lines.map((line, i) => {
        const state = !lyrics.synced ? "" : i < now ? "past" : i === now ? "now" : "next";
        // a pause in the singing shows as a note while it lasts
        const words: ReactNode = line.text || (state === "now" ? <Music2 size="0.9em" aria-label="Instrumental break" /> : " ");
        return lyrics.synced && seek ? (
          <button key={i} className={`lyr ${state}`} aria-current={i === now || undefined} onClick={() => engine.seek(line.t ?? 0)}>
            {words}
          </button>
        ) : <p key={i} className={`lyr ${state}`} aria-current={i === now || undefined}>{words}</p>;
      })}
    </div>
  );
}

const SOURCE: Record<string, ReactNode> = {
  file: "From the song's .lrc file",
  tags: "From the song's tags",
  lrclib: <>Lyrics from <a href="https://lrclib.net" target="_blank" rel="noreferrer">LRCLIB</a></>,
};

export function LyricsSource({ lyrics }: { lyrics: Lyrics }) {
  if (!lyrics.source) return null;
  return (
    <p className="lyr-src">
      {SOURCE[lyrics.source]}{!lyrics.synced && " · not synced to the song"}
    </p>
  );
}

/** The lyrics card: in the now playing panel, and under the controls of the phone's full player,
 * where a tap anywhere on it opens them full screen. */
export function LyricsCard({ item, onExpand, phone }: { item: PlayItem; onExpand: () => void; phone?: boolean }) {
  const q = useLyrics(item);
  if (!q.data || !hasLyrics(q.data)) return null;
  const look = tinted(q.data, `lyr-card ${phone ? "phone" : ""}`);
  const head = (
    <div className="lyr-head">
      <h3>Lyrics</h3>
      {!phone && (
        <button className="lyr-expand" aria-label="Lyrics in the whole panel" data-tip="Show the lyrics in the whole panel" onClick={onExpand}>
          <Maximize2 size={15} />
        </button>
      )}
    </div>
  );
  return phone ? (
    <section {...look} role="button" tabIndex={0} aria-label="Open the lyrics" onClick={onExpand}
             onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && onExpand()}>
      {head}
      <LyricsLines lyrics={q.data} seek={false} />
    </section>
  ) : (
    <section {...look} aria-label="Lyrics">
      {head}
      <LyricsLines lyrics={q.data} />
      <LyricsSource lyrics={q.data} />
    </section>
  );
}

/** The player bar's microphone: the lyrics in the whole now playing panel. */
export function MicButton({ item }: { item: PlayItem | null }) {
  const q = useLyrics(item);
  const on = useUi((s) => s.lyricsPanel && s.npPanel);
  const setLyricsPanel = useUi((s) => s.setLyricsPanel);
  const setPref = useUi((s) => s.setPref);
  const has = hasLyrics(q.data);
  const tip = on ? "Hide the lyrics" : has ? "Lyrics" : noLyrics(item, q);
  return (
    <button className={`ctl lyr-mic ${on ? "on" : ""} ${has || on ? "" : "dim"}`} aria-label="Lyrics" aria-pressed={on}
            aria-disabled={!has && !on} data-tip={tip}
            onClick={() => {
              if (on) setLyricsPanel(false);
              else if (has) {
                setPref("np_panel", true);
                setLyricsPanel(true);
              }
            }}>
      <MicVocal size={17} />
    </button>
  );
}
