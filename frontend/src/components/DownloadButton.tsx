import { ArrowDownToLine, CircleCheck } from "lucide-react";
import { type Collection, fmtBytes, useDownloaded, useDownloads } from "../downloads";
import { appPlayer } from "../player/app";
import { useUi } from "../store/ui";

/** Download to the phone, in the app: an album, a playlist, a book, an episode or the liked songs, the
 * collection made when it's asked for (the full list of songs, the page's data). Downloaded, a click takes
 * it off the phone. */
export function DownloadButton({ id, title, make }: { id: string; title: string; make: () => Promise<Collection> | Collection }) {
  const available = useDownloads((s) => s.available);
  const d = useDownloaded(id);
  const notify = useUi((s) => s.notify);
  if (!available) return null;
  if (d) {
    const busy = d.done < d.total;
    return (
      <button className={`btn ${busy ? "" : "accent"}`}
              data-tip={busy ? "Downloading to the phone: click to stop and remove it" : `On the phone (${fmtBytes(d.bytes)}): click to remove it`}
              onClick={() => {
                if (!confirm(`Remove "${title}" from the phone? It still plays from the server.`)) return;
                appPlayer.undownload(id);
              }}>
        {busy ? <><ArrowDownToLine size={15} /> {d.done} / {d.total}</> : <><CircleCheck size={15} /> Downloaded</>}
      </button>
    );
  }
  return (
    <button className="btn" data-tip="Download to the phone: it plays without the server, offline too"
            onClick={async () => {
              try {
                appPlayer.download(await make());
              } catch (e) {
                notify((e as Error).message, "error");
              }
            }}>
      <ArrowDownToLine size={15} /> Download
    </button>
  );
}
