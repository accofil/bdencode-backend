# BDEncode 2.9 kiadási jegyzet

Az első valódi UHD-job (La Femme Nikita, 117 perc) elemzéséből következő fejlesztések.

## Változások

- **Méretcél az automatikus CRF-hez** (`auto_crf.target_size_gb`). A cél ennél a jobnál 20–25 GB-os videó volt. A kézi kalibráció az alapprofillal 21,8 GB-ot jósolt, a valódi beállításokkal (pl. aq-mode 3) 18,9 GB lett. Méretmódban a worker a mintákat pontosan a végleges beállításokkal kódolja, VMAF helyett a méretüket a teljes filmre vetíti, és log-lineáris modellel (kb. 21% CRF-lépésenként, két próba után a film saját meredekségével) a **legkisebb CRF-et** választja, amely még belefér. A felületen „Minőségcél (VMAF)” vagy „Méretcél (videó, GB)” választható; méretcélnál 24 mintával. A statisztika méretmódban nem olvas gigabájtot VMAF-ként.
- **Várható videóméret kódolás közben.** Az állapotüzenet 10%-tól mutatja („várható videóméret ~19.2 GB”). Ez az FFmpeg által kiírt bájtokból számolt vetítés; a valódi filmnél 11%-nál 15%-kal alábecsült, kb. 80%-tól pontos volt.
- **Mintavett VMAF a kész fájlon.** Az összehasonlítás 12 × 2 mp-en VMAF-ot mér a kész MKV-ra. Mindkét oldal VapourSynth-ablakszkript: a referencia gráfja és a kész fájl L-SMASH-sel (`bdencode-vmaf --encoded-script`), így nincs teljes dekódolás. Az eredmény a `comparison/video-vmaf.json`-ba kerül (átlag, harmonikus átlag, 1%-os alsó érték, ablakonként), hash-sel rögzítve, publikálva. Tájékoztató érték: sikertelen mérés „unavailable”, a minőségkapu továbbra is az SSIM/PSNR. Valódi eszközökkel ellenőrizve a valódi UHD-mintán: CRF 12-es próbakódolásra az ablakok 91–98 közöttiek, tehát a képkockák illeszkednek.
- **Párhuzamos lépések a kódolás után.** A valódi UHD-jobnál ez a szakasz kb. 1 óra 50 perc volt, egy parancs egyszerre. Mostantól egyszerre legfeljebb négy fut:
  - egy hangsáv független próbái, hashei és hangerő-elemzései (eddig 19,5 perc egymás után);
  - a kész fájl ellenőrzései, köztük a 20 perces teljes dekódolás;
  - a referencia és az enkód képtípus-vizsgálata (18 + 12 perc).

  A hibák csak akkor jelentkeznek, ha minden párhuzamos feladat befejeződött. A parancsnapló (`commands.jsonl`) írása ismét zárral védett.
- **Kisebb összehasonlító PNG-k.** A publikált képek soronként választott PNG-szűrővel készülnek (`-pred mixed`). Ez veszteségmentes, 8–15%-kal kisebb fájlt ad, képenként kb. 2 mp többletidővel. A valódi film legnagyobb képe 34,4 MB helyett 31,5 MB lett, ez már az ImgBB 32 MB-os korlátjába is belefér.
- **A végleges feltöltési hibák felülvizsgálatot kérnek.** A 4xx válaszok (a 408 és 429 kivételével: túl nagy fájl, érvénytelen kulcs, tiltás) a szolgáltató indoklásával felülvizsgálatra küldik a jobot. Eddig `UPLOAD_FAILED` „retry is safe” volt az eredmény, pedig az újrapróba ilyenkor nem segíthetett.
- **Crop-mód a felületen.** A crop-szerkesztő mutatja, hogy az automatikus (teljes filmes) crop vagy egy kézi felülírás az aktív, és egy gombbal vissza lehet állni automatikusra.

## Frissítés

A napi időzítő magától telepíti, ha a sor üres (README 11.1.).

## Ellenőrzőlista

1. `GET /api/v1/capabilities` `backend_version`: `2.9.0`.
2. Egy kész job `comparison/video-vmaf.json` állapota `measured`, és a `video-comparison.json` `vmaf` rekordja hivatkozik rá.
3. Méretcéllal a `crf-search.json`-ban `mode: size`, a választott CRF vetített mérete a célon belül van.

## További dokumentáció

- [Felhasználói és telepítési útmutató](../README.md) (7.4.1. Automatikus CRF, 9.2. Videó comparison)
- [BDEncode 2.8.2 kiadási jegyzet](RELEASE_2_8_2.md)
