"""libopenmpt through ctypes: tracker module info and rendering (MOD/XM/IT/S3M/MT2...)."""

import ctypes
import ctypes.util
import threading
import wave
from dataclasses import dataclass, field

_lib = None
_lock = threading.Lock()


def lib():
    global _lib
    with _lock:
        if _lib is None:
            name = ctypes.util.find_library("openmpt") or "libopenmpt.so.0"
            try:
                L = ctypes.CDLL(name)
            except OSError:
                _lib = False
                return None
            L.openmpt_module_create_from_memory2.argtypes = [
                ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                ctypes.c_void_p, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_char_p), ctypes.c_void_p]
            L.openmpt_module_create_from_memory2.restype = ctypes.c_void_p
            L.openmpt_module_destroy.argtypes = [ctypes.c_void_p]
            L.openmpt_module_get_duration_seconds.argtypes = [ctypes.c_void_p]
            L.openmpt_module_get_duration_seconds.restype = ctypes.c_double
            L.openmpt_module_get_num_subsongs.argtypes = [ctypes.c_void_p]
            L.openmpt_module_select_subsong.argtypes = [ctypes.c_void_p, ctypes.c_int]
            L.openmpt_module_set_repeat_count.argtypes = [ctypes.c_void_p, ctypes.c_int]
            L.openmpt_module_get_metadata.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
            L.openmpt_module_get_metadata.restype = ctypes.c_void_p
            L.openmpt_free_string.argtypes = [ctypes.c_void_p]
            L.openmpt_module_read_interleaved_stereo.argtypes = [
                ctypes.c_void_p, ctypes.c_int32, ctypes.c_size_t, ctypes.POINTER(ctypes.c_int16)]
            L.openmpt_module_read_interleaved_stereo.restype = ctypes.c_size_t
            _lib = L
        return _lib or None


def available() -> bool:
    return lib() is not None


@dataclass
class ModuleInfo:
    title: str = ""
    artist: str = ""
    tracker: str = ""
    message: str = ""
    durations: list[float] = field(default_factory=list)   # one per subsong


class _Module:
    def __init__(self, path: str):
        self.L = lib()
        if self.L is None:
            raise RuntimeError("libopenmpt is not installed")
        with open(path, "rb") as f:
            self._data = f.read()
        err = ctypes.c_int(0)
        silent = ctypes.cast(self.L.openmpt_log_func_silent, ctypes.c_void_p)
        self.m = self.L.openmpt_module_create_from_memory2(
            self._data, len(self._data), silent, None, None, None, ctypes.byref(err), None, None)
        if not self.m:
            raise RuntimeError(f"libopenmpt could not load the module (error {err.value})")

    def meta(self, key: str) -> str:
        p = self.L.openmpt_module_get_metadata(self.m, key.encode())
        if not p:
            return ""
        try:
            return ctypes.string_at(p).decode("utf-8", "replace").strip()
        finally:
            self.L.openmpt_free_string(p)

    def close(self):
        if self.m:
            self.L.openmpt_module_destroy(self.m)
            self.m = None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def info(path: str) -> ModuleInfo:
    with _Module(path) as mod:
        L = mod.L
        n = max(1, L.openmpt_module_get_num_subsongs(mod.m))
        durations = []
        for i in range(n):
            if n > 1:
                L.openmpt_module_select_subsong(mod.m, i)
            durations.append(float(L.openmpt_module_get_duration_seconds(mod.m)))
        return ModuleInfo(mod.meta("title"), mod.meta("artist"), mod.meta("tracker"),
                          mod.meta("message"), durations)


def render_wav(path: str, subsong: int, repeats: int, max_seconds: float, out_path: str, rate: int = 44100) -> float:
    """Render to a 16-bit stereo WAV. repeats: times the song plays. Returns seconds written."""
    with _Module(path) as mod:
        L = mod.L
        if subsong >= 0:
            L.openmpt_module_select_subsong(mod.m, subsong)
        L.openmpt_module_set_repeat_count(mod.m, max(0, repeats - 1))
        frames_max = int(max_seconds * rate)
        chunk = 4096
        buf = (ctypes.c_int16 * (chunk * 2))()
        written = 0
        with wave.open(out_path, "wb") as w:
            w.setnchannels(2)
            w.setsampwidth(2)
            w.setframerate(rate)
            while written < frames_max:
                n = L.openmpt_module_read_interleaved_stereo(mod.m, rate, min(chunk, frames_max - written), buf)
                if n == 0:
                    break
                w.writeframes(bytes(memoryview(buf).cast("B")[:n * 4]))
                written += n
        return written / rate
