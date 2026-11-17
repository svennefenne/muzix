/** The sleep timer's button and menu (player/sleep.ts): in the player bar, the phone's player and on a book's page. */

import { Moon } from "lucide-react";
import { useEffect, useState, type MouseEvent } from "react";
import { cancelSleep, endLabel, SLEEP_MINUTES, sleepAtEnd, sleepIn, sleepLeft, useSleep } from "../player/sleep";
import { usePlayer } from "../store/player";
import { useMenu, type MenuItem } from "./ui";

function clock(s: number) {
  const m = Math.floor(s / 60);
  return m >= 60 ? `${Math.floor(m / 60)}:${String(m % 60).padStart(2, "0")}:${String(Math.floor(s % 60)).padStart(2, "0")}`
    : `${m}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
}

/** What's left, as the button shows it: "24:10", or "End of the chapter" while that's not near. */
export function useSleepLeft() {
  const t = useSleep();
  const on = t.ends !== null || t.key !== null;
  const [, redraw] = useState(0);
  useEffect(() => {
    if (!on) return;
    const i = setInterval(() => redraw((n) => n + 1), 1000);
    return () => clearInterval(i);
  }, [on]);
  if (!on) return null;
  const left = sleepLeft(t);
  return left === null ? t.label : clock(Math.max(0, left));
}

export function sleepMenu(e: MouseEvent) {
  const t = useSleep.getState();
  const cur = usePlayer.getState().current();
  const on = t.ends !== null || t.key !== null;
  const left = on ? sleepLeft(t) : null;
  const items: MenuItem[] = [
    { heading: on ? `Sleep timer · ${left === null ? t.label : clock(Math.max(0, left)) + " left"}` : "Sleep timer" },
    ...SLEEP_MINUTES.map((m) => ({ label: `${m} minutes`, onClick: () => sleepIn(m) })),
    { label: endLabel(), onClick: () => void sleepAtEnd(), disabled: !cur || cur.kind === "radio",
      note: !cur ? "Nothing plays" : cur.kind === "radio" ? "Radio has no end" : undefined },
  ];
  if (on) items.push({ sep: true }, { label: "Turn the timer off", onClick: cancelSleep });
  useMenu.getState().show(e, items);
}

/** The player's moon: it fills while the timer runs, with the time left beside it where there's room. */
export function SleepButton({ className = "ctl", size = 18, label }: { className?: string; size?: number; label?: boolean }) {
  const left = useSleepLeft();
  return (
    <button className={`${className} ${left ? "on" : ""}`} aria-label={left ? `Sleep timer: ${left}` : "Sleep timer"}
            data-tip={left ? `Sleep timer: ${left}` : "Sleep timer: pause after a while"} onClick={sleepMenu}>
      <Moon size={size} fill={left ? "currentColor" : "none"} />
      {label && <span className="mono-num">{left ?? "Sleep timer"}</span>}
    </button>
  );
}
