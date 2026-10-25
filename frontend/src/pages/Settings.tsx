import { useMemo, useState } from "react";
import { api } from "../api";
import { castStatus } from "../components/CastButton";
import { SEARCH_ENGINES } from "../components/StationHistory";
import { Display, Kicker, Switch } from "../components/ui";
import { usePlayer } from "../store/player";
import { useUi } from "../store/ui";
import { PALETTES, type Palette } from "../theme/palettes";
import { SKINS } from "../theme/skins";

const GROUPS: [Palette["category"], string][] = [["muzix", "Muzix"], ["builtin", "Built-in"], ["gaming", "Gaming"], ["community", "Community"]];

export function SchemePicker({ value, onChange, dark }: { value: string; onChange: (slug: string) => void; dark: boolean }) {
  const [filter, setFilter] = useState("");
  const list = useMemo(() => PALETTES.filter((p) => p.name.toLowerCase().includes(filter.toLowerCase())), [filter]);
  return (
    <div>
      <input className="input" style={{ maxWidth: 320, marginBottom: 14 }} placeholder={`Filter ${PALETTES.length} color schemes`}
             value={filter} onChange={(e) => setFilter(e.target.value)} />
      {GROUPS.map(([cat, label]) => {
        const items = list.filter((p) => p.category === cat);
        if (!items.length) return null;
        return (
          <div key={cat} style={{ marginBottom: 18 }}>
            <div className="kicker" style={{ marginBottom: 8 }}>{label} · {items.length}</div>
            <div className="swatches">
              {items.map((p) => {
                const c = dark ? p.dark : p.light;
                return (
                  <button key={p.slug} className={`swatch ${value === p.slug ? "active" : ""}`} onClick={() => onChange(p.slug)} title={p.name}>
                    <div className="strip" style={{ background: c.bg }}>
                      {[c.bg, c.surface, c.primary, c.secondary, c.success, c.warning, c.error, c.text].map((x, i) => <span key={i} style={{ background: x }} />)}
                    </div>
                    <div className="name ellipsis">{p.name}</div>
                  </button>
                );
              })}
            </div>
          </div>
        );
      })}
      <p className="faint" style={{ fontSize: 12 }}>
        The {PALETTES.length - 1} extra palettes come from claude-desktop-extra (MIT) and the Noctalia community palettes, each with a light and a dark version.
      </p>
    </div>
  );
}

export default function Settings() {
  const ui = useUi();
  const cast = usePlayer(castStatus);
  const dark = ui.mode === "dark" || (ui.mode === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  const [pw, setPw] = useState({ current: "", next: "" });
  const [pwMsg, setPwMsg] = useState("");
  return (
    <div className="page">
      <Kicker parts={["Your settings", ui.user?.username]} />
      <Display l1="Make it" l2="yours" small />

      <section className="panel">
        <div className="panel-head"><div><div className="kicker">Appearance</div><div className="h2">Look & feel</div></div></div>
        <div className="field">
          <label>Light or dark</label>
          <div className="subnav" style={{ margin: 0 }}>
            {(["system", "light", "dark"] as const).map((m) => (
              <button key={m} className={ui.mode === m ? "active" : ""} onClick={() => ui.setPref("mode", m)}>{m === "system" ? "Match system" : m}</button>
            ))}
          </div>
        </div>
        <div className="field">
          <label>Genre skins</label>
          <div className="row-actions">
            <Switch checked={ui.genreSkins} onChange={(v) => ui.setPref("genre_skins", v)} label="Genre skins" />
            <span className="dim">Restyle the whole app after the genre of what's playing (death metal, psytrance, jazz, chiptune…).</span>
          </div>
        </div>
        <div className="field">
          <label>Lock a skin</label>
          <select className="select" style={{ maxWidth: 320 }} value={ui.skinLock} onChange={(e) => ui.setPref("skin_lock", e.target.value)}>
            <option value="">Follow the music</option>
            {SKINS.map((s) => <option key={s.id} value={s.id}>{s.name}: {s.blurb}</option>)}
          </select>
          <div className="help">Pick one to keep it on regardless of what plays (handy for trying them all).</div>
        </div>
        <div className="field">
          <label>Color scheme (when no genre skin is showing)</label>
          <SchemePicker value={ui.scheme} onChange={(s) => ui.setPref("scheme", s)} dark={dark} />
        </div>
      </section>

      <section className="panel">
        <div className="panel-head"><div><div className="kicker">Playback</div><div className="h2">Sound</div></div></div>
        <div className="field">
          <label>Stream quality</label>
          <select className="select" style={{ maxWidth: 360 }} value={ui.quality} onChange={(e) => ui.setPref("quality", e.target.value as typeof ui.quality)}>
            <option value="original">Original (files as they are; hi-res capped by the server)</option>
            <option value="lossless">Lossless (FLAC)</option>
            <option value="high">High (Opus 160-192 kbit/s, for slow connections)</option>
            <option value="low">Data saver (Opus 96 kbit/s)</option>
          </select>
        </div>
        <div className="field">
          <label>Visualizer & reactive backgrounds</label>
          <div className="row-actions"><Switch checked={ui.visualizer} onChange={(v) => ui.setPref("visualizer", v)} label="Visualizer" />
            <span className="dim">Skin backgrounds and the now-playing view move with the music.</span></div>
        </div>
        <div className="field">
          <label>Searching for a song</label>
          <select className="select" style={{ maxWidth: 360 }} aria-label="Search engine"
                  value={SEARCH_ENGINES.some(([, u]) => u === ui.searchEngine) ? ui.searchEngine : "custom"}
                  onChange={(e) => ui.setPref("search_engine", e.target.value === "custom" ? "https://example.com/search?q=%s" : e.target.value)}>
            {SEARCH_ENGINES.map(([name, url]) => <option key={url} value={url}>{name}</option>)}
            <option value="custom">Another engine…</option>
          </select>
          {!SEARCH_ENGINES.some(([, u]) => u === ui.searchEngine) && (
            <input className="input" style={{ maxWidth: 360 }} value={ui.searchEngine} aria-label="Search address"
                   onChange={(e) => ui.setPref("search_engine", e.target.value)} />
          )}
          <div className="help">The Web button in a station's history searches here. Muzix can't use your browser's own default engine, so pick it here; for another engine, give its search address with %s where the words go.</div>
        </div>
        <div className="field">
          <label>Cast to speakers</label>
          <span className="dim">{cast}</span>
        </div>
      </section>

      <section className="panel">
        <div className="panel-head"><div><div className="kicker">Account</div><div className="h2">Password</div></div></div>
        <div style={{ display: "grid", gap: 10, maxWidth: 360 }}>
          <input className="input" type="password" placeholder="Current password" autoComplete="current-password" value={pw.current} onChange={(e) => setPw({ ...pw, current: e.target.value })} />
          <input className="input" type="password" placeholder="New password (6+ characters)" autoComplete="new-password" value={pw.next} onChange={(e) => setPw({ ...pw, next: e.target.value })} />
          <div className="row-actions">
            <button className="btn accent" disabled={pw.next.length < 6} onClick={async () => {
              try {
                await api.post("/api/me/password", { current: pw.current, new: pw.next });
                setPwMsg("Password changed.");
                setPw({ current: "", next: "" });
              } catch (e) {
                setPwMsg((e as Error).message);
              }
            }}>Change password</button>
            {pwMsg && <span className="dim">{pwMsg}</span>}
          </div>
        </div>
      </section>
    </div>
  );
}
