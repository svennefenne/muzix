/** Casting to Google Cast speakers (Chromecast Audio, Nest and Home speakers, speaker
 * groups). Audio only, through Google's Default Media Receiver, so nothing needs
 * registering and no picture is ever sent. While a session runs the speaker holds the
 * next stretch of the queue and plays it straight from Muzix with signed links, so it
 * carries on when the phone sleeps; the engine hands its controls to this module, and
 * the speaker's state is mirrored back into the player store. */

import { api } from "../api";
import { usePlayer, type PlayItem } from "../store/player";
import { useUi } from "../store/ui";

const SDK = "https://www.gstatic.com/cv/js/sender/v1/cast_sender.js?loadCastFramework=1";
const WINDOW = 30;     // songs handed over at a time; Cast messages have to stay small
const TOP_UP = 8;      // hand over more when the speaker gets down to this many

export type CastState = "unavailable" | "available" | "connecting" | "connected";

export interface CastHooks {
  onStart(): void;                 // the speaker takes over: silence the local player
  onItem(key: string): void;       // the speaker moved on to another item
  onTime(position: number): void;
  onEnd(position: number): void;   // back to local playback, paused here
}

/** What the speaker keeps of an item, enough to rebuild the queue if the page reloads. */
type Slim = Pick<PlayItem, "key" | "kind" | "id" | "title" | "artist" | "album" | "art" | "duration" | "src"
  | "albumId" | "artistId" | "bookId" | "partOffset" | "format" | "castNative">;
interface Carried { muzix: Slim; offset: number }

const MIME: Record<string, string> = {
  mp3: "audio/mpeg", flac: "audio/flac", m4a: "audio/mp4", m4b: "audio/mp4", aac: "audio/mp4",
  ogg: "audio/ogg", oga: "audio/ogg", opus: "audio/ogg", wav: "audio/wav",
};

function slim(it: PlayItem): Slim {
  const { key, kind, id, title, artist, album, art, duration, src, albumId, artistId, bookId, partOffset, format, castNative } = it;
  return { key, kind, id, title, artist, album, art, duration, src, albumId, artistId, bookId, partOffset, format, castNative };
}

function carried(info?: chrome.cast.media.MediaInfo | null): Carried | null {
  const c = info?.customData as Carried | undefined;
  return c?.muzix ? c : null;
}

const castable = (it: PlayItem) => it.kind !== "spotify";

/** Callback-style Cast calls as promises. */
function call<T extends unknown[]>(fn: (...args: [...T, () => void, (e: chrome.cast.Error) => void]) => void, ...args: T) {
  return new Promise<void>((ok, fail) => fn(...args, ok, fail));
}

class Caster {
  state: CastState = "unavailable";
  private hooks: CastHooks | null = null;
  private player: cast.framework.RemotePlayer | null = null;
  private ctl: cast.framework.RemotePlayerController | null = null;
  private link = { token: "", expires: 0 };
  private offset = 0;          // where the current item's stream started, when it was restarted at a time
  private localVolume: number | null = null;

  get active() {
    return this.state === "connected";
  }

  attach(hooks: CastHooks) {
    this.hooks = hooks;
  }

  /** Loads Google's sender library where casting can work (Chrome, https pages), and says why not elsewhere. */
  load() {
    const set = usePlayer.getState().set;
    const no = (castWhy: string) => set({ castSupport: "unsupported", castWhy });
    if (!window.isSecureContext) return no("Casting needs Muzix's https address.");
    if (!/Chrome\//.test(navigator.userAgent) || /SamsungBrowser/.test(navigator.userAgent))
      return no("Casting needs Google Chrome, on Android or a computer.");
    window.__onGCastApiAvailable = (ok, reason) => {
      if (ok) this.init();
      else no(`Google Cast isn't available in this browser${reason ? ` (${reason})` : ""}.`);
    };
    const s = document.createElement("script");
    s.src = SDK;
    s.async = true;
    s.onerror = () => no("Google's Cast library couldn't load. Is an ad or tracker blocker stopping www.gstatic.com?");
    document.head.appendChild(s);
  }

  private init() {
    const ctx = cast.framework.CastContext.getInstance();
    ctx.setOptions({
      receiverApplicationId: chrome.cast.media.DEFAULT_MEDIA_RECEIVER_APP_ID,
      autoJoinPolicy: chrome.cast.AutoJoinPolicy.ORIGIN_SCOPED,
    });
    ctx.addEventListener(cast.framework.CastContextEventType.CAST_STATE_CHANGED, (e) => this.setState(e.castState));
    ctx.addEventListener(cast.framework.CastContextEventType.SESSION_STATE_CHANGED, (e) => this.onSession(e.sessionState));
    this.player = new cast.framework.RemotePlayer();
    this.ctl = new cast.framework.RemotePlayerController(this.player);
    this.ctl.addEventListener(cast.framework.RemotePlayerEventType.ANY_CHANGE, (e) => this.onChange(e.field));
    this.setState(ctx.getCastState());
    usePlayer.getState().set({ castSupport: "ready" });
    usePlayer.subscribe((s, prev) => {
      if (!this.active) return;
      if (s.repeat !== prev.repeat) this.setRepeat();
      if (s.shuffle && !prev.shuffle) {
        this.shuffleUpcoming();
        this.syncUpcoming();
      }
    });
  }

  /** Opens the browser's speaker picker (it also offers "Stop casting" while connected). */
  choose() {
    const failed = (e: unknown) => {
      if (!e || e === "cancel") return;
      useUi.getState().notify(e === "receiver_unavailable" ? "No speakers found on this network"
        : `Couldn't connect to the speaker (${String(e)})`, "error");
    };
    cast.framework.CastContext.getInstance().requestSession().then(failed, failed);
  }

  private session() {
    return cast.framework.CastContext.getInstance().getCurrentSession();
  }

  private media() {
    return this.session()?.getMediaSession() ?? null;
  }

  private setState(cs: cast.framework.CastState) {
    const map: Record<string, CastState> = {
      NO_DEVICES_AVAILABLE: "unavailable", NOT_CONNECTED: "available", CONNECTING: "connecting", CONNECTED: "connected",
    };
    this.state = map[cs] ?? "unavailable";
    usePlayer.getState().set({ castState: this.state, castDevice: this.session()?.getCastDevice().friendlyName || "" });
  }

  private onSession(st: cast.framework.SessionState) {
    const S = cast.framework.SessionState;
    const s = usePlayer.getState();
    if (st === S.SESSION_STARTED) {
      this.state = "connected";
      const wasPlaying = s.playing;
      this.hooks?.onStart();
      this.localVolume = s.volume;
      if (s.current()) this.loadQueue(s.index, s.position, wasPlaying || s.position < 1);
    } else if (st === S.SESSION_RESUMED) {
      this.state = "connected";
      this.hooks?.onStart();
      this.localVolume = s.volume;
      this.adopt();
    } else if (st === S.SESSION_ENDED) {
      this.state = "available";
      const at = s.position;
      if (this.localVolume !== null) s.set({ volume: this.localVolume });
      this.localVolume = null;
      this.offset = 0;
      this.hooks?.onEnd(at);
    }
  }

  /** After a reload mid-session: take the speaker's queue as ours. */
  private adopt() {
    const m = this.media();
    if (!m?.items?.length) return;
    const queue = m.items.map((i) => carried(i.media)?.muzix).filter(Boolean) as PlayItem[];
    const cur = carried(m.media);
    usePlayer.getState().set({ queue, index: Math.max(0, queue.findIndex((i) => i.key === cur?.muzix.key)) });
  }

  // ------------------------------------------------------------ handing the queue over

  private async token() {
    if (this.link.expires - Date.now() / 1000 < 3600) {
      const r = await api.get<{ token: string; expires: number }>("/api/cast/token");
      this.link = r;
    }
    return this.link.token;
  }

  private url(it: PlayItem, token: string, from: number) {
    const u = new URL(it.src, location.origin);
    if (it.kind !== "radio") u.searchParams.set("q", "cast");
    if (from > 0.5) u.searchParams.set("t", from.toFixed(1));
    u.searchParams.set("ct", token);
    return u.toString();
  }

  /** `from`: the stream starts that far in (converted streams can't seek); `startTime`: the speaker seeks there itself. */
  private queueItem(it: PlayItem, token: string, from = 0, startTime = 0) {
    const live = it.kind === "radio";
    const info = new chrome.cast.media.MediaInfo(this.url(it, token, from),
      it.kind === "track" ? MIME[it.format || ""] || "audio/flac" : "audio/mpeg");
    info.streamType = live ? chrome.cast.media.StreamType.LIVE : chrome.cast.media.StreamType.BUFFERED;
    if (it.duration && !from) info.duration = it.duration;
    // words only: the speaker never gets a picture
    if (live) {
      const md = new chrome.cast.media.GenericMediaMetadata();
      md.title = it.title;
      md.subtitle = it.artist;
      info.metadata = md;
    } else {
      const md = new chrome.cast.media.MusicTrackMediaMetadata();
      md.title = it.title;
      md.artist = it.artist;
      md.albumName = it.album || "";
      info.metadata = md;
    }
    info.customData = { muzix: slim(it), offset: from } satisfies Carried;
    const qi = new chrome.cast.media.QueueItem(info);
    qi.autoplay = true;
    qi.preloadTime = 15;
    if (startTime) qi.startTime = startTime;
    return qi;
  }

  /** The castable items from `start` on, as many as fit in one handover. */
  private upcoming(start: number) {
    return usePlayer.getState().queue.slice(start).filter(castable).slice(0, WINDOW);
  }

  /** Shuffle on a speaker plays a shuffled queue in order (it can't pick at random as we do). */
  private shuffleUpcoming() {
    const s = usePlayer.getState();
    const cur = s.current();
    if (!cur) return;
    const rest = s.queue.filter((_, i) => i !== s.index);
    for (let i = rest.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [rest[i], rest[j]] = [rest[j], rest[i]];
    }
    s.set({ queue: [cur, ...rest], index: 0 });
  }

  private repeatMode() {
    const R = chrome.cast.media.RepeatMode;
    return { off: R.OFF, all: R.ALL, one: R.SINGLE }[usePlayer.getState().repeat];
  }

  /** Starts the speaker on the queue at `start`, `at` seconds in. */
  async loadQueue(start: number, at = 0, autoplay = true) {
    const sess = this.session();
    const s = usePlayer.getState();
    if (!sess || start < 0) return;
    if (s.shuffle && start === s.index) {
      this.shuffleUpcoming();
      start = 0;
    }
    const first = s.queue[start];
    if (first && !castable(first)) useUi.getState().notify("Spotify songs can't be cast; skipping them on the speaker");
    const items = this.upcoming(start);
    if (!items.length) return useUi.getState().notify("Nothing in the queue can play on a speaker");
    const token = await this.token();
    // a file the speaker takes as it is, it seeks in itself; anything converted starts at the time
    const into = at > 0.5 && items[0] === first ? at : 0;
    const native = !!items[0].castNative;
    this.offset = native ? 0 : into;
    const req = new chrome.cast.media.QueueLoadRequest(items.map((it, i) =>
      i === 0 ? this.queueItem(it, token, this.offset, native ? into : 0) : this.queueItem(it, token)));
    req.startIndex = 0;
    req.repeatMode = this.repeatMode();
    usePlayer.getState().set({ buffering: true, error: "" });
    try {
      await call(sess.getSessionObj().queueLoad.bind(sess.getSessionObj()), req);
      if (!autoplay && this.player && !this.player.isPaused) this.ctl?.playOrPause();
    } catch {
      usePlayer.getState().set({ buffering: false });
      useUi.getState().notify(`${sess.getCastDevice().friendlyName} couldn't start playing`, "error");
    }
  }

  /** Makes the speaker's upcoming items match ours, without touching what's playing now. */
  async syncUpcoming() {
    const m = this.media();
    if (!m?.items) return;
    const s = usePlayer.getState();
    const at = m.items.findIndex((i) => i.itemId === m.currentItemId);
    const after = m.items.slice(at + 1);
    const want = this.upcoming(s.index).slice(1);
    if (after.length === want.length && after.every((qi, i) => carried(qi.media)?.muzix.key === want[i].key)) return;
    try {
      for (const qi of after) await call(m.queueRemoveItem.bind(m), qi.itemId);
      const token = await this.token();
      if (want.length) await call(m.queueInsertItems.bind(m), new chrome.cast.media.QueueInsertItemsRequest(want.map((it) => this.queueItem(it, token))));
    } catch {
      /* the speaker keeps what it had */
    }
  }

  private setRepeat() {
    const m = this.media();
    if (m) m.queueSetRepeatMode(this.repeatMode(), () => {}, () => {});
  }

  // ------------------------------------------------------------ controls

  toggle() {
    if (!this.player?.isMediaLoaded) {
      const s = usePlayer.getState();
      return this.loadQueue(s.index, s.position, true);
    }
    this.ctl?.playOrPause();
  }

  jump(index: number) {
    const m = this.media();
    const key = usePlayer.getState().queue[index]?.key;
    const qi = m?.items?.find((i) => carried(i.media)?.muzix.key === key);
    if (m && qi) m.queueJumpToItem(qi.itemId, () => {}, () => this.loadQueue(index));
    else this.loadQueue(index);
  }

  next() {
    const m = this.media();
    const s = usePlayer.getState();
    const onSpeaker = m?.items?.findIndex((i) => i.itemId === m.currentItemId) ?? -1;
    if (m?.items && onSpeaker >= 0 && onSpeaker < m.items.length - 1) m.queueNext(() => {}, () => {});
    else if (s.index < s.queue.length - 1) this.loadQueue(s.index + 1);
    else if (s.repeat === "all") this.loadQueue(0);
  }

  prev() {
    const m = this.media();
    const s = usePlayer.getState();
    if (s.position > 4 || s.index <= 0) return this.seek(0);
    const onSpeaker = m?.items?.findIndex((i) => i.itemId === m.currentItemId) ?? -1;
    if (m && onSpeaker > 0) m.queuePrev(() => {}, () => {});
    else this.loadQueue(s.index - 1);
  }

  seek(t: number) {
    const p = this.player;
    const s = usePlayer.getState();
    const cur = s.current();
    if (!p || !this.ctl || !cur || cur.kind === "radio") return;
    // files seek on the speaker; converted and rendered streams are restarted at the time
    if (cur.castNative && !this.offset && p.canSeek) {
      p.currentTime = t;
      this.ctl.seek();
    } else this.loadQueue(s.index, t, !p.isPaused);
    s.set({ position: t });
  }

  setVolume(volume: number, muted: boolean) {
    const p = this.player;
    if (!p || !this.ctl) return;
    if (Math.abs(p.volumeLevel - volume) > 0.01) {
      p.volumeLevel = volume;
      this.ctl.setVolumeLevel();
    }
    if (p.isMuted !== muted) this.ctl.muteOrUnmute();
  }

  stopMedia() {
    this.ctl?.stop();
  }

  // ------------------------------------------------------------ the speaker's side

  private onChange(field: string) {
    const p = this.player;
    if (!p || !this.active) return;
    const s = usePlayer.getState();
    const PS = chrome.cast.media.PlayerState;
    if (field === "currentTime") this.hooks?.onTime(this.offset + p.currentTime);
    else if (field === "mediaInfo") this.onItem();
    else if (field === "playerState") {
      s.set({ playing: p.playerState === PS.PLAYING || p.playerState === PS.BUFFERING, buffering: p.playerState === PS.BUFFERING });
      if (p.playerState === PS.IDLE && this.media()?.idleReason === chrome.cast.media.IdleReason.ERROR) {
        const name = s.current()?.title || "this";
        useUi.getState().notify(`The speaker couldn't play ${name}`, "error");
        this.next();
      }
    } else if (field === "volumeLevel" || field === "isMuted") {
      s.set({ volume: p.volumeLevel, muted: p.isMuted });
    }
  }

  private onItem() {
    const c = carried(this.player?.mediaInfo);
    if (!c) return;
    this.offset = c.offset || 0;
    const s = usePlayer.getState();
    let index = s.queue.findIndex((i) => i.key === c.muzix.key);
    if (index < 0) {
      s.set({ queue: [...s.queue, c.muzix as PlayItem] });
      index = usePlayer.getState().queue.length - 1;
    }
    s.set({ index, duration: c.muzix.duration, position: this.offset });
    this.hooks?.onItem(c.muzix.key);
    this.topUp();
  }

  /** Hands the speaker more of the queue as it nears the end of what it has. */
  private async topUp() {
    const m = this.media();
    if (!m?.items) return;
    const left = m.items.length - 1 - m.items.findIndex((i) => i.itemId === m.currentItemId);
    if (left > TOP_UP) return;
    const have = new Set(m.items.map((i) => carried(i.media)?.muzix.key));
    const more = this.upcoming(usePlayer.getState().index).filter((it) => !have.has(it.key));
    if (!more.length) return;
    const token = await this.token();
    m.queueInsertItems(new chrome.cast.media.QueueInsertItemsRequest(more.map((it) => this.queueItem(it, token))), () => {}, () => {});
  }
}

export const caster = new Caster();
