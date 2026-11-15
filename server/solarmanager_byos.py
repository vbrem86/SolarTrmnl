#!/usr/bin/env python3
"""
Solarmanager -> TRMNL, eigener Server (BYOS), ohne TRMNL-Konto

Kleiner eigener TRMNL-Server für dein Heimnetz (z. B. auf dem Raspberry Pi).
Das TRMNL-Gerät fragt ihn statt der TRMNL-Cloud ab. Der Server holt die Daten
vom Solarmanager und liefert ein fertig gezeichnetes 800x480-Bild (1 Bit) aus.

Anzeige links (wie die SolarWatch-App, für das grössere Display angepasst):
    oben   – PV-Leistung jetzt, Verbrauch jetzt, PV-Produktion heute
    Mitte  – Tagesverlauf 00–24 Uhr: PV, Verbrauch (kW) und Wassertemperatur (°C)
    unten  – Aussentemperatur, Zustand Wärmepumpe, Wassertemperatur
Anzeige rechts: nächste Busabfahrten einer Haltestelle (Linien und Richtung wählbar)
    mit Verspätung, live von transport.opendata.ch (öV-Daten Schweiz, ohne Schlüssel)

Datenquelle (SM_SOURCE):
    cloud  (Standard)  Solarmanager-Cloud-API v3 (wie SolarWatch), braucht SM_ID und SM_API_KEY
    local              Gateway im Heimnetz (http://<IP>/v2/point), braucht SM_IP – ohne Verlauf

Installation (einmalig):
    sudo apt install python3-pil        (oder: pip3 install pillow)

Erster Test der Zugangsdaten (zeigt die Rohdaten, schreibt kein Bild):
    SM_ID=... SM_API_KEY=... python3 solarmanager_byos.py --test

Start:
    SM_ID=... SM_API_KEY=... python3 solarmanager_byos.py
    python3 solarmanager_byos.py --sample            (Beispieldaten, ohne Zugangsdaten)

Vorschau:
    http://<IP-dieses-Rechners>:8080/
    python3 solarmanager_byos.py --preview --sample  -> preview.png

Im TRMNL-Gerät (WLAN-Setup-Portal) als eigenen Server eintragen:
    http://<IP-dieses-Rechners>:8080

Konfiguration per Umgebungsvariablen:
    SM_SOURCE, SM_ID, SM_API_KEY, SM_IP, PORT, REFRESH_SECONDS,
    IMAGE_FORMAT (png|bmp), SM_CLOUD_URL,
    BUS_STATION, BUS_LINES, BUS_VIA, BUS_VIA_LABEL, BUS_COUNT
"""

import argparse
import io
import json
import math
import os
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from PIL import Image, ImageDraw, ImageFont

# ---- Konfiguration ---------------------------------------------------------
SM_SOURCE = os.environ.get("SM_SOURCE", "cloud").lower()  # cloud | local
SM_ID = os.environ.get("SM_ID", "")                       # smId des Gateways
SM_API_KEY = os.environ.get("SM_API_KEY", "")
SM_IP = os.environ.get("SM_IP", "192.168.1.231")          # nur für local
SM_CLOUD_URL = os.environ.get("SM_CLOUD_URL", "https://cloud.solar-manager.ch")
PORT = int(os.environ.get("PORT", "8080"))
REFRESH_SECONDS = int(os.environ.get("REFRESH_SECONDS", "300"))
IMAGE_FORMAT = os.environ.get("IMAGE_FORMAT", "png").lower()  # png | bmp
# Bus (öV-Daten Schweiz über transport.opendata.ch, ohne Schlüssel).
# Haltestelle usw. nur in .env eintragen; leer = Bus-Spalte zeigt einen Hinweis.
BUS_STATION = os.environ.get("BUS_STATION", "")          # z. B. "Bern, Bahnhof"
BUS_LINES = [s.strip() for s in os.environ.get("BUS_LINES", "").split(",") if s.strip()]
BUS_VIA = os.environ.get("BUS_VIA", "")    # Richtung: Kurs hält danach hier (Namensanfang)
BUS_VIA_LABEL = os.environ.get("BUS_VIA_LABEL", "")
BUS_COUNT = int(os.environ.get("BUS_COUNT", "5"))
BUS_API = os.environ.get("BUS_API", "https://transport.opendata.ch/v1")
# ----------------------------------------------------------------------------

W, H = 800, 480
STREAM_CACHE_S = 30        # Cloud-Limit: 1000 Stream-Abfragen pro Stunde
HISTORY_CACHE_S = 5 * 60   # Verlauf hat 15-min-Auflösung
BUS_CACHE_S = 60

# operationState der Wärmepumpe (von Solar Manager nicht dokumentiert,
# Zuordnung an der eigenen Anlage bestätigt 14.11.2026)
HEAT_PUMP_STATES = {1: "Standby", 2: "Heizen", 3: "Warmwasser"}

WEEKDAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]

# Zustand des Geräts, wie es ihn bei /api/display in den Headern meldet
_device = {}

# LiPo-Kennlinie (Spannung -> % Ladung), Näherung für 1 Zelle ohne Last
_LIPO = [(3.30, 0), (3.50, 5), (3.60, 15), (3.70, 30), (3.80, 50),
         (3.90, 65), (4.00, 80), (4.10, 90), (4.20, 100)]


def battery_percent(volts):
    if volts is None:
        return None
    if volts <= _LIPO[0][0]:
        return 0
    for (v0, p0), (v1, p1) in zip(_LIPO, _LIPO[1:]):
        if volts <= v1:
            return round(p0 + (volts - v0) / (v1 - v0) * (p1 - p0))
    return 100

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


# ---- Daten -----------------------------------------------------------------
#
# Internes Format:
#   now  = {"pW", "cW", "grid", "soc", "t",
#           "hp": {"id", "water", "outside", "state"} | None}
#   hist = {"start", "end" (Epoch-s, lokaler Tag), "pv", "cons", "water"
#           (Listen von (Epoch-s, Wert)), "today_wh"}

_cache = {"now": (0.0, None), "hist": (0.0, None)}
USE_SAMPLE = False


def num(value, default=None):
    try:
        v = float(value)
        return default if math.isnan(v) else v
    except (TypeError, ValueError):
        return default


def parse_time(s):
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def iso_utc(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def day_bounds():
    start = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    return start.timestamp(), end.timestamp()


def cloud_get(path):
    """GET auf die Cloud-API v3 mit Header X-API-KEY (wie SolarWatch)."""
    if not SM_ID or not SM_API_KEY:
        raise RuntimeError("SM_ID / SM_API_KEY fehlen (siehe .env.example)")
    req = urllib.request.Request(SM_CLOUD_URL + path, headers={
        "Accept": "application/json", "X-API-KEY": SM_API_KEY})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise RuntimeError("API-Schlüssel ungültig (ohne 'Erneuerung erlauben' erstellen)")
        if e.code == 429:
            raise RuntimeError("Zu viele Abfragen (HTTP 429)")
        raise RuntimeError(f"HTTP {e.code} bei {path.split('?')[0]}")


def parse_heatpump(devices):
    """Wärmepumpe = Gerät mit operationState bzw. Aussentemperatur."""
    for d in devices or []:
        if not isinstance(d, dict):
            continue
        if "operationState" not in d and "temperatureOutside" not in d:
            continue
        state = num(d.get("operationState"))
        return {"id": d.get("_id"), "water": num(d.get("temperature")),
                "outside": num(d.get("temperatureOutside")),
                "state": int(state) if state is not None else None}
    return None


def parse_now(o):
    pv = num(o.get("pW"), 0.0)
    cons = num(o.get("cW"), 0.0)
    bc, bd = num(o.get("bcW"), 0.0), num(o.get("bdW"), 0.0)
    iw, ew = num(o.get("iW")), num(o.get("eW"))
    grid = (iw or 0) - (ew or 0) if (iw is not None or ew is not None) else cons + bc - pv - bd
    return {"pW": pv, "cW": cons, "grid": grid, "soc": num(o.get("soc")),
            "hp": parse_heatpump(o.get("devices")),
            "t": o.get("t") or datetime.now().astimezone().isoformat()}


def range_series(path, keys):
    """GET .../data/range -> {key: [(Epoch-s, Wert), ...]}"""
    raw = cloud_get(path)
    arr = raw.get("data") if isinstance(raw, dict) else raw
    out = {k: [] for k in keys}
    for o in arr or []:
        t = parse_time(o.get("t")) if isinstance(o, dict) else None
        if t is None:
            continue
        for k in keys:
            v = num(o.get(k))
            if v is not None:
                out[k].append((t, v))
    return {k: sorted(v) for k, v in out.items()}


def fetch_now():
    if SM_SOURCE == "local":
        req = urllib.request.Request(f"http://{SM_IP}/v2/point",
                                     headers={"X-API-Key": SM_API_KEY})
        with urllib.request.urlopen(req, timeout=8) as resp:
            raw = json.loads(resp.read())
    else:
        raw = cloud_get(f"/v3/users/{SM_ID}/data/stream")
    return parse_now(raw), raw


def fetch_history(hp_id):
    start, end = day_bounds()
    if SM_SOURCE == "local":   # Gateway liefert keinen Verlauf
        return {"start": start, "end": end, "pv": [], "cons": [], "water": [],
                "today_wh": None}
    rng = urllib.parse.urlencode({"from": iso_utc(start), "to": iso_utc(time.time()),
                                  "interval": 900})
    main = range_series(f"/v3/users/{SM_ID}/data/range?{rng}", ("pW", "cW", "pWh"))
    # pWh = Energie je Intervall; Summe ab Mitternacht = Produktion heute
    today_wh = sum(v for _, v in main["pWh"])
    water = []
    if hp_id:
        water = range_series(f"/v3/devices/{hp_id}/data/range?{rng}",
                             ("temperature",))["temperature"]
    pv, cons = main["pW"], main["cW"]
    return {"start": start, "end": end, "pv": pv, "cons": cons, "water": water,
            "today_wh": today_wh}


def sample_data():
    """Plausibler Tag mit Beispielwerten (für --sample)."""
    start, end = day_bounds()
    now = time.time()
    rnd = random.Random(int(start))           # gleicher Tag -> gleiche Kurve
    pv, cons, water = [], [], []
    temp = 48.0
    t = start
    while t <= now:
        h = (t - start) / 3600
        sun = max(0.0, math.sin(math.pi * (h - 7.5) / 9.5)) if 7.5 < h < 17 else 0.0
        clouds = 0.75 + 0.25 * math.sin(h * 2.3) + rnd.uniform(-0.1, 0.1)
        p = max(0.0, 5200 * sun ** 1.4 * clouds)
        heating = 6 <= h < 8 or 12 <= h < 14 or 18.5 <= h < 19.5
        c = 350 + rnd.uniform(0, 250) + (1800 if heating else 0) \
            + (900 if 11.5 <= h < 12.5 or 18 <= h < 19 else 0)
        temp = min(56.0, temp + 2.2) if heating and h > 11 else max(42.0, temp - 0.35)
        pv.append((t, p))
        cons.append((t, c))
        water.append((t, temp))
        t += 900
    today_wh = sum(v for _, v in pv) * 0.25
    p_now, c_now = (pv[-1][1] if pv else 0), (cons[-1][1] if cons else 400)
    now_d = {"pW": p_now, "cW": c_now, "grid": c_now - p_now, "soc": None,
             "hp": {"id": "sample", "water": water[-1][1] if water else 50.0,
                    "outside": 6.4, "state": 3 if c_now > 1500 else 2},
             "t": datetime.now().astimezone().isoformat()}
    hist = {"start": start, "end": end, "pv": pv, "cons": cons, "water": water,
            "today_wh": today_wh}
    return now_d, hist


def get_data():
    """Liefert (now, hist, hist_error) mit Zwischenspeicher."""
    if USE_SAMPLE:
        n, h = sample_data()
        return n, h, None
    ts, now_d = _cache["now"]
    if not now_d or time.time() - ts > STREAM_CACHE_S:
        now_d, _ = fetch_now()
        _cache["now"] = (time.time(), now_d)
    ts, hist = _cache["hist"]
    hist_err = None
    stale_day = hist and hist["start"] != day_bounds()[0]
    if not hist or stale_day or time.time() - ts > HISTORY_CACHE_S:
        try:
            hist = fetch_history((now_d.get("hp") or {}).get("id"))
            _cache["hist"] = (time.time(), hist)
        except Exception as e:  # Verlauf ist optional, aktuelle Werte trotzdem zeigen
            hist_err = str(e)
            if stale_day:
                hist = None
    return now_d, hist, hist_err



# ---- Bus (öV Schweiz) ------------------------------------------------------
#
# transport.opendata.ch/v1/stationboard: Abfahrten mit Plan-Zeit, Verspätung
# (stop.delay in Minuten, null ohne Echtzeit) und Halteliste (passList).
# Richtung: nur Kurse, die nach der Haltestelle an BUS_VIA halten.

_bus_cache = {"ts": 0.0, "deps": None}


def fetch_bus():
    q = urllib.parse.urlencode({"station": BUS_STATION, "limit": 40})
    req = urllib.request.Request(f"{BUS_API}/stationboard?{q}",
                                 headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        raw = json.loads(resp.read())
    deps = []
    for e in raw.get("stationboard") or []:
        if BUS_LINES and str(e.get("number", "")).strip() not in BUS_LINES:
            continue
        stops = [((p.get("station") or {}).get("name") or "") for p in e.get("passList") or []]
        if BUS_VIA and not any(n.startswith(BUS_VIA) for n in stops[1:]):
            continue
        st = e.get("stop") or {}
        ts = num(st.get("departureTimestamp"))
        if ts is None:
            continue
        delay = num(st.get("delay"))
        deps.append({"line": str(e["number"]).strip(), "t": ts,
                     "delay": int(delay) if delay is not None else None,
                     "to": e.get("to", "")})
    return sorted(deps, key=lambda d: d["t"])


def sample_bus():
    now = time.time()
    base = now - now % 900 + 6 * 60
    out = []
    for i in range(BUS_COUNT + 1):
        out.append({"line": "6" if i % 2 == 0 else "2", "t": base + i * 900,
                    "delay": [2, 0, 1, None, None, None][i % 6], "to": ""})
    return out


def get_bus():
    """Nächste BUS_COUNT Abfahrten (bereits abgefahrene ausgeblendet)."""
    if USE_SAMPLE:
        deps = sample_bus()
    elif not BUS_STATION:
        return None
    else:
        if _bus_cache["deps"] is None or time.time() - _bus_cache["ts"] > BUS_CACHE_S:
            _bus_cache.update(ts=time.time(), deps=fetch_bus())
        deps = _bus_cache["deps"]
    now = time.time()
    return [d for d in deps if d["t"] + (d["delay"] or 0) * 60 > now - 20][:BUS_COUNT]


# ---- Formatierung ----------------------------------------------------------
def fmt_power(w):
    w = abs(w or 0)
    return (f"{round(w)}", "W") if w < 1000 else (f"{w / 1000:.1f}", "kW")


def fmt_energy(wh):
    if wh is None:
        return "–", ""
    return (f"{round(wh)}", "Wh") if wh < 1000 else (f"{wh / 1000:.1f}", "kWh")


def fmt_temp(c):
    return ("–", "") if c is None else (f"{c:.1f}", "°C")


def nice_ceil(v):
    if v <= 0:
        return 1000.0
    base = 10 ** math.floor(math.log10(v))
    for f in (1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10):
        if v / base <= f:
            return f * base
    return 10 * base


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


def heatpump_state(hp):
    st = (hp or {}).get("state")
    if st == 2:
        return icon_flame, "Heizen"
    if st == 3:
        return icon_shower, "Warmwasser"
    return icon_heatpump, ("–" if st is None else HEAT_PUMP_STATES.get(st, f"Zustand {st}"))


# ---- Zeichnen --------------------------------------------------------------
def value_block(d, x, y, icon, isz, label, value, unit, vsize, lsize=16):
    """Symbol links, darüber klein die Beschriftung, darunter gross der Wert."""
    icon(d, x, y + (lsize + vsize * 1.05 - isz) / 2 + 2, isz)
    tx = x + isz + max(8, isz // 4)
    d.text((tx, y), label.upper(), font=font(lsize), fill=0)
    vf = font(vsize, True)
    vy = y + lsize + 4
    d.text((tx, vy), value, font=vf, fill=0)
    if unit:
        vw = d.textlength(value, font=vf)
        uf = font(round(vsize * 0.48))
        asc_v = vf.getmetrics()[0]
        asc_u = uf.getmetrics()[0]
        d.text((tx + vw + 6, vy + asc_v - asc_u), unit, font=uf, fill=0)


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


def legend_item(d, x, y, kind, text, fs=14):
    if kind == "area":
        d.rectangle((x, y + 3, x + 22, y + 13), outline=0, width=2)
        for k in range(x, x + 22, 5):
            e = min(k + 10, x + 22)
            d.line((k, y + 13, e, y + 13 - (e - k)), fill=0)
    elif kind == "line":
        d.line((x, y + 8, x + 22, y + 8), fill=0, width=4)
    else:
        dashed_line(d, [(x, y + 8), (x + 22, y + 8)], 3, dash=7, gap=4)
    d.text((x + 28, y), text, font=font(fs), fill=0)
    return x + 28 + d.textlength(text, font=font(fs)) + 18


def draw_chart(img, d, box, hist, err):
    x0, y0, x1, y1 = box
    # Legende
    lx = x0
    lx = legend_item(d, lx, y0, "area", "PV")
    lx = legend_item(d, lx, y0, "line", "Verbrauch")
    if hist and hist["water"]:
        legend_item(d, lx, y0, "dash", "Wasser")
    d.text((x1, y0), "Heute", font=font(14, True), fill=0, anchor="ra")

    px0, px1 = x0 + 44, x1 - 34            # Plotbereich
    py0, py1 = y0 + 28, y1 - 20
    small = font(13)

    if not hist or not (hist["pv"] or hist["cons"]):
        d.rectangle((px0, py0, px1, py1), outline=0, width=1)
        msg = "Verlauf nicht verfügbar" + (f": {err}" if err else "")
        d.text(((px0 + px1) / 2, (py0 + py1) / 2), msg[:50], font=font(16), fill=0, anchor="mm")
        return

    start, end = hist["start"], hist["end"]
    pv, cons, water = hist["pv"], hist["cons"], hist["water"]
    p_max = nice_ceil(max(v for _, v in pv + cons) if pv + cons else 1000)
    if water:
        t_min = math.floor(min(v for _, v in water) / 5) * 5
        t_max = max(math.ceil(max(v for _, v in water) / 5) * 5, t_min + 5)

    def X(t):
        return px0 + (t - start) / (end - start) * (px1 - px0)

    def YP(v):
        return py1 - v / p_max * (py1 - py0)

    def YT(v):
        return py1 - (v - t_min) / (t_max - t_min) * (py1 - py0)

    # Raster (gepunktet) und Skalen
    for f in (0, 0.5, 1):
        y = py1 - f * (py1 - py0)
        if f > 0:
            for xx in range(int(px0), int(px1), 6):
                d.point((xx, y), fill=0)
        pw = p_max * f
        lbl = "0" if pw == 0 else (f"{pw / 1000:g} kW" if p_max >= 1000 else f"{pw:g} W")
        d.text((px0 - 6, y), lbl, font=small, fill=0, anchor="rm")
        if water:
            d.text((px1 + 6, y), f"{t_min + f * (t_max - t_min):g}°", font=small,
                   fill=0, anchor="lm")
    d.line((px0, py1, px1, py1), fill=0, width=2)
    for hh in range(0, 25, 3):
        x = X(start + hh * 3600)
        d.line((x, py1, x, py1 + (6 if hh % 6 == 0 else 3)), fill=0, width=2)
        if hh % 6 == 0:
            d.text((x, py1 + 6), f"{hh:02d}", font=small, fill=0, anchor="mt")

    # PV: schraffierte Fläche mit kräftiger Kante
    pat = hatch((W, H))
    for seg in segments(pv):
        poly = [(X(t), YP(v)) for t, v in seg]
        if len(poly) < 2:
            continue
        mask = Image.new("L", (W, H), 0)
        ImageDraw.Draw(mask).polygon(poly + [(poly[-1][0], py1), (poly[0][0], py1)], fill=255)
        img.paste(pat, (0, 0), mask)
        d.line(poly, fill=0, width=2, joint="curve")
    # Verbrauch: durchgezogen
    for seg in segments(cons):
        pts = [(X(t), YP(v)) for t, v in seg]
        if len(pts) > 1:
            d.line(pts, fill=0, width=4, joint="curve")
    # Wassertemperatur: gestrichelt, rechte Skala
    for seg in segments(water):
        pts = [(X(t), YT(v)) for t, v in seg]
        if len(pts) > 1:
            dashed_line(d, pts, 3)

    # Jetzt-Markierung
    xn = X(min(time.time(), end))
    for yy in range(int(py0), int(py1), 4):
        d.line((xn, yy, xn, yy + 1), fill=0, width=1)


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


def draw_bus(d, box, deps, err):
    x0, y0, x1, y1 = box
    icon_bus(d, x0, y0 + 2, 30)
    d.text((x0 + 40, y0 + 2), "Bus", font=font(26, True), fill=0)
    if BUS_VIA_LABEL:
        d.text((x0, y0 + 40), f"→ {BUS_VIA_LABEL}", font=font(15, True), fill=0)
    if BUS_STATION:
        d.text((x0, y0 + 60), "ab " + BUS_STATION.split(",")[-1].strip(), font=font(14), fill=0)
    top = y0 + 92
    if not BUS_STATION and not USE_SAMPLE:
        for i, line in enumerate(("Haltestelle in .env", "eintragen:", "BUS_STATION=…")):
            d.text((x0, top + i * 22), line, font=font(15), fill=0)
        return
    if err or not deps:
        msg = "keine Abfahrten" if not err else "öV-Daten nicht erreichbar"
        d.text(((x0 + x1) / 2, top + 40), msg, font=font(15), fill=0, anchor="mm")
        return
    row = (y1 - top) / BUS_COUNT
    tf, lf, df = font(30, True), font(20, True), font(22, True)
    for i, dep in enumerate(deps):
        y = top + i * row
        cy = y + row / 2
        if i:
            for xx in range(int(x0), int(x1), 5):
                d.point((xx, y), fill=0)
        # Linie als schwarzes Schild
        d.rounded_rectangle((x0, cy - 17, x0 + 34, cy + 17), radius=6, fill=0)
        d.text((x0 + 17, cy), dep["line"], font=lf, fill=255, anchor="mm")
        d.text((x0 + 46, cy), datetime.fromtimestamp(dep["t"]).strftime("%H:%M"),
               font=tf, fill=0, anchor="lm")
        if dep["delay"]:
            d.text((x1, cy), f"+{dep['delay']}", font=df, fill=0, anchor="rm")


def render(now_d=None, hist=None, error=None, hist_err=None, bus=None, bus_err=None):
    img = Image.new("L", (W, H), 255)
    d = ImageDraw.Draw(img)
    m = 20
    split = 574                      # links Solar, rechts Bus
    lx0, lx1 = m, split - 16

    # Kopfzeile
    d.text((m, 12), "Solarmanager", font=font(22, True), fill=0)
    stamp = datetime.now().astimezone()
    date_txt = f"{WEEKDAYS[stamp.weekday()]} {stamp:%d.%m.  %H:%M}"
    d.text((W - m, 14), date_txt, font=font(19), fill=0, anchor="ra")
    pct = _device.get("battery")
    if pct is not None:   # Akku des Displays links neben dem Datum
        bx1 = W - m - d.textlength(date_txt, font=font(19)) - 24
        txt = f"{pct} %"
        d.text((bx1, 14), txt, font=font(19), fill=0, anchor="ra")
        bx1 -= d.textlength(txt, font=font(19)) + 8
        bx0, by0, by1 = bx1 - 34, 16, 32
        d.rectangle((bx0, by0, bx1 - 4, by1), outline=0, width=2)
        d.rectangle((bx1 - 3, by0 + 5, bx1, by1 - 5), fill=0)
        fill_w = round((bx1 - 4 - bx0 - 6) * pct / 100)
        if fill_w > 0:
            d.rectangle((bx0 + 3, by0 + 3, bx0 + 3 + fill_w, by1 - 3), fill=0)
    d.line((m, 44, W - m, 44), fill=0, width=3)
    d.line((split, 54, split, H - 12), fill=0, width=2)

    draw_bus(d, (split + 18, 56, W - m, H - 10), bus, bus_err)

    if error or now_d is None:
        cx = (lx0 + lx1) / 2
        d.text((cx, H // 2 - 14), "Solarmanager nicht erreichbar",
               font=font(26, True), fill=0, anchor="mm")
        d.text((cx, H // 2 + 22), str(error or "")[:52], font=font(15), fill=0, anchor="mm")
        return img

    # Oben: jetzt + heute
    yt = 56
    cols = (lx0, lx0 + 170, lx0 + 340)
    v, u = fmt_power(now_d["pW"])
    value_block(d, cols[0], yt, icon_sun, 36, "Produktion", v, u, 36, 13)
    v, u = fmt_power(now_d["cW"])
    value_block(d, cols[1], yt, icon_house, 36, "Verbrauch", v, u, 36, 13)
    v, u = fmt_energy(hist.get("today_wh") if hist else None)
    value_block(d, cols[2], yt, icon_today, 36, "Produktion heute", v, u, 36, 13)
    for c in cols[1:]:
        d.line((c - 10, yt + 4, c - 10, yt + 52), fill=0, width=1)

    # Mitte: Diagramm
    d.line((lx0, 120, lx1, 120), fill=0, width=1)
    draw_chart(img, d, (lx0, 128, lx1, 404), hist, hist_err)
    d.line((lx0, 408, lx1, 408), fill=0, width=1)

    # Unten: Wärmepumpe
    hp = now_d.get("hp")
    yb = 416
    if hp:
        v, u = fmt_temp(hp.get("outside"))
        value_block(d, lx0, yb, icon_thermo, 32, "Aussen", v, u, 28, 12)
        ic, label = heatpump_state(hp)
        value_block(d, lx0 + 150, yb, ic, 32, "Wärmepumpe", label, "",
                    28 if len(label) <= 8 else 24, 12)
        v, u = fmt_temp(hp.get("water"))
        value_block(d, lx0 + 375, yb, icon_drop, 32, "Wasser", v, u, 28, 12)
    else:
        d.text(((lx0 + lx1) / 2, yb + 24), "Keine Wärmepumpe im Datenstrom",
               font=font(16), fill=0, anchor="mm")
    return img


def image_bytes(img):
    one_bit = img.convert("1", dither=Image.Dither.NONE)
    buf = io.BytesIO()
    if IMAGE_FORMAT == "bmp":
        one_bit.save(buf, format="BMP")
        return buf.getvalue(), "image/bmp"
    one_bit.save(buf, format="PNG", bits=1)
    return buf.getvalue(), "image/png"


def current_image():
    bus, bus_err = None, None
    try:
        bus = get_bus()
    except Exception as e:  # Bus ist unabhängig von der Solaranzeige
        bus_err = str(e)
        print(f"[{time.strftime('%H:%M:%S')}] Busdaten fehlgeschlagen: {e}", file=sys.stderr)
    try:
        now_d, hist, hist_err = get_data()
        return render(now_d, hist, hist_err=hist_err, bus=bus, bus_err=bus_err)
    except Exception as e:
        print(f"[{time.strftime('%H:%M:%S')}] Datenabruf fehlgeschlagen: {e}",
              file=sys.stderr)
        return render(error=e, bus=bus, bus_err=bus_err)


# ---- Server ----------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    def _send(self, body, ctype="application/json", code=200):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(json.dumps(obj).encode(), "application/json", code)

    def _image_url(self):
        host = self.headers.get("Host") or f"localhost:{PORT}"
        ext = "bmp" if IMAGE_FORMAT == "bmp" else "png"
        name = f"solar-{int(time.time())}"
        return f"http://{host}/image/{name}.{ext}", name

    def do_GET(self):
        # Firmware fragt teils mit Schrägstrich am Ende (/api/setup/)
        path = self.path.split("?")[0].rstrip("/") or "/"
        if path == "/api/setup":
            url, name = self._image_url()
            self._json({"status": 200, "api_key": "local-solarmanager",
                        "friendly_id": "SOLAR", "image_url": url,
                        "filename": name})
        elif path == "/api/display":
            self._remember_device()
            url, name = self._image_url()
            self._json({"status": 0, "image_url": url, "filename": name,
                        "refresh_rate": REFRESH_SECONDS,
                        "reset_firmware": False, "update_firmware": False,
                        "firmware_url": None, "special_function": ""})
        elif path.startswith("/image/"):
            body, ctype = image_bytes(current_image())
            self._send(body, ctype)
        elif path == "/":
            html = ("<!doctype html><meta charset=utf-8><title>Solarmanager</title>"
                    "<body style='background:#e9e9e6;display:grid;place-items:center;"
                    "min-height:100vh;margin:0'>"
                    "<img src='/image/preview.png' width=800 height=480 "
                    "style='background:#fff;box-shadow:0 8px 30px #0003'>"
                    "<script>setTimeout(()=>location.reload(),30000)</script>")
            self._send(html.encode(), "text/html; charset=utf-8")
        else:
            self._send(b"{}", "application/json", 404)

    def _remember_device(self):
        """Akku, WLAN und Firmware aus den Headern des Geräts merken."""
        h = self.headers
        volts = num(h.get("Battery-Voltage"))
        pct = num(h.get("Percent-Charged"))
        if pct is None:
            pct = battery_percent(volts)
        if volts is None and pct is None:
            return  # z. B. Browser-Vorschau
        if "emu" in (h.get("FW-Version") or ""):
            return  # trmnl_emulator.py soll den echten Akkustand nicht überschreiben
        _device.update(volts=volts, battery=int(pct) if pct is not None else None,
                       rssi=h.get("RSSI"), fw=h.get("FW-Version"), ts=time.time())
        print(f"[{time.strftime('%H:%M:%S')}] Gerät: Akku {volts} V ≈ {_device['battery']} %, "
              f"RSSI {_device['rssi']}, FW {_device['fw']}")

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        if self.path.split("?")[0].rstrip("/") == "/api/log" and body:
            print(f"[{time.strftime('%H:%M:%S')}] Geräte-Log: "
                  f"{body[:600].decode('utf-8', 'replace')}")
        self._json({})  # Antwort wird vom Gerät ignoriert

    def log_message(self, fmt, *args):
        print(f"[{time.strftime('%H:%M:%S')}] {self.client_address[0]} {fmt % args}")


def run_test():
    """Ruft die Daten einmal ab und zeigt Rohdaten + erkannte Werte."""
    try:
        now_d, raw = fetch_now()
    except Exception as e:
        print(f"FEHLER: {e}", file=sys.stderr)
        return 1
    print("Rohdaten (Stream):")
    print(json.dumps(raw, indent=2, ensure_ascii=False)[:3000])
    print("\nErkannt:", {k: v for k, v in now_d.items() if k != "hp"})
    print("Wärmepumpe:", now_d["hp"])
    try:
        h = fetch_history((now_d.get("hp") or {}).get("id"))
        print(f"Verlauf heute: {len(h['pv'])} PV-, {len(h['cons'])} Verbrauchs-, "
              f"{len(h['water'])} Temperaturpunkte, PV heute {h['today_wh']} Wh")
    except Exception as e:
        print(f"Verlauf FEHLER: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true",
                    help="Zugangsdaten testen und Rohdaten anzeigen")
    ap.add_argument("--preview", action="store_true",
                    help="nur preview.png schreiben und beenden")
    ap.add_argument("--sample", action="store_true",
                    help="Beispieldaten statt echter Daten (mit --preview oder im Serverbetrieb)")
    args = ap.parse_args()
    USE_SAMPLE = args.sample

    if args.test:
        sys.exit(run_test())

    if args.preview:
        current_image().convert("1", dither=Image.Dither.NONE).save("preview.png")
        print("preview.png geschrieben")
        sys.exit(0)

    quelle = "Beispieldaten" if USE_SAMPLE else (
        f"Cloud ({SM_ID})" if SM_SOURCE == "cloud" else f"Gateway {SM_IP}")
    print(f"Server läuft auf http://0.0.0.0:{PORT}  (Browser-Vorschau: http://localhost:{PORT}/)")
    print(f"Quelle: {quelle} · Bild alle {REFRESH_SECONDS} s · Ctrl+C beendet")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
