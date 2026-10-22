# BDEncode 3.11.1 kiadási jegyzet

Javítás: egy remux MKV-ból készült munka a QC-ben feleslegesen megállt („final mux changed a retained audio/subtitle packet timeline”).

## Mi történt

Az első valódi MKV-próbán (The Florist 2026 1080p remux) a kész MKV hangsávja bájtra azonos volt a forráséval. A QC mégis megállította a munkát, mert 552 502 DTS-csomagból 18 időbélyege 3 ms-mal eltért.

- A forrás-MKV idővonalát egy idegen muxer írta, ezredmásodpercre kerekítve, valószínűleg csonkolással.
- A kész fájlnál az mkvmerge a 10,67 ms-os DTS-csomagok idejét újraszámolja.
- A két kerekítés együtt legfeljebb 3 ms eltérést ad; ez messze a hallható szinkronhiba alatt van.
- Lemezforrásnál ez nem jön elő, mert ott a referenciát a program maga muxolja; ezért ott a tűrés 2 ms maradt.

## Mi változott

- **MKV-forrásnál** a megtartott hang- és feliratsávok időbélyeg-tűrése 3 ms. Lemezforrásnál továbbra is 2 ms.
- Változatlanul pontosnak kell lennie a csomagok számának, méretének, tartalmának (payload-hash) és hosszának. Egy elveszett, hozzáadott vagy valóban elcsúszott csomagot a QC így is elkap.
- Ellenőrizve a valódi Florist-munka adatain: 2 ms-mal 18 eltérés, 3 ms-mal nulla. A három PGS feliratsáv mindkét tűréssel hibátlan.

## Ellenőrzőlista

1. `GET /api/v1/capabilities` `backend_version`: `3.11.1`.
2. Egy MKV-forrású munka átmegy a QC sávintegritás-ellenőrzésén; a `analysis/track-mux-integrity.json` `timestamp_tolerance_ms` értéke 3.
