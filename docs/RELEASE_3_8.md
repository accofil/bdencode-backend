# BDEncode 3.8.0 kiadási jegyzet

Új: a kész kódolás értékelése, javasolt beállításokkal.

## Értékelés kártya

A kész munka **Comparison** fülének tetején egy **Értékelés** kártya jelenik meg. Ezt mutatja:

- **ítélet:** Átlátszó, Jó, Elfogadható vagy Gyenge;
- **fő mérőszámok:** a kész fájl mintavett VMAF-ja (átlag és 1% low), SSIM és PSNR a 24 képpáron, megtakarítás a forráshoz képest, videó bitráta;
- **megállapítások:** például bőkezű bitráta, kicsi megtakarítás, lágyabb B-képek, a leggyengébb VMAF-ablak időpontja, bitpontos hangsávok;
- **javasolt változtatás hasonló lemezhez,** például CRF 17,5 → 18,5, becsült méretváltozással.

### AI-val vagy rögzített szabályokkal

- **Ha van beállított AI-kulcs** (OpenAI vagy Claude, a Rendszer oldalon): az első megnyitáskor az AI egyszer értékel, és az eredmény elmentődik a munka `analysis/comparison-evaluation.json` fájljába.
  - Az AI csak a mért számokat kapja, képet és fájlnevet nem.
  - A válasza szigorú sémát követ. A javaslatait a program a megengedett mezőkre és tartományokra szűri: CRF 8–30, AQ-erősség, Psy-RD, Psy-RDOQ, deblock, B-képek, referenciák, qcomp, AQ-mód.
  - Ha az AI hibázik, a rögzített szabályok eredménye marad, a hibaüzenettel együtt.
- **Kulcs nélkül:** a program előre rögzített küszöbökből és szabályokból számol (`comparison_evaluation.THRESHOLDS`):
  - Átlátszó: VMAF átlag ≥ 95 és 1% low ≥ 90;
  - Jó: ≥ 93 / ≥ 87;
  - Elfogadható: ≥ 90 / ≥ 83.
  - Ha az eredmény átlátszó, és a többlet nem látszik (átlag ≥ 95, 1% low ≥ 91), magasabb CRF a javaslat: +1, ha a megtakarítás 20% alatti, különben +0,5.
  - Gyenge pontnál (1% low < 85, ablak < 88 vagy minta SSIM < 0,95) eggyel alacsonyabb CRF a javaslat.
  - A méretbecslés CRF-lépésenként x264-nél kb. 15%, x265-nél kb. 21%.
- A kártyán bármikor kérhető **Újraértékelés AI-val** vagy **Szabályalapú értékelés**.
- API:
  - `GET /api/v1/jobs/{id}/evaluation`: elmentett vagy rögzített szabályos értékelés;
  - `POST /api/v1/jobs/{id}/evaluation` `{"use_ai": true|false}`.

## Első valódi eredmény

**Late Fame** (nvme, 1080p x264, CRF 17,5, slow, film):

- **Ítélet:** átlátszó.
  - VMAF átlag 95,27, 1% low 91,94;
  - SSIM 0,9875, PSNR 48,4 dB;
  - egy kézzel megnézett B-képpáron a szemcse 99%-a megmaradt.
- **Méret:** csak 15%-kal kisebb a forrásnál (20,5 Mb/s a 24,0 Mb/s helyett); 0,443 bit/pixel, ami bőkezű.
- **Javaslat:** CRF 18,5, kb. −13% méret.

## Ellenőrzőlista

1. `GET /api/v1/capabilities` `backend_version`: `3.8.0`.
2. Egy kész munka Comparison fülén megjelenik az Értékelés kártya.
