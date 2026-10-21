# BDEncode 3.10.0 kiadási jegyzet

Új: **remux MKV is lehet forrás**, és a **feliratok nyelvét a program a felirat szövegéből ismeri fel** (képes, PGS feliratnál szövegfelismeréssel, OCR-rel). A sávelemzés egy hibás részlet miatt már nem áll le.

## Remux MKV forrás

- Az **Új kódolás** oldalon a forrásmappák mellett a `.mkv` fájlok is megjelennek (külön csempével, „MKV remux” jelöléssel).
- Csak **lemez eredetű remux** fogadható el: pontosan egy Blu-ray videósáv (AVC, HEVC, VC-1 vagy MPEG-2). Streaming eredetű fájl (például Dolby Vision profil 5) nem fogadható el; a hibaüzenet megmondja, miért.
- Az MKV egyetlen címként jelenik meg (playlist `00001`). A borítóképeket és a csatolmányokat a program kihagyja. A szöveges feliratokat (SRT, ASS) megtartja, és a varázslóban „szöveges felirat (nem PGS)” jelölést kapnak.
- A referencia a forrás bájtra azonos másolata. A program a forrásba soha nem ír. Innentől minden lépés ugyanúgy megy, mint lemezről.
- Az MKV sávnyelv-címkéje (`language`) ugyanolyan bizonyíték, mint a lemez MPLS/CLPI címkéje. Hangsávnál ezt a beszédfelismerés ellenőrzi, feliratnál a szövegfelismerés.

## Feliratnyelv a felirat szövegéből

- A sávelemzés a mintavett részletekből kiolvassa a felirat szövegét:
  - **PGS** (képes) feliratnál a program a felirat képeit maga rajzolja ki, és `tesseract`-tal (angol+magyar latin betűkészlettel) olvassa el; folyamonként legfeljebb 30 feliratsort;
  - **SRT/ASS** feliratnál közvetlenül a szöveget olvassa.
- A nyelvet a leggyakoribb szavak alapján határozza meg (16 nyelv). Kevés szövegnél (12 szó alatt) vagy szoros versenynél a nyelv „nem egyértelmű”, és nincs javaslat.
- **A varázslóban** minden feliratsornál látszik: „Nyelv a felirat képeiből (OCR): …”. Ha ez eltér a forrás címkéjétől, egy **Elfogadás** gomb jelenik meg. A javaslat a „Minden javaslat elfogadása” gombbal is elfogadható.
- **Kódoláskor**, ha a nyelvet nem adtad meg kézzel, a felismert nyelv bizonyítékként számít:
  - címke nélküli (`und`) feliratnál a felismert nyelvet kapja (75% felett);
  - egymásnak ellentmondó címkéknél a felismerés dönt;
  - egyező címkéknél a címke marad, eltérő felismerésnél figyelmeztetés kerül a nyelvi jelentésbe.
- A telepítő mostantól felteszi a `tesseract-ocr`, `tesseract-ocr-eng` és `tesseract-ocr-hun` csomagot. Ha a gépen nincs OCR, a varázsló ezt kiírja, és a feliratnyelv a címkéből jön, mint eddig.

## A sávelemzés nem áll le egy hibás részlet miatt

- Egy olvashatatlan részlet vagy felirat nem buktatja el többé az egész elemzést. A kihagyott részek a `skipped` listába kerülnek, az elemzés a többiből készül el. Ez volt a The Florist lemezen a hiba oka.
- A szöveges feliratok minden csomagja eseménynek számít, ezért egy sűrű SRT felirat többé nem „forced” javaslatot kap.
- Az elemzési séma 2-es verzióra lépett: a régi scanek elemzése a következő scankor újra elkészül.

## Kipróbálva (nvme, valódi forrásokon)

| Forrás | Hang | Felirat |
|---|---|---|
| The Florist BD | deu, eng | PGS: deu (OCR), forced: nincs esemény |
| The Florist 1080p remux MKV | eng | ugyanaz, mint a lemezen |
| I Want Your Sex 2160p remux MKV | eng (TrueHD, E-AC-3) | SRT: eng, fra (szöveg); PGS: eng (OCR) |

Teljes kódolás MKV-forrásból (DV/HDR10+, szöveges felirat a kész MKV-ban) még nem futott; ez a következő, szerveren végzett próba.

## Ellenőrzőlista

1. `GET /api/v1/capabilities` `backend_version`: `3.10.0`.
2. `tesseract --list-langs` a szerveren: `eng`, `hun`.
3. Az **Új kódolás** oldalon megjelennek a `.mkv` fájlok; egy remux scanje a varázslóig jut.
4. A varázsló feliratsorainál megjelenik a „Nyelv a felirat …” sor.
