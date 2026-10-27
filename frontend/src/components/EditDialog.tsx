/** The admin's edit window: an item's metadata (an album with its songs), what MusicBrainz,
 * Discogs, Deezer, iTunes and Spotify know about it, and its cover. An album or artist picked from
 * a source brings that source's cover or picture, saved with the rest; otherwise covers come from
 * the sources, fanart.tv, a web image search, a picture's address or a file, and are saved at once. */

import { useQuery } from "@tanstack/react-query";
import { ExternalLink, ImagePlus, Loader2, RotateCcw, Search, Upload } from "lucide-react";
import { type FormEvent, useEffect, useState } from "react";
import { ago, api, fmtTime } from "../api";
import { useUi } from "../store/ui";
import type { Job } from "../types";
import { type ItemKind, refreshAll, undoEdit, whenDone } from "./AdminMode";
import { Modal } from "./ui";

interface TrackEdit { id: number; title: string; artist: string; track_no: number; disc_no: number; duration?: number }
type Details = { kind: ItemKind; id: number; tracks?: TrackEdit[]; art?: string | null; image?: string; favicon?: string;
  tags?: "files" | "muzix"; writable?: boolean; files?: string; album_id?: number | null; duration?: number;
  last_edit?: { id: number; summary: string; created_at: string } | null } & Record<string, unknown>;
interface Match {
  source: string; id: string; title: string; artist?: string; album?: string; year?: number; tracks?: number;
  cover?: string | null; url?: string; country?: string; label?: string; format?: string; genre?: string;
  no?: number; disc?: number; length?: number;
}
interface Found<T> { results: T[]; errors: Record<string, string> }
interface Cover { source: string; thumb: string; url: string; title: string; width?: number; height?: number }
interface Song { disc: number; no: number; title: string; artist: string; length?: number }
interface AlbumDetails { title: string; artist: string; year: number; genre: string; cover?: string | null; tracks: Song[] }
interface ArtistDetails { name: string; cover?: string | null }
interface Namesake { id: number; name: string; albums: number }
interface Renamed {
  songs?: number; albums?: number; folders?: string[]; failed?: string[]; merged?: boolean; edit_id?: number | null;
  artist_id?: number; picture?: boolean;
}
type Pairing = { song: Song; how: "length" | "number" | "order" } | undefined;
interface Picked { url: string; thumb: string; source: string }
type Form = Record<string, string | number>;

const FIELDS: Record<ItemKind, [string, string, "text" | "number" | "area"][]> = {
  album: [["title", "Title", "text"], ["artist", "Album artist", "text"], ["year", "Year", "number"], ["genre", "Genre", "text"]],
  track: [["title", "Title", "text"], ["artist", "Artist", "text"], ["albumartist", "Album artist", "text"], ["album", "Album", "text"],
    ["track_no", "Track", "number"], ["disc_no", "Disc", "number"], ["year", "Year", "number"], ["genre", "Genre", "text"]],
  artist: [["name", "Name", "text"]],
  book: [["title", "Title", "text"], ["author", "Author", "text"], ["narrator", "Narrator", "text"], ["series", "Series", "text"],
    ["year", "Year", "number"], ["description", "Description", "area"]],
  podcast: [["title", "Title", "text"], ["author", "Author", "text"], ["description", "Description", "area"]],
  playlist: [["name", "Name", "text"], ["description", "Description", "area"]],
  fileplaylist: [["name", "Name", "text"]],
  station: [["name", "Name", "text"]],
};
const NOUN: Record<ItemKind, string> = {
  album: "album", track: "song", artist: "artist", book: "audiobook", podcast: "podcast", playlist: "playlist",
  fileplaylist: "playlist", station: "station",
};
const LOOKUP: Partial<Record<ItemKind, "album" | "track" | "artist">> = { album: "album", track: "track", artist: "artist" };
const SOURCE: Record<string, string> = { musicbrainz: "MusicBrainz", discogs: "Discogs", deezer: "Deezer", itunes: "iTunes",
  spotify: "Spotify", fanarttv: "fanart.tv", web: "Web search" };
const ORDER = ["musicbrainz", "discogs", "spotify", "deezer", "itunes"];     // the fullest metadata first
const SHOWN = 8;

/** A picture that steps aside when it can't load (a release without cover art). */
function Thumb({ src }: { src?: string | null }) {
  const [failed, setFailed] = useState(false);
  return src && !failed ? <img src={src} alt="" loading="lazy" referrerPolicy="no-referrer" onError={() => setFailed(true)} />
    : <span className="edit-nocover" />;
}

/** Close enough in length to be the same recording: 3 s, or 2.5% of a long one. */
const sameLength = (a: number, b: number) => Math.abs(a - b) <= Math.max(3, b * 0.025);

/** Each file to the source's song of the same length, the closest pairs first; the numbers only
 * break near ties. Without lengths to go by: disc and number, and file order only when the counts
 * agree and nothing else matched. A file whose length no song has keeps its own tags. */
function pair(files: TrackEdit[], songs: Song[]): Pairing[] {
  const out: Pairing[] = files.map(() => undefined);
  const used = new Set<number>();
  const timed = songs.some((s) => s.length);
  const close: [number, number, number][] = [];
  files.forEach((f, i) => songs.forEach((s, j) => {
    if (f.duration && s.length && sameLength(f.duration, s.length)) {
      const sameNo = f.track_no === s.no && (f.disc_no || 1) === (s.disc || 1);
      close.push([Math.abs(f.duration - s.length) + (sameNo ? 0 : 0.5), i, j]);
    }
  }));
  close.sort((a, b) => a[0] - b[0]);
  for (const [, i, j] of close) {
    if (!out[i] && !used.has(j)) {
      out[i] = { song: songs[j], how: "length" };
      used.add(j);
    }
  }
  const byNo = new Map(songs.map((s, j) => [`${s.disc || 1}-${s.no}`, j]));
  files.forEach((f, i) => {
    const j = f.track_no ? byNo.get(`${f.disc_no || 1}-${f.track_no}`) : undefined;
    if (out[i] || j === undefined || used.has(j) || (timed && f.duration && songs[j].length)) return;   // its length said no
    out[i] = { song: songs[j], how: "number" };
    used.add(j);
  });
  if (out.every((p) => !p) && files.length === songs.length && !(timed && files.some((f) => f.duration))) {
    return songs.map((song) => ({ song, how: "order" }));
  }
  return out;
}

const count = (n: unknown, what: string) => `${Number(n) || 0} ${what}${Number(n) === 1 ? "" : "s"}`;

/** Their albums' folders (Genre/Artist) under a new name: Rock / New Name. */
const refiled = (folders: unknown, name: string) =>
  ((folders as string[] | undefined) || []).map((f) => [...f.split("/").slice(0, -1), name].join(" / "));

/** What renaming an artist does, before it's saved. */
function renameSays(d: Details, name: string, other: Namesake | null): string {
  const songs = count(d.songs, "song");
  if (!name || name === d.name) {
    return `A new name goes into the tags of all ${songs} and their albums are filed under it.`;
  }
  const to = refiled(d.folders, name);
  return `Saving renames ${String(d.name)} to ${name} in the tags of ${songs}`
    + (to.length ? `, and ${Number(d.albums) === 1 ? "their album moves" : `their ${count(d.albums, "album")} move`} to ${to.join(" and ")}` : "")
    + (other ? `. The library already has ${other.name} (${count(other.albums, "album")}): the two become one artist` : "")
    + ". It runs in the background (a minute or two for someone with many albums); Muzix tells you when it's done, with an Undo.";
}

/** How an artist's rename went, once its job is over. */
function sayRenamed(j: Job, from: string, to: string, picture: string) {
  const notify = useUi.getState().notify;
  refreshAll();
  if (j.status !== "done") {
    notify(`Renaming ${from} to ${to} ${j.status === "cancelled" ? "was cancelled" : "stopped with an error"} partway. `
      + "What was renamed can be undone from Admin → Edits.", "error", { label: "See why", to: "/admin/jobs" });
    return;
  }
  const r = j.result as Renamed;
  const failed = r.failed?.length || 0;
  // two artists become one: the old page empties, so the message leads to the one left (Undo is in Admin → Edits)
  const action = failed ? { label: "See why", to: "/admin/jobs" }
    : r.merged ? { label: `Open ${to}`, to: `/artist/${r.artist_id}` }
    : r.edit_id ? { label: "Undo", run: () => void undoEdit(r.edit_id!) } : undefined;
  notify(`${from} is now ${to}: ${count(r.songs, "song")} renamed`
    + (r.folders?.length ? `, filed in ${r.folders.join(" and ")}` : "")
    + (r.merged ? `, together with the ${to} already in the library (undo it from Admin → Edits)` : "")
    + (r.picture ? `, with the picture from ${picture}` : "")
    + (failed ? `. ${count(failed, "thing")} couldn't be changed (Admin → Jobs says why)` : ""),
    failed ? "error" : "info", action);
}

/** Where the changes end up, in a sentence. */
function savedWhere(d: Details, form: Form, other: Namesake | null): string {
  if (d.kind === "album" || d.kind === "track") {
    if (d.tags === "muzix") return "These files have no tags to write, so Muzix keeps the changes and uses them on every scan.";
    if (d.writable === false) return "The folder is read-only for Muzix: the changes can't be saved into the files.";
    return d.files === "music"
      ? `Saved into the files' tags; ${d.kind === "album" ? "the album is filed again as Genre / Artist / Artist - Year - Album, with its songs renamed"
        : "the file is renamed to match"}.`
      : "Saved into the files' tags; the files stay where they are.";
  }
  if (d.kind === "artist") return renameSays(d, String(form.name ?? "").trim(), other);
  if (d.kind === "book" || d.kind === "podcast") return `Muzix keeps these over ${d.kind === "book" ? "rescans" : "refreshes of the feed"}.`;
  if (d.kind === "fileplaylist") return "The playlist file is renamed.";
  return "";
}

export function EditDialog({ kind, id, onClose }: { kind: ItemKind; id: number; onClose: () => void }) {
  const notify = useUi((s) => s.notify);
  const q = useQuery({ queryKey: ["manage", kind, id], queryFn: () => api.get<Details>(`/api/manage/${kind}/${id}`), gcTime: 0 });
  const [form, setForm] = useState<Form>({});
  const [tracks, setTracks] = useState<TrackEdit[]>([]);
  const [filled, setFilled] = useState("");
  const [saving, setSaving] = useState(false);
  const [ready, setReady] = useState(false);       // the form holds the item: the side panel can start searching
  const [picked, setPicked] = useState<Picked | null>(null);       // the cover of the album taken from a source
  const [missed, setMissed] = useState<Set<number>>(new Set());    // songs no source song was as long as
  const [matches, setMatches] = useState<number | null>(null);     // how many the sources found, once they answer
  const d = q.data;
  // a new name someone in the library already has: say before saving that the two become one
  const typed = kind === "artist" ? String(form.name ?? "").trim() : "";
  const [asked, setAsked] = useState("");
  useEffect(() => {
    const t = window.setTimeout(() => setAsked(typed), 400);
    return () => window.clearTimeout(t);
  }, [typed]);
  const namesake = useQuery({
    queryKey: ["namesake", id, asked], enabled: !!asked && asked !== d?.name, staleTime: 30_000,
    queryFn: () => api.get<{ other: Namesake | null }>(`/api/manage/artist/${id}/namesake`, { name: asked }),
  }).data?.other;
  const other = namesake && asked === typed ? namesake : null;
  useEffect(() => {
    if (!d) return;
    setForm(Object.fromEntries(FIELDS[kind].map(([k]) => [k, (d[k] as string | number | undefined) ?? ""])));
    setTracks(Array.isArray(d.tracks) ? d.tracks : []);
    setReady(true);
  }, [d, kind]);

  const save = async () => {
    setSaving(true);
    try {
      // an artist's picture goes with the save: a new name sets it once all their files have it
      const r = await api.put<{ notes?: string[]; job_id?: number; moved_to?: string | null; renamed_to?: string | null;
        edit_id?: number | null; picture?: boolean }>(
        `/api/manage/${kind}/${id}`, { fields: form, tracks, picture: kind === "artist" ? picked?.url ?? "" : "" });
      if (r.job_id) {
        const from = String(d!.name), to = String(form.name ?? "").trim();
        notify(`Renaming ${from} to ${to} (${count(d!.songs, "song")}) in the background`
          + (picked ? `, with the picture from ${picked.source}` : "") + ". Muzix tells you here when it's done",
          "info", { label: "Show progress", to: "/admin/jobs" });
        whenDone(r.job_id, (j) => sayRenamed(j, from, to, picked?.source ?? ""));
      } else {
        const said = r.moved_to ? `Saved, and filed in ${r.moved_to.split("/").slice(-3).join(" / ")}`
          : r.renamed_to ? "Saved, and the file renamed" : "Saved";
        let cover = r.picture ? `with the picture from ${picked?.source}` : "";
        if (picked && kind !== "artist") {
          try {
            await api.post(`/api/manage/${kind}/${id}/cover`, { url: picked.url, edit_id: r.edit_id });
            cover = `with the cover from ${picked.source}`;
          } catch (e) {
            cover = `but the cover from ${picked.source} couldn't be saved: ${(e as Error).message}`;
          }
        }
        notify([cover ? `${said}, ${cover}` : said, ...(r.notes || [])].join(". "), cover.startsWith("but") ? "error" : "info",
          r.edit_id ? { label: "Undo", run: () => void undoEdit(r.edit_id!) } : undefined);
      }
      refreshAll();
      onClose();
    } catch (e) {
      notify((e as Error).message, "error");
    } finally {
      setSaving(false);
    }
  };

  const use = async (m: Match) => {
    if (kind === "artist") {
      const source = SOURCE[m.source];
      try {
        const a = await api.get<ArtistDetails>(`/api/manage/lookup/${m.source}/artist/${encodeURIComponent(m.id)}`);
        setForm({ ...form, name: a.name || m.title });
        setPicked(a.cover ? { url: a.cover, thumb: m.cover || a.cover, source } : null);
        setFilled(`Filled in from ${source}` + (a.cover ? ", with its picture of them" : `. ${source} has no picture of them, so the current one stays`)
          + ". Check it, then save.");
      } catch (e) {
        notify((e as Error).message, "error");
      }
      return;
    } else if (kind === "track") {
      setForm({ ...form, title: m.title, artist: m.artist || form.artist, album: m.album || form.album,
        year: m.year || form.year, genre: m.genre || form.genre, track_no: m.no || form.track_no, disc_no: m.disc || form.disc_no });
      if (m.length && d?.duration && !sameLength(d.duration, m.length)) {
        setFilled(`Filled in from ${SOURCE[m.source]}, but its song is ${fmtTime(m.length)} long and this file ${fmtTime(d.duration)}: `
          + "it may be another recording. Check it, then save.");
        return;
      }
    } else {
      try {
        const a = await api.get<AlbumDetails>(`/api/manage/lookup/${m.source}/album/${encodeURIComponent(m.id)}`);
        setForm({ ...form, title: a.title || form.title, artist: a.artist || form.artist, year: a.year || form.year,
          genre: a.genre || form.genre });
        const pairs = pair(tracks, a.tracks);
        const discs = a.tracks.some((x) => (x.disc || 1) > 1);
        setTracks(tracks.map((t, i) => {
          const r = pairs[i]?.song;
          return r ? { ...t, title: r.title, artist: r.artist || t.artist, track_no: r.no || t.track_no, disc_no: discs ? r.disc : t.disc_no } : t;
        }));
        const matched = pairs.filter(Boolean).length;
        const byLength = pairs.filter((p) => p?.how === "length").length;
        const left = new Set(tracks.filter((_, i) => !pairs[i]).map((t) => t.id));
        setMissed(left);
        setPicked(a.cover ? { url: a.cover, thumb: m.cover || a.cover, source: SOURCE[m.source] } : null);
        const source = SOURCE[m.source];
        setFilled(`Filled in from ${source}: ${matched} of ${tracks.length} songs matched`
          + (byLength ? (byLength === matched ? " by their length" : ` (${byLength} by their length)`) : "")
          + (left.size ? `. ${left.size} kept ${left.size === 1 ? "its" : "their"} own (marked): no song on ${source} is as long` : "")
          + (a.cover ? ". Its cover comes too" : `. ${source} has no cover for it, so the current one stays`) + ". Check them, then save.");
        return;
      } catch (e) {
        notify((e as Error).message, "error");
        return;
      }
    }
    setFilled(`Filled in from ${SOURCE[m.source]}. Check it, then save.`);
  };

  return (
    <Modal onClose={onClose} className="edit-modal">
      {!d ? (
        <div className="edit-loading">{q.isError ? (q.error as Error).message : <><Loader2 size={18} className="spin" /> Reading…</>}</div>
      ) : (
        <>
          <header className="edit-head">
            <div className="kicker">Edit {NOUN[kind]}{d.hidden ? " · hidden" : ""}</div>
            <h2 className="h2 ellipsis">{String(d.title ?? d.name ?? "")}</h2>
            {d.last_edit && (
              <div className="edit-last">
                <span className="faint">Edited {ago(d.last_edit.created_at)}: {d.last_edit.summary || "changes"}.</span>
                <button className="btn small" onClick={async () => { if (await undoEdit(d.last_edit!.id)) onClose(); }}>
                  <RotateCcw size={13} /> Undo that edit
                </button>
              </div>
            )}
          </header>
          <div className="edit-grid">
            <section className="edit-main">
              <div className="edit-fields">
                {FIELDS[kind].map(([k, label, type]) => (
                  <div key={k} className={`field ${type === "area" ? "wide" : ""} ${type === "number" ? "num" : ""}`}>
                    <label htmlFor={`edit-${k}`}>{label}</label>
                    {type === "area"
                      ? <textarea id={`edit-${k}`} className="input" rows={4} value={String(form[k] ?? "")}
                                  onChange={(e) => setForm({ ...form, [k]: e.target.value })} />
                      : <input id={`edit-${k}`} className="input" type={type} value={String(form[k] ?? "")}
                               onChange={(e) => setForm({ ...form, [k]: type === "number" ? Number(e.target.value) || 0 : e.target.value })} />}
                  </div>
                ))}
              </div>
              {kind === "album" && <TrackTable tracks={tracks} missed={missed} onChange={setTracks} />}
              {filled && <p className="edit-filled">{filled}</p>}
              <p className="faint edit-where">{savedWhere(d, form, other)}</p>
            </section>
            <aside className="edit-side">
              {ready && LOOKUP[kind] && <Matches kind={LOOKUP[kind]!} form={form} onUse={use} onResults={setMatches} />}
              {ready && (["album", "track", "artist", "book", "podcast", "station"] as ItemKind[]).includes(kind)
                && !(kind === "track" && !d.album_id)
                && <Covers kind={kind} id={id} d={d} form={form} picked={picked} onUnpick={() => setPicked(null)}
                           search={!LOOKUP[kind] || matches === 0} />}
            </aside>
          </div>
          <footer className="edit-foot">
            <button className="btn" onClick={onClose}>Cancel</button>
            <button className="btn primary" disabled={saving || d.writable === false} onClick={save}>
              {saving && <Loader2 size={15} className="spin" />} Save
            </button>
          </footer>
        </>
      )}
    </Modal>
  );
}

function TrackTable({ tracks, missed, onChange }: { tracks: TrackEdit[]; missed: Set<number>; onChange: (t: TrackEdit[]) => void }) {
  const set = (i: number, patch: Partial<TrackEdit>) => onChange(tracks.map((t, j) => (j === i ? { ...t, ...patch } : t)));
  return (
    <div className="edit-tracks" role="table" aria-label="Songs">
      <div className="edit-track head" role="row"><span>Disc</span><span>#</span><span>Title</span><span>Artist</span><span /></div>
      {tracks.map((t, i) => (
        <div key={t.id} className={`edit-track ${missed.has(t.id) ? "missed" : ""}`} role="row"
             title={missed.has(t.id) ? "No song of this length in the picked album: kept as it was" : undefined}>
          <input className="input" type="number" aria-label="Disc" value={t.disc_no || ""} onChange={(e) => set(i, { disc_no: Number(e.target.value) || 0 })} />
          <input className="input" type="number" aria-label="Track" value={t.track_no || ""} onChange={(e) => set(i, { track_no: Number(e.target.value) || 0 })} />
          <input className="input" aria-label="Title" value={t.title} onChange={(e) => set(i, { title: e.target.value })} />
          <input className="input" aria-label="Artist" value={t.artist} onChange={(e) => set(i, { artist: e.target.value })} />
          <span className="faint">{t.duration ? fmtTime(t.duration) : ""}</span>
        </div>
      ))}
    </div>
  );
}

function Matches({ kind, form, onUse, onResults }: {
  kind: "album" | "track" | "artist"; form: Form; onUse: (m: Match) => Promise<void>; onResults: (n: number) => void;
}) {
  const first = { artist: String((kind === "artist" ? form.name : form.artist) ?? ""), title: kind === "artist" ? "" : String(form.title ?? ""),
    album: kind === "track" ? String(form.album ?? "") : "" };
  const [input, setInput] = useState(first);
  const [ask, setAsk] = useState(first);
  const [using, setUsing] = useState("");       // an album's songs are being fetched (MusicBrainz takes a moment)
  const [all, setAll] = useState(false);
  const ready = !!(ask.artist || ask.title);
  const r = useQuery({
    queryKey: ["lookup", kind, ask], enabled: ready, staleTime: 600_000,
    queryFn: () => api.get<Found<Match>>("/api/manage/lookup", { kind, ...ask }),
  });
  const count = r.data?.results.length;
  useEffect(() => {
    if (count !== undefined) onResults(count);
  }, [count, onResults]);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    setAsk(input);
  };
  return (
    <section className="edit-panel">
      <h3 className="edit-panel-title">Elsewhere</h3>
      <form className="edit-search" onSubmit={submit}>
        <input className="input" placeholder="Artist" value={input.artist} onChange={(e) => setInput({ ...input, artist: e.target.value })} />
        {kind !== "artist" && <input className="input" placeholder={kind === "album" ? "Album" : "Title"} value={input.title}
                                     onChange={(e) => setInput({ ...input, title: e.target.value })} />}
        <button className="btn small" aria-label="Search"><Search size={14} /></button>
      </form>
      {r.isFetching ? <div className="dim edit-wait"><Loader2 size={14} className="spin" /> Asking MusicBrainz, Discogs, Deezer, iTunes and Spotify…</div> : (
        <ul className="edit-matches">
          {sorted(r.data?.results || []).slice(0, all ? undefined : SHOWN).map((m) => (
            <li key={`${m.source}-${m.id}`}>
              <Thumb src={m.cover} />
              <span className="edit-match-text">
                <span className="ellipsis"><b>{m.title}</b></span>
                <span className="faint ellipsis">
                  {[m.artist, m.album, m.year || null, m.tracks ? `${m.tracks} songs` : null, m.length ? fmtTime(m.length) : null,
                    m.format, m.country, m.label].filter(Boolean).join(" · ")}
                </span>
              </span>
              <span className="edit-source">{SOURCE[m.source]}</span>
              {m.url && <a className="mini" href={m.url} target="_blank" rel="noreferrer" aria-label={`Open on ${SOURCE[m.source]}`}><ExternalLink size={13} /></a>}
              <button className="btn small" disabled={!!using} onClick={async () => {
                setUsing(`${m.source}-${m.id}`);
                await onUse(m);
                setUsing("");
              }}>{using === `${m.source}-${m.id}` ? <Loader2 size={13} className="spin" /> : "Use"}</button>
            </li>
          ))}
          {ready && r.data && !r.data.results.length && <li className="dim">Nothing found. Try other words.</li>}
          {!all && (r.data?.results.length || 0) > SHOWN && (
            <li className="dim"><button className="btn small" onClick={() => setAll(true)}>Show all {r.data!.results.length}</button></li>
          )}
        </ul>
      )}
      {r.data && Object.keys(r.data.errors).length > 0 && (
        <p className="faint edit-errors">{Object.entries(r.data.errors).map(([s, e]) => `${SOURCE[s] || s} ${e}`).join(" · ")}</p>
      )}
    </section>
  );
}

/** Each source's best first, then their second best, and so on: one source's many editions
 * of an album don't push the others out of sight. The fullest metadata leads each round. */
function sorted(results: Match[]): Match[] {
  const seen: Record<string, number> = {};
  const rank = new Map(results.map((m) => [m, (seen[m.source] = (seen[m.source] ?? -1) + 1)]));
  return [...results].sort((a, b) => rank.get(a)! - rank.get(b)! || ORDER.indexOf(a.source) - ORDER.indexOf(b.source));
}

function CoverTile({ c, busy, onUse }: { c: Cover; busy: string; onUse: (url: string) => void }) {
  const [src, setSrc] = useState(c.thumb);
  const [failed, setFailed] = useState(false);
  if (failed) return null;
  return (
    <button className={`edit-cover ${busy === c.url ? "busy" : ""}`} disabled={!!busy}
            title={`${c.source}: ${c.title}${c.width ? ` (${c.width}×${c.height})` : ""}`} onClick={() => onUse(c.url)}>
      <img src={src} alt="" loading="lazy" referrerPolicy="no-referrer"
           onError={() => (src !== c.url ? setSrc(c.url) : setFailed(true))} />
      <span>{c.source}{c.width ? ` · ${c.width}` : ""}</span>
      {busy === c.url && <Loader2 size={18} className="spin" />}
    </button>
  );
}

/** The cover: the one an album picked from a source brings along, or one to choose. The sources are
 * only asked for covers when the album wasn't found (`search`) or the admin asks for others. */
function Covers({ kind, id, d, form, picked, onUnpick, search }: {
  kind: ItemKind; id: number; d: Details; form: Form; picked: Picked | null; onUnpick: () => void; search: boolean;
}) {
  const notify = useUi((s) => s.notify);
  const cover = kind === "track" ? "album" : kind;
  const music = cover === "album" || cover === "artist";
  const urlOnly = kind === "podcast" || kind === "station";
  const names = () => ({        // the form as it is now: an album picked from a source has its names
    artist: String((kind === "artist" ? form.name : kind === "album" ? form.artist : form.albumartist || form.artist) ?? ""),
    title: String((kind === "track" ? form.album : kind === "artist" ? "" : form.title ?? form.name) ?? ""),
  });
  const [{ artist, title }] = useState(names);
  const suggest = { album: `${artist} ${title} album cover`, artist: `${artist} band photo`, book: `${title} ${form.author ?? ""} audiobook cover`,
    podcast: `${title} podcast`, station: `${form.name ?? ""} radio logo` }[cover as "album"] || title;
  const [webInput, setWebInput] = useState(suggest.trim());
  const [web, setWeb] = useState("");
  const [paste, setPaste] = useState("");
  const [busy, setBusy] = useState("");
  const [version, setVersion] = useState(0);
  const [current, setCurrent] = useState<string | null>((d.art as string) || d.image || d.favicon || null);
  const [ask, setAsk] = useState<{ artist: string; title: string } | null>(null);
  useEffect(() => {
    if (search) setAsk((a) => a ?? names());
  }, [search]);     // the names as they were when the sources found nothing
  const item = kind === "track" ? d.album_id : id;      // its MusicBrainz id finds it on fanart.tv
  const found = useQuery({
    queryKey: ["covers", cover, ask, item], enabled: music && !!(ask?.artist || ask?.title), staleTime: 600_000,
    queryFn: () => api.get<Found<Cover>>("/api/manage/covers", { kind: cover, ...ask!, item: item ?? 0 }),
  });
  const webFound = useQuery({
    queryKey: ["covers-web", web], enabled: !!web, staleTime: 600_000,
    queryFn: () => api.get<Found<Cover>>("/api/manage/covers", { kind: cover, web }),
  });

  const done = (url?: string) => {
    onUnpick();
    notify(kind === "track" ? "Album cover saved" : "Cover saved");
    if (url && urlOnly) setCurrent(url);
    else setCurrent(kind === "artist" ? `/api/art/artist/${id}` : kind === "book" ? `/api/art/book/${id}`
      : `/api/art/album/${kind === "track" ? d.album_id : id}`);
    setVersion(Date.now());
    refreshAll();
  };
  const use = async (url: string) => {
    setBusy(url);
    try {
      await api.post(`/api/manage/${kind}/${id}/cover`, { url });
      done(url);
    } catch (e) {
      notify((e as Error).message, "error");
    } finally {
      setBusy("");
    }
  };
  const upload = async (file: File) => {
    const body = new FormData();
    body.append("file", file);
    setBusy("upload");
    try {
      await api.post(`/api/manage/${kind}/${id}/cover/upload`, body);
      done();
    } catch (e) {
      notify((e as Error).message, "error");
    } finally {
      setBusy("");
    }
  };
  const shown = current ? (current.startsWith("/api/") ? `${current}${current.includes("?") ? "&" : "?"}s=300${version ? `&v=${version}` : ""}` : current) : null;
  const grid = (list: Cover[]) => (
    <div className="edit-covers">
      {list.map((c) => <CoverTile key={c.url} c={c} busy={busy} onUse={use} />)}
    </div>
  );
  return (
    <section className="edit-panel">
      <h3 className="edit-panel-title">{kind === "track" ? "Album cover" : kind === "station" ? "Logo" : kind === "artist" ? "Picture" : "Cover"}</h3>
      <div className="edit-current">
        {picked ? <img src={picked.thumb} alt="" referrerPolicy="no-referrer" />
          : shown ? <img src={shown} alt="" /> : <span className="edit-nocover big"><ImagePlus size={22} /></span>}
        <div className="edit-own">
          {picked && (
            <div className="edit-picked">
              <span>{picked.source}'s {kind === "artist" ? "picture, saved with the artist" : "cover, saved with the album"}.</span>
              <button className="btn small ghost" onClick={onUnpick}>Keep the current one</button>
            </div>
          )}
          <form onSubmit={(e) => { e.preventDefault(); if (paste) use(paste); }}>
            <input className="input" placeholder="Paste a picture's address" value={paste} onChange={(e) => setPaste(e.target.value)} />
            <button className="btn small" disabled={!paste || !!busy}>Use</button>
          </form>
          {!urlOnly && (
            <label className="btn small edit-upload">
              {busy === "upload" ? <Loader2 size={14} className="spin" /> : <Upload size={14} />} Upload a picture
              <input type="file" accept="image/*" hidden onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
            </label>
          )}
        </div>
      </div>
      {music && !ask && (
        <button className="btn small edit-others" onClick={() => setAsk(names())}><Search size={14} /> Find other covers</button>
      )}
      {music && (found.isFetching ? <div className="dim edit-wait"><Loader2 size={14} className="spin" /> Looking for covers…</div>
        : found.data && (found.data.results.length ? grid(found.data.results) : <p className="dim">No covers found in the music sources.</p>))}
      <form className="edit-search" onSubmit={(e) => { e.preventDefault(); setWeb(webInput); }}>
        <input className="input" placeholder="Search the web for pictures" value={webInput} onChange={(e) => setWebInput(e.target.value)} />
        <button className="btn small" aria-label="Search the web"><Search size={14} /></button>
      </form>
      {web && (webFound.isFetching ? <div className="dim edit-wait"><Loader2 size={14} className="spin" /> Searching the web…</div>
        : webFound.data && (webFound.data.errors.web ? <p className="faint">{webFound.data.errors.web}</p>
          : webFound.data.results.length ? grid(webFound.data.results) : <p className="dim">No pictures found.</p>))}
      {found.data && Object.keys(found.data.errors).length > 0 && (
        <p className="faint edit-errors">{Object.entries(found.data.errors).map(([s, e]) => `${SOURCE[s] || s} ${e}`).join(" · ")}</p>
      )}
    </section>
  );
}
