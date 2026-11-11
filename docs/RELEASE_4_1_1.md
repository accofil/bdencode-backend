# Accofil BDEncode 4.1.1 kiadási jegyzet

Javítás: a hangellenőrzés nem áll le, ha a scan egy hangsávot 0 Hz-cel és 0 csatornával rögzített.

## A hiba

A Taffin (1988) munka a 4.1.0 után eljutott a hangellenőrzésig, és ott `ValueError: sample rate must be positive` hibával állt le. A hang időzítése ekkor már jó volt (a kész fájlban 11,011 s-nál indul). Az ok: a **scan** is az ffmpeg alapértelmezett, rövid vizsgálati ablakával olvasta a playlistet, ezért a hang nélküli bevezető klip miatt a DTS-hangot 0 Hz-cel és 0 csatornával rögzítette (ugyanaz az ok, mint a 4.0.3-ban javított remuxnál). A hangszabály a 0-t valódi értéknek vette.

## A javítás

- A scan ffprobe-ja is `-analyzeduration 120M` opcióval olvassa a playlistet, így új munkánál a hangsáv adatai helyesek.
- A hangszabály a 0 Hz-et és a 0 csatornát **ismeretlennek** veszi. Ilyenkor az ellenőrzés a referenciában ténylegesen mért értékeket használja (a Taffinon 48 kHz, 2 csatorna).

## Amit érdemes tudni

- A régebben scannelt munkáknál a scan adatai nem változnak, de a 0 értékek már nem állítják meg az ellenőrzést.
- Az elbukott munkát újra kell indítani; a mux és az encode megmarad, csak a QC fut újra.

## Ellenőrzőlista

1. `GET /api/v1/capabilities` `backend_version`: `4.1.1`.
2. A Taffin munka a QC-n átjut.
