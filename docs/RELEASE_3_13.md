# BDEncode 3.13.0 kiadási jegyzet

Új: átméretezett képek a BBCode-ban, és külön Aither-féle összehasonlítás.

## A BBCode csomag (`comparison.bbcode`)

Eddig a csomag minden feltöltött képet teljes méretben, fájlnév szerinti sorrendben listázott, így minden encode a saját forrása elé került. Mostantól:

- **400 px széles képek**: minden kép `[url=…][img=400]…[/img][/url]`, kattintásra a képtárhelyen teljes méretben nyílik meg.
- **Párok egymás mellett, időrendben**: „01 · B-frame · 00:14:06”, alatta a forrás és az encode, ebben a sorrendben.
- Utánuk a **tiszta képernyőképek** (tracker-munkáknál) és a **hangspektrumok** (forrás | encode), szintén 400 px-en.
- A tracker-profilok saját részei (Aither képernyőképek és napló, nCore képek és linkek) változatlanok maradtak.

## Külön Aither comparison (`comparison-aither.bbcode`)

Minden feltöltött munkánál, tracker-profiltól függetlenül, elkészül egy önálló, beilleszthető Aither-blokk:

```
[comparison=Source, Encode]forrás1 encode1 forrás2 encode2 …[/comparison]
```

- Teljes méretű képcímek, a feltöltött B és P párokból (I-képek nélkül), időrendben, ahogy az Aither összehasonlítási útmutatója kéri.
- Tíznél kevesebb párnál megjegyzés kerül alá.
- A **Comparison** lapon két gomb van: **BBCode másolása (400 px)** és **Aither comparison másolása**. A fájl a kész kiadás `comparison` mappájába is bekerül.

Valódi feltöltéssel kipróbálva (Casanova S01, ImgBB): 10 pár időrendben, 6 képernyőkép, a hangspektrum, az Aither-blokkban 20 képcím.

A már elkészült munkák BBCode-ja nem változik; az új formátum a következő feltöltéstől érvényes.

## Ellenőrzőlista

1. `GET /api/v1/capabilities` `backend_version`: `3.13.0`.
2. Egy feltöltéses munka Comparison lapján megjelenik mindkét másolás gomb.
3. A `comparison.bbcode` képei `[img=400]`-zal szerepelnek, a `comparison-aither.bbcode` egyetlen `[comparison=Source, Encode]` blokk.
