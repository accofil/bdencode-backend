# BDEncode 3.1.0 kiadási jegyzet

Gyorsabb crop-keresés, GPU nélkül is.

## Változások

- **Csak kulcsképkockák az előkészítésben.** A crop-keresés eddig a film minden képkockáját dekódolta: UHD-n GPU-val kb. 19, CPU-val kb. 56 perc. Most csak a kulcsképkockákat (Blu-rayen kb. másodpercenként egyet):
  - GPU-n egy menetben;
  - GPU nélkül a CPU-n párhuzamos időszakaszokban (legfeljebb 16, mindegyik legalább egy perc), mert a kulcsképkockás dekódolás egyszálú.

  A GPU/CPU választás automatikus, beállítás nem kell (`crop_hwaccel = "auto"`).
- **Mérés a La Femme Nikita UHD lemezén** (117 perc, 62,8 GB):

  | Keresés | Idő | Crop |
  |---|---|---|
  | minden képkocka, GPU | 19 perc | 262/260 |
  | minden képkocka, CPU | kb. 56 perc | 262/260 |
  | kulcsképkockák, GPU | 4,4 perc | 262/260 |
  | kulcsképkockák, CPU, 16 szakasz | 4,2 perc | 262/260 |

  A döntési kód a valódi, minden képkockát tartalmazó naplót másodpercenként egy mintára ritkítva is ugyanazt a cropot adja.
- **Ellenőrzés minden képkockán, a kódolás mellett.** A forrás integritás-ellenőrzése amúgy is minden képkockát dekódol, ezért most a cropot is ellenőrzi. Ha egy kulcsképkockák közé eső rövid, szélesebb snittből a crop képet vágna le, a munka a muxolás előtt felülvizsgálatra kerül. Megszakítás és újraindítás után az előkészítés minden képkockát dekódol. Eredmény: `analysis/crop-verification.json`.
- **Tartalék.** Ha a forrásban túl kevés a kulcsképkocka a döntéshez (24 megfigyelés alatt), a keresés minden képkockát dekódol, mint korábban.
- **Képarány-váltás küszöbe.** A legszélesebb vászon elfogadásához 10 másodpercnyi képidő kell. Eddig 240 megfigyelés kellett, ami minden képkockát tartalmazó naplón ugyanennyit jelentett. Így a küszöb a napló sűrűségétől független.
- A `crop-policy.json` új mezője a `scan` (`keyframes` vagy `full`).

## Ellenőrzőlista

1. `GET /api/v1/capabilities` `backend_version`: `3.1.0`.
2. Egy új munka előkészítésénél a „Most fut” panelen a crop-keresés néhány perc. A `logs/crop-detect-keyframes.log` létezik, a `crop-policy.json` `scan` mezője `keyframes`.
3. A kódolás után az `analysis/crop-verification.json` állapota `passed`.

## További dokumentáció

- [BDEncode 3.0.2 kiadási jegyzet](RELEASE_3_0_2.md)
