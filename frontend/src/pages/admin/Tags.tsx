/** Admin → Tags: every genre tag the artists carry (from Last.fm, MusicBrainz or a linked server),
 * to remove, rename or merge, and sort into categories; one tag's artists, and one artist's tags.
 * The rules hold for later lookups too, and each one can be taken back (backend tagging.py). */

import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, FolderInput, Pencil, Plus, RotateCcw, Search, Trash2, X } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, fmtNumber } from "../../api";
import { refreshAll, useAdminDialogs } from "../../components/AdminMode";
import { useTagOverview, type TagOverview } from "../../components/TagEditor";
import { Empty, Loading, Modal } from "../../components/ui";
import { useUi } from "../../store/ui";
import type { Artist } from "../../types";

type Tag = TagOverview["tags"][number];
type Category = TagOverview["categories"][number];
const PAGE = 150;
const SHOWS: [Category["show"], string, string][] = [
  ["genre", "With the genres", "Shown among the genre tags, as if it had no category"],
  ["apart", "Own row", "On the artist's page under the genres, named after the category"],
  ["hidden", "Hidden", "Not shown anywhere"],
];
const plural = (n: number, one: string, many = one + "s") => `${fmtNumber(n)} ${n === 1 ? one : many}`;

async function act(path: string, body: unknown, said: string) {
  const notify = useUi.getState().notify;
  try {
    await api.post(path, body);
    notify(said);
    refreshAll();
    return true;
  } catch (e) {
    notify((e as Error).message, "error");
    return false;
  }
}

export function Tags() {
  const q = useTagOverview();
  const [find, setFind] = useState("");
  const [sort, setSort] = useState<"count" | "name">("count");
  const [only, setOnly] = useState<"all" | "none" | "added" | number>("all");
  const [shown, setShown] = useState(PAGE);
  const [ticked, setTicked] = useState<Set<string>>(new Set());
  const [open, setOpen] = useState<string | null>(null);
  const [merging, setMerging] = useState<string[] | null>(null);
  const [sorting, setSorting] = useState<string[] | null>(null);
  const [removing, setRemoving] = useState<string[] | null>(null);
  const d = q.data;
  const list = useMemo(() => {
    if (!d) return [];
    const f = find.trim().toLocaleLowerCase();
    const out = d.tags.filter((t) => (!f || t.name.toLocaleLowerCase().includes(f) || t.aliases.some((a) => a.includes(f)))
      && (only === "all" || (only === "none" ? t.category == null : only === "added" ? t.added > 0 : t.category === only)));
    return sort === "name" ? [...out].sort((a, b) => a.name.localeCompare(b.name)) : out;
  }, [d, find, sort, only]);
  if (!d) return <Loading />;
  const cat = (id: number | null) => d.categories.find((c) => c.id === id);
  const page = list.slice(0, shown);
  const picked = list.filter((t) => ticked.has(t.name));
  const all = page.length > 0 && page.every((t) => ticked.has(t.name));
  const tick = (n: string, on: boolean) => setTicked((s) => { const x = new Set(s); if (on) x.add(n); else x.delete(n); return x; });
  const done = () => setTicked(new Set());
  const merged = d.tags.reduce((n, t) => n + t.aliases.length, 0);
  return (
    <>
      <section className="panel">
        <div className="panel-head">
          <div>
            <div className="kicker">Tags</div>
            <div className="h3">{plural(d.tags.length, "tag")} on {plural(d.tagged, "artist")}</div>
          </div>
          <ArtistTagsSearch />
        </div>
        <p className="dim" style={{ marginTop: 0 }}>
          The artists' genre tags, from Last.fm or MusicBrainz. Remove the ones that don't belong, rename them or merge two
          spellings into one, and sort them into categories. Lookups later follow what you decide here, and each change can be
          taken back. {(merged > 0 || d.removed.length > 0) && <span className="faint">{[merged && `${plural(merged, "name")} merged`, d.removed.length && `${fmtNumber(d.removed.length)} removed`].filter(Boolean).join(" · ")}.</span>}
        </p>
        <div className="toolbar tags-toolbar">
          <label className="tag-find">
            <Search size={15} />
            <input className="input" value={find} placeholder="Find a tag…" aria-label="Find a tag"
                   onChange={(e) => { setFind(e.target.value); setShown(PAGE); }} />
          </label>
          <select className="select" value={String(only)} aria-label="Which tags"
                  onChange={(e) => { const v = e.target.value; setOnly(v === "all" || v === "none" || v === "added" ? v : Number(v)); setShown(PAGE); }}>
            <option value="all">All tags</option>
            <option value="none">Without a category</option>
            <option value="added">Added to artists by you</option>
            {d.categories.map((c) => <option key={c.id} value={c.id}>{c.name} ({c.tags})</option>)}
          </select>
          <div className="seg" role="group" aria-label="Sort">
            <button className={sort === "count" ? "on" : ""} onClick={() => setSort("count")}>Most used</button>
            <button className={sort === "name" ? "on" : ""} onClick={() => setSort("name")}>A–Z</button>
          </div>
        </div>
        {page.length > 0 && (
          <div className="bare-bar">
            <label className="bare-all">
              <input type="checkbox" checked={all} ref={(el) => { if (el) el.indeterminate = picked.length > 0 && !all; }}
                     onChange={(e) => setTicked(e.target.checked ? new Set(page.map((t) => t.name)) : new Set())} />
              {picked.length ? `${fmtNumber(picked.length)} selected` : "Select all shown"}
            </label>
            <div className="grow" />
            {picked.length > 0 && <>
              <button className="btn small" onClick={() => setMerging(picked.map((t) => t.name))}>
                <Pencil size={14} /> {picked.length === 1 ? "Rename" : "Merge"}
              </button>
              <button className="btn small" onClick={() => setSorting(picked.map((t) => t.name))}><FolderInput size={14} /> Category</button>
              <button className="btn small danger" onClick={() => setRemoving(picked.map((t) => t.name))}><Trash2 size={14} /> Remove</button>
            </>}
          </div>
        )}
        {page.length ? (
          <div className="list tag-list">
            {page.map((t) => (
              <TagRow key={t.name} t={t} category={cat(t.category)} ticked={ticked.has(t.name)} open={open === t.name}
                      onTick={(on) => tick(t.name, on)} onOpen={() => setOpen(open === t.name ? null : t.name)}
                      onRename={() => setMerging([t.name])} onRemove={() => setRemoving([t.name])} />
            ))}
          </div>
        ) : <Empty title={d.tags.length ? "No tag like that" : "No tags yet"}>{d.tags.length ? undefined : "Tags come once the artists have been looked up on Last.fm or MusicBrainz."}</Empty>}
        {list.length > shown && (
          <div className="row-actions" style={{ marginTop: 12 }}>
            <span className="dim">{fmtNumber(shown)} of {fmtNumber(list.length)} shown</span>
            <button className="btn" onClick={() => setShown((n) => n + PAGE * 2)}>Show more</button>
          </div>
        )}
      </section>

      <Categories d={d} onShow={(id) => { setOnly(id); setShown(PAGE); }} />
      <Removed d={d} />

      {merging && <MergeDialog names={merging} d={d} onClose={() => setMerging(null)} onDone={done} />}
      {sorting && <CategoryDialog names={sorting} d={d} onClose={() => setSorting(null)} onDone={done} />}
      {removing && <RemoveDialog names={removing} d={d} onClose={() => setRemoving(null)} onDone={done} />}
    </>
  );
}

function TagRow({ t, category, ticked, open, onTick, onOpen, onRename, onRemove }: {
  t: Tag; category?: Category; ticked: boolean; open: boolean;
  onTick: (on: boolean) => void; onOpen: () => void; onRename: () => void; onRemove: () => void;
}) {
  return (
    <div className={`list-row tag-row ${ticked ? "ticked" : ""} ${open ? "open" : ""}`}>
      <div className="tag-row-main">
        <input type="checkbox" aria-label={`Select ${t.name}`} checked={ticked} onChange={(e) => onTick(e.target.checked)} />
        <button className="tag-open" aria-expanded={open} onClick={onOpen}>
          {open ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
          <b className="ellipsis">{t.name}</b>
        </button>
        {category && <span className={`badge ${category.show === "hidden" ? "" : "accent"}`}
                           data-tip={SHOWS.find(([s]) => s === category.show)?.[2]}>{category.name}{category.show === "hidden" && " · hidden"}</span>}
        <div className="grow" />
        <span className="faint tag-count">{plural(t.artists, "artist")}{t.added > 0 && ` · ${fmtNumber(t.added)} by you`}</span>
        <button className="btn small ghost" aria-label={`Rename ${t.name}`} data-tip="Rename, or merge into another" onClick={onRename}><Pencil size={14} /></button>
        <button className="btn small ghost danger" aria-label={`Remove ${t.name}`} data-tip="Remove everywhere" onClick={onRemove}><Trash2 size={14} /></button>
      </div>
      {t.aliases.length > 0 && (
        <div className="tag-aliases">
          <span className="faint">Merged in:</span>
          {t.aliases.map((a) => (
            <span key={a} className="tag">
              {a}
              <button className="tag-x" aria-label={`Make ${a} its own tag again`} data-tip="Make it its own tag again"
                      onClick={() => act("/api/admin/tags/unmerge", { names: [a] }, `${a} is its own tag again`)}><X size={12} /></button>
            </span>
          ))}
        </div>
      )}
      {open && <TagArtists name={t.name} />}
    </div>
  );
}

/** One tag's artists: each one's tags to edit, or this one taken off it alone. */
function TagArtists({ name }: { name: string }) {
  const setTags = useAdminDialogs((s) => s.setTags);
  const q = useQuery({ queryKey: ["tag-artists", name],
                       queryFn: () => api.get<{ artists: (Pick<Artist, "id" | "name" | "art"> & { added: boolean })[]; taken_off: { id: number; name: string }[] }>(
                         "/api/admin/tags/artists", { name }) });
  if (!q.data) return <div className="tag-artists"><Loading /></div>;
  const edit = (id: number, body: { add?: string[]; remove?: string[] }, said: string) =>
    act(`/api/admin/artists/${id}/tags`, body, said);
  return (
    <div className="tag-artists">
      <div className="tags">
        {q.data.artists.map((a) => (
          <span key={a.id} className={`tag ${a.added ? "mine" : ""}`}>
            <button className="tag-artist" data-tip="Edit this artist's tags" onClick={() => setTags(a.id)}>{a.name}</button>
            <button className="tag-x" aria-label={`Take ${name} off ${a.name}`} data-tip={`Take ${name} off ${a.name} alone`}
                    onClick={() => edit(a.id, { remove: [name] }, `${name} is taken off ${a.name}`)}><X size={12} /></button>
          </span>
        ))}
      </div>
      {q.data.taken_off.length > 0 && (
        <div className="tag-back">
          <span className="faint">Taken off:</span>
          {q.data.taken_off.map((a) => (
            <button key={a.id} className="tag tag-pick" data-tip={`Give ${name} back to ${a.name}`}
                    onClick={() => edit(a.id, { add: [name] }, `${a.name} has ${name} again`)}><RotateCcw size={11} /> {a.name}</button>
          ))}
        </div>
      )}
      <Link className="faint tag-page-link" to={`/tag/${encodeURIComponent(name)}`}>Everything tagged {name} →</Link>
    </div>
  );
}

/** Finds an artist, to edit its tags. */
function ArtistTagsSearch() {
  const setTags = useAdminDialogs((s) => s.setTags);
  const [text, setText] = useState("");
  const q = useQuery({ queryKey: ["tag-artist-search", text.trim()], enabled: text.trim().length > 1,
                       queryFn: () => api.get<{ artists: Artist[] }>("/api/search", { q: text.trim(), limit: 8 }) });
  return (
    <div className="tag-artist-search">
      <input className="input" value={text} onChange={(e) => setText(e.target.value)} placeholder="An artist's tags…"
             aria-label="Find an artist to edit its tags" />
      {text.trim().length > 1 && q.data && (
        <div className="tag-artist-hits">
          {q.data.artists.length ? q.data.artists.slice(0, 8).map((a) => (
            <button key={a.id} onClick={() => { setTags(a.id); setText(""); }}>
              <b>{a.name}</b><span className="faint ellipsis">{a.tags.slice(0, 4).join(", ")}</span>
            </button>
          )) : <span className="faint">No artist like that</span>}
        </div>
      )}
    </div>
  );
}

function Categories({ d, onShow }: { d: TagOverview; onShow: (id: number) => void }) {
  const notify = useUi((s) => s.notify);
  const [name, setName] = useState("");
  const call = async (fn: () => Promise<unknown>, said?: string) => {
    try {
      await fn();
      if (said) notify(said);
      refreshAll();
    } catch (e) {
      notify((e as Error).message, "error");
    }
  };
  return (
    <section className="panel">
      <div className="panel-head"><div className="h3">Categories</div></div>
      <p className="dim" style={{ marginTop: 0 }}>
        Sort tags that aren't genres (a country, a mood, an instrument…) into a category, to show them on a row of their own on the
        artist's page or not at all. Tags without a category are genres.
      </p>
      {d.categories.length > 0 && (
        <ul className="admin-list">
          {d.categories.map((c) => (
            <li key={c.id} className="tag-category">
              <input className="input" defaultValue={c.name} aria-label="Category name" maxLength={64} key={c.name}
                     onBlur={(e) => { const v = e.target.value.trim(); if (v && v !== c.name) call(() => api.patch(`/api/admin/tag-categories/${c.id}`, { name: v })); else e.target.value = c.name; }}
                     onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); }} />
              <div className="seg" role="group" aria-label={`How ${c.name} shows`}>
                {SHOWS.map(([s, label, tip]) => (
                  <button key={s} className={c.show === s ? "on" : ""} data-tip={tip}
                          onClick={() => c.show !== s && call(() => api.patch(`/api/admin/tag-categories/${c.id}`, { show: s }))}>{label}</button>
                ))}
              </div>
              <span className="tag-category-end">
                <button className="btn small ghost" disabled={!c.tags} data-tip="Show them in the list" onClick={() => onShow(c.id)}>{plural(c.tags, "tag")}</button>
                <button className="btn small ghost danger" aria-label={`Delete ${c.name}`} data-tip="Delete the category: its tags are genres again"
                        onClick={() => confirm(`Delete ${c.name}? Its ${plural(c.tags, "tag")} become genres again.`)
                          && call(() => api.del(`/api/admin/tag-categories/${c.id}`), `${c.name} is deleted`)}><Trash2 size={14} /></button>
              </span>
            </li>
          ))}
        </ul>
      )}
      <form className="row-actions" style={{ marginTop: 12 }}
            onSubmit={(e) => { e.preventDefault(); const v = name.trim(); if (v) call(() => api.post("/api/admin/tag-categories", { name: v }), `${v} is added`).then(() => setName("")); }}>
        <input className="input" style={{ maxWidth: 280 }} value={name} onChange={(e) => setName(e.target.value)} placeholder="A new category…" maxLength={64} aria-label="New category" />
        <button className="btn" disabled={!name.trim()}><Plus size={15} /> Add category</button>
      </form>
    </section>
  );
}

function Removed({ d }: { d: TagOverview }) {
  if (!d.removed.length) return null;
  return (
    <section className="panel">
      <div className="panel-head"><div className="h3">Removed</div></div>
      <p className="dim" style={{ marginTop: 0 }}>Taken off every artist, and kept off when the artists are looked up again.</p>
      <ul className="admin-list">
        {d.removed.map((r) => (
          <li key={r.name}>
            <div className="grow ellipsis"><b>{r.name}</b> <span className="faint">· {r.artists ? `had ${plural(r.artists, "artist")}` : "no artist has it now"}</span></div>
            <button className="btn small" onClick={() => act("/api/admin/tags/restore", { names: [r.name] }, `${r.name} is back`)}>
              <RotateCcw size={14} /> Restore
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}

function names(list: string[]) {
  return list.length <= 3 ? list.join(", ") : `${list.slice(0, 3).join(", ")} and ${fmtNumber(list.length - 3)} more`;
}

function MergeDialog({ names: from, d, onClose, onDone }: { names: string[]; d: TagOverview; onClose: () => void; onDone: () => void }) {
  const [into, setInto] = useState(from[0]);
  const target = d.tags.find((t) => t.name.toLocaleLowerCase() === into.trim().toLocaleLowerCase());
  const one = from.length === 1;
  const same = one && into.trim() === from[0];
  return (
    <Modal onClose={onClose}>
      <h2 className="h2">{one ? `Rename ${from[0]}` : `Merge ${plural(from.length, "tag")}`}</h2>
      <p className="dim" style={{ margin: "10px 0 14px" }}>
        {one ? "Give it a new name, or an existing tag's name to merge it into that one." : `${names(from)} become one tag: pick one of them or type another name.`}
      </p>
      <form onSubmit={async (e) => {
        e.preventDefault();
        if (same || !into.trim()) return;
        if (await act("/api/admin/tags/merge", { names: from, into: into.trim() },
                      target && !from.includes(target.name) ? `Merged into ${target.name}` : `Renamed to ${into.trim()}`)) { onDone(); onClose(); }
      }}>
        {!one && (
          <div className="tags" style={{ marginTop: 0 }}>
            {from.map((n) => <button type="button" key={n} className={`tag tag-pick ${into === n ? "on" : ""}`} onClick={() => setInto(n)}>{n}</button>)}
          </div>
        )}
        <input className="input" list="merge-names" value={into} onChange={(e) => setInto(e.target.value)} autoFocus maxLength={128} aria-label="New name" />
        <datalist id="merge-names">{d.tags.slice(0, 400).map((t) => <option key={t.name} value={t.name} />)}</datalist>
        <p className="faint" style={{ fontSize: 12.5, minHeight: 18, margin: "8px 0 0" }}>
          {target && !from.some((n) => n.toLocaleLowerCase() === target.name.toLocaleLowerCase())
            ? `Merges into ${target.name}, which ${plural(target.artists, "artist")} already have.` : "Later lookups follow the new name. Each old name can be split off again."}
        </p>
        <div className="row-actions" style={{ justifyContent: "flex-end", marginTop: 16 }}>
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button className="btn accent" disabled={same || !into.trim()}>{one && !target ? "Rename" : "Merge"}</button>
        </div>
      </form>
    </Modal>
  );
}

function CategoryDialog({ names: tags, d, onClose, onDone }: { names: string[]; d: TagOverview; onClose: () => void; onDone: () => void }) {
  const [fresh, setFresh] = useState("");
  const sorted = d.tags.some((t) => tags.includes(t.name) && t.category != null);    // one of them is in a category
  const put = async (category: number | null, label: string) => {
    if (await act("/api/admin/tags/category", { names: tags, category }, `${names(tags)} → ${label}`)) { onDone(); onClose(); }
  };
  const create = async () => {
    try {
      const c = await api.post<Category>("/api/admin/tag-categories", { name: fresh.trim() });
      await put(c.id, c.name);
    } catch (e) {
      useUi.getState().notify((e as Error).message, "error");
    }
  };
  return (
    <Modal onClose={onClose}>
      <h2 className="h2">Category</h2>
      <p className="dim" style={{ margin: "10px 0 14px" }}>For {names(tags)}.</p>
      {(d.categories.length > 0 || sorted) && (
        <div className="tag-category-picks">
          {d.categories.map((c) => (
            <button key={c.id} className="btn" onClick={() => put(c.id, c.name)}>
              {c.name}<span className="faint">{SHOWS.find(([s]) => s === c.show)?.[1]}</span>
            </button>
          ))}
          {sorted && <button className="btn ghost" onClick={() => put(null, "the genres")}>No category<span className="faint">a genre again</span></button>}
        </div>
      )}
      <form className="row-actions" style={{ marginTop: d.categories.length ? 14 : 0 }} onSubmit={(e) => { e.preventDefault(); if (fresh.trim()) create(); }}>
        <input className="input" style={{ flex: 1 }} value={fresh} onChange={(e) => setFresh(e.target.value)} placeholder={d.categories.length ? "Or a new category…" : "A new category, e.g. Country…"} maxLength={64} aria-label="New category" />
        <button className="btn" disabled={!fresh.trim()}><Plus size={15} /> Add</button>
      </form>
      <div className="row-actions" style={{ justifyContent: "flex-end", marginTop: 16 }}>
        <button className="btn" onClick={onClose}>Cancel</button>
      </div>
    </Modal>
  );
}

function RemoveDialog({ names: tags, d, onClose, onDone }: { names: string[]; d: TagOverview; onClose: () => void; onDone: () => void }) {
  const artists = d.tags.filter((t) => tags.includes(t.name)).reduce((n, t) => n + t.artists, 0);
  return (
    <Modal onClose={onClose}>
      <h2 className="h2">Remove {tags.length === 1 ? tags[0] : plural(tags.length, "tag")}?</h2>
      <p className="dim" style={{ margin: "10px 0 20px" }}>
        {tags.length > 1
          ? `${names(tags)}: taken off every artist that has them, and kept off when artists are looked up again. Each one can be restored under Removed, below.`
          : `Taken off ${artists === 1 ? "the artist" : `the ${fmtNumber(artists)} artists`} that ${artists === 1 ? "has" : "have"} it, and kept off when artists are looked up again. It can be restored under Removed, below.`}
      </p>
      <div className="row-actions" style={{ justifyContent: "flex-end" }}>
        <button className="btn" onClick={onClose} autoFocus>Cancel</button>
        <button className="btn danger solid" onClick={async () => {
          if (await act("/api/admin/tags/remove", { names: tags }, tags.length === 1 ? `${tags[0]} is removed` : `${plural(tags.length, "tag")} are removed`)) { onDone(); onClose(); }
        }}><Trash2 size={15} /> Remove</button>
      </div>
    </Modal>
  );
}
