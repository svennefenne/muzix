import {
  Activity, BookOpen, Disc3, Gamepad2, House, LogOut, Monitor, Moon, Music2, Podcast, Radio, Search, Settings, Shield, Sun, SunMoon,
} from "lucide-react";
import { useEffect } from "react";
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

/** The sections, as pills in the top bar on desktops (phones have them on Home). */
const SECTIONS = [
  { to: "/library", label: "Music", icon: Disc3 },
  { to: "/vgm", label: "VGM", icon: Gamepad2 },
  { to: "/audiobooks", label: "Audiobooks", icon: BookOpen },
  { to: "/podcasts", label: "Podcasts", icon: Podcast },
  { to: "/radio", label: "Radio", icon: Radio },
  { to: "/spotify", label: "Spotify", icon: Music2 },
];

function SectionPills() {
  return (
    <nav className="topnav" aria-label="Sections">
      {SECTIONS.map(({ to, label, icon: Icon }) => (
        <NavLink key={to} to={to} className="topnav-pill" title={label} aria-label={label}>
          <Icon size={16} /><span>{label}</span>
        </NavLink>
      ))}
    </nav>
  );
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
      <NavLink to="/" className="logo" aria-label="Home">
        <Logo name={siteName || "Muzix"} />
      </NavLink>
      <SectionPills />
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
