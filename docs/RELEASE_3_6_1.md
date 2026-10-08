# BDEncode 3.6.1 kiadási jegyzet

Javítás Debian 12-es szerverekhez: átalakított hangsávnál a minőségellenőrzés tévesen állította meg a munkát.

## Javítás

- **A hangkeretek folytonosságának ellenőrzése Debian 12-n is működik.**
  - **A hiba:** átalakított hangsávnál (FLAC, AC-3, E-AC-3, DTS) a minőségellenőrzés a forrás, a köztes sáv és a kész MKV minden hangkeretét összeveti. Ehhez a keretek mintavételi frekvenciáját is kérte. A Debian 12 FFmpeg-je (5.1) ezt a mezőt nem adja ki, ezért ott minden ilyen munka „decoded audio frame evidence is incomplete” üzenettel ellenőrzést kért, pedig a hang hibátlan volt.
  - **A javítás:** ha az `ffprobe` egyetlen keretnél sem adja meg a frekvenciát, az ellenőrzés a sáv frekvenciáját használja. A bizonyítékban ezt a `frame_sample_rates_reported: false` mező jelzi.
  - **Változatlan szigor:** ha az `ffprobe` megadja a frekvenciát és az eltér, vagy csak néhány keretnél hiányzik, az ellenőrzés továbbra is megállítja a munkát. A minták száma, a végpont és a rések vizsgálata nem változott.
- **Mérés egy valódi, Debian 12-es munkán:** az At Close Range DTS → FLAC sávján a forrás és a kész MKV mintaszáma pontosan egyezik (331 079 168 minta), és nincs bennük rés vagy átfedés.

## Ha egy munka emiatt áll

Ha egy munka emiatt „Ellenőrzést kér” állapotban áll, a frissítő nem telepít, amíg ez a munka a sort foglalja. Ezért:

1. szakítsd meg a munkát (**Műveletek → Megszakítás**);
2. telepítsd a 3.6.1-et;
3. indítsd újra a munkát (**Újraindítás → Újraindítás ugyanígy**).

A kész kódolás és a már elkészült ellenőrzések megmaradnak; csak a hangellenőrzés értékelése fut újra.

## Ellenőrzőlista

1. `GET /api/v1/capabilities` `backend_version`: `3.6.1`.
2. Debian 12-es gépen egy átalakított hangsávos munka átmegy a minőségellenőrzésen.
