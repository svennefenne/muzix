/** Admin → Users: the accounts, and what each one doesn't see (backend limits.py). What's left out
 * for an account isn't there for it anywhere, and nothing tells it something is missing. */

import { useQuery } from "@tanstack/react-query";
import { Plus, SlidersHorizontal, Trash2, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api, fmtNumber } from "../../api";
import { Avatar } from "../../components/Avatar";
import { Loading, Modal, Switch } from "../../components/ui";
import { useUi } from "../../store/ui";
import type { AvatarLook, ModuleKey } from "../../types";

interface Named { id: number; name: string }
interface Limits { genres: string[]; tags: string[]; untagged: string[]; artists: Named[]; allow: Named[]; sections: string[]; every_tag: boolean }
interface Account { id: number; username: string; is_admin: boolean; avatar: AvatarLook; limits: Limits; created_at: string }
interface Choices { genres: { name: string; albums: number; artists: number }[]; tags: { name: string; artists: number }[] }
interface Preview { artists: number; albums: number; songs: number; examples: string[] }

const SECTIONS: [ModuleKey, string][] = [["vgm", "VGM"], ["audiobooks", "Audiobooks"], ["podcasts", "Podcasts"], ["radio", "Radio"]];
const NO_GENRE = "No genre";
const plural = (n: number, one: string, many = one + "s") => `${fmtNumber(n)} ${n === 1 ? one : many}`;

/** What's left out for an account, in a line. */
function summary(l: Limits): string {
  const parts = [
    ...l.tags,
    ...l.genres.map((g) => g || NO_GENRE),
    ...(l.untagged.length ? [`untagged in ${l.untagged.join(", ")}`] : []),
    ...(l.artists.length ? [plural(l.artists.length, "artist")] : []),
    ...l.sections.map((k) => SECTIONS.find(([s]) => s === k)?.[1] ?? k),
  ];
  return parts.length ? `Doesn't see ${parts.join(", ")}` : "Sees everything";
}

export function AdminUsers() {
  const me = useUi((s) => s.user);
  const q = useQuery({ queryKey: ["users"], queryFn: () => api.get<Account[]>("/api/admin/users") });
  const [form, setForm] = useState({ username: "", password: "", is_admin: false });
  const [err, setErr] = useState("");
  const [limiting, setLimiting] = useState<Account | null>(null);
  const add = async () => {
    setErr("");
    try {
      await api.post("/api/admin/users", form);
      setForm({ username: "", password: "", is_admin: false });
      q.refetch();
    } catch (e) {
      setErr((e as Error).message);
    }
  };
  return (
    <>
      <section className="panel">
        <div className="panel-head"><div className="h3">Add a user</div></div>
        <div className="row-actions">
          <input className="input" style={{ maxWidth: 200 }} placeholder="Username" value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} />
          <input className="input" style={{ maxWidth: 220 }} type="password" placeholder="Password (6+)" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
          <label className="row-actions dim" style={{ gap: 6 }}><Switch checked={form.is_admin} onChange={(v) => setForm({ ...form, is_admin: v })} /> Admin</label>
          <button className="btn accent" onClick={add}><Plus size={15} /> Add</button>
        </div>
        {err && <p className="error-text">{err}</p>}
      </section>
      <section className="panel">
        <div className="panel-head"><div className="h3">Users</div></div>
        <p className="dim" style={{ marginTop: 0 }}>
          With <b>Limits</b> you choose music someone shouldn't come across: genre tags, genre folders, artists, or whole
          sections. For them it isn't there at all, and nothing tells them something is missing.
        </p>
        <div className="list">
          {(q.data || []).map((u) => (
            <div key={u.id} className="list-row user-row">
              <Avatar user={u} />
              <div className="grow">
                <b>{u.username}</b>
                <div className="dim user-sub">since {new Date(u.created_at).toLocaleDateString()} · <span className={summary(u.limits) === "Sees everything" ? "" : "limited"}>{summary(u.limits)}</span></div>
              </div>
              <label className="row-actions dim" style={{ gap: 6 }}>
                <Switch checked={u.is_admin} onChange={async (v) => { await api.put(`/api/admin/users/${u.id}`, { username: u.username, is_admin: v }); q.refetch(); }} /> Admin
              </label>
              <button className="btn small" onClick={() => setLimiting(u)}><SlidersHorizontal size={14} /> Limits</button>
              <button className="btn small" onClick={async () => {
                const pw = prompt(`New password for ${u.username} (6+ characters)`);
                if (pw) { await api.put(`/api/admin/users/${u.id}`, { username: u.username, is_admin: u.is_admin, password: pw }); }
              }}>Reset password</button>
              {u.id !== me?.id && <button className="mini" aria-label="Delete" onClick={async () => {
                if (confirm(`Delete ${u.username}?`)) { await api.del(`/api/admin/users/${u.id}`); q.refetch(); }
              }}><Trash2 size={15} /></button>}
            </div>
          ))}
        </div>
      </section>
      {limiting && <LimitsEditor account={limiting} onClose={() => setLimiting(null)} onSaved={() => q.refetch()} />}
    </>
  );
}

function LimitsEditor({ account, onClose, onSaved }: { account: Account; onClose: () => void; onSaved: () => void }) {
  const notify = useUi((s) => s.notify);
  const modules = useUi((s) => s.modules);
  const choices = useQuery({ queryKey: ["limit-choices"], queryFn: () => api.get<Choices>("/api/admin/limits/choices") });
  const [l, setL] = useState<Limits>(account.limits);
  const [allGenres, setAllGenres] = useState(false);
  const [typed, setTyped] = useState("");
  const [saving, setSaving] = useState(false);
  const body = useMemo(() => ({ ...l, artists: l.artists.map((a) => a.id), allow: l.allow.map((a) => a.id) }), [l]);

  // what these limits leave out, worked out a moment after each change
  const [preview, setPreview] = useState<Preview | null>(null);
  useEffect(() => {
    const t = setTimeout(() => api.post<Preview>("/api/admin/limits/preview", body).then(setPreview).catch(() => {}), 350);
    return () => clearTimeout(t);
  }, [body]);

  const toggle = (key: "genres" | "untagged" | "sections", v: string) =>
    setL({ ...l, [key]: l[key].includes(v) ? l[key].filter((x) => x !== v) : [...l[key], v] });
  const addTag = (t: string) => {
    const name = t.trim().toLocaleLowerCase();
    if (name && !l.tags.includes(name)) setL({ ...l, tags: [...l.tags, name] });
    setTyped("");
  };
  const save = async () => {
    setSaving(true);
    try {
      await api.put(`/api/admin/users/${account.id}/limits`, body);
      notify(`${account.username}'s limits are saved`);
      onSaved();
      onClose();
    } catch (e) {
      notify((e as Error).message, "error");
      setSaving(false);
    }
  };

  const genres = choices.data?.genres ?? [];
  const big = genres.filter((g) => g.albums >= 20 || l.genres.includes(g.name) || l.untagged.includes(g.name));
  const shownGenres = allGenres ? genres : big;
  return (
    <Modal onClose={onClose} className="limits-editor">
      <div className="kicker">What {account.username} sees</div>
      <h2 className="h2">Limits</h2>
      <p className="dim" style={{ margin: "8px 0 18px" }}>
        What you leave out here isn't anywhere for {account.username}: not in the library, search, Home, radio, shuffle
        or the linked libraries. Nothing tells them, and only an admin can change it.
      </p>
      {!choices.data ? <Loading /> : (
        <>
          <div className="field">
            <label>Genre tags</label>
            <span className="help">
              The artists' tags. A tag takes its subgenres along: <i>death metal</i> also leaves out <i>melodic death metal</i>.
              It counts when it's one of an artist's main tags, so a band with a little death metal in its past stays.
            </span>
            <div className="tags tag-edit">
              {l.tags.map((t) => (
                <span key={t} className="tag mine">{t}
                  <button className="tag-x" aria-label={`Show ${t} again`} onClick={() => setL({ ...l, tags: l.tags.filter((x) => x !== t) })}><X size={12} /></button>
                </span>
              ))}
            </div>
            <form className="tag-add" onSubmit={(e) => { e.preventDefault(); addTag(typed); }}>
              <input className="input" list="limit-tags" value={typed} onChange={(e) => setTyped(e.target.value)}
                     placeholder="A tag, like death metal…" maxLength={100} aria-label="Leave out a tag" />
              <datalist id="limit-tags">
                {choices.data.tags.filter((t) => !l.tags.includes(t.name)).slice(0, 600).map((t) => <option key={t.name} value={t.name}>{plural(t.artists, "artist")}</option>)}
              </datalist>
              <button className="btn" disabled={!typed.trim()}><Plus size={15} /> Leave out</button>
            </form>
            {l.tags.length > 0 && (
              <label className="row-actions dim" style={{ gap: 8, marginTop: 4 }}>
                <Switch checked={l.every_tag} onChange={(v) => setL({ ...l, every_tag: v })} /> Any of their tags, not only the main ones
              </label>
            )}
          </div>

          {l.tags.length > 0 && (
            <div className="field">
              <label>Artists without tags</label>
              <span className="help">Their tags are looked up over time. Until then, leave out the untagged artists filed in:</span>
              <GenrePicks genres={shownGenres} on={l.untagged} onToggle={(g) => toggle("untagged", g)} skipEmpty />
            </div>
          )}

          <div className="field">
            <label>Genre folders</label>
            <span className="help">Everything filed under a genre folder. An artist goes too when all their albums are in it.</span>
            <GenrePicks genres={shownGenres} on={l.genres} onToggle={(g) => toggle("genres", g)} />
            {genres.length > big.length && (
              <button className="link-btn" onClick={() => setAllGenres(!allGenres)}>
                {allGenres ? "Only the big ones" : `All ${fmtNumber(genres.length)} genre folders`}
              </button>
            )}
          </div>

          <div className="field">
            <label>Artists</label>
            <span className="help">Leave out an artist, or let one through that a tag or folder above would leave out.</span>
            <ArtistPicks label="Left out" picked={l.artists} onChange={(artists) => setL({ ...l, artists, allow: l.allow.filter((a) => !artists.some((b) => b.id === a.id)) })} />
            <ArtistPicks label="Let through" picked={l.allow} onChange={(allow) => setL({ ...l, allow, artists: l.artists.filter((a) => !allow.some((b) => b.id === a.id)) })} />
          </div>

          <div className="field">
            <label>Sections</label>
            <div className="row-actions">
              {SECTIONS.filter(([k]) => modules[k]).map(([k, label]) => (
                <label key={k} className="row-actions dim" style={{ gap: 6 }}>
                  <Switch checked={!l.sections.includes(k)} onChange={() => toggle("sections", k)} /> {label}
                </label>
              ))}
            </div>
          </div>

          <div className="limits-preview" aria-live="polite">
            {preview && (preview.albums || preview.artists || preview.songs)
              ? <>Leaves out <b>{plural(preview.artists, "artist")}</b>, <b>{plural(preview.albums, "album")}</b> and <b>{plural(preview.songs, "song")}</b>
                  {preview.examples.length > 0 && <span className="faint">: {preview.examples.join(", ")}{preview.artists > preview.examples.length ? "…" : ""}</span>}</>
              : <span className="faint">{l.sections.length ? "All the music shows." : "Nothing is left out."}</span>}
          </div>
        </>
      )}
      <div className="row-actions" style={{ justifyContent: "flex-end", marginTop: 20 }}>
        <button className="btn" onClick={onClose}>Cancel</button>
        <button className="btn accent" disabled={saving || !choices.data} onClick={save}>{saving ? "Saving…" : "Save"}</button>
      </div>
    </Modal>
  );
}

function GenrePicks({ genres, on, onToggle, skipEmpty }: { genres: Choices["genres"]; on: string[]; onToggle: (g: string) => void; skipEmpty?: boolean }) {
  return (
    <div className="tags limit-picks">
      {genres.filter((g) => !skipEmpty || g.name).map((g) => (
        <button key={g.name} className={`tag tag-pick ${on.includes(g.name) ? "on" : ""}`} aria-pressed={on.includes(g.name)} onClick={() => onToggle(g.name)}>
          {g.name || NO_GENRE}<small>{fmtNumber(g.albums)}</small>
        </button>
      ))}
    </div>
  );
}

function ArtistPicks({ label, picked, onChange }: { label: string; picked: Named[]; onChange: (a: Named[]) => void }) {
  const [text, setText] = useState("");
  const q = useQuery({ queryKey: ["limit-artists", text.trim()], enabled: text.trim().length > 1,
                       queryFn: () => api.get<(Named & { genre: string; albums: number })[]>("/api/admin/limits/artists", { q: text.trim() }) });
  return (
    <div className="limit-artists">
      <span className="tag-group-label">{label}</span>
      {picked.map((a) => (
        <span key={a.id} className="tag mine">{a.name}
          <button className="tag-x" aria-label={`Take ${a.name} off`} onClick={() => onChange(picked.filter((x) => x.id !== a.id))}><X size={12} /></button>
        </span>
      ))}
      <div className="tag-artist-search">
        <input className="input" value={text} onChange={(e) => setText(e.target.value)} placeholder="Find an artist…" aria-label={`${label}: find an artist`} />
        {text.trim().length > 1 && q.data && (
          <div className="tag-artist-hits">
            {q.data.length ? q.data.filter((a) => !picked.some((p) => p.id === a.id)).slice(0, 8).map((a) => (
              <button key={a.id} onClick={() => { onChange([...picked, { id: a.id, name: a.name }]); setText(""); }}>
                <b>{a.name}</b><span className="faint ellipsis">{[a.genre, plural(a.albums, "album")].filter(Boolean).join(" · ")}</span>
              </button>
            )) : <span className="faint">No artist like that</span>}
          </div>
        )}
      </div>
    </div>
  );
}
