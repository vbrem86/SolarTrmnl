#!/usr/bin/env python3
"""
Solarmanager -> TRMNL (Webhook-Strategie)

Läuft in deinem lokalen Netz (Mac, Raspberry Pi, NAS ...), holt alle paar
Minuten die Daten vom Gateway (http://<IP>/v2/point) und schickt sie per
POST an die Webhook-URL deines TRMNL-Plugins. Das Gateway muss dafür nicht
von aussen erreichbar sein.

Start:
    python3 solarmanager_to_trmnl.py

Einmaliger Test ohne Schleife:
    python3 solarmanager_to_trmnl.py --once

Konfiguration per Umgebungsvariablen (oder unten die Defaults ändern):
    SM_IP, SM_API_KEY, TRMNL_WEBHOOK, INTERVAL_SECONDS
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

# ---- Konfiguration ---------------------------------------------------------
SM_IP = os.environ.get("SM_IP", "192.168.1.231")
SM_API_KEY = os.environ.get("SM_API_KEY", "DEIN_API_KEY")
TRMNL_WEBHOOK = os.environ.get(
    "TRMNL_WEBHOOK", "https://trmnl.com/api/custom_plugins/DEINE-UUID"
)
# Webhook-Limit: 12 Requests/Stunde (TRMNL+: 30). 360 s = 10 pro Stunde.
INTERVAL_SECONDS = int(os.environ.get("INTERVAL_SECONDS", "360"))
# Free-Tier-Limit für die Payload-Grösse
MAX_PAYLOAD_BYTES = 2048
# ----------------------------------------------------------------------------


def fetch_point():
    req = urllib.request.Request(
        f"http://{SM_IP}/v2/point", headers={"X-API-Key": SM_API_KEY}
    )
    with urllib.request.urlopen(req, timeout=8) as resp:
        return json.loads(resp.read())


def build_payload(data):
    """Nur die Felder senden, die das Markup braucht (hält die Payload klein)."""
    heatpump = None
    for d in data.get("devices", []):
        if "temperature" in d:
            heatpump = {
                "temperature": round(d["temperature"], 1),
                "activeDevice": d.get("activeDevice", 0),
                "signal": d.get("signal", ""),
            }
            break

    merge = {
        "pW": data.get("pW", 0),
        "cW": data.get("cW", 0),
        "bcW": data.get("bcW", 0),
        "bdW": data.get("bdW", 0),
        "t": data.get("t", ""),
    }
    if heatpump:
        merge["heatpump"] = heatpump
    return {"merge_variables": merge}


def push(payload):
    body = json.dumps(payload).encode()
    if len(body) > MAX_PAYLOAD_BYTES:
        raise RuntimeError(
            f"Payload {len(body)} Bytes > {MAX_PAYLOAD_BYTES} Bytes Limit"
        )
    req = urllib.request.Request(
        TRMNL_WEBHOOK,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.status


def run_once():
    try:
        data = fetch_point()
    except Exception as e:
        print(f"[Gateway] Fehler: {e}", file=sys.stderr)
        return False
    try:
        status = push(build_payload(data))
        print(f"[{time.strftime('%H:%M:%S')}] an TRMNL gesendet (HTTP {status}) "
              f"PV {data.get('pW')} W · Verbrauch {data.get('cW')} W")
        return True
    except urllib.error.HTTPError as e:
        hint = " (Rate-Limit: Intervall erhöhen)" if e.code == 429 else ""
        print(f"[TRMNL] HTTP {e.code}{hint}", file=sys.stderr)
    except Exception as e:
        print(f"[TRMNL] Fehler: {e}", file=sys.stderr)
    return False


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="nur einmal senden")
    args = ap.parse_args()

    if args.once:
        sys.exit(0 if run_once() else 1)

    print(f"Sende alle {INTERVAL_SECONDS} s von {SM_IP} an TRMNL. Ctrl+C beendet.")
    while True:
        run_once()
        time.sleep(INTERVAL_SECONDS)
