/** A color scheme of the user's own, made or changed (theme/schemes.ts, as in Hooden): the colours of its dark
 * and light versions, fonts, the titles' lettering, corners, glass, the frame, the backdrop and a picture.
 * The whole app shows it while it's made; saved, it's the account's, and it can be shared. */

import { ImagePlus, Moon, RotateCcw, Save, Shuffle, Sun, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { queryClient } from "../actions";
import { api } from "../api";
import { Display, Kicker, Switch } from "../components/ui";
import { useUi } from "../store/ui";
import { type Colors, PALETTES } from "../theme/palettes";
import {
  BACKDROPS, CUSTOM, DISPLAY_FONTS, FRAMES, fromPalette, HEADLINES, type Scheme, type SchemeData, UI_FONTS, useSchemes,
} from "../theme/schemes";

const COLORS: [keyof Colors, string][] = [
  ["bg", "Background"], ["surface", "Panels"], ["text", "Text"], ["primary", "Accent (Play, titles, what's on)"],
  ["secondary", "Second accent (main buttons)"], ["border", "Lines"], ["success", "Success"], ["warning", "Warning"], ["error", "Danger"],
];

const isHex = (v: string) => /^#[0-9a-fA-F]{6}$/.test(v);

function ColorRow({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  const [text, setText] = useState(value);
  useEffect(() => setText(value), [value]);
  return (
    <label className="color-row">
      <input type="color" value={value} onChange={(e) => onChange(e.target.value)} aria-label={label} />
      <span className="grow">{label}</span>
      <input className="input mono" value={text} maxLength={7} aria-label={`${label} as hex`}
             onChange={(e) => {
               setText(e.target.value);
               if (isHex(e.target.value)) onChange(e.target.value.toLowerCase());
             }} />
    </label>
  );
}

/** A picture of the scheme's own: uploaded to the server, shown here small. */
function PicturePick({ label, value, onChange }: { label: string; value: string; onChange: (url: string) => void }) {
  const notify = useUi((s) => s.notify);
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const upload = async (file: File) => {
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      onChange((await api.post<{ url: string }>("/api/schemes/pictures", fd)).url);
    } catch (e) {
      notify((e as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="field">
      <label>{label}</label>
      <div className="pic-pick">
        <div className="pic-thumb" style={value ? { backgroundImage: `url("${value}")` } : undefined}>{!value && <ImagePlus size={20} />}</div>
        <div className="row-actions">
          <button className="btn small" disabled={busy} onClick={() => input.current?.click()}>{busy ? "Uploading…" : value ? "Another picture" : "Choose a picture"}</button>
          {value && <button className="btn small ghost" onClick={() => onChange("")}><X size={14} /> Remove</button>}
        </div>
        <input ref={input} type="file" accept="image/*" hidden onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
      </div>
    </div>
  );
}

function Range({ label, value, min, max, unit, onChange }: { label: string; value: number; min: number; max: number; unit: string; onChange: (v: number) => void }) {
  return (
    <div className="field">
      <label>{label}: {value}{unit}</label>
      <input type="range" className="range" min={min} max={max} value={value} aria-label={label} onChange={(e) => onChange(Number(e.target.value))} />
    </div>
  );
}

export default function SchemeEditor() {
  const { id } = useParams();
  const [params] = useSearchParams();
  const nav = useNavigate();
  const notify = useUi((s) => s.notify);
  const setDraft = useSchemes((s) => s.setDraft);
  const editing = id ? Number(id) : null;
  const from = Number(params.get("from")) || null;
  const [data, setData] = useState<SchemeData | null>(null);
  const [name, setName] = useState("");
  const [shared, setShared] = useState(false);
  const [version, setVersion] = useState<"dark" | "light">("dark");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const which = editing ?? from;
    if (!which) {
      setData(fromPalette(params.get("base") || "muzix"));
      return;
    }
    api.get<Scheme>(`/api/schemes/${which}`).then((s) => {
      setData(s.data);
      setVersion(s.data.modes === "light" ? "light" : "dark");
      setName(editing ? s.name : `${s.name} (copy)`.slice(0, 40));
      setShared(editing ? s.shared : false);
    }).catch((e: Error) => {
      notify(e.message, "error");
      nav("/settings");
    });
  }, [editing, from]);  // eslint-disable-line react-hooks/exhaustive-deps

  // the whole app shows the version being changed, and stops when this page goes
  useEffect(() => {
    if (data) setDraft({ ...data, modes: version });
  }, [data, version, setDraft]);
  useEffect(() => () => setDraft(null), [setDraft]);

  if (!data) return <div className="page" />;
  const set = <K extends keyof SchemeData>(k: K, v: SchemeData[K]) => setData({ ...data, [k]: v });
  const setColor = (k: keyof Colors, v: string) => setData({ ...data, [version]: { ...data[version], [k]: v } });
  const start = (slug: string) => {
    const p = fromPalette(slug);
    setData({ ...data, base: slug, dark: p.dark, light: p.light });
  };
  const versions = (m: SchemeData["modes"]) => {
    setData({ ...data, modes: m });
    if (m !== "both") setVersion(m);
  };
  const save = async (use: boolean) => {
    if (!name.trim()) return notify("Give it a name first", "error");
    setBusy(true);
    try {
      const body = { name: name.trim(), data, shared };
      const s = editing ? await api.put<Scheme>(`/api/schemes/${editing}`, body) : await api.post<Scheme>("/api/schemes", body);
      useSchemes.getState().meet([s]);
      if (use) useUi.getState().setPref("scheme", CUSTOM + s.id);
      queryClient.invalidateQueries({ queryKey: ["schemes"] });
      notify(use ? `${s.name} is this device's color scheme now` : `${s.name} is saved`);
      nav("/settings");
    } catch (e) {
      notify((e as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };
  const other = version === "dark" ? "light" : "dark";
  const pic = data.picture;

  return (
    <div className="page scheme-editor">
      <Kicker parts={["Your settings", editing ? "Your color scheme" : "A color scheme of your own"]} />
      <Display l1={editing ? name || "Your own" : "Make"} l2={editing ? "scheme" : "your own"} small />
      <p className="lede">The whole app shows it as you go: have a look around, then save it. It shows when no genre skin does.</p>

      <section className="panel">
        <div className="panel-head"><div className="h2">Name and starting point</div></div>
        <div className="field">
          <label htmlFor="se-name">Name</label>
          <input id="se-name" className="input" style={{ maxWidth: 360 }} value={name} maxLength={40} placeholder="My scheme"
                 onChange={(e) => setName(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="se-base">Start from a scheme</label>
          <div className="row-actions">
            <select id="se-base" className="select" style={{ maxWidth: 320 }} value={data.base} onChange={(e) => start(e.target.value)}>
              {PALETTES.map((p) => <option key={p.slug} value={p.slug}>{p.name}</option>)}
            </select>
            <button className="btn small" data-tip="A scheme picked at random" onClick={() => start(PALETTES[Math.floor(Math.random() * PALETTES.length)].slug)}>
              <Shuffle size={14} /> Surprise me
            </button>
          </div>
          <div className="help">Its colours, dark and light, replace the ones here; fonts and the rest stay.</div>
        </div>
        <div className="field">
          <label>Versions</label>
          <div className="seg" role="group" aria-label="Versions">
            {([["both", "Dark and light"], ["dark", "Dark only"], ["light", "Light only"]] as const).map(([m, label]) => (
              <button key={m} className={data.modes === m ? "on" : ""} aria-pressed={data.modes === m} onClick={() => versions(m)}>{label}</button>
            ))}
          </div>
          <div className="help">With both, each device's light or dark setting picks one.</div>
        </div>
        <div className="field">
          <label>Share it</label>
          <div className="row-actions">
            <Switch checked={shared} onChange={setShared} label="Share it" />
            <span className="dim">Everyone on this server can use it, or copy it to change.</span>
          </div>
        </div>
      </section>

      <section className="panel">
        <div className="panel-head">
          <div className="h2">Colors</div>
          {data.modes === "both" && (
            <div className="seg" role="group" aria-label="The version being changed">
              <button className={version === "dark" ? "on" : ""} aria-pressed={version === "dark"} onClick={() => setVersion("dark")}><Moon size={13} /> Dark</button>
              <button className={version === "light" ? "on" : ""} aria-pressed={version === "light"} onClick={() => setVersion("light")}><Sun size={13} /> Light</button>
            </div>
          )}
        </div>
        <div className="color-grid">
          {COLORS.map(([k, label]) => <ColorRow key={k} label={label} value={data[version][k]} onChange={(v) => setColor(k, v)} />)}
        </div>
        <div className="row-actions" style={{ marginTop: 12 }}>
          <button className="btn small ghost" onClick={() => setData({ ...data, [version]: { ...fromPalette(data.base)[version] } })}>
            <RotateCcw size={14} /> Back to the scheme's colors
          </button>
          {data.modes === "both" && (
            <button className="btn small ghost" onClick={() => {
              setData({ ...data, [other]: { ...data[other], primary: data[version].primary, secondary: data[version].secondary } });
              notify(`The accents are in the ${other} version too`);
            }}>
              Use these accents in the {other} version
            </button>
          )}
        </div>
      </section>

      <section className="panel">
        <div className="panel-head"><div className="h2">Fonts</div></div>
        <div className="field">
          <label>Titles</label>
          <div className="font-pick" role="group" aria-label="The titles' font">
            {DISPLAY_FONTS.map((f) => (
              <button key={f.id} className={`font-opt ${data.display === f.id ? "on" : ""}`} aria-pressed={data.display === f.id} onClick={() => set("display", f.id)}>
                <span className="font-sample" style={{ fontFamily: f.css, textTransform: data.caps ? "uppercase" : "none" }}>Muzix</span>
                <span className="font-name">{f.name}</span>
              </button>
            ))}
          </div>
        </div>
        <div className="field">
          <label>Titles in capitals</label>
          <div className="row-actions"><Switch checked={data.caps} onChange={(v) => set("caps", v)} label="Titles in capitals" /></div>
        </div>
        <div className="field">
          <label>Everything else</label>
          <div className="font-pick wide" role="group" aria-label="The font for everything else">
            {UI_FONTS.map((f) => (
              <button key={f.id} className={`font-opt ${data.ui === f.id ? "on" : ""}`} aria-pressed={data.ui === f.id} onClick={() => set("ui", f.id)}>
                <span style={{ fontFamily: f.css, fontSize: 15 }}>Play the whole album</span>
                <span className="font-name">{f.name}</span>
              </button>
            ))}
          </div>
        </div>
        <div className="field">
          <label htmlFor="se-headline">The titles' lettering</label>
          <select id="se-headline" className="select" style={{ maxWidth: 320 }} value={data.headline} onChange={(e) => set("headline", e.target.value as SchemeData["headline"])}>
            {HEADLINES.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
          </select>
          <div className="help">The genre skins' effects on the big titles (a few want their skin's font to look right).</div>
        </div>
      </section>

      <section className="panel">
        <div className="panel-head"><div className="h2">Shape, glass and frame</div></div>
        <Range label="Rounded corners" value={data.radius} min={0} max={28} unit="px" onChange={(v) => set("radius", v)} />
        <Range label="Glass (how solid the frame is)" value={data.glass} min={0} max={100} unit="%" onChange={(v) => set("glass", v)} />
        <div className="field">
          <label htmlFor="se-frame">Frame</label>
          <select id="se-frame" className="select" style={{ maxWidth: 320 }} value={data.frame} onChange={(e) => set("frame", e.target.value as SchemeData["frame"])}>
            {FRAMES.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
          </select>
          <div className="help">Round the page on a computer or tablet; phones have none.</div>
        </div>
      </section>

      <section className="panel">
        <div className="panel-head"><div className="h2">Backdrop and picture</div></div>
        <div className="field">
          <label htmlFor="se-backdrop">Backdrop</label>
          <select id="se-backdrop" className="select" style={{ maxWidth: 320 }} value={data.backdrop} onChange={(e) => set("backdrop", e.target.value as SchemeData["backdrop"])}>
            {BACKDROPS.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
          </select>
          <div className="help">Drawn behind everything, moving with the music, when there's no picture.</div>
        </div>
        <div className="pic-grid">
          <PicturePick label="Your own picture" value={pic.desktop} onChange={(u) => set("picture", { ...pic, desktop: u })} />
          <PicturePick label="A phone's own (tall, if you like)" value={pic.mobile} onChange={(u) => set("picture", { ...pic, mobile: u })} />
        </div>
        {(pic.desktop || pic.mobile) && (
          <>
            <Range label="Darken it" value={pic.dim} min={0} max={90} unit="%" onChange={(v) => set("picture", { ...pic, dim: v })} />
            <Range label="Blur it" value={pic.blur} min={0} max={20} unit="px" onChange={(v) => set("picture", { ...pic, blur: v })} />
            <div className="field">
              <label>Fit</label>
              <div className="seg" role="group" aria-label="How the picture fits">
                {([["cover", "Fill"], ["contain", "Whole picture"], ["tile", "Tiles"]] as const).map(([v, label]) => (
                  <button key={v} className={pic.size === v ? "on" : ""} aria-pressed={pic.size === v} onClick={() => set("picture", { ...pic, size: v })}>{label}</button>
                ))}
              </div>
            </div>
          </>
        )}
      </section>

      <div className="scheme-save">
        <button className="btn primary" disabled={busy} onClick={() => save(true)}><Save size={15} /> Save and use it</button>
        <button className="btn" disabled={busy} onClick={() => save(false)}>Just save</button>
        <button className="btn ghost scheme-cancel" aria-label="Cancel" onClick={() => nav("/settings")}><X size={15} /><span>Cancel</span></button>
      </div>
    </div>
  );
}
