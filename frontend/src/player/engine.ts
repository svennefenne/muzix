/** Plays the queue: one <audio> element, a Web Audio analyser for the visualizer
 * and skin backdrops, and the bookkeeping around it (play counts, resume
 * positions, media keys, prefetching the next song's render). */

import { api } from "../api";
import { usePlayer, type PlayItem } from "../store/player";
import { useUi } from "../store/ui";
import { caster } from "./cast";
import { spotify } from "./spotify";

class Engine {
  el: HTMLAudioElement;
  ctx: AudioContext | null = null;
  analyser: AnalyserNode | null = null;
  private offset = 0;            // where a progressive stream started (seconds)
  private loadedKey = "";
  private scrobbled = false;
  private prefetched = "";
  private lastSave = 0;
  private radioTimer: number | undefined;
  private stallTimer: number | undefined;   // a station that stops delivering
  private radioRetries = 0;
  private steadyTimer: number | undefined;
  private freq: Uint8Array<ArrayBuffer> | null = null;

  constructor() {
    this.el = new Audio();
    this.el.preload = "auto";
    const el = this.el;
    el.addEventListener("timeupdate", () => this.onTime());
    el.addEventListener("playing", () => {
      usePlayer.getState().set({ playing: true, buffering: false, error: "" });
      window.clearTimeout(this.stallTimer);
      // a minute of steady radio earns the reconnects back
      window.clearTimeout(this.steadyTimer);
      this.steadyTimer = window.setTimeout(() => (this.radioRetries = 0), 60_000);
    });
    el.addEventListener("pause", () => usePlayer.getState().set({ playing: false }));
    el.addEventListener("waiting", () => {
      usePlayer.getState().set({ buffering: true });
      window.clearTimeout(this.steadyTimer);
      // radio that stalls this long gets a fresh connection
      if (usePlayer.getState().current()?.kind === "radio" && !caster.active) {
        window.clearTimeout(this.stallTimer);
        this.stallTimer = window.setTimeout(() => this.reconnectRadio(), 12_000);
      }
    });
    el.addEventListener("canplay", () => usePlayer.getState().set({ buffering: false }));
    el.addEventListener("ended", () => this.onEnded());
    el.addEventListener("error", () => this.onError());
    el.addEventListener("loadedmetadata", () => {
      const cur = usePlayer.getState().current();
      if (cur && !cur.duration && isFinite(el.duration)) usePlayer.getState().set({ duration: el.duration });
    });
    this.applyVolume();
    spotify.onEnded = () => this.next(true);
    // on a Cast speaker the speaker plays; we keep the books (plays, resume points, radio titles)
    caster.attach({
      onStart: () => {
        this.el.pause();
        spotify.pause();
      },
      onItem: (key) => {
        const item = usePlayer.getState().queue.find((i) => i.key === key);
        window.clearInterval(this.radioTimer);
        this.saveProgress();
        this.scrobbled = false;
        this.loadedKey = key;
        usePlayer.getState().set({ liveTitle: "", error: "" });
        if (item) {
          this.updateMediaSession(item);
          if (item.kind === "radio") this.pollRadio(item);
        }
      },
      onTime: (pos) => this.progress(pos),
      onEnd: (pos) => {
        usePlayer.getState().set({ playing: false, buffering: false });
        if (usePlayer.getState().current()) this.load(false, pos);
      },
    });
    caster.load();
    usePlayer.subscribe((s, prev) => {
      if (s.volume !== prev.volume || s.muted !== prev.muted) this.applyVolume();
      if (s.speed !== prev.speed) el.playbackRate = s.speed;
    });
    this.mediaSession();
  }

  // ------------------------------------------------------------ queue control

  play(items: PlayItem[], start = 0) {
    if (!items.length) return;
    usePlayer.getState().set({ queue: items, index: start });
    if (caster.active) return caster.loadQueue(start, items[start]?.resume ?? 0);
    this.load(true);
  }

  enqueue(items: PlayItem[], next = false) {
    const s = usePlayer.getState();
    if (s.index < 0) return this.play(items);
    const q = [...s.queue];
    q.splice(next ? s.index + 1 : q.length, 0, ...items);
    s.set({ queue: q });
    useUi.getState().notify(next ? `Playing next: ${items[0].title}` : `Added ${items.length > 1 ? items.length + " songs" : items[0].title} to the queue`);
    if (caster.active) caster.syncUpcoming();
  }

  jump(index: number) {
    usePlayer.getState().set({ index });
    if (caster.active) return caster.jump(index);
    this.load(true);
  }

  remove(index: number) {
    const s = usePlayer.getState();
    const q = s.queue.filter((_, i) => i !== index);
    let idx = s.index;
    if (index < idx) idx--;
    s.set({ queue: q, index: Math.min(idx, q.length - 1) });
    if (caster.active) return index === s.index ? caster.loadQueue(Math.min(idx, q.length - 1), 0, s.playing) : caster.syncUpcoming();
    if (index === s.index) this.load(s.playing);
  }

  move(from: number, to: number) {
    const s = usePlayer.getState();
    const q = [...s.queue];
    const [it] = q.splice(from, 1);
    q.splice(to, 0, it);
    let idx = s.index;
    if (from === idx) idx = to;
    else if (from < idx && to >= idx) idx--;
    else if (from > idx && to <= idx) idx++;
    s.set({ queue: q, index: idx });
    if (caster.active) caster.syncUpcoming();
  }

  clear() {
    if (caster.active) caster.stopMedia();
    this.stop();
    usePlayer.getState().set({ queue: [], index: -1, position: 0, duration: 0 });
  }

  toggle() {
    const cur = usePlayer.getState().current();
    if (!cur) return;
    if (caster.active) return caster.toggle();
    if (cur.kind === "spotify") return spotify.toggle();
    this.ensureAudioGraph();
    if (this.el.paused) {
      if (this.loadedKey !== cur.key) this.load(true);
      else this.el.play().catch(() => {});
    } else this.el.pause();
  }

  next(auto = false) {
    const s = usePlayer.getState();
    if (!s.queue.length) return;
    if (caster.active) return caster.next();
    if (auto && s.repeat === "one") return this.seek(0, true);
    let idx = s.index + 1;
    if (s.shuffle && s.queue.length > 1) {
      do idx = Math.floor(Math.random() * s.queue.length);
      while (idx === s.index);
    }
    if (idx >= s.queue.length) {
      if (s.repeat !== "all") {
        this.saveProgress(true);
        s.set({ playing: false });
        return;
      }
      idx = 0;
    }
    s.set({ index: idx });
    this.load(true);
  }

  prev() {
    if (caster.active) return caster.prev();
    const s = usePlayer.getState();
    if (s.position > 4 || s.index <= 0) return this.seek(0);
    s.set({ index: s.index - 1 });
    this.load(true);
  }

  stop() {
    window.clearTimeout(this.stallTimer);
    this.el.pause();
    this.el.removeAttribute("src");
    this.el.load();
    this.loadedKey = "";
    spotify.pause();
  }

  // ------------------------------------------------------------ loading & seeking

  private srcFor(item: PlayItem, at: number) {
    const q = useUi.getState().quality;
    const params = new URLSearchParams();
    if (q !== "original" && item.kind !== "radio") params.set("q", q);
    const cushion = useUi.getState().radioBuffer;
    if (item.kind === "radio" && cushion > 0) params.set("buffer", String(cushion));
    if (at > 0.5) params.set("t", at.toFixed(1));
    const s = params.toString();
    return s ? item.src + (item.src.includes("?") ? "&" : "?") + s : item.src;
  }

  private load(autoplay: boolean, at?: number) {
    const s = usePlayer.getState();
    const item = s.current();
    window.clearInterval(this.radioTimer);
    if (!item) return;
    this.saveProgress();
    this.scrobbled = false;
    this.prefetched = "";
    this.radioRetries = 0;
    window.clearTimeout(this.stallTimer);
    s.set({ position: at ?? item.resume ?? 0, duration: item.duration, liveTitle: "", error: "", buffering: autoplay });
    if (item.kind === "spotify") {
      this.el.pause();
      this.loadedKey = item.key;
      spotify.playItem(item);
      this.updateMediaSession(item);
      return;
    }
    spotify.pause();
    const start = at ?? item.resume ?? 0;
    this.offset = 0;
    this.loadedKey = item.key;
    this.el.src = this.srcFor(item, 0);
    this.el.playbackRate = item.kind === "book" || item.kind === "episode" ? s.speed : 1;
    if (start > 0.5) {
      // native files seek in place; streams that can't are restarted at the offset
      const once = () => {
        this.el.removeEventListener("loadedmetadata", once);
        this.seek(start, autoplay);
      };
      this.el.addEventListener("loadedmetadata", once);
    }
    if (autoplay) {
      this.ensureAudioGraph();
      this.el.play().catch(() => usePlayer.getState().set({ playing: false, buffering: false }));
    }
    if (item.kind === "radio") this.pollRadio(item);
    this.updateMediaSession(item);
    this.prefetchNext();
  }

  seek(t: number, play?: boolean) {
    const s = usePlayer.getState();
    const item = s.current();
    if (!item) return;
    if (item.kind === "spotify") return spotify.seek(t);
    if (item.kind === "radio") return;
    t = Math.max(0, item.duration ? Math.min(t, item.duration - 0.5) : t);
    if (caster.active) return caster.seek(t);
    const local = t - this.offset;
    const el = this.el;
    const canSeek = el.seekable.length > 0 && local >= 0 && el.seekable.end(el.seekable.length - 1) >= local - 1
      && isFinite(el.duration);
    if (canSeek) {
      el.currentTime = local;
    } else {
      const wasPlaying = play ?? !el.paused;
      this.offset = t;
      el.src = this.srcFor(item, t);
      if (wasPlaying) el.play().catch(() => {});
    }
    s.set({ position: t });
  }

  // ------------------------------------------------------------ events

  private onTime() {
    if (caster.active) return;
    const item = usePlayer.getState().current();
    if (!item || item.kind === "spotify") return;
    const pos = this.offset + this.el.currentTime;
    this.progress(pos, isFinite(this.el.duration) ? this.el.duration : 0);
    // chip renders are cut to length; a stream that runs over the planned time stops here
    if ((item.kind === "track" || item.kind === "online") && item.duration && pos > item.duration + 1.5) this.onEnded();
  }

  /** Bookkeeping as playback moves on, here or on a Cast speaker: plays, resume points, prefetch. */
  private progress(pos: number, mediaDuration = 0) {
    const s = usePlayer.getState();
    const item = s.current();
    if (!item || item.kind === "spotify") return;
    s.set({ position: pos });
    const dur = item.duration || mediaDuration;
    if (!this.scrobbled && item.kind === "track" && (pos > 30 || (dur && pos > dur / 2))) {
      this.scrobbled = true;
      api.post("/api/plays", { track_id: item.id }).catch(() => {});
    }
    if (Date.now() - this.lastSave > 10000) this.saveProgress();
    if (dur && dur - pos < 30) this.prefetchNext();
  }

  private onEnded() {
    if (caster.active) return;
    this.saveProgress(true);
    this.next(true);
  }

  /** A dropped or stalled station: connect again, a few times, before giving up. */
  private reconnectRadio(): boolean {
    const item = usePlayer.getState().current();
    if (!item || item.kind !== "radio" || this.radioRetries >= 3) return false;
    this.radioRetries++;
    usePlayer.getState().set({ buffering: true, error: "" });
    this.el.src = this.srcFor(item, 0);
    this.el.play().catch(() => {});
    return true;
  }

  private onError() {
    if (caster.active) return;
    const item = usePlayer.getState().current();
    if (!item || !this.el.getAttribute("src")) return;
    if (item.kind === "radio" && this.reconnectRadio()) return;
    const msg = item.kind === "radio" ? "The station isn't answering" : `Couldn't play ${item.title}`;
    usePlayer.getState().set({ error: msg, playing: false, buffering: false });
    useUi.getState().notify(msg, "error");
    if (item.kind === "track" || item.kind === "online") window.setTimeout(() => {
      if (usePlayer.getState().current()?.key === item.key) this.next(true);
    }, 2500);
  }

  private prefetchNext() {
    const s = usePlayer.getState();
    const next = s.queue[s.index + 1];
    if (!next || (next.kind !== "track" && next.kind !== "online") || this.prefetched === next.key) return;
    this.prefetched = next.key;
    // starts the render of chiptunes/trackers (and an online tune's download) so the next song starts at once
    fetch(next.src + (next.src.includes("?") ? "&" : "?") + "prefetch=1", { credentials: "same-origin" }).catch(() => {});
  }

  saveProgress(finished = false) {
    const s = usePlayer.getState();
    const item = s.queue.find((i) => i.key === this.loadedKey);
    if (!item) return;
    this.lastSave = Date.now();
    const pos = item.key === s.current()?.key ? s.position : 0;
    if (item.kind === "book" && item.bookId) {
      const total = (item.partOffset || 0) + pos;
      api.put(`/api/books/${item.bookId}/progress`, { position: total, finished: finished && isLastPart(item) }).catch(() => {});
    } else if (item.kind === "episode") {
      api.put(`/api/podcasts/episodes/${item.id}/progress`, { position: pos, finished }).catch(() => {});
    }
  }

  private pollRadio(item: PlayItem) {
    const url = item.album || "";
    const poll = () => api.get<{ title: string }>("/api/radio/nowplaying", { url }).then((r) => {
      if (usePlayer.getState().current()?.key === item.key && r.title !== usePlayer.getState().liveTitle) {
        usePlayer.getState().set({ liveTitle: r.title });
        this.updateMediaSession(item, r.title);
      }
    }).catch(() => {});
    window.setTimeout(poll, 4000);
    this.radioTimer = window.setInterval(poll, 15000);
  }

  // ------------------------------------------------------------ audio graph & levels

  ensureAudioGraph() {
    if (this.ctx) {
      if (this.ctx.state === "suspended") this.ctx.resume();
      return;
    }
    try {
      this.ctx = new AudioContext();
      const src = this.ctx.createMediaElementSource(this.el);
      this.analyser = this.ctx.createAnalyser();
      this.analyser.fftSize = 512;
      this.analyser.smoothingTimeConstant = 0.78;
      src.connect(this.analyser);
      this.analyser.connect(this.ctx.destination);
      this.freq = new Uint8Array(this.analyser.frequencyBinCount);
    } catch {
      this.ctx = null;
    }
  }

  /** Frequency data (0..255 per bin), or null when nothing is analysable. */
  spectrum(): Uint8Array | null {
    if (!this.analyser || !this.freq || this.el.paused) return null;
    this.analyser.getByteFrequencyData(this.freq);
    return this.freq;
  }

  /** 0..1 loudness with bass emphasis, for beat-reactive effects. */
  level(): { level: number; bass: number } {
    const f = this.spectrum();
    if (!f) return { level: 0, bass: 0 };
    let sum = 0;
    let bass = 0;
    for (let i = 0; i < f.length; i++) {
      sum += f[i];
      if (i < 12) bass += f[i];
    }
    return { level: sum / f.length / 255, bass: bass / 12 / 255 };
  }

  private applyVolume() {
    const s = usePlayer.getState();
    if (caster.active) return caster.setVolume(s.muted ? 0 : s.volume, s.muted);
    this.el.volume = s.muted ? 0 : s.volume ** 1.6;   // perceptual curve
    spotify.setVolume(s.muted ? 0 : s.volume);
  }

  // ------------------------------------------------------------ media keys

  private mediaSession() {
    if (!("mediaSession" in navigator)) return;
    const ms = navigator.mediaSession;
    ms.setActionHandler("play", () => this.toggle());
    ms.setActionHandler("pause", () => this.toggle());
    ms.setActionHandler("nexttrack", () => this.next());
    ms.setActionHandler("previoustrack", () => this.prev());
    ms.setActionHandler("seekto", (d) => d.seekTime !== undefined && this.seek(d.seekTime));
    ms.setActionHandler("seekforward", () => this.seek(usePlayer.getState().position + 15));
    ms.setActionHandler("seekbackward", () => this.seek(usePlayer.getState().position - 15));
  }

  private updateMediaSession(item: PlayItem, live = "") {
    if (!("mediaSession" in navigator)) return;
    const art = item.art ? [{ src: item.art.startsWith("/api/") ? item.art + "?s=600" : item.art, sizes: "600x600" }] : [];
    navigator.mediaSession.metadata = new MediaMetadata({
      title: live || item.title, artist: live ? item.title : item.artist, album: item.album || "", artwork: art,
    });
    document.title = `${live || item.title} · ${item.artist || useUi.getState().siteName}`;
  }
}

function isLastPart(item: PlayItem) {
  const s = usePlayer.getState();
  return !s.queue.some((i) => i.bookId === item.bookId && (i.partOffset || 0) > (item.partOffset || 0));
}

export const engine = new Engine();
