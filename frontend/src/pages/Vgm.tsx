import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { Shuffle } from "lucide-react";
import { useCallback } from "react";
import { NavLink, Route, Routes, useMatch, useSearchParams } from "react-router-dom";
import { api, fmtNumber } from "../api";
import { playRandom } from "../actions";
import { AlbumItems, DisplaySwitch, SortMenu, useBrowse } from "../components/Browse";
import { Display, Empty, Kicker, Loading, Section, Stripes, useInView } from "../components/ui";
import { SYSTEM_ACCENTS } from "../theme/skins";
import type { Album, Paged } from "../types";
import { OnlineBrowser, OnlineHome } from "./VgmOnline";

interface SystemRow { system: string; tracks: number; albums: number }

const VGM_SORTS: [string, string][] = [
  ["name", "Title"], ["artist", "Composer"], ["added", "Recently added"], ["tracks", "Most tunes"],
  ["year", "Newest first"], ["year_asc", "Oldest first"], ["played", "Most played"],
];

export default function Vgm() {
  const deep = useMatch("/vgm/online/:source/*");
  const online = useMatch("/vgm/online");
  const systems = useQuery({ queryKey: ["vgm-systems"], queryFn: () => api.get<SystemRow[]>("/api/vgm/systems") });
  const total = (systems.data || []).reduce((s, x) => s + x.tracks, 0);
  return (
    <div className="page wide">
      {!deep && <>
        <Kicker parts={online ? ["Video game music", "Online archives"]
          : ["Video game music", total && `${fmtNumber(total)} tunes`, systems.data && `${systems.data.length} systems`]} />
        <Display l1="Press" l2="start" />
      </>}
      <nav className="subnav" aria-label="Video game music">
        <NavLink to="/vgm" end className={({ isActive }) => (isActive ? "active" : "")}>Your collection</NavLink>
        <NavLink to="/vgm/online" className={({ isActive }) => (isActive ? "active" : "")}>Online archives</NavLink>
      </nav>
      <Routes>
        <Route index element={<Collection />} />
        <Route path="online" element={<OnlineHome />} />
        <Route path="online/:source/*" element={<OnlineBrowser />} />
      </Routes>
    </div>
  );
}

function Collection() {
  const [params, setParams] = useSearchParams();
  const system = params.get("system") || "";
  const b = useBrowse("vgm", VGM_SORTS, "name");
  const systems = useQuery({ queryKey: ["vgm-systems"], queryFn: () => api.get<SystemRow[]>("/api/vgm/systems") });
  const albums = useInfiniteQuery({
    queryKey: ["vgm-albums", system, b.sort],
    queryFn: ({ pageParam }) => api.get<Paged<Album>>("/api/albums", { kind: "vgm", system: system || undefined, sort: b.sort, limit: 60, offset: pageParam }),
    initialPageParam: 0,
    getNextPageParam: (last, all) => {
      const n = all.reduce((s, p) => s + p.items.length, 0);
      return n < last.total ? n : undefined;
    },
  });
  const more = useCallback(() => { if (albums.hasNextPage && !albums.isFetchingNextPage) albums.fetchNextPage(); }, [albums]);
  const sentinel = useInView(more, !!albums.hasNextPage);
  const items = albums.data?.pages.flatMap((p) => p.items) || [];

  return (
    <>
      <p className="lede">Chiptunes and tracker music, played by the real chip emulators: NES, Game Boy, SNES, Mega Drive, C64, ZX Spectrum, Atari ST, Amiga MODs, TFMX and AHX, and PC trackers. Looping songs follow the loop settings on the admin page.</p>
      <div className="row-actions" style={{ marginBottom: 26 }}>
        <button className="btn primary" onClick={() => playRandom({ kind: "vgm", system: system || undefined })}><Shuffle size={15} /> Shuffle {system || "all VGM"}</button>
      </div>

      {systems.data && systems.data.length > 0 && (
        <div className="bento" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(230px, 1fr))", gridAutoRows: 130 }}>
          {systems.data.map((s) => {
            const accent = SYSTEM_ACCENTS[s.system];
            return (
              <div key={s.system} className="tile" role="button" tabIndex={0}
                   style={{ "--tile-color": accent?.primary || "var(--success)", outline: system === s.system ? "2px solid var(--primary)" : undefined } as React.CSSProperties}
                   onClick={() => setParams(system === s.system ? {} : { system: s.system })}>
                <Stripes />
                <div className="tile-body">
                  <div className="tile-kicker">{fmtNumber(s.tracks)} tunes · {fmtNumber(s.albums)} {s.albums === 1 ? "set" : "sets"}</div>
                  <div className="tile-title" style={{ fontSize: s.system.length > 16 ? 19 : 25 }}>{s.system}</div>
                  <button className="btn small" style={{ marginTop: 8 }}
                          onClick={(e) => { e.stopPropagation(); playRandom({ kind: "vgm", system: s.system }); }}>
                    <Shuffle size={13} /> Shuffle
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      <Section kicker={system || "Every system"} title="Games & collections">
        <div className="toolbar browsebar">
          <SortMenu value={b.sort} options={VGM_SORTS} onChange={b.setSort} />
          <div className="grow" />
          <DisplaySwitch value={b.display} onChange={b.setDisplay} />
        </div>
        {albums.isLoading ? <Loading /> : items.length ? (
          <>
            <AlbumItems items={items} display={b.display} vgm />
            <div ref={sentinel} style={{ height: 1 }} />
          </>
        ) : <Empty title="No VGM yet">Add a folder with chiptunes or tracker modules as a "VGM" folder on the admin page.</Empty>}
      </Section>
    </>
  );
}
