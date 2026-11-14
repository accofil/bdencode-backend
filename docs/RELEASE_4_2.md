# Accofil BDEncode 4.2.0 kiadási jegyzet

Új opció a külső forrásból illesztett hangsávokhoz: a forrásból hiányzó részek csend helyett a film saját hangjából is pótolhatók.

## Miért

Ha a külső forrás (DVD, WEB-DL) egy része nincs meg, például rövidebb a stáblistája, a hozzá illesztett sáv eddig ott digitálisan néma volt. A The Last Whale Singer (2025) magyar WEB-DL-jéből illesztett sávban a stáblista alatt 9 ilyen kiesés volt (0,5–2,2 s, összesen 11,3 s), miközben az angol sávban végig szólt a zene.

## Az opció

A varázslóban a külső hangsáv beállításai között új mező van: **„A forrásból hiányzó részek”**.

- **Csend** (alapértelmezett, mint eddig).
- **Pótlás a film hangjából:** a film bármelyik saját hangsávja választható.

A pótlás:

- a kiválasztott sáv, ugyanannyi csatornára keverve, mint az illesztett sáv;
- minden kiesésnél olyan hangerővel, hogy a kiesés két oldalán (2–2 s) ugyanolyan hangos legyen, mint az illesztett hang. Ha a két oldal néma, az egész sáv átlagos szintjével. A szintillesztés legfeljebb ±12 dB;
- 25 ms-os áttűnéssel kapcsolódik az illesztett hanghoz (csendnél 5 ms marad, mint eddig);
- a jóváhagyó kártyán és a nyilvános naplóban látszik: hány rész, hány másodperc, mekkora szintillesztés.

A pótlás beállításának módosítása az illesztést nem ismétli meg, csak a sávot készíti el újra, és új jóváhagyást kér. A szinkronellenőrzés változatlan, csak az illesztett részekben mér. A meghallgatható részletek már a pótolt sávból készülnek.

Zenénél (stáblista) hasznos. Beszédnél a másik nyelv hallatszana, ott maradjon a csend.

## Kipróbálva

A The Last Whale Singer két forrásán az app saját lépéseivel:

- A pótolt részek pontosan a kész fájl 9 kiesésén vannak.
- A szintillesztés −0,6 és +2,8 dB között mozgott, mindenhol a két oldal alapján.
- A határokon nincs ugrás vagy kattanás: a legnagyobb mintaugrás akkora, mint a környező zenéé.
- **Fontos:** ennél a filmnél a magyar WEB-DL stáblistája alatt más hanganyag szól, mint a Blu-ray angol sávjában; ±50 ms-on belül sehol nem egyeznek. A pótlás ezért itt az angol stáblista zenéjét hozza be. Döntés előtt hallgasd meg.

## Ellenőrzőlista

1. `GET /api/v1/capabilities` `backend_version`: `4.2.0`.
2. Egy illesztős munkánál a külső sáv beállításai között megjelenik „A forrásból hiányzó részek” mező.
3. Pótlással a jóváhagyó kártya kiírja a pótolt részeket és a szintillesztést.
