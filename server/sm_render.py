"""
Zeichnen des 800x480-Bildes (1 Bit) aus Einstellungen und gesammelten Werten.

Aufbau: Kopfzeile, Solarbereich (Kacheln oben, Diagramm, Kacheln unten) und optional
eine Bus-Spalte rechts oder links. Dunkles Design = Bild invertiert.
"""

import io
import math
import time
from datetime import datetime

from PIL import Image, ImageDraw, ImageFont, ImageOps

W, H = 800, 480
WEEKDAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]

BOLD_FONTS = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]
REGULAR_FONTS = [
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "C:/Windows/Fonts/arial.ttf",
]
_fonts = {}


def font(size, bold=False):
    key = (size, bold)
    if key in _fonts:
        return _fonts[key]
    f = None
    for path in (BOLD_FONTS if bold else REGULAR_FONTS):
        try:
            f = ImageFont.truetype(path, size)
            break
        except OSError:
            continue
    if f is None:
        try:
            f = ImageFont.load_default(size)
        except TypeError:  # ältere Pillow-Version
            f = ImageFont.load_default()
    _fonts[key] = f
    return f


# ---- Symbole (mit Grundformen gezeichnet, gut lesbar in 1 Bit) -------------
def icon_sun(d, x, y, s):
    cx, cy, r = x + s / 2, y + s / 2, s * 0.22
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=0)
    for i in range(8):
        a = i * math.pi / 4
        d.line((cx + math.cos(a) * s * 0.32, cy + math.sin(a) * s * 0.32,
                cx + math.cos(a) * s * 0.47, cy + math.sin(a) * s * 0.47),
               fill=0, width=max(2, round(s / 14)))


def icon_house(d, x, y, s):
    w = max(2, round(s / 12))
    d.polygon([(x + s * 0.5, y + s * 0.08), (x + s * 0.96, y + s * 0.48),
               (x + s * 0.04, y + s * 0.48)], fill=0)
    d.rectangle((x + s * 0.17, y + s * 0.45, x + s * 0.83, y + s * 0.92), outline=0, width=w)
    d.rectangle((x + s * 0.42, y + s * 0.62, x + s * 0.58, y + s * 0.92), fill=0)


def icon_today(d, x, y, s):
    w = max(2, round(s / 14))
    d.rounded_rectangle((x + s * 0.1, y + s * 0.16, x + s * 0.9, y + s * 0.92),
                        radius=s * 0.08, outline=0, width=w)
    d.rectangle((x + s * 0.1, y + s * 0.16, x + s * 0.9, y + s * 0.36), fill=0)
    for fx in (0.3, 0.7):
        d.line((x + s * fx, y + s * 0.06, x + s * fx, y + s * 0.24), fill=0, width=w + 1)
    icon_sun(d, x + s * 0.3, y + s * 0.44, s * 0.42)


def icon_thermo(d, x, y, s):
    w = max(2, round(s / 14))
    cx = x + s * 0.5
    d.rounded_rectangle((cx - s * 0.12, y + s * 0.04, cx + s * 0.12, y + s * 0.7),
                        radius=s * 0.12, outline=0, width=w)
    d.ellipse((cx - s * 0.22, y + s * 0.58, cx + s * 0.22, y + s * 0.98), fill=0)
    d.rectangle((cx - s * 0.04, y + s * 0.3, cx + s * 0.04, y + s * 0.7), fill=0)


def icon_drop(d, x, y, s):
    cx, r = x + s * 0.5, s * 0.3
    cy = y + s * 0.64
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=0)
    d.polygon([(cx, y + s * 0.04), (cx + r * 0.94, cy - r * 0.34),
               (cx - r * 0.94, cy - r * 0.34)], fill=0)
    d.arc((cx - r * 0.6, cy - r * 0.6, cx + r * 0.6, cy + r * 0.6), 100, 170,
          fill=255, width=max(2, round(s / 16)))


def icon_flame(d, x, y, s):
    pts = [(0.5, 0.02), (0.62, 0.22), (0.78, 0.38), (0.86, 0.6), (0.8, 0.8), (0.64, 0.95),
           (0.36, 0.95), (0.2, 0.8), (0.14, 0.6), (0.24, 0.42), (0.34, 0.5), (0.36, 0.3)]
    d.polygon([(x + s * a, y + s * b) for a, b in pts], fill=0)
    inner = [(0.5, 0.5), (0.62, 0.68), (0.62, 0.84), (0.5, 0.92), (0.38, 0.84), (0.4, 0.66)]
    d.polygon([(x + s * a, y + s * b) for a, b in inner], fill=255)


def icon_shower(d, x, y, s):
    w = max(2, round(s / 12))
    d.line((x + s * 0.2, y + s * 0.9, x + s * 0.2, y + s * 0.15, x + s * 0.55, y + s * 0.15,
            x + s * 0.55, y + s * 0.28), fill=0, width=w, joint="curve")
    d.pieslice((x + s * 0.32, y + s * 0.26, x + s * 0.88, y + s * 0.62), 180, 360, fill=0)
    for fx, fy in ((0.42, 0.55), (0.6, 0.55), (0.78, 0.55), (0.48, 0.75), (0.68, 0.75),
                   (0.88, 0.75), (0.56, 0.93), (0.76, 0.93)):
        r = s * 0.045
        d.ellipse((x + s * fx - r, y + s * fy - r, x + s * fx + r, y + s * fy + r), fill=0)


def icon_heatpump(d, x, y, s):
    w = max(2, round(s / 14))
    d.rounded_rectangle((x + s * 0.06, y + s * 0.14, x + s * 0.94, y + s * 0.86),
                        radius=s * 0.08, outline=0, width=w)
    cx, cy, r = x + s * 0.4, y + s * 0.5, s * 0.24
    d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=0, width=w)
    for i in range(3):
        a = i * 2 * math.pi / 3
        d.line((cx, cy, cx + math.cos(a) * r * 0.8, cy + math.sin(a) * r * 0.8),
               fill=0, width=w)
    for fy in (0.32, 0.5, 0.68):
        d.line((x + s * 0.74, y + s * fy, x + s * 0.86, y + s * fy), fill=0, width=w)


def icon_bolt(d, x, y, s):
    pts = [(0.58, 0.02), (0.18, 0.56), (0.46, 0.56), (0.38, 0.98), (0.82, 0.4), (0.54, 0.4)]
    d.polygon([(x + s * a, y + s * b) for a, b in pts], fill=0)


def icon_grid(d, x, y, s):
    """Strommast."""
    w = max(2, round(s / 14))
    top, foot = (x + s * 0.5, y + s * 0.04), y + s * 0.96
    d.line((top, (x + s * 0.2, foot)), fill=0, width=w)
    d.line((top, (x + s * 0.8, foot)), fill=0, width=w)
    for fy, half in ((0.28, 0.42), (0.5, 0.3)):
        d.line((x + s * (0.5 - half), y + s * fy, x + s * (0.5 + half), y + s * fy),
               fill=0, width=w)
    d.line((x + s * 0.3, y + s * 0.72, x + s * 0.7, y + s * 0.72), fill=0, width=w)


def icon_battery(d, x, y, s):
    w = max(2, round(s / 14))
    d.rounded_rectangle((x + s * 0.22, y + s * 0.14, x + s * 0.78, y + s * 0.96),
                        radius=s * 0.06, outline=0, width=w)
    d.rectangle((x + s * 0.4, y + s * 0.04, x + s * 0.6, y + s * 0.14), fill=0)
    d.rectangle((x + s * 0.32, y + s * 0.5, x + s * 0.68, y + s * 0.86), fill=0)


def icon_bus(d, x, y, s):
    w = max(2, round(s / 14))
    d.rounded_rectangle((x + s * 0.12, y + s * 0.06, x + s * 0.88, y + s * 0.84),
                        radius=s * 0.12, fill=0)
    d.rectangle((x + s * 0.22, y + s * 0.18, x + s * 0.78, y + s * 0.48), fill=255)
    for fx in (0.3, 0.7):
        r = s * 0.07
        d.ellipse((x + s * fx - r, y + s * 0.66 - r, x + s * fx + r, y + s * 0.66 + r), fill=255)
        d.rectangle((x + s * fx - s * 0.08, y + s * 0.84, x + s * fx + s * 0.08, y + s * 0.96),
                    fill=0)
    d.line((x + s * 0.12, y + s * 0.56, x + s * 0.88, y + s * 0.56), fill=255, width=w)


def icon_car(d, x, y, s):
    """Auto von der Seite."""
    body = [(0.04, 0.72), (0.04, 0.52), (0.18, 0.46), (0.3, 0.24), (0.68, 0.24), (0.82, 0.46),
            (0.96, 0.52), (0.96, 0.72)]
    d.polygon([(x + s * a, y + s * b) for a, b in body], fill=0)
    for wx0, wx1 in ((0.36, 0.48), (0.53, 0.64)):   # Fenster
        d.polygon([(x + s * wx0, y + s * 0.3), (x + s * wx1, y + s * 0.3),
                   (x + s * wx1, y + s * 0.44), (x + s * (wx0 - 0.08), y + s * 0.44)], fill=255)
    for cx in (0.26, 0.74):                           # Räder
        r = s * 0.13
        d.ellipse((x + s * cx - r, y + s * 0.72 - r, x + s * cx + r, y + s * 0.72 + r), fill=0)
        r2 = s * 0.05
        d.ellipse((x + s * cx - r2, y + s * 0.72 - r2, x + s * cx + r2, y + s * 0.72 + r2),
                  fill=255)


def icon_charger(d, x, y, s):
    """Ladestation (Wallbox) mit Blitz und Kabel."""
    w = max(2, round(s / 14))
    d.rounded_rectangle((x + s * 0.14, y + s * 0.04, x + s * 0.62, y + s * 0.8),
                        radius=s * 0.08, fill=0)
    bolt = [(0.42, 0.14), (0.26, 0.44), (0.38, 0.44), (0.32, 0.68), (0.5, 0.36), (0.38, 0.36)]
    d.polygon([(x + s * a, y + s * b) for a, b in bolt], fill=255)
    d.line((x + s * 0.62, y + s * 0.5, x + s * 0.8, y + s * 0.5, x + s * 0.8, y + s * 0.94,
            x + s * 0.94, y + s * 0.94), fill=0, width=w, joint="curve")


def icon_plug(d, x, y, s):
    """Steckdose."""
    w = max(2, round(s / 12))
    d.ellipse((x + s * 0.06, y + s * 0.06, x + s * 0.94, y + s * 0.94), outline=0, width=w)
    r = s * 0.08
    for cx in (0.36, 0.64):
        d.ellipse((x + s * cx - r, y + s * 0.5 - r, x + s * cx + r, y + s * 0.5 + r), fill=0)


ICON_FUNCS = {
    "sun": icon_sun, "house": icon_house, "today": icon_today, "thermo": icon_thermo,
    "drop": icon_drop, "flame": icon_flame, "shower": icon_shower, "heatpump": icon_heatpump,
    "bolt": icon_bolt, "grid": icon_grid, "battery": icon_battery, "bus": icon_bus,
    "car": icon_car, "charger": icon_charger, "plug": icon_plug,
}


# ---- Formatierung ----------------------------------------------------------
def state_entry(states, v):
    if v is None:
        return None
    return next((e for e in states or [] if e["value"] == int(v)), None)


def fmt_value(fmt, v, unit="", decimals=1, states=None):
    """-> (Text, Einheit)"""
    if v is None:
        return "–", ""
    if fmt == "power":
        a, sign = abs(v), "-" if v < 0 else ""
        return (f"{sign}{round(a)}", "W") if a < 1000 else (f"{sign}{a / 1000:.1f}", "kW")
    if fmt == "energy":
        a = abs(v)
        if a < 1000:
            return f"{round(v)}", "Wh"
        if a < 1_000_000:
            return f"{v / 1000:.1f}", "kWh"
        return f"{v / 1_000_000:.2f}", "MWh"
    if fmt == "state":
        e = state_entry(states, v)
        return (e["text"] if e and e["text"] else f"Zustand {int(v)}"), ""
    return f"{v:.{decimals}f}", unit


def tile_icon(tile, v):
    if tile["icon"] == "auto":   # Symbol des aktuellen Zustands
        e = state_entry(tile.get("states"), v) if tile["format"] == "state" else None
        return ICON_FUNCS.get(e["icon"]) if e else None
    return ICON_FUNCS.get(tile["icon"])


def nice_ceil(v):
    if v <= 0:
        return 1000.0
    base = 10 ** math.floor(math.log10(v))
    for f in (1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10):
        if v / base <= f + 1e-9:
            return f * base
    return 10 * base


def nice_bounds(lo, hi):
    """Achse für Werte ohne festen Nullpunkt (z. B. Temperatur): runde Grenzen."""
    span = max(hi - lo, 1e-6)
    raw = span / 4
    base = 10 ** math.floor(math.log10(raw))
    step = next(m * base for m in (1, 2, 5, 10) if m * base >= raw)
    a, b = math.floor(lo / step) * step, math.ceil(hi / step) * step
    if b <= a:
        b = a + step
    if round((b - a) / step) % 2:   # gerade Anzahl Schritte, damit die Mitte rund ist
        b += step
    return a, b


def axis_label(fmt, unit, v, top):
    v = round(v, 6)
    if v == 0:
        return "0"
    if fmt == "power":
        return f"{v / 1000:g} kW" if top >= 1000 else f"{v:g} W"
    if fmt == "energy":
        return f"{v / 1000:g} kWh" if top >= 1000 else f"{v:g} Wh"
    return f"{v:g}{unit}"


# ---- Bausteine ---------------------------------------------------------------
SIZES = {  # Symbol, Wert, Beschriftung, Zeilenhöhe, Breitengewicht
    "s": {"icon": 32, "value": 28, "label": 12, "h": 58, "weight": 1.0},
    "m": {"icon": 36, "value": 36, "label": 13, "h": 66, "weight": 1.25},
    "l": {"icon": 50, "value": 52, "label": 16, "h": 90, "weight": 1.6},
    "xl": {"icon": 64, "value": 70, "label": 18, "h": 116, "weight": 1.9},
}
BUMP = {"s": "m", "m": "l", "l": "xl"}   # ohne Diagramm eine Stufe grösser


def fit_text(d, text, size, bold, max_w, min_size=10):
    while size > min_size and d.textlength(text, font=font(size, bold)) > max_w:
        size -= 1
    return size


def value_block(d, x, y, w, icon, isz, label, value, unit, vsize, lsize):
    """Symbol links, darüber klein die Beschriftung, darunter gross der Wert."""
    if icon:
        icon(d, x, y + (lsize + vsize * 1.05 - isz) / 2 + 2, isz)
        tx = x + isz + max(8, isz // 4)
    else:
        tx = x
    avail = x + w - tx
    if label:
        lab = label.upper()
        ls = fit_text(d, lab, lsize, False, avail, min_size=8)
        while lab and d.textlength(lab, font=font(ls)) > avail:
            lab = lab[:-1]
        d.text((tx, y + (lsize - ls)), lab, font=font(ls), fill=0)
    ufs = round(vsize * 0.48)
    unit_w = d.textlength(unit, font=font(ufs)) + 6 if unit else 0
    vs = fit_text(d, value, vsize, True, avail - unit_w)
    vf = font(vs, True)
    vy = y + lsize + 4 + (vsize - vs) * 0.6
    d.text((tx, vy), value, font=vf, fill=0)
    if unit:
        uf = font(round(vs * 0.48))
        vw = d.textlength(value, font=vf)
        d.text((tx + vw + 6, vy + vf.getmetrics()[0] - uf.getmetrics()[0]), unit, font=uf, fill=0)


def tile_size(t, bump=False):
    return SIZES[BUMP[t["size"]] if bump else t["size"]]


def draw_tile_row(d, items, x0, x1, y, rh, bump=False):
    if not items:
        return
    gap = 16
    weights = [tile_size(t, bump)["weight"] for t, _ in items]
    total_w = x1 - x0 - gap * (len(items) - 1)
    x = x0
    for i, ((t, v), wgt) in enumerate(zip(items, weights)):
        w = total_w * wgt / sum(weights)
        sz = tile_size(t, bump)
        text, unit = fmt_value(t["format"], v, t["unit"], t["decimals"], t.get("states"))
        ty = y + (rh - sz["h"]) / 2
        value_block(d, x, ty, w, tile_icon(t, v), sz["icon"], t["label"], text, unit,
                    sz["value"], sz["label"])
        if i:
            d.line((x - gap / 2, y + 4, x - gap / 2, y + rh - 8), fill=0, width=1)
        x += w + gap


def dashed_line(d, pts, width, dash=10, gap=7):
    on, left = True, dash
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        seg = math.hypot(x1 - x0, y1 - y0)
        pos = 0.0
        while pos < seg:
            step = min(left, seg - pos)
            if on:
                a, b = pos / seg, (pos + step) / seg
                d.line((x0 + (x1 - x0) * a, y0 + (y1 - y0) * a,
                        x0 + (x1 - x0) * b, y0 + (y1 - y0) * b), fill=0, width=width)
            pos += step
            left -= step
            if left <= 0:
                on = not on
                left = dash if on else gap


def stroke(d, pts, style):
    if style == "line":
        d.line(pts, fill=0, width=4, joint="curve")
    elif style == "thin":
        d.line(pts, fill=0, width=2, joint="curve")
    elif style == "dash":
        dashed_line(d, pts, 3)
    elif style == "dot":
        dashed_line(d, pts, 3, dash=2, gap=5)
    else:  # Kante der Fläche
        d.line(pts, fill=0, width=2, joint="curve")


def segments(pts, max_gap=45 * 60):
    """Zerlegt in zusammenhängende Stücke (Lücken > 45 min nicht verbinden)."""
    out, cur, prev = [], [], None
    for t, v in pts:
        if prev is not None and t - prev > max_gap:
            out.append(cur)
            cur = []
        cur.append((t, v))
        prev = t
    if cur:
        out.append(cur)
    return out


def hatch(size, spacing=6, width=1):
    pat = Image.new("L", size, 255)
    pd = ImageDraw.Draw(pat)
    for k in range(-size[1], size[0], spacing):
        pd.line((k, size[1], k + size[1], 0), fill=0, width=width)
    return pat


def legend_item(d, x, y, style, text, fs=14):
    if style == "area":
        d.rectangle((x, y + 3, x + 22, y + 13), outline=0, width=2)
        for k in range(x, x + 22, 5):
            e = min(k + 10, x + 22)
            d.line((k, y + 13, e, y + 13 - (e - k)), fill=0)
    else:
        stroke(d, [(x, y + 8), (x + 22, y + 8)], style)
    d.text((x + 28, y), text, font=font(fs), fill=0)
    return x + 28 + d.textlength(text, font=font(fs)) + 18


def draw_chart(img, d, box, series, window, err, range_label):
    x0, y0, x1, y1 = box
    lx = x0
    for s, _ in series:
        if s["label"]:
            lx = legend_item(d, lx, y0, s["style"], s["label"])
    d.text((x1, y0), range_label, font=font(14, True), fill=0, anchor="ra")

    left = [(s, p) for s, p in series if s["axis"] == "left" and p]
    right = [(s, p) for s, p in series if s["axis"] == "right" and p]
    px0 = x0 + (44 if left else 6)
    px1 = x1 - (34 if right else 6)
    py0, py1 = y0 + 28, y1 - 20
    small = font(13)
    start, end = window

    if not left and not right:
        d.rectangle((px0, py0, px1, py1), outline=0, width=1)
        msg = "Verlauf nicht verfügbar" + (f": {err}" if err else "")
        d.text(((px0 + px1) / 2, (py0 + py1) / 2), msg[:50], font=font(16), fill=0, anchor="mm")
        return

    def X(t):
        return px0 + (t - start) / (end - start) * (px1 - px0)

    scales = {}
    if left:
        vals = [v for _, p in left for _, v in p]
        lo = min(0.0, min(vals))
        hi = nice_ceil(max(vals)) if max(vals) > 0 else 0.0
        if hi <= lo:
            hi = lo + 1
        scales["left"] = (lo, hi, left[0][0])
    if right:
        vals = [v for _, p in right for _, v in p]
        lo, hi = nice_bounds(min(vals), max(vals))
        scales["right"] = (lo, hi, right[0][0])

    def Y(axis, v):
        lo, hi, _ = scales[axis]
        return py1 - (v - lo) / (hi - lo) * (py1 - py0)

    # Raster (gepunktet) und Skalen
    for f in (0, 0.5, 1):
        y = py1 - f * (py1 - py0)
        if f > 0:
            for xx in range(int(px0), int(px1), 6):
                d.point((xx, y), fill=0)
        if "left" in scales:
            lo, hi, s = scales["left"]
            d.text((px0 - 6, y), axis_label(s["format"], s["unit"], lo + f * (hi - lo), hi),
                   font=small, fill=0, anchor="rm")
        if "right" in scales:
            lo, hi, s = scales["right"]
            d.text((px1 + 6, y), axis_label(s["format"], s["unit"], lo + f * (hi - lo), hi),
                   font=small, fill=0, anchor="lm")
    d.line((px0, py1, px1, py1), fill=0, width=2)
    t = math.ceil(start / 3600) * 3600
    while t <= end + 1:
        hh = datetime.fromtimestamp(t).hour
        if hh % 3 == 0:
            x = X(t)
            d.line((x, py1, x, py1 + (6 if hh % 6 == 0 else 3)), fill=0, width=2)
            if hh % 6 == 0:
                lbl = "24" if (hh == 0 and t >= end - 1 and range_label == "Heute") else f"{hh:02d}"
                d.text((x, py1 + 6), lbl, font=small, fill=0, anchor="mt")
        t += 3600

    pat = None
    for s, pts in series:   # Flächen zuerst, Linien darüber
        if s["style"] != "area" or not pts:
            continue
        pat = pat or hatch((W, H))
        y_zero = Y(s["axis"], max(scales[s["axis"]][0], 0))
        for seg in segments(pts):
            poly = [(X(t), Y(s["axis"], v)) for t, v in seg]
            if len(poly) < 2:
                continue
            mask = Image.new("L", (W, H), 0)
            ImageDraw.Draw(mask).polygon(poly + [(poly[-1][0], y_zero), (poly[0][0], y_zero)],
                                         fill=255)
            img.paste(pat, (0, 0), mask)
            stroke(d, poly, "area")
    for s, pts in series:
        if s["style"] == "area" or not pts:
            continue
        for seg in segments(pts):
            line = [(X(t), Y(s["axis"], v)) for t, v in seg]
            if len(line) > 1:
                stroke(d, line, s["style"])

    now = time.time()
    if start < now < end:   # Jetzt-Markierung
        xn = X(now)
        for yy in range(int(py0), int(py1), 4):
            d.line((xn, yy, xn, yy + 1), fill=0, width=1)


def draw_bus(d, box, deps, err, b):
    x0, y0, x1, y1 = box
    icon_bus(d, x0, y0 + 2, 30)
    d.text((x0 + 40, y0 + 2), "Bus", font=font(26, True), fill=0)
    if b["via_label"]:
        lab = "→ " + b["via_label"]
        d.text((x0, y0 + 40), lab, font=font(fit_text(d, lab, 15, True, x1 - x0), True), fill=0)
    if b["station"]:
        lab = "ab " + b["station"].split(",")[-1].strip()
        d.text((x0, y0 + 60), lab, font=font(fit_text(d, lab, 14, False, x1 - x0)), fill=0)
    top = y0 + 92
    if deps is None and not err:
        for i, line in enumerate(("Haltestelle unter", "/config einstellen")):
            d.text((x0, top + i * 22), line, font=font(15), fill=0)
        return
    if err or not deps:
        msg = "öV-Daten nicht erreichbar" if err else "keine Abfahrten"
        d.text(((x0 + x1) / 2, top + 40), msg, font=font(15), fill=0, anchor="mm")
        return
    row = (y1 - top) / b["count"]
    tsize = min(30, int(row * 0.5))
    badge = min(34, int(row * 0.56))
    wide = b["width"] == "wide"
    for i, dep in enumerate(deps):
        y = top + i * row
        cy = y + row / 2
        if i:
            for xx in range(int(x0), int(x1), 5):
                d.point((xx, y), fill=0)
        d.rounded_rectangle((x0, cy - badge / 2, x0 + badge, cy + badge / 2), radius=6, fill=0)
        lf = font(fit_text(d, dep["line"], int(badge * 0.6), True, badge - 6), True)
        d.text((x0 + badge / 2, cy), dep["line"], font=lf, fill=255, anchor="mm")
        tx = x0 + badge + 12
        time_txt = datetime.fromtimestamp(dep["t"]).strftime("%H:%M")
        if wide and dep.get("to") and row >= 44:
            d.text((tx, cy - 2), time_txt, font=font(tsize, True), fill=0, anchor="ls")
            dest = dep["to"].split(",")[-1].strip()
            d.text((tx, cy + 3), dest, font=font(fit_text(d, dest, 13, False, x1 - tx - 30)),
                   fill=0, anchor="lt")
        else:
            d.text((tx, cy), time_txt, font=font(tsize, True), fill=0, anchor="lm")
        if dep["delay"]:
            d.text((x1, cy), f"+{dep['delay']}", font=font(min(22, tsize), True),
                   fill=0, anchor="rm")


# ---- Einrichtung -------------------------------------------------------------------
def draw_qr(d, x, y, matrix, module):
    """QR-Code mit Ruhezone (4 Module) ab (x, y), dunkle Module schwarz."""
    n = len(matrix) + 8
    d.rectangle((x, y, x + n * module - 1, y + n * module - 1), fill=255)
    for r, row in enumerate(matrix):
        for c, dark in enumerate(row):
            if dark:
                px, py = x + (c + 4) * module, y + (r + 4) * module
                d.rectangle((px, py, px + module - 1, py + module - 1), fill=0)
    return n * module


def render_setup(cfg, url, battery=None):
    """Erste Inbetriebnahme: Anleitung, Adresse der Einstellungen und QR-Code.
    Immer hell gezeichnet, damit jede Kamera-App den QR-Code liest."""
    img = Image.new("L", (W, H), 255)
    d = ImageDraw.Draw(img)
    draw_header(d, cfg, battery)
    m, x1 = 20, 470
    d.text((m, 72), "Noch nicht eingerichtet", font=font(32, True), fill=0)
    steps = [
        ("1.", "Handy oder Computer im selben WLAN"),
        ("2.", "QR-Code scannen oder Adresse öffnen:"),
        (None, url),
        ("3.", "Solar Manager: smId und API-Key"),
        (None, "eintragen, „Verbindung testen“"),
        ("4.", "Speichern. Das Display übernimmt es"),
        (None, "beim nächsten Aufwachen."),
    ]
    y = 140
    for num, text in steps:
        if num:
            d.text((m, y), num, font=font(20, True), fill=0)
        if text == url:
            size = fit_text(d, url, 22, True, x1 - m - 30, min_size=12)
            d.text((m + 30, y), url, font=font(size, True), fill=0)
            y += 40
        else:
            d.text((m + 30, y), text, font=font(fit_text(d, text, 20, False, x1 - m - 30)),
                   fill=0)
            y += 30
    try:
        from sm_qr import qr_matrix
        matrix = qr_matrix(url)
        module = max(3, min(9, 290 // (len(matrix) + 8)))
        size = (len(matrix) + 8) * module
        qx, qy = W - m - size + module * 2, 56 + (H - 56 - size) // 2
        draw_qr(d, qx, qy, matrix, module)
    except ValueError:
        pass   # Adresse zu lang: nur Text
    return img


# ---- Gesamtbild ------------------------------------------------------------------
def draw_header(d, cfg, battery):
    disp, m = cfg["display"], 20
    d.text((m, 12), disp["title"], font=font(22, True), fill=0)
    rx = W - m
    stamp = datetime.now().astimezone()
    if disp["show_date"]:
        date_txt = f"{WEEKDAYS[stamp.weekday()]} {stamp:%d.%m.  %H:%M}"
        d.text((rx, 14), date_txt, font=font(19), fill=0, anchor="ra")
        rx -= d.textlength(date_txt, font=font(19)) + 24
    if disp["show_battery"] and battery is not None:
        txt = f"{battery} %"
        d.text((rx, 14), txt, font=font(19), fill=0, anchor="ra")
        bx1 = rx - d.textlength(txt, font=font(19)) - 8
        bx0, by0, by1 = bx1 - 34, 16, 32
        d.rectangle((bx0, by0, bx1 - 4, by1), outline=0, width=2)
        d.rectangle((bx1 - 3, by0 + 5, bx1, by1 - 5), fill=0)
        fill_w = round((bx1 - 4 - bx0 - 6) * battery / 100)
        if fill_w > 0:
            d.rectangle((bx0 + 3, by0 + 3, bx0 + 3 + fill_w, by1 - 3), fill=0)
    d.line((m, 44, W - m, 44), fill=0, width=3)


def render(cfg, view, battery=None, config_url=""):
    if view.get("setup"):
        return render_setup(cfg, config_url or "http://<Raspberry-IP>:8080/config", battery)
    img = Image.new("L", (W, H), 255)
    d = ImageDraw.Draw(img)
    disp, bus = cfg["display"], cfg["bus"]
    m = 20
    draw_header(d, cfg, battery)

    # Aufteilung Solar / Bus
    sx0, sx1 = m, W - m
    if bus["enabled"]:
        bw = 266 if bus["width"] == "wide" else 206
        if bus["position"] == "right":
            split = W - m - bw
            sx1 = split - 16
            bbox = (split + 18, 56, W - m, H - 10)
        else:
            split = m + bw
            sx0 = split + 16
            bbox = (m, 56, split - 18, H - 10)
        d.line((split, 54, split, H - 12), fill=0, width=2)
        draw_bus(d, bbox, view.get("bus"), view.get("bus_err"), bus)

    top, bottom = 54, H - 8
    if view.get("error"):
        cx = (sx0 + sx1) / 2
        d.text((cx, H // 2 - 14), "Solarmanager nicht erreichbar",
               font=font(fit_text(d, "Solarmanager nicht erreichbar", 26, True, sx1 - sx0), True),
               fill=0, anchor="mm")
        err = str(view["error"])[:90]
        d.text((cx, H // 2 + 22), err, font=font(fit_text(d, err, 15, False, sx1 - sx0, 11)),
               fill=0, anchor="mm")
        if config_url:
            d.text((cx, H // 2 + 56), "Einstellungen: " + config_url,
                   font=font(fit_text(d, "Einstellungen: " + config_url, 15, False, sx1 - sx0)),
                   fill=0, anchor="mm")
    else:
        rows = {a: [(t, v) for t, v in view["tiles"] if t["area"] == a] for a in ("top", "bottom")}
        chart = cfg["chart"]["enabled"]
        rh = {a: max((tile_size(t, not chart)["h"] for t, _ in r), default=0)
              for a, r in rows.items()}
        if chart:
            y = top
            if rows["top"]:
                draw_tile_row(d, rows["top"], sx0, sx1, y, rh["top"])
                y += rh["top"]
                d.line((sx0, y, sx1, y), fill=0, width=1)
                y += 8
            yb = bottom
            if rows["bottom"]:
                yb = bottom - rh["bottom"]
                draw_tile_row(d, rows["bottom"], sx0, sx1, yb, rh["bottom"])
                d.line((sx0, yb - 6, sx1, yb - 6), fill=0, width=1)
                yb -= 10
            label = "Heute" if cfg["chart"]["range"] == "today" else "24 h"
            draw_chart(img, d, (sx0, y, sx1, yb), view["series"], view["window"],
                       view.get("chart_err"), label)
        else:   # ohne Diagramm: Reihen mittig in der oberen und unteren Hälfte
            mid = (top + bottom) / 2
            if rows["top"]:
                draw_tile_row(d, rows["top"], sx0, sx1, (top + mid - rh["top"]) / 2, rh["top"],
                              bump=True)
            if rows["bottom"]:
                draw_tile_row(d, rows["bottom"], sx0, sx1, (mid + bottom - rh["bottom"]) / 2,
                              rh["bottom"], bump=True)
            if rows["top"] and rows["bottom"]:
                d.line((sx0, mid, sx1, mid), fill=0, width=1)

    if disp["theme"] == "dark":
        img = ImageOps.invert(img)
    return img


def image_bytes(img, fmt="png"):
    one_bit = img.convert("1", dither=Image.Dither.NONE)
    buf = io.BytesIO()
    if fmt == "bmp":
        one_bit.save(buf, format="BMP")
        return buf.getvalue(), "image/bmp"
    one_bit.save(buf, format="PNG", bits=1)
    return buf.getvalue(), "image/png"
