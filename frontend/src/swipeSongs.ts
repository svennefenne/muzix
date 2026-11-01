/** A finger's swipe changes the song, as on Spotify: across the big cover or the mini player, to
 * the left for the next one, to the right for the one before. What shows the song follows the
 * finger, goes off to that side and the new one comes in from the other; with no song to go to it
 * gives way only a little and comes back. The caller leaves out audiobooks and podcasts, where a
 * stray swipe would lose the place.
 *
 * `box` takes the touches, `slide` (the box itself by default) is what moves. The returned flag
 * is set from a swipe until the next touch: the click that ends one isn't a tap. */

import { useEffect, useRef, type RefObject } from "react";
import { engine } from "./player/engine";
import { usePlayer } from "./store/player";

type Ref = RefObject<HTMLElement | null>;

export function useSwipeSongs(box: Ref, on: boolean, slide?: Ref) {
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
        mover.getAnimations().forEach((a) => a.cancel());
        el.setPointerCapture(e.pointerId);
      }
      dx = room(x < 0 ? 1 : -1) ? x : x / 4;
      Object.assign(mover.style, look(dx));
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
      const w = mover.offsetWidth;
      const dir = dx < 0 ? 1 : -1;
      if (e.type === "pointercancel" || !room(dir) || (Math.abs(dx) < w / 4 && !fast)) return glide(dx, 0, 220);
      glide(dx, -dir * w * 1.2, still ? 0 : 160);
      // a timer, not the animation's promise: Safari lets a song start this soon after a touch
      window.setTimeout(() => {
        if (dir > 0) engine.next();
        else engine.prev(true);
        glide(dir * w * 0.6, 0, 260);
      }, still ? 0 : 160);
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
  }, [box, on, slide]);
  return swiped;
}
