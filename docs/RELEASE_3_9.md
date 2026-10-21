# BDEncode 3.9.0 kiadási jegyzet

Új: a videókódoló (x264/x265) logja látszik a felületen, a végén lévő összegzéssel.

## Miért nem láttad eddig

A kódoló naplóját a program a munka privát `logs/video-encode.log` fájljába írja, de a felületre egyetlen logot sem regisztrált (a Fájlok fülön nincs `LOG` típusú melléklet). Ráadásul a fájl nehezen olvasható: a Late Fame munkánál 88 382 sor, 1,5 MB, aminek nagy része az ffmpeg kétmásodpercenkénti folyamatjelzése (`frame=…`, `fps=…`, `out_time=…`).

## Mi változott

- Új **Kódoló log** kártya a munka **Áttekintés** fülén, a lépések alatt. Kódolás kezdetétől látszik, és kódolás közben 15 másodpercenként frissül.
  - **Záró összegzés:** az ffmpeg záró sora (`frame=…, Lsize=…, bitrate=…`), a `video:` összesítés, és az x264 saját statisztikája (I/P/B képkockák átlagos QP-vel és mérettel, egymás utáni B-képek, makroblokk-statisztikák, referenciák, `kb/s`).
  - **Teljes tisztított log:** kinyitható, az x264 összes beállításával (`options: cabac=1 ref=4 … crf=17.5 …`) és a bevezetővel. A folyamatjelzés ki van szűrve: a Late Fame logja 88 382 sorról 38 sorra zsugorodik.
  - **Másolás** és **Letöltés** (`x264-encode-log.txt` / `x265-encode-log.txt`).
- **A belső útvonalak, az azonosítók és a kulcsok maszkolva vannak** (ugyanaz a tisztítás, mint a publikus csomagnál), ezért a log megosztható. Az eredeti, teljes fájl változatlanul megmarad a munka privát `logs` mappájában.
- API: `GET /api/v1/jobs/{id}/encoder-log` és `GET /api/v1/jobs/{id}/encoder-log.txt`. Már kész munkáknál is működik, mert a log megmarad a munkaterület takarítása után is.

## Ellenőrzőlista

1. `GET /api/v1/capabilities` `backend_version`: `3.9.0`.
2. Egy kész munka **Áttekintés** fülén megjelenik a „Kódoló log · x264” kártya a záró összegzéssel.
