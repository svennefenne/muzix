/** The Muzix logo: the five stripes and the name, with the name's capitals sized
 * to exactly the stripes' height in whatever display font the current skin uses. */

import { useEffect, useLayoutEffect, useRef } from "react";

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
    // skins swap the display font on <html>; the stripes change size on phones
    const watch = new MutationObserver(refit);
    watch.observe(document.documentElement, { attributes: true, attributeFilter: ["data-skin", "style", "class"] });
    const resize = new ResizeObserver(refit);
    resize.observe(m);
    return () => { watch.disconnect(); resize.disconnect(); };
  }, []);
  useEffect(() => { if (mark.current && text.current) fit(mark.current, text.current); }, [name]);
  return (
    <>
      <div className="logo-mark" ref={mark}><span /><span /><span /><span /><span /></div>
      <span className="logo-name" ref={text}>{name}</span>
    </>
  );
}
