# Accofil BDEncode 4.0.1 kiadási jegyzet

Javítás: az automatikus crop nem hagy halvány, majdnem fekete sort a kép szélén, ha a felismert szél stabil, és csak 2 pixellel tér el a legszélesebb képtől.

## A hiba

Az automatikus crop eddig mindig a kulcskockás vizsgálat **legszélesebb vásznát** tartotta meg. Ezt egyetlen világos kocka is véglegesen eltolja. A Super Troopers 3 vizsgálatában a felismert szél 22 pixel volt felül és alul (7486 megfigyelésből 7485 támogatta), a legszélesebb vászon viszont 20 pixel, így a kész encode legfelső és legalsó sora szinte fekete maradt. Egy másik csoport ugyanebből a filmből 1036 soros képet adott ki, ez 22-es vágásnak felel meg.

## A javítás

- **Felismert szél használata.** Az automatikus crop a felismert szélig vág, ha egyszerre teljesül, hogy:
  - a felismert szél és a legszélesebb vászon minden élen legfeljebb 2 pixellel tér el;
  - a vizsgálat legalább 95%-a egyezik a felismert széllel;
  - a cím nem változó képarányú;
  - a munka nem egy elbukott crop-ellenőrzés utáni újrakezdés.

  Minden más esetben marad a legszélesebb vászon. A 8 pixelnél keskenyebb szegélyt továbbra sem vágja le, és a 4:2:0 páros vágási szabály érvényes.
- **Új ellenőrzés a teljes dekódoláson.** A meglévő ellenőrzés 2 pixel tűréssel dolgozik, ezért egy 22-re szűkített cropnál nem látta volna, ha a kép valóban a 20. sorig ér. Az új mérés élenként azt számolja, hogy az élt elérő kockák hány százaléka nyúlik túl rajta.
  - **25% vagy több**, és legalább fél másodpercnyi kockán: a kép valódi széle. A munka ellenőrzésre áll.
  - **Újraindítás után** a program minden képkockát megvizsgál, és a legszélesebb vásznat tartja meg.
  - **Kevesebbnél** a munka folytatódik, a számok pedig a `crop-verification.json` fájlba és egy `worker.crop-tight-reach` eseménybe kerülnek.
- **Mért értékek.** A Super Troopers 3-nál a felső élen 2,22%, az alsón 0,15%. A The Quiet és egy canadai cím vágása nem változik.

## Amit érdemes tudni

- A 25% egyetlen valódi cím mérésére és arra a feltevésre épül, hogy egy valódi képszélnél szinte minden kocka túlnyúlik. Valódi képszélt tartalmazó filmen nem lett kimérve. Ha a munka nem áll meg, az érintett kockákon legfeljebb 2 képsor veszhet el.
- Kézi cropnál az új szabály nem fut: ott a megadott érték és a meglévő 2 pixeles tűrés érvényes.
- **Ismert korlát.** Ha a felismert szél és a legszélesebb vászon megegyezik, nincs mit szűkíteni, így egy ott maradt halvány szélső sor az encode-ban marad (The Quiet).
- A futó munkák megtartják a korábbi vágásukat, mert a mentett crop-állapot érvényben marad. Ha egy kész vagy futó munkát újra szeretnél vágni, indítsd újra az előkészítést.

## Ellenőrzőlista

1. `GET /api/v1/capabilities` `backend_version`: `4.0.1`.
2. Új munkánál a `crop-policy.json` fájlban a `tightened_edges` mező mutatja, mely éleken követi a program a felismert szélt.
3. Az eseménynaplóban a „Crop-ellenőrzés: felismert szél” bejegyzés mutatja, hány kocka nyúlt túl a vágáson.
