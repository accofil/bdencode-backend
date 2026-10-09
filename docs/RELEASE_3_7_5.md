# BDEncode 3.7.5 kiadási jegyzet

Két javítás, mindkettő valódi munkán derült ki.

## TrueHD hossz-ellenőrzés Debian 12-n

- **A hiba:** a Debian 12 ffprobe-ja (FFmpeg 5.1) a TrueHD hangcsomagoknál nem írja ki a csomag hosszát (`duration_time`). A QC ezt hiányos bizonyítéknak vette, és a munka „audio duration evidence is incomplete for …:truehd” üzenettel megállt. Ez történt a Blue Streak munkával az nvme-n.
- **A javítás:** ha a csomaghossz hiányzik, a program a csomagok időbélyegeinek átlagos távolságából számolja ki. TrueHD-nél ez 1/1200 s, és csak a legutolsó csomag végét befolyásolja.
- **Ellenőrzés a Blue Streak valódi fájljain:**
  - forrás és kódolás: 6 776 020 csomag;
  - mindkettő hossza 5646,684 s, ami egyezik a videóval;
  - a régi kód már az első csomagnál elbukott.

## Release-csomag: tiszta, nem fekete képernyőképek

- **A hiba:** ha a munkának kódoláskor nem volt trackerprofilja, a release-csomag a comparison feliratozott képeire esett vissza („ENCODE | 0-BASED INDEX … | I-FRAME” fejléccel). Ráadásul a film első és utolsó, teljesen fekete képkockáját is beválogatta (At Close Range, Aither-csomag: 01.png és 09.png).
- **A javítás:**
  - Tiszta képek hiányában a csomag a kész MKV-ből veszi ki a képkockákat, a comparison időpontjain, a film hosszában elosztva. HDR-nél SDR-re leképezett nézetet használ.
  - A kivett képek gyorsítótárba kerülnek: `<data_root>/cache/release-screenshots`.
  - A szinte egyszínű (fekete, elsötétülő) képeket a program kihagyja, és helyettük a következő időpontot próbálja.
- A már elkészült csomagok nem változnak. Az At Close Range Aither-csomagját a csomag törlésével és újra elkészítésével lehet tiszta képekkel újraépíteni.

## Ellenőrzőlista

1. `GET /api/v1/capabilities` `backend_version`: `3.7.5`.
2. Egy TrueHD-hiba miatt NEEDS_REVIEW állapotban álló munka a `POST /api/v1/jobs/{id}/resume` hívás után újrafuttatja a QC-t (a mért fájlokat újrahasznosítva), és továbbmegy.
