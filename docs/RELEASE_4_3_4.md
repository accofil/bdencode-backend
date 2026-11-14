# Accofil BDEncode 4.3.4 kiadási jegyzet

Javítás: egy félbemaradt próbálkozás után ottmaradt üres `Sample` mappa nem akasztja meg a véglegesítést.

## A hiba

A The Last Whale Singer remuxnál a 4.3.3 előtti, sikertelen mintaáthelyezés létrehozta a kész mappában az üres `Sample` mappát. Az újrapróbálás véglegesítése a mappa tartalmát még a minta elkészülte előtt ellenőrizte, és az üres mappát hibának vette: „the Sample directory may hold only the release's own sample”.

## A javítás

Az üres `Sample` mappát az ellenőrzés elfogadja; a mintát utána a minta-lépés teszi bele. Ha a mappában bármi más van, mint a kiadás saját mintája, az továbbra is hiba.

A Whale Singer remux már elkészült: az üres mappát eltávolítottam, és a véglegesítés lefutott.

## Ellenőrzőlista

1. `GET /api/v1/capabilities` `backend_version`: `4.3.4`.
