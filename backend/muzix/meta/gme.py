"""Game_Music_Emu (libgme) through ctypes: track info with loop points, and rendering.

Used for NSF/NSFe, GBS, SPC, VGM/VGZ, GYM, HES, KSS, AY and SAP.
"""

import ctypes
import ctypes.util
import threading
import wave
from dataclasses import dataclass

_lib = None
_lib_lock = threading.Lock()


class _Info(ctypes.Structure):
    _fields_ = ([("length", ctypes.c_int), ("intro_length", ctypes.c_int),
                 ("loop_length", ctypes.c_int), ("play_length", ctypes.c_int),
                 ("fade_length", ctypes.c_int)]
                + [(f"i{n}", ctypes.c_int) for n in range(5, 16)]
                + [(name, ctypes.c_char_p) for name in
                   ("system", "game", "song", "author", "copyright", "comment", "dumper")]
                + [(f"s{n}", ctypes.c_char_p) for n in range(7, 16)])


def lib():
    global _lib
    with _lib_lock:
        if _lib is None:
            name = ctypes.util.find_library("gme") or "libgme.so.0"
            try:
                L = ctypes.CDLL(name)
            except OSError:
                _lib = False
                return None
            L.gme_open_file.argtypes = [ctypes.c_char_p, ctypes.POINTER(ctypes.c_void_p), ctypes.c_int]
            L.gme_open_file.restype = ctypes.c_char_p
            L.gme_track_count.argtypes = [ctypes.c_void_p]
            L.gme_track_info.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.POINTER(_Info)), ctypes.c_int]
            L.gme_track_info.restype = ctypes.c_char_p
            L.gme_free_info.argtypes = [ctypes.POINTER(_Info)]
            L.gme_start_track.argtypes = [ctypes.c_void_p, ctypes.c_int]
            L.gme_start_track.restype = ctypes.c_char_p
            L.gme_play.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(ctypes.c_short)]
            L.gme_play.restype = ctypes.c_char_p
            L.gme_ignore_silence.argtypes = [ctypes.c_void_p, ctypes.c_int]
            L.gme_delete.argtypes = [ctypes.c_void_p]
            if hasattr(L, "gme_set_autoload_playback_limit"):
                L.gme_set_autoload_playback_limit.argtypes = [ctypes.c_void_p, ctypes.c_int]
            _lib = L
        return _lib or None


def available() -> bool:
    return lib() is not None


@dataclass
class TrackTimes:
    length: float | None      # the file's own play length (fixed), if any
    intro: float | None       # up to the loop
    loop: float | None        # the looping part
    fade: float | None
    title: str = ""
    game: str = ""
    author: str = ""
    system: str = ""
    copyright: str = ""


def _sec(ms: int) -> float | None:
    return ms / 1000 if ms and ms > 0 else None


def _open(path: str, rate: int):
    L = lib()
    if L is None:
        raise RuntimeError("libgme is not installed")
    emu = ctypes.c_void_p()
    err = L.gme_open_file(path.encode(), ctypes.byref(emu), rate)
    if err:
        raise RuntimeError(err.decode(errors="replace"))
    return L, emu


def track_times(path: str) -> list[TrackTimes]:
    L, emu = _open(path, 44100)
    try:
        out = []
        for i in range(L.gme_track_count(emu)):
            p = ctypes.POINTER(_Info)()
            if L.gme_track_info(emu, ctypes.byref(p), i):
                out.append(TrackTimes(None, None, None, None))
                continue
            info = p.contents
            d = lambda b: (b or b"").decode("utf-8", "replace").strip()
            out.append(TrackTimes(_sec(info.length), _sec(info.intro_length), _sec(info.loop_length),
                                  _sec(info.fade_length) if info.fade_length >= 0 else None,
                                  d(info.song), d(info.game), d(info.author), d(info.system), d(info.copyright)))
            L.gme_free_info(p)
        return out
    finally:
        L.gme_delete(emu)


def render_wav(path: str, track: int, seconds: float, out_path: str, rate: int = 44100):
    """Play `track` for `seconds` into a 16-bit stereo WAV (no fade; ffmpeg adds it)."""
    L, emu = _open(path, rate)
    try:
        if hasattr(L, "gme_set_autoload_playback_limit"):
            L.gme_set_autoload_playback_limit(emu, 0)
        L.gme_ignore_silence(emu, 1)
        err = L.gme_start_track(emu, track)
        if err:
            raise RuntimeError(err.decode(errors="replace"))
        total = int(seconds * rate) * 2           # interleaved stereo samples
        chunk = 8192
        buf = (ctypes.c_short * chunk)()
        with wave.open(out_path, "wb") as w:
            w.setnchannels(2)
            w.setsampwidth(2)
            w.setframerate(rate)
            done = 0
            while done < total:
                n = min(chunk, total - done)
                n -= n % 2
                err = L.gme_play(emu, n, buf)
                if err:
                    raise RuntimeError(err.decode(errors="replace"))
                w.writeframes(bytes(memoryview(buf).cast("B")[:n * 2]))
                done += n
    finally:
        L.gme_delete(emu)
