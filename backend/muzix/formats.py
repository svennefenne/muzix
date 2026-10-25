"""Every file type Muzix knows: how it is read and how it reaches the browser.

family:
  native    browsers play the file as-is (served with HTTP range support)
  decode    ffmpeg decodes the file (WavPack, APE, WMA, AIFF, ALAC...)
  module    tracker modules, rendered with libopenmpt (through ffmpeg)
  gme       console chip music, rendered with Game_Music_Emu (through ffmpeg)
  sid       Commodore 64, rendered with sidplayfp
  midi      General MIDI, rendered with FluidSynth
  ym        Atari ST YM register dumps, rendered with ymtool (StSound)
  furnace   FamiTracker/Furnace songs, rendered with Furnace's command line
  zxtune    ZX Spectrum trackers (Pro Tracker, Sound Tracker, ASC, TurboFM...) and the Amiga/PC
            formats libopenmpt doesn't play (AHX, HivelyTracker, Future Composer...), rendered with zxtune123

Rendered families are turned into a cached FLAC file once and then served
like any other file, so seeking works everywhere.
"""

NATIVE = {"mp3", "flac", "ogg", "oga", "opus", "m4a", "m4b", "aac", "wav", "webm", "mp4"}
DECODE = {"wv", "ape", "wma", "aif", "aiff", "aifc", "tta", "mpc", "dsf", "dff", "ac3", "mka", "spx"}
MODULE = {
    "mod", "it", "s3m", "xm", "mt2", "mptm", "669", "amf", "ams", "c67", "dbm", "digi", "dmf",
    "dsm", "dsym", "dtm", "far", "fmt", "gdm", "ice", "imf", "j2b", "m15", "mdl", "med", "mms",
    "mo3", "mtm", "mus", "nst", "okt", "plm", "psm", "pt36", "ptm", "sfx", "sfx2", "st26", "stk",
    "stm", "stp", "symmod", "ult", "umx", "wow", "xmf", "gt2", "gtk", "puma", "rtm", "cba", "etx",
}
GME = {"nsf", "nsfe", "gbs", "spc", "vgm", "vgz", "gym", "hes", "kss", "ay", "sap"}
SID = {"sid", "psid", "rsid"}
MIDI = {"mid", "midi", "kar", "rmi", "smf"}
YM = {"ym"}
FURNACE = {"ftm", "0cc", "dnm", "fur"}
# libgme plays .ay already. "zx" marks a downloaded tune whose own name doesn't say what it is
# (ZXArt keeps names like "song.$m" and "tune.c"); zxtune123 goes by the contents anyway.
ZX = {
    "pt3", "pt2", "pt1", "stc", "st1", "st3", "stp", "asc", "as0", "psc", "sqt", "ftc", "gtr", "chi",
    "dmm", "dst", "et1", "pdt", "sqd", "tfc", "tfd", "tfe", "ts", "psg", "vtx", "cop", "etc", "mtc",
    "mt3", "zx",
}
# Amiga (and a few PC/Atari ST) trackers zxtune123 plays. "ftmn" and "kris" are what sniff() calls
# Face The Music and ChipTracker files, which come as .ftm (FamiTracker's) and .mod.
AMIGA = {
    "ahx", "thx", "hvl", "fc", "fc13", "fc14", "smod", "gmc", "ims", "emod", "ftmn", "kris", "667",
    "tcb", "fnk", "liq", "v2m",
}
ZXTUNE = ZX | AMIGA
# Amiga style "ahx.songname" names
PREFIXES = MODULE | {"ahx", "thx", "hvl", "fc", "fc13", "fc14", "smod", "gmc", "ims", "emod", "ftm", "667", "tcb"}

FAMILIES = {
    "native": NATIVE, "decode": DECODE, "module": MODULE, "gme": GME,
    "sid": SID, "midi": MIDI, "ym": YM, "furnace": FURNACE, "zxtune": ZXTUNE,
}
_BY_EXT = {ext: fam for fam, exts in FAMILIES.items() for ext in exts}
CHIP_FAMILIES = {"module", "gme", "sid", "midi", "ym", "furnace", "zxtune"}
RENDERED = CHIP_FAMILIES

# a friendly system name per chip format, for the VGM pages
SYSTEMS = {
    "nsf": "NES / Famicom", "nsfe": "NES / Famicom", "ftm": "NES / Famicom", "0cc": "NES / Famicom",
    "dnm": "NES / Famicom", "gbs": "Game Boy", "spc": "Super Nintendo", "vgm": "Sega / arcade",
    "vgz": "Sega / arcade", "gym": "Sega Mega Drive", "hes": "PC Engine", "kss": "MSX",
    "ay": "ZX Spectrum / CPC", "sap": "Atari 8-bit", "sid": "Commodore 64", "psid": "Commodore 64",
    "rsid": "Commodore 64", "ym": "Atari ST", "mid": "MIDI", "midi": "MIDI", "kar": "MIDI",
    "rmi": "MIDI", "smf": "MIDI", "fur": "Furnace",
    **{ext: "ZX Spectrum" for ext in ZX},
    **{ext: "Amiga / PC tracker" for ext in AMIGA}, "tcb": "Atari ST",
    "fnk": "PC tracker", "liq": "PC tracker", "667": "PC tracker", "v2m": "PC tracker",
}


def ext_of(path: str) -> str:
    base = path.rsplit("/", 1)[-1].lower()
    if "." not in base.lstrip("."):
        return ""
    ext = base.rsplit(".", 1)[1]
    if ext in _BY_EXT:
        return ext
    pre = base.split(".", 1)[0]   # Amiga style "mod.songname"
    return pre if pre in PREFIXES else ext


def sniff(path: str, ext: str) -> str:
    """The format of a file whose extension two formats share, from its first bytes: Face The
    Music (Amiga) and FamiTracker both use .ftm, and ChipTracker songs are .mod files."""
    if ext not in ("ftm", "mod"):
        return ext
    try:
        with open(path, "rb") as f:
            head = f.read(956)
    except OSError:
        return ext
    if ext == "ftm" and head[:4] == b"FTMN":
        return "ftmn"
    if ext == "mod" and head[952:956] == b"KRIS":
        return "kris"
    return ext


def family(path_or_ext: str) -> str | None:
    ext = path_or_ext if "." not in path_or_ext and "/" not in path_or_ext else ext_of(path_or_ext)
    return _BY_EXT.get(ext)


def is_audio(path: str) -> bool:
    return family(path) is not None


def system_for(ext: str) -> str:
    if ext in SYSTEMS:
        return SYSTEMS[ext]
    if ext in MODULE:
        return "Amiga / PC tracker" if ext in ("mod", "med", "okt", "dmu") else "PC tracker"
    return ""


def browser_mime(ext: str) -> str:
    return {
        "mp3": "audio/mpeg", "flac": "audio/flac", "ogg": "audio/ogg", "oga": "audio/ogg",
        "opus": "audio/ogg", "m4a": "audio/mp4", "m4b": "audio/mp4", "mp4": "audio/mp4",
        "aac": "audio/aac", "wav": "audio/wav", "webm": "audio/webm",
    }.get(ext, "application/octet-stream")
