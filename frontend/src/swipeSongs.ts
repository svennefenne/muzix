/** A finger's swipe changes the song, as on Spotify: across the big cover or the mini player, to
 * the left for the next one, to the right for the one before. What shows the song follows the
 * finger, goes off to that side and the new one comes in from the other; with no song to go to it
 * gives way only a little and comes back. The caller leaves out audiobooks and podcasts, where a
 * stray swipe would lose the place.
 *
 * With `desk` (the big cover) a computer does it too: dragging the cover with the mouse, or two
 * fingers sideways on a touchpad.
 *
 * `box` takes the touches, `slide` (the box itself by default) is what moves. The returned flag
 * is set from a swipe until the next touch: the click that ends one isn't a tap. */

import { useEffect, useRef, type RefObject } from "react";
import { engine } from "./player/engine";
import { usePlayer } from "./store/player";

type Ref = RefObject<HTMLElement | null>;

const QUIET = 350;      // ms without a touchpad's scrolling before another swipe counts: its fling is over

export function useSwipeSongs(box: Ref, on: boolean, slide?: Ref, desk = false) {
  const swiped = useRef(false);
  useEffect(() => {
    const el = box.current;
    const mover = slide?.current ?? el;
    if (!el || !mover || !on) return;
    const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
    let start: { id: number; x: number; y: number } | null = null;
    let dragging = false;
    let dx = 0;
    let trail: { x: number; t: number }[] = [];   // the last tenth of a second: how fast it flicks
    // 1: the next song, -1: the one before
    const room = (dir: number) => {
      const s = usePlayer.getState();
      return dir > 0 ? s.index < s.queue.length - 1 || s.repeat === "all" || (s.shuffle && s.queue.length > 1) : s.index > 0;
    };
    const look = (x: number) => ({
      transform: `translateX(${x}px)`,
      opacity: String(1 - Math.min(1, Math.abs(x) / mover.offsetWidth) * 0.6),
    });
    const glide = (from: number, to: number, ms: number) => {
      Object.assign(mover.style, to ? look(to) : { transform: "", opacity: "" });
      if (!still) mover.animate([look(from), look(to)], { duration: ms, easing: "cubic-bezier(.2, .7, .3, 1)" });
    };
    const follow = (x: number) => {
      dx = room(x < 0 ? 1 : -1) ? x : x / 4;
      Object.assign(mover.style, look(dx));
    };
    /** Off to the side, then the song changes and the new one comes in from the other. */
    const go = (dir: number) => {
      const w = mover.offsetWidth;
      glide(dx, -dir * w * 1.2, still ? 0 : 160);
      dx = 0;
      // a timer, not the animation's promise: Safari lets a song start this soon after a touch
      window.setTimeout(() => {
        if (dir > 0) engine.next();
        else engine.prev(true);
        glide(dir * w * 0.6, 0, 260);
      }, still ? 0 : 160);
    };
    const down = (e: PointerEvent) => {
      swiped.current = false;
      if ((e.pointerType === "mouse" && (!desk || e.button !== 0)) || start) return;
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
        mover.getAnimations().forEach((a) => a.cancel());
        el.setPointerCapture(e.pointerId);
      }
      follow(x);
      trail.push({ x, t: e.timeStamp });
      while (trail.length > 2 && e.timeStamp - trail[0].t > 100) trail.shift();
    };
    const up = (e: PointerEvent) => {
      if (e.pointerId !== start?.id) return;
      const [a, z] = [trail[0], trail[trail.length - 1]];
      const fast = Math.abs(dx) > 40 && !!a && z.t > a.t && Math.abs(z.x - a.x) / (z.t - a.t) > 0.4;
      start = null;
      if (!dragging) return;
      dragging = false;
      const dir = dx < 0 ? 1 : -1;
      if (e.type === "pointercancel" || !room(dir) || (Math.abs(dx) < mover.offsetWidth / 4 && !fast)) {
        glide(dx, 0, 220);
        dx = 0;
        return;
      }
      go(dir);
    };

    // a touchpad's two fingers sideways: the cover follows them; far enough, the song changes at once
    let wheelX = 0;
    let wheeling = false;
    let quietUntil = 0;
    let rest = 0;
    const settle = () => {
      wheeling = false;
      if (dx) glide(dx, 0, 220);
      dx = wheelX = 0;
    };
    const wheel = (e: WheelEvent) => {
      if (Math.abs(e.deltaX) <= Math.abs(e.deltaY) || start) return;     // up and down scrolls the page
      e.preventDefault();                                                  // and no going back a page
      if (e.timeStamp < quietUntil) {
        quietUntil = e.timeStamp + QUIET;
        return;
      }
      if (!wheeling) {
        wheeling = true;
        wheelX = 0;
        mover.getAnimations().forEach((a) => a.cancel());
      }
      wheelX -= e.deltaX * (e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? mover.offsetWidth : 1);
      follow(wheelX);
      window.clearTimeout(rest);
      const dir = wheelX < 0 ? 1 : -1;
      if (Math.abs(wheelX) > mover.offsetWidth / 4 && room(dir)) {
        wheeling = false;
        wheelX = 0;
        quietUntil = e.timeStamp + QUIET;
        swiped.current = true;
        go(dir);
        return;
      }
      rest = window.setTimeout(settle, 160);
    };
    const noDrag = (e: DragEvent) => e.preventDefault();   // the cover picture isn't dragged away

    el.addEventListener("pointerdown", down);
    el.addEventListener("pointermove", move);
    el.addEventListener("pointerup", up);
    el.addEventListener("pointercancel", up);
    if (desk) {
      el.addEventListener("wheel", wheel, { passive: false });
      el.addEventListener("dragstart", noDrag);
    }
    return () => {
      window.clearTimeout(rest);
      el.removeEventListener("pointerdown", down);
      el.removeEventListener("pointermove", move);
      el.removeEventListener("pointerup", up);
      el.removeEventListener("pointercancel", up);
      el.removeEventListener("wheel", wheel);
      el.removeEventListener("dragstart", noDrag);
    };
  }, [box, on, slide, desk]);
  return swiped;
}
