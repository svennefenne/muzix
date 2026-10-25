/** Opens the speaker picker for Google Cast speakers; shown only when one is around. */

import { Cast } from "lucide-react";
import { caster } from "../player/cast";
import { usePlayer } from "../store/player";

export function CastButton({ size = 18, className = "ctl", label = false }: { size?: number; className?: string; label?: boolean }) {
  const state = usePlayer((s) => s.castState);
  const device = usePlayer((s) => s.castDevice);
  if (state === "unavailable") return null;
  const on = state === "connected";
  const what = on ? `Playing on ${device}` : state === "connecting" ? "Connecting to the speaker…" : "Play on a speaker";
  return (
    <button className={`${className} cast-btn ${on ? "on" : ""} ${state === "connecting" ? "connecting" : ""}`}
            aria-label={what} title={what} onClick={() => caster.choose()}>
      <Cast size={size} />{label && <span>{on ? device : "Cast"}</span>}
    </button>
  );
}

/** "Playing on <speaker>" while casting. */
export function CastNote({ className = "cast-note" }: { className?: string }) {
  const on = usePlayer((s) => s.castState === "connected");
  const device = usePlayer((s) => s.castDevice);
  if (!on) return null;
  return <div className={`${className} ellipsis`}><Cast size={12} /> Playing on {device}</div>;
}
