/** Muzix Connect, as with Spotify: this page is one of the account's devices (backend/muzix/api/connect.py).
 * While another device plays, this one follows it: the queue and what plays are that device's, shown
 * here, and the controls here go to it (the engine hands them to this module the way it does to a
 * Cast speaker). Choosing a device moves the music there, where it was.
 *
 * An app that shows its own library (this phone's or this computer's music) is a device too, but a queue
 * moves only between devices that show the same library: a song's address is another song in another
 * library. Another library's songs are shown here without their covers, likes or links. */

import { create } from "zustand";
import { type PlayItem, type Repeat, usePlayer } from "../store/player";
import { appPlayer, useShell } from "./app";
import { mayPlace, place } from "./last";

export interface Device { id: string; name: string; kind: "browser" | "app"; library?: "server" | "local" }

/** The library a device plays from, as the states say it: the server's, or that device's own. */
export function libraryOf(d: Device) {
  return d.library === "local" ? `local:${d.id}` : "server";
}

/** Another library's song, as this page shows it: no cover, nothing that would find another song here. */
function foreign(it: PlayItem): PlayItem {
  return { ...it, art: null, albumId: null, artistId: null, liked: false, foreign: true };
}

interface DeviceState {
  devices: Device[];
  active: string;          // the device that plays ("" when none does)
  you: string;
  online: boolean;
}

/** The account's devices online, for the device picker. */
export const useDevices = create<DeviceState>(() => ({ devices: [], active: "", you: "", online: false }));

/** What the device that plays tells the others. */
interface Shared {
  queue?: PlayItem[];
  index: number; position: number; duration: number;
  playing: boolean; buffering: boolean; shuffle: boolean; repeat: Repeat;
  volume?: number; muted?: boolean;
  library?: string;           // the queue's: "server", or "local:<device id>" (none from an older app: the server's)
}

export interface Command {
  cmd: "play" | "pause" | "next" | "prev" | "seek" | "jump" | "load" | "queue" | "volume" | "repeat" | "shuffle" | "stop";
  [arg: string]: unknown;
}

export interface ConnectHooks {
  onFollow(): void;                         // another device plays: this one goes quiet
  onItem(key: string): void;                // it went on to another item
  onUnfollow(position: number): void;       // nothing plays there any more: back here, paused
  onTakeover(position: number, play: boolean): void;   // this device plays the queue from here on
  onCommand(c: Command): void;              // for the device that plays (this one)
}

const SPOT = "muzix.device";

/** This tab (a browser's tabs are devices of their own), or the app: kept through reloads. The app says
 * its own (Android 0.10.17, Muzix Desktop 0.4.16 on): a phone's page has a storage for each address of the
 * server, and a page's storage is written a while later, so a restart could make it another device. */
function deviceId() {
  if (appPlayer.deviceId) return appPlayer.deviceId;
  const store = appPlayer.available ? localStorage : sessionStorage;
  try {
    const known = store.getItem(SPOT);
    if (known) return known;
    const id = Array.from({ length: 4 }, () => Math.random().toString(36).slice(2, 8)).join("");
    store.setItem(SPOT, id);
    return id;
  } catch {
    return Math.random().toString(36).slice(2);
  }
}

/** "Chrome on Linux", or the phone's own name in the app. */
function deviceName() {
  if (appPlayer.available) return appPlayer.deviceName || "Muzix app";
  const ua = navigator.userAgent;
  const browser = /Edg\//.test(ua) ? "Edge" : /Firefox\//.test(ua) ? "Firefox" : /Chrome\//.test(ua) ? "Chrome"
    : /Safari\//.test(ua) ? "Safari" : "A browser";
  const os = /Android/.test(ua) ? "Android" : /iPhone|iPad/.test(ua) ? "iOS" : /Windows/.test(ua) ? "Windows"
    : /Mac OS X/.test(ua) ? "macOS" : /CrOS/.test(ua) ? "ChromeOS" : /Linux/.test(ua) ? "Linux" : "";
  return os ? `${browser} on ${os}` : browser;
}

const SAME = ["index", "playing", "buffering", "duration", "shuffle", "repeat", "volume", "muted"] as const;

class Connect {
  private hooks: ConnectHooks | null = null;
  private ws: WebSocket | null = null;
  private wanted = false;
  private retry = 0;
  private retryTimer = 0;
  private awayTimer = 0;
  private id = "";
  /** Another device plays, and this one follows it. */
  following = false;
  private applying = false;        // a state from the device that plays being put in place
  private sentQueue: PlayItem[] | null = null;
  private lastSent = { position: 0, at: 0 };
  private heard = { position: 0, at: 0 };   // the position it told last, and when
  private turned = 0;              // when the volume was changed here: what comes back meanwhile is older
  private claimed = 0;             // when this device took the music over by itself (a speaker chosen here)
  private fresh = false;           // connected just now: the server's word on who plays not heard yet
  private idleTimer = 0;
  private publishing = false;
  private parked = false;          // in the app, out of view: the app has the device's connection
  private silence = 0;             // back in view, a sync asked for: no answer, and the connection was dead
  private theirs = "server";       // the library of what the device that plays plays
  private originals = new Map<string, PlayItem>();   // another library's songs as they came, by key

  get active() {
    return this.following;
  }

  /** The library this device shows. */
  mine() {
    return useShell.getState().library === "local" ? `local:${this.id || deviceId()}` : "server";
  }

  /** The library of the queue the device picker would move: what plays there, or here. */
  queueLibrary() {
    return this.following ? this.theirs : this.mine();
  }

  /** Whether what's chosen here can go to the device that plays: it shows the same library. */
  sameLibrary() {
    return !this.following || this.theirs === this.mine();
  }

  attach(hooks: ConnectHooks) {
    this.hooks = hooks;
    usePlayer.subscribe((s, prev) => {
      if (this.applying) return;
      if (this.following) {
        // the controls here that aren't the engine's: repeat and shuffle
        if (s.repeat !== prev.repeat) this.command({ cmd: "repeat", mode: s.repeat });
        if (s.shuffle !== prev.shuffle) this.command({ cmd: "shuffle", on: s.shuffle });
        return;
      }
      const since = (Date.now() - this.lastSent.at) / 1000;
      const moved = Math.abs(s.position - (this.lastSent.position + (s.playing ? since : 0))) > 3;
      // every few seconds while it plays too, on the player's own news: timers wait long in a page out of view
      const due = s.playing && s.position !== prev.position && since > 10;
      if (s.queue !== prev.queue || SAME.some((k) => s[k] !== prev[k]) || moved || due) this.publishSoon();
    });
    // the position carried on while it plays there (it tells every few seconds)
    window.setInterval(() => {
      const s = usePlayer.getState();
      if (!this.following || !s.playing || s.buffering) return;
      this.applying = true;
      s.set({ position: this.heard.position + (Date.now() - this.heard.at) / 1000 });
      this.applying = false;
    }, 1000);
    // and what plays here, every so often, for the others' positions
    window.setInterval(() => {
      const s = usePlayer.getState();
      if (!this.following && s.playing) this.publish();
    }, 10_000);
  }

  /** Signed in: this page joins the account's devices. */
  start() {
    if (this.wanted) return;
    this.wanted = true;
    this.id = deviceId();
    this.open();
    window.addEventListener("online", () => this.reconnectNow());
    document.addEventListener("visibilitychange", () => (document.hidden ? this.park() : this.backInView()));
    window.addEventListener("focus", () => this.backInView());
  }

  stop() {
    this.wanted = false;
    window.clearTimeout(this.retryTimer);
    this.ws?.close();
    this.ws = null;
    if (this.following) this.unfollow();
    useDevices.setState({ devices: [], active: "", online: false });
  }

  /** Who this device is, told again (the app's name for the phone comes after the page loads). The app
   * hears it too: it keeps the device's connection while the page is out of view. */
  hello() {
    if (!this.wanted) return;
    this.id = deviceId();       // the app's own, once it has said it
    const hello = { t: "hello", id: this.id, name: deviceName(), kind: appPlayer.available ? "app" : "browser",
                    library: useShell.getState().library === "local" ? "local" : "server" };
    this.send(hello);
    if (appPlayer.available) appPlayer.tellDevice(hello);
  }

  /** In the app, out of view: the page is frozen after a while, so the app keeps the device's
   * connection meanwhile (ConnectLink.kt); this page's own goes until it's back in view. */
  private park() {
    if (!appPlayer.available || !this.ws) return;
    this.parked = true;
    window.clearTimeout(this.retryTimer);
    const ws = this.ws;
    this.ws = null;
    ws.close();
  }

  /** Back in view (a phone's app opened again, a tab chosen): what plays elsewhere, asked for again. A
   * connection that went quiet while the page slept doesn't answer: it's made again. */
  private backInView() {
    if (!this.wanted) return;
    this.parked = false;
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return this.reconnectNow();
    this.send({ t: "sync" });
    window.clearTimeout(this.silence);
    const ws = this.ws;
    this.silence = window.setTimeout(() => {
      if (this.ws !== ws) return;
      this.retry = 0;
      ws.close();
      this.ws = null;
      useDevices.setState({ online: false });
      this.open();
    }, 4000);
  }

  private reconnectNow() {
    if (!this.wanted || this.parked || (this.ws && this.ws.readyState <= WebSocket.OPEN)) return;
    window.clearTimeout(this.retryTimer);
    this.open();
  }

  private open() {
    const ws = new WebSocket(`${location.origin.replace(/^http/, "ws")}/api/connect`);
    this.ws = ws;
    ws.onopen = () => {
      this.retry = 0;
      this.fresh = true;
      useDevices.setState({ online: true });
      this.hello();
      this.sentQueue = null;
      if (!this.following && usePlayer.getState().playing) this.publish();
    };
    ws.onmessage = (e) => {
      window.clearTimeout(this.silence);
      try {
        this.onMessage(JSON.parse(e.data));
      } catch {
        /* not ours */
      }
    };
    ws.onclose = () => {
      if (this.ws !== ws) return;
      this.ws = null;
      useDevices.setState({ online: false });
      if (!this.wanted || this.parked) return;
      const wait = [1, 2, 5, 10, 30][Math.min(this.retry++, 4)];
      this.retryTimer = window.setTimeout(() => this.open(), wait * 1000);
    };
  }

  private send(msg: object) {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(msg));
  }

  // ------------------------------------------------------------ the device that plays (this one)

  /** Once the changes made together are in: right after, not on a timer (in a page out of view, as the
   * app's is with the screen off, a timer can wait a minute). */
  private publishSoon() {
    if (this.publishing) return;
    this.publishing = true;
    queueMicrotask(() => {
      this.publishing = false;
      this.publish();
    });
  }

  /** What plays here, for the others; the queue only when it changed. A device that only has a
   * queue (paused, and nothing played anywhere) keeps quiet until it plays. */
  private publish() {
    const s = usePlayer.getState();
    const { active, you } = useDevices.getState();
    if (this.following || !this.ws || s.index < 0 || (active !== you && !s.playing)) return;
    const st: Shared = {
      index: s.index, position: s.position, duration: s.duration, playing: s.playing, buffering: s.buffering,
      shuffle: s.shuffle, repeat: s.repeat, volume: s.volume, muted: s.muted, library: this.mine(),
    };
    if (s.queue !== this.sentQueue || active !== you) st.queue = s.queue;
    this.sentQueue = s.queue;
    this.lastSent = { position: s.position, at: Date.now() };
    this.send({ t: "state", state: st });
  }

  // ------------------------------------------------------------ what comes in

  private onMessage(m: { t: string } & Record<string, unknown>) {
    if (m.t === "devices") this.onDevices(m as unknown as DeviceState & { grace: number });
    else if (m.t === "state") this.onState(m.state as Shared, m.at as number | undefined);
    else if (m.t === "command" && !this.following) this.hooks?.onCommand(m as unknown as Command);
    else if (m.t === "takeover") this.onTakeover(m.state as Shared, m.play as boolean);
    else if (m.t === "yield" && !this.following) this.follow();
    else if (m.t === "chat") window.dispatchEvent(new CustomEvent("muzix:chat", { detail: m }));   // chat/Chat.tsx
  }

  private onDevices(m: DeviceState & { grace: number }) {
    useDevices.setState({ devices: m.devices, active: m.active, you: m.you });
    window.clearTimeout(this.awayTimer);
    const elsewhere = !!m.active && m.active !== m.you;
    const away = elsewhere && !m.devices.some((d) => d.id === m.active);
    // just taken over here: the list may still name the device that played until the server hears of it; one
    // that's away isn't followed by a device that didn't follow it already: it may be gone (an app shut down)
    if (elsewhere && !away && !this.following && Date.now() - this.claimed > 5000) this.follow();
    else if (!elsewhere && this.following) this.unfollow();
    // the device that plays dropped off: it may be back in a moment (a reload); if not, nothing plays, and
    // what it played last is asked for (an empty player here picks it up). Meanwhile nothing plays there
    if (away && this.following) this.halt();
    if (away) {
      this.awayTimer = window.setTimeout(() => {
        useDevices.setState({ active: "" });
        if (this.following) this.unfollow();
        this.send({ t: "sync" });
      }, (m.grace + 1) * 1000);
    }
    // connected just now, and the server has this device as the one that plays: after a reload it plays on in
    // a moment, but after a restart nothing plays here; the others hear so
    if (this.fresh) {
      this.fresh = false;
      window.clearTimeout(this.idleTimer);
      if (m.active === m.you) this.idleTimer = window.setTimeout(() => this.notPlaying(), 2500);
    }
  }

  /** The device followed went away: it plays no more for now, where it got to (it says again if it's back). */
  private halt() {
    const s = usePlayer.getState();
    if (!s.playing && !s.buffering) return;
    this.applying = true;
    s.set({ playing: false, buffering: false, position: this.heard.position + (s.playing ? (Date.now() - this.heard.at) / 1000 : 0) });
    this.applying = false;
  }

  /** This device is the one that plays, as the server has it, but nothing plays here: what's here, paused,
   * or that nothing does. */
  private notPlaying() {
    const s = usePlayer.getState();
    const { active, you } = useDevices.getState();
    if (this.following || active !== you || s.playing || s.buffering) return;
    if (s.current()) this.publish();
    else this.send({ t: "stopped" });
  }

  /** This device plays from now on, through what it has here: a Cast speaker chosen while it followed
   * another device takes the music over, and that device stops (as when it's chosen in the picker). */
  claim() {
    if (!this.following) return;
    this.following = false;
    this.claimed = Date.now();
    this.sentQueue = null;
    usePlayer.getState().set({ deviceVolume: null });
    this.publish();
  }

  private follow() {
    this.hooks?.onFollow();
    this.following = true;
    this.sentQueue = null;
  }

  private unfollow() {
    this.following = false;
    usePlayer.getState().set({ deviceVolume: null });
    this.hooks?.onUnfollow(usePlayer.getState().position);
  }

  /** What plays on the device that plays, put in place here. Not following (nothing plays anywhere),
   * an empty player picks up what played last (`at`, seconds: when it was heard of), to play here, as
   * long as this device has nothing newer of its own (player/last.ts). */
  private onState(st: Shared, at?: number) {
    const s = usePlayer.getState();
    const theirs = st.library || "server";
    const last = (at ?? 0) * 1000;
    if (!this.following && (st.playing || theirs !== this.mine() || !mayPlace(last))) return;
    if (theirs !== this.theirs && !st.queue) return;     // another library's queue comes with it
    this.theirs = theirs;
    if (st.queue && theirs !== this.mine()) this.originals = new Map(st.queue.map((it) => [it.key, it]));
    const before = s.current()?.key;
    const queue = st.queue && (theirs === this.mine() ? st.queue : st.queue.map(foreign));
    if (!this.following && queue) place(queue, last);
    this.applying = true;
    s.set({
      ...(queue ? { queue } : {}),
      index: st.index, position: st.position, duration: st.duration, playing: this.following && st.playing,
      buffering: this.following && st.buffering, shuffle: st.shuffle, repeat: st.repeat,
      ...(this.following && st.volume !== undefined && Date.now() - this.turned > 1500
        ? { deviceVolume: { volume: st.volume, muted: !!st.muted } } : {}),
    });
    this.applying = false;
    this.heard = { position: st.position, at: Date.now() };
    const now = usePlayer.getState().current()?.key;
    if (now && now !== before) this.hooks?.onItem(now);
  }

  private onTakeover(st: Shared, play: boolean) {
    window.clearTimeout(this.awayTimer);
    this.following = false;
    this.applying = true;
    usePlayer.getState().set({
      ...(st.queue ? { queue: st.queue } : {}), index: st.index, duration: st.duration, shuffle: st.shuffle, repeat: st.repeat,
      deviceVolume: null,
    });
    this.applying = false;
    this.sentQueue = null;
    useDevices.setState({ active: useDevices.getState().you });
    this.hooks?.onTakeover(st.position, play);
  }

  // ------------------------------------------------------------ choosing a device

  /** The music moves to `device` (this one, or another), where it was. */
  transfer(device: string) {
    const s = usePlayer.getState();
    const state: Shared | undefined = s.queue.length && !this.following ? {
      queue: s.queue, index: Math.max(0, s.index), position: s.position, duration: s.duration, playing: true, buffering: false,
      shuffle: s.shuffle, repeat: s.repeat, library: this.mine(),
    } : undefined;
    this.send({ t: "transfer", to: device, play: s.playing || this.following ? s.playing : true, state });
  }

  // ------------------------------------------------------------ the controls, for the device that plays

  private command(c: Command) {
    this.send({ t: "command", ...c });
  }

  loadQueue(start: number, at = 0, autoplay = true) {
    const s = usePlayer.getState();
    this.command({ cmd: "load", queue: this.outgoing(s.queue), index: start, position: at, play: autoplay, library: this.theirs });
  }

  syncUpcoming() {
    const s = usePlayer.getState();
    this.command({ cmd: "queue", queue: this.outgoing(s.queue), index: s.index, library: this.theirs });
  }

  /** The queue as the device that plays has it: another library's songs as they came, not as shown here. */
  private outgoing(queue: PlayItem[]) {
    return queue.map((it) => (it.foreign ? this.originals.get(it.key) ?? it : it));
  }

  jump(index: number) {
    this.command({ cmd: "jump", index, key: usePlayer.getState().queue[index]?.key });
  }

  toggle() {
    this.command({ cmd: usePlayer.getState().playing ? "pause" : "play" });
  }

  next() {
    this.command({ cmd: "next" });
  }

  prev(always = false) {
    this.command({ cmd: "prev", always });
  }

  seek(t: number) {
    this.command({ cmd: "seek", position: t });
    this.heard = { position: t, at: Date.now() };
    usePlayer.getState().set({ position: t });
  }

  /** The volume there, shown here at once (this device's own volume stays as it was). */
  setVolume(volume: number, muted: boolean) {
    this.command({ cmd: "volume", volume, muted });
    this.turned = Date.now();
    usePlayer.getState().set({ deviceVolume: { volume, muted } });
  }

  stopMedia() {
    this.command({ cmd: "stop" });
  }
}

export const connect = new Connect();
