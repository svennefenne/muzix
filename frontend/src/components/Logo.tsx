/** The Muzix logo: the app icon's cassette (components/cassette.ts, drawn by scripts/icons.py), six stripes
 * notched on top so it also reads as an M, with a deck across the middle, and the name, with the name's
 * capitals sized to exactly the cassette's height in whatever display font the current skin uses. The
 * stripes and the hubs take the theme's colours, so skins recolour it; the deck shows what's behind it. */

import { useEffect, useId, useLayoutEffect, useRef } from "react";
import { HUBS, PANEL, RIM, STRIPES, VIEWBOX } from "./cassette";

export function Cassette() {
  const mask = "mx-cassette-" + useId().replace(/[^a-zA-Z0-9_-]/g, "");
  const [x, y, w, h] = VIEWBOX;
  return (
    <svg viewBox={`${x} ${y} ${w} ${h}`} aria-hidden="true">
      {/* the deck's outline cut out of the stripes */}
      <mask id={mask} maskUnits="userSpaceOnUse" x={x} y={y} width={w} height={h}>
        <rect x={x} y={y} width={w} height={h} fill="#fff" />
        <path d={RIM} fill="#000" />
      </mask>
      <g mask={`url(#${mask})`}>
        {STRIPES.map((d, i) => <path key={i} className={`s${i + 1}`} d={d} />)}
      </g>
      <path className="deck" fillRule="evenodd" d={PANEL} />
      {HUBS.map((d, i) => <path key={i} className="hub" fillRule="evenodd" d={d} />)}
    </svg>
  );
}

const probe = document.createElement("canvas").getContext("2d");

function fit(mark: HTMLElement, name: HTMLElement) {
  const cs = getComputedStyle(name);
  const family = cs.fontFamily;
  const weight = cs.fontWeight;
  const measure = () => {
    if (!probe || !mark.isConnected) return;
    probe.font = `${weight} 100px ${family}`;
    // how tall a capital is per 100px of font size, measured from the glyph itself
    // (some decorative fonts report wrong metrics, so the font's own numbers aren't used)
    const cap = probe.measureText("M").actualBoundingBoxAscent;
    if (cap > 0) name.style.fontSize = `${(mark.getBoundingClientRect().height / cap) * 100}px`;
  };
  measure();
  document.fonts.load(`${weight} 100px ${family}`, "MUZIX").then(measure, () => {});
}

export function Logo({ name }: { name: string }) {
  const mark = useRef<HTMLDivElement>(null);
  const text = useRef<HTMLSpanElement>(null);
  useLayoutEffect(() => {
    const m = mark.current, t = text.current;
    if (!m || !t) return;
    const refit = () => fit(m, t);
    refit();
    // skins swap the display font on <html>; the cassette changes size on phones
    const watch = new MutationObserver(refit);
    watch.observe(document.documentElement, { attributes: true, attributeFilter: ["data-skin", "style", "class"] });
    const resize = new ResizeObserver(refit);
    resize.observe(m);
    return () => { watch.disconnect(); resize.disconnect(); };
  }, []);
  useEffect(() => { if (mark.current && text.current) fit(mark.current, text.current); }, [name]);
  return (
    <>
      <div className="logo-mark" ref={mark}><Cassette /></div>
      <span className="logo-name" ref={text}>{name}</span>
    </>
  );
}
