import { useQuery } from "@tanstack/react-query";
import { Play, Shuffle } from "lucide-react";
import { type ReactNode, useMemo } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ago, api, fmtLong, fmtNumber, sized } from "../api";
import { playAlbum, playRandom } from "../actions";
import { AlbumRow, GenreCard } from "../components/Cards";
import { Art, Display, Kicker, Loading, NewDot, Section, Stripes } from "../components/ui";
import { engine } from "../player/engine";
import { fromEpisode, useStartedEpisodes } from "../store/player";
import { useUi } from "../store/ui";
import type { Album, Episode, Home as HomeData } from "../types";

function greeting() {
  const h = new Date().getHours();
  return h < 5 ? "Late night" : h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
}

function Tile({ to, kicker, title, sub, art, color, className = "" }: {
  to: string; kicker: string; title: string; sub: ReactNode; art: (string | null)[]; color: string; className?: string;
}) {
  const nav = useNavigate();
  return (
    <div className={`tile ${className}`} style={{ "--tile-color": color } as React.CSSProperties}
         onClick={() => nav(to)} role="link" tabIndex={0} onKeyDown={(e) => e.key === "Enter" && nav(to)}>
      <div className="tile-bg">
        {art.filter((u): u is string => !!u).slice(0, 9).map((u, i) => <img key={i} src={sized(u, 300)} alt="" loading="lazy" />)}
      </div>
      <Stripes />
      <div className="tile-body">
        <div className="tile-kicker">{kicker}</div>
        <div className="tile-title">{title}</div>
        <div className="tile-sub">{sub}</div>
      </div>
    </div>
  );
}

/** A new episode, as on Spotify's home: its cover, a play button, and the blue dot until it's started. */
function EpisodeCard({ e, started }: { e: Episode; started: boolean }) {
  return (
    <Link to={`/podcasts/episode/${e.id}`} className="card ep-card">
      <div className="ep-card-art">
        <Art src={e.image} name={e.feed_title || e.title} />
        <button className="play-fab" aria-label={`Play ${e.title}`} data-tip={`Play ${e.title}`}
                onClick={(ev) => { ev.preventDefault(); ev.stopPropagation(); engine.play([fromEpisode(e)]); }}>
          <Play size={20} fill="currentColor" />
        </button>
      </div>
      <div className="card-title">{e.title}</div>
      <div className="card-sub ellipsis">{e.feed_title}</div>
      <div className="card-sub ellipsis">
        {!started && <NewDot label="New episode" />}
        {[e.published && ago(e.published), e.duration > 0 && fmtLong(e.duration)].filter(Boolean).join(" · ")}
      </div>
    </Link>
  );
}

export default function Home() {
  const user = useUi((s) => s.user);
  const q = useQuery({ queryKey: ["home"], queryFn: () => api.get<HomeData>("/api/home") });
  const books = useQuery({ queryKey: ["books-mini"], queryFn: () => api.get<{ total: number; items: { art: string | null }[] }>("/api/books", { limit: 9, sort: "added" }) });
  const featured: Album | undefined = useMemo(() => {
    const pool = q.data?.rediscover.filter((a) => a.art) || [];
    return pool[Math.floor(Math.random() * pool.length)];
  }, [q.data]);
  const started = useStartedEpisodes();
  if (!q.data) return <div className="page"><Loading /></div>;
  const d = q.data;
  const arts = (list: Album[]) => list.map((a) => a.art);
  const latest = d.recently_added[0];
  // podcasts with something new come first among the shortcuts, with their dot, as on Spotify
  const fresh = d.new_podcasts.slice(0, 4).map((p) => ({
    ...p, dot: p.new > d.new_episodes.filter((e) => e.feed_id === p.id && started.has(e.id)).length,
  }));
  const quick = (d.recently_played.length >= 4 ? d.recently_played : [...d.recently_played, ...d.recently_added]).slice(0, 8 - fresh.length);
  const newCount = d.new_podcasts.reduce((n, p) => n + p.new, 0);

  return (
    <div className="page">
      <nav className="home-chips phone-only" aria-label="Sections">
        <button className="hchip on phone-only" onClick={() => playRandom({ kind: "music" })}><Shuffle size={14} /> Shuffle</button>
        {[["/library", "Music"], ["/vgm", "VGM"], ["/audiobooks", "Audiobooks"], ["/podcasts", "Podcasts"], ["/radio", "Radio"], ["/spotify", "Spotify"]]
          .map(([to, label]) => (
            <Link key={to} to={to} className="hchip">
              {to === "/podcasts" && fresh.some((p) => p.dot) && <NewDot label="New episodes" />}{label}
            </Link>
          ))}
      </nav>
      <div className="hero">
        <div>
          <div className="desktop-only">
            <Kicker parts={["Muzix terminal", `${fmtNumber(d.stats.tracks)} tracks`, `${fmtNumber(d.stats.albums)} albums`, `${fmtNumber(d.stats.hours)} hours`]} />
          </div>
          <Display l1={`${greeting()},`} l2={user?.username || "listener"} />
          <p className="lede desktop-only">
            Your whole collection in one place: {fmtNumber(d.stats.artists)} artists, {fmtNumber(d.stats.vgm_tracks)} chiptunes and tracker
            songs, audiobooks, podcasts and radio. The app dresses up for whatever's playing.
          </p>
          <div className="row-actions desktop-only">
            <button className="btn primary" onClick={() => playRandom({ kind: "music" })}><Shuffle size={15} /> Shuffle everything</button>
            {latest && <button className="btn" onClick={() => playAlbum(latest.id)}>Latest: {latest.title}</button>}
          </div>
        </div>
        {featured && (
          <Link to={`/album/${featured.id}`} className="hero-art" data-tip={`${featured.artist} - ${featured.title}`}>
            <Art src={featured.art} name={featured.title} size={600} />
            <div className="caption">Featured · {featured.artist} · {featured.year || ""}</div>
          </Link>
        )}
      </div>

      <div className="quick-grid">
        {fresh.map((p) => (
          <Link key={`p${p.id}`} to={`/podcasts/${p.id}`} className="quick podcast">
            <Art src={p.image} name={p.title} size={160} />
            <span>{p.title}</span>
            {p.dot && <NewDot label={p.new === 1 ? "A new episode" : `${p.new} new episodes`} />}
          </Link>
        ))}
        {quick.map((a) => (
          <Link key={a.id} to={`/album/${a.id}`} className="quick">
            <Art src={a.art} name={a.title} size={160} />
            <span>{a.title}</span>
          </Link>
        ))}
      </div>

      {d.new_episodes.length > 0 && (
        <Section kicker="From your podcasts" title="New episodes" more={<Link className="see-all" to="/podcasts">All podcasts</Link>}>
          <div className="scroller">{d.new_episodes.map((e) => <EpisodeCard key={e.id} e={e} started={started.has(e.id)} />)}</div>
        </Section>
      )}

      <div className="bento desktop-only">
        <Tile to="/library" className="big" kicker="Your collection" title="Library" color="var(--primary)"
              sub={`${fmtNumber(d.stats.albums)} albums · ${fmtNumber(d.stats.artists)} artists`}
              art={arts([...d.recently_added, ...d.rediscover])} />
        <Tile to="/vgm" className="tall" kicker="8-bit and beyond" title="VGM" color="var(--success)"
              sub="NES, Game Boy, C64, Amiga, SNES…" art={arts(d.vgm)} />
        <Tile to="/audiobooks" className="tall" kicker="Story time" title="Books" color="var(--warning)"
              sub={books.data ? `${fmtNumber(books.data.total)} audiobooks` : "Audiobooks"}
              art={(books.data?.items || []).map((b) => b.art)} />
        <Tile to="/podcasts" kicker="On demand" title="Podcasts" color="var(--secondary)" art={arts(d.most_played)}
              sub={newCount ? <><NewDot label="New episodes" />{newCount === 1 ? "A new episode" : `${newCount} new episodes`}</> : "Subscribe to any feed"} />
        <Tile to="/radio" kicker="Live on air" title="Radio" color="var(--error)" sub="Thousands of stations" art={arts(d.recently_played)} />
      </div>

      {d.recently_played.length > 0 && <Section kicker="Pick up where you left off" title="Jump back in"><AlbumRow albums={d.recently_played} /></Section>}
      <Section kicker="Fresh in the library" title="Recently added" more={<Link className="see-all" to="/library?sort=added">See all</Link>}>
        <AlbumRow albums={d.recently_added} />
      </Section>
      {d.most_played.length > 0 && <Section kicker="Your heavy rotation" title="Most played"><AlbumRow albums={d.most_played} /></Section>}
      <Section kicker="Pulled from the shelves" title="Rediscover"><AlbumRow albums={d.rediscover} /></Section>
      <Section kicker="Browse by" title="Genres" more={<Link className="see-all" to="/library/genres">All genres</Link>}>
        <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))" }}>
          {d.genres.map((g) => <GenreCard key={g.name} g={g} />)}
        </div>
      </Section>
      {d.vgm.length > 0 && <Section kicker="Press start" title="Chiptune picks" more={<Link className="see-all" to="/vgm">All VGM</Link>}><AlbumRow albums={d.vgm} /></Section>}
    </div>
  );
}
