import { useQuery } from "@tanstack/react-query";
import { ChevronRight, Copy, LogOut, Network, Pencil, Plus, Server, Share2, Trash2, X } from "lucide-react";
import { type ReactNode, useEffect, useRef, useState } from "react";
import { queryClient } from "../actions";
import { ago, api } from "../api";
import { appVersion } from "../appUpdate";
import { useChatOn } from "../chat/store";
import { AvatarSettings } from "../components/Avatar";
import { castStatus } from "../components/CastButton";
import { SEARCH_ENGINES } from "../components/StationHistory";
import { Display, Kicker, Switch } from "../components/ui";
import { appPlayer, useShell } from "../player/app";
import { usePlayer } from "../store/player";
import { useUi } from "../store/ui";
import { type Colors, PALETTES, type Palette } from "../theme/palettes";
import { CUSTOM, type Scheme, type SchemeData, useSchemes } from "../theme/schemes";
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

/** Whether people here and on linked servers can find you in the chat and write to you. */
function ChatSettings() {
  const on = useChatOn();
  const user = useUi((s) => s.user);
  const setUser = useUi((s) => s.setUser);
  const [busy, setBusy] = useState(false);
  if (!on || !user) return null;
  const listed = !user.prefs.chat_hidden;
  return (
    <section className="panel">
      <div className="panel-head"><div><div className="kicker">Library Network</div><div className="h2">Messages</div></div></div>
      <div className="field">
        <label>Others can write to you</label>
        <div className="row-actions">
          <Switch checked={listed} label="Others can write to you" onChange={async (v) => {
            if (busy) return;
            setBusy(true);
            try {
              setUser({ ...user, prefs: await api.patch<Prefs>("/api/me/prefs", { chat_hidden: v ? null : true }) });
            } finally {
              setBusy(false);
            }
          }} />
          <span className="dim">
            {listed ? "People on this server and on linked servers find you under New message."
              : "You aren't listed, so nobody new can write to you. You can still write, and whoever you write to can answer."}
          </span>
        </div>
      </div>
    </section>
  );
}

interface Device { id: string; name: string; app: boolean; since: string | null; seen: string | null; current: boolean }

/** Downloads in the app: their format, whether they wait for wifi (on the phone), and what's downloaded. */
function DownloadSettings() {
  const ui = useUi();
  const { available, list } = useDownloads();
  const desktop = useShell((s) => !!s.desktop);
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
      {!desktop && (
        <div className="field">
          <label>Only on wifi</label>
          <div className="row-actions"><Switch checked={ui.downloadWifi} onChange={(v) => ui.setPref("download_wifi", v)} label="Only on wifi" />
            <span className="dim">Downloads wait for wifi instead of using mobile data.</span></div>
        </div>
      )}
      <div className="field">
        <label>{desktop ? "On this computer" : "On the phone"}</label>
        <div className="row-actions">
          <span className="dim">{list.length ? `${list.length} downloaded, ${fmtBytes(total)}` : "Nothing yet"}</span>
          <Link className="btn small" to="/downloads">Your downloads</Link>
        </div>
        <div className="help">Liked songs download by themselves once the Liked songs page's Download is on.</div>
      </div>
    </section>
  );
}

type PhoneFolder = { uri: string; name: string; songs: number };

/** The folders the Android app's own library reads (the app answers for them), and each taken out again. */
function PhoneFolders() {
  const list = useQuery({ queryKey: ["phone-folders"], queryFn: () => api.get<PhoneFolder[]>("/api/local/folders") });
  const notify = useUi((s) => s.notify);
  const remove = async (f: PhoneFolder) => {
    const songs = `${f.songs} song${f.songs === 1 ? "" : "s"}`;
    if (!confirm(`Take "${f.name}" out of this phone's library? The files stay on the phone; the library loses its ${songs}, with any likes and places in playlists.`)) return;
    try {
      await api.del(`/api/local/folders?uri=${encodeURIComponent(f.uri)}`);
      notify(`${f.name} is out of the library`);
    } catch (e) {
      notify((e as Error).message, "error");
    }
    queryClient.invalidateQueries();      // every list, as the library is now
  };
  return (
    <div className="field">
      <label>Music folders</label>
      {list.data?.length === 0 && <span className="dim">None yet: podcasts and radio play without one.</span>}
      <ul className="admin-list" style={{ marginTop: 0 }}>
        {(list.data || []).map((f) => (
          <li key={f.uri}>
            <div className="grow ellipsis">
              <b>{f.name}</b>
              <span className="faint"> · {f.songs} song{f.songs === 1 ? "" : "s"}</span>
            </div>
            <button className="btn small" onClick={() => remove(f)}><X size={14} /> Remove</button>
          </li>
        ))}
      </ul>
      <div style={{ marginTop: 8 }}><button className="btn small" onClick={() => appPlayer.addFolder()}><Plus size={14} /> Add a music folder</button></div>
      <div className="help">The app only reads them. A folder taken out stays on the phone as it is.</div>
    </div>
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

interface Tile { value: string; name: string; colors: Colors; sub?: string; actions?: ReactNode }

/** The color schemes in groups that open and close: the user's own and the ones others share first (while
 * the server has them), then the app's. The group with the scheme in use is open to begin with and names
 * it, and a filter opens every group it finds something in. */
export function SchemePicker({ value, onChange, dark }: { value: string; onChange: (slug: string) => void; dark: boolean }) {
  const [filter, setFilter] = useState("");
  const notify = useUi((s) => s.notify);
  const own = useQuery({
    queryKey: ["schemes"], retry: false,
    queryFn: async () => {
      const r = await api.get<{ mine: Scheme[]; shared: Scheme[] }>("/api/schemes");
      useSchemes.getState().meet([...r.mine, ...r.shared]);
      return r;
    },
  });
  const look = (d: SchemeData) => ((dark && d.modes !== "light") || d.modes === "dark" ? d.dark : d.light);
  const save = async (s: Scheme, shared: boolean) => {
    try {
      await api.put(`/api/schemes/${s.id}`, { name: s.name, data: s.data, shared });
      notify(shared ? `${s.name} is shared: everyone here can use it` : `${s.name} is only yours again`);
    } catch (e) {
      notify((e as Error).message, "error");
    }
    own.refetch();
  };
  const remove = async (s: Scheme) => {
    if (!confirm(`Delete your color scheme "${s.name}"?${s.uses > (value === CUSTOM + s.id ? 1 : 0) ? " Devices that use it go back to Muzix's own." : ""}`)) return;
    await api.del(`/api/schemes/${s.id}`).catch((e: Error) => notify(e.message, "error"));
    if (value === CUSTOM + s.id) onChange(s.data.base);
    own.refetch();
  };
  const groups: { key: string; label: string; tiles: Tile[] }[] = [
    ...(own.data ? [
      { key: "mine", label: "Your own", tiles: own.data.mine.map((s): Tile => ({
        value: CUSTOM + s.id, name: s.name, colors: look(s.data),
        sub: s.shared ? `Shared · on ${s.uses} device${s.uses === 1 ? "" : "s"}` : "Only you",
        actions: <>
          <Link className="mini" to={`/settings/schemes/${s.id}`} aria-label={`Change ${s.name}`} data-tip="Change it"><Pencil size={14} /></Link>
          <button className={`mini ${s.shared ? "liked" : ""}`} aria-label={s.shared ? "Stop sharing it" : "Share it with everyone here"}
                  aria-pressed={s.shared} data-tip={s.shared ? "Shared: click to stop" : "Share it with everyone here"} onClick={() => save(s, !s.shared)}>
            <Share2 size={14} />
          </button>
          <button className="mini" aria-label={`Delete ${s.name}`} data-tip="Delete it" onClick={() => remove(s)}><Trash2 size={14} /></button>
        </>,
      })) },
      { key: "shared", label: "Shared by others", tiles: own.data.shared.map((s): Tile => ({
        value: CUSTOM + s.id, name: s.name, colors: look(s.data), sub: `by ${s.owner.name}`,
        actions: <Link className="mini" to={`/settings/schemes/new?from=${s.id}`} aria-label={`Copy ${s.name} to change it`}
                       data-tip="Make a copy to change"><Copy size={14} /></Link>,
      })) },
    ] : []),
    ...GROUPS.map(([cat, label]) => ({
      key: cat, label,
      tiles: PALETTES.filter((p) => p.category === cat).map((p): Tile => ({ value: p.slug, name: p.name, colors: dark ? p.dark : p.light })),
    })),
  ];
  const groupOf = (v: string) => groups.find((g) => g.tiles.some((t) => t.value === v))?.key;
  const [open, setOpen] = useState(() => new Set<string>([PALETTES.find((p) => p.slug === value)?.category ?? (value.startsWith(CUSTOM) ? "mine" : "muzix")]));
  // the user's own scheme in use is in the list once the server has said whose it is
  const placed = useRef(false);
  useEffect(() => {
    const g = own.data && groupOf(value);
    if (g && !placed.current) {
      placed.current = true;
      setOpen((o) => new Set([...o, g]));
    }
  });
  const toggle = (key: string) => setOpen((o) => new Set(o.has(key) ? [...o].filter((k) => k !== key) : [...o, key]));
  const q = filter.trim().toLowerCase();
  const find = (text: string) => {
    setFilter(text);
    const f = text.trim().toLowerCase();
    if (f) setOpen((o) => new Set([...o, ...groups.filter((g) => g.tiles.some((t) => t.name.toLowerCase().includes(f))).map((g) => g.key)]));
  };
  const inUse = groups.flatMap((g) => g.tiles.map((t) => ({ g: g.key, t }))).find((x) => x.t.value === value);
  const base = value.startsWith(CUSTOM) ? useSchemes.getState().known[Number(value.slice(CUSTOM.length))]?.data.base : value;
  return (
    <div>
      <div className="row-actions" style={{ marginBottom: 10 }}>
        <input className="input" style={{ maxWidth: 320 }} placeholder={`Filter ${PALETTES.length} color schemes`}
               value={filter} onChange={(e) => find(e.target.value)} />
        {own.data && <Link className="btn small" to={`/settings/schemes/new?base=${base || "muzix"}`}><Plus size={14} /> Make your own</Link>}
      </div>
      {groups.map((g) => {
        const tiles = q ? g.tiles.filter((t) => t.name.toLowerCase().includes(q)) : g.tiles;
        if (!tiles.length && (q || g.key !== "mine")) return null;
        const shown = open.has(g.key);
        return (
          <div key={g.key} className="scheme-group">
            <button className="scheme-head" aria-expanded={shown} aria-controls={`schemes-${g.key}`} onClick={() => toggle(g.key)}>
              <ChevronRight size={14} className="chev" aria-hidden="true" />
              <span>{g.label} · {tiles.length}</span>
              {inUse?.g === g.key && <span className="in-use ellipsis">{inUse.t.name}</span>}
            </button>
            <div className="swatches" id={`schemes-${g.key}`} hidden={!shown}>
              {!tiles.length && <p className="dim" style={{ margin: 0, fontSize: 13 }}>None yet. Make one from any scheme: its colours, fonts, frame and a picture of your own.</p>}
              {tiles.map((t) => (
                <div key={t.value} className={`swatch ${value === t.value ? "active" : ""}`}>
                  <button className="swatch-pick" onClick={() => onChange(t.value)} data-tip={t.name} aria-pressed={value === t.value}>
                    <div className="strip" style={{ background: t.colors.bg }}>
                      {[t.colors.bg, t.colors.surface, t.colors.primary, t.colors.secondary, t.colors.success, t.colors.warning, t.colors.error, t.colors.text]
                        .map((x, i) => <span key={i} style={{ background: x }} />)}
                    </div>
                    <div className="name">{t.name}</div>
                    {t.sub && <div className="sub">{t.sub}</div>}
                  </button>
                  {t.actions && <div className="swatch-actions">{t.actions}</div>}
                </div>
              ))}
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
  const shell = useShell();
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
        <div className="panel-head"><div><div className="kicker">Performance</div><div className="h2">Potato mode</div></div></div>
        <div className="field">
          <label>On this device</label>
          <div className="row-actions">
            <Switch checked={ui.potato} onChange={ui.setPotato} label="Potato mode" />
            <span className="dim">Easier on the processor: a still background, no moving headlines or frames, no blur.</span>
          </div>
          {ui.potatoByItself && <div className="help">On by itself: this device draws without a graphics card (a virtual machine, say).</div>}
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
      <ChatSettings />

      <AvatarSettings />

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
          <div className="panel-head"><div><div className="kicker">{shell.desktop ? "Muzix Desktop" : "Android"}</div><div className="h2">The app</div></div></div>
          <div className="field">
            <label>Server</label>
            <div className="row-actions">
              {/* the app's own library is on 127.0.0.1, not a server's address */}
              <span className="dim">{shell.library === "local" ? `Now: this ${shell.desktop ? "computer" : "phone"}'s music` : location.host}</span>
              <button className="btn" onClick={() => appPlayer.changeServer()}><Server size={16} /> Change server</button>
            </div>
          </div>
          {/* Muzix Desktop keeps its folders in its own Settings, with the sharing switches */}
          {shell.library === "local" && !shell.desktop && <PhoneFolders />}
          <div className="field">
            <label>Version</label>
            <span className="dim">{shell.desktop ? "Muzix Desktop" : "Muzix for Android"} {appVersion()}. When a newer one is out, your menu offers it.</span>
          </div>
        </section>
      )}
    </div>
  );
}
