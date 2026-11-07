/** The setup of a new server, right after its admin account (backend/muzix/api/setup.py): the
 * music's folders, what else the server does (the modules), what it's called and where it's
 * reached, then each module's own settings. Nothing is saved until the end; skipping takes the
 * mounted folders with every module on. */

import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight, Copy, FolderOpen, Plus } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { Logo } from "../components/Logo";
import { Display, Kicker, Loading, Switch } from "../components/ui";
import { useUi } from "../store/ui";
import { ThemeApplier } from "../theme/ThemeApplier";
import type { ModuleKey } from "../types";
import { FolderBrowser, MODULE_ICONS, SettingField, type SettingSpec } from "./admin/fields";
import { MODULE_NOTES } from "./admin/Modules";

type Kind = "music" | "vgm" | "audiobooks";
interface SetupModule { key: ModuleKey; label: string; about: string; kinds: Kind[]; suggested: boolean; settings: SettingSpec[]; more: SettingSpec[] }
interface SetupInfo { folders: { path: string; kind: Kind }[]; modules: SetupModule[]; general: SettingSpec[]; metadata: SettingSpec[] }
interface Folder { path: string; kind: Kind; on: boolean }

const KIND_WORD: Record<Kind, string> = { music: "music", vgm: "chiptunes and game music", audiobooks: "audiobooks" };

/** Each step's title, in the display's two tones. */
const TITLES: Record<string, [string, string?]> = {
  music: ["Your", "music"], modules: ["What else", "it plays"], server: ["This", "server"],
  vgm: ["VGM"], audiobooks: ["Audio", "books"], podcasts: ["Podcasts"], radio: ["Radio"], spotify: ["Spotify"],
  network: ["Library", "Network"], done: ["Ready", "to play"],
};
const NAMES: Record<string, string> = { music: "Music", modules: "Modules", server: "This server", done: "Done" };

function Field({ s, value, onChange }: { s: SettingSpec; value: unknown; onChange: (v: unknown) => void }) {
  return (
    <div className="field">
      <label htmlFor={s.key}>{s.label}</label>
      <SettingField s={s} value={value} onChange={onChange} />
      {s.help && <div className="help">{s.help}</div>}
    </div>
  );
}

/** The folders of one kind: the ones offered (on or off) and a way to add another. */
function Folders({ kind, folders, setFolders }: { kind: Kind; folders: Folder[]; setFolders: (f: Folder[]) => void }) {
  const [path, setPath] = useState("");
  const [browsing, setBrowsing] = useState(false);
  const [error, setError] = useState("");
  const mine = folders.filter((f) => f.kind === kind);
  const add = async (p: string) => {
    setError("");
    const clean = p.trim();
    if (!clean) return;
    try {
      const found = await api.get<{ path: string }>("/api/admin/browse", { path: clean });
      const there = folders.find((f) => f.path === found.path);
      setFolders(there ? folders.map((f) => (f === there ? { ...f, kind, on: true } : f)) : [...folders, { path: found.path, kind, on: true }]);
      setPath("");
    } catch {
      setError(`${clean} isn't a folder inside the container. Map the share in the container's settings first (e.g. /mnt/user/media → /music).`);
    }
  };
  return (
    <div className="setup-folders">
      {mine.length > 0 ? (
        <div className="setup-folder-list">
          {mine.map((f) => (
            <div key={f.path} className={`setup-folder ${f.on ? "" : "off"}`}>
              <span className="grow mono-path">{f.path}</span>
              <Switch checked={f.on} label={`Scan ${f.path}`} onChange={(on) => setFolders(folders.map((x) => (x === f ? { ...x, on } : x)))} />
            </div>
          ))}
        </div>
      ) : <p className="help">No {KIND_WORD[kind]} folders yet: add one below.</p>}
      <div className="setup-add">
        <input className="input" placeholder={kind === "music" ? "/music" : `/${kind}`} value={path} aria-label={`A folder with ${KIND_WORD[kind]}`}
               onChange={(e) => setPath(e.target.value)} onKeyDown={(e) => e.key === "Enter" && add(path)} />
        <button className="btn" onClick={() => setBrowsing(true)}><FolderOpen size={15} /> Browse</button>
        <button className="btn" disabled={!path.trim()} onClick={() => add(path)}><Plus size={15} /> Add</button>
      </div>
      {error && <p className="error-text">{error}</p>}
      {browsing && <FolderBrowser onClose={() => setBrowsing(false)} onPick={(p) => { setBrowsing(false); add(p); }} />}
    </div>
  );
}

function CopyLine({ text }: { text: string }) {
  const notify = useUi((s) => s.notify);
  return (
    <div className="setup-copy">
      <code className="grow">{text}</code>
      <button className="btn small" onClick={() => navigator.clipboard?.writeText(text).then(() => notify("Copied"), () => notify("Couldn't copy here: select it and copy", "error"))}>
        <Copy size={14} /> Copy
      </button>
    </div>
  );
}

export default function Setup({ onDone }: { onDone: () => void }) {
  const info = useQuery({ queryKey: ["setup"], queryFn: () => api.get<SetupInfo>("/api/setup"), staleTime: Infinity });
  if (!info.data) return <div className="auth"><ThemeApplier /><Loading /></div>;
  return <Wizard info={info.data} onDone={onDone} />;
}

function Wizard({ info, onDone }: { info: SetupInfo; onDone: () => void }) {
  const siteName = useUi((s) => s.siteName);
  const [folders, setFolders] = useState<Folder[]>(() => info.folders.map((f) => ({ ...f, on: true })));
  const [on, setOn] = useState<Record<ModuleKey, boolean>>(
    () => Object.fromEntries(info.modules.map((m) => [m.key, m.suggested])) as Record<ModuleKey, boolean>);
  const [values, setValues] = useState<Record<string, unknown>>(() => {
    const v: Record<string, unknown> = {};
    for (const s of [...info.general, ...info.metadata, ...info.modules.flatMap((m) => [...m.settings, ...m.more])]) v[s.key] = s.value;
    // the address this page came from is the likely public one, if it's HTTPS
    if (!v.public_url && location.protocol === "https:") v.public_url = location.origin;
    return v;
  });
  const [share, setShare] = useState(true);
  const [step, go] = useState(0);
  const [reached, setReached] = useState(0);         // the furthest step: any up to it can be gone back to
  const setStep = (i: number) => {
    go(i);
    setReached((r) => Math.max(r, i));
  };
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [code, setCode] = useState<string | null>(null);

  useEffect(() => {
    window.scrollTo({ top: 0 });     // (newer browsers return a promise, which isn't a clean-up)
  }, [step]);
  const steps = useMemo(() => ["music", "modules", "server", ...info.modules.filter((m) => on[m.key]).map((m) => m.key), "done"],
    [info.modules, on]);
  // turning a module off takes its step away: the furthest step can't be past the end
  const last = steps.length - 1;
  const key = steps[Math.min(step, last)];
  const mod = info.modules.find((m) => m.key === key);
  const set = (k: string) => (v: unknown) => setValues({ ...values, [k]: v });
  const field = (s: SettingSpec) => <Field key={s.key} s={s} value={values[s.key]} onChange={set(s.key)} />;
  const publicUrl = String(values.public_url || "").replace(/\/+$/, "");

  const chosen = folders.filter((f) => f.on && (f.kind === "music" || on[f.kind as ModuleKey]));
  const finish = async () => {
    setBusy(true);
    setError("");
    try {
      // only what this setup asks: a module's settings when it's on
      const asked = [...info.general, ...info.metadata, ...info.modules.filter((m) => on[m.key]).flatMap((m) => [...m.settings, ...m.more])];
      const r = await api.post<{ code: string | null }>("/api/setup/finish", {
        folders: chosen.map(({ path, kind }) => ({ path, kind })), modules: on, share,
        settings: Object.fromEntries(asked.map((s) => [s.key, values[s.key]])),
      });
      if (r.code && on.network && share) setCode(r.code);
      else onDone();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const skip = async () => {
    setBusy(true);
    try {
      await api.post("/api/setup/skip");
      onDone();
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  };

  if (code) {
    return (
      <div className="auth setup">
        <ThemeApplier />
        <div className="setup-card setup-solo">
          <div className="logo setup-logo"><Logo name={siteName} /></div>
          <Kicker parts={["Setup", "Done"]} />
          <Display l1="Ready" l2="to play" small />
          <p className="lede">The first scan has started. To link with a friend's Muzix, give them this server's share code and its address; they give you theirs, under Admin → Library Network.</p>
          <div className="share-code setup-code">{code}</div>
          {publicUrl && <CopyLine text={publicUrl} />}
          <div className="setup-actions"><span /><button className="btn primary" onClick={onDone}>Open Muzix <ArrowRight size={15} /></button></div>
        </div>
      </div>
    );
  }

  const title = TITLES[key] || [mod?.label || key];
  return (
    <div className="auth setup">
      <ThemeApplier />
      <div className="setup-card">
        <div className="logo setup-logo"><Logo name={siteName} /></div>
        <nav className="setup-steps" aria-label="Setup steps">
          {steps.map((s, i) => (
            <button key={s} className={i === step ? "on" : i <= reached ? "done" : ""} disabled={i > reached} aria-current={i === step ? "step" : undefined}
                    onClick={() => setStep(i)}>
              {NAMES[s] || info.modules.find((m) => m.key === s)?.label}
            </button>
          ))}
        </nav>
        <div className="setup-main">
          <Kicker parts={["Setup", `Step ${Math.min(step, last) + 1} of ${steps.length}`]} />
          <Display l1={title[0]} l2={title[1]} small />

          {key === "music" && (
            <>
              <p className="lede">The folders your music is in. They're paths inside the container: the ones it mounts are already here.</p>
              <Folders kind="music" folders={folders} setFolders={setFolders} />
              <details className="setup-more">
                <summary>Genres, pictures and lyrics <span className="faint">optional</span></summary>
                <p>Where Muzix looks things up for your music. All of it works without keys; each key adds a source.</p>
                {info.metadata.map(field)}
              </details>
            </>
          )}

          {key === "modules" && (
            <>
              <p className="lede">Music is always on. Choose what else this server does; you can change it any time under Admin → Modules.</p>
              <div className="setup-modules">
                {info.modules.map((m) => {
                  const Icon = MODULE_ICONS[m.key];
                  return (
                    <div key={m.key} className={`setup-module ${on[m.key] ? "on" : ""}`}>
                      <Icon size={20} aria-hidden />
                      <span className="grow"><b>{m.label}</b><span className="module-about">{m.about}</span></span>
                      <Switch checked={on[m.key]} label={m.label} onChange={(v) => setOn({ ...on, [m.key]: v })} />
                    </div>
                  );
                })}
              </div>
            </>
          )}

          {key === "server" && (
            <>
              <p className="lede">What it's called, and the address people reach it at.</p>
              {info.general.map(field)}
            </>
          )}

          {mod && (
            <>
              <p className="lede">{mod.about}</p>
              {mod.kinds.map((k) => <Folders key={k} kind={k} folders={folders} setFolders={setFolders} />)}
              {MODULE_NOTES[mod.key] && <p className="dim setup-note">{MODULE_NOTES[mod.key]}</p>}
              {mod.settings.map(field)}
              {mod.key === "spotify" && (
                <div className="field">
                  <label>Redirect URI</label>
                  {publicUrl ? <CopyLine text={`${publicUrl}/api/spotify/callback`} />
                    : <div className="help">Set the public URL under This server first: Spotify needs Muzix's HTTPS address.</div>}
                  <div className="help">Create an app at developer.spotify.com, add this redirect URI to it, and paste its Client ID above.</div>
                </div>
              )}
              {mod.key === "network" && (
                <div className="field">
                  <label>Open for linking</label>
                  <div className="row-actions"><Switch checked={share} label="Open for linking" onChange={setShare} />
                    <span className="dim">{share ? "This server gets a share code to give to friends" : "Turn it on later under Admin → Library Network"}</span></div>
                  {!publicUrl && <div className="help">Linked servers reach this one at its public URL: set it under This server.</div>}
                </div>
              )}
              {mod.more.length > 0 && (
                <details className="setup-more">
                  <summary>More settings</summary>
                  {mod.more.map(field)}
                </details>
              )}
            </>
          )}

          {key === "done" && (
            <>
              <p className="lede">Muzix scans these folders as soon as you start it. Everything here can be changed later under Admin.</p>
              <dl className="setup-summary">
                <dt>Folders</dt>
                <dd>{chosen.length ? chosen.map((f) => <div key={f.path} className="mono-path">{f.path} <span className="faint">{KIND_WORD[f.kind]}</span></div>) : <span className="dim">None: the library starts empty. Add folders later under Admin → Library folders, or go back to the first step.</span>}</dd>
                <dt>Modules</dt>
                <dd>{info.modules.filter((m) => on[m.key]).map((m) => m.label).join(", ") || "Music only"}</dd>
                <dt>Name</dt>
                <dd>{String(values.site_name || "Muzix")}{publicUrl && <span className="faint"> · {publicUrl}</span>}</dd>
              </dl>
            </>
          )}

          {error && <p className="error-text">{error}</p>}
          <div className="setup-actions">
            {step > 0 ? <button className="btn ghost" onClick={() => setStep(step - 1)}><ArrowLeft size={15} /> Back</button>
              : <button className="btn ghost" disabled={busy} onClick={skip} data-tip="The mounted folders, with every module on">Skip setup</button>}
            {key === "done" ? <button className="btn primary" disabled={busy} onClick={finish}>{busy ? "Starting…" : "Start Muzix"}</button>
              : <button className="btn primary" onClick={() => setStep(step + 1)}>Next <ArrowRight size={15} /></button>}
          </div>
        </div>
      </div>
    </div>
  );
}
