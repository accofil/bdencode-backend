# Accofil BDEncode 4.0.3 kiadási jegyzet

Javítás: a referencia-remux már nem bukik el olyan lemezen, amelynek a playlistje hang nélküli bevezető klippel indul.

## A hiba

A Taffin (1988) Blu-ray 4-es playlistje egy kb. 11 másodperces, hang nélküli klippel (00010.m2ts, 712 KB) kezdődik, és csak utána jön a film (00004.m2ts). Az ffmpeg alapértelmezett vizsgálati ideje ennél rövidebb, ezért a DTS-hangot „0 csatorna, 0 Hz" paraméterekkel ismerte fel, a Matroska-író pedig visszautasította a fejlécet (`sample rate not set`). A munka a referencia-remuxnál FAILED állapotba került, még az encode megkezdése előtt. A forrás hibátlan volt.

## A javítás

- A lemez egész címét megnyitó parancsok (referencia-remux és a tervező) `-analyzeduration 120M` bemeneti opciót kapnak, vagyis 120 másodpercnyi vizsgálati időt.
- **Mért értékek** a Taffin lemezén: 10 s-nál még hibás, 20 s-tól helyes (48 kHz, 2 csatorna). Önmagában a `-probesize` nem segít. A 120 s hatszoros ráhagyás.
- Az ffmpeg abbahagyja a vizsgálatot, amint minden stream ismert, ezért normál lemezen a nagyobb ablak semmibe sem kerül (0,13 s a 0,19 s-mal szemben a Taffinon).
- Ellenőrzés a szerveren: a javított parancs alakja a 4-es playlistből 20 másodpercet másolt Matroskába, a streamek (H.264, DTS 48 kHz / 2 csatorna, PGS) rendben voltak. A teljes, 30 GB-os remuxot nem futtattam le.

## Amit érdemes tudni

- A már elbukott munkát újra kell indítani, az magától nem javul.
- A sáv-elemzés ablakai ugrással (`-ss`) dolgoznak, és ugyanezen a lemezen sikerrel futottak, ezért azokat nem módosítottam.

## Ellenőrzőlista

1. `GET /api/v1/capabilities` `backend_version`: `4.0.3`.
2. A Taffin (1988) munka újraindítása után a referencia-remux lefut.
