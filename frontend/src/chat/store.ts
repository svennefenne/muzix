/** The chat's state on this page: whether it's open, the conversation in it, what's being written
 * to whom, and linking (Ctrl+click, or the link button's pick mode). The messages themselves come
 * from the server (api.ts in this folder). */

import { useQuery } from "@tanstack/react-query";
import { create } from "zustand";
import { api } from "../api";
import { useShell } from "../player/app";
import { useUi } from "../store/ui";
import { type Conversation, type Draft, isActive, type Person, personKey, withLink } from "./logic";

export interface ChatLink {
  kind: "album" | "track";
  server: string;
  id: number;
  title: string;
  artist: string;
  year: number | null;
  album: { id: number; title: string } | null;
  place: string;                     // the server it's on
  elsewhere: boolean;                // that server isn't this one
  reach: "here" | "network" | "away";
  cover: string | null;
  here_album: number | null;
  here_track: number | null;
  songs: number;
  length: number;
}

export interface ChatSong { id: number; title: string; artist: string; duration: number; disc: number; no: number; local: number | null; stream: string | null }

export interface Message {
  id: number;
  mine: boolean;
  text: string;
  sent_at: string;
  delivered: boolean;
  read: boolean;
  links: ChatLink[];
}

export interface Thread { with: Person; more: boolean; messages: Message[] }

interface Composing { text: string; links: Draft[] }

interface ChatState {
  open: boolean;
  view: "list" | "people" | "thread";
  who: Person | null;
  drafts: Record<string, Composing>;
  pending: Draft[];                  // shared before choosing who to send it to
  picking: boolean;                  // the link button: the next album or song clicked is linked
  more: { message: number; index: number; link: ChatLink } | null;    // "More info"
  show: (who?: Person | null) => void;
  close: () => void;
  setView: (v: ChatState["view"]) => void;
  setDraft: (who: Person, patch: Partial<Composing>) => void;
  link: (d: Draft) => void;
  setPicking: (v: boolean) => void;
  setMore: (m: ChatState["more"]) => void;
}

export const useChat = create<ChatState>((set, get) => ({
  open: false,
  view: "list",
  who: null,
  drafts: {},
  pending: [],
  picking: false,
  more: null,
  show: (who) => {
    if (!who) return set({ open: true, view: get().who ? "thread" : "list" });
    // what was shared before choosing whom: into this conversation
    const { pending, drafts } = get();
    const key = personKey(who);
    const d = drafts[key] || { text: "", links: [] };
    set({
      open: true, view: "thread", who, pending: [],
      drafts: pending.length ? { ...drafts, [key]: { ...d, links: pending.reduce(withLink, d.links) } } : drafts,
    });
  },
  close: () => set({ open: false, picking: false }),
  setView: (view) => set(view === "thread" ? { view } : { view, picking: false }),
  setDraft: (who, patch) => {
    const key = personKey(who);
    const d = get().drafts[key] || { text: "", links: [] };
    set({ drafts: { ...get().drafts, [key]: { ...d, ...patch } } });
  },
  link: (draft) => {
    const { who, view, drafts } = get();
    if (who && view === "thread") {
      const key = personKey(who);
      const d = drafts[key] || { text: "", links: [] };
      set({ open: true, picking: false, drafts: { ...drafts, [key]: { ...d, links: withLink(d.links, draft) } } });
    } else {
      set({ open: true, picking: false, view: view === "people" ? "people" : "list", pending: withLink(get().pending, draft) });
    }
  },
  setPicking: (picking) => set({ picking }),
  setMore: (more) => set({ more }),
}));

/** Whether this page has the chat: the Library Network module on, and the server's library shown (the
 * app's own library has no people). */
export function useChatOn() {
  const network = useUi((s) => s.modules.network);
  const user = useUi((s) => !!s.user);
  const local = useShell((s) => s.library === "local");
  return network && user && !local;
}

export interface Summary { conversations: Conversation[]; unread: number }

/** The user's conversations and unread count; fetched again on each word from the server (live.ts). */
export function useConversations() {
  const on = useChatOn();
  return useQuery({
    queryKey: ["chat"], enabled: on, refetchInterval: 60_000, staleTime: 10_000,
    queryFn: () => api.get<Summary>("/api/chat"),
  });
}

/** Whether the chat button shows (logic.ts: isActive). */
export function useChatActive() {
  const q = useConversations();
  const open = useChat((s) => s.open);
  return useChatOn() && isActive(q.data?.conversations, open);
}

/** "Share in chat" from a menu: into the open conversation, or the chat opens to choose whom. */
export function shareInChat(d: Draft) {
  useChat.getState().link(d);
}

/** What to put on an album or song so it can be linked: `data-link={linkData(...)}`. */
export function linkData(kind: Draft["kind"], id: number, title: string, sub: string, art?: string | null) {
  return JSON.stringify({ kind, id, title, sub, art: art ?? null });
}
