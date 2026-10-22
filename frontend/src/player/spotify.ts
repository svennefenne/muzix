/** Spotify playback inside Muzix through the Web Playback SDK (Premium), plus a
 * small Web API client. Muzix appears as a Spotify Connect device called "Muzix". */

import { api } from "../api";
import { usePlayer, type PlayItem } from "../store/player";

interface SpotifyPlayer {
  connect(): Promise<boolean>;
  disconnect(): void;
  addListener(ev: string, cb: (arg: any) => void): void;
  togglePlay(): Promise<void>;
  pause(): Promise<void>;
  resume(): Promise<void>;
  seek(ms: number): Promise<void>;
  setVolume(v: number): Promise<void>;
  getCurrentState(): Promise<any>;
  activateElement?(): Promise<void>;
}

declare global {
  interface Window {
    onSpotifyWebPlaybackSDKReady?: () => void;
    Spotify?: { Player: new (opts: any) => SpotifyPlayer };
  }
}

let token: { access_token: string; expires_at: number } | null = null;

export async function spotifyToken(): Promise<string> {
  if (token && token.expires_at * 1000 > Date.now() + 30000) return token.access_token;
  const res = await fetch("/api/spotify/token", { credentials: "same-origin" });
  if (!res.ok) throw new Error("Spotify isn't linked");
  token = await res.json();
  return token!.access_token;
}

/** GET/PUT a Spotify Web API path ("me/playlists", ...). */
export async function sp<T = any>(path: string, init: RequestInit = {}): Promise<T> {
  const url = path.startsWith("http") ? path : `https://api.spotify.com/v1/${path}`;
  const res = await fetch(url, {
    ...init,
    headers: { Authorization: `Bearer ${await spotifyToken()}`, "Content-Type": "application/json", ...(init.headers || {}) },
  });
  if (res.status === 204) return undefined as T;
  if (!res.ok) throw new Error(`Spotify: ${res.status} ${(await res.text()).slice(0, 200)}`);
  return res.json();
}

const genreCache = new Map<string, string[]>();

class SpotifyDriver {
  player: SpotifyPlayer | null = null;
  deviceId = "";
  private ready: Promise<void> | null = null;
  private poll: number | undefined;
  private currentUri = "";
  private endedFor = "";
  onEnded: (() => void) | null = null;

  init(): Promise<void> {
    if (this.ready) return this.ready;
    const ready = new Promise<void>((resolve, reject) => {
      const start = () => {
        const player = new window.Spotify!.Player({
          name: "Muzix",
          getOAuthToken: (cb: (t: string) => void) => spotifyToken().then(cb).catch(() => {}),
          volume: usePlayer.getState().volume,
        });
        player.addListener("ready", ({ device_id }) => {
          this.deviceId = device_id;
          resolve();
        });
        player.addListener("initialization_error", ({ message }) => reject(new Error(message)));
        player.addListener("authentication_error", ({ message }) => reject(new Error(
          `${message}: Spotify's player couldn't sign in. Strict tracking protection or a content blocker ` +
          `can cause this; allow ${location.host} and try again.`)));
        player.addListener("account_error", () => reject(new Error("Spotify Premium is needed to play in Muzix")));
        player.addListener("player_state_changed", (st) => this.onState(st));
        player.connect();
        this.player = player;
      };
      if (window.Spotify) return start();
      window.onSpotifyWebPlaybackSDKReady = start;
      const s = document.createElement("script");
      s.src = "https://sdk.scdn.co/spotify-player.js";
      s.onerror = () => reject(new Error("Couldn't load the Spotify player"));
      document.head.appendChild(s);
    }).catch((e) => {
      // start over on the next try instead of repeating this error until a reload
      this.player?.disconnect();
      this.player = null;
      this.ready = null;
      throw e;
    });
    this.ready = ready;
    return ready;
  }

  async playItem(item: PlayItem) {
    try {
      await this.init();
      await this.player?.activateElement?.();
      this.currentUri = item.spotifyUri || "";
      this.endedFor = "";
      await sp(`me/player/play?device_id=${this.deviceId}`, {
        method: "PUT", body: JSON.stringify({ uris: [item.spotifyUri], position_ms: Math.round((item.resume || 0) * 1000) }),
      });
      this.startPolling();
      this.loadGenres(item.spotifyArtist);
    } catch (e) {
      usePlayer.getState().set({ error: String((e as Error).message), playing: false, buffering: false });
    }
  }

  /** Spotify no longer shares artist genres with small apps; Muzix looks them up. */
  private async loadGenres(artist?: string) {
    if (!artist) return;
    let tags = genreCache.get(artist);
    if (!tags) {
      try {
        tags = await api.get<string[]>("/api/spotify/genres", { artist });
      } catch {
        return;     // genres are a nicety
      }
      genreCache.set(artist, tags);
    }
    if (!tags.length) return;
    const s = usePlayer.getState();
    s.set({ queue: s.queue.map((q) => (q.spotifyArtist === artist && !q.tags?.length ? { ...q, tags } : q)) });
  }

  private onState(st: any) {
    if (!st) return;
    const s = usePlayer.getState();
    if (s.current()?.kind !== "spotify") return;
    s.set({ playing: !st.paused, buffering: st.loading, position: st.position / 1000, duration: st.duration / 1000 });
    const uri = st.track_window?.current_track?.uri;
    // the SDK reports a finished track as paused at 0 with it in previous_tracks
    const finished = st.paused && st.position === 0 &&
      (st.track_window?.previous_tracks || []).some((t: any) => t.uri === this.currentUri);
    if (finished && this.endedFor !== this.currentUri) {
      this.endedFor = this.currentUri;
      this.onEnded?.();
    } else if (uri && uri !== this.currentUri && !st.paused) {
      this.currentUri = uri;
    }
  }

  private startPolling() {
    window.clearInterval(this.poll);
    this.poll = window.setInterval(async () => {
      if (usePlayer.getState().current()?.kind !== "spotify") return window.clearInterval(this.poll);
      const st = await this.player?.getCurrentState();
      if (st && !st.paused) usePlayer.getState().set({ position: st.position / 1000 });
    }, 500);
  }

  toggle() {
    this.player?.togglePlay();
  }

  pause() {
    if (this.player && usePlayer.getState().current()?.kind !== "spotify") this.player.pause().catch(() => {});
  }

  seek(t: number) {
    this.player?.seek(Math.round(t * 1000));
    usePlayer.getState().set({ position: t });
  }

  setVolume(v: number) {
    this.player?.setVolume(v).catch(() => {});
  }
}

export const spotify = new SpotifyDriver();
