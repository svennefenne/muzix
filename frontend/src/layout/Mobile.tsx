/** The phone layout's own pieces (they hide on larger screens): a Spotify-style
 * mini-player and a bottom tab bar whose "More" sheet holds the other sections. */

import {
  BookOpen, Download, FolderPlus, Gamepad2, Heart, House, Laptop, Library, LogOut, MoreHorizontal, Pause, Play, Podcast, Radio, Search, Settings, Shield,
  SkipForward, Smartphone, Wrench, X,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { toggleQueuedLike } from "../actions";
import { api } from "../api";
import { appVersion, useAppUpdate } from "../appUpdate";
import { CastButton, CastNote, usePlaysElsewhere } from "../components/CastButton";
import { Art, NewDot, SwitchLook } from "../components/ui";
import { appPlayer, useShell } from "../player/app";
import { engine } from "../player/engine";
import { usePlayer } from "../store/player";
import { useShown } from "../modules";
import { useUi } from "../store/ui";
import { useSwipeSongs } from "../swipeSongs";
import { hasNext as canNext, SpokenSteps } from "./PlayerBar";

const MORE = [
  { to: "/podcasts", label: "Podcasts", sub: "Your shows and new episodes", icon: Podcast },
  { to: "/vgm", label: "VGM", sub: "Chiptunes and tracker music", icon: Gamepad2 },
  { to: "/audiobooks", label: "Audiobooks", sub: "Pick up where you left off", icon: BookOpen },
  { to: "/radio", label: "Radio", sub: "Stations from all over the world", icon: Radio },
];

export function MiniPlayer() {
  const cur = usePlayer((s) => (s.index >= 0 ? s.queue[s.index] : null));
  const playing = usePlayer((s) => s.playing);
  const live = usePlayer((s) => s.liveTitle);
  const error = usePlayer((s) => s.error);
  const frac = usePlayer((s) => (s.duration ? Math.min(1, s.position / s.duration) : 0));
  const castOn = usePlaysElsewhere();
  const hasNext = usePlayer(canNext);
  const open = useUi((s) => s.setNowPlayingOpen);
  const box = useRef<HTMLDivElement>(null);
  const slide = useRef<HTMLDivElement>(null);
  const spoken = cur?.kind === "book" || cur?.kind === "episode";
  const swiped = useSwipeSongs(box, !!cur && !spoken, slide);
  if (!cur) return <div className="miniplayer-slot" />;
  return (
    <div className="miniplayer-slot">
      {/* a tap opens the full player, except on its buttons; a swipe changes the song */}
      <div ref={box} className="miniplayer" role="button" tabIndex={0} aria-label="Open the player"
           onClick={(e) => !swiped.current && !(e.target as Element).closest("button") && open(true)}
           onKeyDown={(e) => e.key === "Enter" && e.target === e.currentTarget && open(true)}>
        <div className="mp-now">
          <div ref={slide} className="mp-slide">
            <Art src={cur.art} name={cur.album || cur.title} size={96} peer={cur.peer} />
            <div className="mp-text">
              <div className="mp-title ellipsis">{live || cur.title}</div>
              {castOn && !error ? <CastNote className="mp-sub cast-note" />
                : <div className={`mp-sub ellipsis ${error ? "error-text" : ""}`}>{error || (live ? cur.title : cur.artist)}</div>}
            </div>
          </div>
        </div>
        {/* cast and like go first when the screen is narrow (see .miniplayer-slot); an episode or
            audiobook has the steps and the skips instead, and the full player has cast */}
        {spoken ? <SpokenSteps className="mp-play" size={22} stepSize={17} /> : <CastButton className="mp-play mp-cast" size={20} />}
        {cur.kind === "track" && !cur.foreign && (
          <button className={`mp-play mp-like ${cur.liked ? "on" : ""}`} aria-label="Like" aria-pressed={!!cur.liked}
                  onClick={() => toggleQueuedLike(cur)}>
            <Heart size={20} fill={cur.liked ? "currentColor" : "none"} />
          </button>
        )}
        <button className="mp-play" aria-label={playing ? "Pause" : "Play"} onClick={() => engine.toggle()}>
          {playing ? <Pause size={22} fill="currentColor" /> : <Play size={22} fill="currentColor" />}
        </button>
        {spoken ? <SpokenSteps forward className="mp-play" size={22} stepSize={17} /> : (
          <button className="mp-play" aria-label="Next song" disabled={!hasNext} onClick={() => engine.next()}>
            <SkipForward size={20} fill="currentColor" />
          </button>
        )}
        {cur.kind !== "radio" && <div className="mp-progress"><div style={{ width: `${frac * 100}%` }} /></div>}
      </div>
    </div>
  );
}

export function TabBar() {
  const [more, setMore] = useState(false);
  const update = useAppUpdate();
  const { pathname } = useLocation();
  const inMore = ["/vgm", "/audiobooks", "/podcasts", "/radio", "/settings", "/admin"].some((p) => pathname.startsWith(p));
  useEffect(() => {
    setMore(false);
  }, [pathname]);
  const tab = ({ isActive }: { isActive: boolean }) => `tb-item ${isActive ? "on" : ""}`;
  return (
    <>
      <nav className="tabbar" aria-label="Main">
        <NavLink to="/" end className={tab}><House size={22} /><span>Home</span></NavLink>
        <NavLink to="/search" className={tab}><Search size={22} /><span>Search</span></NavLink>
        <NavLink to="/library" className={tab}><Library size={22} /><span>Library</span></NavLink>
        <button className={`tb-item ${inMore || more ? "on" : ""}`} aria-expanded={more} onClick={() => setMore(!more)}>
          <MoreHorizontal size={22} /><span>More</span>
          {update && <NewDot label={`Version ${update.version} of the app is out`} />}
        </button>
      </nav>
      {more && <MoreSheet onClose={() => setMore(false)} />}
    </>
  );
}

function MoreSheet({ onClose }: { onClose: () => void }) {
  const nav = useNavigate();
  const user = useUi((s) => s.user);
  const adminMode = useUi((s) => s.adminMode);
  const setAdminMode = useUi((s) => s.setAdminMode);
  const update = useAppUpdate();
  const more = useShown(MORE);
  useEffect(() => {
    const key = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [onClose]);
  // the app (0.9 on) has no admin pages: its Admin is the server's web version, in the browser
  const inApp = useShell((s) => s.opens);
  // the app's own library (this phone's or computer's music) or the server's: a switch
  const library = useShell((s) => s.library);
  const computer = useShell((s) => !!s.desktop);
  const go = (to: string) => { if (to === "/admin" && inApp) appPlayer.openOnServer(to); else nav(to); onClose(); };
  const items = [
    ...more,
    { to: "/settings", label: "Settings", sub: "Colours, playback and your account", icon: Settings },
    ...(user?.is_admin && library !== "local" ? [{ to: "/admin", label: inApp ? "Admin on the server" : "Admin", sub: "Library folders, uploads, users", icon: Shield }] : []),
  ];
  return (
    <div className="sheet-bg" onClick={onClose}>
      <div className="sheet" role="dialog" aria-label="More" onClick={(e) => e.stopPropagation()}>
        <div className="sheet-head">
          <span className="avatar">{(user?.username || "?")[0].toUpperCase()}</span>
          <b className="grow">{user?.username}</b>
          <button className="iconbtn" aria-label="Close" onClick={onClose}><X size={16} /></button>
        </div>
        {library && (
          <button className="sheet-item" role="switch" aria-checked={library === "local"}
                  onClick={() => { appPlayer.useLibrary(library === "local" ? "server" : "local"); onClose(); }}>
            {computer ? <Laptop size={22} /> : <Smartphone size={22} />}
            <span><b>{computer ? "This computer's music" : "This phone's music"}</b>
              <small>{library === "local" ? `On: the music in this ${computer ? "computer" : "phone"}'s folders` : "Off: the server's music"}</small></span>
            <SwitchLook on={library === "local"} />
          </button>
        )}
        {library === "local" && (
          <button className="sheet-item" onClick={() => { appPlayer.addFolder(); onClose(); }}>
            <FolderPlus size={22} />
            <span><b>Add a music folder</b><small>The app only reads it</small></span>
          </button>
        )}
        {items.map(({ to, label, sub, icon: Icon }) => (
          <button key={to} className="sheet-item" onClick={() => go(to)}>
            <Icon size={22} />
            <span><b>{label}</b><small>{sub}</small></span>
          </button>
        ))}
        {user?.is_admin && !inApp && (
          <button className="sheet-item" role="switch" aria-checked={adminMode} onClick={() => { setAdminMode(!adminMode); onClose(); }}>
            <Wrench size={22} />
            <span><b>Admin mode</b><small>A cog on every item, to edit, hide or delete it</small></span>
            <SwitchLook on={adminMode} />
          </button>
        )}
        {update && (
          <button className="sheet-item" onClick={() => { appPlayer.update(update.url); onClose(); }}>
            <Download size={22} />
            <span><b>Update the app to {update.version}</b><small>You have {appVersion()}</small></span>
          </button>
        )}
        {/* the phone's own library has no login */}
        {library !== "local" && (
          <button className="sheet-item" onClick={() => api.post("/api/auth/logout").then(() => location.assign("/"))}>
            <LogOut size={22} /><span><b>Sign out</b></span>
          </button>
        )}
      </div>
    </div>
  );
}
