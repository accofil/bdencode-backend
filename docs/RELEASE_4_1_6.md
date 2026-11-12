# Accofil BDEncode 4.1.6 kiadási jegyzet

Javítás: a 4.1.5 egyik új tesztje miatt a 4.1.5 egyik szerverre sem települt fel. A program kódja nem változott, a 4.1.6 a 4.1.5 tartalmát hozza.

## A hiba

A szerveres telepítő a teljes tesztsort lefuttatja, és hiba esetén visszaállítja az előző kiadást. A `test_a_disc_window_is_read_from_its_clip_by_the_clip_s_stream_indexes` minden ffmpeg-hívást elemzőablaknak számolt. A szervereken telepítve van a tesseract, ezért ott a PGS-feliratok OCR-je is ffmpeg-et hív, így a teszt 6 helyett 12 hívást látott. A CI-ben és a fejlesztői gépen nincs tesseract, ott a teszt átment.

## A javítás

- A teszt csak az ablakolvasásokat számolja (amelyek WAV-ot írnak), és a testvértesztjéhez hasonlóan rögzíti, hogy nincs tesseract.
- Ellenőrizve a szerveren, telepített tesseract mellett.

## Ellenőrzőlista

1. `GET /api/v1/capabilities` `backend_version`: `4.1.6`.
2. A telepítés a szervereken hiba nélkül végigmegy.
