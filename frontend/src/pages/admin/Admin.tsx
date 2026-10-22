import { useQuery } from "@tanstack/react-query";
import { Activity, Folder, FolderOpen, HardDrive, Library, Plus, RefreshCw, Save, Settings2, Trash2, Upload, Users, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { NavLink, Route, Routes, useLocation } from "react-router-dom";
import { ago, api, fmtBytes, fmtNumber } from "../../api";
import { queryClient } from "../../actions";
import { Display, Empty, Kicker, Loading, Modal, Switch } from "../../components/ui";
import { useUi } from "../../store/ui";
import type { Job } from "../../types";
import { SchemePicker } from "../Settings";

interface Root { id: number; path: string; kind: string; name: string; enabled: boolean; upload_target: boolean; excludes: string[]; items: number; exists: boolean; writable: boolean; last_scan: string | null }
interface Status { version: string; tools: Record<string, boolean>; counts: Record<string, number>; cache_bytes: number; art_bytes: number; data_dir: string; data_free_bytes: number }
interface SettingSpec { key: string; type: string; default: unknown; group: string; label: string; help: string; choices: string[]; min: number | null; max: number | null; value: unknown }

const TOOL_INFO: Record<string, string> = {
  ffmpeg: "Transcoding and FLAC encoding", ffprobe: "Chapters and lengths", libopenmpt: "Tracker modules (MOD/XM/IT/S3M/MT2)",
  libgme: "NES, Game Boy, SNES, Sega, PC Engine…", sidplayfp: "Commodore 64 SID", fluidsynth: "MIDI", ymtool: "Atari ST YM",
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
      </div>
      <section className="panel">
        <div className="panel-head"><div className="h3">Quick actions</div></div>
        <div className="row-actions">
          <button className="btn accent" onClick={() => run("/api/admin/scan", {}, "Scanning for new and changed files")}><RefreshCw size={15} /> Scan library</button>
          <button className="btn" onClick={() => run("/api/admin/scan", { full: true }, "Full rescan started")}>Full rescan</button>
          <button className="btn" onClick={() => run("/api/admin/jobs/scan_books", undefined, "Scanning audiobooks")}>Scan audiobooks</button>
          <button className="btn" onClick={() => run("/api/admin/jobs/artist_tags", undefined, "Fetching artist genres")}>Fetch artist genres</button>
          <button className="btn" onClick={() => run("/api/admin/jobs/refresh_feeds", undefined, "Refreshing podcasts")}>Refresh podcasts</button>
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
          <div className="list-row"><HardDrive size={16} /><div className="grow">Rendered chiptune cache</div><b>{fmtBytes(s.cache_bytes)}</b>
            <button className="btn small ghost" onClick={async () => { await api.post("/api/admin/cache/clear?what=render"); st.refetch(); }}>Clear</button></div>
          <div className="list-row"><HardDrive size={16} /><div className="grow">Cover art cache</div><b>{fmtBytes(s.art_bytes)}</b>
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

function FolderBrowser({ onPick, onClose }: { onPick: (p: string) => void; onClose: () => void }) {
  const [path, setPath] = useState("/");
  const q = useQuery({ queryKey: ["browse", path], queryFn: () => api.get<{ path: string; parent: string | null; folders: string[] }>("/api/admin/browse", { path }) });
  return (
    <Modal onClose={onClose}>
      <div className="kicker">Inside the container</div>
      <div className="h2" style={{ marginBottom: 10, wordBreak: "break-all" }}>{path}</div>
      <div className="list" style={{ maxHeight: 360, overflow: "auto", marginBottom: 14 }}>
        {q.data?.parent && <button className="list-row" onClick={() => setPath(q.data!.parent!)}><FolderOpen size={16} /> ..</button>}
        {q.data?.folders.map((f) => (
          <button key={f} className="list-row" style={{ textAlign: "left", cursor: "pointer" }} onClick={() => setPath(`${path.replace(/\/$/, "")}/${f}`)}>
            <Folder size={16} /> {f}
          </button>
        ))}
      </div>
      <div className="row-actions" style={{ justifyContent: "flex-end" }}>
        <button className="btn ghost" onClick={onClose}>Cancel</button>
        <button className="btn accent" onClick={() => onPick(path)}>Use this folder</button>
      </div>
    </Modal>
  );
}

function RootRow({ r, reload }: { r: Root; reload: () => void }) {
  const [excl, setExcl] = useState(r.excludes.join(", "));
  const save = async (patch: Partial<Root>) => {
    await api.put(`/api/admin/roots/${r.id}`, { ...r, ...patch });
    reload();
  };
  return (
    <div className="list-row" style={{ display: "block" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <span className={`status-dot ${r.exists ? "ok" : "bad"}`} title={r.exists ? "Mounted" : "Not found in the container"} />
        <div className="grow" style={{ minWidth: 220 }}>
          <div style={{ fontWeight: 700, wordBreak: "break-all" }}>{r.path}</div>
          <div className="dim" style={{ fontSize: 12.5 }}>
            {fmtNumber(r.items)} {r.kind === "audiobooks" ? "books" : "tracks"} · scanned {r.last_scan ? ago(r.last_scan) : "never"}
            {r.exists && !r.writable && " · read-only"}
          </div>
        </div>
        <select className="select" style={{ width: 140 }} value={r.kind} onChange={(e) => save({ kind: e.target.value })}>
          <option value="music">Music</option><option value="vgm">VGM</option><option value="audiobooks">Audiobooks</option>
        </select>
        <label className="row-actions dim" style={{ gap: 6 }} title="New uploads of this kind go here">
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
            <option value="music">Music</option><option value="vgm">VGM / chiptunes</option><option value="audiobooks">Audiobooks</option>
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
interface Batch { batch: string; files: { path: string; size: number; kind: string }[]; created: string; job: { id: number; status: string; progress: number; message: string } | null }

async function entriesToFiles(items: DataTransferItemList): Promise<Pending[]> {
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
  const entries = Array.from(items).map((i) => i.webkitGetAsEntry()).filter((e): e is FileSystemEntry => !!e);
  for (const e of entries) await walk(e);
  return out;
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

function UploadArea() {
  const [over, setOver] = useState(false);
  const [progress, setProgress] = useState<{ done: number; total: number; files: number } | null>(null);
  const batches = useQuery({ queryKey: ["batches"], queryFn: () => api.get<Batch[]>("/api/upload/batches"), refetchInterval: 3000 });
  const notify = useUi((s) => s.notify);
  const fileInput = useRef<HTMLInputElement>(null);
  const dirInput = useRef<HTMLInputElement>(null);

  const upload = async (files: Pending[]) => {
    const audioish = files.filter((f) => !f.path.split("/").some((p) => p.startsWith(".")));
    if (!audioish.length) return;
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
      batches.refetch();
    }
  };

  return (
    <>
      <section className="panel">
        <div className="panel-head"><div><div className="kicker">Upload</div><div className="h3">Add music to the library</div></div></div>
        <div className={`dropzone ${over ? "over" : ""}`}
             onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
             onDrop={async (e) => { e.preventDefault(); setOver(false); upload(await entriesToFiles(e.dataTransfer.items)); }}
             onClick={() => fileInput.current?.click()}>
          <Upload size={34} />
          <div className="h3">Drop files or whole folders here</div>
          <div className="dim" style={{ maxWidth: 520 }}>
            Music is matched with MusicBrainz, gets cover art and a main genre, and is filed as Genre/Artist/Artist - Year - Album
            in the music upload folder. Chiptunes and tracker modules go to the VGM upload folder.
          </div>
          <div className="row-actions" onClick={(e) => e.stopPropagation()}>
            <button className="btn" onClick={() => fileInput.current?.click()}>Choose files</button>
            <button className="btn" onClick={() => dirInput.current?.click()}>Choose a folder</button>
          </div>
          {progress && (
            <div style={{ width: "100%", maxWidth: 420 }}>
              <div className="progressbar"><div style={{ width: `${(progress.done / progress.total) * 100}%` }} /></div>
              <div className="dim" style={{ fontSize: 12, marginTop: 6 }}>{progress.files} files · {fmtBytes(progress.done)} of {fmtBytes(progress.total)}</div>
            </div>
          )}
        </div>
        <input ref={fileInput} type="file" multiple hidden onChange={(e) => upload(Array.from(e.target.files || []).map((f) => ({ file: f, path: f.name })))} />
        <input ref={dirInput} type="file" hidden {...{ webkitdirectory: "", directory: "" }}
               onChange={(e) => upload(Array.from(e.target.files || []).map((f) => ({ file: f, path: f.webkitRelativePath || f.name })))} />
      </section>
      <section className="panel">
        <div className="panel-head"><div className="h3">Waiting to be imported</div></div>
        {batches.data?.length ? (
          <div className="list">
            {batches.data.map((b) => {
              const music = b.files.filter((f) => f.kind === "native" || f.kind === "decode").length;
              const chips = b.files.filter((f) => !["native", "decode", "other"].includes(f.kind)).length;
              const running = b.job && (b.job.status === "running" || b.job.status === "queued");
              return (
                <div key={b.batch} className="list-row" style={{ display: "block" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
                    <div className="grow">
                      <b>{b.files.length} files</b> <span className="dim">· {music} music · {chips} chiptune/tracker · uploaded {ago(b.created)}</span>
                      {b.job && <div className="dim" style={{ fontSize: 12.5 }}>Import {b.job.status}{b.job.message ? `: ${b.job.message}` : ""}</div>}
                    </div>
                    {running ? <div style={{ width: 160 }}><div className="progressbar"><div style={{ width: `${(b.job!.progress || 0) * 100}%` }} /></div></div>
                      : <button className="btn accent" onClick={async () => { await api.post(`/api/upload/batch/${b.batch}/import`); batches.refetch(); }}>Import</button>}
                    <button className="mini" aria-label="Discard" onClick={async () => {
                      if (!confirm("Discard these uploaded files?")) return;
                      await api.del(`/api/upload/batch/${b.batch}`);
                      batches.refetch();
                    }}><X size={15} /></button>
                  </div>
                  <details style={{ marginTop: 8 }}>
                    <summary className="dim" style={{ cursor: "pointer", fontSize: 12.5 }}>Files</summary>
                    <pre className="log">{b.files.map((f) => `${f.path}  (${fmtBytes(f.size)})`).join("\n")}</pre>
                  </details>
                  {b.job && <JobRow j={{ id: b.job.id, type: "import_upload", title: "Import log", status: b.job.status as Job["status"], progress: b.job.progress, message: b.job.message, result: {}, created_at: null, started_at: null, finished_at: null }} />}
                </div>
              );
            })}
          </div>
        ) : <Empty title="Nothing waiting">Uploaded files show up here until you import them.</Empty>}
      </section>
    </>
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

function SettingField({ s, value, onChange }: { s: SettingSpec; value: unknown; onChange: (v: unknown) => void }) {
  const dark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  if (s.key === "default_scheme") return <SchemePicker value={String(value)} onChange={onChange} dark={dark} />;
  switch (s.type) {
    case "bool":
      return <Switch checked={!!value} onChange={onChange} label={s.label} />;
    case "int":
    case "float":
      return <input className="input" style={{ maxWidth: 200 }} type="number" min={s.min ?? undefined} max={s.max ?? undefined}
                    step={s.type === "float" ? "0.1" : "1"} value={value as number} onChange={(e) => onChange(Number(e.target.value))} />;
    case "choice":
      return <select className="select" style={{ maxWidth: 320 }} value={String(value)} onChange={(e) => onChange(e.target.value)}>
        {s.choices.map((c) => <option key={c} value={c}>{c}</option>)}
      </select>;
    case "json":
      return <JsonField value={value} onChange={onChange} />;
    case "secret":
      return <input className="input" type="password" autoComplete="off" value={String(value ?? "")} onChange={(e) => onChange(e.target.value)} />;
    default:
      return <input className="input" value={String(value ?? "")} onChange={(e) => onChange(e.target.value)} />;
  }
}

function JsonField({ value, onChange }: { value: unknown; onChange: (v: unknown) => void }) {
  const [text, setText] = useState(JSON.stringify(value ?? {}, null, 2));
  const [bad, setBad] = useState(false);
  return (
    <>
      <textarea className="input" value={text} onChange={(e) => {
        setText(e.target.value);
        try { onChange(JSON.parse(e.target.value)); setBad(false); } catch { setBad(true); }
      }} />
      {bad && <span className="error-text">Not valid JSON yet</span>}
    </>
  );
}

function AdminSettings() {
  const q = useQuery({ queryKey: ["admin-settings"], queryFn: () => api.get<SettingSpec[]>("/api/admin/settings") });
  const [edits, setEdits] = useState<Record<string, unknown>>({});
  const [error, setError] = useState("");
  const notify = useUi((s) => s.notify);
  const loc = useLocation();
  const groups = useMemo(() => {
    const g: Record<string, SettingSpec[]> = {};
    for (const s of q.data || []) (g[s.group] ||= []).push(s);
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
          {group === "Chiptunes" && <p className="dim" style={{ marginTop: 0 }}>Game music usually loops forever. Choose how long looping songs play; the new lengths apply to songs rendered from now on (clear the chiptune cache on the overview to redo older ones).</p>}
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

// ---------------------------------------------------------------- users

function AdminUsers() {
  const me = useUi((s) => s.user);
  const q = useQuery({ queryKey: ["users"], queryFn: () => api.get<{ id: number; username: string; is_admin: boolean; created_at: string }[]>("/api/admin/users") });
  const [form, setForm] = useState({ username: "", password: "", is_admin: false });
  const [err, setErr] = useState("");
  const add = async () => {
    setErr("");
    try {
      await api.post("/api/admin/users", form);
      setForm({ username: "", password: "", is_admin: false });
      q.refetch();
    } catch (e) {
      setErr((e as Error).message);
    }
  };
  return (
    <>
      <section className="panel">
        <div className="panel-head"><div className="h3">Add a user</div></div>
        <div className="row-actions">
          <input className="input" style={{ maxWidth: 200 }} placeholder="Username" value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} />
          <input className="input" style={{ maxWidth: 220 }} type="password" placeholder="Password (6+)" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
          <label className="row-actions dim" style={{ gap: 6 }}><Switch checked={form.is_admin} onChange={(v) => setForm({ ...form, is_admin: v })} /> Admin</label>
          <button className="btn accent" onClick={add}><Plus size={15} /> Add</button>
        </div>
        {err && <p className="error-text">{err}</p>}
      </section>
      <section className="panel">
        <div className="panel-head"><div className="h3">Users</div></div>
        <div className="list">
          {(q.data || []).map((u) => (
            <div key={u.id} className="list-row">
              <span className="avatar">{u.username[0].toUpperCase()}</span>
              <div className="grow"><b>{u.username}</b><div className="dim" style={{ fontSize: 12 }}>since {new Date(u.created_at).toLocaleDateString()}</div></div>
              <label className="row-actions dim" style={{ gap: 6 }}>
                <Switch checked={u.is_admin} onChange={async (v) => { await api.put(`/api/admin/users/${u.id}`, { username: u.username, is_admin: v }); q.refetch(); }} /> Admin
              </label>
              <button className="btn small" onClick={async () => {
                const pw = prompt(`New password for ${u.username} (6+ characters)`);
                if (pw) { await api.put(`/api/admin/users/${u.id}`, { username: u.username, is_admin: u.is_admin, password: pw }); }
              }}>Reset password</button>
              {u.id !== me?.id && <button className="mini" aria-label="Delete" onClick={async () => {
                if (confirm(`Delete ${u.username}?`)) { await api.del(`/api/admin/users/${u.id}`); q.refetch(); }
              }}><Trash2 size={15} /></button>}
            </div>
          ))}
        </div>
      </section>
    </>
  );
}

export default function Admin() {
  const user = useUi((s) => s.user);
  if (!user?.is_admin) return <div className="page"><Empty title="Admins only" /></div>;
  const nav = [["", "Overview", Activity], ["library", "Library folders", Library], ["upload", "Upload", Upload],
    ["jobs", "Jobs", RefreshCw], ["settings", "Settings", Settings2], ["users", "Users", Users]] as const;
  return (
    <div className="page wide">
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
            <Route path="upload" element={<UploadArea />} />
            <Route path="jobs" element={<Jobs />} />
            <Route path="settings" element={<AdminSettings />} />
            <Route path="users" element={<AdminUsers />} />
          </Routes>
        </div>
      </div>
    </div>
  );
}
