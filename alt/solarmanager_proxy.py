#!/usr/bin/env python3
"""
Solarmanager local-API proxy.

Läuft lokal auf deinem Mac, holt die Daten vom Solarmanager-Gateway
(mit deinem API-Key) und reicht sie mit einem CORS-Freigabe-Header an
das lokale HTML-Dashboard weiter. Ohne diesen Proxy blockt der Browser
den fetch()-Aufruf aus dem Dashboard, weil das Gateway selbst keine
CORS-Header setzt.

Benutzung:
    python3 solarmanager_proxy.py

Dann im Dashboard als Proxy-Adresse eintragen:
    http://localhost:8765/point
"""

import json
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer

# ---- Hier deine Werte eintragen ----
GATEWAY_IP = "192.168.1.231"
API_KEY = "DEIN_API_KEY_HIER"
PROXY_PORT = 8765
# -------------------------------------

TARGET_URL = f"http://{GATEWAY_IP}/v2/point"


class ProxyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/point":
            self.send_response(404)
            self.end_headers()
            return

        req = urllib.request.Request(TARGET_URL, headers={"X-API-Key": API_KEY})
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                body = resp.read()
                status = resp.status
        except urllib.error.HTTPError as e:
            body = json.dumps({"error": f"Gateway antwortete mit HTTP {e.code}"}).encode()
            status = e.code
        except Exception as e:
            body = json.dumps({"error": str(e)}).encode()
            status = 502

        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        # ruhigeres Terminal, nur Fehler zeigen
        if "200" not in (args[1] if len(args) > 1 else ""):
            super().log_message(format, *args)


if __name__ == "__main__":
    print(f"Proxy läuft auf http://localhost:{PROXY_PORT}/point")
    print(f"Holt Daten von {TARGET_URL}")
    print("Zum Beenden: Ctrl+C")
    HTTPServer(("localhost", PROXY_PORT), ProxyHandler).serve_forever()
