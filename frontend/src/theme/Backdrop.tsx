/** The animated page background. Each skin picks a kind; all react to the music
 * through the engine's analyser (bass hits, loudness). */

import { useEffect, useRef } from "react";
import { engine } from "../player/engine";
import type { BackdropKind } from "./skins";

type Ctx = CanvasRenderingContext2D;
interface Scene {
  draw(g: Ctx, w: number, h: number, t: number, lv: { level: number; bass: number }, colors: Palette): void;
}
interface Palette { primary: string; secondary: string; text: string; bg: string; warning: string; success: string; error: string }

const rnd = (a: number, b: number) => a + Math.random() * (b - a);

function readColors(): Palette {
  const cs = getComputedStyle(document.documentElement);
  const v = (n: string, d: string) => cs.getPropertyValue(n).trim() || d;
  return {
    primary: v("--primary", "#f2a93b"), secondary: v("--secondary", "#e4572e"), text: v("--text", "#ffffff"),
    bg: v("--bg", "#0a1020"), warning: v("--warning", "#f2c14e"), success: v("--success", "#4fb286"),
    error: v("--error", "#ef5350"),
  };
}

// ---------------------------------------------------------------- particle helpers

function particles(n: number, make: () => any) {
  return Array.from({ length: n }, make);
}

const scenes: Record<string, () => Scene> = {
  space: () => {
    const stars = particles(220, () => ({ x: Math.random(), y: Math.random(), z: rnd(0.2, 1), tw: rnd(0, 6) }));
    return {
      draw(g, w, h, t, lv, c) {
        g.clearRect(0, 0, w, h);
        for (const s of stars) {
          const a = 0.25 + 0.55 * s.z * (0.6 + 0.4 * Math.sin(t / 900 + s.tw)) + lv.level * 0.4;
          g.fillStyle = c.text;
          g.globalAlpha = Math.min(1, a);
          const r = s.z * 1.3;
          g.fillRect(s.x * w, ((s.y + t * 0.000004 * s.z) % 1) * h, r, r);
        }
        g.globalAlpha = 1;
      },
    };
  },
  embers: () => {
    const ps: any[] = [];
    return {
      draw(g, w, h, _t, lv, c) {
        g.clearRect(0, 0, w, h);
        const spawn = 1 + Math.round(lv.bass * 8);
        for (let i = 0; i < spawn && ps.length < 260; i++)
          ps.push({ x: rnd(0, w), y: h + 10, vx: rnd(-0.3, 0.3), vy: rnd(-1.6, -0.5), life: 1, r: rnd(0.8, 2.6) });
        g.globalCompositeOperation = "lighter";
        for (let i = ps.length - 1; i >= 0; i--) {
          const p = ps[i];
          p.x += p.vx + Math.sin(p.y / 40) * 0.3;
          p.y += p.vy * (1 + lv.level * 2);
          p.life -= 0.0035;
          if (p.life <= 0 || p.y < -20) {
            ps.splice(i, 1);
            continue;
          }
          const grd = g.createRadialGradient(p.x, p.y, 0, p.x, p.y, p.r * 4);
          grd.addColorStop(0, c.warning);
          grd.addColorStop(0.4, c.primary);
          grd.addColorStop(1, "transparent");
          g.globalAlpha = p.life;
          g.fillStyle = grd;
          g.beginPath();
          g.arc(p.x, p.y, p.r * 4, 0, Math.PI * 2);
          g.fill();
        }
        g.globalAlpha = 1;
        g.globalCompositeOperation = "source-over";
        // glowing floor
        const fg = g.createLinearGradient(0, h, 0, h * 0.6);
        fg.addColorStop(0, c.primary + "55");
        fg.addColorStop(1, "transparent");
        g.fillStyle = fg;
        g.fillRect(0, h * 0.6, w, h * 0.4);
      },
    };
  },
  snow: () => {
    const flakes = particles(260, () => ({ x: Math.random(), y: Math.random(), r: rnd(0.4, 2.2), s: rnd(0.2, 1) }));
    return {
      draw(g, w, h, t, lv, c) {
        g.clearRect(0, 0, w, h);
        g.fillStyle = c.text;
        for (const f of flakes) {
          f.y += (0.0006 + f.s * 0.0012) * (1 + lv.level * 1.5);
          f.x += Math.sin(t / 2000 + f.y * 8) * 0.0004 + 0.0002;
          if (f.y > 1) { f.y = -0.02; f.x = Math.random(); }
          g.globalAlpha = 0.25 + f.s * 0.6;
          g.beginPath();
          g.arc((f.x % 1) * w, f.y * h, f.r, 0, Math.PI * 2);
          g.fill();
        }
        g.globalAlpha = 1;
      },
    };
  },
  lightning: () => {
    let flash = 0;
    let bolt: [number, number][] = [];
    let cool = 0;
    return {
      draw(g, w, h, _t, lv, c) {
        g.clearRect(0, 0, w, h);
        cool--;
        if ((lv.bass > 0.72 && cool <= 0) || Math.random() < 0.002) {
          flash = 1;
          cool = 40;
          bolt = [];
          let x = rnd(w * 0.1, w * 0.9);
          for (let y = 0; y < h * rnd(0.5, 0.9); y += rnd(18, 40)) {
            x += rnd(-40, 40);
            bolt.push([x, y]);
          }
        }
        if (flash > 0) {
          g.fillStyle = c.text;
          g.globalAlpha = flash * 0.12;
          g.fillRect(0, 0, w, h);
          g.globalAlpha = flash;
          g.strokeStyle = c.text;
          g.shadowColor = c.primary;
          g.shadowBlur = 24;
          g.lineWidth = 2.5;
          g.beginPath();
          bolt.forEach(([x, y], i) => (i ? g.lineTo(x, y) : g.moveTo(x, y)));
          g.stroke();
          g.shadowBlur = 0;
          g.globalAlpha = 1;
          flash -= 0.06;
        }
      },
    };
  },
  smoke: () => {
    const blobs = particles(9, () => ({ x: Math.random(), y: Math.random(), r: rnd(0.25, 0.55), vx: rnd(-1, 1), vy: rnd(-1, 1), k: Math.random() }));
    return {
      draw(g, w, h, t, lv, c) {
        g.clearRect(0, 0, w, h);
        for (const b of blobs) {
          const x = (b.x + Math.sin(t / 9000 + b.k * 9) * 0.15 * b.vx) * w;
          const y = (b.y + Math.cos(t / 11000 + b.k * 7) * 0.12 * b.vy) * h;
          const r = b.r * Math.max(w, h) * (1 + lv.level * 0.15);
          const grd = g.createRadialGradient(x, y, 0, x, y, r);
          grd.addColorStop(0, (b.k > 0.5 ? c.primary : c.secondary) + "26");
          grd.addColorStop(1, "transparent");
          g.fillStyle = grd;
          g.fillRect(0, 0, w, h);
        }
      },
    };
  },
  aurora: () => ({
    draw(g, w, h, t, lv, c) {
      g.clearRect(0, 0, w, h);
      g.globalCompositeOperation = "lighter";
      [c.primary, c.secondary, c.success].forEach((col, k) => {
        g.beginPath();
        for (let x = 0; x <= w; x += 12) {
          const y = h * (0.3 + k * 0.12) + Math.sin(x / 260 + t / (3000 + k * 900) + k) * 60 * (1 + lv.level)
            + Math.sin(x / 90 + t / 1700) * 14;
          x ? g.lineTo(x, y) : g.moveTo(x, y);
        }
        g.lineTo(w, h);
        g.lineTo(0, h);
        g.closePath();
        const grd = g.createLinearGradient(0, h * 0.2, 0, h);
        grd.addColorStop(0, col + "30");
        grd.addColorStop(0.5, col + "10");
        grd.addColorStop(1, "transparent");
        g.fillStyle = grd;
        g.fill();
      });
      g.globalCompositeOperation = "source-over";
    },
  }),
  fractal: () => {
    let rot = 0;
    return {
      draw(g, w, h, _t, lv, c) {
        g.fillStyle = c.bg + "33";
        g.fillRect(0, 0, w, h);
        const spec = engine.spectrum();
        rot += 0.002 + lv.bass * 0.02;
        g.save();
        g.translate(w / 2, h / 2);
        g.globalCompositeOperation = "lighter";
        const arms = 12;
        const R = Math.min(w, h) * 0.45;
        for (let ring = 0; ring < 5; ring++) {
          const amp = spec ? spec[4 + ring * 18] / 255 : 0.2;
          g.strokeStyle = ring % 2 ? c.secondary : c.primary;
          g.globalAlpha = 0.18 + amp * 0.5;
          g.lineWidth = 1 + amp * 2;
          for (let a = 0; a < arms; a++) {
            g.save();
            g.rotate((a / arms) * Math.PI * 2 + rot * (ring % 2 ? -1 : 1) * (1 + ring * 0.3));
            const r = R * (0.2 + ring * 0.18) * (1 + amp * 0.25);
            g.beginPath();
            g.ellipse(r * 0.5, 0, r * 0.5, r * 0.16 * (1 + amp), 0, 0, Math.PI * 2);
            g.stroke();
            g.restore();
          }
        }
        g.restore();
        g.globalAlpha = 1;
        g.globalCompositeOperation = "source-over";
      },
    };
  },
  grid: () => ({
    draw(g, w, h, t, lv, c) {
      g.clearRect(0, 0, w, h);
      const spec = engine.spectrum();
      const step = 26;
      g.fillStyle = c.primary;
      for (let x = 0; x < w; x += step) {
        const v = spec ? spec[Math.floor((x / w) * 120)] / 255 : 0;
        for (let y = h - step; y > h - step - v * h * 0.6; y -= step) {
          g.globalAlpha = 0.08 + v * 0.25;
          g.fillRect(x + 8, y + 8, 6, 6);
        }
      }
      g.globalAlpha = 0.06 + lv.level * 0.08;
      g.strokeStyle = c.primary;
      const off = (t / 40) % step;
      for (let y = off; y < h; y += step) {
        g.beginPath();
        g.moveTo(0, y);
        g.lineTo(w, y);
        g.stroke();
      }
      g.globalAlpha = 1;
    },
  }),
  sunset: () => ({
    draw(g, w, h, t, lv, c) {
      g.clearRect(0, 0, w, h);
      const horizon = h * 0.62;
      const sunR = Math.min(w, h) * 0.22 * (1 + lv.bass * 0.06);
      const sg = g.createLinearGradient(0, horizon - sunR * 2, 0, horizon);
      sg.addColorStop(0, c.warning);
      sg.addColorStop(1, c.primary);
      g.save();
      g.beginPath();
      g.arc(w / 2, horizon, sunR, Math.PI, 0);
      g.clip();
      g.fillStyle = sg;
      g.fillRect(w / 2 - sunR, horizon - sunR, sunR * 2, sunR);
      g.fillStyle = c.bg;
      for (let i = 0; i < 7; i++) {
        const y = horizon - sunR * (0.08 + i * 0.13);
        g.fillRect(w / 2 - sunR, y, sunR * 2, 2 + i * 1.6);
      }
      g.restore();
      g.strokeStyle = c.secondary;
      g.globalAlpha = 0.5;
      g.lineWidth = 1.2;
      const speed = (t / 30) % 40;
      for (let i = 0; i < 20; i++) {
        const z = (i * 40 + speed) / 800;
        const y = horizon + (h - horizon) * z * z * 1.4;
        g.beginPath();
        g.moveTo(0, y);
        g.lineTo(w, y);
        g.stroke();
      }
      for (let i = -20; i <= 20; i++) {
        g.beginPath();
        g.moveTo(w / 2 + i * 12, horizon);
        g.lineTo(w / 2 + i * w * 0.12, h);
        g.stroke();
      }
      g.globalAlpha = 1;
    },
  }),
  stars: () => {
    const st = particles(260, () => ({ x: rnd(-1, 1), y: rnd(-1, 1), z: rnd(0.05, 1) }));
    return {
      draw(g, w, h, _t, lv, c) {
        g.clearRect(0, 0, w, h);
        const cols = [c.text, c.primary, c.secondary, c.success];
        for (let i = 0; i < st.length; i++) {
          const s = st[i];
          s.z -= 0.0025 + lv.bass * 0.02;
          if (s.z <= 0.02) { s.x = rnd(-1, 1); s.y = rnd(-1, 1); s.z = 1; }
          const x = w / 2 + (s.x / s.z) * w * 0.25;
          const y = h / 2 + (s.y / s.z) * h * 0.25;
          const size = Math.max(1, Math.round((1 - s.z) * 4));
          g.fillStyle = cols[i % cols.length];
          g.globalAlpha = 1 - s.z;
          g.fillRect(Math.round(x / 2) * 2, Math.round(y / 2) * 2, size, size);
        }
        g.globalAlpha = 1;
      },
    };
  },
  groove: () => ({
    draw(g, w, h, t, lv, c) {
      g.clearRect(0, 0, w, h);
      const cols = [c.primary, c.secondary, c.warning, c.error];
      const cx = w * 0.85;
      const cy = h * 1.05;
      for (let i = 9; i >= 0; i--) {
        g.beginPath();
        g.arc(cx, cy, (i + 1) * Math.max(w, h) * 0.09 * (1 + lv.bass * 0.03) + Math.sin(t / 1500) * 6, 0, Math.PI * 2);
        g.fillStyle = cols[i % cols.length];
        g.globalAlpha = 0.13;
        g.fill();
      }
      g.globalAlpha = 1;
    },
  }),
  bubbles: () => {
    const bs = particles(40, () => ({ x: Math.random(), y: Math.random(), r: rnd(6, 32), s: rnd(0.3, 1), k: Math.random() }));
    return {
      draw(g, w, h, t, lv, c) {
        g.clearRect(0, 0, w, h);
        for (const b of bs) {
          b.y -= 0.0007 * b.s * (1 + lv.level * 2);
          if (b.y < -0.1) { b.y = 1.1; b.x = Math.random(); }
          const x = (b.x + Math.sin(t / 1500 + b.k * 10) * 0.01) * w;
          g.beginPath();
          g.arc(x, b.y * h, b.r, 0, Math.PI * 2);
          g.strokeStyle = b.k > 0.5 ? c.primary : c.secondary;
          g.globalAlpha = 0.35;
          g.lineWidth = 2;
          g.stroke();
          g.globalAlpha = 0.08;
          g.fillStyle = g.strokeStyle;
          g.fill();
        }
        g.globalAlpha = 1;
      },
    };
  },
  checker: () => ({
    draw(g, w, h, t, lv, c) {
      g.clearRect(0, 0, w, h);
      const horizon = h * 0.55;
      const off = (t / 25) % 2;
      for (let row = 0; row < 18; row++) {
        const z0 = (row + off) / 18;
        const z1 = (row + 1 + off) / 18;
        const y0 = horizon + (h - horizon) * z0 * z0;
        const y1 = horizon + (h - horizon) * z1 * z1;
        for (let col = -12; col < 12; col++) {
          if ((row + col) % 2 === 0) continue;
          const xa = (z: number, k: number) => w / 2 + k * (w / 10) * (0.1 + z * 1.6);
          g.fillStyle = c.text;
          g.globalAlpha = 0.05 + z0 * 0.12 + lv.bass * 0.05;
          g.beginPath();
          g.moveTo(xa(z0, col), y0);
          g.lineTo(xa(z0, col + 1), y0);
          g.lineTo(xa(z1, col + 1), y1);
          g.lineTo(xa(z1, col), y1);
          g.fill();
        }
      }
      g.globalAlpha = 1;
    },
  }),
  film: () => ({
    draw(g, w, h, _t, lv, c) {
      g.clearRect(0, 0, w, h);
      g.fillStyle = c.text;
      for (let i = 0; i < 160; i++) {
        g.globalAlpha = Math.random() * 0.06;
        g.fillRect(Math.random() * w, Math.random() * h, 1.5, 1.5);
      }
      if (Math.random() < 0.06 + lv.level * 0.1) {
        g.globalAlpha = 0.12;
        const x = Math.random() * w;
        g.fillRect(x, 0, 1, h);
      }
      g.globalAlpha = 1;
    },
  }),
  dust: () => {
    const ds = particles(120, () => ({ x: Math.random(), y: Math.random(), r: rnd(0.5, 2.2), k: Math.random() }));
    return {
      draw(g, w, h, t, lv, c) {
        g.clearRect(0, 0, w, h);
        const beam = g.createLinearGradient(w * 0.2, 0, w * 0.7, h);
        beam.addColorStop(0, c.warning + "22");
        beam.addColorStop(1, "transparent");
        g.fillStyle = beam;
        g.fillRect(0, 0, w, h);
        g.fillStyle = c.warning;
        for (const d of ds) {
          d.x += Math.sin(t / 3000 + d.k * 20) * 0.0002;
          d.y += Math.cos(t / 4000 + d.k * 20) * 0.0002 - 0.00005 * (1 + lv.level * 3);
          if (d.y < 0) d.y = 1;
          g.globalAlpha = 0.2 + 0.5 * Math.abs(Math.sin(t / 1200 + d.k * 9));
          g.beginPath();
          g.arc((d.x % 1) * w, d.y * h, d.r, 0, Math.PI * 2);
          g.fill();
        }
        g.globalAlpha = 1;
      },
    };
  },
  rasta: () => ({
    draw(g, w, h, t, lv, c) {
      g.clearRect(0, 0, w, h);
      const cols = [c.error, c.warning, c.success];
      const bandH = h / 3;
      cols.forEach((col, i) => {
        const grd = g.createLinearGradient(0, i * bandH, 0, (i + 1) * bandH);
        grd.addColorStop(0, col + "12");
        grd.addColorStop(0.5, col + (lv.bass > 0.6 ? "2a" : "1c"));
        grd.addColorStop(1, col + "12");
        g.fillStyle = grd;
        g.fillRect(0, i * bandH, w, bandH);
      });
      // a slowly turning record
      const r = Math.min(w, h) * 0.35;
      g.save();
      g.translate(w * 0.82, h * 0.78);
      g.rotate(t / 1800);
      for (let i = 0; i < 26; i++) {
        g.beginPath();
        g.arc(0, 0, r - i * (r / 30), 0, Math.PI * 2);
        g.strokeStyle = "#000000";
        g.globalAlpha = 0.18;
        g.stroke();
      }
      g.restore();
      g.globalAlpha = 1;
    },
  }),
};

// static textures are cheaper as CSS (see skins.css); these canvases just stay empty
const STATIC: BackdropKind[] = ["none", "xerox", "halftone", "marble", "paper"];

export function Backdrop({ kind }: { kind: BackdropKind | "space" }) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const g = canvas.getContext("2d")!;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (STATIC.includes(kind as BackdropKind) || !scenes[kind]) {
      g.clearRect(0, 0, canvas.width, canvas.height);
      return;
    }
    const scene = scenes[kind]();
    let colors = readColors();
    const colorTimer = window.setInterval(() => (colors = readColors()), 1500);
    let raf = 0;
    let last = 0;
    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 1.5);
      canvas.width = Math.floor(window.innerWidth * dpr);
      canvas.height = Math.floor(window.innerHeight * dpr);
      g.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    resize();
    window.addEventListener("resize", resize);
    const frame = (t: number) => {
      raf = requestAnimationFrame(frame);
      if (document.hidden || t - last < 1000 / 40) return;   // ~40 fps is plenty
      last = t;
      scene.draw(g, window.innerWidth, window.innerHeight, t, engine.level(), colors);
    };
    if (reduce) scene.draw(g, window.innerWidth, window.innerHeight, 0, { level: 0, bass: 0 }, colors);
    else raf = requestAnimationFrame(frame);
    return () => {
      cancelAnimationFrame(raf);
      window.clearInterval(colorTimer);
      window.removeEventListener("resize", resize);
    };
  }, [kind]);

  return <canvas ref={ref} className="backdrop" aria-hidden="true" />;
}
