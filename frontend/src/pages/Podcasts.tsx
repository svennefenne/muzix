import { useQuery } from "@tanstack/react-query";
import { Check, CircleCheck, Download, ListChecks, MoreHorizontal, Pause, Play, Plus, RefreshCw, Rss, Upload } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ago, api, fmtLong, fmtTime } from "../api";
import { podcastsChanged, queryClient } from "../actions";
import { AdminCog } from "../components/AdminMode";
import { DownloadButton } from "../components/DownloadButton";
import { Segmented } from "../components/Browse";
import { Art, Display, Empty, Kicker, Loading, Modal, NewDot, Section, Switch, useMenu } from "../components/ui";
import { appPlayer, useShell } from "../player/app";
import { engine } from "../player/engine";
import { fromEpisode, usePlayer, useStartedEpisodes } from "../store/player";
import { useUi } from "../store/ui";
import type { Episode, EpisodeDetail, Feed, PodcastHit } from "../types";

/** Everything under an episode on its podcast's page (the ones out before it) marked finished, with an undo. */
async function finishOlder(e: Episode) {
  const notify = useUi.getState().notify;
  const r = await api.post<{ marked: number; before: unknown[] }>(`/api/podcasts/episodes/${e.id}/finish-older`);
  podcastsChanged();
  if (!r.marked) return notify("The older episodes are already finished");
  notify(`Marked ${r.marked} older episode${r.marked === 1 ? "" : "s"} as finished`, "info", {
    label: "Undo",
    run: () => void api.post("/api/podcasts/episodes/restore", { episodes: r.before }).then(podcastsChanged),
  });
}

/** Where an episode is: as the player has it while it's the one playing, otherwise as last saved. */
function useEpisodeAt(e: Episode) {
  const key = `episode:${e.id}`;
  const here = usePlayer((s) => s.current()?.key === key);
  const playing = usePlayer((s) => s.current()?.key === key && (s.playing || s.buffering));
  const position = usePlayer((s) => (s.current()?.key === key ? s.position : e.position));
  const pct = e.duration ? Math.min(100, (position / e.duration) * 100) : 0;
  return { here, playing, position, pct };
}

function EpisodeRow({ e, feed }: { e: Episode; feed?: Feed }) {
  const notify = useUi((s) => s.notify);
  const showMenu = useMenu((s) => s.show);
  const { here, playing, position, pct } = useEpisodeAt(e);
  const started = useStartedEpisodes().has(e.id);
  const play = () => engine.play([fromEpisode(e, feed?.title, feed?.image)]);
  const menu = (ev: { clientX: number; clientY: number }) => showMenu(ev, [
    ...(e.finished ? [{ label: "Play again", icon: <Play size={16} />, onClick: play }] : []),
    {
      label: e.finished ? "Mark as unplayed" : "Mark as played", icon: <CircleCheck size={16} />,
      onClick: () => void api.put(`/api/podcasts/episodes/${e.id}/progress`, { position: e.finished ? 0 : e.duration, finished: !e.finished })
        .then(podcastsChanged),
    },
    ...(e.published ? [{ label: "Mark older as finished", icon: <ListChecks size={16} />, onClick: () => void finishOlder(e) }] : []),
  ]);
  const kicker = (
    <div className="kicker" style={{ fontSize: 10 }}>
      {e.new && !started && <NewDot label="New episode" />}
      {[e.feed_title, e.published && ago(e.published), e.duration ? fmtTime(e.duration) : null].filter(Boolean).join(" · ")}
    </div>
  );
  // the title's link covers the whole row: a click anywhere but the buttons opens the episode
  const title = <Link className={`ep-open ${e.finished ? "ellipsis" : ""}`} to={`/podcasts/episode/${e.id}`}>{e.title}</Link>;
  const actions = (
    <div className="row-actions">
      {e.finished && <span className="badge accent"><Check size={11} /> Played</span>}
      {e.downloaded ? <span className="badge" data-tip="Downloaded to the server">Saved</span> : (
        <button className="mini" data-tip="Download the episode to the server" aria-label="Download" onClick={async () => {
          await api.post(`/api/podcasts/episodes/${e.id}/download`);
          notify("Downloading in the background");
        }}><Download size={15} /></button>
      )}
      <button className="mini" aria-label={`More options for ${e.title}`}
              data-tip={e.finished ? "More: play again, mark as unplayed, mark older as finished" : "More: mark as played, mark older as finished"}
              onClick={menu}>
        <MoreHorizontal size={15} />
      </button>
    </div>
  );
  const context = (ev: React.MouseEvent) => {
    ev.preventDefault();
    menu(ev);
  };
  // played: a slim row with just what tells it apart; the description is for the ones still to hear
  if (e.finished && !here) {
    return <div className="list-row ep-row done" onContextMenu={context}><div className="grow">{kicker}{title}</div>{actions}</div>;
  }
  return (
    <div className={`list-row ep-row ${here ? "on" : ""}`} style={{ alignItems: "flex-start" }} onContextMenu={context}>
      {/* the one in the player pauses and goes on from here */}
      <button className={`btn round ${here ? "accent" : ""}`} style={{ width: 42, height: 42 }}
              aria-label={`${playing ? "Pause" : here ? "Continue" : "Play"} ${e.title}`} onClick={here ? () => engine.toggle() : play}>
        {playing ? <Pause size={16} fill="currentColor" /> : <Play size={16} fill="currentColor" />}
      </button>
      <div className="grow">
        {kicker}
        {title}
        <div className="dim" style={{ fontSize: 13, display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" }}>{e.description}</div>
        {(pct > 0 || here) && (
          <div className="ep-progress">
            <div className="progressbar"><div style={{ width: `${pct}%` }} /></div>
            {e.duration > 0 && <span>{fmtLong(Math.max(60, e.duration - position))} left</span>}
          </div>
        )}
      </div>
      {actions}
    </div>
  );
}

/** A started episode in Continue listening, small: its show, its title and time left, how far, and play or pause. */
function ContinueCard({ e }: { e: Episode }) {
  const { here, playing, position, pct } = useEpisodeAt(e);
  return (
    <div className={`list-row ep-row ep-card ${here ? "on" : ""}`}>
      <button className={`btn round ${here ? "accent" : ""}`} aria-label={`${playing ? "Pause" : "Continue"} ${e.title}`}
              onClick={here ? () => engine.toggle() : () => engine.play([fromEpisode(e)])}>
        {playing ? <Pause size={14} fill="currentColor" /> : <Play size={14} fill="currentColor" />}
      </button>
      <div className="grow">
        <div className="kicker ellipsis">{e.feed_title}</div>
        {/* the time left over the bar's end; a long title is cut short before it */}
        <div className="ep-card-title">
          <Link className="ep-open ellipsis" to={`/podcasts/episode/${e.id}`}>{e.title}</Link>
          {e.duration > 0 && <span>{fmtLong(Math.max(60, e.duration - position))} left</span>}
        </div>
        <div className="progressbar"><div style={{ width: `${pct}%` }} /></div>
      </div>
    </div>
  );
}

export default function Podcasts() {
  const nav = useNavigate();
  const notify = useUi((s) => s.notify);
  const subs = useQuery({ queryKey: ["podcasts"], queryFn: () => api.get<Feed[]>("/api/podcasts") });
  const latest = useQuery({ queryKey: ["podcasts-latest"], queryFn: () => api.get<Episode[]>("/api/podcasts/latest") });
  // fetched on each visit: what was heard elsewhere (the app, another device) since
  const resume = useQuery({ queryKey: ["podcasts-continue"], queryFn: () => api.get<Episode[]>("/api/podcasts/continue", { limit: 6 }), staleTime: 0 });
  // browsing: a category, and one of its subcategories, national or international (remembered on the device)
  const [genre, setGenre] = useState<Category | null>(null);
  const [sub, setSub] = useState<string | null>(null);
  const genres = useQuery({ queryKey: ["podcast-genres"], queryFn: () => api.get<Category[]>("/api/podcasts/genres"), staleTime: 3600_000 });
  const scope = useUi((s) => s.browse["podcasts-browse"]?.scope) ?? "national";
  const asked = sub ?? (genre ? String(genre.id) : "");
  const browsed = useQuery({
    queryKey: ["podcasts-browse", asked, scope], staleTime: 3600_000,
    queryFn: () => api.get<Browsed>("/api/podcasts/browse", { genre: asked, scope }),
  });
  const admin = useUi((s) => !!s.user?.is_admin);
  const inApp = useShell((s) => s.opens);     // the apps have no admin pages: the server's, in the browser
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
    setHits(await api.get<PodcastHit[]>("/api/podcasts/search", { q: term, scope }));
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

      {resume.data && resume.data.length > 0 && (
        <Section title="Continue listening">
          <div className="ep-cards">{resume.data.map((e) => <ContinueCard key={e.id} e={e} />)}</div>
        </Section>
      )}

      <Section title="Your podcasts">
        {subs.data ? (subs.data.length ? (
          <div className="grid">
            {subs.data.map((f) => (
              <Link key={f.id} to={`/podcasts/${f.id}`} className="card">
                <div className="art-dot">
                  <Art src={f.image} name={f.title} />
                  {f.new && <NewDot label="New episodes" />}
                </div>
                <AdminCog kind="podcast" id={f.id} title={f.title} />
                <div className="card-title ellipsis">{f.title}</div>
                <div className="card-sub ellipsis">{f.unplayed ? `${f.unplayed} unplayed` : f.author}</div>
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

      <Section kicker="Charts" title="Browse"
               more={<Segmented label="Where" value={scope} options={[...SCOPES]}
                                onChange={(v) => setBrowse("podcasts-browse", { scope: v })} />}>
        <div className="subnav swipe" role="toolbar" aria-label="Categories">
          <button className={genre === null ? "active" : ""} aria-pressed={genre === null}
                  onClick={() => { setGenre(null); setSub(null); }}>Top</button>
          {(genres.data || []).map((g) => (
            <button key={g.id} className={genre?.id === g.id ? "active" : ""} aria-pressed={genre?.id === g.id}
                    onClick={() => { setGenre(g); setSub(null); }}>{g.name}</button>
          ))}
        </div>
        {/* a category's subcategories, to dig further */}
        {genre && genre.subs?.length > 0 && (
          <div className="subnav swipe subcats" role="toolbar" aria-label={`${genre.name}: subcategories`}>
            <button className={sub === null ? "active" : ""} aria-pressed={sub === null} onClick={() => setSub(null)}>All {genre.name}</button>
            {genre.subs.map((s) => (
              <button key={s.id} className={sub === String(s.id) ? "active" : ""} aria-pressed={sub === String(s.id)}
                      onClick={() => setSub(String(s.id))}>{s.name}</button>
            ))}
          </div>
        )}
        {browsed.isLoading ? <Loading /> : browsed.data?.sections.some((s) => s.items.length) ? (
          browsed.data.sections.filter((s) => s.items.length).map((s) => (
            <div key={s.source} className="browse-source">
              <h3 className="h3">{sourceTitle(s.source, browsed.data)}</h3>
              <HitGrid list={s.items} />
            </div>
          ))
        ) : <Empty title="Nothing in this chart right now" />}
        {admin && browsed.data && browsed.data.missing.length > 0 && (
          <p className="dim browse-more">
            More lists from {browsed.data.missing.map((m) => SOURCES[m]).join(" and ")}: their keys go under
            {" "}{inApp
              ? <a href="/admin/settings" onClick={(e) => { e.preventDefault(); appPlayer.openOnServer("/admin/settings"); }}>Admin → Settings</a>
              : <Link to="/admin/settings">Admin → Settings</Link>}, Podcasts &amp; radio.
          </p>
        )}
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

interface Category { id: number; name: string; subs: { id: number | string; name: string }[] }
interface Browsed {
  country: string;          // two letters
  languages: string;        // Podcast Index's, the first
  sections: { source: "apple" | "podcastindex" | "listennotes"; items: PodcastHit[] }[];
  missing: string[];        // the sources without a key yet
}

const SCOPES = [{ value: "national", label: "National" }, { value: "international", label: "International" }] as const;
const SOURCES: Record<string, string> = { apple: "Apple Podcasts", podcastindex: "Podcast Index", listennotes: "Listen Notes" };

/** "Apple Podcasts · Sweden", "Trending on Podcast Index · Swedish", "Best on Listen Notes · Sweden". */
function sourceTitle(source: string, b: Browsed) {
  const name = (type: "region" | "language", code: string) => {
    try {
      return new Intl.DisplayNames(["en"], { type }).of(type === "region" ? code.toUpperCase() : code) || code;
    } catch {
      return code;
    }
  };
  if (source === "podcastindex") return `Trending on Podcast Index · ${name("language", b.languages)}`;
  if (source === "listennotes") return `Best on Listen Notes · ${name("region", b.country)}`;
  return `Apple Podcasts · ${name("region", b.country)}`;
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
                <label className="row-actions dim" style={{ gap: 8 }}
                       data-tip={`When an episode ends, the next unplayed one below it in the list plays: ${order === "oldest" ? "a newer one, as the list goes oldest first" : "an older one, as the list goes newest first"}. With none left below it, the nearest one above it plays.`}>
                  <Switch checked={f.autoplay} onChange={async (v) => {
                    await api.put(`/api/podcasts/${f.id}/subscription`, { autoplay: v });
                    await q.refetch();
                    engine.podcastAutoplay(f.id, v);
                  }} />
                  Autoplay
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

export function EpisodePage() {
  const { eid } = useParams();
  const q = useQuery({ queryKey: ["episode", Number(eid)], queryFn: () => api.get<EpisodeDetail>(`/api/podcasts/episodes/${eid}`) });
  if (q.isError) return <div className="page"><Empty title="No such episode" /></div>;
  if (!q.data) return <div className="page"><Loading /></div>;
  return <EpisodeView e={q.data} />;
}

function EpisodeView({ e }: { e: EpisodeDetail }) {
  const notify = useUi((s) => s.notify);
  const { here, playing, position, pct } = useEpisodeAt(e);
  const finished = e.finished && !here;   // played again: it shows where it is
  const f = e.feed;
  const play = () => (here ? engine.toggle() : engine.play([fromEpisode(e, f.title, f.image)]));
  // a timestamp in the notes: there, in this episode
  const playAt = (t: number) => (here ? engine.seek(t, true) : engine.play([{ ...fromEpisode(e, f.title, f.image), resume: t }]));
  const when = e.published && new Date(e.published).toLocaleDateString(undefined, { day: "numeric", month: "long", year: "numeric" });
  return (
    <div className="page">
      <div className="detail-head ep-head">
        <Art src={e.image || f.image} name={f.title} size={600} />
        <div>
          <Kicker parts={["Podcast episode"]} />
          <Display l1={e.title} small />
          <div className="detail-meta">
            <Link to={`/podcasts/${f.id}`}><b>{f.title}</b></Link>
            {when && <span className="dotsep">{when}</span>}
            {e.duration > 0 && <span className="dotsep">{fmtLong(e.duration)}</span>}
            {finished ? <span className="dotsep">Played</span>
              : pct > 0 ? <span className="dotsep">{fmtLong(Math.max(60, e.duration - position))} left</span>
              : e.new && <span className="dotsep"><NewDot label="New episode" />New</span>}
          </div>
          {pct > 0 && !finished && <div className="progressbar" style={{ maxWidth: 320, marginBottom: 18 }}><div style={{ width: `${pct}%` }} /></div>}
          <div className="row-actions">
            <button className="btn accent" onClick={play}>
              {here && playing ? <><Pause size={15} fill="currentColor" /> Pause</>
                : <><Play size={15} fill="currentColor" /> {here ? "Continue" : e.finished ? "Play again" : pct > 0 ? "Resume" : "Play"}</>}
            </button>
            <DownloadButton id={`episode:${e.id}`} title={e.title} make={() => {
              const it = fromEpisode(e, f.title, f.image);
              return { id: `episode:${e.id}`, kind: "episode", title: e.title, subtitle: f.title, art: it.art, path: `/podcasts/episode/${e.id}`,
                       pages: { [`/api/podcasts/episodes/${e.id}`]: e }, items: [it] };
            }} />
            {e.downloaded ? <span className="badge" data-tip="Downloaded to the server">Saved</span> : (
              <button className="btn" onClick={async () => {
                await api.post(`/api/podcasts/episodes/${e.id}/download`);
                notify("Downloading in the background");
              }}><Download size={15} /> Download</button>
            )}
            <button className="btn ghost" onClick={async () => {
              await api.put(`/api/podcasts/episodes/${e.id}/progress`, { position: e.finished ? 0 : e.duration, finished: !e.finished });
              podcastsChanged();
            }}><CircleCheck size={15} /> {e.finished ? "Mark as unplayed" : "Mark as played"}</button>
          </div>
        </div>
      </div>
      <Section title="Episode description">
        {e.notes ? (
          // the server rebuilds the notes from a short list of safe tags, attributes and links
          <div className="show-notes" dangerouslySetInnerHTML={{ __html: e.notes }} onClick={(ev) => {
            const ts = (ev.target as HTMLElement).closest<HTMLElement>("button.ts");
            if (ts) playAt(Number(ts.dataset.t));
          }} />
        ) : <p className="dim">This episode has no description.</p>}
        <Link className="btn" style={{ marginTop: 24 }} to={`/podcasts/${f.id}`}>See all episodes</Link>
      </Section>
    </div>
  );
}
