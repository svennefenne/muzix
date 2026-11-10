import { ArrowDownToLine, CircleCheck } from "lucide-react";
import { type Collection, fmtBytes, useDownloaded, useDownloads } from "../downloads";
import { appPlayer, useShell } from "../player/app";
import { useUi } from "../store/ui";

/** Download to the phone or the computer, in the app: an album, a playlist, a book, an episode or the liked
 * songs, the collection made when it's asked for (the full list of songs, the page's data). Downloaded, a
 * click takes it off again. Not while the app shows its own library: those songs are already here. */
export function DownloadButton({ id, title, make }: { id: string; title: string; make: () => Promise<Collection> | Collection }) {
  const available = useDownloads((s) => s.available);
  const here = useShell((s) => (s.library === "local" ? null : s.desktop ? "this computer" : "the phone"));
  const d = useDownloaded(id);
  const notify = useUi((s) => s.notify);
  if (!available || !here) return null;
  if (d) {
    const busy = d.done < d.total;
    return (
      <button className={`btn ${busy ? "" : "accent"}`}
              data-tip={busy ? `Downloading to ${here}: click to stop and remove it` : `On ${here} (${fmtBytes(d.bytes)}): click to remove it`}
              onClick={() => {
                if (!confirm(`Remove "${title}" from ${here}? It still plays from the server.`)) return;
                appPlayer.undownload(id);
              }}>
        {busy ? <><ArrowDownToLine size={15} /> {d.done} / {d.total}</> : <><CircleCheck size={15} /> Downloaded</>}
      </button>
    );
  }
  return (
    <button className="btn" data-tip={`Download to ${here}: it plays without the server, offline too`}
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
