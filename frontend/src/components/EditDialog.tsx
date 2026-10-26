/** The admin's edit window: an item's metadata (an album with its songs), what MusicBrainz,
 * Deezer, iTunes and Spotify know about it, and its cover, from those sources, a web image
 * search, a picture's address or a file. Covers are saved at once; the rest with Save. */

import { useQuery } from "@tanstack/react-query";
import { ExternalLink, ImagePlus, Loader2, Search, Upload } from "lucide-react";
import { type FormEvent, useEffect, useState } from "react";
import { api, fmtTime } from "../api";
import { useUi } from "../store/ui";
import { type ItemKind, refreshAll } from "./AdminMode";
import { Modal } from "./ui";

interface TrackEdit { id: number; title: string; artist: string; track_no: number; disc_no: number; duration?: number }
type Details = { kind: ItemKind; id: number; tracks?: TrackEdit[]; art?: string | null; image?: string; favicon?: string;
  tags?: "files" | "muzix"; writable?: boolean; files?: string; album_id?: number | null } & Record<string, unknown>;
interface Match {
  source: string; id: string; title: string; artist?: string; album?: string; year?: number; tracks?: number;
  cover?: string | null; url?: string; country?: string; label?: string; format?: string; genre?: string;
  no?: number; disc?: number; length?: number;
}
interface Found<T> { results: T[]; errors: Record<string, string> }
interface Cover { source: string; thumb: string; url: string; title: string; width?: number; height?: number }
interface AlbumDetails { title: string; artist: string; year: number; genre: string; tracks: { disc: number; no: number; title: string; artist: string }[] }
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
const SOURCE: Record<string, string> = { musicbrainz: "MusicBrainz", deezer: "Deezer", itunes: "iTunes", spotify: "Spotify", web: "Web search" };
const ORDER = ["musicbrainz", "spotify", "deezer", "itunes"];     // the fullest metadata first
const SHOWN = 8;

/** A picture that steps aside when it can't load (a release without cover art). */
function Thumb({ src }: { src?: string | null }) {
  const [failed, setFailed] = useState(false);
  return src && !failed ? <img src={src} alt="" loading="lazy" referrerPolicy="no-referrer" onError={() => setFailed(true)} />
    : <span className="edit-nocover" />;
}

/** Where the changes end up, in a sentence. */
function savedWhere(d: Details): string {
  if (d.kind === "album" || d.kind === "track") {
    if (d.tags === "muzix") return "These files have no tags to write, so Muzix keeps the changes and uses them on every scan.";
    if (d.writable === false) return "The folder is read-only for Muzix: the changes can't be saved into the files.";
    return d.files === "music"
      ? `Saved into the files' tags; ${d.kind === "album" ? "the album is filed again as Genre / Artist / Artist - Year - Album, with its songs renamed"
        : "the file is renamed to match"}.`
      : "Saved into the files' tags; the files stay where they are.";
  }
  if (d.kind === "artist") return "A new name goes into the tags of all their songs, and their albums are filed under it (in the background).";
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
  const d = q.data;
  useEffect(() => {
    if (!d) return;
    setForm(Object.fromEntries(FIELDS[kind].map(([k]) => [k, (d[k] as string | number | undefined) ?? ""])));
    setTracks(Array.isArray(d.tracks) ? d.tracks : []);
    setReady(true);
  }, [d, kind]);

  const save = async () => {
    setSaving(true);
    try {
      const r = await api.put<{ notes?: string[]; job_id?: number; moved_to?: string | null; renamed_to?: string | null }>(
        `/api/manage/${kind}/${id}`, { fields: form, tracks });
      const said = r.job_id ? "Renaming in the background: see Admin → Jobs"
        : r.moved_to ? `Saved, and filed in ${r.moved_to.split("/").slice(-3).join(" / ")}`
        : r.renamed_to ? "Saved, and the file renamed" : "Saved";
      notify([said, ...(r.notes || [])].join(". "));
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
      setForm({ ...form, name: m.title });
    } else if (kind === "track") {
      setForm({ ...form, title: m.title, artist: m.artist || form.artist, album: m.album || form.album,
        year: m.year || form.year, genre: m.genre || form.genre, track_no: m.no || form.track_no, disc_no: m.disc || form.disc_no });
    } else {
      try {
        const a = await api.get<AlbumDetails>(`/api/manage/lookup/${m.source}/album/${encodeURIComponent(m.id)}`);
        setForm({ ...form, title: a.title || form.title, artist: a.artist || form.artist, year: a.year || form.year,
          genre: a.genre || form.genre });
        // songs by disc and number, or in order when the counts agree
        const byNo = new Map(a.tracks.map((t) => [`${t.disc || 1}-${t.no}`, t]));
        let matched = 0;
        setTracks(tracks.map((t, i) => {
          const r = byNo.get(`${t.disc_no || 1}-${t.track_no}`) || (a.tracks.length === tracks.length ? a.tracks[i] : undefined);
          if (!r) return t;
          matched++;
          return { ...t, title: r.title, artist: r.artist || t.artist, track_no: r.no || t.track_no,
            disc_no: a.tracks.some((x) => (x.disc || 1) > 1) ? r.disc : t.disc_no };
        }));
        setFilled(`Filled in from ${SOURCE[m.source]}: ${matched} of ${tracks.length} songs matched. Check them, then save.`);
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
              {kind === "album" && <TrackTable tracks={tracks} onChange={setTracks} />}
              {filled && <p className="edit-filled">{filled}</p>}
              <p className="faint edit-where">{savedWhere(d)}</p>
            </section>
            <aside className="edit-side">
              {ready && LOOKUP[kind] && <Matches kind={LOOKUP[kind]!} form={form} onUse={use} />}
              {ready && (["album", "track", "artist", "book", "podcast", "station"] as ItemKind[]).includes(kind)
                && !(kind === "track" && !d.album_id) && <Covers kind={kind} id={id} d={d} form={form} />}
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

function TrackTable({ tracks, onChange }: { tracks: TrackEdit[]; onChange: (t: TrackEdit[]) => void }) {
  const set = (i: number, patch: Partial<TrackEdit>) => onChange(tracks.map((t, j) => (j === i ? { ...t, ...patch } : t)));
  return (
    <div className="edit-tracks" role="table" aria-label="Songs">
      <div className="edit-track head" role="row"><span>Disc</span><span>#</span><span>Title</span><span>Artist</span><span /></div>
      {tracks.map((t, i) => (
        <div key={t.id} className="edit-track" role="row">
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

function Matches({ kind, form, onUse }: { kind: "album" | "track" | "artist"; form: Form; onUse: (m: Match) => Promise<void> }) {
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
      {r.isFetching ? <div className="dim edit-wait"><Loader2 size={14} className="spin" /> Asking MusicBrainz, Deezer, iTunes and Spotify…</div> : (
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

function sorted(results: Match[]): Match[] {
  return [...results].sort((a, b) => ORDER.indexOf(a.source) - ORDER.indexOf(b.source));
}

function CoverTile({ c, busy, onUse }: { c: Cover; busy: string; onUse: (url: string) => void }) {
  const [failed, setFailed] = useState(false);
  if (failed) return null;
  return (
    <button className={`edit-cover ${busy === c.url ? "busy" : ""}`} disabled={!!busy}
            title={`${c.source}: ${c.title}${c.width ? ` (${c.width}×${c.height})` : ""}`} onClick={() => onUse(c.url)}>
      <img src={c.thumb} alt="" loading="lazy" referrerPolicy="no-referrer" onError={() => setFailed(true)} />
      <span>{c.source}{c.width ? ` · ${c.width}` : ""}</span>
      {busy === c.url && <Loader2 size={18} className="spin" />}
    </button>
  );
}

function Covers({ kind, id, d, form }: { kind: ItemKind; id: number; d: Details; form: Form }) {
  const notify = useUi((s) => s.notify);
  const cover = kind === "track" ? "album" : kind;
  const music = cover === "album" || cover === "artist";
  const urlOnly = kind === "podcast" || kind === "station";
  const [{ artist, title }] = useState(() => ({
    artist: String((kind === "artist" ? form.name : kind === "album" ? form.artist : form.albumartist || form.artist) ?? ""),
    title: String((kind === "track" ? form.album : kind === "artist" ? "" : form.title ?? form.name) ?? ""),
  }));
  const suggest = { album: `${artist} ${title} album cover`, artist: `${artist} band photo`, book: `${title} ${form.author ?? ""} audiobook cover`,
    podcast: `${title} podcast`, station: `${form.name ?? ""} radio logo` }[cover as "album"] || title;
  const [webInput, setWebInput] = useState(suggest.trim());
  const [web, setWeb] = useState("");
  const [paste, setPaste] = useState("");
  const [busy, setBusy] = useState("");
  const [version, setVersion] = useState(0);
  const [current, setCurrent] = useState<string | null>((d.art as string) || d.image || d.favicon || null);
  const found = useQuery({
    queryKey: ["covers", cover, artist, title], enabled: music && !!(artist || title), staleTime: 600_000,
    queryFn: () => api.get<Found<Cover>>("/api/manage/covers", { kind: cover, artist, title }),
  });
  const webFound = useQuery({
    queryKey: ["covers-web", web], enabled: !!web, staleTime: 600_000,
    queryFn: () => api.get<Found<Cover>>("/api/manage/covers", { kind: cover, web }),
  });

  const done = (url?: string) => {
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
        {shown ? <img src={shown} alt="" /> : <span className="edit-nocover big"><ImagePlus size={22} /></span>}
        <div className="edit-own">
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
