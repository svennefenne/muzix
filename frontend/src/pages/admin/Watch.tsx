/** Admin → Upload → Watch folder (backend watch.py): albums put in a folder, on this server or on a computer whose
 * Muzix Desktop lets this server pick one there, are filed into the library by themselves. */

import { useQuery } from "@tanstack/react-query";
import { ChevronDown, Folder, FolderOpen, Laptop, MoreHorizontal, Plus, Send, Server } from "lucide-react";
import { useState } from "react";
import { ago, api } from "../../api";
import { Segmented } from "../../components/Browse";
import { Modal, useMenu } from "../../components/ui";
import { useUi } from "../../store/ui";

/** One watch folder: where, how its albums are matched, how it stands, its albums set aside and why. */
interface Folder {
  key: string;                           // which one, for the calls about it
  folder: string;
  computer: string;                      // "" when the folder is on this server
  only: Only;                            // "bandcamp": its albums matched with Bandcamp alone
  reachable: boolean;
  state: { checked: number; error: string; waiting: string[] };
  held: { _Duplicates: string[]; _Failed: string[] };
  why: Record<string, Why>;              // each album in _Duplicates: why it was set aside
  trash: "trash" | "deleted";            // what throwing one away does: the computer's trash, or (on the server) deletes it
}

interface Watched {
  folders: Folder[];
  computers: { id: string; name: string; online: boolean }[];
  recent: {
    id: number; name: string; key: string; status: string; error: string; match: string; duplicate: boolean; removed: boolean;
    replaced: number; aside: number; albums: { artist: string; album: string; songs: number; match: string }[]; finished_at: string | null;
  }[];
}

type Only = "" | "bandcamp";

const MATCHING: { value: Only; label: string }[] = [{ value: "", label: "MusicBrainz, then Bandcamp" }, { value: "bandcamp", label: "Bandcamp only" }];

interface Why {
  songs: number;                          // of how many (0: set aside before this was kept)
  found: { song: string; why: string; title: string; artist: string; album: string; format: string; folder: string }[];
  replaces: string[];                     // the library's albums filing it in their place puts aside
}

type How = "album" | "replace" | "duplicates";

const MATCHED: Record<string, string> = { musicbrainz: "Matched on MusicBrainz", bandcamp: "Matched on Bandcamp",
                                          none: "No match: filed as its tags say, worth a look in admin mode" };

/** "19 albums: 15 matched on MusicBrainz, 4 filed as their tags say", for a folder of albums. */
function matched(albums: Watched["recent"][number]["albums"], match: string) {
  if (albums.length < 2) return MATCHED[match] ?? "Filed";
  const n = (m: string) => albums.filter((a) => a.match === m).length;
  const parts = [n("musicbrainz") && `${n("musicbrainz")} matched on MusicBrainz`, n("bandcamp") && `${n("bandcamp")} on Bandcamp`,
                 n("none") && `${n("none")} filed as their tags say`].filter(Boolean);
  return `${albums.length} albums${parts.length ? `: ${parts.join(", ")}` : ""}`;
}

export function WatchFolder() {
  const notify = useUi((s) => s.notify);
  const q = useQuery({ queryKey: ["watch"], queryFn: () => api.get<Watched>("/api/admin/watch"), refetchInterval: 10_000 });
  const [picking, setPicking] = useState<{ at: number; only: Only; computer: string } | null>(null);
  const w = q.data;
  if (!w) return null;
  const set = async (at: number, folder: string, computer: string, only: Only) => {
    try {
      await api.put("/api/admin/watch", { folder, computer, only, at });
      setPicking(null);
      q.refetch();
    } catch (e) {
      notify((e as Error).message, "error");
    }
  };
  const folders = w.folders.length ? w.folders : [null];
  const bandcampOnly = w.folders.some((f) => f.only === "bandcamp");

  return (
    <>
      {folders.map((f, at) => (
        <WatchCard key={f?.key ?? "none"} f={f} at={at} computers={w.computers} refetch={() => q.refetch()}
                   onPick={() => setPicking({ at, only: f?.only ?? "", computer: f?.computer ?? "" })}
                   onSet={(folder, computer, only) => set(at, folder, computer, only)} />
      ))}
      {w.folders.length > 0 && (
        <div className="row-actions watch-more">
          <button className="btn ghost" onClick={() => setPicking({ at: w.folders.length, only: bandcampOnly ? "" : "bandcamp", computer: w.folders[0].computer })}>
            <Plus size={15} /> Another watch folder
          </button>
        </div>
      )}
      {w.recent.length > 0 && (
        <section className="panel watch">
          <details className="watch-recent" open>
            <summary className="dim">Lately from the watch folder{w.folders.length > 1 ? "s" : ""}</summary>
            <div className="list">
              {w.recent.map((r) => {
                const busy = r.status === "queued" || r.status === "running";
                const text = busy ? "Being filed…" : r.status === "failed" ? r.error || "Couldn't be filed"
                  : r.duplicate ? "Set aside as a duplicate"
                  : [matched(r.albums, r.match), r.replaced && "the library's copy put aside in Duplicates",
                     r.aside && `${r.aside} the library has set aside in _Duplicates`,
                     r.removed && "deleted from the computer"].filter(Boolean).join(" · ");
                return (
                  <div key={r.id} className="list-row">
                    <span className={`status-dot ${busy ? "queued" : r.status === "failed" ? "bad" : r.match === "none" || r.match === "mixed" || r.duplicate ? "" : "ok"}`} />
                    <div className="grow">
                      <div className="ellipsis">{r.albums.length === 1 ? `${r.albums[0].artist} – ${r.albums[0].album}` : r.name}</div>
                      <div className={r.status === "failed" ? "error-text" : "dim"}>{text}{r.finished_at && !busy ? ` · ${ago(r.finished_at)}` : ""}</div>
                    </div>
                  </div>
                );
              })}
            </div>
          </details>
        </section>
      )}
      {picking && <WatchPicker computers={w.computers} start={picking.computer} only={picking.only} adding={picking.at >= w.folders.length && w.folders.length > 0}
                               onPick={(folder, computer, only) => set(picking.at, folder, computer, only)} onClose={() => setPicking(null)} />}
    </>
  );
}

/** One watch folder (none yet: how to set one): where it is, how its albums are matched, how it stands, and its
 * albums set aside, with what can be done with them. */
function WatchCard({ f, at, computers, refetch, onPick, onSet }: {
  f: Folder | null; at: number; computers: Watched["computers"]; refetch: () => void;
  onPick: () => void; onSet: (folder: string, computer: string, only: Only) => void;
}) {
  const notify = useUi((s) => s.notify);
  const [sending, setSending] = useState(false);
  const computer = f ? computers.find((c) => c.id === f.computer) : undefined;
  const key = f?.key ?? "";
  const again = async (name: string, held: "_Duplicates" | "_Failed", how?: How) => {
    try {
      await api.post("/api/admin/watch/again", { name, held, key, ...(how ? { how } : {}) });
      notify(`${name}: being filed`);
      refetch();
    } catch (e) {
      notify((e as Error).message, "error");
    }
  };
  const throwAway = async (name: string) => {
    const where = computer ? `${computer.name}'s trash` : "";
    if (!confirm(where ? `Move "${name}" to ${where}?` : `Delete "${name}" from the watch folder? It can't be undone.`)) return;
    try {
      await api.post("/api/admin/watch/remove", { name, held: "_Duplicates", key });
      notify(where ? `${name}: in ${where}` : `${name}: deleted`);
      refetch();
    } catch (e) {
      notify((e as Error).message, "error");
    }
  };
  const transferNow = async () => {
    setSending(true);
    try {
      const got = await api.post<{ taken: string[]; waiting: string[] }>("/api/admin/watch/now", { key });
      const n = got.taken.length;
      notify(n ? `${n} album${n > 1 ? "s" : ""} being filed${got.waiting.length ? `; still coming in: ${got.waiting.join(", ")}` : ""}`
        : got.waiting.length ? `Still coming in: ${got.waiting.join(", ")}` : "Nothing waiting in the watch folder");
      refetch();
    } catch (e) {
      notify((e as Error).message, "error");
    } finally {
      setSending(false);
    }
  };
  const looked = !f ? "" : !f.reachable
    ? (computer ? `${computer.name} isn't connected (Muzix Desktop isn't running, or isn't sharing): the folder is looked at again when it is`
                : "The folder can't be reached")
    : f.state.error ? `Couldn't look in it: ${f.state.error}`
    : f.state.checked ? `Looked in ${ago(new Date(f.state.checked * 1000).toISOString())}` : "Looked in every minute";
  const bandcamp = f?.only === "bandcamp";

  return (
    <section className="panel watch">
      <div className="panel-head">
        <div>
          <div className="kicker">Watch folder{bandcamp ? " · Bandcamp only" : ""}</div>
          <div className="h3">{f ? "Albums put here are filed by themselves" : "Fill the library from a folder"}</div>
        </div>
        <div className="row-actions">
          {f?.reachable && (
            <button className="btn accent" onClick={transferNow} disabled={sending}
                    data-tip="Take what's in the folder now, without waiting two minutes (an album still being copied in waits)">
              <Send size={15} /> {sending ? "Looking…" : "Transfer now"}
            </button>
          )}
          <button className="btn" onClick={onPick}><FolderOpen size={15} /> {f ? "Another folder" : "Choose a folder"}</button>
          {f && <button className="btn ghost" onClick={() => onSet("", "", "")}>Turn off</button>}
        </div>
      </div>
      {f && (
        <div className="watch-where">
          {computer ? <Laptop size={18} /> : <Server size={18} />}
          <div className="grow">
            <div className="mono watch-path">{f.folder}{computer && <span className="dim"> on {computer.name}</span>}</div>
            <div className={!f.reachable || f.state.error ? "error-text" : "dim"}>{looked}</div>
            {f.state.waiting.length > 0 && <div className="dim">Coming in: {f.state.waiting.join(", ")}</div>}
          </div>
          <Segmented label="Matched with" value={f.only} options={MATCHING} onChange={(v) => v !== f.only && onSet(f.folder, f.computer, v as Only)} />
        </div>
      )}
      {at === 0 && (
        <p className="dim watch-about">
          Each album is looked up on MusicBrainz, where a release counts when its songs are as many and as long; when none does, on
          Bandcamp (in a folder set to Bandcamp only, on Bandcamp alone). Its main genre goes by Bandcamp's genre and tags too, and
          the artist's genre tags are Bandcamp's when MusicBrainz has none. It gets cover art, and is filed as Genre/Artist/Artist -
          Year - Album, as uploads are. An album is taken two minutes after its last file arrived, or at once with Transfer now. An
          album at least half of whose songs the library seems to have already goes to _Duplicates (of a folder of albums, an
          artist's say, each album by itself: those the library has go to _Duplicates under the folder's name, the rest are filed),
          and one that couldn't be filed to _Failed.{computer
            ? ` On ${computer.name}, an album is deleted once the library has every song of it; one that isn't all filed goes to _Done.`
            : " What's left of an album (covers, .cue, .log) goes to _Done."} A folder on a computer: in Muzix Desktop there,
          Settings → Servers → "May pick a folder here to watch" (0.4.24 and later for more than one).
        </p>
      )}
      {f && (f.held._Duplicates.length > 0 || f.held._Failed.length > 0) && (
        <div className="list watch-held">
          {f.held._Duplicates.map((name) => (
            <Duplicate key={`d-${name}`} name={name} why={f.why[name]} trash={f.trash} computer={computer?.name}
                       onFile={(how) => again(name, "_Duplicates", how)} onThrowAway={() => throwAway(name)} />
          ))}
          {f.held._Failed.map((name) => (
            <div key={`f-${name}`} className="list-row">
              <span className="status-dot bad" />
              <div className="grow"><div className="ellipsis">{name}</div><div className="dim">In _Failed: it couldn't be filed</div></div>
              <button className="btn small" onClick={() => again(name, "_Failed")}>Try again</button>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

/** An album in _Duplicates: why it was set aside (its songs the library seems to have, and where), filed anyway
 * as an album of its own, in place of the library's copy or beside it in the Duplicates folder, or thrown away. */
function Duplicate({ name, why, trash, computer, onFile, onThrowAway }: {
  name: string; why?: Why; trash: Folder["trash"]; computer?: string; onFile: (how: How) => void; onThrowAway: () => void;
}) {
  const show = useMenu((s) => s.show);
  const [open, setOpen] = useState(false);
  const found = why?.found ?? [];
  const summary = !why ? "In _Duplicates: the library seems to have it already"
    : `${found.length}${why.songs ? ` of its ${why.songs}` : ""} song${(why.songs || found.length) === 1 ? "" : "s"} seem${found.length === 1 ? "s" : ""} to be in the library already`;
  const replaces = why?.replaces ?? [];
  const base = (f: string) => f.split("/").pop() || f;
  const menu = (e: { clientX: number; clientY: number }) => show(e, [
    { label: "File as an album of its own", note: "Into the library as any album", onClick: () => onFile("album") },
    replaces.length
      ? { label: "In place of the library's copy", note: `${replaces.map(base).join(", ")} to the library's Duplicates folder`,
          onClick: () => confirm(`Put ${replaces.map(base).join(", ")} aside in the library's Duplicates folder, and file "${name}" in its place?`) && onFile("replace") }
      : { label: "In place of the library's copy", disabled: true, note: why ? "No album in the library has most of its songs" : "Set aside before Muzix kept why" },
    { label: "Beside the library's copy", note: "Into the library's Duplicates folder, as (2)", onClick: () => onFile("duplicates") },
    { sep: true },
    { label: "Throw away", note: trash === "trash" ? `To ${computer ?? "the computer"}'s trash` : "Deleted from the watch folder", onClick: onThrowAway },
  ]);
  return (
    <div className="list-row watch-dup">
      <div className="watch-dup-head">
        <span className="status-dot queued" />
        <div className="grow">
          <div className="ellipsis">{name}</div>
          <button className="dim watch-why" onClick={() => setOpen(!open)} aria-expanded={open} disabled={!found.length}>
            {summary}{found.length > 0 && <ChevronDown size={14} className={open ? "flip" : ""} />}
          </button>
        </div>
        <button className="btn small" onClick={() => onFile("album")}>File as an album</button>
        <button className="btn small ghost" aria-label="More" onClick={menu}><MoreHorizontal size={16} /></button>
      </div>
      {open && (
        <ul className="watch-found">
          {found.map((f, i) => (
            <li key={i}>
              <span className="ellipsis">{f.song}</span>
              <span className="dim">
                {f.why === "library" ? "the very same file" : f.why === "uploaded" ? "uploaded before" : f.why === "waiting" ? "waiting in the upload area" : "like"}
                {f.title && ` "${f.title}"${f.artist ? ` by ${f.artist}` : ""}${f.album ? ` on ${f.album}` : ""}${f.format ? ` (${f.format.toUpperCase()})` : ""}`}
                {f.folder && <span className="mono"> · {f.folder}</span>}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** The folder to watch: on this server, or on a computer that's on and lets this server pick one. */
function WatchPicker({ computers, start, only: startOnly, adding, onPick, onClose }: {
  computers: Watched["computers"]; start: string; only: Only; adding: boolean;
  onPick: (folder: string, computer: string, only: Only) => void; onClose: () => void;
}) {
  const [on, setOn] = useState(start);
  const [only, setOnly] = useState<Only>(startOnly);
  const [path, setPath] = useState("");
  const q = useQuery({
    queryKey: ["watch-browse", on, path], retry: false,
    queryFn: () => api.get<{ path: string; parent: string | null; folders: string[] }>("/api/admin/watch/browse", { computer: on, path }),
  });
  const places = [{ value: "", label: "This server" }, ...computers.map((c) => ({ value: c.id, label: c.online ? c.name : `${c.name} (off)` }))];
  const name = computers.find((c) => c.id === on)?.name;
  const here = q.data?.path ?? path;
  return (
    <Modal onClose={onClose}>
      <div className="kicker">{adding ? "Another watch folder" : "Watch folder"}</div>
      {places.length > 1 && <Segmented label="Where" value={on} options={places} onChange={(v) => { setOn(v); setPath(""); }} />}
      <Segmented label="Matched with" value={only} options={MATCHING} onChange={(v) => setOnly(v as Only)} />
      <div className="h2" style={{ margin: "12px 0 10px", wordBreak: "break-all" }}>{here || "…"}</div>
      {q.isError ? (
        <p className="error-text" style={{ marginBottom: 14 }}>
          {(q.error as Error).message}
          {name && <span className="dim"> Muzix Desktop on {name} has to be running, sharing, and allow it.</span>}
        </p>
      ) : (
        <div className="list" style={{ maxHeight: 360, overflow: "auto", marginBottom: 14 }}>
          {q.data?.parent && <button className="list-row" onClick={() => setPath(q.data!.parent!)}><FolderOpen size={16} /> ..</button>}
          {q.data?.folders.map((f) => (
            <button key={f} className="list-row" style={{ textAlign: "left", cursor: "pointer" }}
                    onClick={() => setPath(`${here.replace(/[/\\]$/, "")}${here.includes("\\") ? "\\" : "/"}${f}`)}>
              <Folder size={16} /> <span className="grow">{f}</span>
            </button>
          ))}
        </div>
      )}
      <div className="row-actions" style={{ justifyContent: "flex-end" }}>
        <button className="btn ghost" onClick={onClose}>Cancel</button>
        <button className="btn accent" disabled={!q.data} onClick={() => onPick(here, on, only)}>Watch this folder</button>
      </div>
    </Modal>
  );
}
