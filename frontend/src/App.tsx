import { useQuery } from "@tanstack/react-query";
import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { api } from "./api";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { Logo } from "./components/Logo";
import { Display, Kicker, Loading, MenuHost } from "./components/ui";
import { MiniPlayer, TabBar } from "./layout/Mobile";
import { NowPanel } from "./layout/NowPanel";
import { Sidebar } from "./layout/Sidebar";
import { Footer, NowPlaying, PlaylistPicker, QueueDrawer, Toast } from "./layout/Overlays";
import { PlayerBar } from "./layout/PlayerBar";
import { focusQuickSearch } from "./layout/QuickSearch";
import { isTyping, TopBar } from "./layout/TopBar";
import Home from "./pages/Home";
import {
  AlbumPage, ArtistPage, GenrePage, TagPage, LibraryAlbums, LibraryArtistAlbums, LibraryArtists, LibraryGenreArtists, LibraryGenres,
  LibraryHome, Liked, PlaylistPage, Playlists, SearchPage,
} from "./pages/Library";
import { engine } from "./player/engine";
import { usePlayer } from "./store/player";
import { useUi } from "./store/ui";
import { ThemeApplier } from "./theme/ThemeApplier";
import type { AuthState } from "./types";

const Vgm = lazy(() => import("./pages/Vgm"));
const Books = lazy(() => import("./pages/Books"));
const BookPage = lazy(() => import("./pages/Books").then((m) => ({ default: m.BookPage })));
const Podcasts = lazy(() => import("./pages/Podcasts"));
const PodcastPage = lazy(() => import("./pages/Podcasts").then((m) => ({ default: m.PodcastPage })));
const Radio = lazy(() => import("./pages/Radio"));
const Spotify = lazy(() => import("./pages/Spotify"));
const Settings = lazy(() => import("./pages/Settings"));
const Admin = lazy(() => import("./pages/admin/Admin"));

function Shortcuts() {
  const nav = useNavigate();
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      const search = () => { e.preventDefault(); if (!focusQuickSearch()) nav("/search"); };
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") return search();
      if (isTyping(e) || e.ctrlKey || e.metaKey || e.altKey) return;
      const s = usePlayer.getState();
      if (e.key === " ") { e.preventDefault(); engine.toggle(); }
      else if (e.key === "/") search();
      else if (e.key === "ArrowRight") engine.seek(s.position + (e.shiftKey ? 30 : 5));
      else if (e.key === "ArrowLeft") engine.seek(s.position - (e.shiftKey ? 30 : 5));
      else if (e.key.toLowerCase() === "m") s.set({ muted: !s.muted });
      else if (e.key.toLowerCase() === "n") engine.next();
      else if (e.key.toLowerCase() === "p") engine.prev();
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [nav]);
  return null;
}

function Shell() {
  const loc = useLocation();
  const npPanel = useUi((s) => s.npPanel);
  const scroll = useRef<HTMLDivElement>(null);
  useEffect(() => {
    scroll.current?.scrollTo({ top: 0 });   // (newer Chrome returns a Promise here; an effect mustn't)
  }, [loc.pathname]);
  return (
    <div className="shell">
      <ThemeApplier />
      <Shortcuts />
      <TopBar />
      <div className={`workspace ${npPanel ? "np-open" : ""}`}>
      <Sidebar />
      <main className="frame">
        <div className="frame-scroll" ref={scroll}>
          <ErrorBoundary resetKey={loc.pathname}>
          <Suspense fallback={<div className="page"><Loading /></div>}>
            <Routes>
              <Route path="/" element={<Home />} />
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
              <Route path="/search" element={<SearchPage />} />
              <Route path="/vgm/*" element={<Vgm />} />
              <Route path="/audiobooks" element={<Books />} />
              <Route path="/audiobooks/:id" element={<BookPage />} />
              <Route path="/podcasts" element={<Podcasts />} />
              <Route path="/podcasts/:id" element={<PodcastPage />} />
              <Route path="/radio" element={<Radio />} />
              <Route path="/spotify/*" element={<Spotify />} />
              <Route path="/settings" element={<Settings />} />
              <Route path="/admin/*" element={<Admin />} />
              <Route path="*" element={<div className="page"><Display l1="Lost" l2="in space" /><p className="lede">That page doesn't exist.</p></div>} />
            </Routes>
          </Suspense>
          </ErrorBoundary>
        </div>
      </main>
      {npPanel && <NowPanel />}
      </div>
      <PlayerBar />
      <Footer />
      <MiniPlayer />
      <TabBar />
      <QueueDrawer />
      <NowPlaying />
      <PlaylistPicker />
      <MenuHost />
      <Toast />
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
      await api.post(setup ? "/api/auth/setup" : mode === "signup" ? "/api/auth/signup" : "/api/auth/login", { username, password });
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
        {setup && <p className="lede">Create the admin account. Muzix then adds the folders mounted at /music, /vgm and /audiobooks and starts scanning.</p>}
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
    useUi.setState({ siteName: s.site_name });
    if (s.user) setUser(s.user);
    api.get<{ skin_map: Record<string, string> }>("/api/themes/rules").then((r) => useUi.setState({ skinRules: r.skin_map || {} })).catch(() => {});
  }, [state.data, setUser]);
  useEffect(() => {
    const on = () => state.refetch();
    window.addEventListener("muzix:unauthorized", on);
    return () => window.removeEventListener("muzix:unauthorized", on);
  }, [state]);
  if (!state.data) return <div className="auth"><Loading /></div>;
  if (!state.data.user) return <AuthScreen state={state.data} onDone={() => state.refetch()} />;
  return <Shell />;
}
