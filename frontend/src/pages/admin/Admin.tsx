import { useQuery } from "@tanstack/react-query";
import { Activity, Blocks, Disc3, EyeOff, FileQuestion, FolderOpen, Gamepad2, HardDrive, History, Image as ImageIcon, Library, Network, Plus, RefreshCw, Save, Settings2, Tags as TagsIcon, Trash2, Upload, Users, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, NavLink, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { create } from "zustand";
import { ago, api, fmtBytes, fmtNumber } from "../../api";
import { queryClient } from "../../actions";
import { refreshAll, useAdminDialogs } from "../../components/AdminMode";
import { Art, Display, Empty, Kicker, Loading, Modal, Switch } from "../../components/ui";
import { useUi } from "../../store/ui";
import type { Album, Job } from "../../types";
import { Edits } from "./Edits";
import { HiddenAndTrash } from "./HiddenTrash";
import { FolderBrowser, SettingField, type SettingSpec } from "./fields";
import { Modules } from "./Modules";
import { LibraryNetwork } from "./Network";
import { Tags } from "./Tags";
import { AdminUsers } from "./Users";
import { WatchFolder } from "./Watch";

interface Root { id: number; path: string; kind: string; name: string; enabled: boolean; upload_target: boolean; excludes: string[]; items: number; exists: boolean; writable: boolean; last_scan: string | null }
interface Status {
  version: string; tools: Record<string, boolean>; counts: Record<string, number>; cache_bytes: number | null; art_bytes: number | null;
  data_dir: string; data_free_bytes: number;
  without_art: { albums: number; tracks: number };     // this server's music albums without a cover, and their songs
}

const TOOL_INFO: Record<string, string> = {
  ffmpeg: "Transcoding and FLAC encoding", ffprobe: "Chapters and lengths", libopenmpt: "Tracker modules (MOD/XM/IT/S3M/MT2)",
  libgme: "NES, Game Boy, SNES, Sega, PC Engine…", "libgme-sgc": "Master System and Game Gear (SGC)", sidplayfp: "Commodore 64 SID", fluidsynth: "MIDI", ymtool: "Atari ST YM",
  furnace: "FamiTracker / Furnace", beet: "Upload tagging (beets)",
};

function useJobs(limit = 50, interval = 3000) {
  return useQuery({ queryKey: ["jobs", limit], queryFn: () => api.get<Job[]>("/api/admin/jobs", { limit }), refetchInterval: interval });
}

function JobRow({ j }: { j: Job }) {
  const [open, setOpen] = useState(false);
  const detail = useQuery({ queryKey: ["job", j.id], queryFn: () => api.get<Job>(`/api/admin/jobs/${j.id}`), enabled: open, refetchInterval: open && j.status === "running" ? 2000 : false });
  return (
    <div className="list-row" style={{ display: "block" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <span className={`status-dot ${j.status}`} />
        <div className="grow" style={{ minWidth: 0 }}>
          <div style={{ fontWeight: 700 }}>{j.title}</div>
          <div className="dim ellipsis" style={{ fontSize: 12.5 }}>{j.status} · {ago(j.started_at || j.created_at)}{j.message ? ` · ${j.message}` : ""}</div>
        </div>
        {j.status === "running" && <div style={{ width: 140 }}><div className="progressbar"><div style={{ width: `${j.progress * 100}%` }} /></div></div>}
        {(j.status === "running" || j.status === "queued") && <button className="btn small ghost" onClick={() => api.post(`/api/admin/jobs/${j.id}/cancel`)}>Cancel</button>}
        <button className="btn small" onClick={() => setOpen(!open)}>{open ? "Hide log" : "Log"}</button>
      </div>
      {open && <pre className="log">{detail.data?.log || "…"}</pre>}
    </div>
  );
}

// ---------------------------------------------------------------- overview

function Overview() {
  const st = useQuery({ queryKey: ["admin-status"], queryFn: () => api.get<Status>("/api/admin/status"), refetchInterval: 15000 });
  const jobs = useJobs(6);
  const notify = useUi((s) => s.notify);
  const run = async (path: string, body?: unknown, msg = "Started") => {
    await api.post(path, body);
    notify(msg);
    jobs.refetch();
  };
  if (!st.data) return <Loading />;
  const s = st.data;
  return (
    <>
      <div className="kv" style={{ marginBottom: 18 }}>
        {[["Tracks", s.counts.tracks], ["Chiptunes", s.counts.vgm], ["Albums", s.counts.albums], ["Artists", s.counts.artists],
          ["Audiobooks", s.counts.books], ["Podcasts", s.counts.feeds], ["Users", s.counts.users]].map(([k, v]) => (
          <div key={k as string} className="stat"><div className="v">{fmtNumber(v as number)}</div><div className="k">{k}</div></div>
        ))}
        <Link to="/admin/artwork" className={`stat stat-link ${s.without_art.albums ? "warn" : ""}`}
              data-tip="The albums without a cover, to give them one">
          <div className="v">{fmtNumber(s.without_art.albums)}</div>
          <div className="k">Albums without artwork</div>
          <div className="sub">{s.without_art.albums ? `${fmtNumber(s.without_art.tracks)} songs` : "every album has one"}</div>
        </Link>
      </div>
      <section className="panel">
        <div className="panel-head"><div className="h3">Quick actions</div></div>
        <div className="row-actions">
          <button className="btn accent" onClick={() => run("/api/admin/scan", {}, "Scanning for new and changed files")}><RefreshCw size={15} /> Scan library</button>
          <button className="btn" onClick={() => run("/api/admin/scan", { full: true }, "Full rescan started")}>Full rescan</button>
          <button className="btn" onClick={() => run("/api/admin/jobs/scan_books", undefined, "Scanning audiobooks")}>Scan audiobooks</button>
          <button className="btn" onClick={() => run("/api/admin/jobs/artist_tags", undefined, "Fetching artist genres")}>Fetch artist genres</button>
          <button className="btn" onClick={() => run("/api/admin/jobs/refresh_feeds", undefined, "Refreshing podcasts")}>Refresh podcasts</button>
          <Link className="btn" to="/admin/upload"><Upload size={15} /> Upload music</Link>
        </div>
      </section>
      <section className="panel">
        <div className="panel-head"><div className="h3">Players and tools</div><span className="faint mono" style={{ fontSize: 11 }}>v{s.version}</span></div>
        <div className="kv" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))" }}>
          {Object.entries(s.tools).map(([k, ok]) => (
            <div key={k} className="list-row"><span className={`status-dot ${ok ? "ok" : "bad"}`} />
              <div className="grow"><b>{k}</b><div className="dim" style={{ fontSize: 12 }}>{TOOL_INFO[k] || ""}</div></div>
              <span className="badge">{ok ? "ready" : "missing"}</span></div>
          ))}
        </div>
      </section>
      <section className="panel">
        <div className="panel-head"><div className="h3">Storage</div></div>
        <div className="list">
          <div className="list-row"><HardDrive size={16} /><div className="grow">Rendered chiptune cache</div><b>{s.cache_bytes == null ? "counting…" : fmtBytes(s.cache_bytes)}</b>
            <button className="btn small ghost" onClick={async () => { await api.post("/api/admin/cache/clear?what=render"); st.refetch(); }}>Clear</button></div>
          <div className="list-row"><HardDrive size={16} /><div className="grow">Cover art cache</div><b>{s.art_bytes == null ? "counting…" : fmtBytes(s.art_bytes)}</b>
            <button className="btn small ghost" onClick={async () => { await api.post("/api/admin/cache/clear?what=art"); st.refetch(); }}>Clear</button></div>
          <div className="list-row"><HardDrive size={16} /><div className="grow">Free space in {s.data_dir}</div><b>{fmtBytes(s.data_free_bytes)}</b></div>
        </div>
      </section>
      <section className="panel">
        <div className="panel-head"><div className="h3">Recent jobs</div></div>
        <div className="list">{(jobs.data || []).map((j) => <JobRow key={j.id} j={j} />)}</div>
      </section>
    </>
  );
}

// ---------------------------------------------------------------- library folders

function RootRow({ r, reload }: { r: Root; reload: () => void }) {
  const [excl, setExcl] = useState(r.excludes.join(", "));
  const modules = useUi((s) => s.modules);
  const resting = (r.kind === "vgm" && !modules.vgm) || (r.kind === "audiobooks" && !modules.audiobooks);
  const save = async (patch: Partial<Root>) => {
    await api.put(`/api/admin/roots/${r.id}`, { ...r, ...patch });
    reload();
  };
  return (
    <div className="list-row" style={{ display: "block" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <span className={`status-dot ${r.exists ? "ok" : "bad"}`} data-tip={r.exists ? "Mounted" : "Not found in the container"} />
        <div className="grow" style={{ minWidth: 220 }}>
          <div style={{ fontWeight: 700, wordBreak: "break-all" }}>{r.path}</div>
          <div className="dim" style={{ fontSize: 12.5 }}>
            {fmtNumber(r.items)} {r.kind === "audiobooks" ? "books" : "tracks"} · scanned {r.last_scan ? ago(r.last_scan) : "never"}
            {resting && ` · not scanned while ${r.kind === "vgm" ? "VGM" : "Audiobooks"} is off`}
            {r.exists && !r.writable && " · read-only"}
          </div>
        </div>
        <select className="select" style={{ width: 140 }} value={r.kind} onChange={(e) => save({ kind: e.target.value })}>
          <option value="music">Music</option><option value="vgm">VGM</option><option value="audiobooks">Audiobooks</option>
        </select>
        <label className="row-actions dim" style={{ gap: 6 }} data-tip="New uploads of this kind go here">
          <input type="radio" checked={r.upload_target} onChange={() => save({ upload_target: true })} /> Upload target
        </label>
        <Switch checked={r.enabled} onChange={(v) => save({ enabled: v })} label="Enabled" />
        <button className="btn small" onClick={async () => { await api.post(r.kind === "audiobooks" ? "/api/admin/jobs/scan_books" : "/api/admin/scan", r.kind === "audiobooks" ? undefined : { root_id: r.id }); reload(); }}>Scan</button>
        <button className="mini" aria-label="Remove" onClick={async () => {
          if (!confirm(`Remove ${r.path} from the library? The files on disk are not touched.`)) return;
          await api.del(`/api/admin/roots/${r.id}`);
          reload();
        }}><Trash2 size={15} /></button>
      </div>
      <div style={{ display: "flex", gap: 10, alignItems: "center", marginTop: 10 }}>
        <span className="dim" style={{ fontSize: 12.5, whiteSpace: "nowrap" }}>Skip subfolders</span>
        <input className="input" style={{ height: 32, fontSize: 13 }} value={excl} placeholder="e.g. Other formats, Duplicates"
               onChange={(e) => setExcl(e.target.value)}
               onBlur={() => save({ excludes: excl.split(",").map((x) => x.trim()).filter(Boolean) })} />
      </div>
    </div>
  );
}

function LibraryFolders() {
  const roots = useQuery({ queryKey: ["roots"], queryFn: () => api.get<Root[]>("/api/admin/roots") });
  const [browsing, setBrowsing] = useState(false);
  const [path, setPath] = useState("");
  const [kind, setKind] = useState("music");
  const modules = useUi((s) => s.modules);
  const [err, setErr] = useState("");
  const add = async () => {
    setErr("");
    try {
      await api.post("/api/admin/roots", { path, kind });
      setPath("");
      roots.refetch();
    } catch (e) {
      setErr((e as Error).message);
    }
  };
  return (
    <>
      <section className="panel">
        <div className="panel-head"><div className="h3">Add a folder</div></div>
        <p className="dim" style={{ marginTop: 0 }}>Folders are paths inside the container: map your shares in the Unraid template (e.g. /mnt/user/media/musik → /music).</p>
        <div className="row-actions">
          <input className="input" style={{ flex: 1, minWidth: 220 }} placeholder="/music/mp3" value={path} onChange={(e) => setPath(e.target.value)} />
          <button className="btn" onClick={() => setBrowsing(true)}><FolderOpen size={15} /> Browse</button>
          <select className="select" style={{ width: 150 }} value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="music">Music</option>
            {modules.vgm && <option value="vgm">VGM / chiptunes</option>}
            {modules.audiobooks && <option value="audiobooks">Audiobooks</option>}
          </select>
          <button className="btn accent" disabled={!path} onClick={add}><Plus size={15} /> Add & scan</button>
        </div>
        {err && <p className="error-text">{err}</p>}
      </section>
      <section className="panel">
        <div className="panel-head"><div className="h3">Library folders</div></div>
        {roots.data ? (roots.data.length ? <div className="list">{roots.data.map((r) => <RootRow key={r.id} r={r} reload={() => roots.refetch()} />)}</div>
          : <Empty title="No folders yet" />) : <Loading />}
      </section>
      {browsing && <FolderBrowser onClose={() => setBrowsing(false)} onPick={(p) => { setPath(p); setBrowsing(false); }} />}
    </>
  );
}

// ---------------------------------------------------------------- upload

interface Pending { file: File; path: string }
interface Found {
  path: string; why: "library" | "similar" | "uploaded" | "waiting"; when?: string;
  match?: { title: string; artist: string; album: string; format: string; path: string };
}
interface Review { files: Pending[]; found: Found[]; skip: string[]; resolve: (send: Pending[] | null) => void }
/** An album in an upload, as its songs' tags say (by its folder, without an album tag). */
interface UploadAlbum { artist: string; album: string; year: number; songs: number; formats: string[]; size: number; folder: string }
interface Batch {
  batch: string; files: { path: string; size: number; kind: string }[]; created: string; albums: UploadAlbum[];
  job: { id: number; status: string; progress: number; message: string } | null;
}
/** An import, and where it filed each album (its page here, once the library has scanned it). */
interface ImportDone {
  id: number; batch: string; status: string; message: string; progress: number; started_at: string | null; finished_at: string | null;
  music: number | null; vgm: number | null; vgm_folder: string; left: string[];
  albums: { artist: string; album: string; year: number; songs: number; where: string; album_id: number | null }[];
}
const MUSIC_KINDS = ["native", "decode"];

/** What a batch's files are: its albums, its chiptunes and tracker modules, and anything else. */
function BatchContents({ b }: { b: Batch }) {
  const chips = b.files.filter((f) => !MUSIC_KINDS.includes(f.kind) && f.kind !== "other");
  const others = b.files.filter((f) => f.kind === "other");
  const name = (p: string) => p.split("/").pop();
  return (
    <ul className="upload-contents">
      {b.albums.map((a) => (
        <li key={`${a.artist}|${a.album}|${a.folder}`}>
          <Disc3 size={15} aria-hidden />
          <span className="grow ellipsis"><b>{a.album}</b> <span className="dim">{a.artist || "artist unknown"}</span></span>
          <span className="faint">{[a.year || null, `${a.songs} ${a.songs === 1 ? "song" : "songs"}`, a.formats.join(", ").toUpperCase(),
            fmtBytes(a.size)].filter(Boolean).join(" · ")}</span>
        </li>
      ))}
      {chips.length > 0 && (
        <li>
          <Gamepad2 size={15} aria-hidden />
          <span className="grow"><b>{chips.length} chiptune and tracker {chips.length === 1 ? "file" : "files"}</b>{" "}
            <span className="dim">go to the VGM upload folder as they are</span></span>
        </li>
      )}
      {others.length > 0 && (
        <li>
          <FileQuestion size={15} aria-hidden />
          <span className="grow ellipsis"><b>{others.length} other {others.length === 1 ? "file" : "files"}</b>{" "}
            <span className="dim">{others.slice(0, 4).map((f) => name(f.path)).join(", ")}{others.length > 4 ? ", …" : ""}</span></span>
          <span className="faint">not imported</span>
        </li>
      )}
    </ul>
  );
}

/** Where a batch stands: waiting, being imported, failed, or imported with files left over. */
function batchState(b: Batch): { text: string; tone: "" | "busy" | "bad" | "done" } {
  const j = b.job;
  if (!j) return { text: "Not imported yet", tone: "" };
  if (j.status === "queued") return { text: "Import queued…", tone: "busy" };
  if (j.status === "running") return { text: `Importing${j.message ? `: ${j.message}` : "…"}`, tone: "busy" };
  if (j.status === "failed") return { text: `The import failed${j.message ? `: ${j.message}` : ""}. Import tries again.`, tone: "bad" };
  return { text: "Imported. These files were left over: the import didn't take them", tone: "done" };
}

/** The latest imports: what each filed where, and what it left. */
function RecentImports() {
  const q = useQuery({ queryKey: ["imports"], queryFn: () => api.get<ImportDone[]>("/api/upload/imports"), refetchInterval: 5000 });
  const done = (q.data || []).filter((i) => i.status === "done" || i.status === "failed");
  if (!done.length) return null;
  return (
    <section className="panel">
      <div className="panel-head"><div className="h3">Imported lately</div><span className="dim">where each album went</span></div>
      <div className="list">
        {done.map((i) => {
          const songs = i.albums.reduce((n, a) => n + a.songs, 0);
          const counted = i.albums.length
            ? [`${i.albums.length} ${i.albums.length === 1 ? "album" : "albums"}`, `${songs} ${songs === 1 ? "song" : "songs"}`]
            : i.music ? [`${i.music} music ${i.music === 1 ? "file" : "files"}`] : [];
          if (i.vgm) counted.push(`${i.vgm} chiptune and tracker ${i.vgm === 1 ? "file" : "files"}`);
          return (
            <div key={i.id} className="list-row upload-batch">
              <div className="upload-head">
                <span className={`status-dot ${i.status === "failed" ? "bad" : "ok"}`} />
                <div className="grow">
                  <div className="upload-title">{i.status === "failed" ? "Import failed" : "Imported"} {i.finished_at ? ago(i.finished_at) : ""}</div>
                  <div className={i.status === "failed" ? "error-text" : "dim"} style={{ fontSize: 12.5 }}>
                    {i.status === "failed" ? i.message || "See its log under Jobs" : counted.join(" · ") || "Nothing to import"}
                  </div>
                </div>
              </div>
              {(i.albums.length > 0 || i.vgm || i.left.length > 0) && (
                <ul className="upload-contents">
                  {i.albums.map((a) => (
                    <li key={a.where}>
                      <Disc3 size={15} aria-hidden />
                      <span className="grow ellipsis"><b>{a.album}</b> <span className="dim">{a.artist}</span>{" "}
                        <span className="faint mono-path" data-tip="Where it was filed in the music upload folder">→ {a.where}</span></span>
                      {a.album_id ? <Link className="btn small" to={`/album/${a.album_id}`}>Open</Link>
                        : <span className="faint" data-tip="It shows up once the library has read the folder">being added…</span>}
                    </li>
                  ))}
                  {i.vgm ? (
                    <li><Gamepad2 size={15} aria-hidden /><span className="grow ellipsis"><b>{i.vgm} chiptune and tracker {i.vgm === 1 ? "file" : "files"}</b>{" "}
                      <span className="faint mono-path">→ {i.vgm_folder || "the VGM upload folder"}</span></span></li>
                  ) : null}
                  {i.left.length > 0 && (
                    <li><FileQuestion size={15} aria-hidden /><span className="grow ellipsis"><b>{i.left.length} {i.left.length === 1 ? "file" : "files"} not imported</b>{" "}
                      <span className="dim">{i.left.slice(0, 4).map((p) => p.split("/").pop()).join(", ")}{i.left.length > 4 ? ", …" : ""}</span></span>
                      <span className="faint">still in the upload area</span></li>
                  )}
                </ul>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}

/** The files of a drop: folders walked through their entries, anything without one taken as
 * a plain file. Both have to be picked up during the drop event itself. */
function droppedFiles(dt: DataTransfer): Promise<Pending[]> {
  const items = Array.from(dt.items).filter((i) => i.kind === "file");
  const entries = items.map((i) => i.webkitGetAsEntry?.() ?? null);
  const loose = items.map((i, n) => (entries[n] ? null : i.getAsFile())).filter((f): f is File => !!f);
  if (!items.length) loose.push(...Array.from(dt.files));
  return entriesToFiles(entries.filter((e): e is FileSystemEntry => !!e))
    .then((walked) => [...walked, ...loose.map((file) => ({ file, path: file.name }))]);
}

async function entriesToFiles(entries: FileSystemEntry[]): Promise<Pending[]> {
  const out: Pending[] = [];
  const walk = async (entry: FileSystemEntry): Promise<void> => {
    if (entry.isFile) {
      const file = await new Promise<File>((res, rej) => (entry as FileSystemFileEntry).file(res, rej));
      out.push({ file, path: entry.fullPath.replace(/^\//, "") });
    } else if (entry.isDirectory) {
      const reader = (entry as FileSystemDirectoryEntry).createReader();
      let batch: FileSystemEntry[];
      do {
        batch = await new Promise<FileSystemEntry[]>((res, rej) => reader.readEntries(res, rej));
        for (const e of batch) await walk(e);
      } while (batch.length);
    }
  };
  for (const e of entries) await walk(e);
  return out;
}

/** An upload in progress, shared so a drop on any admin page can start one. */
const useUpload = create<{ progress: { done: number; total: number; files: number } | null; checking: boolean; review: Review | null }>(
  () => ({ progress: null, checking: false, review: null }));

/** Before anything goes up: files that look like duplicates (sent before, or songs the library
 * seems to have) are shown, and the uploader picks what to send. null: cancelled. */
async function checkDuplicates(files: Pending[]): Promise<Pending[] | null> {
  useUpload.setState({ checking: true });
  let res: { found: Found[]; skip: string[] };
  try {
    res = await api.post("/api/upload/check", { files: files.map((f) => ({ path: f.path, size: f.file.size })) });
  } catch {
    useUi.getState().notify("Couldn't check for duplicates: uploading everything", "error");
    return files;
  } finally {
    useUpload.setState({ checking: false });
  }
  if (!res.found.length) return files;
  return new Promise((resolve) => useUpload.setState({ review: { files, ...res, resolve } }));
}

async function startUpload(files: Pending[]) {
  const notify = useUi.getState().notify;
  const setProgress = (progress: { done: number; total: number; files: number } | null) => useUpload.setState({ progress });
  const picked = files.filter((f) => !f.path.split("/").some((p) => p.startsWith(".")));
  if (!picked.length) return;
  const audioish = await checkDuplicates(picked);
  if (!audioish) return;
  if (!audioish.length) return notify("Nothing to upload: every file was skipped");
  const { batch } = await api.post<{ batch: string }>("/api/upload/batch");
  const total = audioish.reduce((s, f) => s + f.file.size, 0);
  let done = 0;
  setProgress({ done: 0, total, files: audioish.length });
  try {
    for (let i = 0; i < audioish.length;) {
      const base = done;
      const report = (loaded: number) => setProgress({ done: base + loaded, total, files: audioish.length });
      if (audioish[i].file.size > MAX_REQUEST) {
        const big = audioish[i++];
        await sendParts(batch, big, report);
        done = base + big.file.size;
        continue;
      }
      const chunk: Pending[] = [];
      let size = 0;
      while (i < audioish.length && chunk.length < 25 && size + audioish[i].file.size <= MAX_REQUEST) {
        size += audioish[i].file.size;
        chunk.push(audioish[i++]);
      }
      await sendChunk(batch, chunk, report);
      done = base + size;
    }
    notify(`Uploaded ${audioish.length} files. Press Import to tag and file them.`);
  } catch (e) {
    notify((e as Error).message, "error");
  } finally {
    setProgress(null);
    queryClient.invalidateQueries({ queryKey: ["batches"] });
  }
}

// Cloudflare (and some other proxies) refuse request bodies over 100 MiB, so
// requests stay well below that and bigger files go up in pieces.
const MAX_REQUEST = 64e6;
const PART = 48 * 1024 * 1024;

function post(url: string, fd: FormData, onProgress: (loaded: number) => void): Promise<void> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", url);
    xhr.upload.onprogress = (e) => onProgress(e.loaded);
    xhr.onload = () => (xhr.status < 300 ? resolve() : reject(new Error(xhr.responseText || xhr.statusText)));
    xhr.onerror = () => reject(new Error("Upload failed"));
    xhr.send(fd);
  });
}

function sendChunk(batch: string, chunk: Pending[], onProgress: (loaded: number) => void): Promise<void> {
  const fd = new FormData();
  for (const p of chunk) {
    fd.append("files", p.file, p.file.name);
    fd.append("paths", p.path);
  }
  return post(`/api/upload/batch/${batch}/files`, fd, onProgress);
}

async function sendParts(batch: string, p: Pending, onProgress: (loaded: number) => void): Promise<void> {
  for (let offset = 0; offset < p.file.size; offset += PART) {
    const fd = new FormData();
    fd.append("path", p.path);
    fd.append("offset", String(offset));
    fd.append("total", String(p.file.size));
    fd.append("data", p.file.slice(offset, offset + PART), p.file.name);
    await post(`/api/upload/batch/${batch}/part`, fd, (loaded) => onProgress(offset + loaded));
  }
}

const WHY: [Found["why"], string][] = [
  ["library", "Already in the library"], ["similar", "Similar name in the library"],
  ["uploaded", "Uploaded before"], ["waiting", "Waiting to be imported"],
];
const SHOWN = 100;

function DuplicatesDialog({ review }: { review: Review }) {
  const done = (send: Pending[] | null) => {
    useUpload.setState({ review: null });
    review.resolve(send);
  };
  const skip = new Set(review.skip);
  const rest = review.files.filter((f) => !skip.has(f.path));
  const along = review.skip.length - review.found.length;
  return (
    <Modal onClose={() => done(null)} className="dupes">
      <div className="kicker">Before uploading</div>
      <div className="h2">{review.found.length} of {review.files.length} files may be duplicates</div>
      {WHY.map(([why, heading]) => {
        const items = review.found.filter((f) => f.why === why);
        if (!items.length) return null;
        return (
          <section key={why} className="dupe-group">
            <div className="h3">{heading} <span className="faint">{items.length}</span></div>
            <ul className="dupe-list">
              {items.slice(0, SHOWN).map((f) => (
                <li key={f.path}>
                  <div>{f.path}</div>
                  {f.match ? (
                    <div className="dim" data-tip={f.match.path}>
                      {f.match.artist} – {f.match.title}{f.match.album && ` · ${f.match.album}`} · {f.match.format.toUpperCase()}
                    </div>
                  ) : <div className="dim">{why === "waiting" ? "In the upload area since" : "Uploaded"} {ago(f.when!)}</div>}
                </li>
              ))}
              {items.length > SHOWN && <li className="dim">and {items.length - SHOWN} more</li>}
            </ul>
          </section>
        );
      })}
      {along > 0 && <p className="dim">Skipping them also leaves out {along} lyrics, covers or other files that go with them.</p>}
      <div className="row-actions">
        <button className="btn accent" onClick={() => done(rest)}>{rest.length ? `Skip them, upload ${rest.length}` : "Skip them all"}</button>
        <button className="btn" onClick={() => done(review.files)}>Upload all {review.files.length}</button>
        <button className="btn ghost" onClick={() => done(null)}>Cancel</button>
      </div>
    </Modal>
  );
}

function UploadArea() {
  const progress = useUpload((s) => s.progress);
  const checking = useUpload((s) => s.checking);
  const review = useUpload((s) => s.review);
  const settings = useQuery({ queryKey: ["admin-settings"], queryFn: () => api.get<SettingSpec[]>("/api/admin/settings") });
  const checkOn = settings.data?.find((x) => x.key === "upload_check_duplicates")?.value !== false;
  const batches = useQuery({ queryKey: ["batches"], queryFn: () => api.get<Batch[]>("/api/upload/batches"), refetchInterval: 3000 });
  const fileInput = useRef<HTMLInputElement>(null);
  const dirInput = useRef<HTMLInputElement>(null);
  const upload = startUpload;


  return (
    <>
      <section className="panel">
        <div className="panel-head">
          <div><div className="kicker">Upload</div><div className="h3">Add music to the library</div></div>
          <label className="row-actions dim" style={{ gap: 8 }}
                 data-tip="Before files go up, look for ones uploaded before or still waiting to be imported, and for songs the library seems to have already (same title, with the artist or album in the file or folder names). You choose what to skip.">
            <Switch checked={checkOn} onChange={async (v) => {
              await api.put("/api/admin/settings", { upload_check_duplicates: v });
              settings.refetch();
            }} />
            Check for duplicates
          </label>
        </div>
        {/* drops are caught by the whole admin page (Admin below) */}
        <div className="dropzone" onClick={() => fileInput.current?.click()}>
          <Upload size={34} />
          <div className="h3">Drop files or whole folders here</div>
          <div className="dim" style={{ maxWidth: 520 }}>
            Music is matched with MusicBrainz, gets cover art and a main genre, and is filed as Genre/Artist/Artist - Year - Album
            in the music upload folder. Lyrics (.lrc files beside their songs) go along with them. Chiptunes and tracker
            modules go to the VGM upload folder.
          </div>
          <div className="row-actions" onClick={(e) => e.stopPropagation()}>
            <button className="btn" onClick={() => fileInput.current?.click()}>Choose files</button>
            <button className="btn" onClick={() => dirInput.current?.click()}>Choose a folder</button>
          </div>
          {checking && <div className="dim">Checking for duplicates…</div>}
          {progress && (
            <div style={{ width: "100%", maxWidth: 420 }}>
              <div className="progressbar"><div style={{ width: `${(progress.done / progress.total) * 100}%` }} /></div>
              <div className="dim" style={{ fontSize: 12, marginTop: 6 }}>{progress.files} files · {fmtBytes(progress.done)} of {fmtBytes(progress.total)}</div>
            </div>
          )}
        </div>
        {review && <DuplicatesDialog review={review} />}
        {/* emptied once read, so picking the same files again still counts */}
        <input ref={fileInput} type="file" multiple hidden onChange={(e) => {
          upload(Array.from(e.target.files || []).map((f) => ({ file: f, path: f.name })));
          e.target.value = "";
        }} />
        <input ref={dirInput} type="file" hidden {...{ webkitdirectory: "", directory: "" }} onChange={(e) => {
          upload(Array.from(e.target.files || []).map((f) => ({ file: f, path: f.webkitRelativePath || f.name })));
          e.target.value = "";
        }} />
      </section>
      <WatchFolder />
      <section className="panel">
        <div className="panel-head"><div className="h3">Waiting to be imported</div></div>
        {batches.data?.length ? (
          <div className="list">
            {batches.data.map((b) => {
              const running = b.job && (b.job.status === "running" || b.job.status === "queued");
              const state = batchState(b);
              const size = b.files.reduce((n, f) => n + f.size, 0);
              const leftOver = b.job?.status === "done";
              return (
                <div key={b.batch} className="list-row upload-batch">
                  <div className="upload-head">
                    <span className={`status-dot ${state.tone === "bad" ? "bad" : state.tone === "busy" ? "queued" : state.tone === "done" ? "ok" : ""}`} />
                    <div className="grow">
                      <div className="upload-title">Uploaded {ago(b.created)} · {b.files.length} {b.files.length === 1 ? "file" : "files"} · {fmtBytes(size)}</div>
                      <div className={state.tone === "bad" ? "error-text" : "dim"} style={{ fontSize: 12.5 }}>{state.text}</div>
                    </div>
                    {running ? <div style={{ width: 160 }}><div className="progressbar"><div style={{ width: `${(b.job!.progress || 0) * 100}%` }} /></div></div>
                      : !leftOver && <button className="btn accent" onClick={async () => { await api.post(`/api/upload/batch/${b.batch}/import`); batches.refetch(); }}>Import</button>}
                    <button className="mini" aria-label="Discard" data-tip="Discard: these uploaded files are deleted" onClick={async () => {
                      if (!confirm("Discard these uploaded files?")) return;
                      await api.del(`/api/upload/batch/${b.batch}`);
                      batches.refetch();
                    }}><X size={15} /></button>
                  </div>
                  <BatchContents b={b} />
                  <details style={{ marginTop: 8 }}>
                    <summary className="dim" style={{ cursor: "pointer", fontSize: 12.5 }}>All {b.files.length} files</summary>
                    <pre className="log">{b.files.map((f) => `${f.path}  (${fmtBytes(f.size)})`).join("\n")}</pre>
                  </details>
                  {b.job && <JobRow j={{ id: b.job.id, type: "import_upload", title: "Import log", status: b.job.status as Job["status"], progress: b.job.progress, message: b.job.message, result: {}, created_at: null, started_at: null, finished_at: null }} />}
                </div>
              );
            })}
          </div>
        ) : <Empty title="Nothing waiting">Uploaded files show up here until you import them.</Empty>}
      </section>
      <RecentImports />
    </>
  );
}

// ---------------------------------------------------------------- albums without artwork

type BareAlbum = Album & { folder: string };
const BARE_PAGE = 100;

/** Admin → Overview → Albums without artwork: each one to give a cover to with Edit metadata (saved
 * with a cover, it leaves the list: every query is fetched again after a save), or ticked, with
 * others, to delete: their files go to the trash, each album to put back on its own. */
function WithoutArtwork() {
  const setEdit = useAdminDialogs((s) => s.setEdit);
  const notify = useUi((s) => s.notify);
  const [shown, setShown] = useState(BARE_PAGE);
  const [ticked, setTicked] = useState<Set<number>>(new Set());
  const [asking, setAsking] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const q = useQuery({ queryKey: ["without-art", shown], placeholderData: (before) => before,
                       queryFn: () => api.get<{ total: number; items: BareAlbum[] }>("/api/admin/without-art", { limit: shown }) });
  if (!q.data) return <Loading />;
  const { total, items } = q.data;
  const songs = items.reduce((n, a) => n + a.track_count, 0);
  const picked = items.filter((a) => ticked.has(a.id));       // only those still listed
  const pickedSongs = picked.reduce((n, a) => n + a.track_count, 0);
  const all = items.length > 0 && picked.length === items.length;
  const tick = (id: number, on: boolean) => setTicked((t) => { const n = new Set(t); if (on) n.add(id); else n.delete(id); return n; });
  const remove = async () => {
    setAsking(false);
    setDeleting(true);
    try {
      const r = await api.post<{ deleted: { id: number }[]; failed: { id: number; why: string }[] }>(
        "/api/manage/albums/delete", { ids: picked.map((a) => a.id) });
      const name = (id: number) => items.find((a) => a.id === id)?.title ?? `album ${id}`;
      setTicked(new Set());
      notify(`${r.deleted.length} ${r.deleted.length === 1 ? "album is" : "albums are"} in the trash`
        + (r.failed.length ? `. Not deleted: ${r.failed.map((f) => `${name(f.id)} (${f.why})`).join("; ")}` : ""),
        r.failed.length ? "error" : "info", { label: "Show the trash", to: "/admin/hidden" });
      refreshAll();
    } catch (e) {
      notify((e as Error).message, "error");
    } finally {
      setDeleting(false);
    }
  };
  return (
    <section className="panel">
      <div className="panel-head">
        <div>
          <div className="kicker"><Link to="/admin">Overview</Link> · Artwork</div>
          <div className="h3">{total ? `${fmtNumber(total)} ${total === 1 ? "album" : "albums"} without artwork` : "Every album has artwork"}</div>
        </div>
      </div>
      <p className="dim" style={{ marginTop: 0 }}>
        Albums with no cover in their folder or their songs. <b>Edit</b> finds the album in the sources and its cover; once it's
        saved with a cover it leaves this list. Tick albums to delete their files: they go to the trash, from where each one can be put
        back under Hidden &amp; trash.
      </p>
      {items.length > 0 && (
        <div className="bare-bar">
          <label className="bare-all">
            <input type="checkbox" checked={all} ref={(el) => { if (el) el.indeterminate = picked.length > 0 && !all; }}
                   onChange={(e) => setTicked(e.target.checked ? new Set(items.map((a) => a.id)) : new Set())} />
            {picked.length ? `${fmtNumber(picked.length)} selected (${fmtNumber(pickedSongs)} songs)` : "Select all shown"}
          </label>
          <div className="grow" />
          {picked.length > 0 && (
            <button className="btn danger" disabled={deleting} onClick={() => setAsking(true)}>
              <Trash2 size={15} /> {deleting ? "Deleting…" : `Delete ${picked.length === 1 ? "album" : `${fmtNumber(picked.length)} albums`}`}
            </button>
          )}
        </div>
      )}
      {items.length > 0 && (
        <div className="list bare-albums">
          {items.map((a) => (
            <div key={a.id} className={`list-row ${ticked.has(a.id) ? "ticked" : ""}`}>
              <input type="checkbox" aria-label={`Select ${a.title}`} checked={ticked.has(a.id)} onChange={(e) => tick(a.id, e.target.checked)} />
              <Art src={null} name={a.title} size={64} className="bare-thumb" />
              <div className="grow" style={{ minWidth: 0 }}>
                <div className="ellipsis"><Link to={`/album/${a.id}`}><b>{a.title}</b></Link> <span className="dim">{a.artist}</span></div>
                {/* the end of its path says which folder it is (the whole of it on hover) */}
                <div className="faint ellipsis mono-path" data-tip={a.folder}>…/{a.folder.split("/").slice(-3).join("/")}</div>
              </div>
              <span className="faint bare-meta">{[a.year || null, `${a.track_count} ${a.track_count === 1 ? "song" : "songs"}`].filter(Boolean).join(" · ")}</span>
              <button className="btn small accent" onClick={() => setEdit({ kind: "album", id: a.id, title: a.title })}>
                <ImageIcon size={14} /> Edit
              </button>
            </div>
          ))}
        </div>
      )}
      {items.length < total && (
        <div className="row-actions" style={{ marginTop: 12 }}>
          <span className="dim">{fmtNumber(items.length)} of {fmtNumber(total)} shown ({fmtNumber(songs)} songs)</span>
          <button className="btn" disabled={q.isFetching} onClick={() => setShown((n) => n + BARE_PAGE)}>Show more</button>
        </div>
      )}
      {asking && (
        <Modal onClose={() => setAsking(false)}>
          <h2 className="h2">Delete {picked.length === 1 ? picked[0].title : `${fmtNumber(picked.length)} albums`}?</h2>
          <p className="dim" style={{ margin: "10px 0 12px" }}>
            {fmtNumber(pickedSongs)} {pickedSongs === 1 ? "song" : "songs"} leave the library. The files go to the trash: each album can be put
            back under Admin → Hidden &amp; trash until the trash is emptied.
          </p>
          {picked.length > 1 && (
            <ul className="bare-confirm">
              {picked.slice(0, 8).map((a) => <li key={a.id} className="ellipsis"><b>{a.title}</b> <span className="dim">{a.artist}</span></li>)}
              {picked.length > 8 && <li className="dim">and {fmtNumber(picked.length - 8)} more</li>}
            </ul>
          )}
          <div className="row-actions" style={{ justifyContent: "flex-end", marginTop: 16 }}>
            <button className="btn" onClick={() => setAsking(false)} autoFocus>Cancel</button>
            <button className="btn danger solid" onClick={remove}><Trash2 size={15} /> Delete</button>
          </div>
        </Modal>
      )}
    </section>
  );
}

// ---------------------------------------------------------------- jobs

function Jobs() {
  const jobs = useJobs(80);
  return (
    <section className="panel">
      <div className="panel-head"><div className="h3">Background jobs</div><span className="dim">refreshes every few seconds</span></div>
      {jobs.data ? <div className="list">{jobs.data.map((j) => <JobRow key={j.id} j={j} />)}</div> : <Loading />}
    </section>
  );
}

// ---------------------------------------------------------------- settings (from the server schema)

function AdminSettings() {
  const q = useQuery({ queryKey: ["admin-settings"], queryFn: () => api.get<SettingSpec[]>("/api/admin/settings") });
  const [edits, setEdits] = useState<Record<string, unknown>>({});
  const [error, setError] = useState("");
  const notify = useUi((s) => s.notify);
  const loc = useLocation();
  const groups = useMemo(() => {
    const g: Record<string, SettingSpec[]> = {};
    // a module's settings, and the modules themselves, are under Modules
    // the modules and the watch folder have places of their own (Modules, Upload → Watch folder)
    for (const s of q.data || []) if (!s.module && s.group !== "Modules" && s.group !== "Watch folder") (g[s.group] ||= []).push(s);
    return g;
  }, [q.data]);
  useEffect(() => {
    if (loc.hash) document.getElementById(decodeURIComponent(loc.hash.slice(1)))?.scrollIntoView();
  }, [loc.hash, q.data]);
  if (!q.data) return <Loading />;
  const dirty = Object.keys(edits).length > 0;
  const save = async () => {
    setError("");
    try {
      await api.put("/api/admin/settings", edits);
      setEdits({});
      q.refetch();
      queryClient.invalidateQueries({ queryKey: ["auth"] });
      notify("Settings saved");
    } catch (e) {
      setError((e as Error).message);
    }
  };
  return (
    <>
      {Object.entries(groups).map(([group, specs]) => (
        <section key={group} className="panel" id={group}>
          <div className="panel-head"><div className="h3">{group}</div></div>
          {specs.map((s) => (
            <div key={s.key} className="field">
              <label htmlFor={s.key}>{s.label}</label>
              <SettingField s={s} value={s.key in edits ? edits[s.key] : s.value} onChange={(v) => setEdits({ ...edits, [s.key]: v })} />
              {s.help && <div className="help">{s.help}</div>}
            </div>
          ))}
        </section>
      ))}
      <div style={{ position: "sticky", bottom: 0, padding: "14px 0", background: "linear-gradient(transparent, var(--bg) 40%)" }}>
        <div className="row-actions">
          <button className="btn accent" disabled={!dirty} onClick={save}><Save size={15} /> Save settings</button>
          {dirty && <button className="btn ghost" onClick={() => setEdits({})}>Undo changes</button>}
          {error && <span className="error-text">{error}</span>}
        </div>
      </div>
    </>
  );
}

export default function Admin() {
  const user = useUi((s) => s.user);
  const modules = useUi((s) => s.modules);
  const [dragging, setDragging] = useState(false);
  const go = useNavigate();
  if (!user?.is_admin) return <div className="page"><Empty title="Admins only" /></div>;
  // files dragged over any admin page can be dropped to upload them
  const files = (e: React.DragEvent) => Array.from(e.dataTransfer.types).includes("Files");
  const nav = [["", "Overview", Activity], ["library", "Library folders", Library], ["modules", "Modules", Blocks],
    ...(modules.network ? [["network", "Library Network", Network] as const] : []), ["upload", "Upload", Upload],
    ["tags", "Tags", TagsIcon], ["edits", "Edits", History], ["hidden", "Hidden & trash", EyeOff], ["jobs", "Jobs", RefreshCw], ["settings", "Settings", Settings2], ["users", "Users", Users]] as const;
  return (
    <div className="page wide"
         onDragOver={(e) => { if (!files(e)) return; e.preventDefault(); setDragging(true); }}
         onDragLeave={(e) => { if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setDragging(false); }}
         onDrop={(e) => {
           if (!files(e)) return;
           e.preventDefault();
           setDragging(false);
           const picked = droppedFiles(e.dataTransfer);
           go("/admin/upload");
           picked.then(startUpload);
         }}>
      {dragging && <div className="drop-overlay" aria-hidden><Upload size={40} /><span>Drop to upload music</span></div>}
      <Kicker parts={["Admin", "Muzix control room"]} />
      <Display l1="Control" l2="room" small />
      <div className="split">
        <nav className="sidenav">
          {nav.map(([to, label, Icon]) => (
            <NavLink key={to} to={`/admin${to ? "/" + to : ""}`} end className={({ isActive }) => (isActive ? "active" : "")}><Icon size={16} /> {label}</NavLink>
          ))}
        </nav>
        <div style={{ minWidth: 0 }}>
          <Routes>
            <Route index element={<Overview />} />
            <Route path="library" element={<LibraryFolders />} />
            <Route path="modules" element={<Modules />} />
            <Route path="network" element={<LibraryNetwork />} />
            <Route path="upload" element={<UploadArea />} />
            <Route path="tags" element={<Tags />} />
            <Route path="edits" element={<Edits />} />
            <Route path="hidden" element={<HiddenAndTrash />} />
            <Route path="jobs" element={<Jobs />} />
            <Route path="settings" element={<AdminSettings />} />
            <Route path="users" element={<AdminUsers />} />
            <Route path="artwork" element={<WithoutArtwork />} />
          </Routes>
        </div>
      </div>
    </div>
  );
}
