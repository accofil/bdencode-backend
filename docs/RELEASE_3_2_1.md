# BDEncode 3.2.1 kiadási jegyzet

Javítás a 3.2.0 kulcsmentéséhez.

## Változás

- **A kulcsmentés eredménye olvasható az oldalon.** A kulcsmentő segédprogram `UMask=0077` alatt fut, ezért az állapotkönyvtár (`/var/lib/bdencode/credentials`) `0700` jogosultsággal jött létre. Az API így nem tudta kiolvasni az eredményt: a kulcs elmentődött, de a Rendszer oldal egy perc múlva „nem válaszolt” figyelmeztetést írt ki. A segédprogram most kifejezetten `0755`-re állítja a könyvtárat. A már meglévő könyvtárat a következő kulcsmentés kijavítja.

## Ellenőrzőlista

1. `GET /api/v1/capabilities` `backend_version`: `3.2.1`.
2. Egy kulcsmentés után a `GET /api/v1/ai-recommendation/status` `key_management.results` listájában megjelenik a kérés `applied` állapotban.

## További dokumentáció

- [BDEncode 3.2 kiadási jegyzet](RELEASE_3_2.md)
