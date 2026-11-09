/** Playback in the Muzix Android app. The app's own player (Android's Media3, in a service)
 * holds the next stretch of the queue and plays it, so songs go on with the screen off and the
 * lock screen, headset and car controls work. The engine hands its controls to this module the
 * way it does to a Cast speaker; the app reports back what plays and where (android/…/PlayerBridge.kt).
 * The app casts by itself too: every entry carries the signed link a speaker would play. */

import { sized } from "../api";
import { type Collection, type Downloaded, useDownloads } from "../downloads";
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
  onSaved(key: string): void;      // the app saved where an episode or audiobook was left, or that it was heard
}

interface AppState {
  key: string; position: number; duration: number; playing: boolean; buffering: boolean;
  seekable: boolean; ended: boolean; left: number;
}

const WINDOW = 100;    // songs handed over at a time
const TOP_UP = 20;     // hand over more when the app gets down to this many

class AppPlayer {
  readonly available = typeof window !== "undefined" && !!window.MuzixApp;
  private hooks: AppHooks | null = null;
  private connected = false;
  private state: AppState | null = null;
  private offset = 0;              // where the current song's stream started, when it was restarted at a time
  private handed = new Set<string>();
  private asked = "";              // the item we last started; one the app goes on to by itself starts at 0
  /** The app saves where episodes and audiobooks got to, and carries on in one heard partly, itself
   * (since 0.5.0): the page sleeps with the screen off, the app's player doesn't. */
  saves = false;
  /** The phone's own name (Settings → About phone), for the other devices' device pickers (since 0.7.0). */
  deviceName = "";
  /** Another device plays (player/connect.ts): the app's player is stopped, and what it says about itself doesn't count. */
  standby = false;
  /** The app downloads and installs a newer version of itself (since 0.8.0). */
  updates = false;

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
    useUi.subscribe((u, prev) => {
      if (this.connected && (u.quality !== prev.quality || u.radioBuffer !== prev.radioBuffer || u.autoplay !== prev.autoplay || u.browse !== prev.browse
        || u.downloadWifi !== prev.downloadWifi)) this.prefs();
    });
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

  /** This page as one of the account's devices (player/connect.ts), and its sound settings: the app keeps
   * the device's connection itself while the page is out of view and frozen (ConnectLink.kt, since 0.7.2). */
  tellDevice(hello: object) {
    this.send({ t: "device", hello });
  }

  private prefs() {
    const ui = useUi.getState();
    // autoplay: the app carries it on itself while the page is frozen (android/…/Autoplay.kt), a podcast's
    // next episode too, in the order its page is sorted: `oldest` are the podcasts sorted oldest first
    const oldest = Object.entries(ui.browse).filter(([k, b]) => k.startsWith("podcast:") && b?.sort === "oldest").map(([k]) => Number(k.slice(8)));
    this.send({ t: "prefs", quality: ui.quality, radioBuffer: ui.radioBuffer, autoplay: ui.autoplay, oldest, downloadWifi: ui.downloadWifi });
  }

  /** Back to the app's screen for the server's address. */
  changeServer() {
    this.send({ t: "server" });
  }

  /** A page of the server's web version, in the phone's browser: the app has no admin pages of its own. */
  openOnServer(path: string) {
    const url = location.origin + path;
    if (this.available) this.send({ t: "open", url });
    else window.open(url, "_blank", "noopener");
  }

  // ------------------------------------------------------------ downloads (downloads.ts)

  private onDownloads(list: Downloaded[], offline: boolean) {
    const was = useDownloads.getState();
    useDownloads.getState().set({ available: true, list, offline });
    // the server gone, or back: the page starts again from what it can reach
    if (was.available && was.offline !== offline) window.dispatchEvent(new Event("muzix:reachable"));
  }

  /** A collection onto the phone, in the format the device's settings ask for. */
  download(c: Collection) {
    const ui = useUi.getState();
    const items = c.items.map((it) => {
      const u = new URL(it.src, location.origin);
      if (ui.downloadFormat !== "original") u.searchParams.set("q", "high");
      return { key: it.key, url: u.toString(), title: it.title, artist: it.artist, album: it.album || "",
               duration: it.duration, muzix: JSON.stringify(slim(it)) };
    });
    this.send({ t: "download", collection: { ...c, items }, wifiOnly: ui.downloadWifi });
  }

  undownload(id: string) {
    this.send({ t: "undownload", id });
  }

  /** The page's sign-in state, which the app keeps to open offline. */
  signedIn(state: object) {
    this.send({ t: "signedIn", state });
  }

  /** A newer version of the app (appUpdate.ts): the app downloads it and opens Android's installer;
   * an older app, which can't, opens it in the browser, which downloads it. */
  update(url: string) {
    if (this.updates) this.send({ t: "update", url });
    else location.assign(url);
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
    if (it.kind === "episode") return true;     // an episode's stream is the file, whatever the quality
    if (useUi.getState().quality !== "original" || it.kind === "radio") return false;
    return it.castNative ?? it.kind === "book";
  }

  private item(it: PlayItem, token: string, from = 0) {
    const art = it.art ? new URL(sized(it.art, 600), location.origin).toString() : "";
    return {
      key: it.key, url: this.url(it, from), title: it.title, artist: it.artist, album: it.album || "", art,
      duration: it.kind === "radio" ? 0 : it.duration, offset: from, resume: it.resume ?? 0, muzix: JSON.stringify(slim(it)),
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

  /** The items from `start` on, as many as one handover takes. */
  private upcoming(start: number) {
    return usePlayer.getState().queue.slice(start, start + WINDOW);
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
    const items = this.upcoming(start);
    if (!items.length) return useUi.getState().notify("Nothing in the queue plays in the app");
    const into = at > 0.5 && items[0] === first ? at : 0;
    // the song that plays now says itself whether it can seek (a chip tune being rendered can't)
    const now = this.state?.key === items[0].key;
    const direct = now ? !!this.state?.seekable && !this.offset : this.direct(items[0]);
    this.offset = direct ? 0 : into;
    this.asked = items[0].key;
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
    const want = this.upcoming(s.index).slice(s.current() ? 1 : 0);
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

  /** The app starts an item it has from the beginning: one to carry on in (an episode left halfway)
   * is handed over again, starting there. */
  jump(index: number) {
    const it = usePlayer.getState().queue[index];
    const at = it?.resume ?? 0;
    if (it && this.handed.has(it.key) && at <= 0.5) {
      this.asked = it.key;
      this.send({ t: "jump", key: it.key });
    } else this.loadQueue(index, at);
  }

  next() {
    const s = usePlayer.getState();
    if (s.index + 1 < s.queue.length) this.jump(s.index + 1);
    else if (s.repeat === "all" && s.queue.length) this.loadQueue(0);
  }

  prev(always = false) {
    const s = usePlayer.getState();
    if ((s.position > 4 && !always) || s.index < 1) return this.seek(0);
    this.jump(s.index - 1);
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

  /** The phone's media volume (`level`, since 0.7.1: what the other devices' sliders show);
   * older apps set their player's own volume (`value`). */
  setVolume(volume: number, muted: boolean) {
    this.send({ t: "volume", value: muted ? 0 : volume ** 1.6, muted, level: volume });
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
    if (m.t === "hello") this.onHello(m as unknown as Parameters<AppPlayer["onHello"]>[0]);
    else if (this.standby && (m.t === "item" || m.t === "state" || m.t === "error")) return;
    else if (m.t === "item") this.onItem(m.key as string, (m.offset as number) || 0, m.muzix as string);
    else if (m.t === "state") this.onState(m as unknown as AppState);
    else if (m.t === "saved") this.hooks?.onSaved(m.key as string);
    else if (m.t === "volume") usePlayer.getState().set({ volume: m.value as number, muted: !!m.muted });
    else if (m.t === "queue") this.onQueue(m.queue as string[], m.index as number);
    else if (m.t === "downloads") this.onDownloads(m.list as Downloaded[], !!m.offline);
    else if (m.t === "cast") usePlayer.getState().set({ castState: m.state as CastState, castDevice: (m.device as string) || "" });
    else if (m.t === "error") {
      const msg = `Couldn't play ${(m.title as string) || "this"}`;
      useUi.getState().notify(msg, "error");
      report("media", `${msg} in the app: ${m.message as string}`);
    }
  }

  /** The app answered: it plays from now on. If it already plays something (the page was
   * reloaded), its queue becomes ours. */
  private onHello(m: { queue: string[]; index: number; state: AppState; saves?: boolean; device?: string; volume?: number; updates?: boolean;
                       downloads?: Downloaded[]; offline?: boolean }) {
    // an app that downloads (0.9 on) says what it has
    if (m.downloads) this.onDownloads(m.downloads, !!m.offline);
    // the phone's media volume is the volume here, before anything is sent to the app
    if (typeof m.volume === "number") usePlayer.getState().set({ volume: m.volume });
    this.connected = true;
    this.saves = !!m.saves;
    this.updates = !!m.updates;
    this.deviceName = m.device || "";
    this.prefs();
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

  /** Back in view: another device gave the app a new queue while the page was frozen; it's ours now. */
  private onQueue(carried: string[], index: number) {
    const queue = carried.map((j) => {
      try {
        return JSON.parse(j) as PlayItem;
      } catch {
        return null;
      }
    }).filter(Boolean) as PlayItem[];
    if (!queue.length) return;
    this.handed = new Set(queue.map((it) => it.key));
    usePlayer.getState().set({ queue, index: Math.max(0, Math.min(index, queue.length - 1)) });
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
    // gone on by itself (the last one ended, or the lock screen's next) to an episode heard halfway: on
    // from there (a newer app does it itself, as the page may only see it much later)
    const at = item.resume ?? 0;
    if (!this.saves && key !== this.asked && at > 0.5 && offset < 0.5) this.seek(at);
    this.asked = "";
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
    else if (st.left < TOP_UP && s.index + 1 < s.queue.length && this.upcoming(s.index).length - 1 > st.left) {
      this.syncUpcoming();      // the app nears the end of what it has
    }
  }
}

export const appPlayer = new AppPlayer();
