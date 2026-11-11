# Accofil BDEncode 4.1.2 kiadási jegyzet

Javítás: a sávonkénti hangellenőrzés a hang első csomagjától méri a kezdetet és a hosszt, és elfogadja a klip-illesztéseknél már igazolt átfedést.

## A hiba

A Taffin (1988) munka a 4.1.1 után a sávonkénti hangellenőrzésnél állt meg: `delay_seconds = -11,011`, `duration_delta = 0,011 s` (tűrés 0,002 s). A kész fájl jó volt (a hang első csomagja 11,011 s-nál, a terv szerint), a mérés tévedett:

- A hangprobe a kezdetet az ffprobe stream-szintű `start_time`-jából vette. Ez a kész fájlban a konténer kezdete (0), mert a hang első csomagja kívül esik a vizsgálati ablakon. Ugyanez az ok, mint a 4.1.0-ban javított mux-tervnél.
- A hossz eltérése a film végi klip-illesztés 512 mintás (10,7 ms) átfedése. A folytonossági ellenőrzés ezt már illesztési átfedésként elfogadta, a hosszellenőrzés viszont nem tudott róla.

## A javítás

- A hangprobe a kezdetet az **első csomag** idejéből veszi, ha beolvasott csomagokat (a probe mindig beolvassa őket); a stream-szintű `start_time` csak tartalék. Így a hossz is a valódi hanghossz.
- A hosszellenőrzés tűrése a folytonossági ellenőrzés által igazolt illesztési rések és átfedések méretével bővül. A kezdet és a mintaszám tűrése nem változik: elveszett vagy hozzáadott hang továbbra is hibát ad.

## Ellenőrzőlista

1. `GET /api/v1/capabilities` `backend_version`: `4.1.2`.
2. A Taffin munka a sávonkénti hangellenőrzésen átjut.
