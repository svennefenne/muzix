/** What a station played while you listened: the last 100 songs, as the server's radio relay
 * heard them announced, each with a quick search on YouTube or the web. */

import { useQuery } from "@tanstack/react-query";
import { Globe, SquarePlay, X } from "lucide-react";
import { create } from "zustand";
import { api } from "../api";
import { useUi } from "../store/ui";
import { Empty, Loading, Modal } from "./ui";

/** Web pages can't reach the browser's own default engine, so Muzix keeps a choice of its own. */
export const SEARCH_ENGINES: [string, string][] = [
  ["Google", "https://www.google.com/search?q=%s"],
  ["DuckDuckGo", "https://duckduckgo.com/?q=%s"],
  ["Bing", "https://www.bing.com/search?q=%s"],
  ["Startpage", "https://www.startpage.com/do/search?q=%s"],
  ["Ecosia", "https://www.ecosia.org/search?q=%s"],
  ["Brave Search", "https://search.brave.com/search?q=%s"],
];

export const useStationHistory = create<{
  station: { key: string; name: string } | null;
  show: (key: string, name: string) => void;
  close: () => void;
}>((set) => ({
  station: null,
  show: (key, name) => set({ station: { key, name } }),
  close: () => set({ station: null }),
}));

const youtube = (title: string) => `https://www.youtube.com/results?search_query=${encodeURIComponent(title)}`;
const web = (template: string, title: string) => template.replace("%s", encodeURIComponent(title));

function when(at: string) {
  const d = new Date(at);
  const time = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const days = Math.round((new Date().setHours(0, 0, 0, 0) - new Date(at).setHours(0, 0, 0, 0)) / 86_400_000);
  if (days === 0) return time;
  if (days === 1) return `Yesterday ${time}`;
  return `${d.toLocaleDateString([], { day: "numeric", month: "short" })} ${time}`;
}

export function StationHistory() {
  const { station, close } = useStationHistory();
  const engine = useUi((s) => s.searchEngine);
  const q = useQuery({
    queryKey: ["radio-history", station?.key], enabled: !!station, refetchInterval: 20_000,
    queryFn: () => api.get<{ title: string; at: string }[]>("/api/radio/history", { station: station!.key }),
  });
  if (!station) return null;
  return (
    <Modal onClose={close}>
      <div className="sh-head">
        <div style={{ minWidth: 0 }}>
          <h2 className="h3 ellipsis">Played on {station.name}</h2>
          <p className="dim">The last 100 songs while you listened</p>
        </div>
        <button className="iconbtn" aria-label="Close" onClick={close}><X size={16} /></button>
      </div>
      {q.isLoading ? <Loading /> : q.data?.length ? (
        <ol className="sh-list">
          {q.data.map((p, i) => (
            <li key={`${p.at}-${i}`} className="sh-row">
              <span className="sh-when">{when(p.at)}</span>
              <span className="sh-title">{p.title}</span>
              <span className="sh-actions">
                <a className="btn small" href={youtube(p.title)} target="_blank" rel="noopener noreferrer"
                   aria-label={`Search YouTube for ${p.title}`}><SquarePlay size={14} /> YouTube</a>
                <a className="btn small" href={web(engine, p.title)} target="_blank" rel="noopener noreferrer"
                   aria-label={`Search the web for ${p.title}`}><Globe size={14} /> Web</a>
              </span>
            </li>
          ))}
        </ol>
      ) : (
        <Empty title="Nothing yet">Songs show up here as the station announces them while you listen.</Empty>
      )}
    </Modal>
  );
}
