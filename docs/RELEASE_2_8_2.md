# BDEncode 2.8.2 kiadási jegyzet

A Catboxra feltöltött összehasonlító képek ellenőrzése most már sikerül.

## A hiba

A 2.8.1 a nagy UHD-képeket helyesen a Catboxra irányította. A feltöltés után a BDEncode letölti a képet, és bájtonként összeveti a helyi fájllal. Ez a letöltés minden alkalommal elbukott („Catbox verification failed after upload”), mert a `files.catbox.moe` válasz nélkül bontja a kapcsolatot, ha a kérés a Python httpx könyvtár alapértelmezett azonosítójával (`python-httpx/…`) érkezik. Bármely más azonosítóra rendesen válaszol. A Catbox így éles környezetben eddig sosem működött. A tesztek ezt nem fogták meg, mert szimulált hálózattal futnak.

## Változás

- **Minden képtárhely-kérés a BDEncode nevével megy:** az ImgBB, a Freeimage és a Catbox feltöltése és visszaellenőrzése is `BDEncode/<verzió> (+https://github.com/accofil/bdencode-backend)` azonosítót küld.

## Ellenőrzőlista

1. `GET /api/v1/capabilities` `backend_version`: `2.8.2`.
2. Egy Catboxra irányított feltöltés `COMPLETED` állapotban zárul, a `comparison/uploads.json` minden képénél `provider: catbox`.

## További dokumentáció

- [BDEncode 2.8.1 kiadási jegyzet](RELEASE_2_8_1.md)
