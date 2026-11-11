import {
  Activity, BookOpen, Disc3, Download, FolderPlus, Gamepad2, House, Laptop, LogOut, MessageCircle, Moon, Podcast, Radio, RefreshCw, Settings, Shield,
  Smartphone, Sun, SunMoon, Wrench,
} from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { api } from "../api";
import { checkForUpdates, useAppUpdate, useAppVersion } from "../appUpdate";
import { ChatButton } from "../chat/Chat";
import { useChat, useChatOn } from "../chat/store";
import { Logo } from "../components/Logo";
import { useShown } from "../modules";
import { NewDot, useMenu } from "../components/ui";
import { appPlayer, useShell } from "../player/app";
import { freshPodcasts, usePlayer, useStartedEpisodes } from "../store/player";
import { useUi } from "../store/ui";
import type { Home } from "../types";
import { QuickSearch } from "./QuickSearch";
import { Avatar } from "../components/Avatar";

export const TABS = [
  { to: "/", label: "Home", end: true },
  { to: "/library", label: "Library" },
  { to: "/podcasts", label: "Podcasts" },
  { to: "/vgm", label: "VGM" },
  { to: "/audiobooks", label: "Audiobooks" },
  { to: "/radio", label: "Radio" },
];

/** The sections, as pills in the top bar on desktops (phones have them as chips: PhoneChips). */
const SECTIONS = [
  { to: "/library", label: "Music", icon: Disc3, tip: "Music: your library" },
  { to: "/podcasts", label: "Podcasts", icon: Podcast, tip: "Podcasts: your shows and new episodes" },
  { to: "/vgm", label: "VGM", icon: Gamepad2, tip: "VGM: chiptunes and tracker music" },
  { to: "/audiobooks", label: "Audiobooks", icon: BookOpen, tip: "Audiobooks: pick up where you left off" },
  { to: "/radio", label: "Radio", icon: Radio, tip: "Radio: stations from all over the world" },
];

function SectionPills() {
  const sections = useShown(SECTIONS);
  return (
    <nav className="topnav" aria-label="Sections">
      {sections.map(({ to, label, icon: Icon, tip }) => (
        <NavLink key={to} to={to} className="topnav-pill" data-tip={tip} data-tip-key="Q / E" aria-label={label}>
          <Icon size={16} /><span>{label}</span>
        </NavLink>
      ))}
    </nav>
  );
}

/** The sections on phones, as chips between the logo and the avatar: All (Home) first, swiped sideways
 * when they don't all fit. */
const CHIPS = [
  { to: "/library", label: "Music" }, { to: "/podcasts", label: "Podcasts" }, { to: "/audiobooks", label: "Audiobooks" },
  { to: "/vgm", label: "VGM" }, { to: "/radio", label: "Radio" },
];

function PhoneChips() {
  const sections = useShown(CHIPS);
  const { pathname } = useLocation();
  const row = useRef<HTMLElement>(null);
  const started = useStartedEpisodes();
  // Home's data, once Home has it: Podcasts has the dot while a show has something new, as Home's tiles do
  const home = useQuery({ queryKey: ["home"], queryFn: () => api.get<Home>("/api/home"), enabled: false }).data;
  const fresh = !!home && freshPodcasts(home, started).some((p) => p.dot);
  // the section you're in stays in sight
  useEffect(() => {
    row.current?.querySelector(".hchip.on")?.scrollIntoView({ inline: "nearest", block: "nearest" });
  }, [pathname]);
  const chip = ({ isActive }: { isActive: boolean }) => `hchip ${isActive ? "on" : ""}`;
  return (
    <nav ref={row} className="phone-chips phone-only" aria-label="Sections">
      <NavLink to="/" end className={chip}>All</NavLink>
      {sections.map(({ to, label }) => (
        <NavLink key={to} to={to} className={chip}>
          {to === "/podcasts" && fresh && <NewDot label="New episodes" />}{label}
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
  const { user, mode, setPref, setNowPlayingOpen, siteName, adminMode, setAdminMode } = useUi();
  const nav = useNavigate();
  const loc = useLocation();
  const atHome = loc.pathname === "/";
  const showMenu = useMenu((s) => s.show);
  const update = useAppUpdate();
  const version = useAppVersion();
  const shown = useShown(TABS);
  // the app (0.9 on) has no admin pages: its Admin is the server's web version
  const inApp = useShell((s) => s.opens);
  // the app's own library (this phone's or computer's music) or the server's: a switch
  const library = useShell((s) => s.library);
  const computer = useShell((s) => !!s.desktop);
  const chat = useChatOn();
  const tabs = user?.is_admin && !inApp ? [...shown, { to: "/admin", label: "Admin" }] : shown;

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
    ...(library ? [{ label: computer ? "This computer's music" : "This phone's music", icon: computer ? <Laptop size={16} /> : <Smartphone size={16} />,
                     checked: library === "local", onClick: () => appPlayer.useLibrary(library === "local" ? "server" : "local") },
                   // the app's own library: its folders are the app's to pick
                   ...(library === "local" ? [{ label: "Add a music folder", icon: <FolderPlus size={16} />, onClick: () => appPlayer.addFolder() }] : []),
                   { sep: true }] : []),
    ...(chat ? [{ label: "Messages", icon: <MessageCircle size={16} />, onClick: () => useChat.getState().show() }] : []),
    { label: "Settings", icon: <Settings size={16} />, onClick: () => nav("/settings") },
    // the app's own library's admin is the app's (Muzix Desktop's own server signs in as one): no server's Admin
    ...(user?.is_admin && library !== "local" ? [{ label: inApp ? "Admin on the server" : "Admin", icon: <Shield size={16} />,
                            onClick: () => (inApp ? appPlayer.openOnServer("/admin") : nav("/admin")) }] : []),
    // admin mode: a cog on every item, to edit, hide or delete it (in the apps too, on the server's music)
    ...(user?.is_admin && library !== "local" ? [{ label: "Admin mode", icon: <Wrench size={16} />, checked: adminMode, onClick: () => setAdminMode(!adminMode) }] : []),
    ...(update ? [{ label: `Update the app to ${update.version}`, icon: <Download size={16} />, onClick: () => appPlayer.update(update.url) }]
      : version ? [{ label: "Check for updates", icon: <RefreshCw size={16} />, onClick: checkForUpdates }] : []),
    // the app's own library has no login
    ...(library !== "local" ? [{ sep: true }, { label: "Sign out", icon: <LogOut size={16} />, onClick: () => api.post("/api/auth/logout").then(() => location.assign("/")) }] : []),
    // the app's own version, in small print at the end
    ...(version ? [{ sep: true }, { foot: `Muzix v${version}` }] : []),
  ]);

  return (
    <header className="topbar">
      <NavLink to="/" className="logo" aria-label="Home" data-tip="Home">
        <Logo name={siteName || "Muzix"} />
      </NavLink>
      <SectionPills />
      <PhoneChips />
      <div className="topbar-center">
        <NavLink to="/" end className={`iconbtn homebtn ${atHome ? "on" : ""}`} data-tip="Home" aria-label="Home"><House size={17} /></NavLink>
        <QuickSearch />
      </div>
      <div className="topbar-right">
        <button className="iconbtn hide-sm" aria-label="Now playing" data-tip="Now playing: the full-screen player" onClick={() => setNowPlayingOpen(true)}>
          <LevelRing /><Activity size={15} />
        </button>
        <button className="iconbtn hide-sm" aria-label="Light or dark" data-tip={`${{ system: "Matching your system", dark: "Dark", light: "Light" }[mode]}: click for ${nextMode === "system" ? "your system's choice" : nextMode}`}
                onClick={() => setPref("mode", nextMode)}>
          <ModeIcon size={15} />
        </button>
        <ChatButton />
        <button className="pill userpill" onClick={userMenu} aria-label={`Account: ${user?.username}`} data-tip="Settings, admin and signing out">
          <Avatar user={user} />
          <span className="uname">{user?.username}</span>
          {update && <NewDot label={`Version ${update.version} of the app is out`} />}
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
