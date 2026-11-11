/** Where the music plays: the account's other devices (Muzix Connect, player/connect.ts) and Google
 * Cast speakers (the browser's, or the Android app's own), in one button, as with Spotify. With no
 * other device online it's the speaker picker as it was, dimmed until a speaker turns up. */

import { Cast, Monitor, MonitorSpeaker, Smartphone } from "lucide-react";
import type { MouseEvent, ReactNode } from "react";
import { appPlayer } from "../player/app";
import { caster } from "../player/cast";
import { connect, type Device, libraryOf, useDevices } from "../player/connect";
import { usePlayer } from "../store/player";
import { type MenuItem, useMenu } from "./ui";

const phone = (d: Device) => d.kind === "app" || /Android|iOS/.test(d.name);

/** Why the music can't move to a device that shows another library than the queue's (its songs aren't there). */
function elsewhereLibrary(d: Device): Partial<MenuItem> {
  if (libraryOf(d) === connect.queueLibrary()) return {};
  return { disabled: true, note: d.library === "local" ? `Shows ${phone(d) ? "the phone's" : "the computer's"} own music` : "Shows the server's music" };
}

/** The other device that plays, while one does. */
function usePlayingElsewhere() {
  // one that's away (it may be back in a moment) only while this device follows it
  return useDevices((s) => (s.active && s.active !== s.you
    ? s.devices.find((d) => d.id === s.active)?.name || (connect.following ? "another device" : "") : ""));
}

export function CastButton({ size = 18, className = "ctl", label = false }: { size?: number; className?: string; label?: boolean }) {
  const state = usePlayer((s) => s.castState);
  const device = usePlayer((s) => s.castDevice);
  const ready = usePlayer((s) => s.castSupport === "ready");
  const devices = useDevices((s) => s.devices);
  const you = useDevices((s) => s.you);
  const elsewhere = usePlayingElsewhere();
  const showMenu = useMenu((s) => s.show);
  const others = devices.filter((d) => d.id !== you);
  const chooseSpeaker = () => (appPlayer.available ? appPlayer.chooseSpeaker() : caster.choose());
  const casting = state === "connected";
  if (!others.length && !elsewhere) {
    if (!ready) return null;
    const what = casting ? `Playing on ${device}` : state === "connecting" ? "Connecting to the speaker…"
      : state === "unavailable" ? "No speakers found on this network yet" : "Play on a speaker";
    return (
      <button className={`${className} cast-btn ${casting ? "on" : ""} ${state === "connecting" ? "connecting" : ""} ${state === "unavailable" ? "dim" : ""}`}
              aria-label={what} data-tip={what} onClick={chooseSpeaker}>
        <Cast size={size} />{label && <span>{casting ? device : "Cast"}</span>}
      </button>
    );
  }
  const here = devices.find((d) => d.id === you);
  const mark = (on: boolean, icon: ReactNode) => <span className={on ? "dev-on" : "dev-icon"}>{icon}</span>;
  const pick = (e: MouseEvent) => {
    const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
    showMenu({ clientX: r.left, clientY: r.bottom + 6 }, [
      { heading: "Play on" },
      {
        label: `${here?.name || "This device"} (this one)${!elsewhere && !casting ? " · playing" : ""}`,
        icon: mark(!elsewhere && !casting, here && phone(here) ? <Smartphone size={16} /> : <Monitor size={16} />),
        onClick: () => elsewhere && connect.transfer(you),
        ...(here && elsewhere ? elsewhereLibrary(here) : {}),
      },
      ...others.map((d) => ({
        label: d.name + (d.name === elsewhere ? " · playing" : ""),
        icon: mark(d.name === elsewhere, phone(d) ? <Smartphone size={16} /> : <Monitor size={16} />),
        onClick: () => d.name !== elsewhere && connect.transfer(d.id),
        ...(d.name !== elsewhere ? elsewhereLibrary(d) : {}),
      })),
      ...(ready ? [{ sep: true }, {
        label: casting ? `${device} · playing` : state === "unavailable" ? "Google Cast: no speakers found yet" : "Google Cast speaker…",
        icon: mark(casting, <Cast size={16} />),
        onClick: chooseSpeaker,
      }] : []),
    ]);
  };
  const on = !!elsewhere || casting;
  const what = elsewhere ? `Playing on ${elsewhere}` : casting ? `Playing on ${device}` : "Play on another device";
  return (
    <button className={`${className} cast-btn ${on ? "on" : ""}`} aria-label={what} data-tip={what} aria-haspopup="menu" onClick={pick}>
      <MonitorSpeaker size={size} />{label && <span>{elsewhere || (casting ? device : "Devices")}</span>}
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

/** "Playing on <device>" while another device plays, or a speaker. */
export function CastNote({ className = "cast-note" }: { className?: string }) {
  const on = usePlayer((s) => s.castState === "connected");
  const device = usePlayer((s) => s.castDevice);
  const elsewhere = usePlayingElsewhere();
  if (elsewhere) return <div className={`${className} ellipsis`}><MonitorSpeaker size={12} /> Playing on {elsewhere}</div>;
  if (!on) return null;
  return <div className={`${className} ellipsis`}><Cast size={12} /> Playing on {device}</div>;
}

/** Whether the music plays somewhere else: another device, or a speaker. */
export function usePlaysElsewhere() {
  const casting = usePlayer((s) => s.castState === "connected");
  return !!usePlayingElsewhere() || casting;
}
