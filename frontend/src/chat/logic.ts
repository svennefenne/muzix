/** The chat's rules that need nothing but their arguments (tested in frontend/tests/chat.test.ts). */

export interface Person {
  server: string; user: number; name: string; place: string; here: boolean;
  avatar?: { picture: string | null; letter: string | null; color: string | null };   // their icon (components/Avatar.tsx)
}

export interface Conversation {
  with: Person;
  at: string | null;               // the last message's time
  unread: number;
  last: { text: string; mine: boolean; links: number };
}

/** What can be linked in a message: an album or a song, as the page shows it. */
export interface Draft { kind: "album" | "track"; id: number; title: string; sub: string; art: string | null }

export const ACTIVE_DAYS = 7;
export const MAX_LINKS = 5;

export function personKey(p: { server: string; user: number }) {
  return `${p.server}/${p.user}`;
}

/** Whether the chat button shows: something unread, a conversation with something new in the last
 * week, or the chat open. */
export function isActive(conversations: Conversation[] | undefined, open: boolean, now = Date.now()) {
  if (open) return true;
  return (conversations || []).some((c) => c.unread > 0 || (!!c.at && now - Date.parse(c.at) < ACTIVE_DAYS * 86400_000));
}

/** A conversation's last message in a line. */
export function preview(last: Conversation["last"]) {
  const said = last.text.replace(/\s+/g, " ").trim();
  const linked = last.links === 1 ? "a link" : last.links > 1 ? `${last.links} links` : "";
  const text = said || (linked ? `Sent ${linked}` : "");
  return last.mine && text ? `You: ${text}` : text;
}

/** A draft's links with one more (the same one once, MAX_LINKS at most). */
export function withLink(links: Draft[], d: Draft): Draft[] {
  if (links.some((l) => l.kind === d.kind && l.id === d.id)) return links;
  return [...links, d].slice(-MAX_LINKS);
}

/** What a data-link attribute holds, or null when it's something else. */
export function parseDraft(text: string | null | undefined): Draft | null {
  if (!text) return null;
  try {
    const d = JSON.parse(text);
    if ((d.kind !== "album" && d.kind !== "track") || !Number.isInteger(d.id)) return null;
    return { kind: d.kind, id: d.id, title: String(d.title || ""), sub: String(d.sub || ""), art: d.art ? String(d.art) : null };
  } catch {
    return null;
  }
}

/** A day's heading above its messages: Today, Yesterday, a weekday this week, else the date. */
export function dayLabel(iso: string, now = new Date()) {
  const d = new Date(iso);
  const day = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const diff = Math.round((day(now) - day(d)) / 86400_000);
  if (diff === 0) return "Today";
  if (diff === 1) return "Yesterday";
  if (diff > 1 && diff < 7) return d.toLocaleDateString("en-GB", { weekday: "long" });
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", ...(d.getFullYear() !== now.getFullYear() ? { year: "numeric" } : {}) });
}

/** A time on a message: 14:05. */
export function clock(iso: string) {
  return new Date(iso).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
}

/** A short time for the list of conversations: 14:05 today, else Yesterday, a weekday (Thu) or the date. */
export function shortWhen(iso: string | null, now = new Date()) {
  if (!iso) return "";
  const label = dayLabel(iso, now);
  if (label === "Today") return clock(iso);
  return /^[A-Z][a-z]+day$/.test(label) && label !== "Yesterday" ? label.slice(0, 3) : label;
}

/** Text with its web addresses apart, so they can be links: [text, url, text, ...]. */
export function splitUrls(text: string): { text: string; url?: string }[] {
  const out: { text: string; url?: string }[] = [];
  const re = /\bhttps?:\/\/[^\s<>"]+[^\s<>".,;:!?)\]'}]/gi;
  let at = 0;
  for (const m of text.matchAll(re)) {
    if (m.index! > at) out.push({ text: text.slice(at, m.index) });
    out.push({ text: m[0], url: m[0] });
    at = m.index! + m[0].length;
  }
  if (at < text.length) out.push({ text: text.slice(at) });
  return out;
}

/** Messages in runs: a new run where the day changes, the writer changes, or five minutes pass. */
export function runs<T extends { mine: boolean; sent_at: string }>(messages: T[]): { day: string | null; items: T[] }[] {
  const out: { day: string | null; items: T[] }[] = [];
  let lastDay = "";
  for (const m of messages) {
    const day = m.sent_at.slice(0, 10);
    const prev = out[out.length - 1]?.items.at(-1);
    const newDay = day !== lastDay;
    if (newDay || !prev || prev.mine !== m.mine || Date.parse(m.sent_at) - Date.parse(prev.sent_at) > 5 * 60_000) {
      out.push({ day: newDay ? m.sent_at : null, items: [m] });
    } else {
      out[out.length - 1].items.push(m);
    }
    lastDay = day;
  }
  return out;
}
