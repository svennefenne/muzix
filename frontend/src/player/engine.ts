/** Plays the queue: two <audio> elements (one plays, the other holds the next song, so one
 * song follows another without a gap), a Web Audio analyser for the visualizer and skin
 * backdrops, and the bookkeeping around it (play counts, resume positions, media keys,
 * riding out a dropped connection, carrying on after a reload). */

import { api, sized } from "../api";
import { report } from "../components/ErrorBoundary";
import { fromEpisode, fromTrack, usePlayer, type PlayItem } from "../store/player";
import { useUi } from "../store/ui";
import type { Episode, Track, User } from "../types";
import { appPlayer } from "./app";
import { caster, type CastHooks } from "./cast";
import { spotify } from "./spotify";
import { onMobileData, onNetworkChange, stash } from "./stash";

/** What plays the queue instead of the page's own audio element: a Cast speaker, or the Android app's player. */
interface Remote {
  loadQueue(start: number, at?: number, autoplay?: boolean): unknown;
  syncUpcoming(): unknown;
  jump(index: number): unknown;
  toggle(): unknown;
  next(): void;
  prev(): void;
  seek(t: number): void;
  setVolume(volume: number, muted: boolean): void;
  stopMedia(): void;
}

/** What a reload (F5) carries on from, kept for this tab only. */
const KEPT_QUEUE = "muzix.queue";
const KEPT_AT = "muzix.at";

interface Kept { user: number; index: number; position: number; playing: boolean; remote: boolean; counted: boolean }

function keep(key: string, value: unknown) {
  try {
    sessionStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* full, or not allowed */
  }
}

function kept<T>(key: string): T | null {
  try {
    return JSON.parse(sessionStorage.getItem(key) || "null");
  } catch {
    return null;
  }
}

/** What the spare element can load ahead: files, not live radio or Spotify. */
const loadsAhead = (it: PlayItem) => it.kind !== "radio" && it.kind !== "spotify";

/** What's downloaded whole away from wifi: songs and episodes, not hours-long audiobook files. */
const stashable = (it: PlayItem) => loadsAhead(it) && it.duration <= 7200 && (it.duration > 0 || it.kind === "track" || it.kind === "online");

class Engine {
  el: HTMLAudioElement;          // the element that plays
  private spare: HTMLAudioElement;   // the next song, loaded and waiting
  private spareKey = "";
  private spareAt = 0;
  private spareRefused = false;  // the browser wouldn't start the spare by itself (iOS): one element it is
  private drawn = -1;            // shuffle's pick for the song after this one, drawn early so it can load
  ctx: AudioContext | null = null;
  analyser: AnalyserNode | null = null;
  private offset = 0;            // where a progressive stream started (seconds)
  private loadedKey = "";
  private scrobbled = false;
  private retryTimer: number | undefined;   // a song waiting for the connection to come back
  private lastSave = 0;
  private radioTimer: number | undefined;
  private stallTimer: number | undefined;   // a station that stops delivering
  private radioRetries = 0;
  private steadyTimer: number | undefined;
  private freq: Uint8Array<ArrayBuffer> | null = null;
  private copies = new Map<HTMLAudioElement, MediaStream>();   // each element's sound, copied for the analyser
  private copyTrack = "";
  private copySource: MediaStreamAudioSourceNode | null = null;
  private hiddenAt = 0;          // while the page is hidden (the screen off): since when, and what playback did
  private trace: string[] = [];
  private stalled = false;
  private lastEnd = 0;
  private lastTick = 0;
  private filling: Promise<boolean> | null = null;   // autoplay looking for more
  private askedNext = "";                              // the episode whose next one was asked for
  private reloaded = "";                               // the item a reload carries on with
  private held = "";                                   // the item the browser held back after a reload, till a click
  private woken = false;                               // a click just started it

  constructor() {
    // tells iOS this page plays music, so its audio keeps going with the screen off (Safari 17+)
    const session = (navigator as Navigator & { audioSession?: { type: string } }).audioSession;
    if (session) session.type = "playback";
    this.el = this.element();
    this.spare = this.element();
    document.addEventListener("visibilitychange", () => this.onVisibility());
    onNetworkChange(() => this.stashAhead());
    this.applyVolume();
    spotify.onEnded = () => this.next(true);
    // on a Cast speaker (or in the Android app) that plays; we keep the books (plays, resume points, radio titles)
    const hooks: CastHooks = {
      onStart: () => {
        this.el.pause();
        spotify.pause();
        this.dropSpare();
        this.stashAhead();
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
    };
    caster.attach(hooks);
    appPlayer.attach({
      ...hooks,
      onFinish: () => {
        this.saveProgress(true);
        usePlayer.getState().set({ playing: false, buffering: false });
        // autoplay found nothing in time: the app goes on once it has
        this.upNext()?.then((more) => {
          if (more) appPlayer.loadQueue(usePlayer.getState().index + 1);
        });
      },
    });
    caster.load();
    appPlayer.connect();
    usePlayer.subscribe((s, prev) => {
      if (s.volume !== prev.volume || s.muted !== prev.muted) this.applyVolume();
      if (s.speed !== prev.speed) this.el.playbackRate = s.speed;
      if (s.index !== prev.index || s.queue !== prev.queue || s.repeat !== prev.repeat || s.shuffle !== prev.shuffle) {
        this.upNext();
        this.stashAhead();
      }
    });
    useUi.subscribe((u, prev) => {
      if (u.autoplay === prev.autoplay) return;
      if (!u.autoplay) this.dropAutoplay();
      else if (this.autoplayDue()) this.fillAutoplay();
    });
    this.mediaSession();
    this.acrossReloads();
  }

  private get remote(): Remote | null {
    return caster.active ? caster : appPlayer.active ? appPlayer : null;
  }

  /** One of the two elements. What happens counts only from the one that plays. */
  private element() {
    const el = new Audio();
    el.preload = "auto";
    const on = (ev: string, fn: () => void) => el.addEventListener(ev, () => el === this.el && fn());
    // first, so they see the song that ended rather than the next one
    for (const ev of ["playing", "waiting", "stalled", "pause", "ended", "error"]) on(ev, () => this.note(ev));
    on("timeupdate", () => this.onTime());
    on("playing", () => {
      usePlayer.getState().set({ playing: true, buffering: false, error: "" });
      this.listen();
      window.clearTimeout(this.stallTimer);
      // a minute of steady radio earns the reconnects back
      window.clearTimeout(this.steadyTimer);
      this.steadyTimer = window.setTimeout(() => (this.radioRetries = 0), 60_000);
    });
    on("pause", () => usePlayer.getState().set({ playing: false }));
    on("waiting", () => this.onWaiting());
    on("canplay", () => usePlayer.getState().set({ buffering: false }));
    on("ended", () => this.onEnded());
    on("error", () => this.onError());
    on("loadedmetadata", () => {
      const cur = usePlayer.getState().current();
      if (cur && !cur.duration && isFinite(el.duration)) usePlayer.getState().set({ duration: el.duration });
    });
    return el;
  }

  // ------------------------------------------------------------ queue control

  play(items: PlayItem[], start = 0) {
    if (!items.length) return;
    usePlayer.getState().set({ queue: items, index: start });
    if (this.remote) return this.remote.loadQueue(start, items[start]?.resume ?? 0);
    this.load(true);
  }

  enqueue(items: PlayItem[], next = false) {
    const s = usePlayer.getState();
    if (s.index < 0) return this.play(items);
    const q = [...s.queue];
    q.splice(next ? s.index + 1 : q.length, 0, ...items);
    s.set({ queue: q });
    useUi.getState().notify(next ? `Playing next: ${items[0].title}` : `Added ${items.length > 1 ? items.length + " songs" : items[0].title} to the queue`);
    if (this.remote) this.remote.syncUpcoming();
  }

  jump(index: number) {
    usePlayer.getState().set({ index });
    if (this.remote) return this.remote.jump(index);
    this.load(true);
  }

  remove(index: number) {
    const s = usePlayer.getState();
    const q = s.queue.filter((_, i) => i !== index);
    let idx = s.index;
    if (index < idx) idx--;
    s.set({ queue: q, index: Math.min(idx, q.length - 1) });
    if (this.remote) return index === s.index ? this.remote.loadQueue(Math.min(idx, q.length - 1), 0, s.playing) : this.remote.syncUpcoming();
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
    if (this.remote) this.remote.syncUpcoming();
  }

  clear() {
    if (this.remote) this.remote.stopMedia();
    this.stop();
    usePlayer.getState().set({ queue: [], index: -1, position: 0, duration: 0 });
  }

  toggle() {
    const s = usePlayer.getState();
    const cur = s.current();
    if (!cur || this.woken) return;
    if (this.remote) return this.remote.toggle();
    if (this.loadedKey !== cur.key) return this.load(true, s.position || undefined);
    if (cur.kind === "spotify") return spotify.toggle();
    this.ensureAudioGraph();
    if (this.el.paused) this.el.play().catch(() => {});
    else this.el.pause();
  }

  next(auto = false) {
    const s = usePlayer.getState();
    if (!s.queue.length) return;
    if (this.remote) return this.remote.next();
    if (auto && s.repeat === "one") return this.again();
    let idx = s.shuffle && s.queue.length > 1 ? this.ahead(1)[0] : s.index + 1;
    if (idx >= s.queue.length) {
      if (s.repeat === "all") idx = 0;
      else {
        // the queue ran out: autoplay may still be finding what comes next
        const more = this.upNext();
        if (more) more.then((found) => (found ? this.next(auto) : this.finish()));
        else this.finish();
        return;
      }
    }
    s.set({ index: idx });
    this.load(true);
  }

  /** Repeat one: the song that ended starts over (and counts as played again). The element
   * stops at the end of a song, so seeking back alone leaves it paused. */
  private again() {
    const cur = usePlayer.getState().current();
    if (!cur) return;
    this.scrobbled = false;
    if (cur.kind === "spotify") return spotify.playItem({ ...cur, resume: 0 });
    this.seek(0, true);
    this.el.play().catch(() => {});
  }

  private finish() {
    this.saveProgress(true);
    usePlayer.getState().set({ playing: false });
  }

  prev() {
    if (this.remote) return this.remote.prev();
    const s = usePlayer.getState();
    if (s.position > 4 || s.index <= 0) return this.seek(0);
    s.set({ index: s.index - 1 });
    this.load(true);
  }

  stop() {
    window.clearTimeout(this.stallTimer);
    window.clearTimeout(this.retryTimer);
    this.el.pause();
    this.el.removeAttribute("src");
    this.el.load();
    this.loadedKey = "";
    this.dropSpare();
    spotify.pause();
  }

  // ------------------------------------------------------------ autoplay

  /** Spotify's autoplay: with the queue about to run out, similar songs join it, picked by the
   * genre tags of the songs you chose (game music: more from the same chips). Not while the
   * queue repeats, nor after audiobooks, podcasts or radio. Shuffling here never runs out. */
  private autoplayDue() {
    const s = usePlayer.getState();
    return useUi.getState().autoplay && s.repeat === "off" && !(s.shuffle && !this.remote)
      && s.current()?.kind === "track" && s.index >= s.queue.length - 2;
  }

  private fillAutoplay(): Promise<boolean> {
    if (this.filling) return this.filling;
    const s = usePlayer.getState();
    const played = s.queue.slice(0, s.index + 1).filter((it) => it.kind === "track");
    const chosen = played.filter((it) => !it.auto);
    const seeds = (chosen.length ? chosen : played).slice(-5).reverse().map((it) => it.id);
    if (!seeds.length) return Promise.resolve(false);
    const exclude = s.queue.filter((it) => it.kind === "track").map((it) => it.id);
    const at = s.current()?.key;
    const ask = api.post<Track[]>("/api/similar", { seeds, exclude, n: 10 }).then((found) => {
      const q = usePlayer.getState().queue;
      // not wanted any more: turned off, or other music started meanwhile
      if (!found.length || !useUi.getState().autoplay || !q.some((it) => it.key === at)) return false;
      usePlayer.getState().set({ queue: [...q, ...found.map((t) => ({ ...fromTrack(t), auto: true }))] });
      if (this.remote) this.remote.syncUpcoming();
      return true;
    }).catch(() => false).finally(() => {
      this.filling = null;
    });
    this.filling = ask;
    return ask;
  }

  /** Autoplay turned off: the songs it lined up go. */
  private dropAutoplay(feedId?: number) {
    const s = usePlayer.getState();
    const lined = (it: PlayItem) => it.auto && (feedId === undefined ? it.kind !== "episode" : it.feedId === feedId);
    const queue = s.queue.filter((it, i) => i <= s.index || !lined(it));
    if (queue.length === s.queue.length) return;
    s.set({ queue });
    if (this.remote) this.remote.syncUpcoming();
  }

  /** What comes once the queue runs out: similar songs, or the podcast's next episode. */
  private upNext(): Promise<boolean> | null {
    return this.filling ?? (this.autoplayDue() ? this.fillAutoplay() : this.episodeDue() ? this.fillEpisode() : null);
  }

  /** A podcast's own autoplay (switched on its page): the episode after this one in its list joins
   * the queue, in the order the page is sorted (a serial from the start, news from the top). */
  private episodeDue() {
    const s = usePlayer.getState();
    const cur = s.current();
    return cur?.kind === "episode" && !!cur.feedId && s.repeat === "off" && s.index >= s.queue.length - 1 && this.askedNext !== cur.key;
  }

  private fillEpisode(): Promise<boolean> {
    const cur = usePlayer.getState().current()!;
    this.askedNext = cur.key;
    const order = useUi.getState().browse[`podcast:${cur.feedId}`]?.sort === "oldest" ? "oldest" : "newest";
    const ask = api.get<{ next: Episode | null }>(`/api/podcasts/episodes/${cur.id}/next`, { order }).then(({ next }) => {
      const q = usePlayer.getState().queue;
      // not wanted any more (other things play), or in the queue already
      if (!next || !q.some((it) => it.key === cur.key) || q.some((it) => it.key === `episode:${next.id}`)) return false;
      usePlayer.getState().set({ queue: [...q, { ...fromEpisode(next), auto: true }] });
      if (this.remote) this.remote.syncUpcoming();
      return true;
    }).catch(() => false).finally(() => {
      this.filling = null;
    });
    this.filling = ask;
    return ask;
  }

  /** A podcast's autoplay switched: its next episode joins the queue now, or the one it lined up goes. */
  podcastAutoplay(feedId: number, on: boolean) {
    if (!on) return this.dropAutoplay(feedId);
    this.askedNext = "";
    this.upNext();
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
    const reloaded = this.reloaded === item.key;
    this.reloaded = "";
    this.saveProgress();
    this.scrobbled = false;
    this.radioRetries = 0;
    window.clearTimeout(this.stallTimer);
    window.clearTimeout(this.retryTimer);
    s.set({ position: at ?? item.resume ?? 0, duration: item.duration, liveTitle: "", error: "", buffering: autoplay });
    if (item.kind === "spotify") {
      this.el.pause();
      this.loadedKey = item.key;
      spotify.playItem(at === undefined ? item : { ...item, resume: at });
      this.updateMediaSession(item);
      return;
    }
    spotify.pause();
    const start = at ?? item.resume ?? 0;
    this.offset = 0;
    this.loadedKey = item.key;
    // the next song, loaded while the last one played, takes over without a gap
    const ahead = this.spareKey === item.key && start < 0.5 && !this.spareRefused && !this.spare.error;
    if (ahead) this.swap();
    else {
      this.dropSpare();
      this.el.src = stash.url(item.key) ?? this.srcFor(item, 0);
    }
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
      this.el.play().catch((e) => {
        usePlayer.getState().set({ playing: false, buffering: false });
        if (e?.name !== "NotAllowedError") return;
        // after a reload the browser may want a click first
        if (reloaded) return this.playOnTouch(item.key);
        // a browser that only lets an element play that was started by a tap (iOS): back to the one
        // that played, which loads each song itself from now on
        if (ahead) {
          this.spareRefused = true;
          this.swap();
          return this.load(true);
        }
        // a phone may refuse to start the next song while the screen is off
        this.stalled = true;
        this.note("refused to start");
        report("media", `The browser wouldn't start ${item.title}: ${e.message}`);
      });
    }
    if (item.kind === "radio") this.pollRadio(item);
    this.updateMediaSession(item);
    this.stashAhead();
  }

  // ------------------------------------------------------------ the next song, ahead of time

  /** The items that play after this one, as far as `n` (shuffle knows only its next pick). */
  private ahead(n: number): number[] {
    const s = usePlayer.getState();
    if (s.index < 0) return [];
    if (s.shuffle && s.queue.length > 1) {
      if (this.drawn < 0 || this.drawn >= s.queue.length || this.drawn === s.index) {
        do this.drawn = Math.floor(Math.random() * s.queue.length);
        while (this.drawn === s.index);
      }
      return [this.drawn];
    }
    const out: number[] = [];
    for (let i = s.index + 1; out.length < n; i++) {
      if (i >= s.queue.length) {
        if (s.repeat !== "all") break;
        i = 0;
      }
      if (i === s.index) break;
      out.push(i);
    }
    return out;
  }

  /** The next song loads into the spare element while this one plays, and takes over the moment
   * this one ends. That also starts a chip tune's render, or an online tune's download. */
  private readyNext() {
    const s = usePlayer.getState();
    const next = s.repeat === "one" ? undefined : s.queue[this.ahead(1)[0] ?? -1];
    if (!next || this.remote || this.spareRefused || !loadsAhead(next) || (next.resume ?? 0) > 0.5) return;
    const whole = stash.url(next.key);
    // loaded already, unless the whole file has come since; one that failed (no connection) tries again now and then
    if (this.spareKey === next.key && (!whole || this.spare.src === whole) && (!this.spare.error || Date.now() - this.spareAt < 5000)) return;
    this.spareKey = next.key;
    this.spareAt = Date.now();
    this.spare.src = whole ?? this.srcFor(next, 0);
  }

  /** The spare plays from now on; the element that played waits for the song after. */
  private swap() {
    const done = this.el;
    this.el = this.spare;
    this.spare = done;
    this.spareKey = "";
    done.pause();
    done.removeAttribute("src");
    done.load();
    this.applyVolume();
    this.listen();
  }

  private dropSpare() {
    this.spareKey = "";
    if (!this.spare.getAttribute("src")) return;
    this.spare.removeAttribute("src");
    this.spare.load();
  }

  /** Away from wifi: the song that plays and the next two, downloaded whole (player/stash.ts). */
  private stashAhead() {
    const s = usePlayer.getState();
    const keep = [this.loadedKey, this.spareKey];
    if (this.remote || !onMobileData() || s.index < 0) return stash.set([], keep);
    const items = [s.index, ...this.ahead(2)].map((i) => s.queue[i]).filter((it) => it && stashable(it));
    stash.set(items.map((it) => ({ key: it.key, url: this.srcFor(it, 0) })), keep);
  }

  seek(t: number, play?: boolean) {
    const s = usePlayer.getState();
    const item = s.current();
    if (!item) return;
    if (item.kind === "spotify") return spotify.seek(t);
    if (item.kind === "radio") return;
    t = Math.max(0, item.duration ? Math.min(t, item.duration - 0.5) : t);
    if (this.remote) return this.remote.seek(t);
    const local = t - this.offset;
    const el = this.el;
    const whole = el.src.startsWith("blob:");
    const canSeek = whole || (el.seekable.length > 0 && local >= 0 && el.seekable.end(el.seekable.length - 1) >= local - 1
      && isFinite(el.duration));
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
    if (this.remote) return;
    const item = usePlayer.getState().current();
    if (!item || item.kind === "spotify") return;
    const pos = this.offset + this.el.currentTime;
    const now = Date.now();
    if (this.hiddenAt && this.lastTick && now - this.lastTick > 10_000 && !this.el.paused) {
      this.stalled = true;
      this.note(`no progress for ${Math.round((now - this.lastTick) / 1000)}s`);
    }
    this.lastTick = now;
    this.progress(pos, isFinite(this.el.duration) ? this.el.duration : 0);
    // chip renders are cut to length; a stream that runs over the planned time stops here
    if ((item.kind === "track" || item.kind === "online") && item.duration && pos > item.duration + 1.5) this.onEnded();
  }

  /** Bookkeeping as playback moves on, here or on a Cast speaker: plays, resume points, the next song. */
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
    if (dur && dur - pos < 45 && !this.remote) this.readyNext();
  }

  private onEnded() {
    if (this.remote) return;
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
    if (this.remote) return;
    const item = usePlayer.getState().current();
    if (!item || !this.el.getAttribute("src")) return;
    if (item.kind === "radio") return this.failed(item);
    // the connection dropped: the downloaded copy plays on, or the song waits for the connection
    const lost = () => this.rescue() || this.awaitConnection(item);
    if (this.el.error?.code === MediaError.MEDIA_ERR_NETWORK) return lost();
    // a song that wouldn't start says only that it couldn't (Chrome): the file, or the connection?
    const err = this.el.error;
    const src = this.el.currentSrc;
    reachable().then((up) => {
      if (usePlayer.getState().current()?.key !== item.key) return;
      if (up) this.failed(item, err, src);
      else lost();
    });
  }

  private failed(item: PlayItem, err = this.el.error, src = this.el.currentSrc) {
    if (item.kind === "radio" && this.reconnectRadio()) return;
    const msg = item.kind === "radio" ? "The station isn't answering" : `Couldn't play ${item.title}`;
    usePlayer.getState().set({ error: msg, playing: false, buffering: false });
    useUi.getState().notify(msg, "error");
    report("media", `${msg}: media error ${err?.code ?? "?"} ${err?.message || ""}`, `\n${src}`);
    if (item.kind === "track" || item.kind === "online") window.setTimeout(() => {
      if (usePlayer.getState().current()?.key === item.key) this.next(true);
    }, 2500);
  }

  // ------------------------------------------------------------ a dropped connection

  /** The music ran dry. Radio that stays silent gets a fresh connection; a song with a copy
   * downloaded ahead plays on from it; a song that stops halfway for long is started again
   * where it stopped (a connection that hung). */
  private onWaiting() {
    const item = usePlayer.getState().current();
    usePlayer.getState().set({ buffering: true });
    window.clearTimeout(this.steadyTimer);
    if (!item || this.remote) return;
    window.clearTimeout(this.stallTimer);
    if (item.kind === "radio") this.stallTimer = window.setTimeout(() => this.reconnectRadio(), 12_000);
    else if (!this.rescue() && this.el.currentTime > 0) {
      this.stallTimer = window.setTimeout(() => usePlayer.getState().current()?.key === item.key && this.awaitConnection(item), 20_000);
    }
  }

  /** Over to the copy downloaded ahead, at the same spot. */
  private rescue(): boolean {
    const cur = usePlayer.getState().current();
    const whole = cur && stash.url(cur.key);
    if (!whole || this.el.src === whole) return false;
    const at = this.offset + this.el.currentTime;
    const el = this.el;
    this.offset = 0;
    el.src = whole;
    el.addEventListener("loadedmetadata", () => (el.currentTime = at), { once: true });
    el.play().catch(() => {});
    this.note("over to the downloaded copy");
    return true;
  }

  /** No connection and no copy: the song waits, and carries on where it stopped once the
   * connection is back (out of a tunnel, say), instead of skipping song after song. */
  private awaitConnection(item: PlayItem) {
    const s = usePlayer.getState();
    const at = s.position;
    const counted = this.scrobbled;
    s.set({ buffering: true, error: "Waiting for the connection…" });
    window.clearTimeout(this.retryTimer);
    const again = () => {
      window.removeEventListener("online", again);
      window.clearTimeout(this.retryTimer);
      if (usePlayer.getState().current()?.key !== item.key || this.remote) return;
      this.load(true, at);
      this.scrobbled = counted;
      usePlayer.getState().set({ error: "Waiting for the connection…" });   // till it plays
    };
    window.addEventListener("online", again);
    this.retryTimer = window.setTimeout(again, 5000);
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

  // ------------------------------------------------------------ across a reload

  /** The queue, and where it stood, are kept for this tab: after a reload (F5) the music carries
   * on from there, playing if it played. Not in the app: its own player plays on through a reload. */
  private acrossReloads() {
    if (appPlayer.available) return;
    const queue = kept<{ user: number; queue: PlayItem[] }>(KEPT_QUEUE);
    const at = kept<Kept>(KEPT_AT);
    const start = (user: User) => {
      this.carryOn(user, queue, at);
      let last = 0;
      const where = () => {
        const s = usePlayer.getState();
        last = Date.now();
        const playing = s.playing || s.buffering || this.held === s.current()?.key;
        keep(KEPT_AT, { user: user.id, index: s.index, position: s.position, playing, remote: !!this.remote,
                        counted: this.scrobbled } satisfies Kept);
      };
      usePlayer.subscribe((s, prev) => {
        if (s.queue !== prev.queue) keep(KEPT_QUEUE, { user: user.id, queue: s.queue });
        if (s.index !== prev.index || s.playing !== prev.playing || Date.now() - last > 3000) where();
      });
      window.addEventListener("pagehide", where);
      document.addEventListener("visibilitychange", () => document.hidden && where());
    };
    // once signed in: the streams need it, and the sound quality is a preference
    const user = useUi.getState().user;
    if (user) return start(user);
    const off = useUi.subscribe((u) => {
      if (!u.user) return;
      off();
      start(u.user);
    });
  }

  private carryOn(user: User, saved: { user: number; queue: PlayItem[] } | null, at: Kept | null) {
    const s = usePlayer.getState();
    const item = at && saved?.queue[at.index];
    if (!item || saved.user !== user.id || at.user !== user.id || s.queue.length) return;
    const pos = item.kind === "radio" ? 0 : at.position;
    s.set({ queue: saved.queue, index: at.index });
    // a speaker that played may still play: it says what (player/cast.ts), and the queue is in place meanwhile
    const here = !at.remote && !this.remote;
    if (here && at.playing) {
      this.reloaded = item.key;
      this.load(true, pos);
    } else if (here && item.kind !== "radio" && item.kind !== "spotify") this.load(false, pos);
    else {
      s.set({ position: pos, duration: item.duration });
      this.updateMediaSession(item);
    }
    this.scrobbled = at.counted;
  }

  /** The browser wouldn't play without being clicked first: the first click or key press carries
   * on. A click on play itself doesn't then pause it again. */
  private playOnTouch(key: string) {
    const ask = "The browser held the music back after the reload: click anywhere to carry on";
    const stop = () => {
      this.held = "";
      if (useUi.getState().toast?.text === ask) useUi.setState({ toast: null });
      window.removeEventListener("click", go, true);
      window.removeEventListener("keydown", go, true);
    };
    const go = () => {
      const s = usePlayer.getState();
      if (s.current()?.key !== key || s.playing || this.remote) return stop();
      this.woken = true;
      window.setTimeout(() => (this.woken = false));
      this.ensureAudioGraph();
      this.el.play().then(stop, () => {});
    };
    this.held = key;
    window.addEventListener("click", go, true);
    window.addEventListener("keydown", go, true);
    useUi.getState().notify(ask, "info", { label: "Play", run: go });
  }

  // ------------------------------------------------------------ while the screen is off

  /** Playback while the page is hidden is traced; a stall in it goes to the server's log. */
  private onVisibility() {
    if (document.hidden) {
      this.hiddenAt = Date.now();
      this.trace = [];
      this.stalled = false;
      this.lastEnd = 0;
      return;
    }
    // iOS may have stopped the audio graph the music plays through (no captureStream there)
    if (this.ctx && this.ctx.state !== "running" && !this.el.paused) this.ctx.resume().catch(() => {});
    // a song ended and the next never started, the music went silent, or playback stopped moving
    if (this.hiddenAt && (this.stalled || (this.lastEnd && !this.el.ended))) {
      const away = Math.round((Date.now() - this.hiddenAt) / 1000);
      report("background", `Playback stalled while the page was hidden (${away}s)`, `\n${this.trace.join("\n")}`);
    }
    this.hiddenAt = 0;
  }

  private note(what: string) {
    if (!this.hiddenAt) return;
    const now = Date.now();
    if (what === "ended") this.lastEnd = now;
    if (what === "playing") {
      if (this.lastEnd && now - this.lastEnd > 5000) this.stalled = true;
      this.lastEnd = 0;
      this.lastTick = now;
    }
    if (this.trace.length < 40) {
      const item = usePlayer.getState().current();
      this.trace.push(`+${Math.round((now - this.hiddenAt) / 1000)}s ${what}: ${item?.title ?? "?"} at ${Math.round(this.offset + this.el.currentTime)}s`);
    }
  }

  // ------------------------------------------------------------ audio graph & levels

  /** The analyser behind the visualizer. Where the browser can copy the element's sound
   * (captureStream), the analyser listens to the copy and the element plays to the speakers
   * itself: a phone that pauses Web Audio with the screen off then doesn't stop the music.
   * Elsewhere (Safari, so every iPhone and iPad) the element plays through the audio graph,
   * which the "playback" audio session keeps running with the screen off. */
  ensureAudioGraph() {
    if (this.ctx) {
      if (this.ctx.state !== "running") this.ctx.resume().catch(() => {});   // iOS also has "interrupted"
      return;
    }
    try {
      const ctx = new AudioContext();
      this.ctx = ctx;
      this.analyser = ctx.createAnalyser();
      this.analyser.fftSize = 512;
      this.analyser.smoothingTimeConstant = 0.78;
      this.freq = new Uint8Array(this.analyser.frequencyBinCount);
      ctx.addEventListener("statechange", () => {
        this.note(`audio graph ${ctx.state}`);
        // the music itself plays through the graph here: stopping it silenced the music
        if (this.hiddenAt && !this.copies.size && ctx.state !== "running" && !this.el.paused) this.stalled = true;
      });
      const els = [this.el, this.spare] as (HTMLAudioElement & { captureStream?: () => MediaStream })[];
      if (typeof els[0].captureStream === "function") {
        for (const el of els) {
          const copy = el.captureStream!();
          copy.addEventListener("addtrack", () => this.listen());
          this.copies.set(el, copy);
        }
        const silent = ctx.createGain();
        silent.gain.value = 0;
        this.analyser.connect(silent).connect(ctx.destination);   // keeps the analyser running
        this.listen();
      } else {
        for (const el of els) ctx.createMediaElementSource(el).connect(this.analyser);
        this.analyser.connect(ctx.destination);
      }
    } catch {
      this.ctx = null;
    }
  }

  /** Points the analyser at the playing element's newest audio track: every song brings one, and
   * Chrome leaves the old ones in the stream, silent. */
  private listen() {
    const copy = this.copies.get(this.el);
    if (!this.ctx || !copy || !this.analyser) return;
    const tracks = copy.getAudioTracks();
    const track = tracks.at(-1);
    for (const old of tracks.slice(0, -1)) {
      copy.removeTrack(old);
      old.stop();
    }
    if (!track || track.id === this.copyTrack) return;
    this.copySource?.disconnect();
    this.copyTrack = track.id;
    this.copySource = this.ctx.createMediaStreamSource(new MediaStream([track]));
    this.copySource.connect(this.analyser);
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
    if (this.remote) return this.remote.setVolume(s.muted ? 0 : s.volume, s.muted);
    for (const el of [this.el, this.spare]) el.volume = s.muted ? 0 : s.volume ** 1.6;   // perceptual curve
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
    const art = item.art ? [{ src: sized(item.art, 600), sizes: "600x600" }] : [];
    if (live && appPlayer.active) appPlayer.meta(live, item.title);
    navigator.mediaSession.metadata = new MediaMetadata({
      title: live || item.title, artist: live ? item.title : item.artist, album: item.album || "", artwork: art,
    });
    document.title = `${live || item.title} · ${item.artist || useUi.getState().siteName}`;
  }
}

/** Whether Muzix answers: a song that won't start may just be out of reach. */
function reachable() {
  return fetch("/api/health", { cache: "no-store", signal: AbortSignal.timeout(8000) }).then((r) => r.ok, () => false);
}

function isLastPart(item: PlayItem) {
  const s = usePlayer.getState();
  return !s.queue.some((i) => i.bookId === item.bookId && (i.partOffset || 0) > (item.partOffset || 0));
}

export const engine = new Engine();
