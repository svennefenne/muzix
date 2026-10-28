/** Tooltips, one host for the whole app. An element shows its `data-tip` (with `data-tip-key`, a
 * keyboard shortcut to go with it; `data-tip=""` for none), else its `title` (taken over, so the
 * browser's own doesn't pop up too), else, on a control that shows only an icon, its label; text
 * cut short with "…" shows in full. They show on hover after a moment, at once while moving from
 * one control to the next, and on keyboard focus. Touch screens have no hover, so no tooltips:
 * there the labels are read out instead. `data-tip-follow` keeps the tip at the pointer (the seek bar). */

import { useEffect, useLayoutEffect, useRef, useState } from "react";

const DELAY = 500;     // ms of hovering before a tip shows
const WARM = 600;      // ms after one tip during which the next shows at once

const CONTROL = "button, a, input, select, textarea, label, summary, [role=button], [role=radio], [role=tab], [role=menuitem]";

interface Tip { el: HTMLElement; text: string; key?: string }

function cutShort(el: HTMLElement) {
  return el.scrollWidth > el.clientWidth + 1 || el.scrollHeight > el.clientHeight + 1;
}

/** The tip for what's under the pointer (or focused): the nearest element that has one. */
export function tipFor(start: EventTarget | null): Tip | null {
  for (let el = start instanceof Element ? start : null; el && el !== document.body; el = el.parentElement) {
    if (!(el instanceof HTMLElement)) continue;
    const title = el.getAttribute("title");
    if (title !== null) {
      el.dataset.tip = title;
      el.removeAttribute("title");
    }
    const tip = el.dataset.tip;
    if (tip !== undefined) return tip ? { el, text: tip, key: el.dataset.tipKey } : null;
    const text = el.textContent?.trim() || "";
    if (el.matches(CONTROL)) {
      const label = el.getAttribute("aria-label");
      if (label && !text) return { el, text: label, key: el.dataset.tipKey };
      if (!el.classList.contains("ellipsis")) return null;     // its own words say what it does
    }
    if (el.classList.contains("ellipsis") && text && cutShort(el)) return { el, text };
  }
  return null;
}

export function Tooltips() {
  const [tip, setTip] = useState<Tip | null>(null);
  const [x, setX] = useState<number | null>(null);
  const box = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState({ left: -9999, top: -9999 });

  useEffect(() => {
    let timer: number | undefined;
    let shown: Tip | null = null;
    let over: HTMLElement | null = null;      // what the pointer is over, tip or not
    let lastHidden = 0;
    let pressed: string | null = null;        // the tip's text when its control was clicked
    let px: number | null = null;             // the pointer's x, for a tip that follows it
    let followed: HTMLElement | null = null;  // the one under the pointer, watched for its words changing

    const cancel = () => window.clearTimeout(timer);
    const show = (t: Tip | null, at: number | null = null) => {
      cancel();
      if (shown?.el.getAttribute("aria-describedby") === "muzix-tip") shown.el.removeAttribute("aria-describedby");
      if (shown && !t) lastHidden = Date.now();
      shown = t;
      if (t && t.text !== t.el.getAttribute("aria-label") && !t.el.hasAttribute("aria-describedby")) {
        t.el.setAttribute("aria-describedby", "muzix-tip");
      }
      setTip(t);
      setX(at);
    };
    const later = (el: HTMLElement) => {
      cancel();
      timer = window.setTimeout(() => {
        const t = el.isConnected ? tipFor(el) : null;      // its words by now, not when the pointer came
        if (t) show(t);
      }, Date.now() - lastHidden < WARM ? 0 : DELAY);
    };

    const onOver = (e: PointerEvent) => {
      if (e.pointerType === "touch") return;
      over = e.target as HTMLElement;
      px = e.clientX;
      const follow = over.closest?.<HTMLElement>("[data-tip-follow]");
      const el = tipFor(e.target)?.el ?? follow;
      if (el && el === shown?.el) return;
      if (shown) show(null);
      cancel();
      if (el && el !== follow) later(el);       // one that follows the pointer shows as it moves
    };
    // moving onto another element is pointerover's business; this is the pointer leaving the page
    const onOut = (e: PointerEvent) => {
      if (e.relatedTarget) return;
      over = null;
      cancel();
      if (shown) show(null);
    };
    const onMove = (e: PointerEvent) => {
      px = e.clientX;
      if (e.pointerType === "touch") return;
      // a seek bar's time shows at once, where the pointer is, and changes as the bar writes it
      const follow = (e.target as Element).closest?.<HTMLElement>("[data-tip-follow]") ?? null;
      if (follow !== followed) {
        rewritten.disconnect();
        followed = follow;
        if (follow) rewritten.observe(follow, { attributes: true, attributeFilter: ["data-tip"] });
      }
      if (follow) onFollow();
    };
    const onFollow = () => {
      const t = followed?.isConnected ? tipFor(followed) : null;
      if (t) show(t, px);
      else if (followed && shown?.el === followed) show(null);
    };
    const rewritten = new MutationObserver(onFollow);
    const onDown = () => {
      pressed = shown?.text ?? (over ? tipFor(over)?.text ?? null : null);
      show(null);
      lastHidden = 0;
    };
    // a toggle says what it does now (Shuffle: on / off): show the new words where they changed
    const onClick = () => window.setTimeout(() => {
      const t = over?.isConnected ? tipFor(over) : null;
      if (t && pressed !== null && t.text !== pressed) show(t);
      pressed = null;
    }, 60);
    const onFocus = (e: FocusEvent) => {
      const el = e.target as HTMLElement;
      if (!el.matches?.(":focus-visible") || el.matches("input:not([type=range]):not([type=checkbox]), textarea")) return;
      const t = tipFor(el);
      if (t) show(t);
    };
    const onBlur = () => shown && show(null);
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && shown && show(null);
    const onScroll = () => {
      cancel();
      if (shown) show(null);
    };
    // the element went away (a menu closed, a page changed) with its tip still showing
    const watch = window.setInterval(() => shown && !shown.el.isConnected && show(null), 300);

    document.addEventListener("pointerover", onOver);
    document.addEventListener("pointerout", onOut);
    document.addEventListener("pointermove", onMove, { passive: true });
    document.addEventListener("pointerdown", onDown, true);
    document.addEventListener("click", onClick, true);
    document.addEventListener("focusin", onFocus);
    document.addEventListener("focusout", onBlur);
    document.addEventListener("keydown", onKey);
    document.addEventListener("scroll", onScroll, true);
    document.addEventListener("wheel", onScroll, { passive: true });
    return () => {
      window.clearTimeout(timer);
      rewritten.disconnect();
      window.clearInterval(watch);
      document.removeEventListener("pointerover", onOver);
      document.removeEventListener("pointerout", onOut);
      document.removeEventListener("pointermove", onMove);
      document.removeEventListener("pointerdown", onDown, true);
      document.removeEventListener("click", onClick, true);
      document.removeEventListener("focusin", onFocus);
      document.removeEventListener("focusout", onBlur);
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("scroll", onScroll, true);
      document.removeEventListener("wheel", onScroll);
    };
  }, []);

  // above the element, or below it when there's no room; never off the screen
  useLayoutEffect(() => {
    if (!tip || !box.current) return;
    box.current.style.left = box.current.style.top = "0px";      // measured at full width, not squeezed at an edge
    const r = tip.el.getBoundingClientRect();
    const b = box.current.getBoundingClientRect();
    const cx = x ?? r.left + r.width / 2;
    const left = Math.min(Math.max(8, cx - b.width / 2), window.innerWidth - b.width - 8);
    const top = r.top - b.height - 8 >= 8 ? r.top - b.height - 8 : r.bottom + 8;
    setPos({ left, top });
  }, [tip, x]);

  if (!tip) return null;
  return (
    <div ref={box} id="muzix-tip" className="tooltip" role="tooltip" style={pos}>
      {tip.text}{tip.key && <kbd>{tip.key}</kbd>}
    </div>
  );
}
