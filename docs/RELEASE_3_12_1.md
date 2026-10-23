# BDEncode 3.12.1 kiadási jegyzet

Javítás: egy valódi lemez-remux MKV scanje tévesen figyelmeztetett, és a figyelmeztetés angolul jelent meg a magyar felületen.

## A téves figyelmeztetés

A Casanova S01 (EPSiLON) 1080p remux scanje ezt írta: „The video track carries no SOURCE_ID tag … make sure the file is an untouched disc remux, not an encode.”

A fájl valódi lemez-remux: 2017-ben mkvmerge v14-gyel muxolták, a sávnevek BDInfo-stílusúak, a videóban nincs kódoló-aláírás. A `SOURCE_ID` címkét csak a MakeMKV írja. A release-csoportok remuxaiban, amelyeket a lemez m2ts fájljaiból mkvmerge-dzsel készítenek, ez a címke általában nincs meg, így a hiánya semmit nem bizonyít.

## Mi változott

- A `SOURCE_ID` alapú figyelmeztetés megszűnt. A korábban elmentett scanekben a felület már nem mutatja.
- Helyette a program a videófolyam első öt kockáját (dekódolás nélkül) átnézi, és **kódoló-aláírást** keres: `x264 - core …`, `x265 (build …`, HandBrake. Az otthoni újrakódolások ezt mindig beleírják.
- Néhány kiadó maga is x264/x265-tel mastereli a lemezt. A The Florist 2026 lemez is ilyen: `bluray_compat=1`, `bitrate=30000`, `nal_hrd=vbr`. Az ilyen folyamot az x264 `bluray_compat=1`, illetve az x265 `uhd-bd=1` beállításáról ismeri fel, és nem figyelmeztet rá.
- Valódi fájlokon ellenőrizve:
  - Casanova, Leatherheads (VC-1), The Florist és I Want Your Sex remux: nincs figyelmeztetés;
  - a BDEncode saját x264 és x265 kódolásai: figyelmeztet.
- Az MKV-scan figyelmeztetései (kódoló-aláírás, kihagyott borítókép) magyarul jelennek meg.

## Ellenőrzőlista

1. `GET /api/v1/capabilities` `backend_version`: `3.12.1`.
2. Egy csoport-remux MKV scanje nem ad „SOURCE_ID” figyelmeztetést.
3. Egy újrakódolt MKV scanje „A videófolyamban x264 kódoló aláírása van …” figyelmeztetést ad.
