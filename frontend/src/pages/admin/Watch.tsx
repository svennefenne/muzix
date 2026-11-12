/** Admin → Upload → Watch folder (backend watch.py): albums put in a folder, on this server or on a computer whose
 * Muzix Desktop lets this server pick one there, are filed into the library by themselves. */

import { useQuery } from "@tanstack/react-query";
import { Folder, FolderOpen, Laptop, Server } from "lucide-react";
import { useState } from "react";
import { ago, api } from "../../api";
import { Segmented } from "../../components/Browse";
import { Modal } from "../../components/ui";
import { useUi } from "../../store/ui";

interface Watched {
  folder: string;
  computer: string;                      // "" when the folder is on this server
  computers: { id: string; name: string; online: boolean }[];
  reachable: boolean;
  state: { checked: number; error: string; waiting: string[] };
  held: { _Duplicates: string[]; _Failed: string[] };
  recent: {
    id: number; name: string; status: string; error: string; match: string; duplicate: boolean;
    albums: { artist: string; album: string; songs: number; match: string }[]; finished_at: string | null;
  }[];
}

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
  const [picking, setPicking] = useState(false);
  const w = q.data;
  if (!w) return null;
  const computer = w.computers.find((c) => c.id === w.computer);
  const set = async (folder: string, on: string) => {
    try {
      await api.put("/api/admin/watch", { folder, computer: on });
      setPicking(false);
      q.refetch();
    } catch (e) {
      notify((e as Error).message, "error");
    }
  };
  const again = async (name: string, held: "_Duplicates" | "_Failed") => {
    try {
      await api.post("/api/admin/watch/again", { name, held });
      notify(`${name}: being filed`);
      q.refetch();
    } catch (e) {
      notify((e as Error).message, "error");
    }
  };
  const looked = !w.reachable
    ? (computer ? `${computer.name} isn't connected (Muzix Desktop isn't running, or isn't sharing): the folder is looked at again when it is`
                : "The folder can't be reached")
    : w.state.error ? `Couldn't look in it: ${w.state.error}`
    : w.state.checked ? `Looked in ${ago(new Date(w.state.checked * 1000).toISOString())}` : "Looked in every minute";

  return (
    <section className="panel watch">
      <div className="panel-head">
        <div><div className="kicker">Watch folder</div><div className="h3">{w.folder ? "Albums put here are filed by themselves" : "Fill the library from a folder"}</div></div>
        <div className="row-actions">
          <button className="btn" onClick={() => setPicking(true)}><FolderOpen size={15} /> {w.folder ? "Another folder" : "Choose a folder"}</button>
          {w.folder && <button className="btn ghost" onClick={() => set("", "")}>Turn off</button>}
        </div>
      </div>
      {w.folder && (
        <div className="watch-where">
          {computer ? <Laptop size={18} /> : <Server size={18} />}
          <div className="grow">
            <div className="mono watch-path">{w.folder}{computer && <span className="dim"> on {computer.name}</span>}</div>
            <div className={!w.reachable || w.state.error ? "error-text" : "dim"}>{looked}</div>
            {w.state.waiting.length > 0 && <div className="dim">Coming in: {w.state.waiting.join(", ")}</div>}
          </div>
        </div>
      )}
      <p className="dim watch-about">
        Each album is looked up on MusicBrainz, where a release counts when its songs are as many and as long; when none does, on
        Bandcamp. It gets a main genre and cover art, and is filed as Genre/Artist/Artist - Year - Album, as uploads are. An album is
        taken two minutes after its last file arrived. What isn't music goes to _Done, albums the library seems to have to
        _Duplicates, and ones that couldn't be filed to _Failed: nothing is deleted.{computer && ` The files on ${computer.name} go to
        _Done once the library has them.`} A folder on a computer: in Muzix Desktop there, Settings → Servers → "May pick a folder
        here to watch".
      </p>
      {(w.held._Duplicates.length > 0 || w.held._Failed.length > 0) && (
        <div className="list watch-held">
          {w.held._Duplicates.map((name) => (
            <div key={`d-${name}`} className="list-row">
              <span className="status-dot queued" />
              <div className="grow"><div className="ellipsis">{name}</div><div className="dim">In _Duplicates: the library seems to have it already. Filed anyway, it goes to the library's Duplicates folder</div></div>
              <button className="btn small" onClick={() => again(name, "_Duplicates")}>File anyway</button>
            </div>
          ))}
          {w.held._Failed.map((name) => (
            <div key={`f-${name}`} className="list-row">
              <span className="status-dot bad" />
              <div className="grow"><div className="ellipsis">{name}</div><div className="dim">In _Failed: it couldn't be filed</div></div>
              <button className="btn small" onClick={() => again(name, "_Failed")}>Try again</button>
            </div>
          ))}
        </div>
      )}
      {w.recent.length > 0 && (
        <details className="watch-recent" open>
          <summary className="dim">Lately from the watch folder</summary>
          <div className="list">
            {w.recent.map((r) => {
              const busy = r.status === "queued" || r.status === "running";
              const text = busy ? "Being filed…" : r.status === "failed" ? r.error || "Couldn't be filed"
                : r.duplicate ? "Set aside as a duplicate" : matched(r.albums, r.match);
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
      )}
      {picking && <WatchPicker computers={w.computers} start={w.computer} onPick={set} onClose={() => setPicking(false)} />}
    </section>
  );
}

/** The folder to watch: on this server, or on a computer that's on and lets this server pick one. */
function WatchPicker({ computers, start, onPick, onClose }: {
  computers: Watched["computers"]; start: string; onPick: (folder: string, computer: string) => void; onClose: () => void;
}) {
  const [on, setOn] = useState(start);
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
      <div className="kicker">Watch folder</div>
      {places.length > 1 && <Segmented label="Where" value={on} options={places} onChange={(v) => { setOn(v); setPath(""); }} />}
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
        <button className="btn accent" disabled={!q.data} onClick={() => onPick(here, on)}>Watch this folder</button>
      </div>
    </Modal>
  );
}
