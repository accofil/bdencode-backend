# BDEncode 3.12.2 kiadási jegyzet

Javítás: egy lemezes munka a forrás ellenőrzésénél ok nélkül megállt.

## Mi történt

A canadán a Birds Without Names (2017) lemez munkája „source video integrity diagnostics require review” üzenettel megállt. A forrás teljes visszadekódolása hibátlanul lefutott (177 805 kocka). A „hiba” a lemez beolvasásakor kiírt `bdj.c:801: BD-J check: Failed to load libbluray.jar` sor volt.

Ez azt jelenti, hogy a gépen van Java, de hiányzik a libbluray BD-J csomagja, így a lemez Java-menüi nem futnak. A videóra, a hangra és a feliratokra ennek nincs hatása. A program eddig csak a másik változatot (`Failed to load JVM library`, vagyis amikor nincs Java) ismerte ártalmatlannak, ezt az újat ismeretlen hibának vette.

## Mi változott

- Mindkét BD-J üzenet ártalmatlan környezeti figyelmeztetés („bdj_runtime_unavailable”), a munkát nem állítja meg.
- A munka valódi naplóin ellenőrizve: a referencia-remux naplójában csak ez a két sor volt, és most egyik sem igényel ellenőrzést.

## Ellenőrzőlista

1. `GET /api/v1/capabilities` `backend_version`: `3.12.2`.
2. A Birds Without Names munka újraindítás után túljut a forrás-ellenőrzésen.
