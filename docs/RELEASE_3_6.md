# BDEncode 3.6.0 kiadási jegyzet

A felület magyarul és angolul is használható.

## Változások

- **Nyelvválasztó.** A bal oldali menü alján a **HU / EN** gombbal válthatsz nyelvet; a választást a böngésző megjegyzi. Első alkalommal a böngésző nyelve dönt: magyar böngészőben magyar, minden más esetben angol a felület.
- **A teljes felület kétnyelvű:**
  - minden oldal, a beállítóvarázsló, a munka oldala és a párbeszédablakok;
  - a beépített kódolási súgó, amelyben angolul angol szavakra lehet keresni;
  - a gombok akadálymentes nevei.

  A dátumok és a számok a választott nyelv szerint jelennek meg.
- **A backend is a választott nyelven válaszol.** A felület minden kérésnél elküldi a nyelvet (`Accept-Language`). Ezen a nyelven jönnek:
  - a tracker-szabályok figyelmeztetései;
  - a zaj- és Aither-presetek leírásai;
  - a színadat-ellenőrzés, az API-kulcsok és az AI-tanácsadó hibaüzenetei;
  - az AI-javaslat szövege is (a modell a választott nyelven indokol).

  Fejléc nélkül, például parancssorból, minden magyar marad, mint eddig.
- **Futó lépések.**
  - A worker a lépések nevét és részleteit („Most fut” panel, „Lépések időtartama”) mindkét nyelven tárolja, és az API a kért nyelven adja vissza. A régebbi, csak magyar bejegyzések változatlanul megjelennek.
  - A kódolás állapotsora a worker naplójában angol lett („Encoding video: 12.3% · … · projected video size ~19.2 GB”); a felület a választott nyelven mutatja, a régi magyar sorokat is.
- **A trackernek szóló anyagok nyelve nem változik.** A BBCode és az NFO nyelvét továbbra is a tracker határozza meg, nem a felület.
- **README:** az angol útmutató az angol gombneveket használja, és mindkét változat leírja a nyelvválasztót.

## Ellenőrzőlista

1. `GET /api/v1/capabilities` `backend_version`: `3.6.0`.
2. A menü alján az **EN** gombra kattintva a teljes felület angol lesz, és frissítés után is az marad.
3. Angol felületen egy nCore-profilos munka **Terv ellenőrzése** gombja angol figyelmeztetéseket mutat.

## További dokumentáció

- [BDEncode 3.5 kiadási jegyzet](RELEASE_3_5.md)
