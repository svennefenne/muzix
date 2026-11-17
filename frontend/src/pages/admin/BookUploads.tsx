/** Admin → Upload → Audiobooks (backend audiobook/pipeline.py, api/bookadmin.py): the books filed without a source
 * sure of them ("Needs a look": the right one picked from any source, or kept as it is), those set aside in
 * Audiobooks/_Duplicates (filed beside the library's copy, in its place, or deleted), and the latest imports. */

import { useQueries, useQuery } from "@tanstack/react-query";
import { Check, Copy, ExternalLink, Search, Trash2 } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { ago, api, fmtBytes, fmtLong } from "../../api";
import { queryClient } from "../../actions";
import { Art, Empty, Modal } from "../../components/ui";
import { useUi } from "../../store/ui";
import { GenreLabel, languageName } from "../../components/BookLabels";

interface Brief {
  id: number; title: string; author: string; narrator: string; series: string; series_part: string; year: number;
  genre: string; language: string; duration: number; asin: string; art: string | null; path: string;
}

interface Hit {
  source: string; id: string; asin: string; url: string; title: string; subtitle: string; authors: string[]; narrators: string[];
  runtime: number; release: string; year: string; series: [string, string][]; language: string; image: string;
}

interface Source { id: string; name: string }

interface Dupe {
  name: string; title: string; authors: string[]; narrators: string[]; size: number; seconds: number; library: Brief | null;
}

interface BookImport {
  id: number; status: string; progress: number; message: string; batch: string; watched: string;
  started_at: string | null; finished_at: string | null;
  books: { title: string; author: string; folder: string; genre: string; language: string; sure: boolean; sources: string[];
           duplicate_of: number | null; seconds: number; chapters: number }[];
  failed: { title: string; error: string; files: number }[];
}

const refresh = () => {
  for (const k of ["book-review", "book-dupes", "book-imports", "books"]) queryClient.invalidateQueries({ queryKey: [k] });
};

async function act(fn: () => Promise<unknown>, done: string) {
  try {
    await fn();
    useUi.getState().notify(done);
    refresh();
  } catch (e) {
    useUi.getState().notify((e as Error).message, "error");
  }
}

/** Under the drop zone on the Audiobooks side: Needs a look, the duplicates, then the latest imports. */
export function BookPanels() {
  return (
    <>
      <NeedsALook />
      <Duplicates />
      <LatestImports />
    </>
  );
}

// ---------------------------------------------------------------- needs a look

function NeedsALook() {
  const q = useQuery({ queryKey: ["book-review"], queryFn: () => api.get<Brief[]>("/api/admin/books/review"), refetchInterval: 15_000 });
  const [picking, setPicking] = useState<Brief | null>(null);
  if (!q.data) return null;
  return (
    <section className="panel">
      <div className="panel-head">
        <div>
          <div className="kicker">Needs a look · {q.data.length}</div>
          <div className="h3">Books filed without a source sure of them</div>
        </div>
      </div>
      {q.data.length ? (
        <div className="list">
          {q.data.map((b) => (
            <div key={b.id} className="list-row bk-row">
              <Art src={b.art} name={b.title} size={96} />
              <div className="grow">
                <Link className="ellipsis bk-title" to={`/audiobooks/${b.id}`}>{b.title}</Link>
                <div className="dim ellipsis">{[b.author, b.narrator && `read by ${b.narrator}`, b.duration ? fmtLong(b.duration) : null].filter(Boolean).join(" · ")}</div>
                <div className="faint mono-path ellipsis" data-tip={b.path}>{b.path}</div>
              </div>
              <div className="row-actions">
                <button className="btn small accent" onClick={() => setPicking(b)}><Search size={14} /> Pick the right book</button>
                <button className="btn small" data-tip="It's right as it was filed: off the list"
                        onClick={() => act(() => api.post(`/api/admin/books/${b.id}/ok`), `${b.title}: off the list`)}>
                  <Check size={14} /> Looks right
                </button>
              </div>
            </div>
          ))}
        </div>
      ) : <Empty title="Nothing to look at">Every book was known to Audible, Bonnier Audio, Apple Books or the Warhammer wiki.</Empty>}
      {picking && <PickBook b={picking} onClose={() => setPicking(null)} />}
    </section>
  );
}

function hitSeries(h: Hit) {
  const [name, n] = h.series[0] || ["", ""];
  return name ? (n ? `Book ${n} of ${name}` : name) : "";
}

const LINK = /^(https?:\/\/|www\.)/i;
const SHOWN = 4;

/** Every source's books for a search (the book's own title and author to begin with), or the one a link is: the one
 * it is retags, renames and moves it where that puts it. Each source answers on its own, the quick ones first. */
function PickBook({ b, onClose }: { b: Brief; onClose: () => void }) {
  const [q, setQ] = useState(b.title);
  const [author, setAuthor] = useState(b.author.split(",")[0] || "");
  const [ask, setAsk] = useState({ q: b.title, author: b.author.split(",")[0] || "" });
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const [saving, setSaving] = useState("");
  const list = useQuery({
    queryKey: ["book-sources"], staleTime: Infinity,
    // a server from before Bonnier Audio et al. has Audible only
    queryFn: () => api.get<Source[]>("/api/admin/books/sources").catch(() => [{ id: "audible", name: "Audible" }]),
  });
  const srcs = list.data || [];
  const link = LINK.test(ask.q.trim());
  const results = useQueries({
    queries: srcs.map((s) => ({
      queryKey: ["book-lookup", s.id, ask], enabled: !!ask.q.trim(), retry: false, staleTime: 5 * 60_000,
      queryFn: () => api.get<Hit[]>("/api/admin/books/lookup", { ...ask, source: s.id }),
    })),
  });
  const pick = async (h: Hit) => {
    setSaving(`${h.source}:${h.id}`);
    try {
      const got = await api.post<Brief>(`/api/admin/books/${b.id}/match`, { source: h.source, id: h.id });
      useUi.getState().notify(`${got.title}: retagged and filed`);
      refresh();
      queryClient.invalidateQueries({ queryKey: ["book", b.id] });
      onClose();
    } catch (e) {
      useUi.getState().notify((e as Error).message, "error");
    } finally {
      setSaving("");
    }
  };
  const nowhere = link && results.length > 0 && results.every((r) => r.isSuccess && !r.data.length);
  return (
    <Modal onClose={onClose} className="pick-book">
      <div className="kicker">Pick the right book</div>
      <div className="h3 ellipsis" style={{ margin: "4px 0 2px" }}>{b.title}</div>
      <div className="dim" style={{ marginBottom: 14 }}>
        Now {[b.author, b.duration ? fmtLong(b.duration) : null].filter(Boolean).join(" · ")}. The one you pick gives it its names,
        cover and tags, and moves it where those put it.
      </div>
      <form className="row-actions pick-search" onSubmit={(e) => { e.preventDefault(); setOpen({}); setAsk({ q, author }); }}>
        <input className="input" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Title, or a link to the book"
               aria-label="Title, or a link to the book on Audible, Bonnier Audio, Apple Books or the Warhammer wiki" />
        <input className="input" value={author} onChange={(e) => setAuthor(e.target.value)} placeholder="Author" aria-label="Author"
               disabled={LINK.test(q.trim())} />
        <button className="btn" type="submit"><Search size={14} /> Search</button>
      </form>
      <div className="pick-hits">
        {nowhere && <div className="dim pick-note">None of {srcs.map((s) => s.name).join(", ")} knows that link.</div>}
        {srcs.map((s, i) => {
          const r = results[i];
          if (!r || (link && r.isSuccess && !r.data.length)) return null;      // a link to another source's book
          const hits = r.data || [];
          const shown = open[s.id] ? hits : hits.slice(0, SHOWN);
          return (
            <section key={s.id} className="pick-source" aria-busy={r.isFetching}>
              <div className="kicker pick-source-head">{s.name}{r.isSuccess && !r.isFetching && ` · ${hits.length}`}</div>
              {r.isFetching ? <div className="dim pick-note">Asking {s.name}…</div>
                : r.isError ? <div className="error-text pick-note">{(r.error as Error).message}</div>
                : !hits.length ? <div className="faint pick-note">Nothing for that here. Fewer words may find it.</div>
                : (
                  <div className="list">
                    {shown.map((h) => <HitRow key={h.id} h={h} b={b} saving={saving} onPick={pick} />)}
                    {hits.length > shown.length && (
                      <button className="btn small ghost pick-more" onClick={() => setOpen({ ...open, [s.id]: true })}>
                        {hits.length - shown.length} more from {s.name}
                      </button>
                    )}
                  </div>
                )}
            </section>
          );
        })}
      </div>
    </Modal>
  );
}

function HitRow({ h, b, saving, onPick }: { h: Hit; b: Brief; saving: string; onPick: (h: Hit) => void }) {
  const near = b.duration && h.runtime ? Math.abs(h.runtime - b.duration) / b.duration < 0.03 : false;
  const key = `${h.source}:${h.id}`;
  return (
    <div className="list-row bk-row pick-hit">
      {h.image ? <img className="pick-cover" src={h.image} alt="" loading="lazy" /> : <span className="pick-cover" />}
      <div className="grow">
        <div className="bk-title ellipsis">{h.title}{h.subtitle && <span className="dim"> · {h.subtitle}</span>}</div>
        <div className="dim ellipsis">{h.authors.join(", ")}{h.narrators.length > 0 && ` · read by ${h.narrators.join(", ")}`}</div>
        <div className="faint ellipsis">
          {[hitSeries(h), h.year || h.release.slice(0, 4), h.runtime ? fmtLong(h.runtime) : null, h.language && languageName(h.language)].filter(Boolean).join(" · ")}
          {near && <span className="pick-near"> · as long as this one</span>}
        </div>
      </div>
      {h.url && (
        <a className="btn small ghost pick-link" href={h.url} target="_blank" rel="noreferrer" data-tip="Its page" aria-label={`${h.title}: its page`}>
          <ExternalLink size={14} />
        </a>
      )}
      <button className="btn small accent" disabled={!!saving} onClick={() => onPick(h)}>{saving === key ? "Filing…" : "This one"}</button>
    </div>
  );
}

// ---------------------------------------------------------------- duplicates

function Duplicates() {
  const q = useQuery({ queryKey: ["book-dupes"], queryFn: () => api.get<Dupe[]>("/api/admin/books/duplicates"), refetchInterval: 15_000 });
  if (!q.data?.length) return null;
  const how = (d: Dupe, h: "keep" | "replace" | "delete", done: string) =>
    act(() => api.post("/api/admin/books/duplicates", { name: d.name, how: h }), done);
  return (
    <section className="panel">
      <div className="panel-head">
        <div>
          <div className="kicker">Audiobooks/_Duplicates · {q.data.length}</div>
          <div className="h3">Books the library seems to have already</div>
        </div>
      </div>
      <div className="list">
        {q.data.map((d) => (
          <div key={d.name} className="list-row bk-dupe">
            <div className="grow">
              <div className="bk-title ellipsis">{d.title}</div>
              <div className="dim ellipsis">
                {[d.authors.join(", "), d.narrators.length ? `read by ${d.narrators.join(", ")}` : null, d.seconds ? fmtLong(d.seconds) : null,
                  fmtBytes(d.size)].filter(Boolean).join(" · ")}
              </div>
              {d.library ? (
                <div className="faint ellipsis">
                  The library's: <Link to={`/audiobooks/${d.library.id}`}>{d.library.title}</Link>
                  {[d.library.narrator && ` read by ${d.library.narrator}`, d.library.duration && fmtLong(d.library.duration)].filter(Boolean).join(" ·")}
                </div>
              ) : <div className="faint">The library's copy is gone: keep it to file it as a book.</div>}
            </div>
            <div className="row-actions">
              <button className="btn small" data-tip="Filed as a book of its own, beside the library's copy"
                      onClick={() => how(d, "keep", `${d.title}: filed beside the library's copy`)}><Copy size={14} /> Keep both</button>
              {d.library && (
                <button className="btn small" data-tip="Filed in the library copy's place (its place in it and its plays stay); the old one goes to _Duplicates"
                        onClick={() => how(d, "replace", `${d.title}: in the library copy's place`)}>Replace the library's</button>
              )}
              <button className="btn small danger" data-tip="Deleted from _Duplicates"
                      onClick={() => confirm(`Delete "${d.title}" from _Duplicates? It can't be undone.`) && how(d, "delete", `${d.title}: deleted`)}>
                <Trash2 size={14} /> Delete
              </button>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

// ---------------------------------------------------------------- latest imports

function LatestImports() {
  const q = useQuery({ queryKey: ["book-imports"], queryFn: () => api.get<BookImport[]>("/api/admin/books/imports"), refetchInterval: 5000 });
  if (!q.data?.length) return null;
  return (
    <section className="panel">
      <div className="panel-head"><div className="h3">Lately filed</div></div>
      <div className="list">
        {q.data.map((j) => {
          const busy = j.status === "queued" || j.status === "running";
          const source = j.watched ? `From the watch folder: ${j.watched}` : "Uploaded";
          return (
            <div key={j.id} className="list-row upload-batch">
              <div className="upload-head">
                <span className={`status-dot ${busy ? "queued" : j.status === "failed" || j.failed.length ? "bad" : "ok"}`} />
                <div className="grow">
                  <div className="upload-title">{source}{j.finished_at && !busy ? ` · ${ago(j.finished_at)}` : ""}</div>
                  <div className={j.status === "failed" ? "error-text" : "dim"} style={{ fontSize: 12.5 }}>
                    {busy ? j.message || "Being made and filed…" : j.status === "failed" ? j.message
                      : `${j.books.length} book${j.books.length === 1 ? "" : "s"} filed${j.failed.length ? `, ${j.failed.length} couldn't be made` : ""}`}
                  </div>
                </div>
                {busy && <div style={{ width: 160 }}><div className="progressbar"><div style={{ width: `${(j.progress || 0) * 100}%` }} /></div></div>}
              </div>
              {(j.books.length > 0 || j.failed.length > 0) && (
                <ul className="upload-contents">
                  {j.books.map((b, i) => (
                    <li key={i}>
                      <span className={`status-dot ${b.duplicate_of ? "" : b.sure ? "ok" : "queued"}`} />
                      <span className="grow ellipsis">
                        <b>{b.title}</b> <span className="dim">· {b.author}</span>
                        <span className="bk-imp-labels"><GenreLabel genre={b.genre} />{b.language && <span className="blabel lang">{languageName(b.language)}</span>}</span>
                        <span className="faint mono-path" data-tip="Where it was filed in the audiobook upload folder"> → {b.folder}</span>
                        {!b.sure && !b.duplicate_of && <span className="dim"> · needs a look</span>}
                        {b.duplicate_of && <span className="dim"> · set aside as a duplicate</span>}
                      </span>
                    </li>
                  ))}
                  {j.failed.map((f, i) => (
                    <li key={`f${i}`}><span className="status-dot bad" /><span className="grow ellipsis"><b>{f.title}</b>
                      <span className="error-text"> · couldn't be made: {f.error}</span></span></li>
                  ))}
                </ul>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}
