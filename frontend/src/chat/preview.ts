/** "More info"'s own little player: a linked album's songs, heard without touching the queue. What
 * Muzix played pauses while it plays and goes on when the box closes; if Muzix plays again meanwhile,
 * the preview stops instead. */

import { useCallback, useEffect, useRef, useState } from "react";
import { engine } from "../player/engine";
import { usePlayer } from "../store/player";
import { useUi } from "../store/ui";
import type { ChatSong } from "./store";

export interface Preview {
  index: number;            // the song it's on (-1: none yet)
  playing: boolean;
  loading: boolean;
  position: number;
  error: string;
  paused: boolean;          // it paused Muzix's own music, which goes on when the box closes
  play: (i: number) => void;
  toggle: () => void;
  step: (by: 1 | -1) => void;
  seek: (t: number) => void;
  /** The music goes to Muzix's player: where the preview got to, and nothing to resume on closing. */
  handOver: () => { index: number; position: number };
}

/** A song's address with the sound quality chosen in Settings and a start (as the player asks for them). */
function address(src: string, at: number) {
  const q = useUi.getState().quality;
  const p = new URLSearchParams();
  if (q !== "original") p.set("q", q);
  if (at > 0.5) p.set("t", at.toFixed(1));
  const s = p.toString();
  return s ? src + (src.includes("?") ? "&" : "?") + s : src;
}

export function usePreview(songs: ChatSong[]): Preview {
  const el = useRef<HTMLAudioElement | null>(null);
  const offset = useRef(0);          // a stream started part way in (t=): its time 0 is here
  const paused = useRef(false);
  const songsRef = useRef(songs);
  songsRef.current = songs;
  const [index, setIndex] = useState(-1);
  const indexRef = useRef(-1);
  const [playing, setPlaying] = useState(false);
  const [loading, setLoading] = useState(false);
  const [position, setPosition] = useState(0);
  const [error, setError] = useState("");
  const [pausedMain, setPausedMain] = useState(false);

  const quietMuzix = () => {
    if (usePlayer.getState().playing) {
      paused.current = true;
      setPausedMain(true);
      engine.toggle();
    }
  };

  const load = useCallback((i: number, at = 0) => {
    const a = el.current;
    const song = songsRef.current[i];
    if (!a || !song?.stream) return;
    offset.current = at;
    indexRef.current = i;
    setIndex(i);
    setPosition(at);
    setError("");
    setLoading(true);
    const { volume, muted } = usePlayer.getState();
    a.volume = volume;
    a.muted = muted;
    a.src = address(song.stream, at);
    quietMuzix();
    a.play().catch(() => {});
  }, []);

  const step = useCallback((by: 1 | -1) => {
    const list = songsRef.current;
    for (let i = indexRef.current + by; i >= 0 && i < list.length; i += by) {
      if (list[i].stream) return load(i);
    }
  }, [load]);

  useEffect(() => {
    const a = new Audio();
    a.preload = "auto";
    el.current = a;
    const time = () => setPosition(offset.current + a.currentTime);
    const on = () => { setPlaying(true); setLoading(false); };
    const off = () => setPlaying(false);
    const ended = () => { setPlaying(false); step(1); };
    const failed = () => { setLoading(false); setPlaying(false); if (a.getAttribute("src")) setError("This song can't be played right now"); };
    a.addEventListener("timeupdate", time);
    a.addEventListener("playing", on);
    a.addEventListener("pause", off);
    a.addEventListener("waiting", () => setLoading(true));
    a.addEventListener("ended", ended);
    a.addEventListener("error", failed);
    // Muzix plays again (its own buttons, a key): the preview gives way, and there's nothing to resume
    const stop = usePlayer.subscribe((s, before) => {
      if (s.playing && !before.playing && !a.paused) {
        a.pause();
        paused.current = false;
        setPausedMain(false);
      }
    });
    return () => {
      stop();
      a.pause();
      a.removeAttribute("src");
      a.load();
      if (paused.current && !usePlayer.getState().playing) engine.toggle();
    };
  }, [step]);

  const toggle = useCallback(() => {
    const a = el.current;
    if (!a) return;
    if (!a.getAttribute("src")) return step(1);
    if (a.paused) {
      quietMuzix();
      a.play().catch(() => {});
    } else a.pause();
  }, [step]);

  const seek = useCallback((t: number) => {
    const a = el.current;
    if (!a || indexRef.current < 0) return;
    const local = t - offset.current;
    const r = a.seekable;
    // a file as it is seeks in itself; a converted or rendered stream starts again from there
    if (local >= 0 && r.length && local <= r.end(r.length - 1)) a.currentTime = local;
    else load(indexRef.current, t);
  }, [load]);

  const handOver = useCallback(() => {
    el.current?.pause();
    paused.current = false;
    setPausedMain(false);
    return { index: Math.max(0, indexRef.current), position: indexRef.current >= 0 ? offset.current + (el.current?.currentTime || 0) : 0 };
  }, []);

  return { index, playing, loading, position, error, paused: pausedMain, play: load, toggle, step, seek, handOver };
}
