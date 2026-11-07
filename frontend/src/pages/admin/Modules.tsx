/** Admin → Modules: the parts of Muzix this server runs (backend/muzix/modules.py), each turned on
 * or off for everyone, with its own settings and folders. */

import { useQuery } from "@tanstack/react-query";
import { Save } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { queryClient } from "../../actions";
import { api, fmtNumber } from "../../api";
import { Loading, Switch } from "../../components/ui";
import { useUi } from "../../store/ui";
import type { ModuleKey } from "../../types";
import { MODULE_ICONS, SettingField, type SettingSpec } from "./fields";

export interface ModuleInfo { key: ModuleKey; label: string; about: string; kinds: string[]; on: boolean; settings: SettingSpec[] }
interface RootRef { id: number; path: string; kind: string; items: number; exists: boolean }

/** What a module's settings mean together, where one line helps. */
export const MODULE_NOTES: Partial<Record<ModuleKey, string>> = {
  vgm: "Game music usually loops forever. Choose how long looping songs play; new lengths apply to songs rendered from now on (clear the chiptune cache on the overview to redo older ones).",
};

function ModulePanel({ m, roots, reload }: { m: ModuleInfo; roots: RootRef[]; reload: () => void }) {
  const Icon = MODULE_ICONS[m.key];
  const notify = useUi((s) => s.notify);
  const [edits, setEdits] = useState<Record<string, unknown>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const folders = roots.filter((r) => m.kinds.includes(r.kind));
  const dirty = Object.keys(edits).length > 0;

  const turn = async (on: boolean) => {
    if (busy) return;
    setBusy(true);
    try {
      await api.put(`/api/admin/modules/${m.key}`, { on });
      // menus, pages and lists all change with it
      await queryClient.invalidateQueries();
      notify(on ? `${m.label} is on` : `${m.label} is off: hidden, with nothing deleted`);
    } catch (e) {
      notify((e as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };
  const save = async () => {
    setError("");
    try {
      await api.put("/api/admin/settings", edits);
      setEdits({});
      reload();
      notify(`${m.label} settings saved`);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <section className={`panel module-panel ${m.on ? "" : "off"}`} id={m.key}>
      <div className="module-head">
        <Icon size={20} aria-hidden />
        <div className="grow">
          <div className="h3">{m.label}</div>
          <p className="module-about">{m.about}</p>
        </div>
        <Switch checked={m.on} onChange={turn} label={m.label} />
      </div>
      {m.on && (m.kinds.length > 0 || m.settings.length > 0 || m.key === "network") && (
        <div className="module-body">
          {m.kinds.length > 0 && (
            <div className="field">
              <label>Folders</label>
              {folders.length ? (
                <div className="module-folders">
                  {folders.map((r) => (
                    <div key={r.id} className="module-folder">
                      <span className={`status-dot ${r.exists ? "ok" : "bad"}`} data-tip={r.exists ? "Mounted" : "Not found in the container"} />
                      <span className="grow ellipsis mono-path">{r.path}</span>
                      <span className="faint">{fmtNumber(r.items)} {r.kind === "audiobooks" ? "books" : "tracks"}</span>
                    </div>
                  ))}
                </div>
              ) : <div className="help">No folders yet.</div>}
              <div className="help"><Link to="/admin/library">Add or change folders under Library folders</Link></div>
            </div>
          )}
          {MODULE_NOTES[m.key] && <p className="dim module-note">{MODULE_NOTES[m.key]}</p>}
          {m.settings.map((s) => (
            <div key={s.key} className="field">
              <label htmlFor={s.key}>{s.label}</label>
              <SettingField s={s} value={s.key in edits ? edits[s.key] : s.value} onChange={(v) => setEdits({ ...edits, [s.key]: v })} />
              {s.help && <div className="help">{s.help}</div>}
            </div>
          ))}
          {m.key === "network" && <Link className="btn" to="/admin/network">Open Library Network</Link>}
          {dirty && (
            <div className="row-actions">
              <button className="btn accent" onClick={save}><Save size={15} /> Save</button>
              <button className="btn ghost" onClick={() => setEdits({})}>Undo changes</button>
              {error && <span className="error-text">{error}</span>}
            </div>
          )}
        </div>
      )}
    </section>
  );
}

export function Modules() {
  const q = useQuery({ queryKey: ["admin-modules"], queryFn: () => api.get<ModuleInfo[]>("/api/admin/modules") });
  const roots = useQuery({ queryKey: ["roots"], queryFn: () => api.get<RootRef[]>("/api/admin/roots") });
  if (!q.data) return <Loading />;
  return (
    <>
      <p className="lede">
        Music is always on. The rest are on or off for everyone on this server. A module that's off is hidden and its background
        work waits, but nothing in it is deleted: turn it on again and it's all back.
      </p>
      {q.data.map((m) => <ModulePanel key={m.key} m={m} roots={roots.data || []} reload={() => q.refetch()} />)}
    </>
  );
}
