# Accofil BDEncode 4.3.5 kiadási jegyzet

Javítás: Blu-ray LPCM hangsáv bitmélysége, amikor az ffprobe nem adja meg.

## A hiba

A The Adventures of Sherlock Holmes DISC01 kódolása a referencia-remux előtt megállt, ezzel az üzenettel: „Blu-ray PCM stream audio:4352 has an unsupported bit depth: 0”. A szervereken futó FFmpeg 5.1 (Debian 12) ffprobe-ja a `pcm_bluray` sávoknál `bits_per_sample=0` értéket ad, a `bits_per_raw_sample` mezőt pedig üresen hagyja. A szkenner a 0-t bitmélységnek vette. Ez volt az első LPCM hangú lemez éles használatban.

## A javítás

- A 0 nem bitmélység. A szkenner az első pozitív értéket veszi: `bits_per_raw_sample`, `bits_per_sample`, végül a natív lemezolvasó értéke.
- Ha egy `pcm_bluray` sávnak így sincs bitmélysége, a szkenner a sáv saját PID-jének első csomagját olvassa be a playlist klipjeiből. Az a klip jön először, amelyik a legtöbb játékidőt adja. A 4 bájtos LPCM-fejléc negyedik bájtjának felső két bitje megadja a bitmélységet: 16, 20 vagy 24.
- Ha a fejléc sem olvasható, a munka ugyanúgy ellenőrzést kér, mint eddig. A rendszer nem találgat.

A Sherlock lemez mindkét LPCM sávja a fejléc szerint 16 bites, sztereó, 48 kHz-es (`03c0 3140`).

## Ellenőrzőlista

1. `GET /api/v1/capabilities` `backend_version`: `4.3.5`.
2. A Sherlock DISC01 munkát újra kell szkennelni: a munka régi `scan.json` fájlja még 0-t tartalmaz.
