/** The VGM page's online archives: HVSC, Modland, ASMA, the Joshw game rips, ZXArt, VGMRips,
 * The Mod Archive and scene.org, browsed folder by folder, searched and shuffled, and played
 * without adding anything to the library. */
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, Folder, Loader2, Play, Search, Shuffle } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api, fmtBytes, fmtTime } from "../api";
import { queryClient } from "../actions";
import { Display, Empty, Loading, Stripes } from "../components/ui";
import { engine } from "../player/engine";
import { fromOnline, usePlayer, type PlayItem } from "../store/player";
import { useUi } from "../store/ui";
import { SYSTEM_ACCENTS } from "../theme/skins";
import type { OnlineFile, OnlineListing, OnlineSearchResult, OnlineShuffleItem, OnlineSource, OnlineTrack } from "../types";

const SHOWN = 240;   // folders like Modland's Protracker hold thousands of composers

function useSources() {
  return useQuery({ queryKey: ["online-sources"], queryFn: () => api.get<OnlineSource[]>("/api/online/sources"), staleTime: Infinity });
}

function href(source: string, path = "") {
  return `/vgm/online/${source}${path ? "/" + path.split("/").map(encodeURIComponent).join("/") : ""}`;
}

function openFile(source: string, path: string) {
  return queryClient.fetchQuery({
    queryKey: ["online-open", source, path], staleTime: Infinity,
    queryFn: () => api.post<{ title: string; tracks: OnlineTrack[] }>("/api/online/open", { source, path }),
  });
}

/** A file's name as a title, and what Joshw-style names add: "Game (1988-12-24)(Capcom)[NES].7z"
 * → ["Game", "1988-12-24 · Capcom · NES"]. */
function splitName(name: string): [string, string] {
  const stem = name.replace(/\.[^.]+$/, "");
  const m = stem.match(/^(.+?)\s*((?:\([^)]*\)\s*)+(?:\[[^\]]*\]\s*)*)$/);
  const nice = (s: string) => (s.includes(" ") ? s : s.replace(/_/g, " "));
  if (!m) return [nice(stem), ""];
  const meta = (m[2].match(/[([][^)\]]*[)\]]/g) || []).map((x) => x.slice(1, -1).trim()).filter((x) => x && x !== "-");
  return [nice(m[1]), meta.join(" · ")];
}

/** What a file row shows: the archive's own title and author when it gives them. */
function fileLabel(f: OnlineFile): [string, string] {
  if (f.title) return [f.title, [f.songs ? `${f.songs} songs` : "", f.artist, f.year || ""].filter(Boolean).join(" · ")];
  return splitName(f.name);
}

/** A whole file, queued before it's downloaded: the server fetches it when it comes up. A game
 * set (a zip or 7z of songs) plays one of its songs, picked at random now and kept. */
function fileItem(source: string, f: OnlineFile, system: string): PlayItem {
  const member = f.kind === "archive" ? `*${Math.floor(Math.random() * 1e6)}` : "";
  const q = new URLSearchParams({ source, path: f.path, sub: "-1", ...(member && { member }) });
  return {
    key: `online:${source}:${f.path}|${member}|-1`, kind: "online", id: f.path, title: fileLabel(f)[0],
    artist: f.artist || "", duration: f.duration || 0, src: `/api/online/stream?${q}`, system, trackKind: f.chip ? "vgm" : "music", format: f.format,
  };
}

/** Plays random tunes from an archive, a folder of one, or every archive. */
function useShuffle() {
  const [busy, setBusy] = useState(false);
  const notify = useUi((s) => s.notify);
  async function shuffle(source = "", path = "") {
    setBusy(true);
    try {
      const r = await api.get<{ items: OnlineShuffleItem[] }>("/api/online/shuffle", { source: source || undefined, path: path || undefined, n: 80 });
      if (!r.items.length) return notify("Nothing to shuffle here", "error");
      engine.play(r.items.map((it) => fileItem(it.source, it, it.system)), 0);
    } catch (e) {
      notify((e as Error).message, "error");
    } finally {
      setBusy(false);
    }
  }
  return { busy, shuffle };
}

/** The search box: every archive's, or one archive's. */
function SearchBox({ source, label, initial = "" }: { source?: string; label?: string; initial?: string }) {
  const navigate = useNavigate();
  const [q, setQ] = useState(initial);
  useEffect(() => setQ(initial), [initial]);
  return (
    <form className="online-search" role="search" onSubmit={(e) => {
      e.preventDefault();
      if (q.trim()) navigate(`/vgm/online/search?${new URLSearchParams({ q: q.trim(), ...(source && { source }) })}`);
    }}>
      <Search size={16} />
      <input className="input" value={q} onChange={(e) => setQ(e.target.value)} enterKeyHint="search"
             placeholder={label ? `Search ${label}: title, artist, year…` : "Search every archive: title, artist, year, system…"}
             aria-label={label ? `Search ${label}` : "Search every archive"} />
    </form>
  );
}

function ShuffleAll({ source, path }: { source?: string; path?: string }) {
  const { busy, shuffle } = useShuffle();
  return (
    <button className="btn primary shuffle-all" disabled={busy} onClick={() => shuffle(source, path)} aria-label="Shuffle all">
      {busy ? <Loader2 size={15} className="spin" /> : <Shuffle size={15} />}<span> Shuffle all</span>
    </button>
  );
}

export function OnlineHome() {
  const sources = useSources();
  const navigate = useNavigate();
  return (
    <>
      <p className="lede vgm-intro">The big chiptune and tracker archives, played straight from the source. Muzix fetches a folder when you open it and a tune when you play it, and keeps recent tunes for a while.</p>
      <div className="online-head">
        <ShuffleAll />
        <SearchBox />
      </div>
      {sources.isLoading ? <Loading /> : (
        <div className="bento online-sources">
          {(sources.data || []).map((s) => (
            <div key={s.id} className="tile" role="link" tabIndex={0} aria-label={`${s.label}, from ${s.name}`}
                 style={{ "--tile-color": SYSTEM_ACCENTS[s.system]?.primary || "var(--primary)" } as React.CSSProperties}
                 onClick={() => navigate(href(s.id))} onKeyDown={(e) => e.key === "Enter" && navigate(href(s.id))}>
              <Stripes />
              <div className="tile-body">
                <div className="tile-kicker">{s.name}</div>
                <div className={`tile-title ${s.label.length > 14 ? "long" : ""}`}>{s.label}</div>
                <div className="tile-sub">{s.about}</div>
                {s.starts.length > 0 && (
                  <div className="online-starts">
                    {s.starts.map((st) => (
                      <Link key={st.path} className="chip" to={href(s.id, st.path)} onClick={(e) => e.stopPropagation()}>{st.name}</Link>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
      <p className="faint online-credit vgm-intro">The archives are run by volunteers: thank you, HVSC, Modland, ASMA, Joshw, ZXArt, VGMRips, The Mod Archive and scene.org.</p>
    </>
  );
}

export function OnlineBrowser() {
  const params = useParams();
  const source = params.source || "";
  const path = (params["*"] || "").replace(/\/+$/, "");
  const src = useSources().data?.find((s) => s.id === source);
  const list = useInfiniteQuery({
    queryKey: ["online-list", source, path], staleTime: 10 * 60_000, initialPageParam: 0,
    queryFn: ({ pageParam }) => api.get<OnlineListing>("/api/online/list", { source, path, page: pageParam || undefined }),
    getNextPageParam: (last, all) => (last.more ? all.length : undefined),
  });
  const pages = list.data?.pages;
  const d = useMemo(() => pages && { ...pages[0], files: pages.flatMap((p) => p.files) }, [pages]);
  const title = d?.crumbs.length ? d.name.replace(/_/g, " ") : src?.label || "";
  return (
    <>
      <nav className="crumbs" aria-label="You are here">
        <Link to="/vgm/online">Online</Link>
        <ChevronRight size={12} />
        {d?.crumbs.length ? <Link to={href(source)}>{src?.label || source}</Link> : <span>{src?.label || source}</span>}
        {d?.crumbs.map((c, i) => (
          <span key={c.path} className="crumb">
            <ChevronRight size={12} />
            {i === d.crumbs.length - 1 ? <span>{c.name}</span> : <Link to={href(source, c.path)}>{c.name}</Link>}
          </span>
        ))}
      </nav>
      <Display l1={title || " "} small />
      <div className="online-head">
        {(!path || !!d?.dirs.length) && <ShuffleAll source={source} path={path} />}
        <SearchBox source={source} label={src?.label} />
      </div>
      {list.isLoading ? <Loading /> : list.isError ? (
        <Empty title="Couldn't open this folder">{(list.error as Error).message}. <button className="btn small" onClick={() => list.refetch()}>Try again</button></Empty>
      ) : d && <FolderView key={`${source}/${path}`} d={d} source={source} system={src?.system || d.system}
                           more={list.hasNextPage ? { loading: list.isFetchingNextPage, load: () => list.fetchNextPage() } : undefined} />}
    </>
  );
}

function FolderView({ d, source, system, more, bare }: {
  d: OnlineListing; source: string; system: string;
  more?: { loading: boolean; load: () => void };       // the next page of a paged folder (VGMRips)
  bare?: boolean;                                       // search results: no filter box
}) {
  const [filter, setFilter] = useState("");
  const [shown, setShown] = useState(SHOWN);
  const [open, setOpen] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const notify = useUi((s) => s.notify);
  const playingKey = usePlayer((s) => (s.index >= 0 ? s.queue[s.index]?.key : "")) || "";
  const f = filter.trim().toLowerCase();
  const dirs = useMemo(() => d.dirs.filter((x) => !f || x.name.toLowerCase().includes(f)), [d, f]);
  const files = useMemo(() => d.files.filter((x) => !f || `${x.name} ${x.title || ""} ${x.artist || ""}`.toLowerCase().includes(f)), [d, f]);
  const tunes = files.filter((x) => x.kind === "tune");
  const letters = d.dirs.length > 0 && d.dirs.every((x) => x.name.length <= 3);
  // mostly letter folders (and a "zzz unlicensed" or two): a tighter grid on a phone
  const short = d.dirs.filter((x) => x.name.length <= 3).length >= d.dirs.length * 0.8;
  useEffect(() => setShown(SHOWN), [f]);

  async function play(file: OnlineFile) {
    setBusy(file.path);
    try {
      const o = await openFile(source, file.path);
      if (!o.tracks.length) return notify(`Nothing in ${file.name} plays here`, "error");
      // a single file is followed by the folder's other tunes, fetched as they come up
      const after = file.kind === "tune" ? tunes.slice(tunes.indexOf(file) + 1).map((x) => fileItem(source, x, system)) : [];
      engine.play([...o.tracks.map(fromOnline), ...after], 0);
      setOpen(o.tracks.length > 1 ? file.path : null);
    } catch (e) {
      notify((e as Error).message, "error");
    } finally {
      setBusy(null);
    }
  }

  function playFolder(shuffle: boolean) {
    const list = shuffle ? [...tunes].sort(() => Math.random() - 0.5) : tunes;
    engine.play(list.map((x) => fileItem(source, x, system)), 0);
  }

  const total = d.dirs.length + d.files.length;
  const all = d.total && d.total > d.files.length ? `${d.files.length.toLocaleString()} of ${d.total.toLocaleString()}` : total.toLocaleString();
  return (
    <>
      <div className="toolbar online-bar">
        {tunes.length > 0 && <>
          <button className="btn primary" onClick={() => playFolder(false)}><Play size={15} fill="currentColor" /> {bare ? "Play all" : "Play folder"}</button>
          <button className="btn" onClick={() => playFolder(true)}><Shuffle size={15} /> Shuffle</button>
        </>}
        {!bare && (total > 12 || more) && (
          <label className="online-filter">
            <Search size={15} />
            <input className="input" value={filter} onChange={(e) => setFilter(e.target.value)}
                   placeholder={`Filter ${all} ${d.files.length ? "items" : "folders"}`} aria-label="Filter this folder" />
          </label>
        )}
      </div>

      {letters && !f ? (
        <div className="online-letters">
          {d.dirs.map((x) => <Link key={x.path} to={href(source, x.path)}>{x.name}</Link>)}
        </div>
      ) : dirs.length > 0 && (
        <div className={`online-folders ${short ? "short" : ""}`}>
          {dirs.slice(0, shown).map((x) => (
            <Link key={x.path} to={href(source, x.path)} data-tip={x.name}>
              <Folder size={15} /><span className="ellipsis">{x.name.replace(/_/g, " ")}</span>
              {!!x.count && <span className="online-count">{x.count.toLocaleString()}</span>}
            </Link>
          ))}
        </div>
      )}
      {dirs.length > shown && (
        <button className="btn small online-more" onClick={() => setShown(shown + SHOWN * 2)}>
          Show more ({(dirs.length - shown).toLocaleString()} left)
        </button>
      )}

      {files.length > 0 && (
        <div className="online-files" role="list">
          {files.map((x, i) => {
            const mine = playingKey.startsWith(`online:${source}:${x.path}|`);
            const expanded = open === x.path;
            const [name, meta] = fileLabel(x);
            return (
              <div key={x.path} role="listitem">
                <div className={`online-file ${mine ? "playing" : ""}`} onClick={() => play(x)}>
                  <span className="online-n">
                    {busy === x.path ? <Loader2 size={15} className="spin" /> : <><span className="n">{i + 1}</span><Play size={14} fill="currentColor" className="p" /></>}
                  </span>
                  <span className="online-name" data-tip={x.name}>
                    <span className="ellipsis">{name}</span>
                    {meta && <span className="online-by ellipsis">{meta}</span>}
                  </span>
                  <span className="badge">{x.kind === "archive" ? "set" : x.format}</span>
                  <span className="online-size">{x.duration ? fmtTime(x.duration) : x.size ? fmtBytes(x.size) : ""}</span>
                  <button className="mini" aria-label={expanded ? "Hide the tunes" : "Show the tunes"} aria-expanded={expanded}
                          onClick={(e) => { e.stopPropagation(); setOpen(expanded ? null : x.path); }}>
                    {expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                  </button>
                </div>
                {expanded && <Tunes source={source} file={x} playingKey={playingKey} />}
              </div>
            );
          })}
        </div>
      )}
      {more && (
        <button className="btn small online-more-files" disabled={more.loading} onClick={more.load}>
          {more.loading && <Loader2 size={14} className="spin" />} Load more ({all} shown)
        </button>
      )}
      {total === 0 && <Empty title="Nothing here Muzix can play">{d.other ? `${d.other} files in other formats.` : "This folder is empty."}</Empty>}
      {d.other > 0 && total > 0 && <p className="faint online-other">{d.other.toLocaleString()} more {d.other === 1 ? "file" : "files"} here in formats Muzix doesn't play.</p>}
    </>
  );
}

/** Results for a search of every archive, or of one. */
export function OnlineSearch() {
  const [params] = useSearchParams();
  const q = params.get("q") || "";
  const source = params.get("source") || "";
  const src = useSources().data?.find((s) => s.id === source);
  const res = useQuery({
    queryKey: ["online-search", q, source], enabled: !!q, staleTime: 5 * 60_000,
    queryFn: () => api.get<OnlineSearchResult>("/api/online/search", { q, source: source || undefined }),
    // an archive's list is still being fetched: ask again until it's there
    refetchInterval: (query) => (query.state.data?.building.length ? 3000 : false),
  });
  const r = res.data;
  const found = r?.groups.reduce((n, g) => n + (g.total || g.files.length), 0) || 0;
  return (
    <>
      <nav className="crumbs" aria-label="You are here">
        <Link to="/vgm/online">Online</Link>
        {src && <><ChevronRight size={12} /><Link to={href(src.id)}>{src.label}</Link></>}
        <ChevronRight size={12} /><span>Search</span>
      </nav>
      <Display l1={q ? `“${q}”` : "Search"} small />
      <div className="online-head">
        <SearchBox source={source || undefined} label={src?.label} initial={q} />
        {source && <Link className="btn" to={`/vgm/online/search?${new URLSearchParams({ q })}`}>Search every archive</Link>}
      </div>
      {!q ? <Empty title="Search the archives">Titles, artists, composers, years and systems: “hubbard”, “mega man nes”, “1988 atari”.</Empty>
        : res.isLoading ? <Loading /> : res.isError ? <Empty title="Couldn't search">{(res.error as Error).message}</Empty> : r && (
        <>
          <p className="faint online-found">
            {found ? `${found.toLocaleString()} found in ${r.groups.length} ${r.groups.length === 1 ? "archive" : "archives"}` : "Nothing found"}
            {r.building.length > 0 && <> · <Loader2 size={12} className="spin" /> still fetching a list, more on the way</>}
          </p>
          {r.groups.map((g) => (
            <section key={g.source} className="online-group">
              <div className="online-group-head">
                <h3 className="h3">{g.label} <span className="faint">{g.archive}</span></h3>
                <span className="faint">{(g.total || 0) > g.files.length ? `first ${g.files.length} of ${(g.total || 0).toLocaleString()}` : `${(g.files.length + g.dirs.length).toLocaleString()} found`}</span>
                <Link className="btn small" to={href(g.source)}>Browse</Link>
              </div>
              <FolderView key={`${q}/${g.source}`} d={g} source={g.source} system={g.system} bare />
            </section>
          ))}
          {r.skipped.length > 0 && (
            <ul className="online-skipped faint">
              {r.skipped.map((s) => <li key={s.source}><b>{s.label}</b> ({s.name}): {s.reason}</li>)}
            </ul>
          )}
        </>
      )}
    </>
  );
}

function Tunes({ source, file, playingKey }: { source: string; file: OnlineFile; playingKey: string }) {
  const q = useQuery({
    queryKey: ["online-open", source, file.path], staleTime: Infinity,
    queryFn: () => api.post<{ title: string; tracks: OnlineTrack[] }>("/api/online/open", { source, path: file.path }),
  });
  if (q.isLoading) return <div className="online-tunes dim">Fetching {file.name}…</div>;
  if (q.isError) return <div className="online-tunes error-text">{(q.error as Error).message}</div>;
  const tracks = q.data?.tracks || [];
  if (!tracks.length) return <div className="online-tunes dim">Nothing in here plays in Muzix.</div>;
  return (
    <div className="online-tunes" role="list" aria-label={`Tunes in ${file.name}`}>
      {tracks.map((t, i) => (
        <div key={t.key} role="listitem" className={`online-tune ${playingKey === t.key ? "playing" : ""}`}
             onClick={() => engine.play(tracks.map(fromOnline), i)}>
          <span className="online-n"><span className="n">{i + 1}</span><Play size={13} fill="currentColor" className="p" /></span>
          <span className="online-name">
            <span className="ellipsis">{t.title}</span>
            {t.artist && <span className="online-by ellipsis">{t.artist}</span>}
          </span>
          <span className="online-size">{t.duration ? fmtTime(t.duration) : ""}</span>
        </div>
      ))}
    </div>
  );
}
