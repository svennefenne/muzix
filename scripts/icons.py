"""Muzix's app icons, drawn from one set of measures: the cassette of six stripes in Hooden's colours
(cream, amber, brick, green, blue, plum, the last lightened to show on the plate), notched on top so it
reads as an M, with the tape opening below and a deck across the middle (a dark panel with round ends,
a reel with a toothed amber hub in each end and the tape window between them), on Hooden's near-black
plate with its ember glow. Run from the repo's root:

    python3 scripts/icons.py

It writes the favicon (with its own drawings for 32 px and 16 px, so every edge lands on a pixel), the
web app's icons, Muzix Desktop's icon in each size and its .ico, Android's adaptive and themed launcher
icon and its notification icon, and Unraid's Docker icon. It needs resvg, and Pillow for the .ico."""

import io
import math
import os
import subprocess
import tempfile

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLATE, GLOW = "#070b10", "#d65a2b"
STRIPES = ["#efe3c8", "#e2a634", "#cc4a30", "#4f8f50", "#2f74a0", "#5a5066"]
PANEL, RIBS, HUB = "#171b23", "#20252f", "#e2a634"
S = 512


# ------------------------------------------------------------------ the measures (on a 512 grid)

def _measures():
    """The old cassette (body 4..28 × 7..26 on a 32 grid) scaled by 1.23 about (16, 16.5), striped six times."""
    k, u = 1.23, S / 32
    sx = lambda x: (16 + (x - 16) * k) * u
    sy = lambda y: (16.5 + (y - 16.5) * k) * u
    m = {"x0": sx(4), "x1": sx(28), "y0": sy(7), "y1": sy(26), "r": 2 * k * u, "nw": 2 * k * u, "nd": 2 * k * u,
         "ob": (sx(10), sx(22)), "ot": (sx(12), sx(20)), "oy": sy(23)}
    h = m["y1"] - m["y0"]
    m["g"] = h / 23                             # six stripes and five gaps, 3 : 1
    m["s"] = 3 * m["g"]
    # the deck: a panel with round ends across the brick stripe, reels in its ends, the window between
    m.update(cy=236.0, ph=124.0, px0=66.0, px1=S - 66.0, rim=7.0)
    return m


M = _measures()


def _stripe_top(i):
    return M["y0"] + i * (M["s"] + M["g"])


def _opening_x(y):
    """Where the tape opening's slanted sides are at height y."""
    (bl, br), (tl, tr), oy, y1 = M["ob"], M["ot"], M["oy"], M["y1"]
    f = (y - oy) / (y1 - oy)
    return tl + (bl - tl) * f, tr + (br - tr) * f


def stripe_paths():
    """(colour, path) for each stripe: the first with the notch and the top corners, the last split into the
    two feet by the tape opening, with the bottom corners."""
    x0, x1, y0, y1, r, s = M["x0"], M["x1"], M["y0"], M["y1"], M["r"], M["s"]
    out = []
    nl, nr = S / 2 - M["nw"], S / 2 + M["nw"]
    out.append((STRIPES[0], (f"M{x0:.2f} {y0+s:.2f}V{y0+r:.2f}A{r:.2f} {r:.2f} 0 0 1 {x0+r:.2f} {y0:.2f}H{nl:.2f}"
                             f"L{S/2:.2f} {y0+M['nd']:.2f}L{nr:.2f} {y0:.2f}H{x1-r:.2f}A{r:.2f} {r:.2f} 0 0 1 {x1:.2f} {y0+r:.2f}"
                             f"V{y0+s:.2f}Z")))
    for i in range(1, 5):
        t = _stripe_top(i)
        out.append((STRIPES[i], f"M{x0:.2f} {t:.2f}H{x1:.2f}V{t+s:.2f}H{x0:.2f}Z"))
    t = _stripe_top(5)
    lt, rt = _opening_x(t)
    (bl, br) = M["ob"]
    out.append((STRIPES[5], (f"M{x0:.2f} {t:.2f}H{lt:.2f}L{bl:.2f} {y1:.2f}H{x0+r:.2f}A{r:.2f} {r:.2f} 0 0 1 {x0:.2f} {y1-r:.2f}Z"
                             f"M{x1:.2f} {t:.2f}V{y1-r:.2f}A{r:.2f} {r:.2f} 0 0 1 {x1-r:.2f} {y1:.2f}H{br:.2f}L{rt:.2f} {t:.2f}Z")))
    return out


def _rrect(x0, y0, x1, y1, r):
    return (f"M{x0+r:.2f} {y0:.2f}H{x1-r:.2f}A{r:.2f} {r:.2f} 0 0 1 {x1:.2f} {y0+r:.2f}V{y1-r:.2f}A{r:.2f} {r:.2f} 0 0 1 {x1-r:.2f} {y1:.2f}"
            f"H{x0+r:.2f}A{r:.2f} {r:.2f} 0 0 1 {x0:.2f} {y1-r:.2f}V{y0+r:.2f}A{r:.2f} {r:.2f} 0 0 1 {x0+r:.2f} {y0:.2f}Z")


def _circle(cx, cy, r):
    return f"M{cx-r:.2f} {cy:.2f}A{r:.2f} {r:.2f} 0 1 0 {cx+r:.2f} {cy:.2f}A{r:.2f} {r:.2f} 0 1 0 {cx-r:.2f} {cy:.2f}Z"


def deck_paths():
    """(colour, path) for the deck, drawn over the stripes."""
    cy, h, x0, x1, rim = M["cy"], M["ph"], M["px0"], M["px1"], M["rim"]
    top, bot, er = cy - h / 2, cy + h / 2, h / 2
    out = [(PLATE, _rrect(x0 - rim, top - rim, x1 + rim, bot + rim, er + rim)), (PANEL, _rrect(x0, top, x1, bot, er))]
    wx0, wx1, wh = x0 + h + 8, x1 - h - 8, h * 0.62
    out.append((PLATE, _rrect(wx0, cy - wh / 2, wx1, cy + wh / 2, 7)))
    for k in range(7):
        x = wx0 + (wx1 - wx0) * (k + 1) / 8
        out.append((RIBS, _rrect(x - 2.5, cy - wh / 2 + 12, x + 2.5, cy + wh / 2 - 12, 2.5)))
    for rx in (x0 + er, x1 - er):
        hr = er - 22
        out.append((PLATE, _circle(rx, cy, er - 10)))
        out.append((HUB, _circle(rx, cy, hr)))
        for k in range(6):          # six notches round the hub's rim, and its middle
            a = math.pi / 3 * k + math.pi / 6
            out.append((PLATE, _circle(rx + math.cos(a) * hr, cy + math.sin(a) * hr, hr * 0.2)))
        out.append((PLATE, _circle(rx, cy, hr * 0.28)))
    return out


def silhouette():
    """The mark in one colour (Android's themed icon, the notification icon), as a cassette pictogram: the
    outline with the notch and the tape opening, the two reels and the window between them cut out of it,
    and in each reel its hub (six holes, and the middle). Each path even-odd."""
    x0, x1, y0, y1, r = M["x0"], M["x1"], M["y0"], M["y1"], M["r"]
    nl, nr = S / 2 - M["nw"], S / 2 + M["nw"]
    (bl, br), (tl, tr), oy = M["ob"], M["ot"], M["oy"]
    body = (f"M{x0+r:.2f} {y0:.2f}H{nl:.2f}L{S/2:.2f} {y0+M['nd']:.2f}L{nr:.2f} {y0:.2f}H{x1-r:.2f}"
            f"A{r:.2f} {r:.2f} 0 0 1 {x1:.2f} {y0+r:.2f}V{y1-r:.2f}A{r:.2f} {r:.2f} 0 0 1 {x1-r:.2f} {y1:.2f}H{br:.2f}"
            f"L{tr:.2f} {oy:.2f}H{tl:.2f}L{bl:.2f} {y1:.2f}H{x0+r:.2f}A{r:.2f} {r:.2f} 0 0 1 {x0:.2f} {y1-r:.2f}"
            f"V{y0+r:.2f}A{r:.2f} {r:.2f} 0 0 1 {x0+r:.2f} {y0:.2f}Z")
    cy, h, px0, px1 = M["cy"], M["ph"], M["px0"], M["px1"]
    er = h / 2
    wells = [px0 + er, px1 - er]
    for rx in wells:
        body += _circle(rx, cy, er - 6)
    wx0, wx1, wh = px0 + h + 8, px1 - h - 8, h * 0.62
    body += _rrect(wx0, cy - wh / 2, wx1, cy + wh / 2, 10)
    hubs = []
    for rx in wells:
        hr = er - 20
        d = _circle(rx, cy, hr) + _circle(rx, cy, hr * 0.3)
        for k in range(6):
            a = math.pi / 3 * k + math.pi / 6
            d += _circle(rx + math.cos(a) * hr * 0.66, cy + math.sin(a) * hr * 0.66, hr * 0.15)
        hubs.append(d)
    return [body] + hubs


# ------------------------------------------------------------------ SVG

GLOW_DEF = (f'<radialGradient id="g" cx="80%" cy="105%" r="70%"><stop offset="0" stop-color="{GLOW}" stop-opacity=".35"/>'
            f'<stop offset="1" stop-color="{GLOW}" stop-opacity="0"/></radialGradient>')


def _mark():
    return "".join(f'<path fill="{c}" d="{d}"/>' for c, d in stripe_paths() + deck_paths())


def icon_svg(round_=0.22, scale=1.0):
    """The icon on its plate (round_: the corners' share of the side, 0 for a square plate); scale: the mark's
    size, about the plate's middle (the body's middle lands there)."""
    plate = (f'<rect width="{S}" height="{S}" rx="{S*round_:.2f}" fill="{PLATE}"/>'
             f'<rect width="{S}" height="{S}" rx="{S*round_:.2f}" fill="url(#g)"/>')
    mid = (M["y0"] + M["y1"]) / 2
    t = f'translate({S/2:.2f} {S/2:.2f}) scale({scale}) translate({-S/2:.2f} {-mid:.2f})' if scale != 1 else ""
    mark = f'<g transform="{t}">{_mark()}</g>' if t else _mark()
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="{S}" height="{S}" viewBox="0 0 {S} {S}"><defs>{GLOW_DEF}</defs>{plate}{mark}</svg>'


def favicon_svg(only: str = ""):
    """The favicon: the icon drawn on a 32 grid so each edge lands on a pixel, and a simpler drawing for 16 px
    (one pixel = 2 units), where the deck is a dark band with two amber hubs. only="big" or "small": that
    drawing alone, for rendering one size (renderers don't apply the media query)."""
    big = [
        (STRIPES[0], "M1 8V7A2 2 0 0 1 3 5H14L16 7L18 5H29A2 2 0 0 1 31 7V8Z"),
        (STRIPES[1], "M1 9H31V12H1Z"), (STRIPES[2], "M1 13H31V16H1Z"),
        (STRIPES[3], "M1 17H31V20H1Z"), (STRIPES[4], "M1 21H31V24H1Z"),
        (STRIPES[5], "M1 25H11L8 28H3A2 2 0 0 1 1 26Z M31 25V26A2 2 0 0 1 29 28H24L21 25Z"),
        (PANEL, "M8 11H24A4 4 0 0 1 24 19H8A4 4 0 0 1 8 11Z"),
        (PLATE, "M12 13H20V17H12Z"),
        (PLATE, _circle(8, 15, 3)), (PLATE, _circle(24, 15, 3)),
        (HUB, _circle(8, 15, 2)), (HUB, _circle(24, 15, 2)),
        (PLATE, _circle(8, 15, 0.6)), (PLATE, _circle(24, 15, 0.6)),
    ]
    small = [
        (STRIPES[0], "M2 8V5A1 1 0 0 1 3 4H14L16 6L18 4H29A1 1 0 0 1 30 5V8Z"),
        (STRIPES[1], "M2 8H30V10H2Z"), (STRIPES[2], "M2 10H30V20H2Z"),
        (STRIPES[3], "M2 20H30V22H2Z"), (STRIPES[4], "M2 22H30V26H2Z"),
        (STRIPES[5], "M2 26H10V28H3A1 1 0 0 1 2 27Z M30 26V27A1 1 0 0 1 29 28H22V26Z"),
        (PANEL, "M9 10H23A5 5 0 0 1 23 20H9A5 5 0 0 1 9 10Z"),
        (HUB, "M6 12H10V18H6Z"), (HUB, "M22 12H26V18H22Z"),
        (PLATE, "M12 12H20V18H12Z"),
    ]
    paths = lambda ps: "".join(f'<path fill="{c}" d="{d}"/>' for c, d in ps)
    if only:
        return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><defs>{GLOW_DEF}</defs>'
                f'<rect width="32" height="32" rx="7" fill="{PLATE}"/><rect width="32" height="32" rx="7" fill="url(#g)"/>'
                f'{paths(big if only == "big" else small)}</svg>')
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">\n'
            '  <!-- Muzix: a cassette of the six stripes, notched on top so it also reads as an M, with a deck across\n'
            '       the middle (scripts/icons.py). Two drawings on the same 32 grid: every edge falls on a whole pixel\n'
            '       at 32px and up, and the small one (one pixel = 2 units) at 16px, where the big one would blur. -->\n'
            '  <style>.small { display: none } @media (max-width: 20px) { .big { display: none } .small { display: inline } }</style>\n'
            f'  <defs>{GLOW_DEF}</defs>\n'
            f'  <rect width="32" height="32" rx="7" fill="{PLATE}"/><rect width="32" height="32" rx="7" fill="url(#g)"/>\n'
            f'  <g class="big">{paths(big)}</g>\n'
            f'  <g class="small">{paths(small)}</g>\n'
            '</svg>\n')


def favicon_at(size: int) -> str:
    """The favicon's drawing for one size: the small one up to 20 px."""
    return favicon_svg("small" if size <= 20 else "big")


# ------------------------------------------------------------------ Android's vector drawables

def _vd(width, height, viewport, body, comment):
    return (f'<?xml version="1.0" encoding="utf-8"?>\n<!-- {comment} -->\n'
            f'<vector xmlns:android="http://schemas.android.com/apk/res/android"\n'
            f'    android:width="{width}dp" android:height="{height}dp" android:viewportWidth="{viewport}" android:viewportHeight="{viewport}">\n'
            f'{body}</vector>\n')


def _group(scale, tx, ty, inner):
    return (f'    <group android:scaleX="{scale:.5f}" android:scaleY="{scale:.5f}" android:translateX="{tx:.3f}" android:translateY="{ty:.3f}">\n'
            f'{inner}    </group>\n')


def _fit(viewport, radius):
    """Scale and offset that put the cassette's body in the middle of a viewport, its corners within `radius`."""
    hw, hh = (M["x1"] - M["x0"]) / 2, (M["y1"] - M["y0"]) / 2
    k = radius / math.hypot(hw, hh)
    mid = (M["y0"] + M["y1"]) / 2
    return k, viewport / 2 - S / 2 * k, viewport / 2 - mid * k


def android_foreground():
    k, tx, ty = _fit(108, 33)       # inside the 66 dp circle every launcher shape keeps
    inner = "".join(f'        <path android:fillColor="{c}" android:pathData="{d}" />\n' for c, d in stripe_paths() + deck_paths())
    return _vd(108, 108, 108, _group(k, tx, ty, inner),
               "The Muzix icon's cassette (scripts/icons.py), small enough to stay inside the 66 dp circle every launcher shape keeps.")


def android_mono(width, viewport, radius, comment):
    k, tx, ty = _fit(viewport, radius)
    inner = "".join(f'        <path android:fillColor="#ffffff" android:fillType="evenOdd" android:pathData="{d}" />\n'
                    for d in silhouette())
    return _vd(width, width, viewport, _group(k, tx, ty, inner), comment)


# ------------------------------------------------------------------ writing

def _png(svg: str, size: int) -> bytes:
    with tempfile.NamedTemporaryFile("w", suffix=".svg", delete=False) as f:
        f.write(svg)
    try:
        return subprocess.run(["resvg", "-w", str(size), "-h", str(size), f.name, "-c"], check=True, capture_output=True).stdout
    finally:
        os.remove(f.name)


def _write(rel: str, data):
    path = os.path.join(ROOT, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb" if isinstance(data, bytes) else "w") as f:
        f.write(data)
    print("wrote", rel)


def main():
    icon = icon_svg()
    # the web
    _write("frontend/public/favicon.svg", favicon_svg())
    _write("frontend/public/icon-512.png", _png(icon, 512))
    _write("frontend/public/icon-192.png", _png(icon, 192))
    _write("frontend/public/apple-touch-icon.png", _png(icon_svg(round_=0), 180))     # iOS rounds it itself
    _write("frontend/public/icon-maskable-512.png", _png(icon_svg(round_=0, scale=0.66), 512))   # inside the safe circle
    # Muzix Desktop: the favicon's drawings up to 32 px, the icon from 48
    sizes = {n: _png(favicon_at(n) if n <= 32 else icon, n) for n in (16, 20, 24, 32, 48, 64, 128, 256)}
    for n, data in sizes.items():
        _write(f"desktop/muzix_desktop/assets/icons/{n}.png", data)
    _write("desktop/muzix_desktop/assets/icon.png", _png(icon, 512))
    images = [Image.open(io.BytesIO(sizes[n])) for n in sorted(sizes)]
    out = io.BytesIO()
    images[-1].save(out, format="ICO", sizes=[(n, n) for n in sorted(sizes)], append_images=images[:-1])
    _write("desktop/muzix_desktop/assets/icon.ico", out.getvalue())
    # Android
    res = "android/app/src/main/res/drawable/"
    _write(res + "ic_launcher_foreground.xml", android_foreground())
    _write(res + "ic_launcher_monochrome.xml", android_mono(108, 108, 33, "The Muzix icon's cassette in one colour, for Android's themed icons (scripts/icons.py)."))
    _write(res + "ic_stat_muzix.xml", android_mono(24, 24, 11.5, "The Muzix cassette in white, for the notifications (scripts/icons.py)."))
    # Unraid's Docker icon
    _write("unraid/muzix.png", _png(icon, 512))


if __name__ == "__main__":
    main()
