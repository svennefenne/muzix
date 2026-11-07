/** Admin → Library Network: this server's sharing code, and the Muzix servers it shares its library
 * with (backend/muzix/network.py). A link takes both admins: each enters the other's code. Computers
 * share folders through the desktop client (backend/muzix/tunnel.py): their owner enters this
 * server's code in the client, and the admin says yes with the code the client shows. */

import { useQuery } from "@tanstack/react-query";
import { Check, Copy, Laptop, Link2, RefreshCw, Server, Trash2, X } from "lucide-react";
import { useState } from "react";
import { ago, api, fmtNumber } from "../../api";
import { Empty, Loading } from "../../components/ui";
import { useUi } from "../../store/ui";

interface Peer {
  id: number; name: string; address: string; state: "linked" | "waiting" | "asked";
  kind: "server" | "computer"; online: boolean;     // a computer's music shows only while it's on
  linked_at: string | null; last_seen: string | null; created_at: string | null; synced_at: string | null;
  counts: Partial<Record<"albums" | "tracks" | "books" | "playlists", number>>; error: string;
}

/** What a linked server shares, as of its last sync: "12 albums · 140 songs · 1 audiobook". */
function shares(c: Peer["counts"]) {
  const n = (k: keyof Peer["counts"], one: string, many: string) => (c[k] ? `${fmtNumber(c[k]!)} ${c[k] === 1 ? one : many}` : "");
  return [n("albums", "album", "albums"), n("tracks", "song", "songs"), n("books", "audiobook", "audiobooks"),
    n("playlists", "playlist file", "playlist files")].filter(Boolean).join(" · ") || "nothing shared yet";
}
interface Overview {
  name: string; code: string | null; address: string; peers: Peer[];
  main: number | null;                              // the main library (null: this server's)
  copies: { albums: number; books: number };        // other libraries' copies, not listed
}

/** Where the admin's browser reaches this server: what the other one is told, unless Settings has a public URL. */
const ownAddress = () => location.origin;

function useLink(reload: () => void) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const link = async (address: string, code: string) => {
    setBusy(true);
    setErr("");
    try {
      const p = await api.post<Peer>("/api/network/peers", { address, code, own_address: ownAddress() });
      reload();
      return p;
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return { busy, err, link };
}

function ThisServer({ net, reload }: { net: Overview; reload: () => void }) {
  const notify = useUi((s) => s.notify);
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(net.code!);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      notify("Couldn't copy here: select the code and copy it", "error");
    }
  };
  return (
    <section className="panel">
      <div className="panel-head"><div className="h3">This server's sharing code</div></div>
      {net.code ? (
        <>
          <p className="dim" style={{ marginTop: 0 }}>
            Give it to the admin of the server you want to link with, with this server's address
            ({net.address || ownAddress()}). They enter it on their server, and you enter theirs here: both are needed.
          </p>
          <div className="row-actions">
            <code className="share-code mono">{net.code}</code>
            <button className="btn" onClick={copy}>{copied ? <Check size={15} /> : <Copy size={15} />} Copy</button>
            <button className="btn ghost" onClick={async () => {
              if (!confirm("Make a new code? The old one no longer links; the links there are stay.")) return;
              await api.post("/api/network/code");
              reload();
            }}><RefreshCw size={15} /> New code</button>
            <button className="btn ghost" onClick={async () => {
              if (!confirm("Turn the Library Network off? No one can ask to link until it's on again; the links there are stay.")) return;
              await api.del("/api/network/code");
              reload();
            }}>Turn off</button>
          </div>
          {!net.address && (
            <p className="faint" style={{ fontSize: 12.5, marginBottom: 0 }}>
              Other servers are told {ownAddress()}. If they reach this one at another address, set the Public URL in Settings.
            </p>
          )}
          <p className="faint" style={{ fontSize: 12.5, marginBottom: 0 }}>
            Someone without a server of their own can share folders on their computer with the Muzix desktop client: they enter
            this server's HTTPS address and this code in it, and you enter the code their client shows.
          </p>
        </>
      ) : (
        <>
          <p className="dim" style={{ marginTop: 0 }}>
            Link this library with other Muzix servers to share your music with each other. Turning it on makes a sharing
            code; a link takes both admins entering each other's.
          </p>
          <button className="btn accent" onClick={async () => { await api.post("/api/network/code"); reload(); }}>
            <Link2 size={15} /> Turn on the Library Network
          </button>
        </>
      )}
    </section>
  );
}

function LinkForm({ reload }: { reload: () => void }) {
  const [address, setAddress] = useState("");
  const [code, setCode] = useState("");
  const { busy, err, link } = useLink(reload);
  const notify = useUi((s) => s.notify);
  return (
    <section className="panel">
      <div className="panel-head"><div className="h3">Link with another server</div></div>
      <div className="row-actions">
        <input className="input" style={{ flex: 2, minWidth: 220 }} placeholder="Its address: 192.168.1.20:8484 or muzix.example.com"
               value={address} onChange={(e) => setAddress(e.target.value)} />
        <input className="input mono" style={{ flex: 1, minWidth: 250 }} placeholder="XXXXX-XXXXX-XXXXX-XXXXX" spellCheck={false}
               value={code} onChange={(e) => setCode(e.target.value.toUpperCase())} />
        <button className="btn accent" disabled={busy || !address.trim() || !code.trim()} onClick={async () => {
          const p = await link(address, code);
          if (!p) return;
          setAddress("");
          setCode("");
          notify(p.state === "linked" ? `Linked with ${p.name}` : `${p.name} took the code: now its admin enters this server's`);
        }}><Link2 size={15} /> Link</button>
      </div>
      {err && <p className="error-text">{err}</p>}
    </section>
  );
}

/** Yes to a computer's request: the code its desktop client shows. */
function useAccept(p: Peer, reload: () => void) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const accept = async (code: string) => {
    setBusy(true);
    setErr("");
    try {
      await api.post(`/api/network/peers/${p.id}/accept`, { code });
      reload();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return { busy, err, accept };
}

function PeerRow({ p, reload }: { p: Peer; reload: () => void }) {
  const [code, setCode] = useState("");
  const linking = useLink(reload);
  const accepting = useAccept(p, reload);
  const computer = p.kind === "computer";
  const { busy, err } = computer ? accepting : linking;
  const remove = async (ask: string) => {
    if (!confirm(ask)) return;
    await api.del(`/api/network/peers/${p.id}`);
    reload();
  };
  const notify = useUi((s) => s.notify);
  const away = computer && p.state === "linked" && !p.online;
  const what = away ? `off${p.last_seen ? ` since ${ago(p.last_seen)}` : ""} · its music is hidden until it's on`
    : p.state === "linked" ? (p.synced_at ? `${shares(p.counts)} · synced ${ago(p.synced_at)}` : "linked · fetching its library…")
    : p.state === "waiting" ? "waiting for its admin to enter this server's code" : `asked to link ${p.created_at ? ago(p.created_at) : ""}`;
  const Icon = computer ? Laptop : Server;
  return (
    <div className="list-row" style={{ display: "block" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <span className={`status-dot ${p.state === "linked" && !away ? (p.error ? "bad" : "ok") : "queued"}`} />
        <div className="grow" style={{ minWidth: 200 }}>
          <div style={{ fontWeight: 700, display: "flex", alignItems: "center", gap: 6 }}><Icon size={14} aria-hidden /> {p.name}</div>
          <div className="faint" style={{ fontSize: 12, wordBreak: "break-all" }}>
            {computer ? `A computer, through the desktop client · ${p.online ? "on" : "off"}` : p.address || "no address"}
          </div>
          <div className="dim" style={{ fontSize: 12.5 }}>{what}</div>
          {p.error && <div className="error-text" style={{ fontSize: 12.5 }}>{p.error}</div>}
        </div>
        {p.state === "linked" && (
          <>
            <button className="btn small" disabled={away} onClick={async () => {
              await api.post(`/api/network/peers/${p.id}/sync`);
              notify(`Fetching ${p.name}'s library`);
            }}><RefreshCw size={14} /> Sync now</button>
            <button className="mini" aria-label="Unlink" data-tip="Unlink" onClick={() => remove(`Unlink ${p.name}? Its music leaves this library, and yours leaves its.`)}>
              <Trash2 size={15} />
            </button>
          </>
        )}
        {p.state === "waiting" && <button className="btn small ghost" onClick={() => remove(`Take back the request to ${p.name}?`)}>Cancel</button>}
      </div>
      {p.state === "asked" && (
        <>
          <p className="dim" style={{ fontSize: 13, margin: "10px 0" }}>
            {computer ? `${p.name} wants to share music from its folders with this server. To say yes, enter the code its Muzix desktop client shows under Settings → Servers.`
              : `${p.name} has entered this server's code. To link, enter its code (its admin finds it under Admin → Library Network).`}
          </p>
          <div className="row-actions">
            <input className="input mono" style={{ flex: 1, minWidth: 250 }} placeholder="Its code: XXXXX-XXXXX-XXXXX-XXXXX" spellCheck={false}
                   value={code} onChange={(e) => setCode(e.target.value.toUpperCase())} />
            {computer ? <button className="btn accent" disabled={busy || !code.trim()} onClick={() => accepting.accept(code)}><Check size={15} /> Accept</button>
              : <button className="btn accent" disabled={busy || !code.trim() || !p.address} onClick={() => linking.link(p.address, code)}><Link2 size={15} /> Link</button>}
            <button className="btn ghost" onClick={() => remove(`Turn down ${p.name}'s request?`)}><X size={15} /> Turn down</button>
          </div>
          {err && <p className="error-text">{err}</p>}
        </>
      )}
    </div>
  );
}

/** Whose copy of an album shows when more than one library has it (backend/muzix/mirror.py: dedupe). */
function MainLibrary({ net, reload }: { net: Overview; reload: () => void }) {
  const [busy, setBusy] = useState(false);
  const linked = net.peers.filter((p) => p.state === "linked");
  if (!linked.length) return null;
  const choose = async (peer_id: number | null) => {
    setBusy(true);
    try {
      await api.put("/api/network/main", { peer_id });
      reload();
    } finally {
      setBusy(false);
    }
  };
  const { albums, books } = net.copies;
  const counted = [albums && `${fmtNumber(albums)} ${albums === 1 ? "album" : "albums"}`,
    books && `${fmtNumber(books)} ${books === 1 ? "audiobook" : "audiobooks"}`].filter(Boolean).join(" and ");
  return (
    <section className="panel">
      <div className="panel-head"><div className="h3">Main library</div></div>
      <p className="dim" style={{ marginTop: 0 }}>
        When more than one library has the same album or audiobook, only one copy is listed: the main library's. When it
        doesn't have it, this server's comes next, then the others in the order they were linked. Songs someone liked or put
        in a playlist stay as they were.
      </p>
      <div className="list">
        {[{ id: null, name: `${net.name} (this server)` }, ...linked].map((l) => (
          <label key={l.id ?? "here"} className="list-row" style={{ cursor: busy ? "progress" : "pointer" }}>
            <input type="radio" name="main-library" disabled={busy} checked={net.main === l.id} onChange={() => choose(l.id)} />
            <span className="grow" style={{ fontWeight: net.main === l.id ? 700 : 400 }}>{l.name}</span>
            {net.main === l.id && <span className="badge accent">Main</span>}
          </label>
        ))}
      </div>
      <p className="faint" style={{ fontSize: 12.5, marginBottom: 0 }}>
        {counted ? `${counted} ${albums + books === 1 ? "is a copy" : "are copies"} another library has first, so ${albums + books === 1 ? "it isn't" : "they aren't"} listed.`
          : "No album or audiobook is in more than one library."}
      </p>
    </section>
  );
}

export function LibraryNetwork() {
  const net = useQuery({ queryKey: ["network"], queryFn: () => api.get<Overview>("/api/network"), refetchInterval: 10000 });
  if (!net.data) return <Loading />;
  const reload = () => net.refetch();
  const peers = net.data.peers;
  return (
    <>
      <ThisServer net={net.data} reload={reload} />
      {net.data.code && <LinkForm reload={reload} />}
      <section className="panel">
        <div className="panel-head"><div className="h3">Servers and computers in the network</div></div>
        {peers.length ? <div className="list">{peers.map((p) => <PeerRow key={p.id} p={p} reload={reload} />)}</div>
          : <Empty title="No other servers or computers yet" />}
      </section>
      <MainLibrary net={net.data} reload={reload} />
    </>
  );
}
