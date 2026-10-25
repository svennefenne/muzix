import { Activity, House, Monitor, Moon, Search, Settings, Shield, Sun, SunMoon, LogOut } from "lucide-react";
import { useEffect, useMemo } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { api } from "../api";
import { Logo } from "../components/Logo";
import { useMenu } from "../components/ui";
import { usePlayer } from "../store/player";
import { useUi } from "../store/ui";
import { QuickSearch } from "./QuickSearch";

export const TABS = [
  { to: "/", label: "Home", end: true },
  { to: "/library", label: "Library" },
  { to: "/vgm", label: "VGM" },
  { to: "/audiobooks", label: "Audiobooks" },
  { to: "/podcasts", label: "Podcasts" },
  { to: "/radio", label: "Radio" },
  { to: "/spotify", label: "Spotify" },
];

const QUOTES: [string, string, string][] = [
  ["Without music, life would be a mistake.", "Friedrich Nietzsche", "Twilight of the Idols"],
  ["If music be the food of love, play on.", "William Shakespeare", "Twelfth Night"],
  ["Where words fail, music speaks.", "Hans Christian Andersen", "What the Moon Saw"],
  ["After silence, that which comes nearest to expressing the inexpressible is music.", "Aldous Huxley", "Music at Night"],
  ["Music is the space between the notes.", "Claude Debussy", "attributed"],
  ["Music expresses that which cannot be said.", "Victor Hugo", "William Shakespeare"],
  ["One good thing about music, when it hits you, you feel no pain.", "Bob Marley", "Trenchtown Rock"],
  ["It's dangerous to go alone! Take this.", "Old Man", "The Legend of Zelda"],
  ["Do a barrel roll!", "Peppy Hare", "Star Fox 64"],
  ["Insert coin to continue.", "Every arcade cabinet", "1978 onwards"],
  ["The only truth is music.", "Jack Kerouac", "Mexico City Blues"],
  ["Music is the wine that fills the cup of silence.", "Robert Fripp", "attributed"],
];

function Ticker() {
  const cur = usePlayer((s) => (s.index >= 0 ? s.queue[s.index] : null));
  const live = usePlayer((s) => s.liveTitle);
  const quote = useMemo(() => QUOTES[Math.floor(Math.random() * QUOTES.length)], []);
  if (cur?.kind === "radio")
    return <div className="ticker">- On air: {live || "…"}, <em>{cur.title}</em></div>;
  if (cur)
    return <div className="ticker">- Now playing: {cur.title}, {cur.artist} {cur.album && <em>({cur.album})</em>}</div>;
  return <div className="ticker">- {quote[0]} <em>{quote[1]} ({quote[2]})</em></div>;
}

function LevelRing() {
  const pos = usePlayer((s) => s.position);
  const dur = usePlayer((s) => s.duration);
  const frac = dur ? Math.min(1, pos / dur) : 0;
  const r = 17;
  const len = 2 * Math.PI * r;
  return (
    <svg className="ring" viewBox="0 0 38 38">
      <circle cx="19" cy="19" r={r} fill="none" stroke="var(--primary)" strokeWidth="2"
              strokeDasharray={`${len * frac} ${len}`} transform="rotate(-90 19 19)" strokeLinecap="round" />
    </svg>
  );
}

export function TopBar() {
  const { user, mode, setPref, setNowPlayingOpen, siteName } = useUi();
  const nav = useNavigate();
  const loc = useLocation();
  const atHome = loc.pathname === "/";
  const showMenu = useMenu((s) => s.show);
  const tabs = user?.is_admin ? [...TABS, { to: "/admin", label: "Admin" }] : TABS;

  // Q / E step through the sections, like a console's shoulder buttons
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey || e.altKey || isTyping(e)) return;
      const k = e.key.toLowerCase();
      if (k !== "q" && k !== "e") return;
      const idx = tabs.findIndex((t) => (t.to === "/" ? loc.pathname === "/" : loc.pathname.startsWith(t.to)));
      const next = (idx + (k === "e" ? 1 : -1) + tabs.length) % tabs.length;
      nav(tabs[next].to);
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [tabs, loc.pathname, nav]);

  const nextMode = mode === "system" ? "dark" : mode === "dark" ? "light" : "system";
  const ModeIcon = mode === "system" ? SunMoon : mode === "dark" ? Moon : Sun;
  const userMenu = (e: React.MouseEvent) => showMenu(e, [
    { heading: user?.username || "" },
    { label: "Settings", icon: <Settings size={16} />, onClick: () => nav("/settings") },
    ...(user?.is_admin ? [{ label: "Admin", icon: <Shield size={16} />, onClick: () => nav("/admin") }] : []),
    { sep: true },
    { label: "Sign out", icon: <LogOut size={16} />, onClick: () => api.post("/api/auth/logout").then(() => location.assign("/")) },
  ]);

  return (
    <header className="topbar">
      <div className="topbar-left">
        <NavLink to="/" className="logo" aria-label="Home">
          <Logo name={siteName || "Muzix"} />
        </NavLink>
        <Ticker />
      </div>
      <div className="topbar-center">
        <NavLink to="/" end className={`iconbtn homebtn ${atHome ? "on" : ""}`} title="Home" aria-label="Home"><House size={17} /></NavLink>
        <QuickSearch />
      </div>
      <div className="topbar-right">
        <button className="iconbtn hide-sm" title="Now playing" onClick={() => setNowPlayingOpen(true)}>
          <LevelRing /><Activity size={15} />
        </button>
        <button className="iconbtn show-sm" title="Search (/)" onClick={() => nav("/search")}><Search size={15} /></button>
        <button className="iconbtn hide-sm" title={`Light/dark: ${mode} (click for ${nextMode})`} onClick={() => setPref("mode", nextMode)}>
          <ModeIcon size={15} />
        </button>
        <button className="iconbtn hide-sm trim-2" title="Fullscreen (F11)" onClick={toggleFullscreen}><Monitor size={15} /></button>
        <button className="pill userpill" onClick={userMenu} aria-label={`Account: ${user?.username}`}>
          <span className="avatar">{(user?.username || "?")[0].toUpperCase()}</span>
          <span className="uname">{user?.username}</span>
        </button>
      </div>
    </header>
  );
}

export function isTyping(e: KeyboardEvent) {
  const t = e.target as HTMLElement;
  return t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable);
}

export function toggleFullscreen() {
  if (document.fullscreenElement) document.exitFullscreen();
  else document.documentElement.requestFullscreen().catch(() => {});
}
