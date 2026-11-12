# Accofil BDEncode 4.1.3 kiadási jegyzet

Javítás: az összehasonlítás forráskockái és a mintaablakok első kockája nem lehet többé az L-SMASH első ugrásának elavult képe.

## A hiba

A Taffin (1988) munka a 4.1.2-vel végigment, de az összehasonlítás képminőség-mérése megállt: 24 mintából 11-nél a forráskocka teljesen fekete volt (mindegyik ugyanaz a kép, Y = 16), az encode pedig rendben. Ebből lett a „+24,15 Y-eltolás”, és a 8–20 dB-es PSNR. Az összehasonlító képeken is fekete forrás látszott.

Reprodukálva a lemez referenciájával:

- Az L-SMASH-Works egy **új forráspéldány első ugrásakor** elavult képet adhat vissza, ha az ugrás I-kockára vagy mellé esik. A 66334-es kocka önmagában kérve fekete volt (Y 16,0), bármely korábbi kocka után kérve pontos (Y 111,98, egyezik a folyamatos dekódolással). Minden későbbi ugrás pontos.
- Az összehasonlítás minden forráskockát külön `vspipe --start N --end N` hívással, új példányból kért. Ezért találta el minden I-minta és néhány B-minta ezt a hibát.
- A VMAF-mintaablakos szkriptek ugyanígy kezdenek. Ott az első ablak első kockája lehetett rossz (bemelegítés nélkül fekete volt, reprodukálva). A Taffin VMAF-ját ez nem érintette.

A többi szerver legutóbbi munkáinál nincs ilyen eltérés, a hiba ennél a lemeznél jött elő.

## A javítás

- Egy forráskockát a `vspipe` 8 kockával korábbról dekódol, és az ffmpeg csak az utolsót tartja meg (`select`). Az első, esetleg rossz kocka így sosem kerül a képre vagy a mérésbe. A köztes eredmények jelölői ezt rögzítik, így egy újrapróbált összehasonlítás újra kinyeri a kockákat.
- Az L-SMASH-es mintaablakos szkript (VMAF, CRF-keresés) az első ugrását egy eldobott kockára költi, 24 kockával az első ablak előtt.
- Mérve a Taffin referenciáján: mind a 11 korábban fekete minta helyes lett, és egyezik a folyamatos dekódolással.

A kódolás nem változik; a kész Taffin encode jó volt, csak a mérés és a forrásképek voltak hibásak.

## Ellenőrzőlista

1. `GET /api/v1/capabilities` `backend_version`: `4.1.3`.
2. Egy új összehasonlításban nincs fekete forráskocka, és nincsenek ismétlődő referencia-hashek.
