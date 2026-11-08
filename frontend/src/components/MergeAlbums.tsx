/** Merging albums into one (admin mode): a reissue's bonus disc and the album itself, filed as two,
 * become one album with a disc each, in the first one's folder (backend manage.merge_albums). */

import { useQuery } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, Combine, Plus, Search, X } from "lucide-react";
import { useDeferredValue, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { api, fmtNumber } from "../api";
import { useUi } from "../store/ui";
import type { Album, AlbumDetail, Paged } from "../types";
import { refreshAll, undoEdit } from "./AdminMode";
import { Art, Loading, Modal } from "./ui";

interface Plan {
  folder: string;
  fields: { title: string; artist: string; year: number; genre: string };
  albums: { album_id: number; title: string; artist: string; year: number; folder: string; discs: number[];
            songs: { title: string; disc: number; name: string }[] }[];
  discs: number;
  trashed: string[];
}
type Fields = { title: string; artist: string; year: string; genre: string };

export function MergeAlbums({ id, onClose }: { id: number; onClose: () => void }) {
  const notify = useUi((s) => s.notify);
  const go = useNavigate();
  const where = useLocation().pathname;
  const start = useQuery({ queryKey: ["album", id], queryFn: () => api.get<AlbumDetail>(`/api/albums/${id}`) });
  const [picked, setPicked] = useState<Album[]>([]);         // the others, in disc order after the first
  const [order, setOrder] = useState<number[] | null>(null);  // ids, the first one staying
  const [fields, setFields] = useState<Fields | null>(null);  // the admin's own, once changed
  const [find, setFind] = useState("");
  const [merging, setMerging] = useState(false);
  const [names, setNames] = useState(false);
  const a = start.data;
  const artistId = a?.artist_id;
  const same = useQuery({ queryKey: ["merge-same-artist", artistId], enabled: !!artistId,
                          queryFn: () => api.get<Paged<Album>>("/api/albums", { kind: "music", artist_id: artistId!, sort: "year_asc", limit: 60 }) });
  const term = useDeferredValue(find.trim());
  const found = useQuery({ queryKey: ["merge-search", term], enabled: term.length > 1,
                           queryFn: () => api.get<{ albums: Album[] }>("/api/search", { q: term, limit: 12 }) });
  const all: Album[] = a ? [a, ...picked] : [];
  const ids = order ?? all.map((x) => x.id);
  const byId = new Map(all.map((x) => [x.id, x]));
  const listed = ids.map((i) => byId.get(i)).filter(Boolean) as Album[];
  const sent = useDeferredValue(fields ? { title: fields.title, artist: fields.artist, year: Number(fields.year) || 0, genre: fields.genre } : {});
  const plan = useQuery({ queryKey: ["merge-plan", ids, sent], enabled: ids.length > 1, retry: false,
                          queryFn: () => api.post<Plan>("/api/manage/albums/merge/plan", { ids, fields: sent }) });
  if (!a) return <Modal onClose={onClose}><Loading /></Modal>;
  const shown: Fields = fields ?? (plan.data
    ? { title: plan.data.fields.title, artist: plan.data.fields.artist, year: plan.data.fields.year ? String(plan.data.fields.year) : "", genre: plan.data.fields.genre }
    : { title: a.title, artist: a.artist, year: a.year ? String(a.year) : "", genre: a.genre });
  const set = (k: keyof Fields, v: string) => setFields({ ...shown, [k]: v });
  const add = (x: Album) => {
    if (byId.has(x.id) || x.peer) return;
    setPicked([...picked, x]);
    setOrder([...ids, x.id]);
    setFind("");
  };
  const drop = (i: number) => {
    setPicked(picked.filter((x) => x.id !== i));
    setOrder(ids.filter((x) => x !== i));
  };
  const move = (i: number, by: number) => {
    const n = [...ids];
    const at = n.indexOf(i);
    [n[at], n[at + by]] = [n[at + by], n[at]];
    setOrder(n);
  };
  const candidates = [...(same.data?.items || []), ...(term.length > 1 ? found.data?.albums || [] : [])]
    .filter((x, k, list) => !byId.has(x.id) && !x.peer && x.kind === "music" && list.findIndex((y) => y.id === x.id) === k);
  const discOf = (albumId: number) => plan.data?.albums.find((p) => p.album_id === albumId)?.discs;
  const merge = async () => {
    setMerging(true);
    try {
      const r = await api.post<{ album_id: number; edit_id: number; summary: string }>("/api/manage/albums/merge", { ids, fields: sent });
      notify(`${shown.title}: ${r.summary}`, "info", { label: "Undo", run: () => void undoEdit(r.edit_id) });
      refreshAll();
      onClose();
      if (ids.some((i) => i !== r.album_id && where === `/album/${i}`)) go(`/album/${r.album_id}`, { replace: true });
    } catch (e) {
      notify((e as Error).message, "error");
      setMerging(false);
    }
  };
  return (
    <Modal onClose={onClose} className="merge-albums">
      <div className="kicker">Merge albums</div>
      <h2 className="h2">{a.title}</h2>
      <p className="dim" style={{ margin: "8px 0 16px" }}>
        The albums become one, each one a disc of its own, in the first one's folder. The first album stays: its cover, likes and
        place in the library. What else the others' folders hold (a cover, a text file) goes to the trash. It can be undone.
      </p>

      <div className="merge-list">
        {listed.map((x, k) => (
          <div key={x.id} className={`merge-row ${k === 0 ? "first" : ""}`}>
            <span className="merge-disc">{discOf(x.id)?.length ? `Disc ${discOf(x.id)!.join("–")}` : `#${k + 1}`}</span>
            <Art src={x.art} name={x.title} size={80} className="merge-thumb" />
            <div className="grow" style={{ minWidth: 0 }}>
              <div className="ellipsis"><b>{x.title}</b> <span className="dim">{x.artist}</span></div>
              <div className="faint ellipsis" style={{ fontSize: 12 }}>
                {[x.year || null, `${fmtNumber(x.track_count)} songs`, k === 0 ? "stays" : null].filter(Boolean).join(" · ")}
              </div>
              {plan.data && (() => {
                const f = plan.data.albums.find((p) => p.album_id === x.id)?.folder || "";
                return <div className="faint ellipsis merge-folder" data-tip={f}>…/{f.split("/").pop()}</div>;     // its own folder's name
              })()}
            </div>
            <div className="merge-moves">
              <button className="btn small ghost" aria-label={`Move ${x.title} up`} disabled={k === 0} onClick={() => move(x.id, -1)}><ArrowUp size={14} /></button>
              <button className="btn small ghost" aria-label={`Move ${x.title} down`} disabled={k === listed.length - 1} onClick={() => move(x.id, 1)}><ArrowDown size={14} /></button>
              <button className="btn small ghost" aria-label={`Leave ${x.title} out`} disabled={listed.length < 2}
                      onClick={() => drop(x.id)}><X size={14} /></button>
            </div>
          </div>
        ))}
      </div>

      <div className="merge-add">
        <label className="tag-find">
          <Search size={15} />
          <input className="input" value={find} onChange={(e) => setFind(e.target.value)} placeholder="Find another album…" aria-label="Find an album to merge" />
        </label>
        {candidates.length > 0 && (
          <div className="merge-candidates">
            {candidates.slice(0, 12).map((x) => (
              <button key={x.id} className="merge-candidate" onClick={() => add(x)}>
                <Plus size={14} /><span className="ellipsis"><b>{x.title}</b> <span className="faint">{x.artist}{x.year ? ` · ${x.year}` : ""} · {x.track_count} songs</span></span>
              </button>
            ))}
          </div>
        )}
      </div>

      {listed.length > 1 && <>
        <div className="merge-fields">
          {([["title", "Title"], ["artist", "Album artist"], ["year", "Year"], ["genre", "Genre"]] as [keyof Fields, string][]).map(([k, label]) => (
            <label key={k} className="field">
              <span className="faint">{label}</span>
              <input className="input" value={shown[k]} inputMode={k === "year" ? "numeric" : undefined} onChange={(e) => set(k, e.target.value)} />
            </label>
          ))}
        </div>
        {plan.error ? <p className="merge-error">{(plan.error as Error).message}</p> : plan.data ? (
          <div className="merge-plan">
            <div><span className="faint">Into</span> <span className="mono-path">{plan.data.folder}</span></div>
            <div className="faint">{plan.data.discs} discs, {fmtNumber(plan.data.albums.reduce((n, p) => n + p.songs.length, 0))} songs
              {plan.data.trashed.length > 0 && `; ${plan.data.trashed.length === 1 ? "an emptied folder's" : "emptied folders'"} other files to the trash`}
              {" · "}<button className="linkish" onClick={() => setNames(!names)}>{names ? "Hide the names" : "Show the names"}</button>
            </div>
            {names && (
              <ol className="merge-names">
                {plan.data.albums.flatMap((p) => p.songs).sort((x, y) => x.disc - y.disc).map((s) => <li key={s.name}>{s.name}</li>)}
              </ol>
            )}
          </div>
        ) : <Loading />}
      </>}

      <div className="row-actions" style={{ justifyContent: "flex-end", marginTop: 18 }}>
        <button className="btn" onClick={onClose}>Cancel</button>
        <button className="btn accent" disabled={listed.length < 2 || !plan.data || merging} onClick={merge}>
          <Combine size={15} /> {merging ? "Merging…" : listed.length < 2 ? "Merge" : `Merge ${listed.length} albums`}
        </button>
      </div>
    </Modal>
  );
}
