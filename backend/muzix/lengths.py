"""How long a chip or tracker song plays, from the admin's loop settings.

Scanning stores what the file itself says in Track.extra:
  intro, loop   seconds up to the loop and of the looping part (if known)
  length        a fixed play time the file specifies (NSFe/SPC/SID database)
  fade          the file's own fade-out, if any
  natural       a finite length for songs that end by themselves (modules, MIDI,
                VGM without a loop)

play_plan() turns that into (seconds to render, fade seconds). The same plan
gives the duration the player shows and the length of the rendered file.
"""

from . import formats, settings


def play_plan(fam: str, extra: dict | None, duration: float = 0) -> tuple[float, float]:
    extra = extra or {}
    mode = settings.get("chip_loop_mode")
    loops = int(settings.get("chip_loops"))
    fixed_time = float(settings.get("chip_length"))
    fade = float(settings.get("chip_fade"))
    cap = float(settings.get("chip_max_length"))

    if fam == "midi":
        return (extra.get("natural") or duration or fixed_time), 0.0
    if fam in ("module", "zxtune"):      # ZX Spectrum and AHX tunes are tracker songs too
        one = extra.get("natural") or duration
        repeats = int(settings.get("module_repeats"))
        if not one:
            return 0.0, 0.0                       # unknown: libopenmpt stops at the end
        if repeats <= 1:
            return one, 0.0
        return min(one * repeats + fade, cap), fade
    if fam == "furnace":
        # Furnace plays the loop itself (-loops); the length is learned on first render
        if mode == "time":
            return fixed_time, fade
        return min(extra.get("rendered") or fixed_time, cap), fade if extra.get("rendered") else 0.0

    if fam == "uade":
        # UADE knows when a song ends (its player says so); one that doesn't is cut at the fixed time
        if extra.get("natural"):
            return extra["natural"], 0.0
        return min(fixed_time, cap), fade

    intro, loop = extra.get("intro"), extra.get("loop")
    own_fade = extra.get("fade")
    if mode == "time":
        return fixed_time, fade
    if loop:
        total = (intro or 0) + loop * loops + fade
        return min(total, cap), fade
    if extra.get("length"):
        f = own_fade if own_fade is not None else fade
        return min(extra["length"] + f, cap), f
    if extra.get("natural"):
        return extra["natural"], 0.0
    return fixed_time, fade


def display_duration(t) -> float:
    """Duration to show for a track row."""
    fam = formats.family(t.format)
    if fam not in formats.RENDERED:
        return t.duration
    total, _ = play_plan(fam, t.extra, t.duration)
    return total or t.duration
