# BDEncode 3.6.2 kiadási jegyzet

Javítás: hosszú GOP-os kódolásnál az összehasonlítás nem talált elég I-képpárt, és a munka ellenőrzést kért.

## Javítás

- **Kevesebb I-pár, ha a mintákból nem jön ki több.**
  - **A hiba:** az összehasonlítás 24 képpárt választ (alapból 8 I, 8 P, 8 B), mindegyiket úgy, hogy a forrásban és a kódolásban is ugyanolyan típusú képkocka legyen. Mindezt 24 rövid, 2 másodperces mintaablakból. Hosszú GOP-os kódolásnál (például `keyint 240`, `bframes 16`) csak minden tizedik másodpercben vagy vágásnál van I-képkocka, és ennek a forrás I-képkockájával is egybe kell esnie. Ennyi mintában ez ritka, ezért a munka „bounded comparison sampling could not find the required same-frame I/P/B pairs” üzenettel ellenőrzést kért.
  - **A javítás:** ha az I-párok nem jönnek ki, a program lépésenként kevesebb I-párral próbálja (legalább eggyel), a felszabaduló helyekre P- és B-párok kerülnek. A párok száma, az azonos típus és az egyenletes eloszlás szabálya nem változik. A csökkentést a munka eseménynaplója rögzíti („Az összehasonlítás N I-képpárt használ…”).
  - Ha egyetlen egybeeső I-képkocka sincs, a munka továbbra is ellenőrzést kér.
- **Mérés egy valódi munkán** (At Close Range, 1080p x264, `keyint 240`, `bframes 16`): a mintákban 11 egybeeső I-képkocka volt, az egyenletes eloszlással ebből 7 használható. Az új kiválasztás 24 párt ad (7 I, 9 P, 8 B), mind azonos típusú; a régi elakadt.

## Ha egy munka emiatt áll

1. Szakítsd meg (**Műveletek → Megszakítás**).
2. Telepítsd a 3.6.2-t.
3. Indítsd újra (**Újraindítás → Újraindítás ugyanígy**).

A kész kódolás és az ellenőrzések megmaradnak; csak az összehasonlítás fut újra.

## Ellenőrzőlista

1. `GET /api/v1/capabilities` `backend_version`: `3.6.2`.
