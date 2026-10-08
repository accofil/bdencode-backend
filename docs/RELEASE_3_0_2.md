# BDEncode 3.0.2 kiadási jegyzet

A verziószám a felületen is látszik.

## Változások

- **Verziószám az oldalsávban.** A BDEncode felirat alatt minden oldalon ott a szerveren futó verzió (például `v3.0.2`). Eddig csak a Rendszer oldal Backend kártyája mutatta.
- **Figyelmeztetés régi felületnél.** Frissítés után egy már nyitott böngészőlap a régi felületet futtatja tovább, amíg újra nem töltöd. Ha a lap verziója eltér a szerverétől, az oldalsáv ezt jelzi („Ez a lap a v3.0.1 felületét futtatja, a szerveren a v3.0.2 van.”), és az **Oldal frissítése** gomb betölti az újat.

## Ellenőrzőlista

1. `GET /api/v1/capabilities` `backend_version`: `3.0.2`.
2. Az oldalsávban a BDEncode felirat alatt `v3.0.2` látszik.

## További dokumentáció

- [BDEncode 3.0.1 kiadási jegyzet](RELEASE_3_0_1.md)
