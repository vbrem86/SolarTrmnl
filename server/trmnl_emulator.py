#!/usr/bin/env python3
"""
TRMNL-Geräte-Emulator (ohne Hardware)

Verhält sich gegenüber dem Server wie die TRMNL-Firmware:
    1. GET  /api/setup    (Header ID = MAC)          -> api_key, friendly_id
    2. GET  /api/display  (Access-Token, Battery-Voltage, RSSI, ...)
                                                     -> image_url, refresh_rate
    3. GET  image_url                                -> Bild prüfen und "anzeigen"
    4. warten (refresh_rate), weiter bei 2.
Fehler werden wie bei der Firmware per POST /api/log gemeldet.

Das "Display" ist eine Seite im Browser: http://localhost:8090/
Taste "Aktualisieren" entspricht dem Knopf am Gerät.

Start (Server muss laufen, z. B. mit Beispieldaten):
    python3 solarmanager_byos.py --sample
    python3 trmnl_emulator.py                       # Server http://localhost:8080
    python3 trmnl_emulator.py --server http://<Raspberry-IP>:8080 --interval 15

Nur einmal abrufen und als Datei speichern:
    python3 trmnl_emulator.py --once emulator.png
"""

import argparse
import json
import struct
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MAC = "AA:BB:CC:DD:EE:01"
FW_VERSION = "1.5.2-emu"
W, H = 800, 480

state = {
    "image": None, "ctype": "image/png", "api_key": None, "friendly_id": "",
    "refresh": 0, "next": 0, "count": 0, "check": "", "log": [],
}
wake = threading.Event()
lock = threading.Lock()


def log(msg):
    line = f"{time.strftime('%H:%M:%S')}  {msg}"
    print(line)
    with lock:
        state["log"] = (state["log"] + [line])[-60:]


def http(method, url, headers, body=None, timeout=20):
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.headers.get("Content-Type", ""), r.read()


def check_image(data):
    """Prüft das Bild so, wie es das Panel braucht: 800x480, 1 Bit."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        w, h, depth, color = struct.unpack(">IIBB", data[16:26])
        fmt = f"PNG {w}x{h}, {depth} Bit, Farbtyp {color}"
        ok = (w, h) == (W, H) and depth == 1
    elif data[:2] == b"BM":
        w, h = struct.unpack("<ii", data[18:26])
        bpp = struct.unpack("<H", data[28:30])[0]
        fmt = f"BMP {w}x{abs(h)}, {bpp} Bit"
        ok = (w, abs(h)) == (W, H) and bpp == 1
    else:
        return False, "unbekanntes Bildformat"
    return ok, fmt + (" – passt" if ok else f" – erwartet {W}x{H}, 1 Bit")


def device_headers(extra=None):
    h = {"ID": MAC, "FW-Version": FW_VERSION, "Model": "og",
         "Width": str(W), "Height": str(H), "User-Agent": "ESP32HTTPClient"}
    h.update(extra or {})
    return h


def send_log(server, text):
    try:
        body = json.dumps({"log": {"logs_array": [{
            "creation_timestamp": int(time.time()), "log_message": text,
            "device_status_stamp": {"wifi_rssi_level": -58,
                                    "battery_voltage": 4.05}}]}}).encode()
        http("POST", f"{server}/api/log",
             device_headers({"Access-Token": state["api_key"] or "",
                             "Content-Type": "application/json"}), body)
    except Exception:
        pass


def cycle(server, interval):
    """Ein Aufwach-Zyklus wie in der Firmware. Gibt die Schlafzeit zurück."""
    if not state["api_key"]:
        st, _, body = http("GET", f"{server}/api/setup", device_headers())
        js = json.loads(body)
        log(f"/api/setup -> {st} {js}")
        state["api_key"] = js.get("api_key")
        state["friendly_id"] = js.get("friendly_id", "")
        if not state["api_key"]:
            raise RuntimeError("Setup ohne api_key")

    st, _, body = http("GET", f"{server}/api/display", device_headers({
        "Access-Token": state["api_key"], "Refresh-Rate": str(state["refresh"] or 900),
        "Battery-Voltage": "4.05", "RSSI": "-58"}))
    js = json.loads(body)
    log(f"/api/display -> {st} status={js.get('status')} "
        f"refresh_rate={js.get('refresh_rate')} file={js.get('filename')}")
    url = js.get("image_url")
    if not url:
        raise RuntimeError("Antwort ohne image_url")

    st, ctype, img = http("GET", url, device_headers(), timeout=30)
    ok, info = check_image(img)
    log(f"Bild {len(img)} Bytes, {info}")
    if not ok:
        send_log(server, f"bad image: {info}")
    with lock:
        state.update(image=img, ctype=ctype or "image/png", check=info,
                     count=state["count"] + 1)
    rr = int(js.get("refresh_rate") or 900)
    state["refresh"] = rr
    return interval or rr


def loop(server, interval):
    while True:
        try:
            sleep = cycle(server, interval)
        except (urllib.error.URLError, OSError, ValueError, RuntimeError) as e:
            log(f"FEHLER: {e} – neuer Versuch in 30 s")
            send_log(server, f"error: {e}")
            sleep = 30
        state["next"] = time.time() + sleep
        log(f"Deep Sleep {sleep} s")
        wake.wait(sleep)
        if wake.is_set():
            log("Taste gedrückt – aufwachen")
        wake.clear()


PAGE = """<!doctype html><html lang=de><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>TRMNL-Emulator</title>
<style>
body{margin:0;background:#2b2b2b;color:#ddd;font:14px/1.4 -apple-system,system-ui,sans-serif;
 display:flex;flex-direction:column;align-items:center;gap:18px;padding:28px 16px}
.dev{background:#d9d6cf;padding:34px 34px 44px;border-radius:14px;box-shadow:0 20px 50px #0008;
 max-width:100%;box-sizing:border-box}
.scr{display:block;width:800px;max-width:100%;aspect-ratio:5/3;background:#f2f1ec;
 image-rendering:pixelated;filter:contrast(.92) sepia(.08);transition:opacity .25s}
.scr.flash{opacity:.05}
.bar{display:flex;gap:16px;align-items:center;flex-wrap:wrap;justify-content:center}
button{font:inherit;padding:6px 14px;border-radius:6px;border:1px solid #666;background:#444;color:#eee;cursor:pointer}
pre{width:868px;max-width:100%;box-sizing:border-box;background:#1c1c1c;padding:12px;border-radius:8px;
 height:200px;overflow:auto;margin:0;font:12px/1.5 ui-monospace,Menlo,monospace}
</style>
<div class=dev><img class=scr id=scr alt="E-Paper"></div>
<div class=bar><span id=info>warte auf erstes Bild…</span>
<button onclick="fetch('/press',{method:'POST'})">Aktualisieren (Taste)</button></div>
<pre id=log></pre>
<script>
let shown=-1;
async function tick(){
 try{
  const s=await (await fetch('/state')).json();
  const left=Math.max(0,Math.round(s.next-Date.now()/1000));
  document.getElementById('info').textContent=
   `${s.friendly_id||'–'} · Bild #${s.count} · ${s.check} · nächster Abruf in ${left} s`;
  const l=document.getElementById('log');
  const atEnd=l.scrollTop+l.clientHeight>=l.scrollHeight-5;
  l.textContent=s.log.join('\\n'); if(atEnd) l.scrollTop=l.scrollHeight;
  if(s.count!==shown&&s.count>0){
   shown=s.count; const img=document.getElementById('scr');
   img.classList.add('flash');   // E-Paper-Vollrefresh andeuten
   setTimeout(()=>{img.src='/screen?'+s.count;img.classList.remove('flash')},300);
  }
 }catch(e){}
}
setInterval(tick,1000);tick();
</script></html>"""


class UI(BaseHTTPRequestHandler):
    def _send(self, body, ctype, code=200):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        p = self.path.split("?")[0]
        if p == "/":
            self._send(PAGE.encode(), "text/html; charset=utf-8")
        elif p == "/state":
            with lock:
                s = {k: state[k] for k in
                     ("friendly_id", "count", "check", "next", "log", "refresh")}
            self._send(json.dumps(s).encode(), "application/json")
        elif p == "/screen" and state["image"]:
            self._send(state["image"], state["ctype"])
        else:
            self._send(b"", "text/plain", 404)

    def do_POST(self):
        if self.path == "/press":
            wake.set()
        self._send(b"{}", "application/json")

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="TRMNL-Geräte-Emulator")
    ap.add_argument("--server", default="http://localhost:8080",
                    help="Adresse des BYOS-Servers (wie im WLAN-Portal eingetragen)")
    ap.add_argument("--interval", type=int, default=0,
                    help="Abrufintervall in s erzwingen (Standard: refresh_rate vom Server)")
    ap.add_argument("--port", type=int, default=8090, help="Port der Emulator-Seite")
    ap.add_argument("--once", metavar="DATEI",
                    help="einen Zyklus ausführen, Bild speichern, beenden")
    args = ap.parse_args()
    server = args.server.rstrip("/")

    if args.once:
        try:
            cycle(server, args.interval)
        except Exception as e:
            log(f"FEHLER: {e}")
            raise SystemExit(1)
        with open(args.once, "wb") as f:
            f.write(state["image"])
        print(f"{args.once} geschrieben")
        raise SystemExit(0 if "passt" in state["check"] else 2)

    threading.Thread(target=loop, args=(server, args.interval), daemon=True).start()
    print(f"Emulator-Display: http://localhost:{args.port}/  ·  Server: {server}  ·  Ctrl+C beendet")
    ThreadingHTTPServer(("127.0.0.1", args.port), UI).serve_forever()
