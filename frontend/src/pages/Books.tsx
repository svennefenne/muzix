/** Audiobooks: the shelf (a series is one stack of covers, the filters are chips above it), the same books as a list,
 * a book's page (where it sits in its series, what comes next), a series' page and an author's. Every book says its
 * genre (a coloured label) and its language (an outlined one, in that language: "English", "Svenska"). */

import { useQuery } from "@tanstack/react-query";
import { ArrowRight, BookOpen, Check, Play, RotateCcw, Search, X } from "lucide-react";
import { useMemo, useState, type CSSProperties } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api, ago, fmtLong, fmtNumber, fmtTime } from "../api";
import { queryClient } from "../actions";
import { AdminCog, useAdminMode } from "../components/AdminMode";
import { DownloadButton } from "../components/DownloadButton";
import { DisplaySwitch, Rows, SortMenu, useBrowse, useStuck } from "../components/Browse";
import { GenreLabel, Labels, languageName } from "../components/BookLabels";
import { SleepButton } from "../components/SleepTimer";
import { Art, Display, Empty, FromPeer, Kicker, Loading, Section } from "../components/ui";
import { rowTap } from "../components/TrackList";
import { engine } from "../player/engine";
import { fromBook, usePlayer } from "../store/player";
import type { Book, BookFacets, DisplayMode, Paged } from "../types";

const BOOK_SORTS: [string, string][] = [
  ["title", "Title"], ["author", "Author"], ["added", "Recently added"], ["listened", "Recently listened"], ["length", "Longest first"],
];

const STATUSES: [string, string][] = [["all", "All books"], ["new", "Not started"], ["listening", "Listening"], ["finished", "Finished"]];

// ---------------------------------------------------------------- labels

/** "Book 5 · The Stormlight Archive", or the author when it's in no series. */
function placeIn(b: Book) {
  if (!b.series) return b.author || "Unknown author";
  return b.series_part ? `Book ${b.series_part} · ${b.series}` : b.series;
}

const seriesLink = (series: string, author: string) =>
  `/audiobooks/series/${encodeURIComponent(series)}${author ? `?author=${encodeURIComponent(author)}` : ""}`;
const authorLink = (author: string) => `/audiobooks/author/${encodeURIComponent(author)}`;

function progressText(b: Book) {
  if (b.finished) return "Finished";
  return b.duration && b.position > 0 ? `${Math.round((b.position / b.duration) * 100)} %` : "";
}

/** Plays a book, from where it was left or from its start: the list has no parts, its page does. */
async function playBook(b: Book, fromStart = false) {
  const full = b.parts ? b : await queryClient.fetchQuery({ queryKey: ["book", b.id], queryFn: () => api.get<Book>(`/api/books/${b.id}`) });
  engine.play(fromBook(full, fromStart || full.finished ? 0 : full.position));
}

// ---------------------------------------------------------------- cards

function BookCard({ b, sub }: { b: Book; sub?: string }) {
  const pct = b.duration ? Math.min(100, (b.position / b.duration) * 100) : 0;
  return (
    <Link to={`/audiobooks/${b.id}`} className="card bcard">
      <Art src={b.art} name={b.title} peer={b.peer} />
      <AdminCog kind="book" id={b.id} title={b.title} peer={b.peer} />
      {pct > 0 && !b.finished && <div className="progressbar bcard-progress"><div style={{ width: `${pct}%` }} /></div>}
      <div className="card-title ellipsis">{b.title}</div>
      <div className="card-sub ellipsis">{b.finished ? "Finished · " : ""}{sub ?? placeIn(b)}</div>
      <Labels b={b} />
    </Link>
  );
}

interface Stack { key: string; series: string; author: string; books: Book[] }

function Covers({ books, size = 300, big }: { books: Book[]; size?: number; big?: boolean }) {
  const top = books.slice(0, 3);
  return (
    <div className={`bstack ${big ? "big" : ""}`} aria-hidden>
      {top.map((b, i) => (
        <div key={b.id} className="bstack-cover" style={{ "--i": i, zIndex: top.length - i } as CSSProperties}>
          <Art src={b.art} name={b.title} size={size} peer={b.peer} />
        </div>
      ))}
      {!big && <span className="bstack-count">{books.length} books</span>}
    </div>
  );
}

/** A series on the shelf: its covers fanned, how many, and how far you are in it. */
function StackCard({ s }: { s: Stack }) {
  const done = s.books.filter((b) => b.finished).length;
  return (
    <Link to={seriesLink(s.series, "")} className="card bcard" aria-label={`${s.series}, ${s.books.length} books`}>
      <Covers books={s.books} />
      <div className="card-title ellipsis">{s.series}</div>
      <div className="card-sub ellipsis">{done ? `${done} of ${s.books.length} finished · ` : ""}{s.author || "Unknown author"}</div>
      <Labels b={s.books[0]} />
    </Link>
  );
}

/** "Dan Abnett", or "Graham McNeill, Dan Abnett +4" for a series several wrote. */
function authorsOf(books: Book[]) {
  const all = [...new Set(books.map((b) => b.author).filter(Boolean))];
  return all.length > 2 ? `${all.slice(0, 2).join(", ")} +${all.length - 2}` : all.join(", ");
}

const byPart = (x: Book, y: Book) =>
  (parseFloat(x.series_part) || 1e9) - (parseFloat(y.series_part) || 1e9) || x.title.localeCompare(y.title);

/** The books on the shelf: a series with two or more of them here is one stack, where its first book would be (one
 * stack whoever wrote them: The Horus Heresy has many authors). */
function shelve(items: Book[], sort: string): (Book | Stack)[] {
  const key = (b: Book) => b.series;
  const groups = new Map<string, Book[]>();
  for (const b of items) if (b.series) groups.set(key(b), [...(groups.get(key(b)) || []), b]);
  const out: (Book | Stack)[] = [];
  const seen = new Set<string>();
  for (const b of items) {
    const g = b.series ? groups.get(key(b))! : [];
    if (g.length < 2) out.push(b);
    else if (!seen.has(key(b))) {
      seen.add(key(b));
      out.push({ key: key(b), series: b.series, author: authorsOf(g), books: [...g].sort(byPart) });
    }
  }
  if (sort === "title") {     // a stack goes by its series' name, as it's shown
    const name = (e: Book | Stack) => ("books" in e ? e.series : e.title).replace(/^(the|a|an) /i, "");
    out.sort((x, y) => name(x).localeCompare(name(y), undefined, { numeric: true, sensitivity: "base" }));
  }
  return out;
}

function BookRows({ items }: { items: Book[] }) {
  return (
    <Rows cols="48px minmax(0, 2.2fr) minmax(0, 1.2fr) minmax(170px, 1fr) 92px 84px" colsSm="44px minmax(0, 1fr) 64px"
          head={["", "Title", "Author", "Genre · language", "Length", "Progress"].map((h, i) =>
            <span key={i} className={i >= 2 && i <= 4 ? "l-opt" : i === 5 ? "l-num" : ""}>{h}</span>)}>
      {items.map((b) => (
        <Link key={b.id} to={`/audiobooks/${b.id}`} className="lrow">
          <div className="l-thumb"><Art src={b.art} name={b.title} size={96} peer={b.peer} /></div>
          <div className="l-main">
            <div className="l-title ellipsis">{b.title}</div>
            <div className="l-sub ellipsis">{placeIn(b)}</div>
            <div className="l-sm"><Labels b={b} /></div>
          </div>
          <span className="l-col ellipsis l-opt">{b.author}</span>
          <span className="l-col l-opt"><Labels b={b} /></span>
          <span className="l-col l-opt mono-num">{b.duration ? fmtLong(b.duration) : ""}</span>
          <span className="l-num">{progressText(b)}</span>
          <AdminCog kind="book" id={b.id} title={b.title} peer={b.peer} />
        </Link>
      ))}
    </Rows>
  );
}

function Shelf({ items, display, sort }: { items: Book[]; display: DisplayMode; sort: string }) {
  const entries = useMemo(() => shelve(items, sort), [items, sort]);
  if (display === "list") return <BookRows items={items} />;
  return (
    <div className={`grid bshelf ${display === "grid" ? "compact" : ""}`}>
      {entries.map((e) => ("books" in e ? <StackCard key={e.key} s={e} /> : <BookCard key={e.id} b={e} />))}
    </div>
  );
}

// ---------------------------------------------------------------- continue listening

function ContinueCard({ b }: { b: Book }) {
  const pct = b.duration ? Math.min(100, (b.position / b.duration) * 100) : 0;
  return (
    <div className="bcont">
      <Link to={`/audiobooks/${b.id}`} className="bcont-link">
        <Art src={b.art} name={b.title} size={160} peer={b.peer} />
        <div className="bcont-text">
          <div className="bcont-title ellipsis">{b.title}</div>
          <div className="bcont-sub ellipsis">{placeIn(b)}</div>
          <div className="progressbar"><div style={{ width: `${pct}%` }} /></div>
          <div className="bcont-left">{fmtLong(Math.max(0, b.duration - b.position))} left</div>
        </div>
      </Link>
      <button className="bcont-play" aria-label={`Resume ${b.title}`} data-tip="Resume" onClick={() => playBook(b)}>
        <Play size={16} fill="currentColor" />
      </button>
    </div>
  );
}

// ---------------------------------------------------------------- the page

function Chips({ label, all, items, value, onChange }: {
  label: string; all: number; items: { value: string; name: string; count: number; genre?: boolean }[];
  value: string | null; onChange: (v: string | null) => void;
}) {
  return (
    <div className="bfilter-row" role="radiogroup" aria-label={label}>
      <span className="seg-label bfilter-label">{label}</span>
      <div className="bchips">
        <button role="radio" aria-checked={value === null} className={`bchip ${value === null ? "on" : ""}`} onClick={() => onChange(null)}>
          All <b>{fmtNumber(all)}</b>
        </button>
        {items.map((it) => (
          <button key={it.value} role="radio" aria-checked={value === it.value} className={`bchip ${value === it.value ? "on" : ""}`}
                  data-genre={it.genre ? it.name : undefined} onClick={() => onChange(value === it.value ? null : it.value)}>
            {it.genre && <i className="bchip-dot" aria-hidden />}{it.name} <b>{fmtNumber(it.count)}</b>
          </button>
        ))}
      </div>
    </div>
  );
}

export default function Books() {
  const [params, setParams] = useSearchParams();
  const genre = params.get("genre");
  const language = params.get("language");
  const status = params.get("status") || "all";
  const [q, setQ] = useState("");
  const b = useBrowse("books", BOOK_SORTS, "title");
  const set = (k: string, v: string | null) => {
    const p = new URLSearchParams(params);
    if (v === null || (k === "status" && v === "all")) p.delete(k);
    else p.set(k, v);
    setParams(p, { replace: true });
  };
  const facets = useQuery({ queryKey: ["books", "facets"], queryFn: () => api.get<BookFacets>("/api/books/facets") });
  const listening = useQuery({ queryKey: ["books", "listening"], queryFn: () => api.get<Paged<Book>>("/api/books", { status: "listening", limit: 20 }) });
  const filters: Record<string, string> = { q, sort: b.sort, status };
  if (genre !== null) filters.genre = genre;
  if (language !== null) filters.language = language;
  const all = useQuery({ queryKey: ["books", filters], queryFn: () => api.get<Paged<Book>>("/api/books", { ...filters, limit: 1000 }) });
  const total = (facets.data?.genres || []).reduce((n, g) => n + g.count, 0);
  const filtered = genre !== null || language !== null || status !== "all" || !!q;
  const stuck = useStuck();
  return (
    <div className="page wide">
      <Kicker parts={["Audiobooks", total ? `${fmtNumber(total)} books` : null]} />
      <Display l1="Story" l2="time" />
      {listening.data && listening.data.items.length > 0 && (
        <Section kicker="Pick up where you left off" title="Continue listening">
          <div className="bconts">{listening.data.items.map((x) => <ContinueCard key={x.id} b={x} />)}</div>
        </Section>
      )}
      {/* the filters stay at the top of the frame as the shelf scrolls under them */}
      <div ref={stuck.edge} aria-hidden />
      <div className={`browse-sticky bfilters ${stuck.on ? "stuck" : ""}`}>
        {facets.data && facets.data.genres.length > 0 && (
          <Chips label="Genre" all={total} value={genre} onChange={(v) => set("genre", v)}
                 items={facets.data.genres.map((g) => ({ value: g.value || "Uncategorized", name: g.name, count: g.count, genre: true }))} />
        )}
        {facets.data && facets.data.languages.length > 0 && (
          <Chips label="Language" all={total} value={language} onChange={(v) => set("language", v)}
                 items={facets.data.languages.map((l) => ({ value: l.code, name: l.code ? languageName(l.code) : l.name, count: l.count }))} />
        )}
        <div className="toolbar browsebar bfilter-tools">
          <label className="bsearch">
            <Search size={15} aria-hidden />
            <input className="input" placeholder="Search titles, authors, series" value={q} onChange={(e) => setQ(e.target.value)}
                   aria-label="Search the audiobooks" />
            {q && <button className="bsearch-clear" aria-label="Clear the search" onClick={() => setQ("")}><X size={14} /></button>}
          </label>
          <label className="sortmenu">
            <span className="seg-label">Status</span>
            <select className="select" value={status} onChange={(e) => set("status", e.target.value)}>
              {STATUSES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </label>
          <SortMenu value={b.sort} options={BOOK_SORTS} onChange={b.setSort} />
          <div className="grow" />
          {all.data && filtered && <span className="faint bfilter-count">{fmtNumber(all.data.total)} of {fmtNumber(total)}</span>}
          <DisplaySwitch value={b.display} onChange={b.setDisplay} />
        </div>
      </div>
      {all.data ? (all.data.items.length ? <Shelf items={all.data.items} display={b.display} sort={b.sort} />
        : filtered ? <Empty title="No books like that">Try another genre or language, or clear the search.</Empty>
          : <Empty title="No audiobooks">Upload some on the admin page, or add a folder of audiobooks there.</Empty>) : <Loading />}
    </div>
  );
}

// ---------------------------------------------------------------- a series, an author

function useBooks(key: string, params: Record<string, string>) {
  return useQuery({ queryKey: ["books", key, params], queryFn: () => api.get<Paged<Book>>("/api/books", { ...params, limit: 1000 }) });
}

/** The book to carry on with: the one you're in, else the first you haven't finished. */
function upNext(books: Book[]) {
  return books.find((b) => b.position > 0 && !b.finished) || books.find((b) => !b.finished) || null;
}

export function SeriesPage() {
  const { name = "" } = useParams();
  const [params] = useSearchParams();
  const author = params.get("author") || "";
  const q = useBooks("series", { series: name, ...(author ? { author } : {}) });
  if (!q.data) return <div className="page"><Loading /></div>;
  const books = q.data.items;
  if (!books.length) return <div className="page"><Empty title="No such series" /></div>;
  const next = upNext(books);
  const done = books.filter((b) => b.finished).length;
  const length = books.reduce((n, b) => n + b.duration, 0);
  return (
    <div className="page">
      <div className="detail-head">
        <Covers books={books} size={600} big />
        <div>
          <Kicker parts={["Series", `${books.length} books`]} />
          <Display l1={name} small />
          <div className="detail-meta">
            {author ? <Link to={authorLink(author)}><b>{author}</b></Link>
              : [...new Set(books.map((b) => b.author))].length === 1 ? <Link to={authorLink(books[0].author)}><b>{books[0].author}</b></Link>
              : <b>{authorsOf(books)}</b>}
            <span className="dotsep">{fmtLong(length)}</span>
            {done > 0 && <span className="dotsep">{done} of {books.length} finished</span>}
          </div>
          <Labels b={books[0]} big />
          <div className="row-actions" style={{ marginTop: 18 }}>
            {next && (
              <button className="btn accent" onClick={() => playBook(next)}>
                <Play size={15} fill="currentColor" /> {next.position > 0 ? "Resume" : "Play"}{next.series_part ? ` book ${next.series_part}` : ""}
              </button>
            )}
            {next !== books[0] && (
              <button className="btn" onClick={() => playBook(books[0], true)}><RotateCcw size={15} /> From book {books[0].series_part || 1}</button>
            )}
          </div>
        </div>
      </div>
      <div className="bseries">
        {books.map((b) => (
          <Link key={b.id} to={`/audiobooks/${b.id}`} className={`bseries-row ${b === next ? "next" : ""}`}>
            <span className="bseries-n">{b.series_part || "·"}</span>
            <Art src={b.art} name={b.title} size={160} peer={b.peer} />
            <div className="bseries-main">
              <div className="l-title ellipsis">{b.title}</div>
              <div className="l-sub ellipsis">{[author || b.author === books[0].author && books.every((x) => x.author === b.author) ? null : b.author,
                b.year || null, b.narrator && `Read by ${b.narrator}`].filter(Boolean).join(" · ")}</div>
              {b.position > 0 && !b.finished && <div className="progressbar"><div style={{ width: `${(b.position / (b.duration || 1)) * 100}%` }} /></div>}
            </div>
            <span className="l-opt mono-num faint">{fmtLong(b.duration)}</span>
            <span className="l-num">{b.finished ? <Check size={16} aria-label="Finished" /> : progressText(b)}</span>
            <AdminCog kind="book" id={b.id} title={b.title} peer={b.peer} />
          </Link>
        ))}
      </div>
    </div>
  );
}

export function AuthorPage() {
  const { name = "" } = useParams();
  const q = useBooks("author", { author: name, sort: "series" });
  if (!q.data) return <div className="page"><Loading /></div>;
  const books = q.data.items;
  if (!books.length) return <div className="page"><Empty title="No books by them here" /></div>;
  const series = new Map<string, Book[]>();
  const alone: Book[] = [];
  for (const b of books) {
    if (b.series) series.set(b.series, [...(series.get(b.series) || []), b]);
    else alone.push(b);
  }
  const genres = [...new Set(books.map((b) => b.genre))];
  return (
    <div className="page wide">
      <Kicker parts={["Author", `${books.length} books`, series.size ? `${series.size} series` : null]} />
      <Display l1={name} small />
      <div className="blabels big bauthor-genres">{genres.map((g) => <GenreLabel key={g || "-"} genre={g} />)}</div>
      {[...series].map(([s, list]) => (
        <Section key={s} kicker={`${list.length} book${list.length > 1 ? "s" : ""}`} title={s}
                 more={<Link className="more" to={seriesLink(s, name)}>The series <ArrowRight size={14} /></Link>}>
          <div className="grid bshelf">{list.map((b) => <BookCard key={b.id} b={b} sub={b.series_part ? `Book ${b.series_part}` : String(b.year || "")} />)}</div>
        </Section>
      ))}
      {alone.length > 0 && (
        <Section title={series.size ? "Other books" : "Books"}>
          <div className="grid bshelf">{alone.map((b) => <BookCard key={b.id} b={b} sub={String(b.year || "")} />)}</div>
        </Section>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- a book

const CHAPTERS_SHOWN = 24;

export function BookPage() {
  const { id } = useParams();
  const q = useQuery({ queryKey: ["book", Number(id)], queryFn: () => api.get<Book>(`/api/books/${id}`) });
  const cur = usePlayer((s) => (s.index >= 0 ? s.queue[s.index] : null));
  const pos = usePlayer((s) => s.position);
  const admin = useAdminMode();
  const [allChapters, setAllChapters] = useState(false);
  if (!q.data) return <div className="page"><Loading /></div>;
  const b = q.data;
  const playingThis = cur?.kind === "book" && cur.bookId === b.id;
  const bookPos = playingThis ? (cur!.partOffset || 0) + pos : b.position;
  const chapters = b.chapters || [];
  const chapterIdx = chapters.reduce((acc, c, i) => (c.start <= bookPos + 0.5 ? i : acc), 0);
  const start = (at: number) => engine.play(fromBook(b, at));
  const mark = async (finished: boolean) => {
    await api.put(`/api/books/${b.id}/progress`, { position: finished ? b.duration : 0, finished });
    queryClient.invalidateQueries({ queryKey: ["book", b.id] });
    queryClient.invalidateQueries({ queryKey: ["books"] });
  };
  const inSeries = b.in_series || [];
  const latest = inSeries.length > 1 && inSeries[inSeries.length - 1].id === b.id;
  const shown = allChapters || chapters.length <= CHAPTERS_SHOWN + 6 ? chapters : chapters.slice(0, Math.max(CHAPTERS_SHOWN, chapterIdx + 3));
  return (
    <div className="page wide bpage">
      <div className="detail-head">
        <Art src={b.art} name={b.title} size={600} peer={b.peer} />
        <div>
          {b.series ? (
            <Link className="kicker bseries-link" to={seriesLink(b.series, "")}>
              {b.series_part ? `Book ${b.series_part} of ${b.series}` : b.series} <ArrowRight size={12} aria-hidden />
            </Link>
          ) : <Kicker parts={["Audiobook"]} />}
          <Display l1={b.title} small />
          <div className="detail-meta">
            {b.author ? <Link to={authorLink(b.author)}><b>{b.author}</b></Link> : <b>Unknown author</b>}
            {b.narrator && <span className="dotsep">Read by {b.narrator}</span>}
            {b.updated_at && <span className="dotsep">Last listened {ago(b.updated_at)}</span>}
            {b.peer && <FromPeer peer={b.peer} />}
          </div>
          <Labels b={b} big>
            {b.year > 0 && <span className="blabel plain">{b.year}</span>}
            <span className="blabel plain">{fmtLong(b.duration)}</span>
            {chapters.length > 1 && <span className="blabel plain">{chapters.length} chapters</span>}
            {admin && b.review && <Link className="blabel review" to="/admin/upload">Needs a look</Link>}
          </Labels>
          <div className="progressbar bpage-progress"><div style={{ width: `${b.duration ? (bookPos / b.duration) * 100 : 0}%` }} /></div>
          <div className="faint mono bpage-at">
            {fmtTime(bookPos)} of {fmtTime(b.duration)}
            {b.finished ? " · finished" : chapters.length > 1 && bookPos > 0 ? ` · ${chapters[chapterIdx]?.title}` : ""}
          </div>
          <div className="row-actions">
            <button className="btn accent" onClick={() => start(b.finished ? 0 : bookPos)}>
              <Play size={15} fill="currentColor" /> {bookPos > 5 && !b.finished ? "Resume" : "Play"}
            </button>
            {bookPos > 5 && <button className="btn" onClick={() => start(0)}><RotateCcw size={15} /> From the start</button>}
            <button className="btn" onClick={() => mark(!b.finished)}><Check size={15} /> {b.finished ? "Mark unfinished" : "Mark finished"}</button>
            {playingThis && <SleepButton className="btn" size={15} label />}
            <DownloadButton id={`book:${b.id}`} title={b.title} make={() => ({
              id: `book:${b.id}`, kind: "book", title: b.title, subtitle: b.author, art: b.art, path: `/audiobooks/${b.id}`,
              pages: { [`/api/books/${b.id}`]: b }, items: fromBook(b, 0) })} />
            <AdminCog kind="book" id={b.id} title={b.title} className="inline" peer={b.peer} />
          </div>
        </div>
      </div>
      <div className={`bpage-body ${inSeries.length > 1 ? "with-side" : ""}`}>
        <div className="bpage-main">
          {b.description && (
            <Section title="About">
              <p className="lede bpage-about">{b.description}</p>
            </Section>
          )}
          <Section kicker={`${chapters.length} chapters`} title="Chapters">
            {chapters.length ? (
              <div className="tracks">
                {shown.map((c, i) => {
                  const end = chapters[i + 1]?.start ?? b.duration;
                  return (
                    <div key={i} className={`trow no-album ${i === chapterIdx && bookPos > 0 ? "playing" : ""}`}
                         onDoubleClick={() => start(c.start)} onClick={rowTap(() => start(c.start))}>
                      <div className="t-num"><span className="n">{i + 1}</span>
                        <button className="p" aria-label={`Play ${c.title}`} onClick={() => start(c.start)}><Play size={15} fill="currentColor" /></button></div>
                      <div className="t-main"><div className="t-title ellipsis">{c.title}</div></div>
                      <div className="t-dur">{fmtTime(end - c.start)}</div>
                      <div className="t-dur faint">{fmtTime(c.start)}</div>
                    </div>
                  );
                })}
                {shown.length < chapters.length && (
                  <button className="btn bpage-more" onClick={() => setAllChapters(true)}>All {chapters.length} chapters</button>
                )}
              </div>
            ) : <Empty title="No chapters"><BookOpen size={16} /></Empty>}
          </Section>
        </div>
        {inSeries.length > 1 && (
          <aside className="bside" aria-label="The series">
            <div className="kicker">Next in the series</div>
            {b.next ? <SideBook b={b.next} /> : <p className="faint bside-note">{latest ? "This is the latest one here." : "No later book here."}</p>}
            <div className="kicker bside-h">In this series · {inSeries.length}</div>
            <div className="bside-list">
              {inSeries.map((x) => <SideBook key={x.id} b={x} current={x.id === b.id} />)}
            </div>
            <Link className="more bside-all" to={seriesLink(b.series, "")}>The series <ArrowRight size={14} /></Link>
          </aside>
        )}
      </div>
    </div>
  );
}

function SideBook({ b, current }: { b: Book; current?: boolean }) {
  const sub = [b.series_part && `Book ${b.series_part}`, b.year || null, b.finished ? "finished" : b.position > 0 ? progressText(b) : null];
  return (
    <Link to={`/audiobooks/${b.id}`} className={`bside-book ${current ? "current" : ""}`} aria-current={current ? "page" : undefined}>
      <Art src={b.art} name={b.title} size={96} peer={b.peer} />
      <div className="bside-text">
        <div className="ellipsis bside-title">{b.title}</div>
        <div className="ellipsis faint">{sub.filter(Boolean).join(" · ")}</div>
      </div>
    </Link>
  );
}
