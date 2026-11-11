import { useQuery } from "@tanstack/react-query";
import { lazy, type RefObject, Suspense, useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { Link, Route, Routes, useLocation, useNavigate, useNavigationType } from "react-router-dom";
import { queryClient } from "./actions";
import { api } from "./api";
import { ChatHost, ChatPanel } from "./chat/Chat";
import { useChat } from "./chat/store";
import { AdminHost } from "./components/AdminMode";
import { useAccountLook } from "./components/Avatar";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { Logo } from "./components/Logo";
import { StationHistory } from "./components/StationHistory";
import { Tooltips } from "./components/Tooltips";
import { Display, Kicker, Loading, MenuHost } from "./components/ui";
import { MiniPlayer, TabBar } from "./layout/Mobile";
import { NowPanel } from "./layout/NowPanel";
import { Sidebar } from "./layout/Sidebar";
import { Footer, LyricsSheet, NowPlaying, PlaylistPicker, QueueDrawer, Toast } from "./layout/Overlays";
import { PlayerBar, SKIP } from "./layout/PlayerBar";
import { focusQuickSearch } from "./layout/QuickSearch";
import { isTyping, TopBar } from "./layout/TopBar";
import Home from "./pages/Home";
import {
  AlbumPage, ArtistPage, FilePlaylistPage, GenrePage, TagPage, LibraryAlbums, LibraryArtistAlbums, LibraryArtists, LibraryGenreArtists, LibraryGenres,
  LibraryHome, Liked, PlaylistPage, Playlists, SearchPage,
} from "./pages/Library";
import { appPlayer, useShell } from "./player/app";
import { engine } from "./player/engine";
import { usePlayer } from "./store/player";
import { useUi } from "./store/ui";
import { ThemeApplier } from "./theme/ThemeApplier";
import { likedCollection, useDownloads } from "./downloads";
import type { AuthState, ModuleKey, Track } from "./types";

const Vgm = lazy(() => import("./pages/Vgm"));
const Books = lazy(() => import("./pages/Books"));
const BookPage = lazy(() => import("./pages/Books").then((m) => ({ default: m.BookPage })));
const Podcasts = lazy(() => import("./pages/Podcasts"));
const PodcastPage = lazy(() => import("./pages/Podcasts").then((m) => ({ default: m.PodcastPage })));
const EpisodePage = lazy(() => import("./pages/Podcasts").then((m) => ({ default: m.EpisodePage })));
const Radio = lazy(() => import("./pages/Radio"));
const Settings = lazy(() => import("./pages/Settings"));
const SchemeEditor = lazy(() => import("./pages/SchemeEditor"));
const Admin = lazy(() => import("./pages/admin/Admin"));
const Setup = lazy(() => import("./pages/Setup"));
const Downloads = lazy(() => import("./pages/Downloads"));

const MODULE_NAMES: Record<ModuleKey, string> = {
  vgm: "VGM", audiobooks: "Audiobooks", podcasts: "Podcasts", radio: "Radio", network: "Library Network",
};

/** A module's page, while the module is on (modules.ts); else a word that it's off. */
function Gate({ module, children }: { module: ModuleKey; children: React.ReactNode }) {
  const on = useUi((s) => s.modules[module]);
  const admin = useUi((s) => !!s.user?.is_admin);
  if (on) return children;
  return (
    <div className="page">
      <Display l1={MODULE_NAMES[module]} l2="is off" />
      <p className="lede">This server doesn't run {MODULE_NAMES[module]} at the moment.{admin ? " You can turn it on under Admin → Modules." : ""}</p>
      {admin && <Link className="btn accent" to="/admin/modules">Open Modules</Link>}
    </div>
  );
}

function Shortcuts() {
  const nav = useNavigate();
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      const search = () => { e.preventDefault(); if (!focusQuickSearch()) nav("/search"); };
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") return search();
      if (isTyping(e) || e.ctrlKey || e.metaKey || e.altKey) return;
      const s = usePlayer.getState();
      // in an episode or an audiobook: the arrows skip as its buttons do, and P goes to the one before it
      const spoken = s.current()?.kind === "book" || s.current()?.kind === "episode";
      const skip = e.shiftKey ? 30 : spoken ? SKIP : 5;
      if (e.key === " ") { e.preventDefault(); engine.toggle(); }
      else if (e.key === "/") search();
      else if (e.key === "ArrowRight") engine.seek(s.position + skip);
      else if (e.key === "ArrowLeft") engine.seek(s.position - skip);
      else if (e.key.toLowerCase() === "m") engine.setVolume(s.deviceVolume?.volume ?? s.volume, !(s.deviceVolume?.muted ?? s.muted));
      else if (e.key.toLowerCase() === "n") engine.next();
      else if (e.key.toLowerCase() === "p") { if (!spoken) engine.prev(); else if (s.index > 0) engine.prev(true); }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [nav]);
  return null;
}

/** F5 (or Ctrl+R) while music plays: the page's data is fetched afresh and the page drawn again,
 * while the music plays on without a break. A new version of Muzix needs the real thing: then
 * the page reloads, and the music carries on where it was (player/engine.ts). Ctrl+F5, Shift+F5
 * and the browser's own button reload as ever. */
function useSoftReload(redraw: () => void) {
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      const f5 = e.key === "F5" && !e.ctrlKey && !e.shiftKey && !e.metaKey && !e.altKey;
      const r = (e.ctrlKey || e.metaKey) && !e.shiftKey && !e.altKey && e.key.toLowerCase() === "r";
      const s = usePlayer.getState();
      if ((!f5 && !r) || !(s.playing || s.buffering)) return;
      e.preventDefault();
      if (e.repeat) return;
      newVersion().then((newer) => {
        if (newer) return location.reload();
        queryClient.invalidateQueries();
        redraw();
        useUi.getState().notify("Refreshed: the music plays on");
      });
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [redraw]);
}

/** Whether the server has a newer Muzix than this page runs: its page loads other scripts. */
async function newVersion() {
  const ours = [...document.scripts].map((el) => el.getAttribute("src") || "").filter((src) => src.startsWith("/assets/"));
  try {
    const r = await fetch("/", { cache: "no-store" });
    const theirs = r.ok ? [...(await r.text()).matchAll(/<script[^>]*\ssrc="(\/assets\/[^"]+)"/g)].map((m) => m[1]) : [];
    return theirs.length > 0 && theirs.join(" ") !== ours.join(" ");
  } catch {
    return false;
  }
}

/** Where each page was scrolled, by history entry: going back (or forward) returns there; a new
 * page starts at the top. */
const scrolledTo = new Map<string, number>();

function useScrollMemory(scroll: RefObject<HTMLDivElement | null>) {
  const loc = useLocation();
  const how = useNavigationType();
  const entry = useRef(loc.key);
  const path = useRef(loc.pathname);
  useEffect(() => {
    const el = scroll.current;
    if (!el) return;
    const save = () => scrolledTo.set(entry.current, el.scrollTop);
    el.addEventListener("scroll", save, { passive: true });
    return () => el.removeEventListener("scroll", save);
  }, [scroll]);
  // right after the new page is on screen, before any scroll event: a clamped scroll belongs to it
  useLayoutEffect(() => {
    const el = scroll.current;
    entry.current = loc.key;
    const samePage = path.current === loc.pathname;
    path.current = loc.pathname;
    if (!el) return;
    if (how !== "POP") {
      if (!samePage) el.scrollTo({ top: 0, behavior: "instant" });
      return;
    }
    const target = scrolledTo.get(loc.key) ?? 0;
    el.scrollTo({ top: target, behavior: "instant" });
    if (!target) return;
    // the page may still be filling in: keep at it until it's tall enough, or the user scrolls
    let tries = 0;
    const stop = () => {
      window.clearInterval(timer);
      el.removeEventListener("wheel", stop);
      el.removeEventListener("touchstart", stop);
    };
    const timer = window.setInterval(() => {
      if (++tries > 40 || entry.current !== loc.key) return stop();
      if (el.scrollHeight - el.clientHeight >= target && Math.abs(el.scrollTop - target) < 2) return stop();
      el.scrollTo({ top: target, behavior: "instant" });
    }, 50);
    el.addEventListener("wheel", stop, { passive: true });
    el.addEventListener("touchstart", stop, { passive: true });
    return stop;
  }, [loc.key, loc.pathname, how, scroll]);
}

/** Offline, in the app: the page needs the server, which can't be reached. */
function NeedsServer() {
  return (
    <div className="page">
      <Display l1="Needs" l2="the server" small />
      <p className="lede">The server can't be reached, so only what's downloaded is here.</p>
      <Link className="btn accent" to="/downloads">Your downloads</Link>
    </div>
  );
}

/** The liked songs, while they're downloaded: the phone gets each song liked, and lets go of each unliked. */
function useLikedKept() {
  const kept = useDownloads((s) => !s.offline && s.list.some((d) => d.id === "liked"));
  const q = useQuery({ queryKey: ["liked"], queryFn: () => api.get<Track[]>("/api/likes/tracks"), enabled: kept });
  useEffect(() => {
    if (kept && q.data) appPlayer.download(likedCollection(q.data));
  }, [kept, q.data]);
}

function Shell() {
  const loc = useLocation();
  const npPanel = useUi((s) => s.npPanel);
  const chatOpen = useChat((s) => s.open);
  const offline = useDownloads((s) => s.offline);
  const downloaded = useDownloads((s) => s.list);
  // offline, only the downloads, their pages and the settings
  const away = offline && loc.pathname !== "/" && loc.pathname !== "/downloads" && loc.pathname !== "/settings"
    && !downloaded.some((d) => d.path === loc.pathname);
  useLikedKept();
  useAccountLook();
  const scroll = useRef<HTMLDivElement>(null);
  const [drawn, setDrawn] = useState(0);
  useScrollMemory(scroll);
  useSoftReload(useCallback(() => setDrawn((n) => n + 1), []));
  return (
    <div className="shell">
      <ThemeApplier />
      <Shortcuts />
      <TopBar />
      <div className={`workspace ${npPanel || chatOpen ? "np-open" : ""}`}>
      <Sidebar />
      <main className="frame">
        <div className="frame-scroll" ref={scroll}>
          <ErrorBoundary resetKey={loc.pathname} key={drawn}>
          <Suspense fallback={<div className="page"><Loading /></div>}>
            {away ? <NeedsServer /> : <Routes>
              <Route path="/" element={offline ? <Downloads /> : <Home />} />
              <Route path="/downloads" element={<Downloads />} />
              <Route path="/library" element={<LibraryHome />} />
              <Route path="/library/genres" element={<LibraryGenres />} />
              <Route path="/library/genres/:genre" element={<LibraryGenreArtists />} />
              <Route path="/library/genres/:genre/:id" element={<LibraryArtistAlbums />} />
              <Route path="/library/artists" element={<LibraryArtists />} />
              <Route path="/library/artists/:id" element={<LibraryArtistAlbums />} />
              <Route path="/library/albums" element={<LibraryAlbums />} />
              <Route path="/library/liked" element={<Liked />} />
              <Route path="/library/playlists" element={<Playlists />} />
              <Route path="/album/:id" element={<AlbumPage />} />
              <Route path="/artist/:id" element={<ArtistPage />} />
              <Route path="/genre/:name" element={<GenrePage />} />
              <Route path="/tag/:name" element={<TagPage />} />
              <Route path="/playlist/:id" element={<PlaylistPage />} />
              <Route path="/playlist/file/:id" element={<FilePlaylistPage />} />
              <Route path="/search" element={<SearchPage />} />
              <Route path="/vgm/*" element={<Gate module="vgm"><Vgm /></Gate>} />
              <Route path="/audiobooks" element={<Gate module="audiobooks"><Books /></Gate>} />
              <Route path="/audiobooks/:id" element={<Gate module="audiobooks"><BookPage /></Gate>} />
              <Route path="/podcasts" element={<Gate module="podcasts"><Podcasts /></Gate>} />
              <Route path="/podcasts/:id" element={<Gate module="podcasts"><PodcastPage /></Gate>} />
              <Route path="/podcasts/episode/:eid" element={<Gate module="podcasts"><EpisodePage /></Gate>} />
              <Route path="/radio" element={<Gate module="radio"><Radio /></Gate>} />
              <Route path="/settings" element={<Settings />} />
              <Route path="/settings/schemes/new" element={<SchemeEditor key="new" />} />
              <Route path="/settings/schemes/:id" element={<SchemeEditor />} />
              <Route path="/admin/*" element={<Admin />} />
              <Route path="*" element={<div className="page"><Display l1="Lost" l2="in space" /><p className="lede">That page doesn't exist.</p></div>} />
            </Routes>}
          </Suspense>
          </ErrorBoundary>
        </div>
      </main>
      {chatOpen ? <ChatPanel /> : npPanel && <NowPanel />}
      </div>
      <PlayerBar />
      <Footer />
      <MiniPlayer />
      <TabBar />
      <QueueDrawer />
      <NowPlaying />
      <LyricsSheet />
      <PlaylistPicker />
      <StationHistory />
      <MenuHost />
      <Tooltips />
      <AdminHost />
      <ChatHost />
      <Toast />
    </div>
  );
}

/** The server doesn't answer. In the app, whose pages come with it, that's said here (a browser has no
 * page without the server). */
function Unreachable({ retry }: { retry: () => void }) {
  // Muzix Desktop's pages are on 127.0.0.1, not the server's address
  const desktop = useShell((s) => !!s.desktop);
  return (
    <div className="auth">
      <ThemeApplier />
      <div className="auth-card">
        <div className="logo" style={{ marginBottom: 26 }}><Logo name="Muzix" /></div>
        <Kicker parts={["No answer", desktop ? undefined : location.host]} />
        <Display l1="Can't reach" l2="the server" small />
        {desktop
          ? <p className="lede">Your Muzix server doesn't answer. Check this computer's connection, or that the server is up.</p>
          : <p className="lede">Muzix at {location.host} doesn't answer. Check the phone's connection, or that the server is up.</p>}
        <div className="row-actions">
          <button className="btn primary" onClick={retry}>Try again</button>
          {appPlayer.available && <button className="btn ghost" onClick={() => appPlayer.changeServer()}>Another server</button>}
        </div>
      </div>
    </div>
  );
}

function AuthScreen({ state, onDone }: { state: AuthState; onDone: () => void }) {
  const setup = state.needs_setup;
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    try {
      // the app names its phone, for the account's list of devices
      const device = appPlayer.available ? appPlayer.deviceName : "";
      await api.post(setup ? "/api/auth/setup" : mode === "signup" ? "/api/auth/signup" : "/api/auth/login", { username, password, device });
      onDone();
    } catch (err) {
      setError((err as Error).message);
    }
  };
  return (
    <div className="auth">
      <ThemeApplier />
      <form className="auth-card" onSubmit={submit}>
        <div className="logo" style={{ marginBottom: 26 }}>
          <Logo name={state.site_name} />
        </div>
        <Kicker parts={[setup ? "First start" : "Welcome back", `v${state.version}`]} />
        <Display l1={setup ? "Set up" : mode === "signup" ? "Join" : "Sign in"} l2={setup ? "Muzix" : undefined} small />
        {setup && <p className="lede">First the admin account. Then you pick the folders your music is in, and what else this server should do.</p>}
        <div className="field"><label htmlFor="u">Username</label>
          <input id="u" className="input" autoFocus autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} /></div>
        <div className="field"><label htmlFor="p">Password</label>
          <input id="p" className="input" type="password" autoComplete={setup ? "new-password" : "current-password"} value={password} onChange={(e) => setPassword(e.target.value)} /></div>
        {error && <p className="error-text">{error}</p>}
        <div className="row-actions">
          <button className="btn primary" type="submit">{setup ? "Create admin" : mode === "signup" ? "Create account" : "Sign in"}</button>
          {!setup && state.allow_signup && (
            <button type="button" className="btn ghost" onClick={() => setMode(mode === "login" ? "signup" : "login")}>
              {mode === "login" ? "Create an account" : "I have an account"}
            </button>
          )}
        </div>
      </form>
    </div>
  );
}

export default function App() {
  const state = useQuery({ queryKey: ["auth"], queryFn: () => api.get<AuthState>("/api/auth/state"), staleTime: Infinity });
  const setUser = useUi((s) => s.setUser);
  useEffect(() => {
    const s = state.data;
    if (!s) return;
    useUi.setState({ siteName: s.site_name, modules: s.modules });
    if (s.user) setUser(s.user);
    // the app keeps it, to open offline (downloads.ts)
    if (s.user && !s.offline && appPlayer.available) appPlayer.signedIn(s);
  }, [state.data, setUser]);
  useEffect(() => {
    // the app lost the server, or found it again: everything from what it can reach now
    const on = () => {
      state.refetch();
      queryClient.invalidateQueries();
    };
    window.addEventListener("muzix:reachable", on);
    return () => window.removeEventListener("muzix:reachable", on);
  }, [state]);
  useEffect(() => {
    const on = () => state.refetch();
    window.addEventListener("muzix:unauthorized", on);
    return () => window.removeEventListener("muzix:unauthorized", on);
  }, [state]);
  if (!state.data) return state.isError ? <Unreachable retry={() => state.refetch()} /> : <div className="auth"><Loading /></div>;
  if (!state.data.user) return <AuthScreen state={state.data} onDone={() => state.refetch()} />;
  if (state.data.setup) {
    return <Suspense fallback={<div className="auth"><Loading /></div>}><Setup onDone={() => state.refetch()} /></Suspense>;
  }
  return <Shell />;
}
