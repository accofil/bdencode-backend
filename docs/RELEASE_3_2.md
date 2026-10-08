# BDEncode 3.2.0 kiadási jegyzet

AI-kulcs a weboldalról, és Claude a második AI-tanácsadó.

## Változások

- **API-kulcs a Rendszer oldalon.** Az **AI tanácsadó** kártyán szolgáltatónként egy rejtett mezőbe írható a kulcs (**Kulcs mentése**, **Kulcs törlése**). Parancssor és telepítő-újrafuttatás nem kell. A kulcs ugyanúgy titkosított systemd credential lesz, mint eddig. Az út:
  1. az API egyszeri kérést ír a memóriában lévő `/run/bdencode-api` mappába;
  2. a `bdencode-credentials.path` elindítja a root segédprogramot (`/usr/local/libexec/bdencode-credentials`);
  3. a segédprogram törli a kérést, a kulcsot `systemd-creds encrypt`-tel, a standard bemenetén titkosítja, majd beköti az API-hoz, és újraindítja az API-t;
  4. az eredmény, kulcs nélkül, a `/var/lib/bdencode/credentials/status.json` fájlba kerül.

  Az oldal kivárja az újraindulást, és kiírja az eredményt.
- **Claude (Anthropic) mint AI-tanácsadó.** Új credential: `anthropic-api-key`. Alapértelmezett modell: `claude-opus-5-5`.
  - A hívás a hivatalos `anthropic` Python-csomaggal megy, ez új függőség (`anthropic>=1.11,<2`). A telepítő a PyPI-ről telepíti.
  - Strukturált kimenet (`output_config.format`), `effort: high`, és szerveroldali tartalékmodell (`fallbacks: "default"`, `server-side-fallback-2026-07-01` béta).
  - Claude egy kérésben legfeljebb 16 null típusú mezőt enged. Ezért csak a megváltoztatott mezőket adja vissza, szövegként. A backend a mező típusa és tartománya szerint alakítja át őket, a hibásakat figyelmeztetéssel elveti. Ezután ugyanaz a helyi x264/x265 validátor ellenőriz, mint az OpenAI-nál.
- **Szolgáltató és modell választása.** A Rendszer oldalon:
  - alapértelmezett szolgáltató, vagy automatikus mód (az első beállított kulcs, OpenAI elöl);
  - szolgáltatónként felülírható modellnév.

  Ezek a `state/ai-settings.json` fájlba kerülnek, és újraindítás nélkül érvényesek. Ha mindkét kulcs megvan, a varázslóban munkánként is választható a szolgáltató.
- **Érthetőbb hibák.** Elutasított kulcs (401), hiányzó jogosultság (403), nem elérhető modell (404) és korlátozás (429) esetén a hibaüzenet megnevezi a szolgáltatót és a teendőt.
- `doctor --json`: `ai_recommendation.providers` (OpenAI és Claude credential-állapot). Az `uninstall.sh --purge-credentials` már nyolc credentialt töröl, az `anthropic-api-key`-t is.
- A 3.1.1 kiadási jegyzet sorrendje javítva: előbb megszakítás, aztán telepítés, végül újraindítás.

## Ellenőrzőlista

1. `GET /api/v1/capabilities` `backend_version`: `3.2.0`.
2. `systemctl is-enabled bdencode-credentials.path`: `enabled`.
3. Rendszer → AI tanácsadó: egy kulcs mentése után a sor **Kulcs beállítva**, a `status.json` utolsó eredménye `applied`, és a kulcs nem szerepel benne.
4. A varázsló AI-kártyáján egy javaslat kérése a kiválasztott szolgáltatóval működik.

## További dokumentáció

- README 5.2.1. pont: az AI-tanácsadó beállítása
- [BDEncode 3.1 kiadási jegyzet](RELEASE_3_1.md)
