"""
Einstellungen: Standardwerte, Laden, Prüfen und Speichern von config.json.

config.json liegt neben dem Server (oder CONFIG_PATH) und enthält auch den API-Key,
deshalb steht sie in .gitignore und wird mit Rechten 600 geschrieben.
Fehlt die Datei, gelten die Standardwerte, ergänzt um Werte aus der Umgebung (.env).
"""

import copy
import json
import os
import re
import threading

CONFIG_PATH = os.environ.get(
    "CONFIG_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json"))
_lock = threading.Lock()

ICONS = ["auto", "none", "sun", "house", "today", "thermo", "drop", "flame", "shower",
         "heatpump", "bolt", "grid", "battery", "car", "charger", "plug", "bus"]

# Vorlage für Zustands-Kacheln der Wärmepumpe (operationState, an einer Anlage beobachtet)
HEATPUMP_STATES = [
    {"value": 1, "text": "Standby", "icon": "heatpump"},
    {"value": 2, "text": "Heizen", "icon": "flame"},
    {"value": 3, "text": "Warmwasser", "icon": "shower"},
]
FORMATS = ["power", "energy", "number", "state"]
SIZES = ["s", "m", "l"]
AREAS = ["top", "bottom", "off"]
STYLES = ["area", "line", "thin", "dash", "dot"]
AXES = ["left", "right"]


def _env(name, default=""):
    return os.environ.get(name, default)


def _int(v, default, lo=None, hi=None):
    try:
        v = int(float(v))
    except (TypeError, ValueError):
        return default
    if lo is not None:
        v = max(lo, v)
    if hi is not None:
        v = min(hi, v)
    return v


def defaults():
    """Standard: entspricht der Anzeige vor Einführung der Web-Konfiguration."""
    hp = "type=heatpump"
    return {
        "version": 1,
        "solarmanager": {
            "source": _env("SM_SOURCE", "cloud").lower(),
            "sm_id": _env("SM_ID"),
            "api_key": _env("SM_API_KEY"),
            "gateway_ip": _env("SM_IP"),
            "cloud_url": _env("SM_CLOUD_URL", "https://cloud.solar-manager.ch"),
        },
        "display": {
            "title": "Solarmanager",
            "theme": "light",
            "show_date": True,
            "show_battery": True,
            "image_format": _env("IMAGE_FORMAT", "png").lower(),
            "refresh_s": _int(_env("REFRESH_SECONDS", "300"), 300, 60),
            "night_enabled": False,
            "night_from": "23:00",
            "night_to": "06:00",
            "night_refresh_s": 3600,
        },
        "bus": {
            "enabled": True,
            "position": "right",
            "width": "narrow",
            "station": _env("BUS_STATION"),
            "lines": [s.strip() for s in _env("BUS_LINES").split(",") if s.strip()],
            "via": _env("BUS_VIA"),
            "via_label": _env("BUS_VIA_LABEL"),
            "count": _int(_env("BUS_COUNT", "5"), 5, 1, 8),
        },
        "tiles": [
            tile("top", "stream:pW", "Produktion", "sun", "power", size="m"),
            tile("top", "stream:cW", "Verbrauch", "house", "power", size="m"),
            tile("top", "today:pWh", "Produktion heute", "today", "energy", size="m"),
            tile("bottom", f"device:{hp}:temperatureOutside", "Aussen", "thermo", "number",
                 "°C", 1, "s"),
            tile("bottom", f"device:{hp}:operationState", "Wärmepumpe", "auto", "state",
                 size="s", states=HEATPUMP_STATES),
            tile("bottom", f"device:{hp}:temperature", "Wasser", "drop", "number", "°C", 1, "s"),
        ],
        "chart": {
            "enabled": True,
            "range": "today",
            "series": [
                series("range:pW", "PV", "area", "left", "power"),
                series("range:cW", "Verbrauch", "line", "left", "power"),
                series(f"devrange:{hp}:temperature", "Wasser", "dash", "right", "number", "°"),
            ],
        },
    }


def tile(area, source, label, icon, fmt, unit="", decimals=1, size="m", states=None):
    return {"area": area, "source": source, "label": label, "icon": icon, "format": fmt,
            "unit": unit, "decimals": decimals, "size": size,
            "states": copy.deepcopy(states or [])}


def _states(raw, fmt):
    """Zustandstexte einer Kachel: [{value, text, icon}]."""
    if raw is None:
        # ältere Einstellungen ohne Zustandsliste: bisheriges Verhalten (Wärmepumpe)
        return copy.deepcopy(HEATPUMP_STATES) if fmt == "state" else []
    out, seen = [], set()
    for e in raw if isinstance(raw, list) else []:
        if not isinstance(e, dict):
            continue
        v = _int(e.get("value"), None, -9999, 99999)
        if v is None or v in seen:
            continue
        seen.add(v)
        out.append({"value": v, "text": _text(e.get("text", ""), "", 20),
                    "icon": _choice(e.get("icon"), [i for i in ICONS if i != "auto"], "none")})
    return out[:16]


def series(source, label, style, axis, fmt, unit=""):
    return {"source": source, "label": label, "style": style, "axis": axis,
            "format": fmt, "unit": unit}


def _time(v, default):
    return v if isinstance(v, str) and re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", v) else default


def _choice(v, options, default):
    return v if v in options else default


def _text(v, default="", maxlen=80):
    return str(v)[:maxlen] if isinstance(v, (str, int, float)) else default


def sanitize(raw):
    """Prüft eine (vom Browser gesendete) Konfiguration und ergänzt fehlende Werte."""
    d = defaults()
    raw = raw if isinstance(raw, dict) else {}

    sm_in, sm = raw.get("solarmanager") or {}, d["solarmanager"]
    sm["source"] = _choice(sm_in.get("source"), ["cloud", "local"], sm["source"])
    for k in ("sm_id", "api_key", "gateway_ip", "cloud_url"):
        if k in sm_in:
            sm[k] = _text(sm_in[k], sm[k], 200).strip()

    di, dd = raw.get("display") or {}, d["display"]
    dd["title"] = _text(di.get("title", dd["title"]), dd["title"], 40)
    dd["theme"] = _choice(di.get("theme"), ["light", "dark"], dd["theme"])
    for k in ("show_date", "show_battery", "night_enabled"):
        if k in di:
            dd[k] = bool(di[k])
    dd["image_format"] = _choice(di.get("image_format"), ["png", "bmp"], dd["image_format"])
    dd["refresh_s"] = _int(di.get("refresh_s"), dd["refresh_s"], 60, 86400)
    dd["night_refresh_s"] = _int(di.get("night_refresh_s"), dd["night_refresh_s"], 60, 86400)
    dd["night_from"] = _time(di.get("night_from"), dd["night_from"])
    dd["night_to"] = _time(di.get("night_to"), dd["night_to"])

    bi, bd = raw.get("bus") or {}, d["bus"]
    if "enabled" in bi:
        bd["enabled"] = bool(bi["enabled"])
    bd["position"] = _choice(bi.get("position"), ["right", "left"], bd["position"])
    bd["width"] = _choice(bi.get("width"), ["narrow", "wide"], bd["width"])
    for k in ("station", "via", "via_label"):
        if k in bi:
            bd[k] = _text(bi[k], bd[k]).strip()
    if isinstance(bi.get("lines"), list):
        bd["lines"] = [_text(x, "", 10).strip() for x in bi["lines"] if _text(x, "").strip()][:20]
    bd["count"] = _int(bi.get("count"), bd["count"], 1, 8)

    if isinstance(raw.get("tiles"), list):
        tiles = []
        for t in raw["tiles"][:12]:
            if not isinstance(t, dict) or not t.get("source"):
                continue
            fmt = _choice(t.get("format"), FORMATS, "number")
            tiles.append({
                "area": _choice(t.get("area"), AREAS, "top"),
                "source": _text(t["source"], "", 120),
                "label": _text(t.get("label", ""), "", 30),
                "icon": _choice(t.get("icon"), ICONS, "none"),
                "format": fmt,
                "unit": _text(t.get("unit", ""), "", 8),
                "decimals": _int(t.get("decimals"), 1, 0, 3),
                "size": _choice(t.get("size"), SIZES, "m"),
                "states": _states(t.get("states"), fmt),
            })
        d["tiles"] = tiles

    ci, cd = raw.get("chart") or {}, d["chart"]
    if "enabled" in ci:
        cd["enabled"] = bool(ci["enabled"])
    cd["range"] = _choice(ci.get("range"), ["today", "24h"], cd["range"])
    if isinstance(ci.get("series"), list):
        out = []
        for s in ci["series"][:6]:
            if not isinstance(s, dict) or not s.get("source"):
                continue
            out.append({
                "source": _text(s["source"], "", 120),
                "label": _text(s.get("label", ""), "", 24),
                "style": _choice(s.get("style"), STYLES, "line"),
                "axis": _choice(s.get("axis"), AXES, "left"),
                "format": _choice(s.get("format"), ["power", "energy", "number"], "number"),
                "unit": _text(s.get("unit", ""), "", 8),
            })
        cd["series"] = out
    return d


def load():
    """Gespeicherte Konfiguration (geprüft) oder Standardwerte."""
    with _lock:
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                return sanitize(json.load(f))
        except FileNotFoundError:
            return defaults()
        except (OSError, ValueError) as e:
            print(f"config.json nicht lesbar ({e}), verwende Standardwerte")
            return defaults()


def save(cfg):
    cfg = sanitize(cfg)
    with _lock:
        tmp = CONFIG_PATH + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        os.replace(tmp, CONFIG_PATH)
    return cfg


def public_view(cfg):
    """Für den Browser: API-Key nicht im Klartext ausliefern."""
    out = copy.deepcopy(cfg)
    key = out["solarmanager"].pop("api_key", "")
    out["solarmanager"]["api_key"] = ""
    out["solarmanager"]["api_key_hint"] = ("…" + key[-4:]) if key else ""
    return out


def merge_secret(new, current):
    """Leeres API-Key-Feld aus dem Browser heisst: gespeicherten Key behalten."""
    new = new if isinstance(new, dict) else {}
    sm = new.setdefault("solarmanager", {})
    if not sm.get("api_key"):
        sm["api_key"] = current["solarmanager"]["api_key"]
    return new
