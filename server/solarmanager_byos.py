#!/usr/bin/env python3
"""
Solarmanager -> TRMNL, eigener Server (BYOS), ohne TRMNL-Konto

Kleiner eigener TRMNL-Server für das Heimnetz (z. B. Raspberry Pi). Das TRMNL-Gerät
fragt ihn statt der TRMNL-Cloud ab. Der Server holt die Daten vom Solar Manager
(und optional öV-Abfahrten) und liefert ein fertig gezeichnetes 800x480-Bild (1 Bit).

Einstellungen im Browser:  http://<IP-dieses-Rechners>:8080/config
Vorschau im Browser:       http://<IP-dieses-Rechners>:8080/

Start:
    python3 solarmanager_byos.py              (Einstellungen aus config.json bzw. .env)
    python3 solarmanager_byos.py --sample     (Beispieldaten, ohne Zugangsdaten)
    python3 solarmanager_byos.py --test       (Verbindung prüfen, Rohdaten zeigen)
    python3 solarmanager_byos.py --preview    (nur preview.png schreiben)

Umgebungsvariablen (nur Server): PORT, CONFIG_PATH, CONFIG_PASSWORD.
Alle anderen Einstellungen über /config; ohne config.json gelten SM_ID, SM_API_KEY,
BUS_STATION usw. aus der Umgebung als Startwerte (siehe .env.example).

Module: sm_config (Einstellungen), sm_data (Daten), sm_render (Bild), config.html (Menü).
"""

import argparse
import base64
import hmac
import json
import os
import socket
import sys
import time
import urllib.parse
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import sm_config
import sm_data
import sm_render

PORT = int(os.environ.get("PORT", "8080"))
CONFIG_PASSWORD = os.environ.get("CONFIG_PASSWORD", "")
HERE = os.path.dirname(os.path.abspath(__file__))

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


def refresh_seconds(cfg, now=None):
    """Aufwach-Intervall; im Nachtfenster das längere Nacht-Intervall."""
    disp = cfg["display"]
    if not disp["night_enabled"]:
        return disp["refresh_s"]
    now = now or datetime.now()
    cur = now.hour * 60 + now.minute
    f = int(disp["night_from"][:2]) * 60 + int(disp["night_from"][3:])
    t = int(disp["night_to"][:2]) * 60 + int(disp["night_to"][3:])
    night = (f <= cur < t) if f < t else (cur >= f or cur < t)
    if not night:
        return disp["refresh_s"]
    # nicht über das Nachtende hinaus schlafen
    until_end = ((t - cur) % 1440) * 60
    return max(60, min(disp["night_refresh_s"], until_end or disp["night_refresh_s"]))


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}")


def lan_ip():
    """IP dieses Rechners im Heimnetz (UDP-„Verbindung“ sendet keine Pakete)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))
            return s.getsockname()[0]
    except OSError:
        return "<Raspberry-IP>"


def config_url(host=None):
    """Adresse der Einstellungsseite, wie Display bzw. Browser den Server erreichen."""
    if not host or host.split(":")[0] in ("localhost", "127.0.0.1", "[::1]", "0.0.0.0"):
        host = f"{lan_ip()}:{PORT}"
    return f"http://{host}/config"


def current_image(cfg=None, host=None):
    cfg = cfg or sm_config.load()
    view = sm_data.collect(cfg)
    if view.get("error"):
        log(f"Datenabruf fehlgeschlagen: {view['error']}")
    return sm_render.render(cfg, view, _device.get("battery"), config_url(host)), cfg


# ---- Server ----------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    def _send(self, body, ctype="application/json", code=200, extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(json.dumps(obj, ensure_ascii=False).encode(), "application/json", code)

    def _body_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            return json.loads(raw or b"{}")
        except ValueError:
            return {}

    def _authorized(self):
        """Optionaler Passwortschutz für /config (Umgebungsvariable CONFIG_PASSWORD)."""
        if not CONFIG_PASSWORD:
            return True
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Basic "):
            try:
                _, _, pw = base64.b64decode(auth[6:]).decode().partition(":")
                if hmac.compare_digest(pw, CONFIG_PASSWORD):
                    return True
            except ValueError:
                pass
        self._send(b"Passwort erforderlich", "text/plain; charset=utf-8", 401,
                   {"WWW-Authenticate": 'Basic realm="Solarmanager-Konfiguration"'})
        return False

    def _image_url(self, cfg):
        host = self.headers.get("Host") or f"localhost:{PORT}"
        ext = cfg["display"]["image_format"]
        name = f"solar-{int(time.time())}"
        return f"http://{host}/image/{name}.{ext}", name

    def _draft(self):
        """Konfiguration aus dem Browser (noch nicht gespeichert), API-Key ergänzt."""
        return sm_config.sanitize(sm_config.merge_secret(self._body_json(), sm_config.load()))

    def do_GET(self):
        url = urllib.parse.urlsplit(self.path)
        # Firmware fragt teils mit Schrägstrich am Ende (/api/setup/)
        path = url.path.rstrip("/") or "/"
        q = urllib.parse.parse_qs(url.query)
        if path == "/api/setup":
            u, name = self._image_url(sm_config.load())
            self._json({"status": 200, "api_key": "local-solarmanager",
                        "friendly_id": "SOLAR", "image_url": u, "filename": name})
        elif path == "/api/display":
            self._remember_device()
            cfg = sm_config.load()
            u, name = self._image_url(cfg)
            self._json({"status": 0, "image_url": u, "filename": name,
                        "refresh_rate": refresh_seconds(cfg),
                        "reset_firmware": False, "update_firmware": False,
                        "firmware_url": None, "special_function": ""})
        elif path.startswith("/image/"):
            img, cfg = current_image(host=self.headers.get("Host"))
            body, ctype = sm_render.image_bytes(img, cfg["display"]["image_format"])
            self._send(body, ctype)
        elif path == "/":
            html = ("<!doctype html><meta charset=utf-8><title>Solarmanager</title>"
                    "<body style='background:#e9e9e6;display:grid;place-items:center;"
                    "min-height:100vh;margin:0;font-family:system-ui'>"
                    "<div><img src='/image/preview.png' width=800 height=480 "
                    "style='background:#fff;box-shadow:0 8px 30px #0003;max-width:100%;height:auto'>"
                    "<p style='text-align:center'><a href='/config'>Einstellungen</a></p></div>"
                    "<script>setTimeout(()=>location.reload(),30000)</script>")
            self._send(html.encode(), "text/html; charset=utf-8")
        elif path.startswith("/config"):
            if not self._authorized():
                return
            if path == "/config":
                with open(os.path.join(HERE, "config.html"), "rb") as f:
                    self._send(f.read(), "text/html; charset=utf-8")
            elif path == "/config/api/config":
                self._json(sm_config.public_view(sm_config.load()))
            elif path == "/config/api/stations":
                self._safe(lambda: {"stations": sm_data.search_stations(q.get("q", [""])[0])})
            elif path == "/config/api/station":
                self._safe(lambda: sm_data.station_info(q.get("name", [""])[0]))
            else:
                self._send(b"{}", "application/json", 404)
        else:
            self._send(b"{}", "application/json", 404)

    def do_POST(self):
        path = urllib.parse.urlsplit(self.path).path.rstrip("/")
        if path.startswith("/config"):
            if not self._authorized():
                return
            if path == "/config/api/config":
                cfg = sm_config.save(sm_config.merge_secret(self._body_json(), sm_config.load()))
                sm_data.clear_cache()
                log("Einstellungen gespeichert")
                self._json({"ok": True, "config": sm_config.public_view(cfg),
                            "refresh_s": refresh_seconds(cfg)})
            elif path == "/config/api/preview":
                cfg = self._draft()
                img, _ = current_image(cfg, self.headers.get("Host"))
                body, ctype = sm_render.image_bytes(img, "png")
                self._send(body, ctype)
            elif path == "/config/api/fields":
                cfg = self._draft()
                self._safe(lambda: sm_data.discover(cfg))
            elif path == "/config/api/test":
                cfg = self._draft()
                self._safe(lambda: {"ok": True, "message": sm_data.test_connection(cfg)})
            else:
                self._send(b"{}", "application/json", 404)
            return
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        if path == "/api/log" and body:
            log(f"Geräte-Log: {body[:600].decode('utf-8', 'replace')}")
        self._json({})  # Antwort wird vom Gerät ignoriert

    def _safe(self, fn):
        try:
            self._json(fn())
        except Exception as e:
            self._json({"ok": False, "error": str(e)}, 502)

    def _remember_device(self):
        """Akku, WLAN und Firmware aus den Headern des Geräts merken."""
        h = self.headers
        volts = sm_data.num(h.get("Battery-Voltage"))
        pct = sm_data.num(h.get("Percent-Charged"))
        if pct is None:
            pct = battery_percent(volts)
        if volts is None and pct is None:
            return  # z. B. Browser-Vorschau
        if "emu" in (h.get("FW-Version") or ""):
            return  # trmnl_emulator.py soll den echten Akkustand nicht überschreiben
        _device.update(volts=volts, battery=int(pct) if pct is not None else None,
                       rssi=h.get("RSSI"), fw=h.get("FW-Version"), ts=time.time())
        log(f"Gerät: Akku {volts} V ≈ {_device['battery']} %, RSSI {_device['rssi']}, "
            f"FW {_device['fw']}")

    def log_message(self, fmt, *args):
        log(f"{self.client_address[0]} {fmt % args}")


def run_test():
    """Ruft die Daten einmal ab und zeigt Rohdaten + gefundene Felder."""
    cfg = sm_config.load()
    try:
        raw = sm_data.get_stream(cfg)
        print("Rohdaten (Stream):")
        print(json.dumps(raw, indent=2, ensure_ascii=False)[:3000])
        print("\n" + sm_data.test_connection(cfg))
        f = sm_data.discover(cfg)
        print("Verlaufsfelder:", ", ".join(f["range"]) or "–")
        for d in f["devices"]:
            print(f"Gerät {d['name']} ({d['type']}, {d['ref']}): "
                  + ", ".join(x["key"] for x in d["fields"]))
    except Exception as e:
        print(f"FEHLER: {e}", file=sys.stderr)
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
    sm_data.USE_SAMPLE = args.sample

    if args.test:
        sys.exit(run_test())

    if args.preview:
        img, _ = current_image()
        img.convert("1", dither=sm_render.Image.Dither.NONE).save("preview.png")
        print("preview.png geschrieben")
        sys.exit(0)

    cfg = sm_config.load()
    sm = cfg["solarmanager"]
    quelle = "Beispieldaten" if args.sample else (
        f"Cloud ({sm['sm_id'] or 'smId fehlt'})" if sm["source"] == "cloud"
        else f"Gateway {sm['gateway_ip']}")
    gespeichert = "config.json" if os.path.exists(sm_config.CONFIG_PATH) else "Standardwerte/.env"
    print(f"Server läuft auf http://0.0.0.0:{PORT}  (Einstellungen: http://localhost:{PORT}/config)")
    print(f"Quelle: {quelle} · Einstellungen aus {gespeichert} · Ctrl+C beendet")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
