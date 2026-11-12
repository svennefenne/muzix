import { ArrowDownToLine, CircleCheck } from "lucide-react";
import { type Collection, fmtBytes, useDownloaded, useDownloads } from "../downloads";
import { appPlayer, useShell } from "../player/app";
import { useUi } from "../store/ui";
import type { MenuItem } from "./ui";

type Make = () => Promise<Collection> | Collection;

/** What downloading something does where it shows: null where it can't (not in the app, or while the app shows
 * its own library: those songs are already here), else its state, the tip for it and what a click does. */
function useDownload(id: string, title: string, make: Make) {
  const available = useDownloads((s) => s.available);
  const here = useShell((s) => (s.library === "local" ? null : s.desktop ? "this computer" : "the phone"));
  const d = useDownloaded(id);
  const notify = useUi((s) => s.notify);
  if (!available || !here) return null;
  if (d) {
    const busy = d.done < d.total;
    return {
      state: busy ? ("busy" as const) : ("done" as const), done: d.done, total: d.total,
      tip: busy ? `Downloading to ${here}: click to stop and remove it` : `On ${here} (${fmtBytes(d.bytes)}): click to remove it`,
      run: () => {
        if (!confirm(`Remove "${title}" from ${here}? It still plays from the server.`)) return;
        appPlayer.undownload(id);
      },
    };
  }
  return {
    state: "none" as const, done: 0, total: 0, tip: `Download to ${here}: it plays without the server, offline too`,
    run: async () => {
      try {
        appPlayer.download(await make());
      } catch (e) {
        notify((e as Error).message, "error");
      }
    },
  };
}

/** Download to the phone or the computer, in the app: an album, a playlist, a book, an episode or the liked
 * songs, the collection made when it's asked for (the full list of songs, the page's data). Downloaded, a
 * click takes it off again. */
export function DownloadButton({ id, title, make }: { id: string; title: string; make: Make }) {
  const d = useDownload(id, title, make);
  if (!d) return null;
  return (
    <button className={`btn ${d.state === "done" ? "accent" : ""}`} data-tip={d.tip} onClick={() => void d.run()}>
      {d.state === "busy" ? <><ArrowDownToLine size={15} /> {d.done} / {d.total}</>
        : d.state === "done" ? <><CircleCheck size={15} /> Downloaded</> : <><ArrowDownToLine size={15} /> Download</>}
    </button>
  );
}

/** The same as an item of a menu (the album's in the Android app), or null where there's nothing to download. */
export function useDownloadItem(id: string, title: string, make: Make): MenuItem | null {
  const d = useDownload(id, title, make);
  if (!d) return null;
  return {
    label: d.state === "busy" ? `Downloading ${d.done} / ${d.total}: stop` : d.state === "done" ? "Remove download" : "Download",
    icon: d.state === "done" ? <CircleCheck size={16} /> : <ArrowDownToLine size={16} />,
    onClick: () => void d.run(),
  };
}
