# Firmware für das Seeed TRMNL 7.5" OG DIY Kit

Ziel: Das Gerät fragt statt der TRMNL-Cloud den eigenen Server ab.

## Einfacher Weg: Custom Server im WLAN-Portal (Firmware ab 1.4.6)

So eingerichtet und geprüft mit Firmware 1.5.12, ohne Flashen:

1. Taste hinten am Gerät ca. 5 Sekunden halten, bis der Einrichtungsmodus erscheint.
2. Mit dem Handy ins WLAN „TRMNL“ gehen (Portal öffnet sich, sonst `4.3.2.1` aufrufen).
3. Das eigene **2,4-GHz-WLAN** wählen, Passwort eingeben.
4. Vor „Connect“: **Advanced → Custom Server → Yes**, Adresse `http://<Raspberry-IP>:8080`
   (mit `http://`, ohne Schrägstrich am Ende).
5. Connect. Im Server-Log (`journalctl -u solarmanager -f`) erscheinen `/api/setup` und `/api/display`.

„MAC not registered – visit trmnl.com/go/byod“ auf dem Display heisst: Das Gerät fragt noch die
TRMNL-Cloud, der Custom Server ist nicht gesetzt.

## Nur für ältere Firmware: selbst bauen und flashen

Fehlt „Custom Server“ im Portal, muss eine neuere Firmware aufs Gerät. Der folgende Weg
stammt aus einem Erfahrungsbericht (dev.to, Lee Hambley) und der Seeed-Doku und ist nicht
selbst ausprobiert.

### Voraussetzungen

- Computer mit VS Code und der Erweiterung PlatformIO
- USB-C-Kabel (Daten, nicht nur Laden)
- `esptool` (`pip install esptool`)
- Der Server läuft auf dem Raspberry und ist im WLAN erreichbar: `http://<Raspberry-IP>:8080/`
  (IP im Router fest reservieren)

### Schritte

1. **Original sichern**, bevor du etwas überschreibst:
   ```bash
   esptool.py flash_id                       # zeigt die Flash-Grösse
   esptool.py read_flash 0 <GROESSE> original-backup.bin
   ```
   Beispiel: bei 16 MB `0x1000000`.

2. **Firmware holen**: Repository `usetrmnl/trmnl-firmware` von GitHub klonen
   und im Ordner in VS Code öffnen.

3. **Ziel einstellen**: in `platformio.ini` unter `default_envs` den Eintrag
   `trmnl` durch `seeed_xiao_esp32s3` ersetzen.

4. **Server-Adresse eintragen**: in `include/config.h` den Wert `API_BASE_URL`
   auf `http://<Raspberry-IP>:8080` setzen. (Name laut Bericht, bei Abweichung
   im Quelltext nach der Basis-URL suchen.)

5. **Bauen** (PlatformIO: Build). Ergebnis ist `firmware.bin`.

6. **Flashen** (im Bericht: Offset `0x10000`, 460800 Baud):
   ```bash
   esptool.py --baud 460800 write_flash 0x10000 .pio/build/seeed_xiao_esp32s3/firmware.bin
   ```
   Falls das Gerät nicht in den Flash-Modus geht: BOOT-Taste gedrückt halten
   und dabei per USB einstecken.

7. **WLAN einrichten**: Das Gerät öffnet das WLAN «TRMNL» (Portal-Adresse `4.3.2.1`).
   Dein **2,4-GHz-WLAN** wählen, 5 GHz wird nicht unterstützt.

8. Im Server-Log (`journalctl -u solarmanager -f` oder Terminal) sollten
   Anfragen auf `/api/setup` und `/api/display` erscheinen.

## Wenn es nicht klappt

- Display bleibt leer: `IMAGE_FORMAT=bmp` beim Server probieren.
- Keine Anfragen im Server-Log: IP und Port prüfen, `curl http://<Raspberry-IP>:8080/api/display`
  von einem anderen Gerät testen.
- Zurück zum Original: `esptool.py write_flash 0 original-backup.bin`.

## Alternative: ESPHome

Das Kit läuft auch mit ESPHome und Home Assistant, ganz ohne TRMNL-Cloud
(siehe Seeed: Work with ESPHome). Dafür brauchst du Home Assistant,
und das Display wird in ESPHome selbst gezeichnet. Der Server hier wird dann nicht gebraucht.
