/** One artist's genre tags, edited by an admin: taken off it, or added to it. What the sources gave
 * it stays as it came (backend tagging.py), so later lookups still come through and each change
 * can be taken back here. */

import { useQuery } from "@tanstack/react-query";
import { Plus, RotateCcw, X } from "lucide-react";
import { useState } from "react";
import { api } from "../api";
import { useUi } from "../store/ui";
import { refreshAll } from "./AdminMode";
import { Loading, Modal } from "./ui";

interface ArtistTag { name: string; added: boolean; category: number | null }
interface ArtistTags { id: number; name: string; tags: ArtistTag[]; taken_off: string[]; given: string[]; removed_everywhere?: string[] }
export interface TagOverview {
  tagged: number;
  tags: { name: string; artists: number; added: number; category: number | null; aliases: string[] }[];
  removed: { name: string; artists: number }[];
  categories: { id: number; name: string; show: "genre" | "apart" | "hidden"; tags: number }[];
  places?: { on: boolean; tags: { name: string; artists: number }[] };   // the general rule: place names off
}

export function useTagOverview() {
  return useQuery({ queryKey: ["admin-tags"], queryFn: () => api.get<TagOverview>("/api/admin/tags") });
}

export function TagEditor({ id, onClose }: { id: number; onClose: () => void }) {
  const notify = useUi((s) => s.notify);
  const q = useQuery({ queryKey: ["artist-tags", id], queryFn: () => api.get<ArtistTags>(`/api/admin/artists/${id}/tags`) });
  const all = useTagOverview();
  const [tags, setTags] = useState<ArtistTag[] | null>(null);
  const [typed, setTyped] = useState("");
  const [saving, setSaving] = useState(false);
  if (!q.data) return <Modal onClose={onClose}><Loading /></Modal>;
  const d = q.data;
  const now = tags ?? d.tags;
  const has = (n: string) => now.some((t) => t.name.toLocaleLowerCase() === n.toLocaleLowerCase());
  const category = (c: number | null) => all.data?.categories.find((x) => x.id === c)?.name;
  const add = (n: string) => {
    const name = n.trim();
    if (name && !has(name)) setTags([...now, { name, added: true, category: null }]);
    setTyped("");
  };
  // taken off this artist (before, or just now), and not given back yet
  const back = [...d.taken_off, ...d.tags.filter((t) => !t.added).map((t) => t.name)].filter((n) => !has(n));
  const save = async () => {
    setSaving(true);
    try {
      const r = await api.put<ArtistTags>(`/api/admin/artists/${id}/tags`, { tags: now.map((t) => t.name) });
      notify(r.removed_everywhere?.length
        ? `Saved. Not shown: ${r.removed_everywhere.join(", ")} (removed everywhere, under Admin → Tags)`
        : `${d.name}'s tags are saved`, r.removed_everywhere?.length ? "error" : "info");
      refreshAll();
      onClose();
    } catch (e) {
      notify((e as Error).message, "error");
      setSaving(false);
    }
  };
  return (
    <Modal onClose={onClose} className="tag-editor">
      <div className="kicker">Tags</div>
      <h2 className="h2">{d.name}</h2>
      <p className="dim" style={{ margin: "8px 0 14px" }}>
        Take off the tags that don't fit this artist, or add your own. The next lookup keeps to it.
      </p>
      <div className="tags tag-edit">
        {now.map((t) => (
          <span key={t.name} className={`tag ${t.added ? "mine" : ""}`} data-tip={t.added ? "Added by you" : undefined}>
            {t.name}{t.category != null && category(t.category) && <small>{category(t.category)}</small>}
            <button className="tag-x" aria-label={`Take ${t.name} off`} onClick={() => setTags(now.filter((x) => x !== t))}><X size={12} /></button>
          </span>
        ))}
        {now.length === 0 && <span className="faint">No tags</span>}
      </div>
      <form className="tag-add" onSubmit={(e) => { e.preventDefault(); add(typed); }}>
        <input className="input" list="tag-names" value={typed} onChange={(e) => setTyped(e.target.value)}
               placeholder="Add a tag…" maxLength={128} aria-label="Add a tag" />
        <datalist id="tag-names">{all.data?.tags.filter((t) => !has(t.name)).slice(0, 400).map((t) => <option key={t.name} value={t.name} />)}</datalist>
        <button className="btn" disabled={!typed.trim()}><Plus size={15} /> Add</button>
      </form>
      {back.length > 0 && (
        <div className="tag-back">
          <span className="faint">Taken off:</span>
          {back.map((n) => (
            <button key={n} className="tag tag-pick" data-tip="Give it back"
                    onClick={() => setTags([...now, { name: n, added: false, category: null }])}>
              <RotateCcw size={11} /> {n}
            </button>
          ))}
        </div>
      )}
      {d.given.length > 0 && <p className="faint" style={{ fontSize: 12, margin: "14px 0 0" }}>From the lookup: {d.given.join(", ")}</p>}
      <div className="row-actions" style={{ justifyContent: "flex-end", marginTop: 20 }}>
        <button className="btn" onClick={onClose}>Cancel</button>
        <button className="btn accent" disabled={saving || !tags} onClick={save}>{saving ? "Saving…" : "Save"}</button>
      </div>
    </Modal>
  );
}
