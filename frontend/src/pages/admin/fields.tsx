/** Pieces the admin pages and the setup share: a setting's field (from the server's schema,
 * settings.py) and the folder picker. */

import { useQuery } from "@tanstack/react-query";
import { BookOpen, Folder, FolderOpen, Gamepad2, Network, Podcast, Radio } from "lucide-react";
import { useState } from "react";
import { api } from "../../api";
import { Modal, Switch } from "../../components/ui";
import type { ModuleKey } from "../../types";

export interface SettingSpec {
  key: string; type: string; default: unknown; group: string; label: string; help: string; choices: string[];
  min: number | null; max: number | null; value: unknown; module: ModuleKey | null;
}

export const MODULE_ICONS: Record<ModuleKey, typeof Folder> = {
  vgm: Gamepad2, audiobooks: BookOpen, podcasts: Podcast, radio: Radio, network: Network,
};

export function FolderBrowser({ onPick, onClose }: { onPick: (p: string) => void; onClose: () => void }) {
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
            <Folder size={16} /> <span className="grow">{f}</span>
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

export function SettingField({ s, value, onChange }: { s: SettingSpec; value: unknown; onChange: (v: unknown) => void }) {
  switch (s.type) {
    case "bool":
      return <Switch checked={!!value} onChange={onChange} label={s.label} />;
    case "int":
    case "float":
      return <input id={s.key} className="input" style={{ maxWidth: 200 }} type="number" min={s.min ?? undefined} max={s.max ?? undefined}
                    step={s.type === "float" ? "0.1" : "1"} value={value as number} onChange={(e) => onChange(Number(e.target.value))} />;
    case "choice":
      return <select id={s.key} className="select" style={{ maxWidth: 320 }} value={String(value)} onChange={(e) => onChange(e.target.value)}>
        {s.choices.map((c) => <option key={c} value={c}>{c}</option>)}
      </select>;
    case "json":
      return <JsonField value={value} onChange={onChange} />;
    case "secret":
      return <input id={s.key} className="input" type="password" autoComplete="off" value={String(value ?? "")} onChange={(e) => onChange(e.target.value)} />;
    default:
      return <input id={s.key} className="input" value={String(value ?? "")} onChange={(e) => onChange(e.target.value)} />;
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
