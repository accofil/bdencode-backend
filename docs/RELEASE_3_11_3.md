# BDEncode 3.11.3 kiadási jegyzet

**Fontos javítás: a kész MKV-kban a feliratok el voltak csúszva.**

## A hiba

A 3.11.2-ig minden kész kódolásban a megtartott feliratsávok első eseménye 0:00-ra került, és a sáv minden felirata ugyanennyivel korábban jelent meg. A The Florist 2026 lemezről készült kódolásában a három német felirat 71,9, 6,9 és 71,9 másodperccel korábban jött.

Az ok: a program a sávok kezdőidejét az ffprobe `start_time` értékéből vette.
- A referenciában (több sávos MKV) a feliratsáv `start_time`-ja a konténer kezdete, általában 0.
- A kicsomagolt, egysávos feliratfájlban az első esemény ideje.
- A kettő különbségét „szinkron-korrekcióként” átadta az mkvmerge-nek (`--sync`), ami a feliratot pontosan ennyivel korábbra tolta.

A QC nem vette észre, mert a csomagokat a sávok első csomagjához viszonyítva hasonlította össze, így az egész sáv eltolása rejtve maradt. A hang és a videó nem érintett: a hangsávok kicsomagolt fájljában a `start_time` valódi érték.

Ugyanez a hiba okozta, hogy egy remux MKV szöveges (SRT) feliratával a munka megállt („track-03 has no trustworthy presentation start time”). Egysávos SRT-fájlnál az ffprobe nem ad `start_time`-ot.

## A javítás

- A feliratok helyét a program most mindkét oldalon az **első csomag időbélyegéből** méri. A kicsomagolás `-copyts` stream-másolás, ezért a két érték egyezik, és a felirat a referencia abszolút idejét tartja meg.
- Csak a közös nullpontra igazít (ugyanúgy, mint a hangot és a videót).
- **Új QC-ellenőrzés:** a kész MKV-ban minden feliratsáv első eseményének a referencia szerinti helyén kell lennie (3 ms tűréssel MKV-forrásnál, 2 ms-mal lemeznél). Egy eltolt sáv többé nem mehet át. A sáv-integritás QC sémája 3-ra lépett, így egy félbehagyott munka ezt az ellenőrzést is lefuttatja.
- Az idővonal-terv (`analysis/timeline-plan.json`, séma 2) a feliratok várt első eseményét is rögzíti.

## A korábbi kiadások

A 3.11.2-ig készült, feliratot tartalmazó kész kiadásokban a feliratok el vannak csúszva. Ezek feliratát újra kell muxolni. A program a kész fájlokhoz nem nyúl.

## Ellenőrzőlista

1. `GET /api/v1/capabilities` `backend_version`: `3.11.3`.
2. Egy feliratos munka után az `analysis/track-mux-integrity.json` feliratsávjainál az `absolute_shift_ms` értéke 0 (vagy néhány ms).
3. A kész MKV-ban a felirat első eseménye ugyanott van, mint a forrásban (`ffprobe -select_streams s:0 -show_entries packet=pts_time -read_intervals %+#1`).
