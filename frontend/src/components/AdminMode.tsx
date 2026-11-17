/** Admin mode: a cog on every library item (albums, songs, artists, books, podcasts, playlists,
 * stations) with Edit metadata, Hide from library and Delete (and an artist's or album's Edit tags, an album's Merge, type and genre,
 * a book's Mark as not started). Deleted files go to a trash on
 * their share; hidden things and the trash are on the admin page. */

import { Check, Combine, Disc3, EyeOff, Guitar, ListMusic, Pencil, RotateCcw, Settings, Tags, Trash2 } from "lucide-react";
import { create } from "zustand";
import { queryClient } from "../actions";
import { api } from "../api";
import { useShell } from "../player/app";
import { useUi } from "../store/ui";
import type { Job } from "../types";
import { EditDialog } from "./EditDialog";
import { MergeAlbums } from "./MergeAlbums";
import { TagEditor } from "./TagEditor";
import { Modal, useMenu } from "./ui";

export type ItemKind = "album" | "track" | "artist" | "book" | "podcast" | "playlist" | "fileplaylist" | "station";

const NOUN: Record<ItemKind, string> = {
  album: "album", track: "song", artist: "artist", book: "audiobook", podcast: "podcast", playlist: "playlist",
  fileplaylist: "playlist", station: "station",
};

/** What deleting does to each kind: into the trash (files), or gone. */
export const DELETE_SAYS: Record<ItemKind, string> = {
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
  tags: number | null;                  // the artist whose tags are edited
  albumTags: number | null;             // the album whose tags are edited (its own, for it alone)
  merge: number | null;                 // the album others are merged into
  setEdit: (t: Target | null) => void;
  setConfirm: (t: Target | null) => void;
  setTags: (artist: number | null) => void;
  setAlbumTags: (album: number | null) => void;
  setMerge: (album: number | null) => void;
}

export const useAdminDialogs = create<AdminDialogs>((set) => ({
  edit: null,
  confirm: null,
  tags: null,
  albumTags: null,
  merge: null,
  setEdit: (edit) => set({ edit }),
  setConfirm: (confirm) => set({ confirm }),
  setTags: (tags) => set({ tags }),
  setAlbumTags: (albumTags) => set({ albumTags }),
  setMerge: (merge) => set({ merge }),
}));

/** On for an admin who turned it on, on the server's music: the apps' own library has nothing to edit. */
export function useAdminMode() {
  const on = useUi((s) => s.adminMode && !!s.user?.is_admin);
  const local = useShell((s) => s.library === "local");
  return on && !local;
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
export function AdminCog({ kind, id, title, className = "", peer }: {
  kind: ItemKind; id: number; title: string; className?: string; peer?: string | null;    // another server's: only hidden here
}) {
  const on = useAdminMode();
  const showMenu = useMenu((s) => s.show);
  const { setEdit, setConfirm, setTags, setAlbumTags, setMerge } = useAdminDialogs();
  if (!on) return null;
  const t = { kind, id, title };
  return (
    <button className={`admin-cog ${className}`} aria-label={`Admin: ${title}`}
            data-tip={peer ? `Hide this ${NOUN[kind]}` : `Edit, hide or delete this ${NOUN[kind]}`}
            onClick={(e) => {
              e.preventDefault();
              e.stopPropagation();
              const at = { clientX: e.clientX, clientY: e.clientY, target: e.currentTarget };
              // your own listening, for a book of any library's
              const listening = kind === "book" ? [{ label: "Mark as not started", icon: <RotateCcw size={16} />, onClick: () => void notStarted(t) }] : [];
              showMenu(e, peer ? [
                { heading: title },
                ...listening,
                { label: "Hide from library", icon: <EyeOff size={16} />, onClick: () => hide(t) },
                { sep: true },
                { heading: `In ${peer}'s library: its admin edits it` },
              ] : [
                { heading: title },
                { label: "Edit metadata", icon: <Pencil size={16} />, onClick: () => setEdit(t) },
                ...(kind === "artist" ? [{ label: "Edit tags", icon: <Tags size={16} />, onClick: () => setTags(id) }] : []),
                ...(kind === "album" ? [{ label: "Edit tags", icon: <Tags size={16} />, onClick: () => setAlbumTags(id) }] : []),
                ...(kind === "album" ? [{ label: "Merge with another album", icon: <Combine size={16} />, onClick: () => setMerge(id) }] : []),
                // album, EP or single: a second menu, where the cog was clicked
                ...(kind === "album" ? [{ label: "Change type", icon: <Disc3 size={16} />, onClick: () => showMenu(at, [
                  { heading: "Change type" },
                  // "As tagged": the admin's choice taken back, the type the tags (or the guess) give
                  ...([["album", "Album"], ["ep", "EP"], ["single", "Single"], ["", "As tagged"]] as const)
                    .map(([type, label]) => ({ label, icon: <Disc3 size={16} />, onClick: () => void setRelease(id, type) })),
                ]) }] : []),
                ...(kind === "album" ? [{ label: "Change genre", icon: <Guitar size={16} />, onClick: () => void pickGenre(at, t, () => setEdit(t)) }] : []),
                ...(kind === "album" ? [{ label: "Make compilation", icon: <ListMusic size={16} />, onClick: () => void makeCompilation(id) }] : []),
                ...listening,
                { label: "Hide from library", icon: <EyeOff size={16} />, onClick: () => hide(t) },
                { label: "Delete", icon: <Trash2 size={16} />, onClick: () => setConfirm(t) },
              ]);
            }}>
      <Settings size={15} />
    </button>
  );
}

/** A book back to not started for you: where you were and that you'd finished it are forgotten (backend api/books.py). */
async function notStarted(t: Target) {
  const notify = useUi.getState().notify;
  try {
    await api.del(`/api/books/${t.id}/progress`);
    queryClient.invalidateQueries({ queryKey: ["book", t.id] });
    queryClient.invalidateQueries({ queryKey: ["books"] });
    notify(`${t.title}: not started`);
  } catch (e) {
    notify((e as Error).message, "error");
  }
}

/** An admin's choice of an album's type, over its tags' and the guess (backend/muzix/releases.py); "": theirs again. */
async function setRelease(id: number, type: "" | "album" | "ep" | "single") {
  const notify = useUi.getState().notify;
  try {
    await api.put(`/api/manage/album/${id}/release`, { type });
    queryClient.invalidateQueries();
    notify(type ? `Marked as ${({ album: "an album", ep: "an EP", single: "a single" })[type]}` : "Its type as tagged");
  } catch (e) {
    notify((e as Error).message, "error");
  }
}

interface GenreChoices { genres: string[]; now: string | null; genre: string; stays: string | null }
interface Edited { written: number; moved_to?: string | null; notes?: string[]; edit_id?: number | null }

/** Change genre: a second menu, where the cog was clicked, of the library's genre folders (backend
 * manage.genre_choices). One picked tags the album's songs so and files it in that folder; "Other genre…"
 * is the edit window, for a genre tag of one's own. */
async function pickGenre(at: { clientX: number; clientY: number; target?: EventTarget | null }, t: Target, other: () => void) {
  const notify = useUi.getState().notify;
  let c: GenreChoices;
  try {
    c = await api.get<GenreChoices>(`/api/manage/album/${t.id}/genres`);
  } catch (e) {
    notify((e as Error).message, "error");
    return;
  }
  useMenu.getState().show(at, [
    { heading: c.stays ? `Change genre (it stays in ${c.stays})` : "Change genre" },
    ...c.genres.map((g) => ({ label: g, icon: g === c.now ? <Check size={16} /> : <Guitar size={16} />,
                              onClick: () => void changeGenre(t, g) })),
    ...(c.genres.length ? [{ sep: true }] : []),
    { label: "Other genre…", icon: <Pencil size={16} />, onClick: other },
  ]);
}

async function changeGenre(t: Target, genre: string) {
  const notify = useUi.getState().notify;
  try {
    const r = await api.put<Edited>(`/api/manage/album/${t.id}/genre`, { genre });
    refreshAll();
    if (!r.written && !r.moved_to) {
      notify(`${t.title} is ${genre} already`);
      return;
    }
    const where = r.moved_to?.split("/").slice(-3);
    // the genre folder has an album of that name already (the first disc of a double album, say): it got "[2]"
    const twin = where && / \[\d+\]$/.test(where[2]) ? ". An album of that name is there already: Merge with another album makes them one" : "";
    notify([where ? `${t.title} is ${genre} now, filed in ${where.join(" / ")}${twin}`
            : `${t.title} is ${genre} now: ${r.written} song${r.written === 1 ? "" : "s"} tagged`,
            ...(r.notes || [])].join(". "), "info", r.edit_id ? { label: "Undo", run: () => void undoEdit(r.edit_id!) } : undefined);
  } catch (e) {
    notify((e as Error).message, "error");
  }
}

/** The album made a compilation: by Various Artists, its files' album artist so and filed under it
 * (<Genre>/Various Artists/), as editing its artist does; its songs keep theirs. Undone as any edit. */
async function makeCompilation(id: number) {
  const notify = useUi.getState().notify;
  try {
    const r = await api.put<{ written: number; moved_to?: string | null; notes?: string[]; edit_id?: number | null }>(
      `/api/manage/album/${id}`, { fields: { artist: "Various Artists" }, tracks: [] });
    refreshAll();
    if (!r.written && !r.moved_to && !r.edit_id) {
      notify("It's by Various Artists already");
      return;
    }
    notify([r.moved_to ? `A compilation now, filed in ${r.moved_to.split("/").slice(-3).join(" / ")}` : "A compilation now, by Various Artists",
            ...(r.notes || [])].join(". "), "info", r.edit_id ? { label: "Undo", run: () => void undoEdit(r.edit_id!) } : undefined);
  } catch (e) {
    notify((e as Error).message, "error");
  }
}

/** The edit window and the delete question, wherever a cog was clicked. */
export function AdminHost() {
  const { edit, confirm, tags, albumTags, merge, setEdit, setConfirm, setTags, setAlbumTags, setMerge } = useAdminDialogs();
  return (
    <>
      {edit && <EditDialog kind={edit.kind} id={edit.id} onClose={() => setEdit(null)} />}
      {tags !== null && <TagEditor id={tags} onClose={() => setTags(null)} />}
      {albumTags !== null && <TagEditor kind="album" id={albumTags} onClose={() => setAlbumTags(null)} />}
      {merge !== null && <MergeAlbums id={merge} onClose={() => setMerge(null)} />}
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
