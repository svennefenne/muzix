"""Runtime settings, stored in the database and edited on the admin page.

SCHEMA drives the admin form: every setting has a type, a default, a group
and a short help text, so adding a setting here is all it takes to make it
editable.
"""

from dataclasses import dataclass, field
from threading import RLock

from . import db
from .models import Setting


@dataclass
class Spec:
    key: str
    type: str            # bool | int | float | str | secret | choice | json
    default: object
    group: str
    label: str
    help: str = ""
    choices: list = field(default_factory=list)
    min: float | None = None
    max: float | None = None


SCHEMA: list[Spec] = [
    # general
    Spec("site_name", "str", "Muzix", "General", "Site name"),
    Spec("public_url", "str", "", "General", "Public URL",
         "The HTTPS address Muzix is reached at through your reverse proxy, e.g. "
         "https://muzix.example.com. Needed for Spotify and podcast links."),
    Spec("allow_signup", "bool", False, "General", "Allow sign-up",
         "Let new people create an account from the login page."),
    # library
    Spec("scan_interval_hours", "int", 6, "Library", "Rescan every (hours)",
         "0 turns automatic rescans off.", min=0, max=168),
    Spec("artist_tags", "choice", "musicbrainz", "Library", "Artist genre tags",
         "Where detailed genres (\"death metal\", \"goa trance\") come from. They pick the genre skin.",
         choices=["musicbrainz", "lastfm", "off"]),
    Spec("lastfm_api_key", "secret", "", "Library", "Last.fm API key"),
    # playback
    Spec("transcode_format", "choice", "flac", "Playback", "Transcode to",
         "Format for files a browser can't play (WavPack, chiptunes, trackers, MIDI).",
         choices=["flac", "opus", "mp3"]),
    Spec("max_sample_rate", "int", 96000, "Playback", "Max sample rate",
         "Hi-res files above this are resampled while streaming.", min=44100, max=384000),
    Spec("opus_bitrate", "int", 192, "Playback", "Opus/MP3 bitrate (kbit/s)", min=64, max=320),
    # chiptunes
    Spec("chip_loop_mode", "choice", "loops", "Chiptunes", "Looping songs",
         "Most game music loops forever. \"loops\": play the intro once and the looping part a set "
         "number of times, then fade. \"time\": play every song for a fixed time.",
         choices=["loops", "time"]),
    Spec("chip_loops", "int", 2, "Chiptunes", "Times through the loop",
         "With \"loops\": how often the looping part plays (VGM, YM, FamiTracker, SPC/NSF sets "
         "that carry loop points).", min=1, max=16),
    Spec("chip_length", "int", 180, "Chiptunes", "Fixed time (s)",
         "With \"time\", every song plays this long. With \"loops\", it's used for files that don't "
         "say where they loop (SID, most NSF and GBS).", min=10, max=3600),
    Spec("chip_fade", "int", 8, "Chiptunes", "Fade-out (s)", "How long a looping song fades at the end.",
         min=0, max=60),
    Spec("chip_max_length", "int", 900, "Chiptunes", "Longest song (s)",
         "A cap, so a long loop played many times doesn't run for an hour.", min=30, max=7200),
    Spec("module_repeats", "int", 1, "Chiptunes", "Play tracker modules (times)",
         "MOD/XM/IT/S3M/MT2 songs usually end by themselves; 1 plays them once.", min=1, max=8),
    Spec("sid_songlengths", "str", "", "Chiptunes", "HVSC Songlengths.md5",
         "Path to the HVSC song length database for exact SID durations."),
    Spec("soundfont", "str", "", "Chiptunes", "MIDI soundfont (.sf2)",
         "Leave empty for the built-in General MIDI soundfont."),
    # appearance
    Spec("default_scheme", "str", "catppuccin-mocha", "Appearance", "Default color scheme"),
    Spec("default_mode", "choice", "system", "Appearance", "Default light/dark",
         choices=["system", "light", "dark"]),
    Spec("genre_skins", "bool", True, "Appearance", "Genre skins",
         "Restyle the whole app after the genre of what's playing."),
    Spec("skin_map", "json", {}, "Appearance", "Extra genre → skin rules",
         "Tag → skin pairs that win over the built-in rules, e.g. {\"melodeath\": \"death-metal\"}."),
    # podcasts & radio
    Spec("podcast_refresh_hours", "int", 3, "Podcasts & radio", "Refresh feeds every (hours)", min=1, max=72),
    Spec("podcast_keep_days", "int", 30, "Podcasts & radio", "Keep downloaded episodes (days)",
         "0 keeps them forever.", min=0, max=3650),
    Spec("radio_country", "str", "", "Podcasts & radio", "Radio home country",
         "Two-letter code for the \"popular near you\" list, e.g. SE."),
    # uploads
    Spec("upload_musicbrainz", "bool", True, "Uploads", "Match with MusicBrainz"),
    Spec("upload_fetch_art", "bool", True, "Uploads", "Find cover art"),
    Spec("upload_genre_folders", "bool", True, "Uploads", "File into genre folders",
         "Genre/Artist/Artist - Year - Album, like the rest of the library."),
    # admin mode's edit window
    Spec("discogs_token", "secret", "", "Library", "Discogs personal access token",
         "Album and artist matches and pictures from Discogs when editing in admin mode. Free: sign in at "
         "https://www.discogs.com/settings/developers and press \"Generate new token\"."),
    Spec("fanarttv_api_key", "secret", "", "Library", "fanart.tv API key",
         "Artist pictures and album covers from fanart.tv when editing in admin mode, found by the "
         "MusicBrainz ids in your tags. Free from https://fanart.tv/get-an-api-key/ (a project key or "
         "your personal key)."),
    Spec("brave_api_key", "secret", "", "Library", "Brave Search API key",
         "For the web image search when changing a cover in admin mode. Brave's Search plan at "
         "https://brave.com/search/api/ gives $5 of searches a month (about 1,000) but asks for a card."),
    Spec("modarchive_api_key", "secret", "", "Online archives", "The Mod Archive API key",
         "Lets VGM → Online archives browse modarchive.org. Keys are personal: ask for one in the API "
         "section of The Mod Archive's forum (https://modarchive.org/forums), then paste it here."),
    # spotify
    Spec("spotify_client_id", "str", "", "Spotify", "Client ID",
         "From developer.spotify.com → your app. Redirect URI: <public URL>/api/spotify/callback"),
]

_BY_KEY = {s.key: s for s in SCHEMA}
_cache: dict[str, object] = {}
_lock = RLock()


def get(key: str):
    with _lock:
        if key in _cache:
            return _cache[key]
    spec = _BY_KEY[key]
    with db.session() as s:
        row = s.get(Setting, key)
        value = row.value if row is not None else spec.default
    with _lock:
        _cache[key] = value
    return value


def set_many(values: dict):
    with db.session() as s:
        for key, value in values.items():
            spec = _BY_KEY.get(key)
            if spec is None:
                raise KeyError(key)
            value = coerce(spec, value)
            row = s.get(Setting, key)
            if row is None:
                s.add(Setting(key=key, value=value))
            else:
                row.value = value
    with _lock:
        _cache.clear()


def coerce(spec: Spec, value):
    if spec.type == "bool":
        return bool(value)
    if spec.type == "int":
        v = int(value)
    elif spec.type == "float":
        v = float(value)
    elif spec.type == "choice":
        if value not in spec.choices:
            raise ValueError(f"{spec.key}: {value!r} is not one of {spec.choices}")
        return value
    elif spec.type == "json":
        if not isinstance(value, (dict, list)):
            raise ValueError(f"{spec.key}: expected JSON object")
        return value
    else:
        return "" if value is None else str(value)
    if spec.min is not None and v < spec.min or spec.max is not None and v > spec.max:
        raise ValueError(f"{spec.key}: {v} is outside {spec.min}..{spec.max}")
    return v


def public_schema(include_secrets=False):
    out = []
    for spec in SCHEMA:
        value = get(spec.key)
        if spec.type == "secret" and not include_secrets:
            value = "••••••" if value else ""
        out.append({**spec.__dict__, "value": value})
    return out
