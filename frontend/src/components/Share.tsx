/** Sharing (backend api/shares.py). "Copy link" copies the page's own address, for people with an account
 * on this server. "Share link…" makes a public link: anyone who has it can listen in a browser without
 * an account until it runs out (a day, a week, a month or never, chosen here). They can't download.
 * Only this server's own library can be shared that way: a friend's album of the Library Network gets
 * "Copy link" alone. The app's own library (no server) shares nothing. */

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Copy, Link2, MessageCircle, Share2 } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { create } from "zustand";
import { api } from "../api";
import type { Draft } from "../chat/logic";
import { shareInChat, useChatOn } from "../chat/store";
import { appPlayer, inAndroidApp, useShell } from "../player/app";
import type { PlayItem } from "../store/player";
import { useUi } from "../store/ui";
import { Art, Modal, useMenu, type MenuItem } from "./ui";

export type ShareKind = "track" | "album" | "playlist" | "artist" | "podcast" | "episode";

export interface ShareTarget {
  kind: ShareKind;
  id: number;
  title: string;
  sub?: string;
  art?: string | null;
  path: string;               // its page in the app ("Copy link")
  peer?: string | null;       // a friend's (the Library Network): no public link
  chat?: Draft;               // "Share in chat" too, where the chat is on
}

export interface SharedLink {
  token: string; url: string; kind: ShareKind; item_id: number; title: string; sub: string;
  created_at: string; expires_at: string | null; run_out: boolean; opened: number; path: string | null; by?: string;
}

export const KIND_NAME: Record<ShareKind, string> = {
  track: "Song", album: "Album", playlist: "Playlist", artist: "Artist", podcast: "Podcast", episode: "Episode",
};

/** An address in the app as people elsewhere reach it: the server's public address when it has one. */
export function appLink(path: string) {
  return (useUi.getState().publicUrl || location.origin).replace(/\/$/, "") + path;
}

/** Puts text on the clipboard: the app's own (its page may not be allowed to), else the browser's. */
export async function copyText(text: string): Promise<boolean> {
  if (appPlayer.copy(text)) return true;
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.setAttribute("readonly", "");
    Object.assign(ta.style, { position: "fixed", opacity: "0", top: "0" });
    document.body.appendChild(ta);
    ta.select();
    let ok = false;
    try {
      ok = document.execCommand("copy");
    } catch {
      /* nothing to copy with */
    }
    ta.remove();
    return ok;
  }
}

/** The system's own share sheet (messages, mail, chat apps): the Android app's, or a browser's that has one. */
export function canShareSheet() {
  return inAndroidApp ? appPlayer.sharesNative : !appPlayer.available && typeof navigator !== "undefined" && !!navigator.share;
}

export async function shareSheet(url: string, title: string) {
  if (inAndroidApp) return appPlayer.shareSheet(url, title);
  try {
    await navigator.share({ title, url });
  } catch {
    /* closed without sharing */
  }
}

export async function copyLink(url: string, what = "Link") {
  const ok = await copyText(url);
  useUi.getState().notify(ok ? `${what} copied` : "Couldn't copy here: the link is in Settings → Shared links", ok ? "info" : "error");
}

/** What plays, to share: a song or an episode of this library (not one another device plays from another). */
export function playingTarget(it: PlayItem | null | undefined): ShareTarget | null {
  if (!it || it.foreign || typeof it.id !== "number") return null;
  if (it.kind === "track") {
    return { kind: "track", id: it.id, title: it.title, sub: it.artist, art: it.art, peer: it.peer, path: it.albumId ? `/album/${it.albumId}` : "/",
             chat: { kind: "track", id: it.id, title: it.title, sub: it.artist, art: it.art ?? null } };
  }
  if (it.kind === "episode") return { kind: "episode", id: it.id, title: it.title, sub: it.artist, art: it.art, path: `/podcasts/episode/${it.id}` };
  return null;
}

// ---------------------------------------------------------------- the menu

export const useShare = create<{ target: ShareTarget | null; open: (t: ShareTarget) => void; close: () => void }>((set) => ({
  target: null,
  open: (target) => set({ target }),
  close: () => set({ target: null }),
}));

/** The share items of a menu: copy the page's link, make a public one, share in chat. None in the app's own library. */
export function shareItems(t: ShareTarget, chat: boolean): MenuItem[] {
  if (useShell.getState().library === "local") return [];
  const user = useUi.getState().user;
  const allowed = user?.can_share !== false;
  return [
    { label: "Copy link", icon: <Link2 size={16} />, onClick: () => void copyLink(appLink(t.path)) },
    { label: "Share link…", icon: <Share2 size={16} />, onClick: () => useShare.getState().open(t),
      disabled: !!t.peer || !allowed,
      note: t.peer ? `In ${t.peer}'s library: only your own` : !allowed ? "Turned off for your account" : undefined },
    ...(chat && t.chat ? [{ label: "Share in chat", icon: <MessageCircle size={16} />, onClick: () => shareInChat(t.chat!) }] : []),
  ];
}

/** A page's Share button: its menu of the ways to share. */
export function ShareButton({ target, label = true, className = "btn ghost" }: { target: ShareTarget; label?: boolean; className?: string }) {
  const show = useMenu((s) => s.show);
  const chat = useChatOn();
  const local = useShell((s) => s.library === "local");
  if (local) return null;
  return (
    <button className={className} aria-label={`Share ${target.title}`} data-tip={label ? undefined : "Share"}
            onClick={(e) => { const r = e.currentTarget.getBoundingClientRect(); show({ clientX: r.left, clientY: r.bottom + 6, target: e.currentTarget }, shareItems(target, chat)); }}>
      <Share2 size={16} />{label && " Share"}
    </button>
  );
}

// ---------------------------------------------------------------- making a public link

const LASTS: { days: number | null; label: string }[] = [
  { days: 1, label: "1 day" }, { days: 7, label: "7 days" }, { days: 30, label: "30 days" }, { days: null, label: "Forever" },
];

/** Shown once, in the shell: the dialog that makes a public link. */
export function ShareHost() {
  const target = useShare((s) => s.target);
  const close = useShare((s) => s.close);
  if (!target) return null;
  return <ShareDialog key={`${target.kind}:${target.id}`} target={target} onClose={close} />;
}

function ShareDialog({ target, onClose }: { target: ShareTarget; onClose: () => void }) {
  const notify = useUi((s) => s.notify);
  const qc = useQueryClient();
  const [days, setDays] = useState<number | null>(7);
  const [made, setMade] = useState<SharedLink | null>(null);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const sheet = canShareSheet();
  const make = async () => {
    if (made) return made;
    setBusy(true);
    try {
      const link = await api.post<SharedLink>("/api/shares", { kind: target.kind, id: target.id, days });
      setMade(link);
      qc.invalidateQueries({ queryKey: ["shares"] });
      return link;
    } catch (e) {
      notify((e as Error).message, "error");
      return null;
    } finally {
      setBusy(false);
    }
  };
  const copy = async () => {
    const link = await make();
    if (!link) return;
    const ok = await copyText(link.url);
    setCopied(ok);
    if (!ok) notify("Couldn't copy here: select the link and copy it", "error");
  };
  const send = async () => {
    const link = await make();
    if (link) await shareSheet(link.url, target.title);
  };
  const lasts = made ? (made.expires_at ? `Works until ${new Date(made.expires_at).toLocaleDateString(undefined, { day: "numeric", month: "long", year: "numeric" })}` : "Works until you take it away") : null;
  return (
    <Modal onClose={onClose} className="share-dialog">
      <div className="kicker">Share link</div>
      <div className="share-what">
        <Art src={target.art} name={target.title} size={120} className="share-art" round={target.kind === "artist"} />
        <div className="grow" style={{ minWidth: 0 }}>
          <div className="share-title ellipsis">{target.title}</div>
          <div className="dim ellipsis">{[KIND_NAME[target.kind], target.sub].filter(Boolean).join(" · ")}</div>
        </div>
      </div>
      <p className="dim share-note">Anyone with the link can listen in a browser, without an account. They can't download it.</p>
      {made ? (
        <>
          <div className="share-link">
            <input className="input" readOnly value={made.url} aria-label="The link" onFocus={(e) => e.currentTarget.select()} />
          </div>
          <p className="faint share-lasts">{lasts}. Your links are in Settings → Shared links.</p>
        </>
      ) : (
        <div className="share-lasts-pick">
          <span className="seg-label" id="share-lasts">Lasts</span>
          <div className="seg" role="radiogroup" aria-labelledby="share-lasts">
            {LASTS.map((l) => (
              <button key={l.label} role="radio" aria-checked={days === l.days} className={days === l.days ? "on" : ""}
                      onClick={() => setDays(l.days)}>{l.label}</button>
            ))}
          </div>
        </div>
      )}
      <div className="row-actions">
        <button className="btn primary" disabled={busy} onClick={copy}>
          {copied ? <Check size={16} /> : <Copy size={16} />} {copied ? "Copied" : made ? "Copy again" : "Copy link"}
        </button>
        {sheet && <button className="btn" disabled={busy} onClick={send}><Share2 size={16} /> Share…</button>}
        <button className="btn ghost" onClick={onClose}>{made ? "Done" : "Cancel"}</button>
      </div>
    </Modal>
  );
}

// ---------------------------------------------------------------- the links made

/** The public links made: one's own (Settings), or everyone's (Admin → Shared links). */
export function SharedLinks({ all = false }: { all?: boolean }) {
  const notify = useUi((s) => s.notify);
  const qc = useQueryClient();
  const key = all ? ["shares", "all"] : ["shares"];
  const list = useQuery({ queryKey: key, queryFn: () => api.get<SharedLink[]>(all ? "/api/admin/shares" : "/api/shares") });
  const remove = async (l: SharedLink) => {
    try {
      await api.del(`/api/shares/${l.token}`);
      notify(`The link to ${l.title} no longer works`);
    } catch (e) {
      notify((e as Error).message, "error");
    }
    qc.invalidateQueries({ queryKey: ["shares"] });
  };
  if (!list.data) return null;
  if (!list.data.length) return <p className="faint">{all ? "Nobody has shared a link yet." : "You haven't shared any links. Share link… in a menu makes one."}</p>;
  const until = (l: SharedLink) => l.run_out ? "ran out" : l.expires_at
    ? `until ${new Date(l.expires_at).toLocaleDateString(undefined, { day: "numeric", month: "short" })}` : "until taken away";
  return (
    <ul className="admin-list">
      {list.data.map((l) => (
        <li key={l.token} className={l.run_out ? "shared-out" : ""}>
          <div className="grow" style={{ minWidth: 0 }}>
            <div className="ellipsis">
              <span className="badge">{KIND_NAME[l.kind]}</span>{" "}
              {l.path ? <Link to={l.path}><b>{l.title}</b></Link> : <b>{l.title}</b>}
              {l.sub && <span className="dim"> · {l.sub}</span>}
            </div>
            <div className="faint" style={{ fontSize: 12 }}>
              {[all && l.by ? `by ${l.by}` : null, until(l), `opened ${l.opened === 1 ? "once" : `${l.opened} times`}`].filter(Boolean).join(" · ")}
            </div>
          </div>
          {!l.run_out && <button className="btn small" onClick={() => void copyLink(l.url)}><Copy size={14} /> Copy</button>}
          <button className="btn small danger" onClick={() => remove(l)}>Remove</button>
        </li>
      ))}
    </ul>
  );
}
