# Accofil BDEncode 4.3.1 kiadási jegyzet

Javítás: a remux QC elfogadja, ha egy hangsáv a lemez hangja után néhány tized másodperc digitális csenddel folytatódik.

## A hiba

A The Last Whale Singer (2025) német lemezéből készült remux a QC-nél megállt: „03-audio.dtsma decodes differently from the disc”. A videó, a feliratok és a szinkron rendben voltak.

- Az eac3to egy klip hangját a klip végéig írja ki; a referencia (libbluray) a lejátszási lista végpontjánál áll meg. Ezért a remux angol DTS-HD MA sávja 38 912 mintával (0,81 s) hosszabb lett, és ez a rész a kép vége után szól.
- A referencia hosszáig a két hang bitre azonos volt (azonos MD5), a többlet csupa nulla minta (−91 dB).
- A QC a teljes dekódolt hang MD5-jét vetette össze, ezért ezt eltérésnek látta.

## A javítás

Ha egy hangsáv MD5-je eltér (egyetlen klipes listánál), a QC tovább vizsgálja:

- a referencia mintaszámáig a kész sáv MD5-je azonos-e a lemezével;
- a többlet a végén legfeljebb 2 s-e, és digitálisan néma-e (legfeljebb −90 dB).

Ha mindkettő teljesül, a QC elfogadja, és a jelentésbe beírja, hány ms csend maradt a végén. Bármilyen más eltérés (más minta, hang a többletben, hosszabb többlet) továbbra is hibát ad. A több klipes listák illesztési kezelése nem változott.

## Ellenőrzőlista

1. `GET /api/v1/capabilities` `backend_version`: `4.3.1`.
2. A Whale Singer remux QC-je átmegy, a jelentésben „811 ms of digital silence” szerepel.
