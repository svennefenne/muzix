/** Admin → Hidden & trash: what admin mode hid (to show again) and deleted (to put back, or
 * delete for good). */

import { useQuery } from "@tanstack/react-query";
import { Eye, RotateCcw, Trash2 } from "lucide-react";
import { useState } from "react";
import { ago, api, fmtBytes } from "../../api";
import { refreshAll } from "../../components/AdminMode";
import { Empty, Loading, Modal } from "../../components/ui";
import { useUi } from "../../store/ui";

interface Hidden { kind: string; id: number; title: string; subtitle: string }
interface Trashed { id: number; kind: string; title: string; subtitle: string; size: number; files: number; created_at: string | null; where: string }

export function HiddenAndTrash() {
  const notify = useUi((s) => s.notify);
  const hidden = useQuery({ queryKey: ["manage-hidden"], queryFn: () => api.get<Hidden[]>("/api/manage/hidden") });
  const trash = useQuery({ queryKey: ["manage-trash"], queryFn: () => api.get<Trashed[]>("/api/manage/trash") });
  const [forGood, setForGood] = useState<Trashed | "all" | null>(null);
  const run = async (fn: () => Promise<unknown>, said: string) => {
    try {
      await fn();
      notify(said);
      refreshAll();
    } catch (e) {
      notify((e as Error).message, "error");
    }
  };
  const total = (trash.data || []).reduce((s, t) => s + t.size, 0);
  return (
    <>
      <section className="section">
        <h2 className="h2">Hidden</h2>
        <p className="dim">Hidden from every page and list, for everyone. The files stay where they are.</p>
        {hidden.isLoading ? <Loading /> : hidden.data?.length ? (
          <ul className="admin-list">
            {hidden.data.map((h) => (
              <li key={`${h.kind}-${h.id}`}>
                <div className="grow ellipsis"><b>{h.title}</b><span className="faint"> · {h.subtitle}</span></div>
                <button className="btn small" onClick={() => run(() => api.post(`/api/manage/${h.kind}/${h.id}/unhide`), `${h.title} is back`)}>
                  <Eye size={14} /> Show again
                </button>
              </li>
            ))}
          </ul>
        ) : <Empty title="Nothing is hidden" />}
      </section>

      <section className="section">
        <div className="row-actions" style={{ justifyContent: "space-between" }}>
          <h2 className="h2">Trash</h2>
          {!!trash.data?.length && (
            <button className="btn danger" onClick={() => setForGood("all")}><Trash2 size={15} /> Empty the trash ({fmtBytes(total)})</button>
          )}
        </div>
        <p className="dim">Deleted albums, songs and artists wait here, in a .muzix-trash folder on their share, until the trash is emptied.</p>
        {trash.isLoading ? <Loading /> : trash.data?.length ? (
          <ul className="admin-list">
            {trash.data.map((t) => (
              <li key={t.id}>
                <div className="grow" style={{ minWidth: 0 }}>
                  <div className="ellipsis"><b>{t.title}</b><span className="faint"> · {t.kind}{t.subtitle ? ` · ${t.subtitle}` : ""}</span></div>
                  <div className="faint ellipsis" style={{ fontSize: 12 }}>
                    {fmtBytes(t.size)} · {t.files} {t.files === 1 ? "item" : "items"}{t.created_at ? ` · deleted ${ago(t.created_at)}` : ""} · from {t.where}
                  </div>
                </div>
                <button className="btn small" onClick={() => run(() => api.post(`/api/manage/trash/${t.id}/restore`), `${t.title} is back; the folder is being scanned`)}>
                  <RotateCcw size={14} /> Put back
                </button>
                <button className="btn small danger" onClick={() => setForGood(t)}><Trash2 size={14} /> Delete for good</button>
              </li>
            ))}
          </ul>
        ) : <Empty title="The trash is empty" />}
      </section>

      {forGood && (
        <Modal onClose={() => setForGood(null)}>
          <h2 className="h2">{forGood === "all" ? "Empty the trash?" : `Delete ${forGood.title} for good?`}</h2>
          <p className="dim" style={{ margin: "10px 0 20px" }}>
            {forGood === "all" ? `Everything in the trash (${fmtBytes(total)}) is deleted from the disk.` : `Its files (${fmtBytes(forGood.size)}) are deleted from the disk.`} There's no way back.
          </p>
          <div className="row-actions" style={{ justifyContent: "flex-end" }}>
            <button className="btn" onClick={() => setForGood(null)} autoFocus>Cancel</button>
            <button className="btn danger solid" onClick={() => {
              const t = forGood;
              setForGood(null);
              run(() => api.del(t === "all" ? "/api/manage/trash" : `/api/manage/trash/${t.id}`), "Deleted for good");
            }}><Trash2 size={15} /> Delete for good</button>
          </div>
        </Modal>
      )}
    </>
  );
}
