"""Turning any supported file into something a browser can play.

* chip/tracker/MIDI files are rendered once to a cached FLAC (fast: a few
  seconds of CPU per song), then served with range requests like a normal file
* everything else a browser can't decode (WavPack, APE, WMA, hi-res above the
  configured limit) is transcoded on the fly by ffmpeg, starting at any offset
"""

import hashlib
import logging
import os
import shutil
import subprocess
import tempfile
import threading
import time

from . import env, formats, settings

log = logging.getLogger("muzix.render")
_locks: dict[str, threading.Lock] = {}
_guard = threading.Lock()
RENDER_TIMEOUT = 600


class RenderError(Exception):
    pass


def have(tool: str) -> bool:
    return shutil.which(tool) is not None


def _lock(key):
    with _guard:
        return _locks.setdefault(key, threading.Lock())


def cache_path(path: str, subsong: int, plan: tuple[float, float], extra_key: str = "") -> str:
    st = os.stat(path)
    key = hashlib.sha1(f"{path}|{subsong}|{st.st_size}|{st.st_mtime}|{plan[0]:.2f}|{plan[1]:.2f}|"
                       f"{extra_key}".encode()).hexdigest()
    d = env.CACHE_DIR / "render" / key[:2]
    d.mkdir(parents=True, exist_ok=True)
    return str(d / f"{key}.flac")


def render(path: str, fmt: str, subsong: int, duration: float, extra: dict | None) -> tuple[str, float]:
    """(path of a cached FLAC rendition, its length in seconds), rendering if needed."""
    from .lengths import play_plan
    from .meta import gme, openmpt

    fam = formats.family(fmt)
    total, fade = play_plan(fam, extra, duration)
    loops = int(settings.get("chip_loops"))
    mode = settings.get("chip_loop_mode")
    extra_key = {"midi": settings.get("soundfont"), "furnace": f"{mode}{loops}",
                 "module": settings.get("module_repeats")}.get(fam, "")
    # Furnace's length is only known after rendering; key its cache on the loop settings alone
    out = cache_path(path, subsong, (0.0, 0.0) if fam == "furnace" else (total, fade), str(extra_key))
    if os.path.exists(out):
        return out, _probe_seconds(out)
    with _lock(out):
        if os.path.exists(out):
            return out, _probe_seconds(out)
        with tempfile.TemporaryDirectory(dir=env.CACHE_DIR) as tmp:
            wav = os.path.join(tmp, "render.wav")
            cap = float(settings.get("chip_max_length"))
            if fam == "module":
                openmpt.render_wav(path, subsong, int(settings.get("module_repeats")),
                                   total or cap, wav)
            elif fam == "gme":
                gme.render_wav(path, max(subsong, 0), total, wav)
            elif fam == "sid":
                _run(["sidplayfp", "-q", f"-w{wav}", f"-o{max(subsong, 0) + 1}",
                      f"-t{int(total) // 60}:{int(total) % 60:02d}", path])
            elif fam == "midi":
                font = settings.get("soundfont") or env.SOUNDFONT
                _run(["fluidsynth", "-ni", "-q", "-g", "0.6", "-r", "44100", "-F", wav, font, path])
            elif fam == "ym":
                _run(["ymtool", "render", path, wav, f"{total:.2f}"])
            elif fam == "furnace":
                # Furnace's -loops counts repeats after the first pass; ours counts passes
                _furnace(path, subsong, loops - 1 if mode == "loops" else 50, wav)
                if mode == "loops":
                    total = min(_probe_seconds(wav), cap)   # Furnace stops at the loop end; fade the tail
            else:
                raise RenderError(f"{fmt} is not a rendered format")
            cmd = ["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", wav]
            if total:
                cmd += ["-t", f"{total:.3f}"]
                if fade:
                    cmd += ["-af", f"afade=t=out:st={max(0.0, total - fade):.3f}:d={fade:.3f}"]
            part = out + ".part"
            cmd += ["-ar", "44100", "-ac", "2", "-c:a", "flac", "-f", "flac", part]
            _run(cmd)
            os.replace(part, out)
    return out, _probe_seconds(out)


# ---------------------------------------------------------------- progressive rendering
# sidplayfp renders at ~18x real time (10 s for a 3 minute tune). Instead of
# waiting, follow its WAV file as it grows, encode on the fly into the cache
# file, and let the response read that file while it is being written.

PROGRESSIVE = {"sid"}
_running: dict[str, threading.Event] = {}


def plan_for(path, fmt, subsong, duration, extra):
    from .lengths import play_plan
    fam = formats.family(fmt)
    total, fade = play_plan(fam, extra, duration)
    out = cache_path(path, subsong, (total, fade), "")
    return out, total, fade


def start_progressive(path: str, fmt: str, subsong: int, duration: float, extra: dict | None):
    """(cache file, done event): starts a background render unless one is running."""
    out, total, fade = plan_for(path, fmt, subsong, duration, extra)
    with _guard:
        ev = _running.get(out)
        if ev is not None or os.path.exists(out):
            return out, ev
        ev = threading.Event()
        _running[out] = ev
    threading.Thread(target=_sid_progressive, args=(path, subsong, total, fade, out, ev), daemon=True).start()
    return out, ev


def _sid_progressive(path, subsong, total, fade, out, done):
    part = out + ".part"
    try:
        with tempfile.TemporaryDirectory(dir=env.CACHE_DIR) as tmp:
            wav = os.path.join(tmp, "r.wav")
            p1 = subprocess.Popen(["sidplayfp", "-q", f"-w{wav}", f"-o{max(subsong, 0) + 1}",
                                   f"-t{int(total) // 60}:{int(total) % 60:02d}", path],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            deadline = time.monotonic() + 20
            while (not os.path.exists(wav) or os.path.getsize(wav) < 44) and p1.poll() is None:
                if time.monotonic() > deadline:
                    raise RenderError("sidplayfp didn't start")
                time.sleep(0.02)
            with open(wav, "rb") as f:
                hdr = f.read(44)
                channels = int.from_bytes(hdr[22:24], "little") or 1
                rate = int.from_bytes(hdr[24:28], "little") or 44100
                cmd = ["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "s16le", "-ar", str(rate),
                       "-ac", str(channels), "-i", "pipe:0", "-t", f"{total:.3f}"]
                if fade:
                    cmd += ["-af", f"afade=t=out:st={max(0.0, total - fade):.3f}:d={fade:.3f}"]
                cmd += ["-ar", "44100", "-ac", "2", "-c:a", "flac", "-f", "flac", part]
                ff = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
                try:
                    while True:
                        chunk = f.read(256 * 1024)
                        if chunk:
                            ff.stdin.write(chunk)
                        elif p1.poll() is not None:
                            rest = f.read()
                            if rest:
                                ff.stdin.write(rest)
                            break
                        else:
                            time.sleep(0.02)
                finally:
                    ff.stdin.close()
                    ff.wait()
            if p1.wait() == 0 and ff.returncode == 0:
                os.replace(part, out)
    except Exception:
        log.exception("progressive render of %s failed", path)
    finally:
        if os.path.exists(part):
            try:
                os.remove(part)
            except OSError:
                pass
        with _guard:
            _running.pop(out, None)
        done.set()


def follow(out: str, done: threading.Event):
    """Yield a cache file's bytes while a background render is still writing it."""
    part = out + ".part"
    deadline = time.monotonic() + 30
    while not os.path.exists(part) and not os.path.exists(out):
        if done.is_set() and not os.path.exists(out):
            raise RenderError("rendering failed")
        if time.monotonic() > deadline:
            raise RenderError("rendering didn't start")
        time.sleep(0.02)
    try:
        f = open(part, "rb")
    except FileNotFoundError:
        f = open(out, "rb")   # finished in the meantime
    with f:
        idle = time.monotonic()
        while True:
            chunk = f.read(64 * 1024)
            if chunk:
                idle = time.monotonic()
                yield chunk
            elif done.is_set():
                rest = f.read()
                if rest:
                    yield rest
                return
            elif time.monotonic() - idle > 60:
                return
            else:
                time.sleep(0.03)


def _probe_seconds(path: str) -> float:
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                             capture_output=True, text=True, timeout=30).stdout.strip()
        return float(out) if out and out != "N/A" else 0.0
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return 0.0


def _furnace(path, subsong, loops, wav):
    cmd = ["furnace", "-console", "-nostatus", "-nocontrols", "-loops", str(loops), "-output", wav]
    if subsong >= 0:
        cmd += ["-subsong", str(subsong)]
    _run(cmd + [path], env={**os.environ, "SDL_AUDIODRIVER": "dummy", "SDL_VIDEODRIVER": "dummy"})


def _run(cmd, env=None):
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=RENDER_TIMEOUT, env=env)
    except FileNotFoundError:
        raise RenderError(f"{cmd[0]} is not installed")
    except subprocess.TimeoutExpired:
        raise RenderError(f"{cmd[0]} took too long")
    if r.returncode != 0:
        raise RenderError(f"{cmd[0]} failed: {r.stderr.decode(errors='replace')[-400:]}")


# ---------------------------------------------------------------- on-the-fly transcoding

def transcode_args(path: str, offset: float, target: str, out_rate: int, bit_depth: int,
                   bitrate: int) -> tuple[list, str]:
    """ffmpeg command writing to stdout, and the response MIME type.

    out_rate: resample to this rate (0 keeps the source rate)."""
    cmd = ["ffmpeg", "-nostdin", "-v", "error"]
    if offset > 0:
        cmd += ["-ss", f"{offset:.2f}"]
    cmd += ["-i", path, "-map", "0:a:0", "-vn", "-sn", "-dn"]
    if target == "flac":
        if out_rate:
            cmd += ["-af", f"aresample=resampler=soxr:osr={out_rate}"]
        cmd += ["-sample_fmt", "s32" if bit_depth > 16 else "s16",
                "-c:a", "flac", "-compression_level", "2", "-f", "flac", "pipe:1"]
        return cmd, "audio/flac"
    if target == "opus":
        cmd += ["-ar", "48000", "-c:a", "libopus", "-b:a", f"{bitrate}k", "-vbr", "on", "-f", "ogg", "pipe:1"]
        return cmd, "audio/ogg"
    cmd += ["-ar", "44100", "-c:a", "libmp3lame", "-b:a", f"{bitrate}k", "-f", "mp3", "pipe:1"]
    return cmd, "audio/mpeg"


# what Google's Cast speakers (Chromecast Audio, Nest and Home speakers) play as they are
CAST_NATIVE = {"mp3", "flac", "ogg", "oga", "opus", "m4a", "m4b", "aac", "wav"}
CAST_MAX_RATE = 96000   # FLAC up to 96 kHz / 24-bit


def needs_transcode(ext: str, codec: str, sample_rate: int, quality: str) -> bool:
    fam = formats.family(ext)
    if fam in formats.RENDERED:
        return False
    if fam == "decode" or codec == "alac":
        return True
    if quality == "cast":
        return ext not in CAST_NATIVE or bool(sample_rate and sample_rate > CAST_MAX_RATE)
    if quality in ("high", "low") and ext not in ("mp3", "ogg", "opus", "m4a", "aac", "m4b"):
        return True
    return bool(sample_rate and sample_rate > int(settings.get("max_sample_rate")))
