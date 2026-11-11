/** The Library Network's chat (backend/muzix/chat.py): private conversations with people on this
 * server and on linked ones. On desktops it takes the right-hand panel's place while it's open (a
 * drawer where the window is too narrow for the panel); on phones it fills the screen. Its button
 * sits in the top bar while there's something to it: unread messages, or a conversation that went
 * on this past week. Albums and songs are linked by Ctrl+clicking them, or with the link button,
 * after which the next one tapped is linked (phones have no Ctrl). */

import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, Clock, Link2, MessageCircle, SendHorizontal, SquarePen, X } from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { queryClient } from "../actions";
import { api } from "../api";
import { useBackCloses } from "../backCloses";
import { Art } from "../components/ui";
import { useUi } from "../store/ui";
import { HoverCard, LinkCard, MoreInfoHost } from "./Links";
import { clock, dayLabel, type Draft, parseDraft, type Person, personKey, preview, runs, shortWhen, splitUrls } from "./logic";
import { type Message, type Thread, useChat, useChatActive, useChatOn, useConversations } from "./store";

const mac = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform);

function usePhone() {
  const [phone, setPhone] = useState(() => matchMedia("(max-width: 860px)").matches);
  useEffect(() => {
    const m = matchMedia("(max-width: 860px)");
    const on = () => setPhone(m.matches);
    m.addEventListener("change", on);
    return () => m.removeEventListener("change", on);
  }, []);
  return phone;
}

/** A person's round mark: their initials on a colour of their name (as covers without a picture). */
function Face({ name }: { name: string }) {
  return <Art name={name} round className="chat-face" />;
}

/** The top bar's button, where the fullscreen button was: there while there's something to the chat. */
export function ChatButton() {
  const active = useChatActive();
  const open = useChat((s) => s.open);
  const unread = useConversations().data?.unread || 0;
  if (!active) return null;
  const label = unread ? `Messages: ${unread} unread` : "Messages";
  return (
    <button className={`iconbtn chat-btn ${open ? "on" : ""}`} aria-label={label} data-tip={open ? "Close the messages" : label}
            aria-pressed={open} onClick={() => (open ? useChat.getState().close() : useChat.getState().show())}>
      <MessageCircle size={15} />
      {unread > 0 && <span className="chat-count" aria-hidden>{unread > 9 ? "9+" : unread}</span>}
    </button>
  );
}

/** Everything the chat needs on every page: its panel's companions (what's said live, Ctrl+click,
 * the pick banner, the card on hover and "More info"). */
export function ChatHost() {
  const on = useChatOn();
  useLive(on);
  useLinking(on);
  const picking = useChat((s) => s.picking);
  const looking = useChat((s) => (s.open && s.view === "thread" && s.who ? personKey(s.who) : ""));
  useEffect(() => {
    if (looking && noted?.key === looking && useUi.getState().toast?.id === noted.id) useUi.setState({ toast: null });
  }, [looking]);
  if (!on) return null;
  return (
    <>
      {picking && <PickBanner />}
      <HoverCard />
      <MoreInfoHost />
    </>
  );
}

// ------------------------------------------------------------ the panel

export function ChatPanel() {
  const { open, view, who, picking, close } = useChat();
  const phone = usePhone();
  useBackCloses("chat", open && phone && !picking, close);
  if (!open) return null;
  return (
    <aside className={`dock chatdock ${picking ? "picking" : ""}`} aria-label="Messages">
      {view === "thread" && who ? <Conversation who={who} key={personKey(who)} /> : view === "people" ? <People /> : <Conversations />}
    </aside>
  );
}

function CloseButton() {
  return (
    <button className="iconbtn" data-tip="Close the messages" aria-label="Close the messages" onClick={() => useChat.getState().close()}>
      <X size={15} />
    </button>
  );
}

/** Albums and songs shared before choosing whom they go to. */
function Pending() {
  const pending = useChat((s) => s.pending);
  if (!pending.length) return null;
  return (
    <div className="chat-pending">
      <p>Choose who to send {pending.length === 1 ? <b>{pending[0].title}</b> : `these ${pending.length}`} to.</p>
      <DraftLinks links={pending} onRemove={(d) => useChat.setState({ pending: pending.filter((p) => p !== d) })} />
    </div>
  );
}

function Conversations() {
  const q = useConversations();
  const setView = useChat((s) => s.setView);
  const show = useChat((s) => s.show);
  const list = q.data?.conversations || [];
  return (
    <>
      <div className="np-head chat-head">
        <h2 className="np-heading">Messages</h2>
        <button className="iconbtn" data-tip="New message" aria-label="New message" onClick={() => setView("people")}><SquarePen size={15} /></button>
        <CloseButton />
      </div>
      <Pending />
      <div className="chat-scroll">
        {q.isLoading ? <RowSkeletons /> : list.length ? list.map((c) => (
          <button key={personKey(c.with)} className={`chat-row ${c.unread ? "unread" : ""}`} onClick={() => show(c.with)}>
            <Face name={c.with.name} />
            <span className="chat-row-text">
              <span className="chat-row-name">
                <b className="ellipsis">{c.with.name}</b>
                {!c.with.here && <small className="ellipsis">{c.with.place}</small>}
              </span>
              <span className="chat-row-last ellipsis">{preview(c.last)}</span>
            </span>
            <span className="chat-row-meta">
              <small>{shortWhen(c.at)}</small>
              {c.unread > 0 && <span className="chat-count" aria-label={`${c.unread} unread`}>{c.unread > 9 ? "9+" : c.unread}</span>}
            </span>
          </button>
        )) : (
          <div className="chat-empty">
            <p>No conversations yet. Write to someone on this server, or on a server it's linked with, and share what you're listening to.</p>
            <button className="btn" onClick={() => setView("people")}><SquarePen size={15} /> New message</button>
          </div>
        )}
      </div>
    </>
  );
}

function RowSkeletons() {
  return <>{[0, 1, 2].map((i) => <div key={i} className="chat-row skeleton" aria-hidden><span className="chat-face" /><span /></div>)}</>;
}

function People() {
  const setView = useChat((s) => s.setView);
  const show = useChat((s) => s.show);
  const admin = useUi((s) => !!s.user?.is_admin);
  const [filter, setFilter] = useState("");
  const q = useQuery({ queryKey: ["chat", "people"], queryFn: () => api.get<Person[]>("/api/chat/people"), staleTime: 30_000 });
  const words = filter.trim().toLowerCase();
  const found = (q.data || []).filter((p) => !words || p.name.toLowerCase().includes(words) || p.place.toLowerCase().includes(words));
  // this server's people first, then each linked server's
  const places = [...new Set(found.sort((a, b) => Number(b.here) - Number(a.here)).map((p) => p.place))];
  return (
    <>
      <div className="np-head chat-head">
        <button className="iconbtn" aria-label="Back to the conversations" onClick={() => setView("list")}><ChevronLeft size={16} /></button>
        <h2 className="np-heading">New message</h2>
        <CloseButton />
      </div>
      <Pending />
      <div className="chat-find">
        <input className="input" placeholder="Find someone" aria-label="Find someone" value={filter} autoFocus
               onChange={(e) => setFilter(e.target.value)} />
      </div>
      <div className="chat-scroll">
        {q.isLoading ? <RowSkeletons /> : places.map((place) => (
          <section key={place} className="chat-group">
            <h3 className="chat-group-name">{place}</h3>
            {found.filter((p) => p.place === place).map((p) => (
              <button key={personKey(p)} className="chat-row" onClick={() => show(p)}>
                <Face name={p.name} />
                <span className="chat-row-text"><b className="ellipsis">{p.name}</b></span>
              </button>
            ))}
          </section>
        ))}
        {!q.isLoading && !found.length && (
          <div className="chat-empty">
            {words ? <p>Nobody by that name.</p>
              : <p>Nobody to write to yet. Once others have accounts here{admin ? ", or this server is linked with another under Admin → Library Network," : " or on a linked server,"} they're listed here.</p>}
          </div>
        )}
      </div>
    </>
  );
}

// ------------------------------------------------------------ a conversation

function Conversation({ who }: { who: Person }) {
  const key = personKey(who);
  const setView = useChat((s) => s.setView);
  const q = useQuery({
    queryKey: ["chat", "thread", key],
    queryFn: () => api.get<Thread>(`/api/chat/with/${who.server}/${who.user}`),
  });
  const [older, setOlder] = useState<Message[]>([]);
  const [more, setMore] = useState<boolean | null>(null);
  const unread = useConversations().data?.conversations.find((c) => personKey(c.with) === key)?.unread || 0;
  const scroller = useRef<HTMLDivElement>(null);
  const atEnd = useRef(true);
  const shownWho = q.data?.with || who;
  const latest = q.data?.messages || [];
  const messages = [...older.filter((m) => !latest.some((l) => l.id === m.id)), ...latest];

  // what they wrote is read once it's on screen
  useEffect(() => {
    if (!unread || !q.data || document.visibilityState !== "visible") return;
    api.post(`/api/chat/with/${who.server}/${who.user}/read`).then(() => queryClient.invalidateQueries({ queryKey: ["chat"], exact: true }));
  }, [unread, q.data, who.server, who.user]);

  // the latest message stays in sight, unless the reader scrolled up
  useLayoutEffect(() => {
    const el = scroller.current;
    if (el && atEnd.current) el.scrollTop = el.scrollHeight;
  }, [latest.length, q.data]);

  const earlier = async () => {
    const first = messages[0];
    if (!first) return;
    const el = scroller.current;
    const from = el ? el.scrollHeight - el.scrollTop : 0;
    const page = await api.get<Thread>(`/api/chat/with/${who.server}/${who.user}`, { before: first.id });
    setOlder((o) => [...page.messages, ...o]);
    setMore(page.more);
    requestAnimationFrame(() => { if (el) el.scrollTop = el.scrollHeight - from; });
  };

  return (
    <>
      <div className="np-head chat-head">
        <button className="iconbtn" aria-label="Back to the conversations" onClick={() => setView("list")}><ChevronLeft size={16} /></button>
        <Face name={shownWho.name} />
        <div className="chat-who">
          <b className="ellipsis">{shownWho.name}</b>
          <small className="ellipsis">{shownWho.here ? "On this server" : shownWho.place}</small>
        </div>
        <CloseButton />
      </div>
      <div className="chat-scroll chat-thread" ref={scroller} role="log" aria-label={`Messages with ${shownWho.name}`}
           onScroll={(e) => { const el = e.currentTarget; atEnd.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40; }}>
        {(more ?? q.data?.more) && <button className="np-link chat-earlier" onClick={earlier}>Show earlier messages</button>}
        {q.isLoading && <p className="chat-quiet">Loading…</p>}
        {q.isError && <p className="error-text chat-quiet">{(q.error as Error).message}</p>}
        {q.data && !messages.length && <p className="chat-quiet">Say hello to {shownWho.name}, or link an album or a song for them to hear.</p>}
        {runs(messages).map((run) => (
          <div key={run.items[0].id} className={`chat-run ${run.items[0].mine ? "mine" : ""}`}>
            {run.day && <h3 className="chat-day">{dayLabel(run.day)}</h3>}
            {run.items.map((m) => (
              <div key={m.id} className={`chat-msg ${m.mine ? "mine" : ""}`}>
                {m.text && <p className="chat-text">{splitUrls(m.text).map((part, i) => part.url
                  ? <a key={i} href={part.url} target="_blank" rel="noopener noreferrer">{part.text}</a> : part.text)}</p>}
                {m.links.map((link, i) => <LinkCard key={i} link={link} message={m.id} index={i} />)}
              </div>
            ))}
            <div className="chat-meta">
              {clock(run.items[run.items.length - 1].sent_at)}
              {run.items.some((m) => m.mine && !m.delivered) && (
                <span className="chat-waiting" data-tip={`${shownWho.place} can't be reached right now: it gets the message once it's back`}>
                  <Clock size={11} /> Waiting for {shownWho.place}
                </span>
              )}
            </div>
          </div>
        ))}
      </div>
      <Composer who={shownWho} />
    </>
  );
}

function DraftLinks({ links, onRemove }: { links: Draft[]; onRemove: (d: Draft) => void }) {
  return (
    <div className="chat-drafts">
      {links.map((d) => (
        <span key={`${d.kind}:${d.id}`} className="chat-draft">
          <Art src={d.art} name={d.title} size={64} />
          <span className="chat-draft-text"><b className="ellipsis">{d.title}</b><small className="ellipsis">{d.kind === "track" ? "Song" : "Album"}{d.sub ? ` · ${d.sub}` : ""}</small></span>
          <button className="mini" aria-label={`Leave out ${d.title}`} onClick={() => onRemove(d)}><X size={14} /></button>
        </span>
      ))}
    </div>
  );
}

function Composer({ who }: { who: Person }) {
  const key = personKey(who);
  const draft = useChat((s) => s.drafts[key]) || { text: "", links: [] };
  const setDraft = useChat((s) => s.setDraft);
  const picking = useChat((s) => s.picking);
  const setPicking = useChat((s) => s.setPicking);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const box = useRef<HTMLTextAreaElement>(null);
  const empty = !draft.text.trim() && !draft.links.length;

  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 140)}px`;
  }, [draft.text]);

  const send = async () => {
    if (busy || empty) return;
    setBusy(true);
    setError("");
    try {
      await api.post(`/api/chat/with/${who.server}/${who.user}`, {
        text: draft.text, links: draft.links.map((l) => ({ kind: l.kind, id: l.id })), name: who.name,
      });
      setDraft(who, { text: "", links: [] });
      queryClient.invalidateQueries({ queryKey: ["chat"] });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
      box.current?.focus();
    }
  };

  return (
    <div className="chat-compose">
      {draft.links.length > 0 && <DraftLinks links={draft.links} onRemove={(d) => setDraft(who, { links: draft.links.filter((l) => l !== d) })} />}
      <div className="chat-inputrow">
        <button className={`iconbtn ${picking ? "on" : ""}`} aria-pressed={picking} aria-label="Link an album or a song"
                data-tip={picking ? "Stop linking" : "Link an album or a song: click the button, then the album or song"}
                onClick={() => setPicking(!picking)}>
          <Link2 size={15} />
        </button>
        <textarea ref={box} className="chat-input" rows={1} value={draft.text} placeholder={`Message ${who.name}`}
                  aria-label={`Message ${who.name}`} maxLength={4000}
                  onChange={(e) => setDraft(who, { text: e.target.value })}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                      e.preventDefault();
                      send();
                    }
                  }} />
        <button className="iconbtn chat-send" aria-label="Send" data-tip="Send" data-tip-key="Enter" disabled={empty || busy} onClick={send}>
          <SendHorizontal size={15} />
        </button>
      </div>
      {error ? <p className="error-text chat-hint" role="alert">{error}</p>
        : <p className="chat-hint desktop-only">{picking ? "Click an album or a song to link it · Esc stops" : `${mac ? "⌘" : "Ctrl"}+click an album or a song to link it`}</p>}
    </div>
  );
}

// ------------------------------------------------------------ linking

function PickBanner() {
  const setPicking = useChat((s) => s.setPicking);
  return (
    <div className="chat-pick" role="status">
      <Link2 size={16} />
      <span>Tap an album or a song to link it</span>
      <button className="btn small" onClick={() => setPicking(false)}>Cancel</button>
    </div>
  );
}

/** Ctrl (⌘ on a Mac) + click on an album or a song while the chat is open links it; so does any
 * click on one while picking. What can be linked carries data-link (store.ts: linkData). */
function useLinking(on: boolean) {
  const picking = useChat((s) => s.picking);
  useEffect(() => {
    if (!on) return;
    const take = (e: MouseEvent) => {
      const s = useChat.getState();
      if (!s.picking && !((e.ctrlKey || e.metaKey) && s.open)) return null;
      const el = e.target instanceof Element ? e.target.closest("[data-link]") : null;
      return parseDraft(el?.getAttribute("data-link"));
    };
    const click = (e: MouseEvent) => {
      const d = take(e);
      if (!d) return;
      e.preventDefault();
      e.stopPropagation();
      useChat.getState().link(d);
    };
    // a double click on a song plays it: not when it was being linked
    const double = (e: MouseEvent) => { if (take(e) || ((e.ctrlKey || e.metaKey) && useChat.getState().open)) e.stopPropagation(); };
    const key = (e: KeyboardEvent) => { if (e.key === "Escape" && useChat.getState().picking) useChat.getState().setPicking(false); };
    window.addEventListener("click", click, true);
    window.addEventListener("dblclick", double, true);
    window.addEventListener("keydown", key);
    return () => {
      window.removeEventListener("click", click, true);
      window.removeEventListener("dblclick", double, true);
      window.removeEventListener("keydown", key);
    };
  }, [on]);
  useEffect(() => {
    document.body.classList.toggle("chat-picking", picking);
  }, [picking]);
}

// ------------------------------------------------------------ what's said live

/** The note about the last message that came in, and whose conversation it's from (it goes once that's open). */
let noted: { id: number; key: string } | null = null;

interface Word { event: "new" | "read" | "delivered"; with?: Person; mine?: boolean; text?: string; links?: number }

/** The server's word (over Muzix Connect's connection) that something was written, read or got
 * there: the lists again, and a note when it's for the user and they aren't looking at it. */
function useLive(on: boolean) {
  useEffect(() => {
    if (!on) return;
    const hear = (e: Event) => {
      const w = (e as CustomEvent<Word>).detail;
      queryClient.invalidateQueries({ queryKey: ["chat"] });
      if (w.event !== "new" || w.mine || !w.with) return;
      const s = useChat.getState();
      const looking = s.open && s.view === "thread" && !!s.who && personKey(s.who) === personKey(w.with) && document.visibilityState === "visible";
      if (looking) return;
      const said = w.text || (w.links === 1 ? "sent a link" : `sent ${w.links} links`);
      const who = w.with;
      useUi.getState().notify(`${who.name}: ${said}`, "info", { label: "Open", run: () => useChat.getState().show(who) });
      noted = { id: useUi.getState().toast?.id ?? 0, key: personKey(who) };
    };
    const back = () => { if (document.visibilityState === "visible") queryClient.invalidateQueries({ queryKey: ["chat"] }); };
    window.addEventListener("muzix:chat", hear);
    document.addEventListener("visibilitychange", back);
    return () => {
      window.removeEventListener("muzix:chat", hear);
      document.removeEventListener("visibilitychange", back);
    };
  }, [on]);
}
