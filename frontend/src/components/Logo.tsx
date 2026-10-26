/** The Muzix logo: a cassette made of the five stripes, notched on top so it also reads as an
 * M, and the name, with the name's capitals sized to exactly the cassette's height in whatever
 * display font the current skin uses. The stripes take the theme's colours, so skins recolour it. */

import { useEffect, useId, useLayoutEffect, useRef } from "react";

// on a 40×30 grid: the body, the notch, the two reel holes and the tape opening
const CUT = "M3 0H37A3 3 0 0 1 40 3V27A3 3 0 0 1 37 30H3A3 3 0 0 1 0 27V3A3 3 0 0 1 3 0Z M17 0L20 4L23 0Z "
  + "M8.4 13a3.6 3.6 0 1 0 7.2 0a3.6 3.6 0 1 0 -7.2 0Z M24.4 13a3.6 3.6 0 1 0 7.2 0a3.6 3.6 0 1 0 -7.2 0Z "
  + "M10 30L13.5 24.5H26.5L30 30Z";

export function Cassette() {
  const clip = "mx-cassette-" + useId().replace(/[^a-zA-Z0-9_-]/g, "");
  return (
    <svg viewBox="0 0 40 30" aria-hidden="true">
      <clipPath id={clip}><path clipRule="evenodd" d={CUT} /></clipPath>
      <g clipPath={`url(#${clip})`}>
        {[0, 1, 2, 3, 4].map((i) => <rect key={i} className={`s${i + 1}`} x="0" y={i * 6.2} width="40" height="5.2" />)}
      </g>
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
