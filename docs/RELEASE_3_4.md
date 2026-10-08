# BDEncode 3.4.0 kiadási jegyzet

Megszakított munka újraindítása módosított beállításokkal.

## Változás

- **Beállítások módosítása újraindításkor.** Egy beállított, megszakított munkánál az **Újraindítás** ablakban két gomb van:
  - **Újraindítás ugyanígy:** a jóváhagyott beállításokkal vissza a várólistára, mint eddig.
  - **Beállítások módosítása:** a munka a beállítóvarázslóba kerül vissza, a korábbi beállításokkal kitöltve. A kódolás csak az új beállítások jóváhagyása után indul.

  Mindkét esetben megmarad minden checkpoint, amelyet a változás nem érint: azonos forrásnál és playlistnél a referencia-remux, a crop és a forrás-ellenőrzés. Ami a megváltozott beállításoktól függ (például a kódolás egy új CRF-fel), az újrafut.
- API: `POST /api/v1/jobs/{id}/restart` új mezője a `reconfigure` (alapértelmezés: `false`). `true` esetén a munka `AWAITING_SELECTION` állapotba kerül, a mentett `selection` megmarad. A `job.restart` esemény `reconfigure` mezője ezt rögzíti.

## Ellenőrzőlista

1. `GET /api/v1/capabilities` `backend_version`: `3.4.0`.
2. Egy megszakított, beállított munkánál a **Beállítások módosítása** után a Beállítások fülön a varázsló a korábbi értékekkel nyílik meg; a jóváhagyás után a munka `READY` állapotba kerül.

## További dokumentáció

- [BDEncode 3.3 kiadási jegyzet](RELEASE_3_3.md)
