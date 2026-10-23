/** The phone layout's own pieces (they hide on larger screens): a Spotify-style
 * mini-player and a bottom tab bar whose "More" sheet holds the other sections. */

import {
  BookOpen, Gamepad2, House, Library, LogOut, MoreHorizontal, Music2, Pause, Play, Podcast, Radio, Search, Settings, Shield, X,
} from "lucide-react";
import { useEffect, useState } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { api } from "../api";
import { Art } from "../components/ui";
import { engine } from "../player/engine";
import { usePlayer } from "../store/player";
import { useUi } from "../store/ui";

const MORE = [
  { to: "/vgm", label: "VGM", sub: "Chiptunes and tracker music", icon: Gamepad2 },
  { to: "/audiobooks", label: "Audiobooks", sub: "Pick up where you left off", icon: BookOpen },
  { to: "/podcasts", label: "Podcasts", sub: "Your shows and new episodes", icon: Podcast },
  { to: "/radio", label: "Radio", sub: "Stations from all over the world", icon: Radio },
  { to: "/spotify", label: "Spotify", sub: "Your Spotify, played in Muzix", icon: Music2 },
];

export function MiniPlayer() {
  const cur = usePlayer((s) => (s.index >= 0 ? s.queue[s.index] : null));
  const playing = usePlayer((s) => s.playing);
  const live = usePlayer((s) => s.liveTitle);
  const error = usePlayer((s) => s.error);
  const frac = usePlayer((s) => (s.duration ? Math.min(1, s.position / s.duration) : 0));
  const open = useUi((s) => s.setNowPlayingOpen);
  if (!cur) return <div className="miniplayer-slot" />;
  return (
    <div className="miniplayer-slot">
      <div className="miniplayer" role="button" tabIndex={0} aria-label="Open the player"
           onClick={() => open(true)} onKeyDown={(e) => e.key === "Enter" && open(true)}>
        <Art src={cur.art} name={cur.album || cur.title} size={96} />
        <div className="mp-text">
          <div className="mp-title ellipsis">{live || cur.title}</div>
          <div className={`mp-sub ellipsis ${error ? "error-text" : ""}`}>{error || (live ? cur.title : cur.artist)}</div>
        </div>
        <button className="mp-play" aria-label={playing ? "Pause" : "Play"}
                onClick={(e) => { e.stopPropagation(); engine.toggle(); }}>
          {playing ? <Pause size={22} fill="currentColor" /> : <Play size={22} fill="currentColor" />}
        </button>
        {cur.kind !== "radio" && <div className="mp-progress"><div style={{ width: `${frac * 100}%` }} /></div>}
      </div>
    </div>
  );
}

export function TabBar() {
  const [more, setMore] = useState(false);
  const { pathname } = useLocation();
  const inMore = ["/vgm", "/audiobooks", "/podcasts", "/radio", "/spotify", "/settings", "/admin"].some((p) => pathname.startsWith(p));
  useEffect(() => setMore(false), [pathname]);
  const tab = ({ isActive }: { isActive: boolean }) => `tb-item ${isActive ? "on" : ""}`;
  return (
    <>
      <nav className="tabbar" aria-label="Main">
        <NavLink to="/" end className={tab}><House size={22} /><span>Home</span></NavLink>
        <NavLink to="/search" className={tab}><Search size={22} /><span>Search</span></NavLink>
        <NavLink to="/library" className={tab}><Library size={22} /><span>Library</span></NavLink>
        <button className={`tb-item ${inMore || more ? "on" : ""}`} aria-expanded={more} onClick={() => setMore(!more)}>
          <MoreHorizontal size={22} /><span>More</span>
        </button>
      </nav>
      {more && <MoreSheet onClose={() => setMore(false)} />}
    </>
  );
}

function MoreSheet({ onClose }: { onClose: () => void }) {
  const nav = useNavigate();
  const user = useUi((s) => s.user);
  useEffect(() => {
    const key = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [onClose]);
  const go = (to: string) => { nav(to); onClose(); };
  const items = [
    ...MORE,
    { to: "/settings", label: "Settings", sub: "Colours, playback and your account", icon: Settings },
    ...(user?.is_admin ? [{ to: "/admin", label: "Admin", sub: "Library folders, uploads, users", icon: Shield }] : []),
  ];
  return (
    <div className="sheet-bg" onClick={onClose}>
      <div className="sheet" role="dialog" aria-label="More" onClick={(e) => e.stopPropagation()}>
        <div className="sheet-head">
          <span className="avatar">{(user?.username || "?")[0].toUpperCase()}</span>
          <b className="grow">{user?.username}</b>
          <button className="iconbtn" aria-label="Close" onClick={onClose}><X size={16} /></button>
        </div>
        {items.map(({ to, label, sub, icon: Icon }) => (
          <button key={to} className="sheet-item" onClick={() => go(to)}>
            <Icon size={22} />
            <span><b>{label}</b><small>{sub}</small></span>
          </button>
        ))}
        <button className="sheet-item" onClick={() => api.post("/api/auth/logout").then(() => location.assign("/"))}>
          <LogOut size={22} /><span><b>Sign out</b></span>
        </button>
      </div>
    </div>
  );
}
