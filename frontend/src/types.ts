export interface User {
  id: number;
  username: string;
  is_admin: boolean;
  avatar?: AvatarLook;
  prefs: Prefs;
}

/** An account's icon: its picture, or a letter or two on a colour (null: the scheme's). */
export interface AvatarLook {
  picture: string | null;
  letter: string | null;
  color: string | null;
}

export interface Prefs {
  scheme?: string;
  mode?: "system" | "light" | "dark";
  genre_skins?: boolean;
  skin_lock?: string;          // a skin pinned by hand ("" = follow the music)
  skin_map?: Record<string, string>;     // tag → skin rules of the device's own, before the built-in ones
  volume?: number;
  quality?: "original" | "lossless" | "high" | "low";
  visualizer?: boolean;
  speed?: number;              // audiobooks / podcasts
  library_view?: LibraryView;
  sidebar_collapsed?: boolean;           // the library panel as an icon strip
  np_panel?: boolean;                    // the "Now playing" panel on the right
  search_engine?: string;                // web search for a song: a URL with %s for the words
  radio_buffer?: number;                 // seconds of a station gathered before it starts playing
  autoplay?: boolean;                    // similar songs once the queue runs out
  download_format?: "smaller" | "original";   // downloads in the app: Opus at the server's bitrate, or the files as they are
  download_wifi?: boolean;               // downloads wait for wifi
  network?: boolean;                     // false: the Library Network's music left out (only this server's)
  chat_hidden?: boolean;                 // true: not listed in the chat, so nobody new can write
  browse?: Record<string, BrowsePref>;   // sort and display mode per page
}

export interface LyricLine { t: number | null; text: string }
export interface Lyrics {
  source: "file" | "tags" | "lrclib" | null;
  synced: boolean;
  lines: LyricLine[];
  instrumental: boolean;
  colors: string[];          // the cover's, for the background
}

export type LibraryView = "genres" | "artists" | "albums";
export type DisplayMode = "list" | "grid" | "gallery";
export interface BrowsePref { display?: DisplayMode; sort?: string; hide_finished?: boolean; collapsed?: boolean;
  scope?: "national" | "international" }

/** The parts of Muzix a server can do without (modules.ts). */
export type ModuleKey = "vgm" | "audiobooks" | "podcasts" | "radio" | "network";
export type Modules = Record<ModuleKey, boolean>;

export interface AuthState {
  needs_setup: boolean;
  setup: boolean;                  // an admin still has the rest of the setup to do (pages/Setup.tsx)
  modules: Modules;
  user: User | null;
  site_name: string;
  allow_signup: boolean;
  version: string;
  offline?: boolean;          // the app's kept copy, while the server can't be reached (downloads.ts)
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
  peer?: string | null;       // the server in the Library Network it's from (null: this one's)
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
  peer?: string | null;       // the server in the Library Network it's from (null: this one's)
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
  tag_groups: { name: string; tags: string[] }[];     // tags in categories shown on a row of their own
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

export interface SidebarAlbum { id: number; title: string; artist: string; year: number; kind: "music" | "vgm"; art: string | null; liked: boolean; peer?: string | null }
/** A playlist file found in the music folders (read-only, everyone's). */
export interface FilePlaylist { id: number; name: string; tracks: number; entries: number; art: string[]; peer?: string | null }
export interface FilePlaylistDetail { id: number; name: string; path: string; entries: number; tracks: Track[]; peer?: string | null }

export interface SidebarData {
  liked_songs: number;
  playlists: { id: number; name: string; art: string | null }[];
  file_playlists: { id: number; name: string; tracks: number; art: string | null; peer?: string | null }[];
  albums: SidebarAlbum[];
  games: SidebarAlbum[];
  artists: { id: number; name: string; art: string | null }[];
  books: { id: number; title: string; author: string; art: string | null; progress: number; peer?: string | null }[];
  podcasts: { id: number; title: string; author: string; art: string | null; new: boolean }[];
  stations: Station[];
}

export interface BookHit { id: number; title: string; author: string; series: string; art: string | null; peer?: string | null }
export interface SearchResults { artists: Artist[]; albums: Album[]; tracks: Track[]; books: BookHit[] }
export type RecentKind = "artist" | "album" | "track" | "book";
/** Something picked from search results, as search gives it now. */
export type RecentSearch = { kind: "artist"; item: Artist } | { kind: "album"; item: Album } | { kind: "track"; item: Track } | { kind: "book"; item: BookHit };

export interface Home {
  stats: { tracks: number; albums: number; artists: number; vgm_tracks: number; hours: number };
  recently_played: Album[];
  recently_added: Album[];
  most_played: Album[];
  rediscover: Album[];
  vgm: Album[];
  genres: Genre[];
  new_podcasts: { id: number; title: string; image: string; new: number }[];     // with new episodes, latest first
  new_episodes: Episode[];
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
  peer?: string | null;       // the server in the Library Network it's from (null: this one's)
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
  autoplay: boolean;            // when an episode ends, the next one in the list plays
  unplayed: number | null;
  new: boolean;                 // it has a new episode
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
