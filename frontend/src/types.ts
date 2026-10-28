export interface User {
  id: number;
  username: string;
  is_admin: boolean;
  prefs: Prefs;
}

export interface Prefs {
  scheme?: string;
  mode?: "system" | "light" | "dark";
  genre_skins?: boolean;
  skin_lock?: string;          // a skin pinned by hand ("" = follow the music)
  volume?: number;
  quality?: "original" | "lossless" | "high" | "low";
  visualizer?: boolean;
  speed?: number;              // audiobooks / podcasts
  library_view?: LibraryView;
  sidebar_collapsed?: boolean;           // the library panel as an icon strip
  np_panel?: boolean;                    // the "Now playing" panel on the right
  search_engine?: string;                // web search for a song: a URL with %s for the words
  radio_buffer?: number;                 // seconds of a station gathered before it starts playing
  browse?: Record<string, BrowsePref>;   // sort and display mode per page
}

export type LibraryView = "genres" | "artists" | "albums";
export type DisplayMode = "list" | "grid" | "gallery";
export interface BrowsePref { display?: DisplayMode; sort?: string; hide_finished?: boolean; collapsed?: boolean }

export interface AuthState {
  needs_setup: boolean;
  user: User | null;
  site_name: string;
  allow_signup: boolean;
  version: string;
  defaults: { scheme: string; mode: "system" | "light" | "dark"; genre_skins: boolean };
}

export interface Track {
  id: number;
  title: string;
  artist: string;
  albumartist: string;
  album: string;
  album_id: number | null;
  artist_id: number | null;
  track_no: number;
  disc_no: number;
  year: number;
  genre: string;
  duration: number;
  format: string;
  kind: "music" | "vgm";
  family: string | null;
  subsong: number;
  sample_rate: number;
  cast_native?: boolean;
  bit_depth: number;
  bitrate: number;
  system: string;
  art: string | null;
  stream: string;
  liked: boolean;
  tags: string[];
  item_id?: number;
}

export interface Album {
  id: number;
  title: string;
  artist: string;
  artist_id: number | null;
  year: number;
  genre: string;
  kind: "music" | "vgm";
  track_count: number;
  duration: number;
  formats: string[];
  art: string | null;
  added_at: string | null;
  liked: boolean;
}

export interface AlbumDetail extends Album {
  tracks: Track[];
  more: Album[];
  colors: string[];
  folder: string;
  artist_tags: string[];
}

export interface Artist {
  id: number;
  name: string;
  genre: string;
  tags: string[];
  art: string | null;
  album_count: number | null;
  liked: boolean;
}

export interface TagDetail {
  name: string;
  tracks: number;
  albums: number;
  artists: Artist[];
  album_list: Album[];
}

export interface ArtistDetail extends Artist {
  albums: Album[];
  top_tracks: Track[];
}

export interface Genre {
  name: string;
  albums: number;
  tracks: number;
  artists?: number;
  art: string[];
}

export interface SidebarAlbum { id: number; title: string; artist: string; year: number; kind: "music" | "vgm"; art: string | null; liked: boolean }
/** A playlist file found in the music folders (read-only, everyone's). */
export interface FilePlaylist { id: number; name: string; tracks: number; entries: number; art: string[] }
export interface FilePlaylistDetail { id: number; name: string; path: string; entries: number; tracks: Track[] }

export interface SidebarData {
  liked_songs: number;
  playlists: { id: number; name: string; art: string | null }[];
  file_playlists: { id: number; name: string; tracks: number; art: string | null }[];
  albums: SidebarAlbum[];
  games: SidebarAlbum[];
  artists: { id: number; name: string; art: string | null }[];
  books: { id: number; title: string; author: string; art: string | null; progress: number }[];
  podcasts: { id: number; title: string; author: string; art: string | null; new: boolean }[];
  stations: Station[];
}

export interface BookHit { id: number; title: string; author: string; series: string; art: string | null }
export interface SearchResults { artists: Artist[]; albums: Album[]; tracks: Track[]; books: BookHit[] }

export interface Home {
  stats: { tracks: number; albums: number; artists: number; vgm_tracks: number; hours: number };
  recently_played: Album[];
  recently_added: Album[];
  most_played: Album[];
  rediscover: Album[];
  vgm: Album[];
  genres: Genre[];
}

export interface Playlist {
  id: number;
  name: string;
  description: string;
  public: boolean;
  owner_id: number;
  track_count: number;
  duration: number;
  art: string[];
  updated_at: string | null;
  tracks?: Track[];
}

export interface Book {
  id: number;
  title: string;
  author: string;
  narrator: string;
  series: string;
  year: number;
  duration: number;
  art: string | null;
  position: number;
  finished: boolean;
  updated_at: string | null;
  description?: string;
  chapters?: { title: string; start: number }[];
  parts?: { position: number; title: string; duration: number; offset: number; format: string; stream: string }[];
}

export interface Feed {
  id: number;
  url: string;
  title: string;
  author: string;
  description: string;
  image: string;
  link: string;
  categories: string[];
  error: string;
  subscribed: boolean;
  auto_download: boolean;
  unplayed: number | null;
  new: boolean;                 // a new episode since its page was last opened
  last_checked: string | null;
  episodes?: Episode[];         // a podcast's page: the first of them, in its order
  total?: number;               // all its episodes
  finished?: number;            // the ones you've finished
}

/** An episode's own page: its podcast and its show notes (safe HTML, built by the server). */
export interface EpisodeDetail extends Episode {
  notes: string;
  feed: { id: number; title: string; author: string; image: string };
}

export interface Episode {
  id: number;
  feed_id: number;
  title: string;
  description: string;
  published: string | null;
  duration: number;
  image: string;
  downloaded: boolean;
  position: number;
  finished: boolean;
  new: boolean;                 // out since you subscribed, not started yet
  stream: string;
  feed_title?: string | null;
}

export interface PodcastHit {
  title: string;
  author: string;
  url: string;
  image: string;
  genre: string;
}

export interface Station {
  id?: number;
  uuid: string;
  name: string;
  url: string;
  homepage: string;
  favicon: string;
  tags: string;
  country: string;
  countrycode?: string;
  codec: string;
  bitrate: number;
  votes?: number;
  hls?: boolean;
}

export interface Job {
  id: number;
  type: string;
  title: string;
  status: "queued" | "running" | "done" | "failed" | "cancelled";
  progress: number;
  message: string;
  result: Record<string, unknown>;
  created_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  log?: string;
}

export interface Paged<T> {
  total: number;
  items: T[];
}

export interface OnlineSource {
  id: string; name: string; label: string; about: string; system: string; home: string;
  starts: { name: string; path: string }[];
}
export interface OnlineFile {
  name: string; path: string; kind: "tune" | "archive"; size: number; format: string; chip: boolean;
  title?: string; artist?: string; year?: number; duration?: number;   // archives that say (ZXArt, VGMRips)
  songs?: number;
}
export interface OnlineListing {
  source: string; path: string; name: string; system: string;
  crumbs: { name: string; path: string }[];
  dirs: { name: string; path: string; count?: number }[];
  files: OnlineFile[];
  other: number;                 // files Muzix can't play
  more?: boolean;                // archives that list a folder a page at a time (VGMRips)
  total?: number | null;
}
export interface OnlineSearchGroup extends OnlineListing { label: string; archive: string }
export interface OnlineSearchResult {
  query: string;
  groups: OnlineSearchGroup[];
  skipped: { source: string; name: string; label: string; reason: string }[];
  building: string[];                 // archives whose list is still being fetched
}
export interface OnlineShuffleItem extends OnlineFile { source: string; system: string }
export interface OnlineTrack {
  key: string; title: string; artist: string; album: string; duration: number; format: string;
  kind: "music" | "vgm"; system: string; year: number; stream: string; cast_native: boolean;
}
