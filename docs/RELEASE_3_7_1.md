# BDEncode 3.7.1 kiadási jegyzet

Javítás: egy határeseti képminőség-mérés nem állítja meg a munkát.

## Javítás

- **A mintavételes PSNR/SSIM-mérés figyelmeztet, és csak hibás kódolásnál áll meg.**
  - **A hiba:** az összehasonlítás 24 mintáján mért értékek közül egyetlen, a határ alatti minta is ellenőrzésre állította a munkát („sampled native-YUV video metrics require review”). Az At Close Range kódolásánál (1080p x264, CRF 20) egy füstös, szemcsés jelenet B-képe SSIM 0,9279-et mért a 0,93-as határ alatt, miközben 2× nagyításban is azonos volt a forrással. A többi mérés bőven jó volt: átlag SSIM 0,968, átlag PSNR 44,2 dB.
  - A „Folytatás” sem segített: a comparison újramérte ugyanazt, és megint megállt.
  - **A javítás:** két szint lett.
    - A **minőségi irányérték** (mintánként SSIM ≥ 0,93, PSNR ≥ 35 dB; átlag SSIM ≥ 0,95, PSNR ≥ 38 dB; B–P SSIM-különbség ≤ 0,03) alá eső minta csak **figyelmeztetés**: a munka befejeződik. A figyelmeztetést az eseménynapló és a `video-metrics.json` (`quality_gate.status: passed_with_warnings`, `warnings`) rögzíti.
    - **Megállás** csak akkor van, ha a mérés hibás kódolásra utal:
      - mintánként SSIM < 0,80 vagy PSNR < 28 dB;
      - átlag SSIM < 0,90 vagy PSNR < 33 dB;
      - mérhetetlen minta;
      - egy színsík rendszeres eltolódása.
- **Elfogadás gomb.** Ha a munka mégis megáll, a munka oldalán egy kártya mutatja az érintett mintákat. Az **Elfogadom a mérést** gomb továbbengedi a munkát.
  - A döntés a `comparison/video-metrics-acceptance.json` fájlba kerül, a jelentésben pedig `accepted_by_operator` lesz.
  - Az elfogadás csak pontosan ezekre a mért képkockákra és eltérésekre érvényes, másik kódolásra nem.
  - API: `POST /api/v1/jobs/{id}/review/video-metrics`.

## Ha egy munka emiatt áll

1. Telepítsd a 3.7.1-et.
2. A munka oldalán megjelenik az ellenőrző kártya. Régi, határeseti eltérésnél a `POST /api/v1/jobs/{id}/resume` is elég: a comparison újrafut (kb. 3–5 perc), és most figyelmeztetéssel továbbmegy.

A kódolás nem fut újra.

## Ellenőrzőlista

1. `GET /api/v1/capabilities` `backend_version`: `3.7.1`.
2. Egy határeseti mintánál a munka befejeződik, az eseménynaplóban „A mintavételes képminőség egy-egy ponton a minőségi irányérték alatt maradt…” üzenettel.
