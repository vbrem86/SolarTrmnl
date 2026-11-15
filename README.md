# Solarmanager auf TRMNL (eigener Server)

Zeigt die Daten eines [Solar Manager](https://www.solar-manager.ch) auf einem TRMNL-kompatiblen
E-Paper (z. B. Seeed TRMNL 7.5" OG DIY Kit, 800x480, schwarz-weiss), dazu rechts die nächsten
Busabfahrten einer Haltestelle in der Schweiz, live mit Verspätung.

Ohne TRMNL-Konto und ohne BYOD-Lizenz: Ein kleiner Server im Heimnetz (z. B. Raspberry Pi)
zeichnet das Bild, das Gerät holt es dort ab (TRMNL „BYOS“).

```
Solar Manager Cloud-API ─┐
                         ├─> server/solarmanager_byos.py (Raspberry) ─> E-Paper
transport.opendata.ch ───┘
```

**Anzeige**

- links oben: PV-Leistung, Verbrauch, PV-Produktion heute
- links Mitte: Tagesdiagramm 00–24 Uhr mit PV (schraffiert), Verbrauch (Linie) und
  Wassertemperatur der Wärmepumpe (gestrichelt, eigene Skala)
- links unten: Aussentemperatur, Zustand der Wärmepumpe (Standby / Heizen / Warmwasser),
  Wassertemperatur
- rechts: nächste Busabfahrten (Linie, Zeit, Verspätung als „+2“)
- Kopfzeile: Datum, Uhrzeit und Akkustand des Displays

Alles davon lässt sich im Browser unter `http://<Raspberry-IP>:8080/config` anpassen (siehe unten).

## Ordner

| Pfad | Inhalt |
|---|---|
| `server/solarmanager_byos.py` | Der Server: TRMNL-Protokoll und Einstellungsseite `/config` |
| `server/sm_config.py`, `sm_data.py`, `sm_render.py` | Einstellungen, Datenabruf, Bild zeichnen |
| `server/sm_qr.py` | kleiner QR-Code-Encoder (ohne Abhängigkeiten) für die Einrichtungsseite |
| `server/config.html` | Einstellungsseite (ohne externe Bibliotheken) |
| `server/trmnl_emulator.py` | Geräte-Emulator zum Testen ohne Hardware |
| `server/.env.example` | Vorlage für Zugangsdaten und Einstellungen |
| `server/solarmanager.service` | systemd-Dienst für den Autostart |
| `firmware/FIRMWARE.md` | Gerät auf den eigenen Server umstellen |
| `alt/` | Verworfene oder alternative Wege (Webhook, Liquid-Recipe, Browser-Dashboard) |

## Einrichten

Voraussetzung: Python 3.9+ und Pillow (`sudo apt install python3-pil` oder
`pip3 install -r server/requirements.txt`).

```bash
cd server
cp .env.example .env          # Werte eintragen, siehe unten
set -a; source .env; set +a
python3 solarmanager_byos.py --test     # Zugangsdaten prüfen, zeigt Rohdaten
python3 solarmanager_byos.py            # Server starten, Vorschau: http://localhost:8080/
```

Beim ersten Start ohne Zugangsdaten zeigt das Display „Noch nicht eingerichtet“ mit der Adresse
der Einstellungsseite und einem QR-Code dazu: Handy im selben WLAN, Code scannen, smId und API-Key
eintragen, speichern. Alternativ reichen smId und API-Key in `server/.env` (Solar Manager Web-App → Profil →
Cloud-API-Schlüssel, **ohne** „Erneuerung erlauben“ erstellen). Alles Weitere geht über die
Einstellungsseite.

### Einstellungsseite `/config`

`http://<Raspberry-IP>:8080/config` zeigt eine Live-Vorschau, die sich bei jeder Änderung
aktualisiert. Erst „Speichern“ übernimmt die Einstellungen; das Display holt sie beim nächsten
Aufwachen.

| Bereich | Einstellungen |
|---|---|
| Anzeige | Titel, hell/dunkel, Datum, Akkustand, Aktualisierungsintervall, Nachtmodus (seltener aktualisieren, spart Akku), PNG/BMP |
| Werte | beliebige Werte der Anlage als Kacheln oben oder unten: Quelle, Beschriftung, Symbol, Format, Einheit, Nachkommastellen, Grösse, Reihenfolge |
| Diagramm | an/aus, heute oder letzte 24 h, Verläufe mit Darstellung (Fläche, Linie, gestrichelt, …) und Achse links/rechts |
| öV-Abfahrten | an/aus (ohne: Solar über die ganze Breite), links/rechts, schmal/breit, Haltestelle mit Suche, Linien, Richtung, Anzahl |
| Solar Manager | Cloud oder Gateway, smId, API-Key, Verbindung testen |

Die Auswahl der Werte zeigt alles, was die Anlage liefert: aktuelle Werte, Tagessummen und
Verläufe der Anlage sowie jedes Geräts (z. B. Wärmepumpe, Wechselrichter, Zähler, Ladestation,
Batterien) mit dem Namen aus der Solar-Manager-App. Nur Zahlenwerte; Texte und verschachtelte
Angaben werden nicht angeboten.

- **Zustände** (z. B. `operationState`): Format „Zustand“, dann jeder Zahl einen Text und ein
  Symbol zuordnen; das Menü zeigt, welche Zahl das Gerät gerade meldet. Für die Wärmepumpe gibt es
  eine Vorlage (1 Standby, 2 Heizen, 3 Warmwasser), Symbol „automatisch“ wechselt mit dem Zustand.
- **Mehrere gleiche Geräte** (z. B. zwei Batterien) werden über ihre Geräte-ID zugeordnet, einzelne
  über ihren Typ. Wird ein Gerät ersetzt oder entfernt, markiert das Menü die betroffenen Einträge
  („Gerät nicht mehr vorhanden – bitte neu zuordnen“), das Display zeigt dort „–“.
- Nur mit einer Anlage (Wärmepumpe, Wechselrichter, Zähler) und Beispieldaten getestet.

Die Einstellungen liegen in `server/config.json` (nicht im Git, nur für den Besitzer lesbar).
Der API-Key wird nie an den Browser geschickt. Die Seite ist im ganzen Heimnetz erreichbar;
wer sie schützen will, setzt `CONFIG_PASSWORD` in der `.env` (Benutzername beliebig).

Die Richtung der Busse wird über die Halteliste bestimmt, nicht über die Endstation: Viele Linien
fahren über das gewünschte Ziel hinaus oder enden an einer Nachbarhaltestelle.

### Dauerhaft auf dem Raspberry

```bash
scp -r server <benutzer>@<Raspberry-IP>:~/solarmanager-trmnl/
# auf dem Raspberry: in solarmanager.service User= und Pfade anpassen, dann
sudo cp ~/solarmanager-trmnl/server/solarmanager.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now solarmanager
journalctl -u solarmanager -f           # zeigt Anfragen des Geräts, Akku, Geräte-Logs
```

- Zeitzone des Raspberry setzen (`sudo timedatectl set-timezone Europe/Zurich`), sonst stimmen
  Tagesdiagramm und Abfahrtszeiten nicht.
- Dem Raspberry im Router eine feste IP geben. `raspberrypi.local` kann vom Mac aus zuerst auf
  IPv6 auflösen und dann nicht erreichbar sein; die IPv4-Adresse ist zuverlässiger.
- Aktualisieren: Dateien erneut kopieren, dann `sudo systemctl restart solarmanager`.

### Gerät verbinden

Ab TRMNL-Firmware 1.4.6 ohne Flashen: Taste hinten am Gerät ca. 5 s halten, mit dem WLAN
„TRMNL“ verbinden, WLAN wählen, dann **Advanced → Custom Server → Yes** und
`http://<Raspberry-IP>:8080` eintragen. Details und Weg für ältere Firmware: `firmware/FIRMWARE.md`.

Zeigt das Display „MAC not registered“, fragt es noch die TRMNL-Cloud: Custom Server fehlt.

## Test ohne Gerät (Emulator)

`server/trmnl_emulator.py` verhält sich wie die TRMNL-Firmware (`/api/setup` → `/api/display`
→ Bild holen, Fehler per `/api/log`), prüft das Bild auf 800x480 / 1 Bit und zeigt es im Browser.

```bash
python3 solarmanager_byos.py --sample                # Beispieldaten, auch /config ausprobieren
python3 trmnl_emulator.py --interval 15              # Display: http://localhost:8090/
python3 trmnl_emulator.py --once emulator.png        # einmal abrufen, als Datei speichern
python3 solarmanager_byos.py --preview --sample      # nur Bild schreiben -> preview.png
```

## Technische Details

- **Solar Manager Cloud-API v3**, Header `X-API-KEY`:
  `/v3/users/{smId}/data/stream` (aktuell), `/v3/users/{smId}/data/range` (Verlauf ab Mitternacht,
  15-min-Schritte, `pWh` für die Tagesproduktion), `/v3/devices/{id}/data/range` (Wassertemperatur).
  Wärmepumpe = Gerät im Stream mit `operationState` bzw. `temperatureOutside`;
  `operationState` 1 = Standby, 2 = Heizen, 3 = Warmwasser (an einer Stiebel-Anlage beobachtet,
  nicht offiziell dokumentiert).
- Quellen-Schlüssel in `config.json`: `stream:<feld>`, `device:<gerät>:<feld>`, `today:<feld>`
  (Kacheln), `range:<feld>`, `devrange:<gerät>:<feld>` (Diagramm); `<gerät>` ist die Geräte-ID oder
  `type=heatpump` usw. Gerätenamen aus `/v3/users/{smId}/devices`.
- Abrufe werden zwischengespeichert: Stream 30 s, Verlauf 5 min, Bus 60 s
  (Cloud-Limit: 1000 Stream-Abfragen pro Stunde).
- **Bus**: [transport.opendata.ch](https://transport.opendata.ch/docs.html) `/v1/stationboard`,
  kein Schlüssel nötig. Verspätung aus `stop.delay` (Minuten, ohne Echtzeit leer).
- **Akku**: Das Gerät schickt bei `/api/display` den Header `Battery-Voltage`; der Server rechnet
  ihn mit einer LiPo-Kennlinie in Prozent um (Näherung). Meldungen des Emulators werden ignoriert.
- Die Firmware fragt teils `/api/setup/` mit Schrägstrich ab; der Server akzeptiert beides.
- Alternativ `SM_SOURCE=local`: aktuelle Werte vom Gateway im Heimnetz (`/v2/point`), dann ohne Verlauf.

## Offene Punkte

- [ ] Einstellungsseite auf einem echten Handy testen (geprüft nur in Chrome ab ca. 500 px Breite)

## Lizenz

MIT, siehe [LICENSE](LICENSE). Kein offizielles Projekt von Solar Manager, TRMNL oder SBB.

## Quellen

- [transport.opendata.ch (öV-Daten Schweiz)](https://transport.opendata.ch/docs.html)
- [TRMNL BYOS](https://docs.trmnl.com/go/diy/byos)
- [TRMNL Hilfe: Gerät mit eigenem Server verbinden](https://help.trmnl.com/en/articles/12263392-connect-your-device-to-terminus-byos)
- [TRMNL DIY-Optionen (BYOD, BYOD/S, BYOS)](https://docs.trmnl.com/go/diy/introduction)
- [Seeed: TRMNL 7.5" DIY Kit](https://wiki.seeedstudio.com/trmnl_7inch5_diy_kit_main_page/)
- [Seeed: Work with TRMNL](https://wiki.seeedstudio.com/reterminal_e10xx_trmnl/)
- [dev.to: Seeed TRMNL BYOD und BYOS](https://dev.to/leehambley/seedstudio-trmnl-byod-and-byos-36jn)
- [Home-Assistant-Integration für Solar Manager](https://github.com/Soardiac/ha-solarmanager)
