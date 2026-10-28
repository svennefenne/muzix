import { useQuery } from "@tanstack/react-query";
import { Check, Download, Play, Plus, RefreshCw, Rss, Upload } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ago, api, fmtTime } from "../api";
import { queryClient } from "../actions";
import { AdminCog } from "../components/AdminMode";
import { Segmented } from "../components/Browse";
import { Art, Display, Empty, Kicker, Loading, Modal, NewDot, Section, Switch } from "../components/ui";
import { engine } from "../player/engine";
import { fromEpisode, usePlayer } from "../store/player";
import { useUi } from "../store/ui";
import type { Episode, Feed, PodcastHit } from "../types";

function EpisodeRow({ e, feed }: { e: Episode; feed?: Feed }) {
  const notify = useUi((s) => s.notify);
  const pct = e.duration ? Math.min(100, (e.position / e.duration) * 100) : 0;
  // started here: its dot goes now rather than when the list is next fetched
  const started = usePlayer((s) => s.queue.slice(0, s.index + 1).some((q) => q.key === `episode:${e.id}`));
  return (
    <div className="list-row" style={{ alignItems: "flex-start" }}>
      <button className="btn round" style={{ width: 42, height: 42 }} aria-label={`Play ${e.title}`}
              onClick={() => engine.play([fromEpisode(e, feed?.title, feed?.image)])}>
        <Play size={16} fill="currentColor" />
      </button>
      <div className="grow">
        <div className="kicker" style={{ fontSize: 10 }}>
          {e.new && !started && <NewDot label="New episode" />}
          {[e.feed_title, e.published && ago(e.published), e.duration ? fmtTime(e.duration) : null].filter(Boolean).join(" · ")}
        </div>
        <div style={{ fontWeight: 700 }}>{e.title}</div>
        <div className="dim" style={{ fontSize: 13, display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" }}>{e.description}</div>
        {pct > 0 && !e.finished && <div className="progressbar" style={{ marginTop: 8, maxWidth: 260 }}><div style={{ width: `${pct}%` }} /></div>}
      </div>
      <div className="row-actions">
        {e.finished && <span className="badge accent"><Check size={11} /> Played</span>}
        {e.downloaded ? <span className="badge">Saved</span> : (
          <button className="mini" title="Download" aria-label="Download" onClick={async () => {
            await api.post(`/api/podcasts/episodes/${e.id}/download`);
            notify("Downloading in the background");
          }}><Download size={15} /></button>
        )}
      </div>
    </div>
  );
}

export default function Podcasts() {
  const nav = useNavigate();
  const notify = useUi((s) => s.notify);
  const subs = useQuery({ queryKey: ["podcasts"], queryFn: () => api.get<Feed[]>("/api/podcasts") });
  const latest = useQuery({ queryKey: ["podcasts-latest"], queryFn: () => api.get<Episode[]>("/api/podcasts/latest") });
  const [genre, setGenre] = useState<number | null>(null);
  const genres = useQuery({ queryKey: ["podcast-genres"], queryFn: () => api.get<{ id: number; name: string }[]>("/api/podcasts/genres"), staleTime: Infinity });
  const top = useQuery({
    queryKey: ["podcasts-top", genre], staleTime: 3600_000,
    queryFn: () => api.get<PodcastHit[]>("/api/podcasts/top", genre ? { genre } : {}),
  });
  const [term, setTerm] = useState("");
  const [hits, setHits] = useState<PodcastHit[] | null>(null);
  const [adding, setAdding] = useState(false);
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState("");
  const opml = useRef<HTMLInputElement>(null);
  const latestOpen = !useUi((s) => s.browse["podcasts-latest"]?.collapsed);
  const setBrowse = useUi((s) => s.setBrowse);

  const subscribe = async (feedUrl: string) => {
    setBusy(feedUrl);
    try {
      const r = await api.post<{ id: number }>("/api/podcasts", { url: feedUrl });
      queryClient.invalidateQueries({ queryKey: ["podcasts"] });
      queryClient.invalidateQueries({ queryKey: ["podcasts-latest"] });
      nav(`/podcasts/${r.id}`);
    } catch (e) {
      notify((e as Error).message, "error");
    } finally {
      setBusy("");
    }
  };
  // a podcast's page without subscribing, to look and listen first
  const open = async (feedUrl: string) => {
    setBusy(feedUrl);
    try {
      const r = await api.post<{ id: number }>("/api/podcasts/open", { url: feedUrl });
      nav(`/podcasts/${r.id}`);
    } catch (e) {
      notify((e as Error).message, "error");
    } finally {
      setBusy("");
    }
  };
  const search = async () => {
    if (!term.trim()) return;
    setHits(null);
    setHits(await api.get<PodcastHit[]>("/api/podcasts/search", { q: term }));
  };
  const importOpml = async (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    const r = await api.post<{ subscribed: number; failed: unknown[] }>("/api/podcasts/opml/import", fd);
    notify(`Subscribed to ${r.subscribed} podcasts${r.failed.length ? `, ${r.failed.length} failed` : ""}`);
    queryClient.invalidateQueries({ queryKey: ["podcasts"] });
  };

  const HitGrid = ({ list }: { list: PodcastHit[] }) => (
    <div className="grid">
      {list.map((h) => (
        <div key={h.url} className="card" role="link" tabIndex={0} style={{ cursor: "pointer" }} aria-busy={busy === h.url}
             onClick={() => open(h.url)} onKeyDown={(e) => e.key === "Enter" && open(h.url)}>
          <Art src={h.image} name={h.title} />
          <div className="card-title ellipsis">{h.title}</div>
          <div className="card-sub ellipsis">{busy === h.url ? "Opening…" : h.author}</div>
          <button className="btn small" style={{ marginTop: 8 }} disabled={busy === h.url}
                  onClick={(e) => { e.stopPropagation(); subscribe(h.url); }}>
            <Plus size={13} /> Subscribe
          </button>
        </div>
      ))}
    </div>
  );

  return (
    <div className="page wide">
      <Kicker parts={["Podcasts", subs.data && `${subs.data.length} subscriptions`]} />
      <Display l1="On" l2="demand" />
      <div className="toolbar">
        <input className="input" style={{ maxWidth: 380 }} placeholder="Find a podcast" value={term}
               onChange={(e) => setTerm(e.target.value)} onKeyDown={(e) => e.key === "Enter" && search()} />
        <button className="btn" onClick={search}>Search</button>
        <div className="grow" />
        <button className="btn" onClick={() => setAdding(true)}><Rss size={15} /> Add by URL</button>
        <button className="btn" onClick={async () => { await api.post("/api/podcasts/refresh"); notify("Checking feeds for new episodes"); }}><RefreshCw size={15} /> Refresh</button>
        <button className="btn ghost" onClick={() => opml.current?.click()}><Upload size={15} /> Import OPML</button>
        <a className="btn ghost" href="/api/podcasts/opml/export">Export OPML</a>
        <input ref={opml} type="file" accept=".opml,.xml" hidden onChange={(e) => e.target.files?.[0] && importOpml(e.target.files[0])} />
      </div>

      {hits && <Section kicker="Search results" title={`"${term}"`}>{hits.length ? <HitGrid list={hits} /> : <Empty title="No podcasts found" />}</Section>}

      <Section title="Your podcasts">
        {subs.data ? (subs.data.length ? (
          <div className="grid">
            {subs.data.map((f) => (
              <Link key={f.id} to={`/podcasts/${f.id}`} className="card">
                <Art src={f.image} name={f.title} />
                <AdminCog kind="podcast" id={f.id} title={f.title} />
                <div className="card-title ellipsis">{f.title}</div>
                <div className="card-sub ellipsis">
                  {f.new && <NewDot label="New episodes" />}{f.unplayed ? `${f.unplayed} unplayed` : f.author}
                </div>
              </Link>
            ))}
          </div>
        ) : <Empty title="No subscriptions yet">Search above, pick from the charts below or add a feed URL.</Empty>) : <Loading />}
      </Section>

      {latest.data && latest.data.length > 0 && (
        <Section kicker="Fresh episodes" title="Latest" open={latestOpen}
                 onToggle={() => setBrowse("podcasts-latest", { collapsed: latestOpen })}>
          <div className="list">{latest.data.slice(0, 12).map((e) => <EpisodeRow key={e.id} e={e} />)}</div>
        </Section>
      )}

      <Section kicker="Charts" title="Browse">
        <div className="subnav swipe" role="toolbar" aria-label="Categories">
          <button className={genre === null ? "active" : ""} aria-pressed={genre === null} onClick={() => setGenre(null)}>Top</button>
          {(genres.data || []).map((g) => (
            <button key={g.id} className={genre === g.id ? "active" : ""} aria-pressed={genre === g.id} onClick={() => setGenre(g.id)}>{g.name}</button>
          ))}
        </div>
        {top.isLoading ? <Loading /> : top.data?.length ? <HitGrid list={top.data} /> : <Empty title="Nothing in this chart right now" />}
      </Section>

      {adding && (
        <Modal onClose={() => setAdding(false)}>
          <div className="h2" style={{ marginBottom: 14 }}>Add a feed</div>
          <input className="input" autoFocus placeholder="https://example.com/feed.xml" value={url} onChange={(e) => setUrl(e.target.value)}
                 onKeyDown={(e) => e.key === "Enter" && subscribe(url)} />
          <div className="row-actions" style={{ marginTop: 16, justifyContent: "flex-end" }}>
            <button className="btn accent" disabled={!url || !!busy} onClick={() => subscribe(url)}>{busy ? "Reading feed…" : "Subscribe"}</button>
          </div>
        </Modal>
      )}
    </div>
  );
}

const ORDERS = [{ value: "newest", label: "Newest" }, { value: "oldest", label: "Oldest" }] as const;
const PAGE = 200;

export function PodcastPage() {
  const { id } = useParams();
  const nav = useNavigate();
  // the order and "hide finished" are remembered per podcast: a serial is heard from the start, news from the top
  const pref = useUi((s) => s.browse[`podcast:${id}`]);
  const setBrowse = useUi((s) => s.setBrowse);
  const order = pref?.sort === "oldest" ? "oldest" : "newest";
  const hideFinished = !!pref?.hide_finished;
  const [limit, setLimit] = useState(PAGE);
  useEffect(() => setLimit(PAGE), [id, order, hideFinished]);
  const q = useQuery({
    queryKey: ["podcast", Number(id), order, hideFinished, limit], placeholderData: (before) => before,
    queryFn: () => api.get<Feed>(`/api/podcasts/${id}`, { order, hide_finished: hideFinished, limit }),
  });
  const subscribed = !!q.data?.subscribed;
  // opening the page is seeing what's new: the podcast's dot goes from the library
  useEffect(() => {
    if (!subscribed) return;
    api.post(`/api/podcasts/${id}/seen`).then(() => {
      for (const key of ["sidebar", "podcasts"]) queryClient.invalidateQueries({ queryKey: [key] });
    }).catch(() => {});
  }, [id, subscribed]);
  if (!q.data) return <div className="page"><Loading /></div>;
  const f = q.data;
  const eps = f.episodes || [];
  const next = eps.find((e) => !e.finished);
  const total = f.total ?? eps.length;
  const listed = hideFinished ? total - (f.finished || 0) : total;
  return (
    <div className="page">
      <div className="detail-head">
        <Art src={f.image} name={f.title} size={600} />
        <div>
          <Kicker parts={["Podcast", f.categories[0], `${total} episodes`]} />
          <Display l1={f.title} small />
          <div className="detail-meta"><b>{f.author}</b>{f.last_checked && <span className="dotsep">Checked {ago(f.last_checked)}</span>}</div>
          {f.error && <p className="error-text">Last refresh failed: {f.error}</p>}
          <div className="row-actions">
            {next && <button className="btn accent" onClick={() => engine.play([fromEpisode(next, f.title, f.image)])}><Play size={15} fill="currentColor" /> Play {order === "oldest" ? "oldest" : "latest"} unplayed</button>}
            <AdminCog kind="podcast" id={f.id} title={f.title} className="inline" />
            {f.subscribed ? (
              <>
                <label className="row-actions dim" style={{ gap: 8 }}>
                  <Switch checked={f.auto_download} onChange={async (v) => { await api.put(`/api/podcasts/${f.id}/subscription`, { auto_download: v }); q.refetch(); }} />
                  Download new episodes
                </label>
                <button className="btn danger" onClick={async () => {
                  await api.del(`/api/podcasts/${f.id}`);
                  queryClient.invalidateQueries({ queryKey: ["podcasts"] });
                  nav("/podcasts");
                }}>Unsubscribe</button>
              </>
            ) : (
              <button className="btn accent" onClick={async () => {
                await api.post("/api/podcasts", { url: f.url });
                q.refetch();
                for (const key of ["podcasts", "podcasts-latest", "sidebar"]) queryClient.invalidateQueries({ queryKey: [key] });
              }}>Subscribe</button>
            )}
          </div>
        </div>
      </div>
      {f.description && <p className="lede" style={{ maxWidth: 820 }}>{f.description}</p>}
      <div className="toolbar browsebar">
        <Segmented label="Sort" value={order} options={[...ORDERS]} onChange={(v) => setBrowse(`podcast:${id}`, { sort: v })} />
        <label className="row-actions dim" style={{ gap: 8 }}>
          <Switch checked={hideFinished} onChange={(v) => setBrowse(`podcast:${id}`, { hide_finished: v })} />
          Hide finished
        </label>
        {hideFinished && !!f.finished && <span className="faint" style={{ fontSize: 13 }}>{f.finished} finished hidden</span>}
      </div>
      {eps.length ? <div className="list">{eps.map((e) => <EpisodeRow key={e.id} e={e} feed={f} />)}</div>
        : <Empty title={hideFinished ? "You've finished every episode" : "No episodes yet"} />}
      {eps.length < listed && (
        <button className="btn" style={{ marginTop: 16 }} disabled={q.isFetching} onClick={() => setLimit(limit + PAGE)}>
          {q.isFetching ? "Loading…" : `Show more (${listed - eps.length} left)`}
        </button>
      )}
    </div>
  );
}
