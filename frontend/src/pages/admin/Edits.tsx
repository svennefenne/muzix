/** Admin → Edits: what admin mode's edit window changed, newest first, each to undo. */

import { useQuery } from "@tanstack/react-query";
import { RotateCcw } from "lucide-react";
import { useState } from "react";
import { ago, api } from "../../api";
import { undoEdit } from "../../components/AdminMode";
import { Empty, Loading } from "../../components/ui";

interface Edit {
  id: number; kind: string; item_id: number; title: string; summary: string; created_at: string | null; undone_at: string | null;
}

const NOUN: Record<string, string> = {
  album: "album", track: "song", artist: "artist", book: "audiobook", podcast: "podcast", playlist: "playlist",
  fileplaylist: "playlist file", station: "station",
};

export function Edits() {
  const edits = useQuery({ queryKey: ["manage-edits"], queryFn: () => api.get<Edit[]>("/api/manage/edits") });
  const [busy, setBusy] = useState(0);
  return (
    <section className="section">
      <h2 className="h2">Edits</h2>
      <p className="dim">
        Everything saved in admin mode's edit window, newest first. Undo puts the tags, file names, folders and covers back
        as they were, as long as nothing has changed them since; when something has, undo the later edit first.
      </p>
      {edits.isLoading ? <Loading /> : edits.data?.length ? (
        <ul className="admin-list">
          {edits.data.map((e) => (
            <li key={e.id} className={e.undone_at ? "undone" : ""}>
              <div className="grow" style={{ minWidth: 0 }}>
                <div className="ellipsis"><b>{e.title}</b><span className="faint"> · {NOUN[e.kind] || e.kind}</span></div>
                <div className="faint ellipsis" style={{ fontSize: 12 }}>
                  {e.summary}{e.created_at ? ` · ${ago(e.created_at)}` : ""}{e.undone_at ? ` · undone ${ago(e.undone_at)}` : ""}
                </div>
              </div>
              {!e.undone_at && (
                <button className="btn small" disabled={!!busy} onClick={async () => {
                  setBusy(e.id);
                  await undoEdit(e.id);
                  setBusy(0);
                }}><RotateCcw size={14} className={busy === e.id ? "spin" : ""} /> Undo</button>
              )}
            </li>
          ))}
        </ul>
      ) : <Empty title="Nothing has been edited yet" />}
    </section>
  );
}
