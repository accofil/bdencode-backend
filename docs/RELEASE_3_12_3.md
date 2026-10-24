# BDEncode 3.12.3 kiadási jegyzet

Javítás: a 3.12.0 hangszinkron-ellenőrzése egy hibátlan kész fájlt egy képkockával (41,667 ms) elcsúszottnak mért, és megállította a munkát.

## Mi történt

A canadán a Birds Without Names (2017) munka a QC-ben megállt: „audio track audio:4352 is 41.667 ms out of sync with the source”.

A kész fájl helyes volt. A forrásban a videó és a hang is 0,042 s-nál kezdődik, a kész fájlban mindkettő 0-n, tehát a kép-hang viszony változatlan.

A mérés hibázott: az FFmpeg `-ss` keresési pontja magában nem abszolút időbélyeg, hanem a fájl kezdetétől (itt 0,042 s) mért távolság. A mérő ezért a forrás ablakát 42 ms-mal később vette, és pont ennyi „késést” mért. Az eddigi próbákban (The Florist, I Want Your Sex, Casanova) a forrás 0-n kezdődött, ezért a hiba nem jött elő.

## Mi változott

- A mérőablakokat a program `-seek_timestamp 1` kapcsolóval valódi időbélyegre keresi, a forrásban és a kész fájlban egyaránt.
- A canadai munka valódi fájljain: a régi mérés 41,0 és 41,667 ms-ot adott, az új −1,0 és 0,0 ms-ot. A maradék a Matroska ezredmásodperces időbélyegeiből adódik, az 1,5 ms-os tűrésen belül.
- A mérés stage-sémája 2-re lépett, ezért egy újraindított munka a szinkronmérést újra elvégzi (a kódolást nem).

## Ellenőrzőlista

1. `GET /api/v1/capabilities` `backend_version`: `3.12.3`.
2. A Birds Without Names munka újraindítás után átmegy az `av-sync` ellenőrzésen.
