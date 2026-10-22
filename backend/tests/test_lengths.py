from muzix import settings
from muzix.lengths import play_plan


def setup_function():
    settings.set_many({"chip_loop_mode": "loops", "chip_loops": 2, "chip_length": 180, "chip_fade": 8,
                       "chip_max_length": 900, "module_repeats": 1})


def test_loops_mode_uses_loop_points():
    # intro once, the loop twice, then the fade
    assert play_plan("gme", {"intro": 30, "loop": 60}) == (30 + 120 + 8, 8)


def test_fixed_lengths_and_defaults():
    assert play_plan("gme", {"length": 61, "fade": 2}) == (63, 2)       # NSFe / SPC own length and fade
    assert play_plan("gme", {}) == (180, 8)                             # NSF/GBS without info
    assert play_plan("sid", {}) == (180, 8)
    assert play_plan("gme", {"natural": 89.6}) == (89.6, 0.0)           # VGM without a loop ends by itself


def test_time_mode_overrides_everything():
    settings.set_many({"chip_loop_mode": "time", "chip_length": 120})
    assert play_plan("gme", {"intro": 30, "loop": 60}) == (120, 8)


def test_cap_and_modules():
    settings.set_many({"chip_loops": 16, "chip_max_length": 300})
    assert play_plan("gme", {"intro": 0, "loop": 100})[0] == 300
    assert play_plan("module", {"natural": 150}) == (150, 0.0)          # modules play once by default
    settings.set_many({"module_repeats": 2})
    assert play_plan("module", {"natural": 150}) == (300, 8)
