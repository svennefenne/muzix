/** Opens the speaker picker for Google Cast speakers (the browser's, or the Android app's own);
 * shown wherever casting works, dimmed until a speaker turns up on the network. */

import { Cast } from "lucide-react";
import { appPlayer } from "../player/app";
import { caster } from "../player/cast";
import { usePlayer } from "../store/player";

export function CastButton({ size = 18, className = "ctl", label = false }: { size?: number; className?: string; label?: boolean }) {
  const state = usePlayer((s) => s.castState);
  const device = usePlayer((s) => s.castDevice);
  const ready = usePlayer((s) => s.castSupport === "ready");
  if (!ready) return null;
  const on = state === "connected";
  const what = on ? `Playing on ${device}` : state === "connecting" ? "Connecting to the speaker…"
    : state === "unavailable" ? "No speakers found on this network yet" : "Play on a speaker";
  return (
    <button className={`${className} cast-btn ${on ? "on" : ""} ${state === "connecting" ? "connecting" : ""} ${state === "unavailable" ? "dim" : ""}`}
            aria-label={what} data-tip={what} onClick={() => (appPlayer.available ? appPlayer.chooseSpeaker() : caster.choose())}>
      <Cast size={size} />{label && <span>{on ? device : "Cast"}</span>}
    </button>
  );
}

/** What casting can do in this browser, for the settings page. */
export function castStatus(s: { castSupport: string; castWhy: string; castState: string; castDevice: string }) {
  if (s.castSupport === "loading") return "Looking for Google Cast…";
  if (s.castSupport === "unsupported") return s.castWhy;
  if (s.castState === "connected") return `Playing on ${s.castDevice}.`;
  if (s.castState === "unavailable") return "Ready, but no speakers found yet. They show up when they're on the same network as this device.";
  return "Ready: speakers found. Use the Cast button in the player.";
}

/** "Playing on <speaker>" while casting. */
export function CastNote({ className = "cast-note" }: { className?: string }) {
  const on = usePlayer((s) => s.castState === "connected");
  const device = usePlayer((s) => s.castDevice);
  if (!on) return null;
  return <div className={`${className} ellipsis`}><Cast size={12} /> Playing on {device}</div>;
}
