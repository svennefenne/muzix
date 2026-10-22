"""Build frontend/src/theme/palettes.json from the claude-desktop-extra palette previews.

    git clone --depth 1 https://github.com/patrickjaja/claude-desktop-extra /tmp/cde
    python scripts/import_palettes.py /tmp/cde/themes

The previews (themes/palettes/*.svg) label every colour role of each palette's
dark and light variant, which is all Muzix needs.
"""

import json
import re
import sys
from pathlib import Path

BUILTIN = ["sweet", "nord", "catppuccin-mocha", "catppuccin-macchiato", "catppuccin-frappe", "catppuccin-latte"]
GAMING = ["mario", "playstation", "gameboy", "final-fantasy", "zelda", "warcraft", "dragonball"]
ROLES = {"elevated surface": "surface", "text": "text", "primary": "primary", "secondary": "secondary",
         "error": "error", "warning": "warning", "success": "success", "border": "border"}


def parse(svg: str) -> dict:
    name = re.search(r"<title>(.+?) palette \(dark and light\)</title>", svg).group(1)
    backgrounds = re.findall(r'<rect[^>]+fill="(#[0-9a-fA-F]{6})"', svg)
    roles = re.findall(r"<title>([a-z ]+): (#[0-9a-fA-F]{6})</title>", svg)
    half = len(roles) // 2
    modes = {}
    for mode, bg, chunk in (("dark", backgrounds[0], roles[:half]), ("light", backgrounds[1], roles[half:])):
        modes[mode] = {"bg": bg.lower(), **{ROLES[r]: c.lower() for r, c in chunk if r in ROLES}}
    return {"name": name, **modes}


def main(themes_dir: str):
    out = []
    for svg in sorted(Path(themes_dir, "palettes").glob("*.svg")):
        slug = svg.stem
        p = parse(svg.read_text())
        if p["name"] == slug:
            p["name"] = slug.replace("-", " ").title()
        category = "builtin" if slug in BUILTIN else "gaming" if slug in GAMING else "community"
        out.append({"slug": slug, "category": category, **p})
    order = {s: i for i, s in enumerate(BUILTIN + GAMING)}
    out.sort(key=lambda p: (order.get(p["slug"], 999), p["name"].lower()))
    dest = Path(__file__).resolve().parent.parent / "frontend/src/theme/palettes.json"
    dest.write_text(json.dumps(out, indent=1) + "\n")
    print(f"{len(out)} palettes -> {dest}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "/tmp/cde-themes/themes")
