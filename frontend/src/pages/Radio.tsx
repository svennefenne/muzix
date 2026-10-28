import { useQuery } from "@tanstack/react-query";
import { Heart, History, Play, Radio as RadioIcon, Tags, X } from "lucide-react";
import { useState } from "react";
import { api } from "../api";
import { queryClient } from "../actions";
import { AdminCog } from "../components/AdminMode";
import { useStationHistory } from "../components/StationHistory";
import { Art, Display, Empty, Kicker, Loading, Section } from "../components/ui";
import { engine } from "../player/engine";
import { fromStation, usePlayer } from "../store/player";
import { useUi } from "../store/ui";
import type { Station } from "../types";

function StationGrid({ list, saved }: { list: Station[]; saved: Station[] }) {
  const notify = useUi((s) => s.notify);
  const showHistory = useStationHistory((s) => s.show);
  const cur = usePlayer((s) => (s.index >= 0 ? s.queue[s.index]?.key : null));
  const savedBy = new Map(saved.map((s) => [s.uuid || s.url, s]));
  const toggle = async (s: Station) => {
    const have = savedBy.get(s.uuid || s.url);
    if (have?.id) await api.del(`/api/radio/stations/${have.id}`);
    else {
      await api.post("/api/radio/stations", { ...s, homepage: s.homepage || "", favicon: s.favicon || "" });
      notify(`Saved ${s.name}`);
    }
    queryClient.invalidateQueries({ queryKey: ["stations"] });
  };
  return (
    <div className="grid small">
      {list.filter((s) => !s.hls).map((s) => {
        const key = `radio:${s.uuid || s.url}`;
        const isSaved = savedBy.has(s.uuid || s.url);
        const mine = savedBy.get(s.uuid || s.url);
        return (
          <div key={s.uuid || s.url} className="card" style={{ cursor: "pointer" }} onClick={() => engine.play([fromStation(s)])}>
            <div style={{ position: "relative" }}>
              <Art src={s.favicon} name={s.name} size={160} />
              {cur === key && <div className="badge accent" style={{ position: "absolute", left: 8, top: 8, background: "var(--bg)" }}>On air</div>}
              {mine?.id && <AdminCog kind="station" id={mine.id} title={s.name} />}
            </div>
            <div className="card-title ellipsis">{s.name}</div>
            <div className="card-sub ellipsis">{[s.countrycode || s.country, s.codec, s.bitrate ? `${s.bitrate}k` : ""].filter(Boolean).join(" · ")}</div>
            <div className="row-actions" style={{ marginTop: 6 }}>
              <button className="mini" aria-label="Play" onClick={(e) => { e.stopPropagation(); engine.play([fromStation(s)]); }}><Play size={14} fill="currentColor" /></button>
              <button className={`mini ${isSaved ? "liked" : ""}`} aria-label={isSaved ? "Remove" : "Save"}
                      onClick={(e) => { e.stopPropagation(); toggle(s); }}><Heart size={14} fill={isSaved ? "currentColor" : "none"} /></button>
              <button className="mini" aria-label={`Played on ${s.name}`} data-tip="Songs this station played while you listened"
                      onClick={(e) => { e.stopPropagation(); showHistory(s.uuid || s.url, s.name); }}><History size={14} /></button>
            </div>
          </div>
        );
      })}
    </div>
  );
}

export default function Radio() {
  const [term, setTerm] = useState("");
  const [tag, setTag] = useState("");
  const [query, setQuery] = useState<{ q?: string; tag?: string } | null>(null);
  const [tagsOpen, setTagsOpen] = useState(false);
  const [tagFind, setTagFind] = useState("");
  const saved = useQuery({ queryKey: ["stations"], queryFn: () => api.get<Station[]>("/api/radio/stations") });
  const top = useQuery({ queryKey: ["radio-top"], queryFn: () => api.get<{ top: Station[]; local?: Station[] }>("/api/radio/top"), staleTime: 600_000 });
  const tags = useQuery({ queryKey: ["radio-tags"], queryFn: () => api.get<{ name: string; stations: number }[]>("/api/radio/tags"), staleTime: 3600_000 });
  const results = useQuery({ queryKey: ["radio-search", query], enabled: !!query, queryFn: () => api.get<Station[]>("/api/radio/search", query || {}) });
  const savedList = saved.data || [];
  return (
    <div className="page wide">
      <Kicker parts={["Internet radio", "radio-browser.info", savedList.length > 0 && `${savedList.length} saved`]} />
      <Display l1="Live" l2="on air" />
      <div className="toolbar">
        <input className="input" style={{ maxWidth: 380 }} placeholder="Station name" value={term}
               onChange={(e) => setTerm(e.target.value)} onKeyDown={(e) => e.key === "Enter" && setQuery({ q: term, tag })} />
        <button className="btn" onClick={() => setQuery({ q: term, tag })}><RadioIcon size={15} /> Search</button>
        {/* the tags wait behind a button, so the stations come first */}
        <button className={`btn ${tag ? "accent" : ""}`} aria-expanded={tagsOpen} onClick={() => setTagsOpen(!tagsOpen)}>
          <Tags size={15} /> {tag ? `Tag: ${tag}` : "Tags"}
        </button>
        {tag && (
          <button className="btn ghost" onClick={() => { setTag(""); setQuery(term ? { q: term } : null); }}>
            <X size={14} /> Clear tag
          </button>
        )}
      </div>
      {tagsOpen && tags.data && (
        <div className="tag-panel">
          <input className="input" placeholder="Find a tag" value={tagFind} aria-label="Find a tag"
                 onChange={(e) => setTagFind(e.target.value)} />
          <div className="tags">
            {tags.data.filter((t) => t.name.toLowerCase().includes(tagFind.trim().toLowerCase())).map((t) => (
              <button key={t.name} className={`tag tag-pick ${tag === t.name ? "on" : ""}`} aria-pressed={tag === t.name}
                      onClick={() => { setTag(t.name); setQuery({ q: term, tag: t.name }); setTagsOpen(false); setTagFind(""); }}>
                {t.name} <small>{t.stations}</small>
              </button>
            ))}
          </div>
        </div>
      )}
      {query && <Section kicker="Search" title={[query.q, query.tag].filter(Boolean).join(" · ") || "Stations"}>
        {results.data ? (results.data.length ? <StationGrid list={results.data} saved={savedList} /> : <Empty title="No stations found" />) : <Loading />}
      </Section>}
      <Section kicker="Your stations" title="Saved">
        {savedList.length ? <StationGrid list={savedList.map((s) => ({ ...s, uuid: s.uuid || "" }))} saved={savedList} />
          : <Empty title="No saved stations">Tap the heart on a station to keep it here.</Empty>}
      </Section>
      {top.data?.local && top.data.local.length > 0 && <Section kicker="Near you" title="Popular here"><StationGrid list={top.data.local} saved={savedList} /></Section>}
      <Section kicker="Worldwide" title="Most played">{top.data ? <StationGrid list={top.data.top} saved={savedList} /> : <Loading />}</Section>
    </div>
  );
}
