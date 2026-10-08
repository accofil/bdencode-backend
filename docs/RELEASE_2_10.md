# BDEncode 2.10 kiadási jegyzet

Kezelhetőségi kiadás. A felületről követhető, mi fut éppen, és a felülvizsgálatot kérő munkák is a felületről oldhatók meg, kézi API-hívás nélkül.

## Változások

- **Az éppen futó részfolyamat saját százalékkal.** A munka oldalán a teljes folyamat sávja alatt „Most fut” panel jelenik meg. Ezt mutatja:
  - a lépés nevét, saját százalékát, az eltelt és a hátralévő időt;
  - ha a lépés aránya nem mérhető (például a nyelvfelismerés), mozgó sávot;
  - a mellette párhuzamosan futó feladatokat külön sávval (forrásindex, forrás-integritás ellenőrzése).

  A kezdőlap aktív munka kártyáján ugyanez egy sorban látszik. Értesítés nincs, a panel kétmásodpercenként frissül.
- **Kódolási adatok.** Kódolás közben a panel mutatja:
  - a sebességet (fps és a valós idő hányada);
  - a már kiírt méretet;
  - a várható videóméretet, méretcélnál a céllal együtt. Ha a becslés a keresés 4%-os tűrésén belül van, „célon belül” jelzést kap, egyébként azt, hogy hány százalékkal van a cél felett.
- **Lépések időtartama.** Az Áttekintés lapon minden befejezett lépés (helyi másolat, remux, crop-keresés, nyelvellenőrzés, CRF-keresés, kódolás, mux, QC, összehasonlítás, feltöltés) a kezdési idejével és időtartamával szerepel, összesítve. A megszakított vagy felülvizsgálatra került lépés ezt jelzi. Ha a worker egy lépés közben állt le, a következő induláskor a lépés „megszakítva” bejegyzéssel záródik, így nem marad beragadt sáv.
- **Nyelvi felülvizsgálat a felületen.** Ha a lemez nyelvjelölése és a hangfelismerés eltér, vagy egy felirat nyelve nem olvasható ki, a munka oldalán kártya jelenik meg. Minden megtartott hang- és feliratsávnál mutatja a lemez szerinti és a felismert nyelvet a biztonsággal, és felkínálja a valószínű nyelvet. A megerősítés a nyelveket a beállításba írja, és a munka visszakerül a sorba. A kész előkészítő lépések (helyi másolat, remux, crop) újrahasznosulnak, a már felismert sávokat nem kell újra elemezni.
- **Képfeltöltési hibák a felületen.** `UPLOAD_FAILED` vagy feltöltési felülvizsgálat esetén a kártya mutatja:
  - a rögzített tárhelyet, a már feltöltött képek számát és a legnagyobb képet;
  - tárhelyenként, hogy a képek elférnek-e.

  Három lehetőség van:
  - **Újrapróbálás ugyanoda.** Akkor tiltott, ha a rögzített tárhely nem fogadja a legnagyobb képet.
  - **Újrakezdés más beállítással.** Más tárhelyet vagy képkészletet lehet választani. A régi feltöltési checkpoint a privát `logs/upload-resets` mappába kerül, a régi képek a régi tárhelyen maradnak.
  - **Befejezés képek nélkül.**

  A választás egy szakaszfájlba kerül, nem a kiválasztásba. Így a kiválasztás hash-éhez rögzített előkészítési jelentések érvényesek maradnak, és nem indul újrakódolás.
- **Csak SDR (vagy csak natív) képek feltöltése.** Az új munka oldalán és a varázslóban választható a feltöltött képkészlet:
  - minden kép;
  - csak SDR-nézet;
  - csak natív kép.

  HDR-filmnél az egyik nézet elhagyása felezi a feltöltendő képek számát. A helyi PNG-k mind megmaradnak. Az első kép után a feltöltés tárhelyenként párhuzamosan, egyszerre három képpel halad.
- **CPU-keret és éjszakai mód a felületen.** A Rendszer oldalon beállítható:
  - a nappali CPU-keret (10–100%);
  - egy éjszakai idősáv saját kerettel. Az idősáv a böngésző időzónájában értendő, mert a WSL órája UTC-n is járhat.

  A mentett beállítást egy root segéd (`bdencode-cpu-policy`) alkalmazza a worker futásidejű `CPUQuota`-jaként. Mentéskor egy path unit azonnal elindítja, egy ötperces időzítő pedig időben vált nappali és éjszakai keret között. Futó kódolásnál is azonnal érvényes: a folyamat a szálait megtartja, a kernel az új arányt adja neki. Az oldalsáv és a kezdőlap a ténylegesen érvényes keretet mutatja a rögzített 80% helyett.
- **A leggyengébb VMAF-szakaszok.** A kész fájl mintavett VMAF-ablakai időkóddal együtt kerülnek a comparison manifestbe. A Comparison lap a leggyengébbtől sorolja őket sávval és minimummal. A három leggyengébb kiemelést kap, és a 60 másodpercen belüli képpárok „Gyenge VMAF-szakasz közelében” jelzést kapnak. A `video-vmaf.json` a Fájlok lapon is letölthető.

## Új API-végpontok

- `GET /api/v1/jobs/{id}/live`: a futó lépés (arány, idők, mérőszámok, párhuzamos feladatok), a befejezett lépések és a szerver órája.
- `GET /api/v1/jobs/{id}/review`: mit kér a felülvizsgálat (`language`, `upload`, `upload_failed`, `comparison_timeout`, `other`) és a megoldáshoz szükséges adatok.
- `POST /api/v1/jobs/{id}/review/languages`: a megerősített ISO 639-2 nyelvek sávonként; a munka `READY` lesz.
- `POST /api/v1/jobs/{id}/reset-upload`: feltöltés elölről, opcionálisan más tárhellyel vagy képkészlettel, illetve feltöltés nélkül.
- `GET` és `PUT /api/v1/system/cpu-policy`: a nappali keret, az éjszakai idősáv és az éppen érvényes érték.

## Frissítés

A napi időzítő magától telepíti, ha a sor üres (README 11.1.). Az új rendszerszintű egységeket (`bdencode-cpu-policy.service`, `.path`, `.timer`) a telepítő hozza létre és engedélyezi.

## Ellenőrzőlista

1. `GET /api/v1/capabilities` `backend_version`: `2.10.0`.
2. `systemctl is-active bdencode-cpu-policy.path bdencode-cpu-policy.timer`: mindkettő `active`.
3. A Rendszer oldalon a CPU-keret mentése után néhány másodpercen belül `/var/lib/bdencode/cpu-policy/status.json` `state: applied`. `systemctl show -p CPUQuotaPerSecUSec bdencode-worker.service` az új értéket mutatja.
4. Futó munkánál a munka oldalán megjelenik a „Most fut” panel, és a lépés százaléka nő.

## További dokumentáció

- [Felhasználói és telepítési útmutató](../README.md) (8. Az aktuális lépés és a felülvizsgálatok, 9.2. Videó comparison, 14.1. CPU-keret)
- [BDEncode 2.9 kiadási jegyzet](RELEASE_2_9.md)
