/** Playback in the Muzix Android app. The app's own player (Android's Media3, in a service)
 * holds the next stretch of the queue and plays it, so songs go on with the screen off and the
 * lock screen, headset and car controls work. The engine hands its controls to this module the
 * way it does to a Cast speaker; the app reports back what plays and where (android/…/PlayerBridge.kt).
 * The app casts by itself too: every entry carries the signed link a speaker would play. */

import { report } from "../components/ErrorBoundary";
import { usePlayer, type PlayItem } from "../store/player";
import { useUi } from "../store/ui";
import { type CastHooks, type CastState, type Slim, castLink, castMime, castUrl, shuffleUpcoming, slim } from "./cast";

interface Bridge {
  postMessage(data: string): void;
  addEventListener(type: "message", listener: (e: MessageEvent<string>) => void): void;
}

declare global {
  interface Window {
    MuzixApp?: Bridge;
  }
}

export interface AppHooks extends CastHooks {
  onFinish(): void;                // the queue played to its end
}

interface AppState {
  key: string; position: number; duration: number; playing: boolean; buffering: boolean;
  seekable: boolean; ended: boolean; left: number;
}

const WINDOW = 100;    // songs handed over at a time
const TOP_UP = 20;     // hand over more when the app gets down to this many

const playable = (it: PlayItem) => it.kind !== "spotify";

class AppPlayer {
  readonly available = typeof window !== "undefined" && !!window.MuzixApp;
  private hooks: AppHooks | null = null;
  private connected = false;
  private state: AppState | null = null;
  private offset = 0;              // where the current song's stream started, when it was restarted at a time
  private handed = new Set<string>();

  get active() {
    return this.connected;
  }

  attach(hooks: AppHooks) {
    this.hooks = hooks;
  }

  connect() {
    const app = window.MuzixApp;
    if (!app) return;
    app.addEventListener("message", (e) => this.onMessage(e.data));
    this.send({ t: "hello" });
    usePlayer.subscribe((s, prev) => {
      if (!this.connected) return;
      if (s.repeat !== prev.repeat) this.send({ t: "repeat", mode: s.repeat });
      if (s.speed !== prev.speed) this.speed();
      if (s.shuffle && !prev.shuffle) {
        shuffleUpcoming();
        this.syncUpcoming();
      }
    });
    // the status and navigation bars follow the skin's background
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) {
      const bars = () => this.send({ t: "bars", color: meta.getAttribute("content") || "" });
      new MutationObserver(bars).observe(meta, { attributes: true, attributeFilter: ["content"] });
      bars();
    }
  }

  /** Back to the app's screen for the server's address. */
  changeServer() {
    this.send({ t: "server" });
  }

  private send(msg: object) {
    window.MuzixApp?.postMessage(JSON.stringify(msg));
  }

  // ------------------------------------------------------------ handing the queue over

  private url(it: PlayItem, from: number) {
    const u = new URL(it.src, location.origin);
    const ui = useUi.getState();
    if (it.kind === "radio") {
      if (ui.radioBuffer > 0) u.searchParams.set("buffer", String(ui.radioBuffer));
    } else if (ui.quality !== "original") u.searchParams.set("q", ui.quality);
    if (from > 0.5) u.searchParams.set("t", from.toFixed(1));
    return u.toString();
  }

  /** Whether the app gets the file as it is, and can seek in it; converted streams start at a time instead. */
  private direct(it: PlayItem) {
    if (useUi.getState().quality !== "original" || it.kind === "radio") return false;
    return it.castNative ?? (it.kind === "book" || it.kind === "episode");
  }

  private item(it: PlayItem, token: string, from = 0) {
    const art = it.art ? new URL(it.art.startsWith("/api/") ? it.art + "?s=600" : it.art, location.origin).toString() : "";
    return {
      key: it.key, url: this.url(it, from), title: it.title, artist: it.artist, album: it.album || "", art,
      duration: it.kind === "radio" ? 0 : it.duration, offset: from, muzix: JSON.stringify(slim(it)),
      cast: castUrl(it, token, from), castMime: castMime(it), live: it.kind === "radio",
    };
  }

  private async token() {
    try {
      return await castLink();
    } catch {
      return "";        // no speaker links; playing on the phone doesn't need them
    }
  }

  /** The playable items from `start` on, as many as one handover takes. */
  private upcoming(start: number) {
    return usePlayer.getState().queue.slice(start).filter(playable).slice(0, WINDOW);
  }

  /** Starts the app on the queue at `start`, `at` seconds in. */
  async loadQueue(start: number, at = 0, autoplay = true) {
    const s = usePlayer.getState();
    if (start < 0) return;
    if (s.shuffle && start === s.index) {
      shuffleUpcoming();
      start = 0;
    }
    const first = usePlayer.getState().queue[start];
    if (first && !playable(first)) useUi.getState().notify("Spotify songs don't play in the app; skipping them");
    const items = this.upcoming(start);
    if (!items.length) return useUi.getState().notify("Nothing in the queue plays in the app");
    const into = at > 0.5 && items[0] === first ? at : 0;
    // the song that plays now says itself whether it can seek (a chip tune being rendered can't)
    const now = this.state?.key === items[0].key;
    const direct = now ? !!this.state?.seekable && !this.offset : this.direct(items[0]);
    this.offset = direct ? 0 : into;
    this.handed = new Set(items.map((it) => it.key));
    const token = await this.token();
    this.send({
      t: "load", index: 0, position: direct ? into : 0, play: autoplay,
      items: items.map((it, i) => this.item(it, token, i === 0 ? this.offset : 0)),
    });
    usePlayer.getState().set({ buffering: autoplay, error: "" });
  }

  /** Makes the app's upcoming songs match ours, without touching what plays now. */
  async syncUpcoming() {
    const s = usePlayer.getState();
    const want = this.upcoming(s.index).slice(s.current() && playable(s.current()!) ? 1 : 0);
    this.handed = new Set([s.current()?.key ?? "", ...want.map((it) => it.key)]);
    const token = await this.token();
    this.send({ t: "upcoming", items: want.map((it) => this.item(it, token)) });
  }

  /** The app's speaker picker (while casting: the speaker's volume and Stop casting). */
  chooseSpeaker() {
    this.send({ t: "cast" });
  }

  // ------------------------------------------------------------ controls

  toggle() {
    const s = usePlayer.getState();
    if (!this.state?.key) return this.loadQueue(s.index, s.position, true);
    this.send({ t: this.state.playing ? "pause" : "play" });
  }

  jump(index: number) {
    const key = usePlayer.getState().queue[index]?.key;
    if (key && this.handed.has(key)) this.send({ t: "jump", key });
    else this.loadQueue(index);
  }

  /** The nearest playable item from `from`, stepping by `step`; -1 if there's none. */
  private playableFrom(from: number, step: number) {
    const q = usePlayer.getState().queue;
    for (let i = from; i >= 0 && i < q.length; i += step) if (playable(q[i])) return i;
    return -1;
  }

  next() {
    const s = usePlayer.getState();
    const i = this.playableFrom(s.index + 1, 1);
    if (i >= 0) this.jump(i);
    else if (s.repeat === "all" && this.playableFrom(0, 1) >= 0) this.loadQueue(this.playableFrom(0, 1));
  }

  prev() {
    const s = usePlayer.getState();
    const i = this.playableFrom(s.index - 1, -1);
    if (s.position > 4 || i < 0) return this.seek(0);
    this.jump(i);
  }

  seek(t: number) {
    const s = usePlayer.getState();
    const cur = s.current();
    if (!cur || cur.kind === "radio") return;
    // files seek in the app; converted and rendered streams are restarted at the time
    if (this.direct(cur) && !this.offset && this.state?.seekable) this.send({ t: "seek", position: t });
    else this.loadQueue(s.index, t, s.playing);
    s.set({ position: t });
  }

  setVolume(volume: number, muted: boolean) {
    this.send({ t: "volume", value: muted ? 0 : volume ** 1.6 });
  }

  stopMedia() {
    this.send({ t: "stop" });
    this.handed.clear();
  }

  /** What a radio station plays now, for the lock screen. */
  meta(title: string, artist: string) {
    this.send({ t: "meta", title, artist });
  }

  private speed() {
    const s = usePlayer.getState();
    const spoken = s.current()?.kind === "book" || s.current()?.kind === "episode";
    this.send({ t: "speed", value: spoken ? s.speed : 1 });
  }

  // ------------------------------------------------------------ the app's side

  private onMessage(data: string) {
    let m: { t?: string } & Record<string, unknown>;
    try {
      m = JSON.parse(data);
    } catch {
      return;
    }
    if (m.t === "hello") this.onHello(m as unknown as { queue: string[]; index: number; state: AppState });
    else if (m.t === "item") this.onItem(m.key as string, (m.offset as number) || 0, m.muzix as string);
    else if (m.t === "state") this.onState(m as unknown as AppState);
    else if (m.t === "cast") usePlayer.getState().set({ castState: m.state as CastState, castDevice: (m.device as string) || "" });
    else if (m.t === "error") {
      const msg = `Couldn't play ${(m.title as string) || "this"}`;
      useUi.getState().notify(msg, "error");
      report("media", `${msg} in the app: ${m.message as string}`);
    }
  }

  /** The app answered: it plays from now on. If it already plays something (the page was
   * reloaded), its queue becomes ours. */
  private onHello(m: { queue: string[]; index: number; state: AppState }) {
    this.connected = true;
    this.hooks?.onStart();
    const s = usePlayer.getState();
    this.send({ t: "repeat", mode: s.repeat });
    const queue = m.queue.map((j) => {
      try {
        return JSON.parse(j) as Slim;
      } catch {
        return null;
      }
    }).filter(Boolean) as PlayItem[];
    if (queue.length && !s.queue.length) {
      s.set({ queue, index: Math.max(0, m.index) });
      this.handed = new Set(queue.map((it) => it.key));
      const cur = queue[Math.max(0, m.index)];
      if (cur) this.hooks?.onItem(cur.key);
    }
    this.onState(m.state);
  }

  private onItem(key: string, offset: number, carried: string) {
    this.offset = offset;
    const s = usePlayer.getState();
    let index = s.queue.findIndex((i) => i.key === key);
    if (index < 0) {
      try {
        s.set({ queue: [...s.queue, JSON.parse(carried) as PlayItem] });
        index = usePlayer.getState().queue.length - 1;
      } catch {
        return;
      }
    }
    const item = usePlayer.getState().queue[index];
    s.set({ index, duration: item.duration, position: offset });
    this.hooks?.onItem(key);
    this.speed();
  }

  private onState(st: AppState) {
    this.state = st;
    const s = usePlayer.getState();
    s.set({ playing: st.playing, buffering: st.buffering });
    if (!st.key) return;
    if (st.key === s.current()?.key) {
      if (!s.duration && st.duration) s.set({ duration: st.duration });
      this.hooks?.onTime(st.position);
    }
    if (st.ended) this.hooks?.onFinish();
    else if (st.left < TOP_UP && this.playableFrom(s.index + 1, 1) >= 0 && this.upcoming(s.index).length - 1 > st.left) {
      this.syncUpcoming();      // the app nears the end of what it has
    }
  }
}

export const appPlayer = new AppPlayer();
