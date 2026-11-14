# Accofil BDEncode 4.3.3 kiadási jegyzet

Javítás: a mintafájl (Sample) akkor is a kész mappába kerül, ha a munkaterület és a kész mappa külön csatolás.

## A hiba

A The Last Whale Singer remux a QC és a képfeltöltés után UPLOAD_FAILED állapotba került: „Invalid cross-device link”. A minta (`sample.mkv`) a munkaterületről (`jobs/…/work/sample`) a kész mappába (`completed/…/Sample`) költözött volna egyszerű átnevezéssel. A worker systemd-egysége a `jobs` és a `completed` könyvtárat külön `ReadWritePaths` csatolásként kapja, a kettő között pedig átnevezni nem lehet, még ha ugyanazon a lemezen vannak is.

## A javítás

A minta a célmappába másolódik egy ideiglenes névvel, ott atomikusan átneveződik, és csak ezután törlődik a munkaterületről. Ha az átnevezés közvetlenül is lehetséges, továbbra is az történik.

## Ellenőrzőlista

1. `GET /api/v1/capabilities` `backend_version`: `4.3.3`.
2. A Whale Singer remux a feltöltés újrapróbálásával elkészül, a mintája a `Sample` mappában van.
