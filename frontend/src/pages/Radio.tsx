import { useQuery } from "@tanstack/react-query";
import { Heart, Play, Radio as RadioIcon } from "lucide-react";
import { useState } from "react";
import { api } from "../api";
import { queryClient } from "../actions";
import { Art, Display, Empty, Kicker, Loading, Section } from "../components/ui";
import { engine } from "../player/engine";
import { fromStation, usePlayer } from "../store/player";
import { useUi } from "../store/ui";
import type { Station } from "../types";

function StationGrid({ list, saved }: { list: Station[]; saved: Station[] }) {
  const notify = useUi((s) => s.notify);
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
        return (
          <div key={s.uuid || s.url} className="card" style={{ cursor: "pointer" }} onClick={() => engine.play([fromStation(s)])}>
            <div style={{ position: "relative" }}>
              <Art src={s.favicon} name={s.name} size={160} />
              {cur === key && <div className="badge accent" style={{ position: "absolute", left: 8, top: 8, background: "var(--bg)" }}>On air</div>}
            </div>
            <div className="card-title ellipsis">{s.name}</div>
            <div className="card-sub ellipsis">{[s.countrycode || s.country, s.codec, s.bitrate ? `${s.bitrate}k` : ""].filter(Boolean).join(" · ")}</div>
            <div className="row-actions" style={{ marginTop: 6 }}>
              <button className="mini" aria-label="Play" onClick={(e) => { e.stopPropagation(); engine.play([fromStation(s)]); }}><Play size={14} fill="currentColor" /></button>
              <button className={`mini ${isSaved ? "liked" : ""}`} aria-label={isSaved ? "Remove" : "Save"}
                      onClick={(e) => { e.stopPropagation(); toggle(s); }}><Heart size={14} fill={isSaved ? "currentColor" : "none"} /></button>
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
        {tag && <button className="btn ghost" onClick={() => { setTag(""); setQuery(term ? { q: term } : null); }}>Tag: {tag} ✕</button>}
      </div>
      {tags.data && (
        <div className="tags" style={{ marginBottom: 10 }}>
          {tags.data.slice(0, 36).map((t) => (
            <button key={t.name} className="tag" style={{ cursor: "pointer", background: tag === t.name ? "var(--primary)" : "transparent", color: tag === t.name ? "var(--on-primary)" : undefined }}
                    onClick={() => { setTag(t.name); setQuery({ q: term, tag: t.name }); }}>{t.name}</button>
          ))}
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
