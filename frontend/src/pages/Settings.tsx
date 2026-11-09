import { useQuery } from "@tanstack/react-query";
import { LogOut, Network, Plus, Server, X } from "lucide-react";
import { useMemo, useState } from "react";
import { queryClient } from "../actions";
import { ago, api } from "../api";
import { appVersion } from "../appUpdate";
import { castStatus } from "../components/CastButton";
import { SEARCH_ENGINES } from "../components/StationHistory";
import { Display, Kicker, Switch } from "../components/ui";
import { appPlayer } from "../player/app";
import { usePlayer } from "../store/player";
import { useUi } from "../store/ui";
import { PALETTES, type Palette } from "../theme/palettes";
import { SKINS } from "../theme/skins";
import { Link } from "react-router-dom";
import { fmtBytes, useDownloads } from "../downloads";
import type { Prefs } from "../types";

const GROUPS: [Palette["category"], string][] = [["muzix", "Muzix"], ["builtin", "Built-in"], ["gaming", "Gaming"], ["community", "Community"]];

/** The linked servers' music (the Library Network): in everyone's library, unless they leave it out. */
function NetworkMusic() {
  const linking = useUi((s) => s.modules.network);
  const servers = useQuery({ queryKey: ["network-servers"], enabled: linking, queryFn: () => api.get<string[]>("/api/network/servers") });
  const user = useUi((s) => s.user);
  const setUser = useUi((s) => s.setUser);
  const [busy, setBusy] = useState(false);
  const names = servers.data || [];
  if (!linking || !names.length || !user) return null;
  const on = user.prefs.network !== false;
  const who = names.length > 1 ? `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}` : names[0];
  return (
    <section className="panel">
      <div className="panel-head"><div><div className="kicker">Library Network</div><div className="h2">Other libraries</div></div></div>
      <div className="field">
        <label>Music from linked servers</label>
        <div className="row-actions">
          <Switch checked={on} label="Music from linked servers" onChange={async (v) => {
            if (busy) return;
            setBusy(true);
            try {
              const prefs = await api.patch<Prefs>("/api/me/prefs", { network: v ? null : false });
              setUser({ ...user, prefs });
              queryClient.invalidateQueries();      // every list, as the library is now
            } finally {
              setBusy(false);
            }
          }} />
          <span className="dim">
            {on ? <>The albums, songs and audiobooks of {who} are in your library, with <Network size={13} style={{ verticalAlign: "-2px" }} /> on their covers.</>
              : <>Only this server's own library: the music of {who} is left out.</>}
          </span>
        </div>
      </div>
    </section>
  );
}

interface Device { id: string; name: string; app: boolean; since: string | null; seen: string | null; current: boolean }

/** Downloads in the app: their format, whether they wait for wifi, and what's on the phone. */
function DownloadSettings() {
  const ui = useUi();
  const { available, list } = useDownloads();
  if (!available) return null;
  const total = list.reduce((n, d) => n + d.bytes, 0);
  return (
    <section className="panel">
      <div className="panel-head"><div><div className="kicker">This device</div><div className="h2">Downloads</div></div></div>
      <div className="field">
        <label>Format</label>
        <select className="select" style={{ maxWidth: 360 }} aria-label="Download format" value={ui.downloadFormat}
                onChange={(e) => ui.setPref("download_format", e.target.value as typeof ui.downloadFormat)}>
          <option value="smaller">Smaller (Opus at the server's bitrate)</option>
          <option value="original">Original (the files as they are)</option>
        </select>
        <div className="help">For what's downloaded from now on.</div>
      </div>
      <div className="field">
        <label>Only on wifi</label>
        <div className="row-actions"><Switch checked={ui.downloadWifi} onChange={(v) => ui.setPref("download_wifi", v)} label="Only on wifi" />
          <span className="dim">Downloads wait for wifi instead of using mobile data.</span></div>
      </div>
      <div className="field">
        <label>On the phone</label>
        <div className="row-actions">
          <span className="dim">{list.length ? `${list.length} downloaded, ${fmtBytes(total)}` : "Nothing yet"}</span>
          <Link className="btn small" to="/downloads">Your downloads</Link>
        </div>
        <div className="help">Liked songs download by themselves once the Liked songs page's Download is on.</div>
      </div>
    </section>
  );
}

/** Where the account is signed in (each browser, each app), and each signed out from here. */
function Devices() {
  const list = useQuery({ queryKey: ["devices"], queryFn: () => api.get<Device[]>("/api/me/devices") });
  const notify = useUi((s) => s.notify);
  const signOut = async (d: Device) => {
    try {
      await api.del(`/api/me/devices/${d.id}`);
      notify(`${d.name} is signed out`);
    } catch (e) {
      notify((e as Error).message, "error");
    }
    list.refetch();
  };
  return (
    <section className="panel">
      <div className="panel-head"><div><div className="kicker">Account</div><div className="h2">Devices</div></div></div>
      <p className="dim">Where you're signed in. A device signed out here has to sign in again.</p>
      <ul className="admin-list">
        {(list.data || []).map((d) => (
          <li key={d.id}>
            <div className="grow ellipsis">
              <b>{d.name}</b>
              <span className="faint"> · {d.current ? "this device" : `seen ${ago(d.seen)}`}</span>
            </div>
            {!d.current && <button className="btn small" onClick={() => signOut(d)}><LogOut size={14} /> Sign out</button>}
          </li>
        ))}
      </ul>
    </section>
  );
}

/** The device's own tag → skin rules: a tag in a song's genre or its artist's tags picks that skin, before
 * the built-in rules. */
function SkinRules() {
  const rules = useUi((s) => s.skinRules);
  const setPref = useUi((s) => s.setPref);
  const [rows, setRows] = useState<[string, string][]>(() => Object.entries(rules));
  const save = (next: [string, string][]) => {
    setRows(next);
    setPref("skin_map", Object.fromEntries(next.filter(([tag]) => tag.trim()).map(([tag, skin]) => [tag.trim().toLowerCase(), skin])));
  };
  return (
    <div className="field">
      <label>Your skin rules</label>
      <div style={{ display: "grid", gap: 8 }}>
        {rows.map(([tag, skin], i) => (
          <div key={i} className="row-actions">
            <input className="input" style={{ maxWidth: 200 }} aria-label="Tag" placeholder="melodeath" value={tag}
                   onChange={(e) => save(rows.map((r, j) => (j === i ? [e.target.value, r[1]] : r)))} />
            <select className="select" style={{ maxWidth: 240 }} aria-label="Skin" value={skin}
                    onChange={(e) => save(rows.map((r, j) => (j === i ? [r[0], e.target.value] : r)))}>
              {SKINS.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
            <button className="btn small" onClick={() => save(rows.filter((_, j) => j !== i))}><X size={14} /> Remove</button>
          </div>
        ))}
        <div><button className="btn small" onClick={() => setRows([...rows, ["", SKINS[0].id]])}><Plus size={14} /> Add a rule</button></div>
      </div>
      <div className="help">A tag in a song's genre or its artist's tags picks that skin before the built-in rules do (melodeath → Death metal).</div>
    </div>
  );
}

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
                  <button key={p.slug} className={`swatch ${value === p.slug ? "active" : ""}`} onClick={() => onChange(p.slug)} data-tip={p.name}>
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
        <SkinRules />
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
          <label>Autoplay</label>
          <div className="row-actions"><Switch checked={ui.autoplay} onChange={(v) => ui.setPref("autoplay", v)} label="Autoplay" />
            <span className="dim">When your music runs out, keep playing similar songs, picked by their genre tags (for game music: the same chips).</span></div>
        </div>
        <div className="field">
          <label>Visualizer & reactive backgrounds</label>
          <div className="row-actions"><Switch checked={ui.visualizer} onChange={(v) => ui.setPref("visualizer", v)} label="Visualizer" />
            <span className="dim">Skin backgrounds and the now-playing view move with the music.</span></div>
        </div>
        <div className="field">
          <label>Radio buffer</label>
          <select className="select" style={{ maxWidth: 360 }} aria-label="Radio buffer" value={ui.radioBuffer}
                  onChange={(e) => ui.setPref("radio_buffer", Number(e.target.value))}>
            <option value={0}>Start at once</option>
            {[3, 8, 15, 30].map((s) => <option key={s} value={s}>{s} seconds</option>)}
          </select>
          <div className="help">A station waits this long before it starts, then plays through dropouts in your connection this long, a little behind live. A station that still stalls reconnects by itself.</div>
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

      <DownloadSettings />

      <NetworkMusic />

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

      <Devices />

      {appPlayer.available && (
        <section className="panel">
          <div className="panel-head"><div><div className="kicker">Android</div><div className="h2">The app</div></div></div>
          <div className="field">
            <label>Server</label>
            <div className="row-actions">
              <span className="dim">{location.host}</span>
              <button className="btn" onClick={() => appPlayer.changeServer()}><Server size={16} /> Change server</button>
            </div>
          </div>
          <div className="field">
            <label>Version</label>
            <span className="dim">Muzix for Android {appVersion()}. When a newer one is out, your menu offers it.</span>
          </div>
        </section>
      )}
    </div>
  );
}
