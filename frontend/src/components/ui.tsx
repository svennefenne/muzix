import { ChevronDown } from "lucide-react";
import { type ReactNode, useEffect, useRef, useState } from "react";
import { create } from "zustand";

/** Cover art with a generated fallback (colour from the name, big initials). */
export function Art({ src, name, size = 300, round, className = "", onClick }: {
  src?: string | null; name?: string; size?: number; round?: boolean; className?: string; onClick?: () => void;
}) {
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    setFailed(false);
  }, [src]);
  const pixel = document.documentElement.dataset.artfx === "pixel";
  const url = src && src.startsWith("/api/art/") ? `${src}${src.includes("?") ? "&" : "?"}s=${pixel ? 64 : size}` : src;
  const hue = hashHue(name || "");
  return (
    <div className={`art ${round ? "round" : ""} ${className}`} onClick={onClick}
         style={!url || failed ? { background: `linear-gradient(135deg, hsl(${hue} 55% 38%), hsl(${(hue + 50) % 360} 60% 22%))` } : undefined}>
      {url && !failed ? <img src={url} alt="" loading="lazy" onError={() => setFailed(true)} />
        : <div className="art-fallback">{initials(name || "?")}</div>}
    </div>
  );
}

export function hashHue(s: string) {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) % 360;
  return h;
}

function initials(s: string) {
  const words = s.replace(/[^\p{L}\p{N} ]/gu, " ").split(/\s+/).filter(Boolean);
  return (words.length > 1 ? words[0][0] + words[1][0] : (words[0] || "?").slice(0, 2)).toUpperCase();
}

/** Two-tone headline in the Deck Force style. */
export function Display({ l1, l2, small }: { l1: string; l2?: string; small?: boolean }) {
  return (
    <h1 className={`display ${small ? "small" : ""}`}>
      <span className="l1" data-text={l1}>{l1}</span>
      {l2 && <span className="l2" data-text={l2}>{l2}</span>}
    </h1>
  );
}

/** Spotify's blue dot: a new episode not played yet, or a podcast with ones you haven't seen. */
export function NewDot({ label }: { label: string }) {
  return <span className="new-dot" role="img" aria-label={label} title={label} />;
}

export function Kicker({ parts }: { parts: (string | number | null | undefined | false)[] }) {
  const shown = parts.filter((p) => p !== null && p !== undefined && p !== false && p !== "");
  return (
    <div className="kicker">
      {shown.map((p, i) => (
        <span key={i}>{i > 0 && <span className="sep">·</span>}{p}</span>
      ))}
    </div>
  );
}

export function Stripes() {
  return <div className="stripes">{Array.from({ length: 6 }, (_, i) => <span key={i} />)}</div>;
}

/** A titled section; with `onToggle` its title folds it away and opens it again. */
export function Section({ kicker, title, more, children, open = true, onToggle }: {
  kicker?: string; title: string; more?: ReactNode; children: ReactNode; open?: boolean; onToggle?: () => void;
}) {
  return (
    <section className="section">
      <div className="section-head">
        <div>
          {kicker && <div className="kicker">{kicker}</div>}
          <h2 className="h2">
            {onToggle ? (
              <button className="section-toggle" aria-expanded={open} onClick={onToggle}>
                {title}<ChevronDown size={22} aria-hidden />
              </button>
            ) : title}
          </h2>
        </div>
        {more}
      </div>
      {open && children}
    </section>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return <div className="empty"><div className="h3">{title}</div>{children}</div>;
}

export function Loading() {
  return <div className="dim" style={{ padding: 40 }}>Loading…</div>;
}

export function Switch({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label?: string }) {
  return (
    <label className="switch" title={label}>
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} aria-label={label} />
      <span />
    </label>
  );
}

/** Calls back when the element scrolls into view (infinite lists). */
export function useInView(cb: () => void, enabled = true) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!enabled || !ref.current) return;
    const io = new IntersectionObserver((e) => e[0].isIntersecting && cb(), { rootMargin: "600px" });
    io.observe(ref.current);
    return () => io.disconnect();
  }, [cb, enabled]);
  return ref;
}

// ---------------------------------------------------------------- context menu & modal

export interface MenuItem {
  label?: string;
  icon?: ReactNode;
  onClick?: () => void;
  sep?: boolean;
  heading?: string;
}

interface MenuState {
  open: { x: number; y: number; items: MenuItem[] } | null;
  show: (e: { clientX: number; clientY: number }, items: MenuItem[]) => void;
  hide: () => void;
}

export const useMenu = create<MenuState>((set) => ({
  open: null,
  show: (e, items) => set({ open: { x: e.clientX, y: e.clientY, items } }),
  hide: () => set({ open: null }),
}));

export function MenuHost() {
  const { open, hide } = useMenu();
  const ref = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState({ x: 0, y: 0 });
  useEffect(() => {
    if (!open) return;
    const close = (e: Event) => {
      if (ref.current && e.target instanceof Node && ref.current.contains(e.target)) return;
      hide();
    };
    const key = (e: KeyboardEvent) => e.key === "Escape" && hide();
    window.addEventListener("mousedown", close);
    window.addEventListener("scroll", hide, true);
    window.addEventListener("keydown", key);
    return () => {
      window.removeEventListener("mousedown", close);
      window.removeEventListener("scroll", hide, true);
      window.removeEventListener("keydown", key);
    };
  }, [open, hide]);
  useEffect(() => {
    if (!open || !ref.current) return;
    const r = ref.current.getBoundingClientRect();
    setPos({ x: Math.min(open.x, window.innerWidth - r.width - 8), y: Math.min(open.y, window.innerHeight - r.height - 8) });
  }, [open]);
  if (!open) return null;
  return (
    <div className="menu" ref={ref} style={{ left: pos.x || open.x, top: pos.y || open.y }} role="menu">
      {open.items.map((it, i) => it.sep ? <hr key={i} /> : it.heading ? <div className="label" key={i}>{it.heading}</div> : (
        <button key={i} role="menuitem" onClick={() => { hide(); it.onClick?.(); }}>{it.icon}{it.label}</button>
      ))}
    </div>
  );
}

export function Modal({ onClose, children, className = "" }: { onClose: () => void; children: ReactNode; className?: string }) {
  useEffect(() => {
    const key = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [onClose]);
  return (
    <div className="modal-bg" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`modal ${className}`} role="dialog">{children}</div>
    </div>
  );
}
