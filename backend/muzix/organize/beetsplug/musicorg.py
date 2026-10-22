"""musicorg: organise this library into main-genre folders.

Import hook
    Records each item's original path/genre and splits import tasks whose
    folder mixes formats (mp3 + flac) or holds loose songs from many albums.

Commands
    beet mgenre [-f] [query]  decide a main genre per album (album.mo_genre)
    beet mplan  [query]       compute destination fields used by `paths`
    beet mreport              summarise the plan
"""

from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
import unicodedata
from collections import Counter, defaultdict

import yaml

from beets import config
from beets.importer.tasks import ImportTask
from beets.plugins import BeetsPlugin
from beets.ui import Subcommand

# --------------------------------------------------------------------------
# mutagen: WavPack files with non-standard sample rates
# --------------------------------------------------------------------------

def _patch_mutagen_wavpack():
    """mutagen only knows WavPack's 15 table sample rates; other rates
    (176.4/384 kHz vinyl rips) live in an ID_SAMPLE_RATE metadata sub-block
    and made mutagen raise IndexError, so beets skipped those files."""
    from mutagen import wavpack as wv

    if getattr(wv.WavPackInfo, "_musicorg_patched", False):
        return

    def custom_rate(fileobj, start):
        fileobj.seek(start)
        head = fileobj.read(32)
        body = fileobj.read(int.from_bytes(head[4:8], "little") + 8 - 32)
        i = 0
        while i + 2 <= len(body):
            mid = body[i]
            if mid & 0x80:  # ID_LARGE: 24-bit size
                size, i = int.from_bytes(body[i + 1:i + 4], "little") * 2, i + 4
            else:
                size, i = body[i + 1] * 2, i + 2
            if mid & 0x3F == 0x27:  # ID_SAMPLE_RATE
                return int.from_bytes(body[i:i + 3], "little")
            i += size
        return 0

    def init(self, fileobj):
        start = fileobj.tell()
        try:
            header = wv._WavPackHeader.from_fileobj(fileobj)
        except wv.WavPackHeaderError:
            raise wv.WavPackHeaderError("not a WavPack file")
        self.version = header.version
        self.channels = bool(header.flags & 4) or 2
        idx = (header.flags >> 23) & 0xF
        if idx < len(wv.RATES):
            self.sample_rate = wv.RATES[idx]
        else:
            pos = fileobj.tell()
            self.sample_rate = custom_rate(fileobj, start)
            fileobj.seek(pos)
        self.bits_per_sample = ((header.flags & 3) + 1) * 8
        if (header.flags >> 31) & 1:  # DSD
            self.sample_rate *= 4
            self.bits_per_sample = 1
        if header.total_samples == -1 or header.block_index != 0:
            samples = header.block_samples
            while True:
                fileobj.seek(header.block_size - 32 + 8, 1)
                try:
                    header = wv._WavPackHeader.from_fileobj(fileobj)
                except wv.WavPackHeaderError:
                    break
                samples += header.block_samples
        else:
            samples = header.total_samples
        self.length = float(samples) / self.sample_rate if self.sample_rate else 0.0

    wv.WavPackInfo.__init__ = init
    wv.WavPackInfo._musicorg_patched = True


_patch_mutagen_wavpack()


# --------------------------------------------------------------------------
# Genre mapping
# --------------------------------------------------------------------------

METAL, ROCK, POP, PSY = "Metal", "Rock", "Pop", "Psytrance"
ELEC, HIPHOP, JAZZ, SOUL = "Electronic", "Hip-Hop", "Jazz & Blues", "Soul & R&B"
FOLK, CLASS, OST = "Country & Folk", "Classical", "Soundtrack"
REGGAE, WORLD, COMEDY, KIDS = "Reggae & Ska", "World", "Comedy", "Children's"
MAIN_GENRES = (METAL, ROCK, POP, PSY, ELEC, HIPHOP, JAZZ, SOUL, FOLK, CLASS, OST,
               REGGAE, WORLD, COMEDY, KIDS)
UNCAT, DUPES = "Uncategorized", "Duplicates"

_ABBR = {"M": METAL, "R": ROCK, "P": POP, "PSY": PSY, "E": ELEC, "H": HIPHOP,
         "J": JAZZ, "S": SOUL, "C": FOLK, "CL": CLASS, "ST": OST,
         "RG": REGGAE, "W": WORLD, "CO": COMEDY, "K": KIDS}

# Exact tag -> main genre shares. "-" means: known, but maps to nothing.
EXACT_TABLE = """
psy psytrance psy-trance psychedelic-trance goa goa-trance psybient psychill psy-chill psychedelic-chill psychedelic-ambient psydub full-on fullon dark-psy darkpsy dark-psytrance forest forest-psy hi-tech hitech psyprog progressive-psytrance progressive-psy psy-progressive suomisaundi zenonesque psytech twilight-psy nitzhonot psybreaks psychedelic-electronica psychedelic-electronic psy-trance goa-psytrance israeli-trance psycore psygressive psy-ambient psyambient psychedelic-downtempo = PSY
trip-hop trip-hop/downtempo new-age ebm aggrotech futurepop darkwave dark-wave coldwave chiptune 8-bit chillout chill-out lounge-electronica big-beat elektro = E
synthpop synth-pop electropop eurodance dance euro-house euro-dance hi-nrg = E:.5 P:.5
new-wave = R:.5 P:.5
dance-pop europop teen-pop schlager dansband swedish-pop svensk-pop easy-listening christmas-pop = P
disco = S:.5 P:.5
funk soul motown gospel rnb r&b rhythm-and-blues contemporary-r&b neo-soul neo-soul northern-soul soul-and-r&b soul/r&b = S
blues-rock = R:.6 J:.4
folk-rock = R:.5 C:.5
folk-punk celtic-punk = R:.6 C:.4
pop-rock pop/rock rock/pop soft-rock power-pop adult-alternative-pop = R:.5 P:.5
pop-punk britpop grunge post-grunge emo screamo gothic goth gothic-rock deathrock instrumental-rock guitar-virtuoso shred stoner-rock industrial-rock aor = R
symphonic-prog symphonic-rock symphonic-progressive-rock = R
industrial = R:.5 E:.5
jazz-fusion fusion = J
bossa-nova latin-jazz = J:.5 W:.5
jazz-rock = J:.6 R:.4
acid-jazz nu-jazz lounge = J:.5 E:.5
chanson french-pop = P:.6 C:.4
visor visa svensk-visa vispop = C
singer-songwriter acoustic = C:.5 P:.5
rockabilly = R:.6 C:.4
rock-and-roll rock-n-roll rock-&-roll oldies = R:.5 P:.5
grime trap gangsta-rap svensk-hiphop swedish-hip-hop swedish-hiphop = H
turntablism = H:.5 E:.5
video-game-music game-music vgm video-game videogame game game-soundtrack ost score film-score film-soundtrack movie-soundtrack soundtracks original-soundtrack anime musical musicals broadway show-tunes film/tv general-film/tv-music = ST
celtic irish traditional spanish-guitar = C:.6
world world-music worldbeat world-fusion ethnic flamenco tango tango-nuevo fado klezmer balkan balkan-brass gypsy romani latin latin-american salsa cumbia son-cubano cuban afrobeat afro-cuban african highlife samba mpb bollywood = W
reggae ska rocksteady dancehall roots-reggae ragga lovers-rock two-tone 2-tone dub-reggae swedish-reggae svensk-reggae = RG
ska-punk = R:.5 RG:.5
comedy humour humor funny stand-up stand-up-comedy parody novelty spoken-word = CO
kids kids-music children children's-music childrens-music barnmusik barnvisor barnsånger sagor lullaby nursery-rhymes = K
progg svensk-progg = R
modern-classical contemporary-classical neoclassical string-quartet choral choir chamber-music minimalism = CL
symphonic piano = CL:.3
audiobook christmas xmas holiday other misc unknown genre default unclassifiable general-unclassifiable data-&-other porn-groove soundclash seen-live = -
"""

# Ambiguous tags: their weight goes to whichever candidate already leads.
AMBIGUOUS = {
    "psychedelic": (PSY, ROCK),
    "progressive": (ROCK, PSY, ELEC, METAL),
    "hardcore": (ROCK, METAL, ELEC),
    "dub": (ELEC, REGGAE),
}

# Nodes in beets' genre tree, most specific first along each chain.
TREE_NODES = {
    "psytrance": {PSY: 1}, "heavy metal": {METAL: 1},
    "rock": {ROCK: 1}, "pop": {POP: 1}, "electronic": {ELEC: 1},
    "hip hop": {HIPHOP: 1}, "jazz": {JAZZ: 1}, "blues": {JAZZ: 1},
    "r&b": {SOUL: 1}, "country": {FOLK: 1}, "folk": {FOLK: 1},
    "classical": {CLASS: 1}, "soundtrack": {OST: 1},
    "easy listening": {POP: 1}, "singer-songwriter": {FOLK: .5, POP: .5},
    "world music": {WORLD: 1}, "reggae": {REGGAE: 1},
    "caribbean and latin american": {WORLD: 1}, "african": {WORLD: 1},
    "asian": {WORLD: 1}, "comedy": {COMEDY: 1}, "kids music": {KIDS: 1},
}

# Substring fallbacks for tags not otherwise known (ordered).
FALLBACKS = [
    (r"metal|deathcore|grindcore|djent|thrash", {METAL: 1}),
    (r"psytrance|psy-?trance|psychedelic trance|\bgoa\b|psybient|psychill|psydub|darkpsy|full[ -]on", {PSY: 1}),
    (r"hip[ -]?hop|\brap\b", {HIPHOP: 1}),
    (r"soundtrack|\bscore\b|\bost\b|\bfilm\b|movie|\bgame\b|video ?game|\banime\b|musical", {OST: 1}),
    (r"classical|orchestra|baroque|\bopera\b|symphon|chamber", {CLASS: 1}),
    (r"jazz|\bswing\b|bebop|big band|blues", {JAZZ: 1}),
    (r"\bsoul|\bfunk|r&b|\brnb\b|motown|gospel|\bdisco\b", {SOUL: 1}),
    (r"country|\bfolk|bluegrass|americana|celtic|\bvis(a|or)\b", {FOLK: 1}),
    (r"reggae|\bska\b|dancehall|rocksteady|\bragga", {REGGAE: 1}),
    (r"comedy|humou?r|parody|stand.?up", {COMEDY: 1}),
    (r"children'?s|\bkids\b|barnmusik|barnvis", {KIDS: 1}),
    (r"\blatin|salsa|tango|flamenco|balkan|\bafro|cuban|\bworld\b", {WORLD: 1}),
    (r"\btrance|techno|\bhouse\b|electro|elektro|ambient|\bidm\b|breakbeat|\bbreaks\b|\bdrum|\bbass\b|jungle|\bchill|downtempo|trip[ -]?hop|\bdub\b|dubstep|\bedm\b|\bdance\b|synth", {ELEC: 1}),
    (r"punk|\brock\b|grunge|\bindie\b|alternative|\bprog\b", {ROCK: 1}),
    (r"\bpop\b", {POP: 1}),
]
FALLBACKS = [(re.compile(p), g) for p, g in FALLBACKS]

# Umbrella tags that sit on nearly every release of their family; they count
# half so the specific tags decide.
GENERIC = {"electronic", "electronica", "electronic music"}


def _parse_exact(table):
    exact = {}
    for line in table.strip().splitlines():
        tags, _, target = line.partition("=")
        target = target.strip()
        if target == "-":
            shares = {}
        else:
            shares = {}
            for part in target.split():
                key, _, frac = part.partition(":")
                shares[_ABBR[key]] = float(frac) if frac else 1.0
        for tag in tags.split():
            exact[hk(tag)] = shares
    return exact


def hk(tag):
    """Hyphen-insensitive lookup key ("full-on" == "full on")."""
    return re.sub(r"\s+", " ", tag.replace("-", " ")).strip()


class GenreMapper:
    """Maps free-form genre tags onto MAIN_GENRES."""

    def __init__(self):
        import beetsplug.lastgenre as lg

        base = os.path.dirname(lg.__file__)
        self.exact = _parse_exact(EXACT_TABLE)
        with open(os.path.join(base, "aliases.yaml")) as f:
            aliases = yaml.safe_load(f)
        self.aliases = [(re.compile(p), tmpl)
                        for tmpl, pats in aliases.items() for p in pats]
        with open(os.path.join(base, "genres-tree.yaml")) as f:
            tree = yaml.safe_load(f)
        self.tree_nodes = {hk(k): v for k, v in TREE_NODES.items()}
        self.parents = defaultdict(set)
        self._walk_tree(tree, None)
        self.cache = {}

    def _walk_tree(self, node, parent):
        if isinstance(node, list):
            for n in node:
                self._walk_tree(n, parent)
        elif isinstance(node, dict):
            for k, v in node.items():
                if parent:
                    self.parents[hk(k)].add(parent)
                self._walk_tree(v, hk(k))
        elif isinstance(node, str) and parent:
            self.parents[hk(node)].add(parent)

    def normalize(self, tag):
        t = re.sub(r"[_\s]+", " ", tag.lower()).strip(" -_.")
        t = re.sub(r"^general ", "", t)
        for pat, tmpl in self.aliases:
            if m := pat.fullmatch(t):
                try:
                    return m.expand(tmpl)
                except (re.error, IndexError):
                    pass
        return t

    def _tree_lookup(self, tag):
        """Collect the mapping of the nearest mapped ancestor on every chain."""
        results = []
        stack = [(tag, 0)]
        seen = set()
        while stack:
            node, depth = stack.pop()
            if node in seen or depth > 12:
                continue
            seen.add(node)
            if node in self.tree_nodes:
                results.append(self.tree_nodes[node])
                continue
            for p in self.parents.get(node, ()):
                stack.append((p, depth + 1))
        if not results:
            return None
        merged = Counter()
        for r in results:
            for g, w in r.items():
                merged[g] += w / len(results)
        return dict(merged)

    def map(self, tag):
        """Return ({genre: share}, ambiguous_candidates_or_None)."""
        t = hk(self.normalize(tag))
        if t in self.cache:
            return self.cache[t]
        res = ({}, None)
        if t in AMBIGUOUS:
            res = ({}, AMBIGUOUS[t])
        elif t in self.exact:
            res = (self.exact[t], None)
        elif re.search(r"metal", t):
            res = ({METAL: 1}, None)
        elif (tm := self._tree_lookup(t)) is not None:
            res = (tm, None)
        else:
            for pat, g in FALLBACKS:
                if pat.search(t):
                    res = (g, None)
                    break
        self.cache[t] = res
        return res


def split_genre_string(s):
    return [p for p in re.split(r"\s*[;,]\s*|\s+/\s+", s or "") if p.strip()]


# --------------------------------------------------------------------------
# Last.fm (through beets' own pylast network object)
# --------------------------------------------------------------------------


class LastFmTags:
    def __init__(self, cache_path, log):
        global pylast
        import pylast
        from beetsplug.lastgenre.client import LASTFM, PYLAST_EXCEPTIONS

        self.net = LASTFM
        self.errors = PYLAST_EXCEPTIONS
        self.net.enable_rate_limit()
        self.path = cache_path
        self.log = log
        self.lock = threading.Lock()
        self.dirty = 0
        self.failed = 0
        try:
            with open(cache_path) as f:
                self.cache = json.load(f)
        except (OSError, ValueError):
            self.cache = {}

    def save(self):
        with self.lock:
            tmp = self.path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(self.cache, f, ensure_ascii=False)
            os.replace(tmp, self.path)
            self.dirty = 0

    def _get(self, key, fn):
        if key in self.cache:
            return self.cache[key]
        tags = None
        for delay in (2, 5, 10, 20, 40, None):
            try:
                tags = [[t.item.get_name(), int(t.weight or 0)]
                        for t in fn().get_top_tags(limit=15)]
                break
            except self.errors as exc:
                msg = str(exc).lower()
                if isinstance(exc, pylast.WSError) and (
                        "not found" in msg or "could not be found" in msg
                        or getattr(exc, "status", None) in ("6",)):
                    tags = []
                    break
                self.log.warning("last.fm error ({}): {} {}",
                                 key.replace("\x1f", " / "), type(exc).__name__, exc)
                if delay:
                    time.sleep(delay)
            except Exception as exc:  # isolate pylast bugs
                self.log.warning("pylast error {}: {}", key, exc)
                tags = []
                break
        if tags is None:
            self.failed += 1
            return []  # transient failure: don't cache
        self.cache[key] = tags
        self.dirty += 1
        if self.dirty >= 50:
            self.save()
        return tags

    def album(self, artist, album):
        if not artist or not album:
            return []
        key = f"album\x1f{artist.lower()}\x1f{album.lower()}"
        return self._get(key, lambda: self.net.get_album(artist, album))

    def artist(self, artist):
        if not artist:
            return []
        key = f"artist\x1f{artist.lower()}"
        return self._get(key, lambda: self.net.get_artist(artist))


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def nkey(s):
    """Case/Unicode-insensitive comparison key."""
    s = unicodedata.normalize("NFKC", s or "").casefold()
    return re.sub(r"\s+", " ", s).strip()


DISC_SUFFIX = re.compile(
    r"[\s\-_:,]*[\(\[]?\s*(cd|dis[ck]|vol(ume)?\.?|part)\s*\d+\s*(of\s*\d+)?[\)\]]?\s*$",
    re.I)


# vinyl side positions in titles: "A1 Title", "B3,B4 Title", "01. A1. Title"
VINYL_POS = re.compile(
    r"^(?:\d{1,2}[.\s]+)?([A-H])(\d{1,2})(?:\s*,\s*[A-H]\d{1,2})*(?:\s*[.\-_]\s*|\s+)(.+)$")
LOSSLESS = {"FLAC", "WAVPACK", "ALAC", "APE", "WAV", "AIFF"}

NUM_TAIL = re.compile(r"\s*[\(\[]\s*\d{1,2}\s*[\)\]]\s*$")


def norm_album(s):
    s = nkey(s)
    s = re.sub(r"\s+-\s+(single|ep)$", "", s)
    s = re.sub(r"\s*[\(\[][^\)\]]*(remaster|deluxe|edition|version|expanded|anniversary|bonus)"
               r"[^\)\]]*[\)\]]", "", s)
    return s.strip()


def album_key(s):
    return nkey(DISC_SUFFIX.sub("", s or ""))


def item_format(item):
    return (item.format or os.path.splitext(item.path)[1].lstrip(b".").decode()).upper()


VA_NAMES = {"various", "various artists", "various artist", "va", "v.a.", "v/a",
            "v. a.", "diverse", "diverse artister", "div. artister", "blandade artister",
            "varios", "varios artistas", "verschiedene", "verschiedene interpreten",
            "artistes divers", "various performers"}

DISC_DIR = re.compile(r"^(cd|dis[ck])[\s_-]*(\d+)\b", re.I)
JUNK_TAIL = re.compile(
    r"\s*([\(\[{][^\)\]}]*(kbps|kbit|mp3|flac|www|torrent|\d{3}k|vbr|cbr|cover|cd\b|web|"
    r"retail|promo|\d{2}bit)[^\)\]}]*[\)\]}]|@\s*\d+|-\s*\d{3}k\S*|\s\d{3}kbps\S*)\s*$",
    re.I)
SCENE_TAGS = re.compile(
    r"-(?=\(|\d?CDS?\b|CDM\b|CDR\b|Promo|Vinyl|VLS\b|EP\b|LP\b|Ltd|Limited|Retail|"
    r"WEB\b|Advance|Bootleg|Remastered|Deluxe|[A-Z]{2,5}\d{2,})", re.I)


def clean_title(s):
    prev = None
    while prev != s:
        prev = s
        s = JUNK_TAIL.sub("", s).strip(" -_")
    return s


def parse_dirname(name):
    """Guess (artist, album, year) from a release folder name."""
    year = 0
    if "_-_" in name or ("_" in name and " " not in name):
        s = name.replace("_", " ")
        m = re.match(r"^(.+?) - (.+?)-((?:19|20)\d\d)-[^-]+$", s)
        if m:
            artist, album, year = m.group(1), m.group(2), int(m.group(3))
        else:
            m = re.match(r"^(.+?) - (.+?)(?:-[A-Za-z0-9]{2,8})?$", s)
            if not m:
                return None
            artist, album = m.group(1), m.group(2)
        album = SCENE_TAGS.split(album)[0]
        return artist.strip(), album.strip(" -"), year
    # "Artist-Album-LP-32BIT-WAVPACK-1977-GROUP" (release style with spaces)
    m = re.match(r"^([^-]+?)-([^-].*?)-(?:.*-)?((?:19|20)\d\d)-[A-Za-z0-9]+$", name)
    if m and " - " not in name:
        album = SCENE_TAGS.split(m.group(2))[0]
        return m.group(1).strip(), re.sub(r"\s+", " ", album).strip(" -"), int(m.group(3))
    s = clean_title(name)
    for pat in (r"^(?P<a>.+?) - [\(\[]?(?P<y>(?:19|20)\d\d)[\)\]]? - (?P<b>.+)$",
                r"^(?P<a>.+?) - (?P<b>.+?)\s*[\(\[](?P<y>(?:19|20)\d\d)[\)\]].*$",
                r"^(?P<a>.+?) - (?P<b>.+)$"):
        m = re.match(pat, s)
        if m:
            y = m.groupdict().get("y")
            return m.group("a").strip(), clean_title(m.group("b")), int(y) if y else 0
    return None


def parse_filename(stem, scene):
    """Guess (disc, track, rest) from a file name without extension."""
    if scene or ("_" in stem and " " not in stem):
        stem = stem.replace("_", " ")
        stem = re.sub(r"-[A-Za-z0-9]{2,10}$", "", stem)
    m = re.match(r"^(?:(?P<d>\d)-)?(?P<n>\d{1,3})(?:\s*[-.)]\s*|\s+)(?P<rest>.+)$", stem)
    if m:
        return int(m.group("d") or 0), int(m.group("n")), m.group("rest").strip()
    return 0, 0, stem.strip()


BAD_NAMES = {"", "unknown", "unknown artist", "unknown album", "various", "untitled",
             "track", "artist", "album", "<unknown>", "[notag]", "notag", "n/a", "-",
             "no title", "none", "title", "<undefined>", "undefined"}


def present(s):
    return nkey(s) not in BAD_NAMES


# --------------------------------------------------------------------------
# Plugin
# --------------------------------------------------------------------------


class MusicOrgPlugin(BeetsPlugin):
    def __init__(self):
        super().__init__()
        self.config.add({
            "lastfm_cache": "~/.local/share/musicorg/lastfm-cache.json",
            "min_score": 30.0,
            "overrides": "~/.local/share/musicorg/genre-overrides.yaml",
            # {"artist name": "Genre folder"} for artists already in the library (written by Muzix)
            "artist_genres": "",
        })
        self.register_listener("import_task_created", self.on_task_created)
        self._mapper = None
        self._patch_itunes()

    # ---- fetchart tweaks -----------------------------------------------------
    def _patch_itunes(self):
        """iTunes: accept only real name matches (never "first search result").
        Folder images: also look in the parent of CD1/CD2 folders, skip folders
        that hold other albums' songs, and accept an oddly named image only
        when it is the folder's sole image."""
        try:
            from beetsplug import fetchart
        except ImportError:
            return
        if getattr(fetchart.ITunesStore, "_musicorg_patched", False):
            return

        def itunes_get(self_, album, plugin, paths):
            if not (album.albumartist and album.album):
                return
            payload = {"term": f"{album.albumartist} {album.album}",
                       "entity": "album", "media": "music", "limit": 200}
            try:
                r = self_.request(self_.API_URL, params=payload)
                r.raise_for_status()
                results = r.json()["results"]
            except Exception as e:  # network/JSON problems: no candidate
                self_._log.debug("iTunes search failed: {}", e)
                return
            size = ("100000x100000-999" if self_._config["high_resolution"]
                    else "1200x1200bb")
            want = (nkey(album.albumartist), norm_album(album.album))
            for c in results:
                got = (nkey(c.get("artistName")), norm_album(c.get("collectionName")))
                if got == want and c.get("artworkUrl100"):
                    yield self_._candidate(
                        url=c["artworkUrl100"].replace("100x100bb", size),
                        match=fetchart.MetadataMatch.EXACT)

        orig_fs = fetchart.FileSystem.get
        exts = tuple(b"." + e for e in fetchart.IMAGE_EXTENSIONS)

        def fs_get(self_, album, plugin, paths):
            if not paths:
                return
            mine = Counter(os.path.dirname(i.path) for i in album.items())
            search = []
            for p in list(paths) + list(mine):
                for q in (p, os.path.dirname(p) if DISC_DIR.match(
                        os.fsdecode(os.path.basename(p))) else None):
                    if q and q not in search:
                        search.append(q)
            for p in search:
                try:
                    names = os.listdir(p)
                except OSError:
                    continue
                n_audio = sum(1 for f in names if f.lower().endswith((b".mp3", b".flac")))
                if n_audio > mine.get(p, 0):
                    continue  # folder shared with other albums
                n_img = sum(1 for f in names if f.lower().endswith(exts))
                for cand in orig_fs(self_, album, plugin, [p]):
                    if cand.match == fetchart.MetadataMatch.EXACT or n_img == 1:
                        yield cand

        fetchart.ITunesStore.get = itunes_get
        fetchart.FileSystem.get = fs_get
        fetchart.ITunesStore._musicorg_patched = True

    @property
    def mapper(self):
        if self._mapper is None:
            self._mapper = GenreMapper()
        return self._mapper

    # ---- import hook ------------------------------------------------------
    def on_task_created(self, session, task):
        if type(task) is not ImportTask or not task.items:
            return None
        for item in task.items:
            item["mo_orig_path"] = os.fsdecode(item.path)
            item["mo_orig_genre"] = "; ".join(item.genres or [])
        self._infer_tags(task.items)
        for item in task.items:
            if nkey(item.albumartist) in VA_NAMES:
                item.albumartist = config["va_name"].as_str()
                item.comp = True
        groups = self._split(task.items, session)
        if len(groups) <= 1:
            return None
        self._log.info("splitting {} into {} albums",
                       os.fsdecode(task.toppath or b"?"), len(groups))
        return [ImportTask(task.toppath, task.paths, g) for g in groups]

    def _infer_tags(self, items):
        """Fill missing artist/album/title/track from folder and file names."""
        root = os.fsdecode(config["directory"].as_filename()).rstrip("/")
        by_dir = defaultdict(list)
        for it in items:
            by_dir[os.path.dirname(os.fsdecode(it.path))].append(it)
        for d, its in by_dir.items():
            if d == root:
                continue
            name = os.path.basename(d)
            disc = 0
            if m := DISC_DIR.match(name):
                disc = int(m.group(2))
                name = os.path.basename(os.path.dirname(d))
            scene = "_-_" in name or ("_" in name and " " not in name)
            guess = None
            if sum(1 for i in its if present(i.album)) < len(its) / 2:
                guess = parse_dirname(name)
            for it in its:
                changed = []
                if guess:
                    artist, album, year = guess
                    if nkey(album) in ("soundtrack", "ost", "original soundtrack", "score"):
                        artist, album = "", artist
                    if not present(it.album) and album:
                        it.album = album
                        changed.append("album")
                    if artist and not present(it.albumartist) and not present(it.artist):
                        it.albumartist = artist
                        changed.append("albumartist")
                    if year and not it.year:
                        it.year = year
                        changed.append("year")
                if disc and not it.disc:
                    it.disc = disc
                    changed.append("disc")
                if not present(it.title):
                    stem = os.path.splitext(os.path.basename(os.fsdecode(it.path)))[0]
                    fdisc, num, rest = parse_filename(stem, scene)
                    art = it.artist or it.albumartist
                    parts = rest.split(" - ")
                    if len(parts) >= 2 and art and nkey(parts[0]) == nkey(art):
                        rest = " - ".join(parts[1:])
                    elif len(parts) >= 2 and nkey(it.albumartist) in VA_NAMES | {"various artists"} \
                            and not present(it.artist):
                        it.artist, rest = parts[0], " - ".join(parts[1:])
                        changed.append("artist")
                    it.title = rest
                    changed.append("title")
                    if num and not it.track:
                        it.track = num
                        changed.append("track")
                    if fdisc and not it.disc:
                        it.disc = fdisc
                if not present(it.artist) and present(it.albumartist):
                    it.artist = it.albumartist
                    changed.append("artist")
                if changed:
                    it["mo_inferred"] = ",".join(changed)

    def _split(self, items, session):
        root = os.fsdecode(config["directory"].as_filename()).rstrip("/")
        groups = defaultdict(list)
        for it in items:
            groups[item_format(it) in ("FLAC",)].append(it)
        out = []
        for grp in groups.values():
            if os.path.dirname(os.fsdecode(grp[0].path)) == root:
                # loose files in the library root: every song stands alone
                # unless it shares artist + album with another loose song
                def key(i):
                    if not album_key(i.album):
                        return os.fsdecode(i.path)
                    return album_key(i.album), nkey(i.albumartist or i.artist)
            else:
                def key(i):
                    return album_key(i.album)
            keys = Counter(key(i) for i in grp)
            top_share = keys.most_common(1)[0][1] / len(grp)
            if len(keys) > 1 and (top_share < 0.5 or
                                  os.path.dirname(os.fsdecode(grp[0].path)) == root):
                by = defaultdict(list)
                for i in grp:
                    by[key(i)].append(i)
                out.extend(by.values())
            else:
                out.append(grp)
        return out

    # ---- commands -----------------------------------------------------------
    def commands(self):
        g = Subcommand("mgenre", help="decide main genre per album")
        g.parser.add_option("-f", "--force", action="store_true",
                            help="recompute albums that already have one")
        g.parser.add_option("-v", "--explain", action="store_true",
                            help="print scores per album")
        g.func = self.cmd_mgenre

        p = Subcommand("mplan", help="compute destination path fields")
        p.func = self.cmd_mplan

        r = Subcommand("mreport", help="summarise the plan")
        r.parser.add_option("-o", "--out", help="write full plan TSV here")
        r.func = self.cmd_mreport
        return [g, p, r]

    # ---- main genre ---------------------------------------------------------
    def score_album(self, album, lastfm):
        mapper = self.mapper
        items = list(album.items())
        scores = Counter()
        ambiguous = []
        evidence = []

        def add(tag, weight, source):
            if weight <= 0:
                return
            if hk(mapper.normalize(tag)) in GENERIC:
                weight *= 0.5
            shares, amb = mapper.map(tag)
            if amb:
                ambiguous.append((amb, weight))
                evidence.append(f"{source}:{tag}~{weight:.0f}")
            for g, s in shares.items():
                scores[g] += weight * s
            if shares:
                evidence.append(f"{source}:{tag}={weight:.0f}")

        # 1. original file genre tags
        file_genres = Counter()
        for it in items:
            for g in set(nkey(x) for x in split_genre_string(it.get("mo_orig_genre", ""))):
                file_genres[g] += 1
        for g, n in file_genres.items():
            w = 35.0 * n / len(items)
            if g == "blues":  # ID3v1 genre 0: often a bogus default
                w *= 0.3
            add(g, w, "file")

        # 2. MusicBrainz genres (only present on matched albums)
        if album.mb_albumid:
            # kept aside: mplan later replaces the genres tag with the main genre
            mbg = json.loads(album.get("mo_mb_genres") or "null")
            if mbg is None:
                mbg = []
                for it in items:
                    cur = "; ".join(it.genres or [])
                    if cur and cur != it.get("mo_orig_genre", ""):
                        mbg = list(it.genres)
                        break
                album["mo_mb_genres"] = json.dumps(mbg)
            for w, g in zip((60, 45, 35, 25, 20), mbg):
                add(g, w, "mb")
            if "soundtrack" in (album.albumtypes or []):
                scores[OST] += 80
                evidence.append("mb:type=soundtrack")

        # 3. Last.fm album + artist tags
        aa = album.albumartist
        is_va = album.comp or nkey(aa) in ("various artists", "va", "various")
        for name, w in lastfm.album(aa if not is_va else "Various Artists",
                                    album.album)[:15]:
            if w >= 10:
                add(name, w * 1.0, "lfm-album")
        if not is_va:
            for name, w in lastfm.artist(aa)[:15]:
                if w >= 10:
                    add(name, w * 0.6, "lfm-artist")
        else:
            artists = Counter(it.artist for it in items if present(it.artist))
            chosen = [a for a, _ in artists.most_common(12)]
            for a in chosen:
                for name, w in lastfm.artist(a)[:10]:
                    if w >= 10:
                        add(name, w * 0.6 / len(chosen), "lfm-va")

        # 4. folder names (parent folders weigh more: often hand-made categories)
        root = os.fsdecode(config["directory"].as_filename()).rstrip("/")
        orig = items[0].get("mo_orig_path", os.fsdecode(items[0].path))
        rel = os.path.relpath(os.path.dirname(orig), root)
        parts = [] if rel == "." else rel.split(os.sep)
        for i, part in enumerate(parts):
            add(part, 10.0 if i == len(parts) - 1 else 25.0, "dir")

        for cands, w in ambiguous:
            best = max(cands, key=lambda g: scores[g])
            if scores[best] > 0:
                scores[best] += w
        return scores, evidence

    def cmd_mgenre(self, lib, opts, args):
        lastfm = LastFmTags(os.path.expanduser(self.config["lastfm_cache"].get(str)),
                            self._log)
        min_score = self.config["min_score"].get(float)
        albums = list(lib.albums(args))
        t0 = time.time()
        skipped = 0
        try:
            for n, album in enumerate(albums, 1):
                if album.get("mo_genre") is not None and not opts.force:
                    continue
                failed_before = lastfm.failed
                scores, evidence = self.score_album(album, lastfm)
                if lastfm.failed > failed_before:
                    skipped += 1  # leave unset; a later run retries it
                    continue
                ranked = scores.most_common()
                best = ranked[0] if ranked else (None, 0)
                genre = best[0] if best[1] >= min_score else ""
                # Psytrance is a branch of Electronic: once it has a solid
                # share, the umbrella genre should not outvote it
                if genre == ELEC and scores[PSY] >= max(min_score, 0.5 * scores[ELEC]):
                    genre = PSY
                album["mo_genre"] = genre
                album["mo_genre_scores"] = json.dumps(
                    {g: round(s) for g, s in ranked[:4]})
                album["mo_genre_evidence"] = " | ".join(evidence[:25])
                album.store()
                if opts.explain:
                    print(f"{album.albumartist} - {album.album}: {genre or '-'} "
                          f"{album['mo_genre_scores']}\n    {album['mo_genre_evidence']}")
                if n % 50 == 0:
                    print(f"mgenre {n}/{len(albums)} {time.time() - t0:.0f}s",
                          flush=True)
        finally:
            lastfm.save()
        print(f"mgenre done: {len(albums)} albums, {skipped} left for retry "
              f"(Last.fm errors)")

    # ---- planning -----------------------------------------------------------
    def _merge_numbered(self, albums, root):
        """Re-join albums that were split only because their album tags carry
        a track number: "Dancing Galaxy (1)" ... "Dancing Galaxy (8)"."""
        groups = defaultdict(list)
        for a in albums:
            if a.mb_albumid or not NUM_TAIL.search(a.album or ""):
                continue
            items = list(a.items())
            d = os.path.dirname(items[0].get("mo_orig_path", os.fsdecode(items[0].path)))
            if d != root:
                key = (d, album_key(NUM_TAIL.sub("", a.album)), item_format(items[0]))
                groups[key].append(a)
        merged = 0
        for grp in groups.values():
            if len(grp) < 2:
                continue
            grp.sort(key=lambda a: -len(a.items()))
            keep = grp[0]
            for other in grp[1:]:
                for it in other.items():
                    it.album_id = keep.id
                    it.store()
                if not keep.artpath and other.artpath:
                    keep.artpath = other.artpath
                other.remove(delete=False, with_items=False)
            keep.album = NUM_TAIL.sub("", keep.album).strip()
            if keep.get("mo_genre") is not None:
                del keep["mo_genre"]
            keep["mo_repaired"] = "merged"
            keep.store()
            merged += 1
        return merged

    def _repair_asis(self, a, root):
        """Fill a missing album artist / album name of an unmatched album from
        its folder and file names, only where two hints agree."""
        if a.mb_albumid:
            return
        items = list(a.items())
        va = config["va_name"].as_str()
        if nkey(a.albumartist) in VA_NAMES and a.albumartist != va:
            a.albumartist = va
            a.comp = True
            a["mo_repaired"] = "va"
            if a.get("mo_genre") is not None:
                del a["mo_genre"]
            a.store()
            for it in a.items():
                for sep in (" - ", " / "):
                    if nkey(it.artist) in VA_NAMES and sep in it.title:
                        it.artist, it.title = [x.strip() for x in it.title.split(sep, 1)]
                        it.store()
            return
        artist = a.albumartist if present(a.albumartist) else ""
        album = a.album if present(a.album) else ""
        if artist and album:
            return
        d = os.path.dirname(items[0].get("mo_orig_path", os.fsdecode(items[0].path)))
        if d == root:
            return
        name, parent = os.path.basename(d), os.path.dirname(d)
        if DISC_DIR.match(name):
            name, parent = os.path.basename(parent), os.path.dirname(parent)
        parent_name = "" if parent == root else os.path.basename(parent)
        folder = nkey(name.replace("_", " "))
        guess = parse_dirname(name)
        bracketed = re.match(r"^\[[^\]]+\] - ", name)  # "[Artist] - Album" folders
        if guess and bracketed:
            guess = (guess[0].strip("[] "), guess[1], guess[2])
        # only titles that were made from file names get prefixes stripped
        titles = {it.id: it.title for it in items if "title" in (it.get("mo_inferred") or "")}

        def lead():
            c = Counter(t.split(" - ", 1)[0].strip() for t in titles.values() if " - " in t)
            if c:
                x, n = c.most_common(1)[0]
                if n >= 0.8 * len(items) and present(x):
                    return x
            return ""

        def strip_lead(x):
            for k, t in titles.items():
                if " - " in t and nkey(t.split(" - ", 1)[0]) == nkey(x):
                    titles[k] = t.split(" - ", 1)[1].strip()

        new = {}
        if not artist:
            x = lead()
            if x and nkey(x) != nkey(album) and (
                    re.match(re.escape(nkey(x)) + r"(?!\w)", folder) or nkey(x) == nkey(parent_name)):
                artist = new["albumartist"] = x
            elif guess and guess[0] and (bracketed or nkey(guess[0]) == nkey(parent_name) or (
                    album and norm_album(guess[1]) == norm_album(album))):
                artist = new["albumartist"] = guess[0]
        if not artist or nkey(artist) in VA_NAMES:
            return
        strip_lead(artist)
        seg = lead()
        if seg and (nkey(seg) == nkey(album) or nkey(seg) in folder):
            if not album or nkey(album) not in folder:
                album = new["album"] = seg
            strip_lead(seg)
        if not album:
            if guess and nkey(guess[0]) == nkey(artist) and guess[1]:
                album = new["album"] = guess[1]
                if guess[2] and not a.year:
                    new["year"] = guess[2]
            elif parent_name and nkey(parent_name) == nkey(artist):
                m = re.match(r"^(.*?)\s*[\(\[]((?:19|20)\d\d)[\)\]]\s*$", clean_title(name))
                album = new["album"] = m.group(1) if m else clean_title(name)
                if m and not a.year:
                    new["year"] = int(m.group(2))
        if not new:
            return
        for it in items:
            if it.id in titles:
                t = titles[it.id]
                m = re.match(r"^(\d{1,3})\s*[-.]\s+(.+)$", t)
                if m:
                    it.track = it.track or int(m.group(1))
                    t = m.group(2)
                it.title = t
            if not present(it.artist):
                it.artist = artist
            it.store()
        for k, v in new.items():
            a[k] = v
        a["mo_repaired"] = "tags"
        if a.get("mo_genre") is not None:
            del a["mo_genre"]
        a.store()

    def _artist_genres(self):
        path = self.config["artist_genres"].as_str()
        if not path or not os.path.isfile(os.path.expanduser(path)):
            return {}
        with open(os.path.expanduser(path)) as f:
            return {nkey(k): v for k, v in json.load(f).items() if v in MAIN_GENRES}

    def _overrides(self):
        path = os.path.expanduser(self.config["overrides"].as_str())
        out = {}
        if os.path.isfile(path):
            with open(path) as f:
                for k, v in (yaml.safe_load(f) or {}).items():
                    if v in MAIN_GENRES:
                        out[nkey(str(k))] = v
                    else:
                        self._log.warning("genre override {}: unknown genre {!r}", k, v)
        return out

    def cmd_mplan(self, lib, opts, args):
        root = os.fsdecode(config["directory"].as_filename()).rstrip("/")
        albums = list(lib.albums(args))
        if self._merge_numbered(albums, root):
            albums = list(lib.albums(args))
        for a in albums:
            self._repair_asis(a, root)
        info = {}

        # as-is albums: album-level fields come from the first track only;
        # use the most common non-empty value instead and tidy whitespace
        for a in albums:
            if a.mb_albumid:
                continue
            items = list(a.items())
            va = config["va_name"].as_str()
            for it in items:
                old = {f: it.get(f) or "" for f in ("title", "artist", "album", "albumartist")}
                for f in old:
                    it[f] = re.sub(r"\s+", " ", old[f]).strip()
                # "01 - Title" in the title tag
                m = re.match(r"^(\d{1,3})\s*[-.]\s+(.+)$", it.title)
                if m and it.track and int(m.group(1)) == it.track:
                    it.title = m.group(2)
                # compilation tracks tagged artist="Various Artists", title="Artist - Title"
                if nkey(it.artist) in VA_NAMES and " - " in it.title:
                    it.artist, it.title = [x.strip() for x in it.title.split(" - ", 1)]
                if any(it.get(f) != old[f] for f in old):
                    it.store()
            # vinyl rips: side positions in the titles give the track order
            vin = [VINYL_POS.match(it.title or "") for it in items]
            pos = {(m.group(1), int(m.group(2))) for m in vin if m}
            if len(items) > 1 and len(pos) >= 0.8 * len(items):
                renumber = not any(it.track for it in items)
                order = sorted(range(len(items)), key=lambda k: (
                    (vin[k].group(1), int(vin[k].group(2))) if vin[k] else ("Z", 0)))
                for n, k in enumerate(order, 1):
                    it = items[k]
                    if vin[k] and present(vin[k].group(3).strip()):
                        it.title = vin[k].group(3).strip()
                    if renumber:
                        it.track = n
                    it.store()
            # no track numbers in the tags: take them from the file names
            # when every file has one and none repeats
            if not any(it.track for it in items):
                nums = []
                for it in items:
                    orig = it.get("mo_orig_path", os.fsdecode(it.path))
                    stem = os.path.splitext(os.path.basename(orig))[0]
                    fd, n, _ = parse_filename(stem, "_" in stem and " " not in stem)
                    nums.append((it.disc or fd, os.path.dirname(orig), n))
                if all(n for *_, n in nums) and len(set(nums)) == len(nums):
                    for it, (dn, _, n) in zip(items, nums):
                        it.track = n
                        it.disc = it.disc or dn
                        it.store()
            per_disc = Counter(it.disc for it in items)
            for it in items:
                if it.track and not it.tracktotal:
                    it.tracktotal = per_disc[it.disc]
                    it.store()
            changed = False
            for f in ("album", "albumartist", "year"):
                vals = Counter(it.get(f) for it in items if it.get(f))
                if vals:
                    best = vals.most_common(1)[0][0]
                    if a.get(f) != best:
                        a[f] = best
                        changed = True
            if changed:
                a.store(inherit=True)

        # two albums must never point at the same cover file
        seen_art = set()
        for a in albums:
            if not a.artpath:
                continue
            path = os.fsdecode(a.artpath)
            if path in seen_art and os.path.isfile(path):
                stem, ext = os.path.splitext(path)
                n = 1
                while os.path.exists(f"{stem}.{n}{ext}"):
                    n += 1
                shutil.copy2(path, f"{stem}.{n}{ext}")
                a.artpath = f"{stem}.{n}{ext}"
                a.store()
            seen_art.add(os.fsdecode(a.artpath))

        # canonical spelling per album artist (prefer MusicBrainz spelling)
        spellings = defaultdict(Counter)
        for a in albums:
            if present(a.albumartist):
                spellings[nkey(a.albumartist)][a.albumartist] += 10 if a.mb_albumid else 1
        canon = {k: c.most_common(1)[0][0] for k, c in spellings.items()}

        for a in albums:
            items = sorted(a.items(), key=lambda i: (i.disc, i.track, i.title))
            origs = [i.get("mo_orig_path", os.fsdecode(i.path)) for i in items]
            orig_dir = os.path.dirname(origs[0])
            matched = bool(a.mb_albumid)
            artist = canon.get(nkey(a.albumartist), "")
            title = a.album if present(a.album) else ""
            year = a.year or 0
            reason = ""
            if all(os.path.dirname(o) == root for o in origs):
                reason = "loose file in root folder"
            elif len(items) == 1 and not (matched and (items[0].tracktotal or 0) == 1):
                reason = "single song from an album"
            elif not matched and (not artist or not title):
                reason = "missing artist/album tags"
            elif not a.get("mo_genre"):
                reason = "no genre match"
            fmts = Counter(item_format(i) for i in items)
            bitrate = sum(i.bitrate or 0 for i in items) / max(len(items), 1)
            info[a.id] = dict(album=a, items=items, origs=origs, orig_dir=orig_dir,
                              artist=artist, title=title, year=year, reason=reason,
                              lossless=bool(set(fmts) & LOSSLESS), fmts=fmts, bitrate=bitrate,
                              genre=a.get("mo_genre") or "")

        # one genre folder per artist: the genre most of their albums got
        # (ties: summed scores); also covers their albums with no genre match
        va_key = nkey(config["va_name"].as_str())
        mb_ids = defaultdict(set)
        for d in info.values():
            if d["album"].mb_albumartistid:
                mb_ids[nkey(d["artist"])].add(d["album"].mb_albumartistid)

        def artist_key(d):
            # different MusicBrainz artists sharing a name keep their own genres
            k = nkey(d["artist"])
            return (k, d["album"].mb_albumartistid or "") if len(mb_ids[k]) > 1 else (k, "")

        votes, weight = defaultdict(Counter), defaultdict(Counter)
        for d in info.values():
            if d["reason"] == "" and d["artist"] and nkey(d["artist"]) != va_key:
                k = artist_key(d)
                votes[k][d["genre"]] += 1
                for g, s in json.loads(d["album"].get("mo_genre_scores") or "{}").items():
                    weight[k][g] += s
        for d in info.values():
            k = artist_key(d)
            if k in votes and d["reason"] in ("", "no genre match"):
                d["genre"] = max(votes[k], key=lambda g: (votes[k][g], weight[k][g]))
                d["reason"] = ""

        # artists that already live in a genre folder of the library stay there
        known = self._artist_genres()
        for d in info.values():
            g = known.get(nkey(d["artist"]))
            if g and d["reason"] in ("", "no genre match"):
                d["genre"], d["reason"] = g, ""

        # hand-made corrections win: "artist" or "artist - album" -> genre
        overrides = self._overrides()
        for d in info.values():
            g = overrides.get(nkey(f"{d['artist']} - {d['title']}")) or overrides.get(nkey(d["artist"]))
            if g and d["reason"] in ("", "no genre match"):
                d["genre"], d["reason"] = g, ""

        def albumdir(d):
            if d["artist"] and d["title"]:
                yr = f"{d['year']} - " if d["year"] else ""
                return f"{d['artist']} - {yr}{d['title']}"
            if d["orig_dir"] == root:
                return "Loose files"
            # untagged: the whole original path, so "CD 1" folders stay apart
            return os.path.relpath(d["orig_dir"], root).replace(os.sep, " - ")

        # a hi-res WavPack rip is its own edition next to a CD/FLAC/mp3 copy
        for d in info.values():
            d["dir"] = albumdir(d)
        plain = {(nkey(d["artist"]), nkey(d["dir"])) for d in info.values() if "WAVPACK" not in d["fmts"]}
        for d in info.values():
            if "WAVPACK" in d["fmts"] and d["artist"] and (nkey(d["artist"]), nkey(d["dir"])) in plain:
                d["dir"] += " (WavPack)"

        # duplicates: same artist + album folder name among normal albums
        groups = defaultdict(list)
        for d in info.values():
            if d["reason"] in ("", "no genre match", "missing artist/album tags") \
                    and d["artist"] and d["title"]:
                groups[(nkey(d["artist"]), nkey(d["dir"]))].append(d)
        for grp in groups.values():
            if len(grp) < 2:
                continue
            grp.sort(key=lambda d: (d["lossless"], bool(d["album"].mb_albumid),
                                    len(d["items"]), d["bitrate"]), reverse=True)
            for n, d in enumerate(grp[1:], 2):
                d["dupe_of"] = grp[0]["orig_dir"]
                d["dir"] = f"{d['dir']} ({n})"

        # every album gets a folder of its own
        taken = Counter()
        for d in sorted(info.values(), key=lambda d: d["orig_dir"]):
            if d.get("dupe_of"):
                d["top"] = DUPES
            elif d["reason"]:
                d["top"] = UNCAT
            else:
                d["top"] = d["genre"]
            d["artist_dir"] = d["artist"] if d["artist"] and d["title"] else "_Untagged"
            if d["artist_dir"] == "_Untagged":
                continue  # named after the original folder, file names kept
            base = d["dir"]
            while True:
                key = (nkey(d["top"]), nkey(d["artist_dir"]), nkey(d["dir"]))
                taken[key] += 1
                if taken[key] == 1:
                    break
                d["dir"] = f"{base} [{taken[key]}]"

        for d in info.values():
            a = d["album"]
            top, artist_dir = d["top"], d["artist_dir"]
            a["mo_root"] = top
            a["mo_artistdir"] = artist_dir
            a["mo_albumdir"] = d["dir"]
            a["mo_reason"] = d["reason"]
            a["mo_dupe_of"] = d.get("dupe_of", "")
            a.store()

            tracked = d["artist"] and d["title"]
            names = []
            for it, orig in zip(d["items"], d["origs"]):
                stem = os.path.splitext(os.path.basename(orig))[0]
                if tracked and present(it.title):
                    art = it.artist if present(it.artist) else d["artist"]
                    yr = it.year or d["year"]
                    name = f"{art} - {d['title']} - {it.title}"
                    if yr:
                        name += f" ({yr})"
                    names.append([it, name])
                else:
                    names.append([it, stem, True])
            # number tracks; prefix disc when per-disc numbers would collide
            nums = Counter(it.track for it, *_ in names if it.track)
            multi = any(c > 1 for c in nums.values())
            seen = Counter()
            for entry in names:
                it, name = entry[0], entry[1]
                if len(entry) == 2 and it.track:
                    num = f"{it.disc}-{it.track}" if multi and it.disc else str(it.track)
                    name = f"{num}. {name}"
                seen[nkey(name)] += 1
                if seen[nkey(name)] > 1:
                    name += f" ({seen[nkey(name)]})"
                it["mo_root"] = top
                it["mo_artistdir"] = artist_dir
                it["mo_albumdir"] = d["dir"]
                it["mo_track"] = name
                if top in MAIN_GENRES:
                    it.genres = [top]
                it.store()
        print(f"planned {len(info)} albums")

    def cmd_mreport(self, lib, opts, args):
        per_root = Counter()
        reasons = Counter()
        rows = []
        for a in lib.albums(args):
            root = a.get("mo_root")
            n = len(a.items())
            per_root[root] += 1
            if a.get("mo_reason"):
                reasons[a["mo_reason"]] += 1
            items = list(a.items())
            rows.append([root, a.get("mo_artistdir"), a.get("mo_albumdir"),
                         a.get("mo_reason", ""), str(n),
                         "MB" if a.mb_albumid else "asis",
                         a.get("mo_genre_scores", ""),
                         a.get("mo_dupe_of", ""),
                         os.path.dirname(items[0].get("mo_orig_path", "")) if items else "",
                         a.get("mo_genre", ""), a.get("mo_repaired", "")])
        for k, v in sorted(per_root.items(), key=lambda kv: -kv[1]):
            print(f"{v:6d}  {k}")
        print("uncategorized reasons:")
        for k, v in reasons.most_common():
            print(f"{v:6d}  {k}")
        if opts.out:
            with open(opts.out, "w") as f:
                f.write("root\tartist\talbumdir\treason\ttracks\tsource\tscores\tdupe_of\torig_dir\town_genre\trepaired\n")
                for r in sorted(rows, key=lambda r: [str(x) for x in r]):
                    f.write("\t".join(str(x) for x in r) + "\n")
