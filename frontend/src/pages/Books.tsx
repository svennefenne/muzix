import { useQuery } from "@tanstack/react-query";
import { BookOpen, Check, Play, RotateCcw } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, ago, fmtLong, fmtNumber, fmtTime } from "../api";
import { queryClient } from "../actions";
import { Art, Display, Empty, Kicker, Loading, Section } from "../components/ui";
import { engine } from "../player/engine";
import { fromBook, usePlayer } from "../store/player";
import type { Book, Paged } from "../types";

function BookCard({ b }: { b: Book }) {
  const pct = b.duration ? Math.min(100, (b.position / b.duration) * 100) : 0;
  return (
    <Link to={`/audiobooks/${b.id}`} className="card">
      <Art src={b.art} name={b.title} />
      {pct > 0 && !b.finished && <div className="progressbar" style={{ marginTop: 8 }}><div style={{ width: `${pct}%` }} /></div>}
      <div className="card-title ellipsis">{b.title}</div>
      <div className="card-sub ellipsis">{b.finished ? "Finished · " : ""}{b.author || "Unknown author"}</div>
    </Link>
  );
}

export default function Books() {
  const [q, setQ] = useState("");
  const [sort, setSort] = useState("title");
  const listening = useQuery({ queryKey: ["books", "listening"], queryFn: () => api.get<Paged<Book>>("/api/books", { status: "listening", limit: 20 }) });
  const all = useQuery({ queryKey: ["books", q, sort], queryFn: () => api.get<Paged<Book>>("/api/books", { q, sort, limit: 1000 }) });
  return (
    <div className="page wide">
      <Kicker parts={["Audiobooks", all.data && `${fmtNumber(all.data.total)} books`]} />
      <Display l1="Story" l2="time" />
      {listening.data && listening.data.items.length > 0 && (
        <Section kicker="Pick up where you left off" title="Continue listening">
          <div className="scroller">{listening.data.items.map((b) => <BookCard key={b.id} b={b} />)}</div>
        </Section>
      )}
      <Section title="All books">
        <div className="toolbar">
          <input className="input" style={{ maxWidth: 340 }} placeholder="Search titles, authors, series" value={q} onChange={(e) => setQ(e.target.value)} />
          <select className="select" style={{ width: 160 }} value={sort} onChange={(e) => setSort(e.target.value)}>
            <option value="title">Title</option>
            <option value="author">Author</option>
            <option value="added">Recently added</option>
          </select>
        </div>
        {all.data ? (all.data.items.length ? <div className="grid">{all.data.items.map((b) => <BookCard key={b.id} b={b} />)}</div>
          : <Empty title="No audiobooks">Add a folder of audiobooks as an "audiobooks" folder on the admin page.</Empty>) : <Loading />}
      </Section>
    </div>
  );
}

export function BookPage() {
  const { id } = useParams();
  const q = useQuery({ queryKey: ["book", Number(id)], queryFn: () => api.get<Book>(`/api/books/${id}`) });
  const cur = usePlayer((s) => (s.index >= 0 ? s.queue[s.index] : null));
  const pos = usePlayer((s) => s.position);
  if (!q.data) return <div className="page"><Loading /></div>;
  const b = q.data;
  const playingThis = cur?.kind === "book" && cur.bookId === b.id;
  const bookPos = playingThis ? (cur!.partOffset || 0) + pos : b.position;
  const chapterIdx = (b.chapters || []).reduce((acc, c, i) => (c.start <= bookPos + 0.5 ? i : acc), 0);
  const start = (at: number) => engine.play(fromBook(b, at));
  const mark = async (finished: boolean) => {
    await api.put(`/api/books/${b.id}/progress`, { position: finished ? b.duration : 0, finished });
    queryClient.invalidateQueries({ queryKey: ["book", b.id] });
    queryClient.invalidateQueries({ queryKey: ["books"] });
  };
  return (
    <div className="page">
      <div className="detail-head">
        <Art src={b.art} name={b.title} size={600} />
        <div>
          <Kicker parts={["Audiobook", b.series, b.year || null]} />
          <Display l1={b.title} small />
          <div className="detail-meta">
            <b>{b.author || "Unknown author"}</b>
            {b.narrator && <span className="dotsep">Read by {b.narrator}</span>}
            <span className="dotsep">{fmtLong(b.duration)}</span>
            {b.updated_at && <span className="dotsep">Last listened {ago(b.updated_at)}</span>}
          </div>
          <div className="progressbar" style={{ maxWidth: 420, margin: "4px 0 6px" }}><div style={{ width: `${b.duration ? (bookPos / b.duration) * 100 : 0}%` }} /></div>
          <div className="faint mono" style={{ fontSize: 12, marginBottom: 16 }}>{fmtTime(bookPos)} of {fmtTime(b.duration)}{b.finished ? " · finished" : ""}</div>
          <div className="row-actions">
            <button className="btn accent" onClick={() => start(b.finished ? 0 : bookPos)}>
              <Play size={15} fill="currentColor" /> {bookPos > 5 && !b.finished ? "Resume" : "Play"}
            </button>
            <button className="btn" onClick={() => start(0)}><RotateCcw size={15} /> From the start</button>
            <button className="btn" onClick={() => mark(!b.finished)}><Check size={15} /> {b.finished ? "Mark unfinished" : "Mark finished"}</button>
          </div>
        </div>
      </div>
      {b.description && <p className="lede">{b.description}</p>}
      <Section kicker={`${b.chapters?.length || 0} chapters`} title="Chapters">
        {(b.chapters || []).length ? (
          <div className="tracks">
            {(b.chapters || []).map((c, i) => {
              const end = (b.chapters || [])[i + 1]?.start ?? b.duration;
              return (
                <div key={i} className={`trow no-album ${i === chapterIdx && playingThis ? "playing" : ""}`} onDoubleClick={() => start(c.start)}>
                  <div className="t-num"><span className="n">{i + 1}</span>
                    <button className="p" aria-label={`Play ${c.title}`} onClick={() => start(c.start)}><Play size={15} fill="currentColor" /></button></div>
                  <div className="t-main"><div className="t-title ellipsis">{c.title}</div></div>
                  <div className="t-dur">{fmtTime(end - c.start)}</div>
                  <div className="t-dur faint">{fmtTime(c.start)}</div>
                </div>
              );
            })}
          </div>
        ) : <Empty title="No chapters"><BookOpen size={16} /></Empty>}
      </Section>
    </div>
  );
}
