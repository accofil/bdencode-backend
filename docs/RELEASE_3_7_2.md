# BDEncode 3.7.2 kiadási jegyzet

Javítás: ha a képtárhely egy ideig nem érhető el, a munka magától újrapróbálja a feltöltést.

## Javítás

- **Automatikus újrapróbálás a képfeltöltésnél.**
  - **A hiba:** egyetlen kapcsolódási hiba (például „ImgBB could not be reached before upload”) azonnal `UPLOAD_FAILED` állapotba tette a munkát, és kézzel kellett újraindítani. Az At Close Range munka a canadai szerveren így állt meg.
  - **A javítás:** átmeneti hibánál a munka 30 mp, 1, 2, 5, 10 és 15 perc várakozással összesen hatszor magától újrapróbál. Ez kb. 33 perc. Csak ha a tárhely ezután sem érhető el, akkor áll meg `UPLOAD_FAILED` állapotban.
  - Minden újrapróbálás az eseménynaplóba kerül („A képfeltöltés N. kísérlete nem sikerült…”), az élő lépés pedig mutatja a várakozást.
  - A már feltöltött képeket nem küldi újra, és a kiválasztott tárhelyhez ragaszkodik. Ugyanazt a feltöltési checkpointot használja, mint a kézi újrapróbálás.
  - A várakozás közben a munka szüneteltethető és megszakítható; a worker leállítása is megszakítja a várakozást, és a következő indításkor a munka folytatódik.
  - **Nem próbálja újra:**
    - a végleges elutasítást (túl nagy fájl, hibás kulcs): ez továbbra is operátori ellenőrzést kér;
    - a helyi beállítási hibát (nincs tárhely beállítva).

## Ellenőrzőlista

1. `GET /api/v1/capabilities` `backend_version`: `3.7.2`.
2. Egy elérhetetlen tárhelynél az eseménynaplóban automatikus újrapróbálások látszanak, mielőtt a munka megállna.
