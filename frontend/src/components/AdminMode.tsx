/** Admin mode: a cog on every library item (albums, songs, artists, books, podcasts, playlists,
 * stations) with Edit metadata, Hide from library and Delete. Deleted files go to a trash on
 * their share; hidden things and the trash are on the admin page. */

import { EyeOff, Pencil, Settings, Trash2 } from "lucide-react";
import { create } from "zustand";
import { queryClient } from "../actions";
import { api } from "../api";
import { useUi } from "../store/ui";
import type { Job } from "../types";
import { EditDialog } from "./EditDialog";
import { Modal, useMenu } from "./ui";

export type ItemKind = "album" | "track" | "artist" | "book" | "podcast" | "playlist" | "fileplaylist" | "station";

const NOUN: Record<ItemKind, string> = {
  album: "album", track: "song", artist: "artist", book: "audiobook", podcast: "podcast", playlist: "playlist",
  fileplaylist: "playlist", station: "station",
};

/** What deleting does to each kind: into the trash (files), or gone. */
const DELETE_SAYS: Record<ItemKind, string> = {
  album: "Its folder moves to the trash on the music share. You can put it back from Admin → Hidden & trash until the trash is emptied.",
  track: "The file moves to the trash on the music share (a chip file takes all its songs with it). You can put it back from Admin → Hidden & trash.",
  artist: "All of the artist's albums and songs move to the trash on the music share. You can put them back from Admin → Hidden & trash.",
  book: "The book's files move to the trash, if Muzix may write to the audiobook folder.",
  fileplaylist: "The playlist file moves to the trash next to it.",
  podcast: "The podcast is removed for everyone, with its downloaded episodes. This can't be undone, but it can be subscribed to again.",
  playlist: "The playlist is removed. This can't be undone.",
  station: "The station is removed from the saved stations. This can't be undone.",
};

/** Puts back what an edit changed: from the message after saving, the edit window or Admin → Edits. */
export async function undoEdit(id: number): Promise<boolean> {
  const notify = useUi.getState().notify;
  try {
    await api.post(`/api/manage/edits/${id}/undo`);
    notify("Undone: everything is as it was before that edit");
    refreshAll();
    return true;
  } catch (e) {
    notify((e as Error).message, "error");
    return false;
  }
}

/** Waits for a background job (an artist's new name takes a while), then hands it over. */
export function whenDone(jobId: number, then: (j: Job) => void) {
  const look = async () => {
    try {
      const j = await api.get<Job>(`/api/admin/jobs/${jobId}`);
      if (j.status !== "queued" && j.status !== "running") return then(j);
    } catch {
      /* a moment without the server: look again */
    }
    window.setTimeout(look, 2000);
  };
  window.setTimeout(look, 1500);
}

interface Target { kind: ItemKind; id: number; title: string }

interface AdminDialogs {
  edit: Target | null;
  confirm: Target | null;
  setEdit: (t: Target | null) => void;
  setConfirm: (t: Target | null) => void;
}

export const useAdminDialogs = create<AdminDialogs>((set) => ({
  edit: null,
  confirm: null,
  setEdit: (edit) => set({ edit }),
  setConfirm: (confirm) => set({ confirm }),
}));

export function useAdminMode() {
  return useUi((s) => s.adminMode && !!s.user?.is_admin);
}

/** Everything shown may have changed. */
export function refreshAll() {
  queryClient.invalidateQueries();
}

async function hide(t: Target) {
  const notify = useUi.getState().notify;
  try {
    await api.post(`/api/manage/${t.kind}/${t.id}/hide`);
    notify(`Hid ${t.title}: it's back with one click under Admin → Hidden & trash`);
    refreshAll();
  } catch (e) {
    notify((e as Error).message, "error");
  }
}

/** The cog: Edit metadata, Hide from library, Delete. Only in admin mode. */
export function AdminCog({ kind, id, title, className = "" }: { kind: ItemKind; id: number; title: string; className?: string }) {
  const on = useAdminMode();
  const showMenu = useMenu((s) => s.show);
  const { setEdit, setConfirm } = useAdminDialogs();
  if (!on) return null;
  const t = { kind, id, title };
  return (
    <button className={`admin-cog ${className}`} aria-label={`Admin: ${title}`} data-tip={`Edit, hide or delete this ${NOUN[kind]}`}
            onClick={(e) => {
              e.preventDefault();
              e.stopPropagation();
              showMenu(e, [
                { heading: title },
                { label: "Edit metadata", icon: <Pencil size={16} />, onClick: () => setEdit(t) },
                { label: "Hide from library", icon: <EyeOff size={16} />, onClick: () => hide(t) },
                { label: "Delete", icon: <Trash2 size={16} />, onClick: () => setConfirm(t) },
              ]);
            }}>
      <Settings size={15} />
    </button>
  );
}

/** The edit window and the delete question, wherever a cog was clicked. */
export function AdminHost() {
  const { edit, confirm, setEdit, setConfirm } = useAdminDialogs();
  return (
    <>
      {edit && <EditDialog kind={edit.kind} id={edit.id} onClose={() => setEdit(null)} />}
      {confirm && <ConfirmDelete t={confirm} onClose={() => setConfirm(null)} />}
    </>
  );
}

function ConfirmDelete({ t, onClose }: { t: Target; onClose: () => void }) {
  const notify = useUi((s) => s.notify);
  const go = async () => {
    onClose();
    try {
      const r = await api.del<{ trash_id?: number; removed?: boolean }>(`/api/manage/${t.kind}/${t.id}`);
      notify(r.trash_id ? `${t.title} is in the trash` : `${t.title} is deleted`);
      refreshAll();
      if (["/album/", "/artist/", "/audiobooks/", "/podcasts/", "/playlist/"].some((p) => location.pathname.startsWith(p))) history.back();
    } catch (e) {
      notify((e as Error).message, "error");
    }
  };
  return (
    <Modal onClose={onClose}>
      <h2 className="h2">Delete {t.title}?</h2>
      <p className="dim" style={{ margin: "10px 0 20px" }}>{DELETE_SAYS[t.kind]}</p>
      <div className="row-actions" style={{ justifyContent: "flex-end" }}>
        <button className="btn" onClick={onClose} autoFocus>Cancel</button>
        <button className="btn danger solid" onClick={go}><Trash2 size={15} /> Delete</button>
      </div>
    </Modal>
  );
}
