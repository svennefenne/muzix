/** The VGM page's online archives: HVSC, Modland, ASMA, the Joshw game rips and scene.org,
 * browsed folder by folder and played without adding anything to the library. */
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, Folder, Loader2, Play, Search, Shuffle } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, fmtBytes, fmtTime } from "../api";
import { queryClient } from "../actions";
import { Display, Empty, Loading, Stripes } from "../components/ui";
import { engine } from "../player/engine";
import { fromOnline, usePlayer, type PlayItem } from "../store/player";
import { useUi } from "../store/ui";
import { SYSTEM_ACCENTS } from "../theme/skins";
import type { OnlineFile, OnlineListing, OnlineSource, OnlineTrack } from "../types";

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
  if (f.title) return [f.title, [f.artist, f.year || ""].filter(Boolean).join(" · ")];
  return splitName(f.name);
}

/** A whole file, queued before it's downloaded: the server fetches it when it comes up. */
function fileItem(source: string, f: OnlineFile, system: string): PlayItem {
  const q = new URLSearchParams({ source, path: f.path, sub: "-1" });
  return {
    key: `online:${source}:${f.path}||-1`, kind: "online", id: f.path, title: fileLabel(f)[0],
    artist: f.artist || "", duration: f.duration || 0, src: `/api/online/stream?${q}`, system, trackKind: f.chip ? "vgm" : "music", format: f.format,
  };
}

export function OnlineHome() {
  const sources = useSources();
  const navigate = useNavigate();
  return (
    <>
      <p className="lede">The big chiptune and tracker archives, played straight from the source. Muzix fetches a folder when you open it and a tune when you play it, and keeps recent tunes for a while.</p>
      {sources.isLoading ? <Loading /> : (
        <div className="bento online-sources">
          {(sources.data || []).map((s) => (
            <div key={s.id} className="tile" role="link" tabIndex={0} aria-label={`${s.label}, from ${s.name}`}
                 style={{ "--tile-color": SYSTEM_ACCENTS[s.system]?.primary || "var(--primary)" } as React.CSSProperties}
                 onClick={() => navigate(href(s.id))} onKeyDown={(e) => e.key === "Enter" && navigate(href(s.id))}>
              <Stripes />
              <div className="tile-body">
                <div className="tile-kicker">{s.name}</div>
                <div className="tile-title" style={{ fontSize: s.label.length > 14 ? 24 : 30 }}>{s.label}</div>
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
      <p className="faint online-credit">The archives are run by volunteers: thank you, HVSC, Modland, ASMA, Joshw and scene.org.</p>
    </>
  );
}

export function OnlineBrowser() {
  const params = useParams();
  const source = params.source || "";
  const path = (params["*"] || "").replace(/\/+$/, "");
  const src = useSources().data?.find((s) => s.id === source);
  const list = useQuery({
    queryKey: ["online-list", source, path], staleTime: 10 * 60_000,
    queryFn: () => api.get<OnlineListing>("/api/online/list", { source, path }),
  });
  const d = list.data;
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
      {list.isLoading ? <Loading /> : list.isError ? (
        <Empty title="Couldn't open this folder">{(list.error as Error).message}. <button className="btn small" onClick={() => list.refetch()}>Try again</button></Empty>
      ) : d && <FolderView key={`${source}/${path}`} d={d} source={source} system={src?.system || d.system} />}
    </>
  );
}

function FolderView({ d, source, system }: { d: OnlineListing; source: string; system: string }) {
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
  return (
    <>
      <div className="toolbar online-bar">
        {tunes.length > 0 && <>
          <button className="btn primary" onClick={() => playFolder(false)}><Play size={15} fill="currentColor" /> Play folder</button>
          <button className="btn" onClick={() => playFolder(true)}><Shuffle size={15} /> Shuffle</button>
        </>}
        {total > 12 && (
          <label className="online-filter">
            <Search size={15} />
            <input className="input" value={filter} onChange={(e) => setFilter(e.target.value)}
                   placeholder={`Filter ${total.toLocaleString()} ${d.files.length ? "items" : "folders"}`} aria-label="Filter this folder" />
          </label>
        )}
      </div>

      {letters && !f ? (
        <div className="online-letters">
          {d.dirs.map((x) => <Link key={x.path} to={href(source, x.path)}>{x.name}</Link>)}
        </div>
      ) : dirs.length > 0 && (
        <div className="online-folders">
          {dirs.slice(0, shown).map((x) => (
            <Link key={x.path} to={href(source, x.path)} title={x.name}>
              <Folder size={15} /><span className="ellipsis">{x.name.replace(/_/g, " ")}</span>
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
                  <span className="online-name" title={x.name}>
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
      {total === 0 && <Empty title="Nothing here Muzix can play">{d.other ? `${d.other} files in other formats.` : "This folder is empty."}</Empty>}
      {d.other > 0 && total > 0 && <p className="faint online-other">{d.other.toLocaleString()} more {d.other === 1 ? "file" : "files"} here in formats Muzix doesn't play.</p>}
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
