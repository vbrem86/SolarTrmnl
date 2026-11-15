"""
Daten: Solar Manager (Cloud-API v3 oder Gateway), öV-Abfahrten, Beispieldaten.

Quellen-Schlüssel (in den Einstellungen):
    stream:<feld>               aktueller Wert der Anlage, z. B. stream:pW
    device:<ref>:<feld>         aktueller Wert eines Geräts, z. B. device:type=heatpump:temperature
    today:<feld>                Summe seit Mitternacht aus dem Verlauf, z. B. today:pWh
    range:<feld>                Verlauf der Anlage (Diagramm)
    devrange:<ref>:<feld>       Verlauf eines Geräts (Diagramm)
<ref> ist die Geräte-ID oder type=<typ> (erstes Gerät dieses Typs, z. B. heatpump).
"""

import json
import math
import random
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

USE_SAMPLE = False

STREAM_CACHE_S = 30        # Cloud-Limit: 1000 Stream-Abfragen pro Stunde
RANGE_CACHE_S = 5 * 60     # Verlauf hat 15-min-Auflösung
DEVICES_CACHE_S = 60 * 60
BUS_CACHE_S = 60
BUS_API = "https://transport.opendata.ch/v1"

# Bekannte Feldnamen (für das Menü)
FIELD_NAMES = {
    "pW": "PV-Leistung", "cW": "Verbrauch", "iW": "Netzbezug", "eW": "Einspeisung",
    "bcW": "Batterie laden", "bdW": "Batterie entladen", "soc": "Batterie-Ladestand",
    "pWh": "PV-Energie", "cWh": "Verbrauch (Energie)", "iWh": "Netzbezug (Energie)",
    "eWh": "Einspeisung (Energie)", "bcWh": "Batterie geladen", "bdWh": "Batterie entladen (Energie)",
    "scWh": "Eigenverbrauch", "cPvWh": "Verbrauch aus PV", "cOtherW": "Übriger Verbrauch",
    "temperature": "Temperatur (Warmwasser)", "temperatureOutside": "Aussentemperatur",
    "operationState": "Betriebszustand", "power": "Leistung", "activeDevice": "Aktiv",
    "mode": "Modus", "targetPower": "Zielleistung", "targetPercent": "Zielwert %",
    "iWhTotal": "Zählerstand Bezug", "eWhTotal": "Zählerstand Einspeisung",
    "heatingAdjustment": "Heizanpassung", "limitType": "Begrenzung",
}
_SKIP = {"t", "v", "iv", "fw", "_id", "signal"}

_cache = {}


def clear_cache():
    _cache.clear()


def _cached(key, ttl, fn):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    value = fn()
    _cache[key] = (time.time(), value)
    return value


# ---- Hilfen ------------------------------------------------------------------
def num(value, default=None):
    if isinstance(value, bool):
        return float(value)
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


def midnight(ts=None):
    d = datetime.fromtimestamp(ts if ts is not None else time.time()).astimezone()
    return d.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


def chart_window(cfg):
    """(Start, Ende) des Diagramms: heute 00–24 Uhr oder die letzten 24 Stunden."""
    if cfg["chart"]["range"] == "24h":
        end = time.time()
        return end - 86400, end
    start = midnight()
    return start, start + 86400


def _numeric_fields(obj):
    return {k: v for k, v in obj.items()
            if k not in _SKIP and num(v) is not None and not isinstance(v, (dict, list))}


def _http_json(url, headers, timeout=15):
    req = urllib.request.Request(url, headers=dict(headers, Accept="application/json"))
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


# ---- Solar Manager -------------------------------------------------------------
def _sm_key(cfg):
    sm = cfg["solarmanager"]
    return (sm["source"], sm["sm_id"], sm["api_key"], sm["gateway_ip"], sm["cloud_url"])


def cloud_get(cfg, path):
    sm = cfg["solarmanager"]
    if not sm["sm_id"] or not sm["api_key"]:
        raise RuntimeError("smId / API-Key fehlen (Einstellungen unter /config)")
    try:
        return _http_json(sm["cloud_url"].rstrip("/") + path, {"X-API-KEY": sm["api_key"]})
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise RuntimeError("API-Schlüssel ungültig (ohne 'Erneuerung erlauben' erstellen)")
        if e.code == 429:
            raise RuntimeError("Zu viele Abfragen (HTTP 429)")
        raise RuntimeError(f"HTTP {e.code} bei {path.split('?')[0]}")


def get_stream(cfg):
    if USE_SAMPLE:
        return sample_stream()
    sm = cfg["solarmanager"]

    def fetch():
        if sm["source"] == "local":
            if not sm["gateway_ip"]:
                raise RuntimeError("Gateway-IP fehlt (Einstellungen unter /config)")
            return _http_json(f"http://{sm['gateway_ip']}/v2/point",
                              {"X-API-Key": sm["api_key"]}, timeout=8)
        return cloud_get(cfg, f"/v3/users/{sm['sm_id']}/data/stream")
    return _cached(("stream",) + _sm_key(cfg), STREAM_CACHE_S, fetch)


def _guess_type(dev):
    if "operationState" in dev or "temperatureOutside" in dev:
        return "heatpump"
    return "device"


def get_devices(cfg):
    """[{id, type, name, model}] – Namen aus der Cloud, sonst aus dem Stream geraten."""
    if USE_SAMPLE:
        return sample_devices()
    sm = cfg["solarmanager"]

    def from_stream():
        out = []
        for d in get_stream(cfg).get("devices") or []:
            if isinstance(d, dict) and d.get("_id"):
                t = _guess_type(d)
                out.append({"id": d["_id"], "type": t,
                            "name": "Wärmepumpe" if t == "heatpump" else f"Gerät …{d['_id'][-4:]}",
                            "model": ""})
        return out

    def fetch():
        if sm["source"] != "cloud":
            return from_stream()
        try:
            raw = cloud_get(cfg, f"/v3/users/{sm['sm_id']}/devices")
        except Exception:
            return from_stream()
        out = []
        for d in raw if isinstance(raw, list) else []:
            tag = d.get("tag")
            name = tag if isinstance(tag, str) and tag else (tag or {}).get("name") \
                if isinstance(tag, dict) else None
            out.append({"id": d.get("_id"), "type": str(d.get("type") or "device").lower(),
                        "name": name or d.get("deviceKey") or d.get("type") or d.get("_id"),
                        "model": d.get("deviceKey") or ""})
        return out
    return _cached(("devices",) + _sm_key(cfg), DEVICES_CACHE_S, fetch)


def resolve_device(cfg, ref):
    if not ref.startswith("type="):
        return ref
    want = ref[5:].lower()
    try:
        for d in get_devices(cfg):
            if d["type"] == want:
                return d["id"]
    except Exception:
        pass
    for d in get_stream(cfg).get("devices") or []:   # Rückfall ohne Geräteliste
        if isinstance(d, dict) and _guess_type(d) == want:
            return d.get("_id")
    return None


def _range_start(start):
    return int(start // 900 * 900)   # auf 15 min runden, damit der Zwischenspeicher greift


def get_range(cfg, start):
    """Verlauf der Anlage ab start bis jetzt (Liste der Rohdaten-Objekte)."""
    start = _range_start(start)
    if USE_SAMPLE:
        return sample_range(start)
    sm = cfg["solarmanager"]
    if sm["source"] != "cloud":
        return []

    def fetch():
        q = urllib.parse.urlencode({"from": iso_utc(start), "to": iso_utc(time.time()),
                                    "interval": 900})
        raw = cloud_get(cfg, f"/v3/users/{sm['sm_id']}/data/range?{q}")
        return (raw.get("data") if isinstance(raw, dict) else raw) or []
    return _cached(("range", start) + _sm_key(cfg), RANGE_CACHE_S, fetch)


def get_devrange(cfg, dev_id, start):
    start = _range_start(start)
    if USE_SAMPLE:
        return sample_devrange(dev_id, start)
    if cfg["solarmanager"]["source"] != "cloud" or not dev_id:
        return []

    def fetch():
        q = urllib.parse.urlencode({"from": iso_utc(start), "to": iso_utc(time.time()),
                                    "interval": 900})
        raw = cloud_get(cfg, f"/v3/devices/{dev_id}/data/range?{q}")
        return (raw.get("data") if isinstance(raw, dict) else raw) or []
    return _cached(("devrange", dev_id, start) + _sm_key(cfg), RANGE_CACHE_S, fetch)


def _split_device(rest):
    ref, _, field = rest.rpartition(":")
    return ref, field


def point_value(cfg, source):
    """Aktueller Wert einer Quelle (oder None)."""
    kind, _, rest = source.partition(":")
    if kind == "stream":
        return num(get_stream(cfg).get(rest))
    if kind == "device":
        ref, field = _split_device(rest)
        dev_id = resolve_device(cfg, ref)
        for d in get_stream(cfg).get("devices") or []:
            if isinstance(d, dict) and d.get("_id") == dev_id:
                return num(d.get(field))
        return None
    if kind == "today":
        vals = [num(o.get(rest)) for o in get_range(cfg, midnight()) if isinstance(o, dict)]
        vals = [v for v in vals if v is not None]
        return sum(vals) if vals else None
    return None


def series_points(cfg, source, start, end):
    kind, _, rest = source.partition(":")
    if kind == "range":
        rows, field = get_range(cfg, start), rest
    elif kind == "devrange":
        ref, field = _split_device(rest)
        rows = get_devrange(cfg, resolve_device(cfg, ref), start)
    else:
        return []
    pts = []
    for o in rows:
        if not isinstance(o, dict):
            continue
        t, v = parse_time(o.get("t")), num(o.get(field))
        if t is not None and v is not None and start <= t <= end:
            pts.append((t, v))
    return sorted(pts)


def is_configured(cfg):
    """Sind die Zugangsdaten zum Solar Manager eingetragen?"""
    if USE_SAMPLE:
        return True
    sm = cfg["solarmanager"]
    if sm["source"] == "local":
        return bool(sm["gateway_ip"])
    return bool(sm["sm_id"] and sm["api_key"])


def collect(cfg):
    """Alle Werte für ein Bild. Fehler werden pro Bereich gesammelt, nicht geworfen."""
    view = {"error": None, "tiles": [], "series": [], "chart_err": None,
            "window": chart_window(cfg), "bus": None, "bus_err": None,
            "setup": not is_configured(cfg)}
    if view["setup"]:
        return view   # Einrichtungsseite statt Daten
    try:
        get_stream(cfg)
    except Exception as e:
        view["error"] = str(e)
    if not view["error"]:
        for t in cfg["tiles"]:
            if t["area"] == "off":
                continue
            try:
                v = point_value(cfg, t["source"])
            except Exception:
                v = None
            view["tiles"].append((t, v))
        if cfg["chart"]["enabled"]:
            start, end = view["window"]
            for s in cfg["chart"]["series"]:
                try:
                    pts = series_points(cfg, s["source"], start, end)
                except Exception as e:
                    view["chart_err"] = str(e)
                    pts = []
                view["series"].append((s, pts))
    if cfg["bus"]["enabled"]:
        try:
            view["bus"] = get_bus(cfg)
        except Exception as e:
            view["bus_err"] = str(e)
    return view


def discover(cfg):
    """Alle Felder, die die Anlage liefert – für die Auswahl im Menü."""
    stream = get_stream(cfg)
    try:
        devices = get_devices(cfg)
    except Exception:
        devices = []
    stream_devs = {d.get("_id"): d for d in stream.get("devices") or [] if isinstance(d, dict)}
    types = [d["type"] for d in devices]
    try:
        rows = get_range(cfg, midnight())
    except Exception:
        rows = []
    range_keys = sorted({k for o in rows if isinstance(o, dict) for k in _numeric_fields(o)})
    out_devs = []
    for d in devices:
        cur = _numeric_fields(stream_devs.get(d["id"], {}))
        try:
            hist_rows = get_devrange(cfg, d["id"], midnight())
        except Exception:
            hist_rows = []
        hist = sorted({k for o in hist_rows if isinstance(o, dict) for k in _numeric_fields(o)})
        ref = f"type={d['type']}" if types.count(d["type"]) == 1 and d["type"] != "device" \
            else d["id"]
        out_devs.append({"ref": ref, "id": d["id"], "name": d["name"], "type": d["type"],
                         "model": d["model"],
                         "fields": [{"key": k, "value": v} for k, v in sorted(cur.items())],
                         "hist": hist})
    return {
        "stream": [{"key": k, "value": v} for k, v in sorted(_numeric_fields(stream).items())],
        "today": [k for k in range_keys if k.endswith("Wh")],
        "range": range_keys,
        "devices": out_devs,
        "names": FIELD_NAMES,
    }


def test_connection(cfg):
    stream = get_stream(cfg)
    msg = f"Verbindung ok: {len(_numeric_fields(stream))} Werte"
    msg += f", {len(stream.get('devices') or [])} Geräte"
    if cfg["solarmanager"]["source"] == "cloud":
        msg += f", {len(get_range(cfg, midnight()))} Verlaufspunkte heute"
    return msg


# ---- Bus (transport.opendata.ch) -----------------------------------------------
def _stationboard(station, limit=40):
    q = urllib.parse.urlencode({"station": station, "limit": limit})
    return _http_json(f"{BUS_API}/stationboard?{q}", {}, timeout=10)


def fetch_bus(cfg):
    b = cfg["bus"]
    raw = _stationboard(b["station"])
    deps = []
    for e in raw.get("stationboard") or []:
        line = str(e.get("number", "")).strip()
        if b["lines"] and line not in b["lines"]:
            continue
        stops = [((p.get("station") or {}).get("name") or "") for p in e.get("passList") or []]
        if b["via"] and not any(n.startswith(b["via"]) for n in stops[1:]):
            continue
        st = e.get("stop") or {}
        ts = num(st.get("departureTimestamp"))
        if ts is None:
            continue
        delay = num(st.get("delay"))
        deps.append({"line": line, "t": ts, "delay": int(delay) if delay is not None else None,
                     "to": e.get("to", "")})
    return sorted(deps, key=lambda d: d["t"])


def get_bus(cfg):
    """Nächste Abfahrten (abgefahrene ausgeblendet). None = keine Haltestelle eingestellt."""
    b = cfg["bus"]
    if USE_SAMPLE:
        deps = sample_bus(b["count"])
    elif not b["station"]:
        return None
    else:
        key = ("bus", b["station"], tuple(b["lines"]), b["via"])
        deps = _cached(key, BUS_CACHE_S, lambda: fetch_bus(cfg))
    now = time.time()
    return [d for d in deps if d["t"] + (d["delay"] or 0) * 60 > now - 20][:b["count"]]


def search_stations(query):
    if len(query.strip()) < 2:
        return []

    def fetch():
        q = urllib.parse.urlencode({"query": query, "type": "station"})
        raw = _http_json(f"{BUS_API}/locations?{q}", {}, timeout=10)
        return [s["name"] for s in raw.get("stations") or [] if s.get("name") and s.get("id")][:10]
    return _cached(("stations", query.strip().lower()), 3600, fetch)


def station_info(station):
    """Linien und mögliche Richtungen (Halte nach der Haltestelle) für das Menü."""
    def fetch():
        raw = _stationboard(station, 60)
        lines, stops = set(), {}
        for e in raw.get("stationboard") or []:
            line = str(e.get("number", "")).strip()
            if line:
                lines.add(line)
            seen = set()
            for p in (e.get("passList") or [])[1:]:
                name = (p.get("station") or {}).get("name")
                if not name or name in seen:
                    continue
                seen.add(name)
                s = stops.setdefault(name, {"name": name, "count": 0, "lines": set()})
                s["count"] += 1
                s["lines"].add(line)
        key = lambda x: (len(x), x)   # 2 vor 10
        out = sorted(stops.values(), key=lambda s: (-s["count"], s["name"]))[:60]
        return {"station": (raw.get("station") or {}).get("name") or station,
                "lines": sorted(lines, key=key),
                "stops": [{"name": s["name"], "count": s["count"],
                           "lines": sorted(s["lines"], key=key)} for s in out]}
    return _cached(("stationinfo", station), 600, fetch)


# ---- Beispieldaten (--sample) ----------------------------------------------------
def _sample_at(t):
    lt = datetime.fromtimestamp(t)
    h = lt.hour + lt.minute / 60
    rnd = random.Random(int(t // 900))
    sun = max(0.0, math.sin(math.pi * (h - 7.5) / 9.5)) if 7.5 < h < 17 else 0.0
    pv = max(0.0, 5200 * sun ** 1.4 * (0.75 + 0.25 * math.sin(h * 2.3) + rnd.uniform(-0.1, 0.1)))
    heating = 6 <= h < 8 or 12 <= h < 14 or 18.5 <= h < 19.5
    cons = 350 + rnd.uniform(0, 250) + (1800 if heating else 0) \
        + (900 if 11.5 <= h < 12.5 or 18 <= h < 19 else 0)
    water = 50 + 5 * math.sin(2 * math.pi * (h - 9) / 24) + (3 if heating else 0)
    state = 3 if heating and h > 11 else (2 if heating else 1)
    return pv, cons, water, state


def sample_stream():
    now = time.time()
    pv, cons, water, state = _sample_at(now)
    return {"t": iso_utc(now), "pW": round(pv), "cW": round(cons),
            "iW": round(max(0, cons - pv)), "eW": round(max(0, pv - cons)), "soc": 64,
            "devices": [
                {"_id": "sample-hp", "temperature": round(water, 1), "temperatureOutside": 6.4,
                 "operationState": state},
                {"_id": "sample-inv", "power": round(pv)},
            ]}


def sample_devices():
    return [{"id": "sample-hp", "type": "heatpump", "name": "Wärmepumpe", "model": "Beispiel"},
            {"id": "sample-inv", "type": "inverter", "name": "Wechselrichter", "model": "Beispiel"}]


def sample_range(start):
    out, t, now = [], start, time.time()
    while t <= now:
        pv, cons, _, _ = _sample_at(t)
        out.append({"t": iso_utc(t), "pW": pv, "cW": cons, "pWh": pv / 4, "cWh": cons / 4,
                    "iWh": max(0, cons - pv) / 4, "eWh": max(0, pv - cons) / 4})
        t += 900
    return out


def sample_devrange(dev_id, start):
    out, t, now = [], start, time.time()
    while t <= now:
        pv, _, water, state = _sample_at(t)
        if dev_id == "sample-hp":
            out.append({"t": iso_utc(t), "temperature": water, "temperatureOutside": 6.4,
                        "operationState": state})
        else:
            out.append({"t": iso_utc(t), "power": pv})
        t += 900
    return out


def sample_bus(count):
    now = time.time()
    base = now - now % 900 + 6 * 60
    delays = [2, 0, 1, None, None, None]
    return [{"line": "6" if i % 2 == 0 else "2", "t": base + i * 900,
             "delay": delays[i % 6], "to": ""} for i in range(count + 1)]
