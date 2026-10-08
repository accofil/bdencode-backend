# BDEncode 3.0.1 kiadási jegyzet

A Release panelen beépített Aither- és nCore-profil választható.

## Változások

- **Beépített release-profilok.** A Release panel trackerlistája eddig csak a szerver profilfájljából (`/etc/bdencode/release-profiles.json`) töltődött, és a fájl alapból üres. Mostantól két profil beépített:
  - `aither` (Aither): 3–9 kép;
  - `ncore` (nCore): pontosan 3 kép.

  A csomag NFO-t, leírást, MediaInfót és képeket tartalmaz; dupe check nélkül, mert ahhoz a tracker címe és API-kulcsa kell. A profilfájl azonos azonosítójú bejegyzése a beépített profil helyére lép (például dupe-check címmel), a saját profilok mellettük megmaradnak.
- **Előválasztás.** Ha a munka Aither vagy nCore tracker-profillal készült, a Release panel ezt a profilt választja ki előre.
- **Tiszta képernyőképek a csomagban.** Trackerprofilos munkánál a csomag a tiszta, jelölés nélküli képeket használja (Aither 6, nCore 3), ha a profil képszámához elég van belőlük. Különben marad a comparison encode-oldali képe.
- **Dupe-check credential.** A `tracker.credential_name` csak dupe-check endpoint mellett kötelező; nélküle a profil credential nélkül is érvényes.
- **Doctor.** A `release_profiles` állapot a profilfájl saját profiljait számolja, és külön listázza a beépítetteket (`builtin_profiles`).

## Ellenőrzőlista

1. `GET /api/v1/capabilities` `backend_version`: `3.0.1`.
2. `GET /api/v1/release-profiles` az `aither` és az `ncore` profillal kezdődik.
3. Egy nCore-profillal készült kész munkánál a Release panel az nCore-profilt választja ki, és a csomagba 3 tiszta kép kerül.

## További dokumentáció

- [BDEncode 3.0 kiadási jegyzet](RELEASE_3_0.md)
