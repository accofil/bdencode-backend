# Accofil BDEncode 4.1.4 kiadási jegyzet

Javítás: a hang folytonossági ellenőrzése két egymást követő időbélyeg különbségénél két időegységnyi (tick) kvantálási hibát enged, nem egyet.

## A hiba

A Clementine (2019) munka (MKV remux forrás, DTS-HD MA) a QC-ben megállt: „decoded audio sample-cursor continuity failed for audio:1”. A forrás DTS-sávjában 24 277 darab 64 mintás (1,333 ms) „hézagot” talált, a kész E-AC-3 hang viszont hézagmentes volt.

Valójában nem hiányzott hang:

- A dekódolt mintaszám pontosan 529 900 × 512, a végpont egyezik, és a kódolt hang is ennyi (+1024 minta enkóder-kitöltés, a tűrésen belül).
- A forrás-MKV időbélyegei 1 ms-os időalapban vannak, és a pontos mintaidővonalhoz képest −1,667 és +0,333 ms között szórnak, sodródás nélkül. Például a 160 ms-os kocka 159-en van, a következő 171-en.
- Egy időbélyeg tehát akár egy ticket is tévedhet, két egymást követő különbsége így kettőt. Az ellenőrző csak egy ticket (48 mintát) engedett.

## A javítás

- A kockánkénti tűrés 2 tick (1 ms-os időalapnál 96 minta, 90 kHz-esnél 2 minta). A Clementine összes időbélyegén: a lépések −32, +16 és +64 mintásak, egy sem jelez.
- Egy kiesett vagy hozzáadott hangkocka (DTS 512, AC-3 1536 minta) továbbra is hibát ad, és a teljes mintaszám és a végpont ellenőrzése sem változik.
- A már elkészült bizonyítékot (a dekódolt kockák listáját) a QC újra értékeli, nem kell újradekódolni.

## Ellenőrzőlista

1. `GET /api/v1/capabilities` `backend_version`: `4.1.4`.
2. A Clementine munka a hang folytonossági ellenőrzésén átjut.
