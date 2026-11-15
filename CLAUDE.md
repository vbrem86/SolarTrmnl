# Projektkontext: Solarmanager auf TRMNL

Lies zuerst `README.md` (Stand, offene Punkte) und `firmware/FIRMWARE.md`.

## Ziel
Solarmanager-Daten (PV, Verbrauch, Netz, Batterie, Wärmepumpe) auf einem TRMNL-kompatiblen
E-Paper (Seeed TRMNL 7.5" OG DIY Kit, XIAO ESP32-S3 Plus, 800x480, 1 Bit) anzeigen.
Ohne TRMNL-Konto: eigener Server auf dem Raspberry (BYOS); Gerät per „Custom Server“ im
WLAN-Portal umgestellt (Firmware 1.5.12, kein Flashen nötig). Das Repository ist öffentlich.

## Entscheidungen
- Cloud-Plugin/Recipe verworfen: TRMNLs Cloud erreicht das Heimnetz nicht (`alt/`).
- Haupt-Weg ist `server/solarmanager_byos.py` (Server, TRMNL-Protokoll `/api/setup`,
  `/api/display`, `/api/log`, `/image/...`, dazu Web-Konfiguration `/config`).
  Module: `sm_config.py` (Einstellungen, config.json), `sm_data.py` (Daten, Quellen-Schlüssel),
  `sm_render.py` (Bild), `sm_qr.py` (QR-Encoder, gegen Bibliothek `qrcode` Modul für Modul
  geprüft), `config.html` (Menü, Vanilla-JS ohne externe Bibliotheken).
- Zustands-Kacheln: `states` = [{value, text, icon}] je Kachel; Wärmepumpen-Vorlage
  `HEATPUMP_STATES` in sm_config. Alte Einstellungen ohne `states` bekommen die Vorlage.
  Menü warnt bei Quellen, die `discover()` nicht mehr liefert (Gerät weg / Feld fehlt).
- Ohne Zugangsdaten: Einrichtungsseite auf dem Display mit Adresse + QR-Code zu /config
  (Adresse aus Host-Header des Geräts, bei localhost die LAN-IP); immer hell gezeichnet.
- Einstellungen in `server/config.json` (gitignored, Rechte 600, enthält API-Key). Ohne Datei:
  Standardwerte + Umgebung (.env). API-Key geht nie im Klartext an den Browser
  (`public_view`/`merge_secret`). Optional `CONFIG_PASSWORD` für /config.
- Quellen-Schlüssel: `stream:<f>`, `device:<ref>:<f>`, `today:<f>` (Kacheln),
  `range:<f>`, `devrange:<ref>:<f>` (Diagramm); `<ref>` = Geräte-ID oder `type=<typ>`.
  Gerätenamen aus `/v3/users/{smId}/devices` (`tag`, `deviceKey`, `type`).
- Datenquelle per `SM_SOURCE`: `cloud` (Standard, Cloud-API) oder `local` (Gateway `/v2/point`).
- Cloud-API v3 wie in der SolarWatch-App (`../SolarWatch`): Header `X-API-KEY`,
  `/v3/users/{smId}/data/stream`, `/v3/users/{smId}/data/range`, `/v3/devices/{id}/data/range`.
- Standard-Anzeige wie SolarWatch: oben PV/Verbrauch/heute, Mitte Tagesdiagramm (PV, Verbrauch,
  Wassertemperatur), unten Aussentemperatur, Zustand Wärmepumpe, Wassertemperatur.
  1 Bit: PV schraffiert, Verbrauch durchgezogen, Wasser gestrichelt. Alles über /config änderbar
  (Kacheln oben/unten mit Grösse s/m/l, Diagramm-Verläufe mit Stil/Achse, Bus links/rechts/aus,
  hell/dunkel, Nachtmodus). Ohne Diagramm werden Kacheln eine Stufe grösser gezeichnet.
- Rechte Spalte „Bus“: nächste Abfahrten, Zeit + Verspätung („+2“). Quelle transport.opendata.ch
  `/v1/stationboard`. Haltestelle, Linien und Richtung nur über `BUS_*` in `.env` (persönlich,
  nicht in Code oder Doku). Richtung über `passList` (Kurs hält danach an `BUS_VIA`), weil
  Linien oft über das Ziel hinausfahren oder an einer Nachbarhaltestelle enden.
- Akkustand aus Header `Battery-Voltage` bei `/api/display`, LiPo-Kennlinie; Emulator ignoriert.

## Annahmen, die noch nicht geprüft sind
- `operationState` der Wärmepumpe: 1 = Standby, 2 = Heizen, 3 = Warmwasser (bestätigt). Cloud-Abruf mit echten Daten am 14.11.2026 geprüft.
- Bauen einer eigenen Firmware (nur für ältere Geräte nötig) ist nicht ausprobiert.

## Konventionen
- Sprache der Oberfläche und Doku: Deutsch.
- Keine Zugangsdaten und keine persönlichen Angaben (Haltestelle, IPs, Benutzernamen) ins
  Repository; alles Persönliche gehört in `.env` (ist in `.gitignore`).
- Test ohne Hardware: `python3 solarmanager_byos.py --preview --sample` und `--test`,
  Einstellungsseite mit Beispieldaten: `--sample`, dann http://localhost:8080/config,
  Geräte-Emulator: `python3 trmnl_emulator.py` (Display unter http://localhost:8090/).
