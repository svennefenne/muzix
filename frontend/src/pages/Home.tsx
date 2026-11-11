import { useQuery } from "@tanstack/react-query";
import { FolderPlus, Play, Shuffle } from "lucide-react";
import { useMemo } from "react";
import { Link } from "react-router-dom";
import { ago, api, fmtLong, fmtNumber } from "../api";
import { playAlbum, playRandom } from "../actions";
import { AlbumRow, GenreCard } from "../components/Cards";
import { Art, Display, Kicker, Loading, NewDot, Section } from "../components/ui";
import { useModules } from "../modules";
import { appPlayer, useShell } from "../player/app";
import { engine } from "../player/engine";
import { freshPodcasts, fromEpisode, useStartedEpisodes } from "../store/player";
import { useUi } from "../store/ui";
import type { Album, Episode, Home as HomeData } from "../types";

/** "a, b and c" */
function listed(parts: string[]) {
  return parts.length > 1 ? `${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1]}` : parts.join("");
}

function greeting() {
  const h = new Date().getHours();
  return h < 5 ? "Late night" : h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
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
  const featured: Album | undefined = useMemo(() => {
    const pool = q.data?.rediscover.filter((a) => a.art) || [];
    return pool[Math.floor(Math.random() * pool.length)];
  }, [q.data]);
  const started = useStartedEpisodes();
  const modules = useModules();
  // the app's own library with no folder picked yet: the app asks for one
  const own = useShell((s) => (s.library === "local" ? (s.desktop ? "computer" : "phone") : null));
  if (!q.data) return <div className="page"><Loading /></div>;
  const d = q.data;
  const latest = d.recently_added[0];
  // podcasts with something new come first among the shortcuts, with their dot, as on Spotify
  const fresh = freshPodcasts(d, started);
  const quick = (d.recently_played.length >= 4 ? d.recently_played : [...d.recently_played, ...d.recently_added]).slice(0, 8 - fresh.length);

  return (
    <div className="page">
      {/* phones go straight to the tiles: their sections are chips in the top bar */}
      <div className="hero desktop-only">
        <div>
          <div className="desktop-only">
            <Kicker parts={["Muzix terminal", `${fmtNumber(d.stats.tracks)} tracks`, `${fmtNumber(d.stats.albums)} albums`, `${fmtNumber(d.stats.hours)} hours`]} />
          </div>
          <Display l1={`${greeting()},`} l2={user?.username || "listener"} />
          <p className="lede desktop-only">
            Your whole collection in one place: {listed([
              `${fmtNumber(d.stats.artists)} artists`,
              ...(modules.vgm ? [`${fmtNumber(d.stats.vgm_tracks)} chiptunes and tracker songs`] : []),
              ...(["audiobooks", "podcasts", "radio"] as const).filter((m) => modules[m]),
            ])}. The app dresses up for whatever's playing.
          </p>
          <div className="row-actions desktop-only">
            <button className="btn primary" onClick={() => playRandom({ kind: "music" })}><Shuffle size={15} /> Shuffle everything</button>
            {latest && <button className="btn" onClick={() => playAlbum(latest.id)}>Latest: {latest.title}</button>}
          </div>
        </div>
        {featured && (
          <Link to={`/album/${featured.id}`} className="hero-art" data-tip={`${featured.artist} - ${featured.title}`}>
            <Art src={featured.art} name={featured.title} size={600} peer={featured.peer} />
            <div className="caption">Featured · {featured.artist} · {featured.year || ""}</div>
          </Link>
        )}
      </div>

      {own && d.stats.tracks === 0 && (
        <section className="panel home-empty">
          <div className="kicker">This {own}'s music</div>
          <div className="h2">No music here yet</div>
          <p className="dim">Pick the folder on this {own} that has your music; the app only reads it. Podcasts and radio play meanwhile.</p>
          <button className="btn primary" onClick={() => appPlayer.addFolder()}><FolderPlus size={15} /> Choose a music folder</button>
        </section>
      )}

      <div className="quick-grid">
        {fresh.map((p) => (
          <Link key={`p${p.id}`} to={`/podcasts/${p.id}`} className="quick">
            <div className="art-dot">
              <Art src={p.image} name={p.title} size={160} />
              {p.dot && <NewDot label={p.new === 1 ? "A new episode" : `${p.new} new episodes`} />}
            </div>
            <span>{p.title}</span>
          </Link>
        ))}
        {quick.map((a) => (
          <Link key={a.id} to={`/album/${a.id}`} className="quick">
            <Art src={a.art} name={a.title} size={160} peer={a.peer} />
            <span>{a.title}</span>
          </Link>
        ))}
      </div>

      {d.new_episodes.length > 0 && (
        <Section kicker="From your podcasts" title="New episodes" more={<Link className="see-all" to="/podcasts">All podcasts</Link>}>
          <div className="scroller">{d.new_episodes.map((e) => <EpisodeCard key={e.id} e={e} started={started.has(e.id)} />)}</div>
        </Section>
      )}

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
