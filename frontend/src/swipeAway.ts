/** A finger's swipe to either side takes a row away, as in a mail app: the row follows the finger, what's
 * behind it says what a swipe does, and past a quarter of its width (or flicked) it goes off that side
 * and `away` is called; short of that it comes back. Touch only: a mouse drag selects text as before.
 *
 * `box` takes the touches and gets the class "swiping" while it's dragged and data-side="left|right"
 * for the side the row moves to; its first child with the class "swipe-row" is what moves. The returned
 * flag is set from a swipe until the next touch: the click that ends one isn't a tap. */

import { useEffect, useRef, type RefObject } from "react";

export function useSwipeAway(box: RefObject<HTMLElement | null>, on: boolean, away: () => void) {
  const swiped = useRef(false);
  const gone = useRef(away);
  gone.current = away;
  useEffect(() => {
    const el = box.current;
    const row = el?.querySelector<HTMLElement>(".swipe-row");
    if (!el || !row || !on) return;
    const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
    let start: { id: number; x: number; y: number } | null = null;
    let dragging = false;
    let dx = 0;
    let trail: { x: number; t: number }[] = [];   // the last tenth of a second: how fast it flicks
    const look = (x: number) => ({ transform: x ? `translateX(${x}px)` : "" });
    const glide = (from: number, to: number, ms: number, then?: () => void) => {
      Object.assign(row.style, look(to));
      const done = () => {
        if (!to) el.classList.remove("swiping");
        then?.();
      };
      if (still || !ms) return done();
      row.animate([{ transform: `translateX(${from}px)` }, { transform: `translateX(${to}px)` }],
                  { duration: ms, easing: "cubic-bezier(.2, .7, .3, 1)" }).finished.then(done, done);
    };
    const down = (e: PointerEvent) => {
      swiped.current = false;
      if (e.pointerType === "mouse" || start) return;
      start = { id: e.pointerId, x: e.clientX, y: e.clientY };
      dragging = false;
      trail = [];
    };
    const move = (e: PointerEvent) => {
      if (e.pointerId !== start?.id) return;
      const x = e.clientX - start.x;
      if (!dragging) {
        if (Math.abs(x) < 10 || Math.abs(x) < Math.abs(e.clientY - start.y)) return;
        dragging = swiped.current = true;
        row.getAnimations().forEach((a) => a.cancel());
        el.setPointerCapture(e.pointerId);
        el.classList.add("swiping");
      }
      dx = x;
      el.dataset.side = dx < 0 ? "left" : "right";
      Object.assign(row.style, look(dx));
      trail.push({ x, t: e.timeStamp });
      while (trail.length > 2 && e.timeStamp - trail[0].t > 100) trail.shift();
    };
    const up = (e: PointerEvent) => {
      if (e.pointerId !== start?.id) return;
      const [a, z] = [trail[0], trail[trail.length - 1]];
      const fast = Math.abs(dx) > 40 && !!a && z.t > a.t && Math.abs(z.x - a.x) / (z.t - a.t) > 0.4
        && Math.sign(z.x - a.x) === Math.sign(dx);
      start = null;
      if (!dragging) return;
      dragging = false;
      const w = row.offsetWidth;
      if (e.type === "pointercancel" || (Math.abs(dx) < w / 4 && !fast)) return glide(dx, 0, 220);
      glide(dx, Math.sign(dx) * w * 1.1, 180, () => gone.current());
    };
    el.addEventListener("pointerdown", down);
    el.addEventListener("pointermove", move);
    el.addEventListener("pointerup", up);
    el.addEventListener("pointercancel", up);
    return () => {
      el.removeEventListener("pointerdown", down);
      el.removeEventListener("pointermove", move);
      el.removeEventListener("pointerup", up);
      el.removeEventListener("pointercancel", up);
    };
  }, [box, on]);
  return swiped;
}
