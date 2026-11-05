/** Muzix Connect, as with Spotify: this page is one of the account's devices (backend/muzix/api/connect.py).
 * While another device plays, this one follows it: the queue and what plays are that device's, shown
 * here, and the controls here go to it (the engine hands them to this module the way it does to a
 * Cast speaker). Choosing a device moves the music there, where it was. */

import { create } from "zustand";
import { type PlayItem, type Repeat, usePlayer } from "../store/player";
import { appPlayer } from "./app";

export interface Device { id: string; name: string; kind: "browser" | "app" }

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

/** This tab (a browser's tabs are devices of their own), or the app: kept through reloads. */
function deviceId() {
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

const SAME = ["index", "playing", "buffering", "duration", "shuffle", "repeat"] as const;

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
  private sendTimer = 0;
  private lastSent = { position: 0, at: 0 };
  private heard = { position: 0, at: 0 };   // the position it told last, and when

  get active() {
    return this.following;
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
      const moved = Math.abs(s.position - (this.lastSent.position + (s.playing ? (Date.now() - this.lastSent.at) / 1000 : 0))) > 3;
      if (s.queue !== prev.queue || SAME.some((k) => s[k] !== prev[k]) || moved) this.publishSoon();
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
    document.addEventListener("visibilitychange", () => !document.hidden && this.reconnectNow());
  }

  stop() {
    this.wanted = false;
    window.clearTimeout(this.retryTimer);
    this.ws?.close();
    this.ws = null;
    if (this.following) this.unfollow();
    useDevices.setState({ devices: [], active: "", online: false });
  }

  /** Who this device is, told again (the app's name for the phone comes after the page loads). */
  hello() {
    if (this.wanted) this.send({ t: "hello", id: this.id, name: deviceName(), kind: appPlayer.available ? "app" : "browser" });
  }

  private reconnectNow() {
    if (!this.wanted || (this.ws && this.ws.readyState <= WebSocket.OPEN)) return;
    window.clearTimeout(this.retryTimer);
    this.open();
  }

  private open() {
    const ws = new WebSocket(`${location.origin.replace(/^http/, "ws")}/api/connect`);
    this.ws = ws;
    ws.onopen = () => {
      this.retry = 0;
      useDevices.setState({ online: true });
      this.hello();
      this.sentQueue = null;
      if (!this.following && usePlayer.getState().playing) this.publish();
    };
    ws.onmessage = (e) => {
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
      if (!this.wanted) return;
      const wait = [1, 2, 5, 10, 30][Math.min(this.retry++, 4)];
      this.retryTimer = window.setTimeout(() => this.open(), wait * 1000);
    };
  }

  private send(msg: object) {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(msg));
  }

  // ------------------------------------------------------------ the device that plays (this one)

  private publishSoon() {
    window.clearTimeout(this.sendTimer);
    this.sendTimer = window.setTimeout(() => this.publish(), 150);
  }

  /** What plays here, for the others; the queue only when it changed. A device that only has a
   * queue (paused, and nothing played anywhere) keeps quiet until it plays. */
  private publish() {
    const s = usePlayer.getState();
    const { active, you } = useDevices.getState();
    if (this.following || !this.ws || s.index < 0 || (active !== you && !s.playing)) return;
    const st: Shared = {
      index: s.index, position: s.position, duration: s.duration, playing: s.playing, buffering: s.buffering,
      shuffle: s.shuffle, repeat: s.repeat,
    };
    if (s.queue !== this.sentQueue || active !== you) st.queue = s.queue;
    this.sentQueue = s.queue;
    this.lastSent = { position: s.position, at: Date.now() };
    this.send({ t: "state", state: st });
  }

  // ------------------------------------------------------------ what comes in

  private onMessage(m: { t: string } & Record<string, unknown>) {
    if (m.t === "devices") this.onDevices(m as unknown as DeviceState & { grace: number });
    else if (m.t === "state") this.onState(m.state as Shared);
    else if (m.t === "command" && !this.following) this.hooks?.onCommand(m as unknown as Command);
    else if (m.t === "takeover") this.onTakeover(m.state as Shared, m.play as boolean);
    else if (m.t === "yield" && !this.following) this.follow();
  }

  private onDevices(m: DeviceState & { grace: number }) {
    useDevices.setState({ devices: m.devices, active: m.active, you: m.you });
    window.clearTimeout(this.awayTimer);
    const elsewhere = !!m.active && m.active !== m.you;
    if (elsewhere && !this.following) this.follow();
    else if (!elsewhere && this.following) this.unfollow();
    // the device that plays dropped off: it may be back in a moment (a reload); if not, nothing plays
    if (elsewhere && !m.devices.some((d) => d.id === m.active)) {
      this.awayTimer = window.setTimeout(() => {
        useDevices.setState({ active: "" });
        if (this.following) this.unfollow();
      }, (m.grace + 1) * 1000);
    }
  }

  private follow() {
    this.hooks?.onFollow();
    this.following = true;
    this.sentQueue = null;
  }

  private unfollow() {
    this.following = false;
    this.hooks?.onUnfollow(usePlayer.getState().position);
  }

  /** What plays on the device that plays, put in place here. Not following (nothing plays anywhere),
   * an empty player picks up what played last, to play here. */
  private onState(st: Shared) {
    const s = usePlayer.getState();
    if (!this.following && (s.queue.length || st.playing)) return;
    const before = s.current()?.key;
    this.applying = true;
    s.set({
      ...(st.queue ? { queue: st.queue } : {}),
      index: st.index, position: st.position, duration: st.duration, playing: this.following && st.playing,
      buffering: this.following && st.buffering, shuffle: st.shuffle, repeat: st.repeat,
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
    const state: Shared | undefined = s.queue.length ? {
      queue: s.queue, index: Math.max(0, s.index), position: s.position, duration: s.duration, playing: true, buffering: false,
      shuffle: s.shuffle, repeat: s.repeat,
    } : undefined;
    this.send({ t: "transfer", to: device, play: s.playing || this.following ? s.playing : true, state });
  }

  // ------------------------------------------------------------ the controls, for the device that plays

  private command(c: Command) {
    this.send({ t: "command", ...c });
  }

  loadQueue(start: number, at = 0, autoplay = true) {
    const s = usePlayer.getState();
    this.command({ cmd: "load", queue: s.queue, index: start, position: at, play: autoplay });
  }

  syncUpcoming() {
    const s = usePlayer.getState();
    this.command({ cmd: "queue", queue: s.queue, index: s.index });
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

  setVolume(volume: number, muted: boolean) {
    this.command({ cmd: "volume", volume, muted });
  }

  stopMedia() {
    this.command({ cmd: "stop" });
  }
}

export const connect = new Connect();
