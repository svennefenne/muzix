import { CloudOff, Trash2 } from "lucide-react";
import { Link } from "react-router-dom";
import { Art, Display, Empty, Kicker } from "../components/ui";
import { fmtBytes, useDownloads } from "../downloads";
import { appPlayer } from "../player/app";

const KIND: Record<string, string> = { album: "Album", playlist: "Playlist", book: "Audiobook", episode: "Episode", liked: "Liked songs" };

/** What's on the phone, in the app: each download, how far it has come, its size, and removing it. Offline,
 * the app's home: only these play then. */
export default function Downloads() {
  const { list, offline } = useDownloads();
  const total = list.reduce((n, d) => n + d.bytes, 0);
  return (
    <div className="page">
      <Kicker parts={[offline ? "Offline" : "On the phone", list.length ? fmtBytes(total) : undefined]} />
      <Display l1="Your" l2="downloads" small />
      {offline && (
        <p className="lede row-actions"><CloudOff size={18} /> The server can't be reached: what's downloaded plays from the phone.</p>
      )}
      {list.length ? (
        <ul className="admin-list">
          {list.map((d) => (
            <li key={d.id}>
              <Link to={d.path} className="row-actions grow ellipsis" style={{ gap: 12 }}>
                <div style={{ width: 48, flex: "none" }}><Art src={d.art || null} name={d.title} size={96} /></div>
                <div className="ellipsis">
                  <b>{d.title}</b>
                  <div className="faint ellipsis">
                    {KIND[d.kind]}{d.subtitle ? ` · ${d.subtitle}` : ""} · {d.done < d.total ? `${d.done} of ${d.total} downloaded` : fmtBytes(d.bytes)}
                    {d.failed > 0 && ` · ${d.failed} couldn't be downloaded`}
                  </div>
                </div>
              </Link>
              <button className="btn small" onClick={() => confirm(`Remove "${d.title}" from the phone?`) && appPlayer.undownload(d.id)}>
                <Trash2 size={14} /> Remove
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <Empty title="Nothing downloaded yet">Download an album, a playlist, an audiobook or an episode from its page, and it plays without the server.</Empty>
      )}
    </div>
  );
}
