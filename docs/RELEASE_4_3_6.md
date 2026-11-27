# Accofil BDEncode 4.3.6 kiadási jegyzet

Javítás: AVI külső forrásból illesztett hang csúszása.

## A hiba

A Swept from the Sea illesztésénél a magyar hang („Érzelmek hullámain.avi”) végig kb. 5,5 másodperccel késett a képhez képest. A képkockák megfeleltetése közben hibátlannak látszott: 163 433 kocka egyezett, 0,99-es hasonlósággal.

Az AVI-ban a kimerevített képet üres képkocka jelöli. Ebben a fájlban az 1–132. kocka üres (a nyitókép 5,3 másodpercig áll), és a végén is van 43. Az FFmpeg az üres kockákból nem dekódol képet. A lenyomat `-fps_mode passthrough` módban készült, így ezek kimaradtak. A térkép viszont a dekódolt kocka sorszámát veszi időnek (n / fps). Így minden kocka 132-vel kisebb sorszámot kapott a valódinál, és minden képhez a 132 kockával korábbi hang került: a film idején ez 5,5 másodperc késés. Állandó képkockaszámmal újraillesztve az eltolás −64-ről +68 kockára változott, a különbség pontosan a 132 üres kocka.

## A javítás

- Az AVI forrás lenyomata állandó képkockaszámmal készül (`-fps_mode cfr -r <fps>`). Az üres kocka helyén az előző kép ismétlődik, ahogy egy lejátszó is mutatja, így az n. kocka valóban n / fps időpontban van.
- A többi forrás (MKV, MP4, DVD) lenyomata nem változik.
- Az AVI lenyomat szakaszjelzője új bemenetet kapott, így a meglévő munkák újra elkészítik a lenyomatot és a térképet. A régi, csúszó térkép jóváhagyása így nem marad érvényben.

## Ellenőrzőlista

1. `GET /api/v1/capabilities` `backend_version`: `4.3.6`.
2. A Swept from the Sea illesztést újra kell indítani. Az új térkép eltér a régitől, ezért újra jóvá kell hagyni, a mintákat pedig meg kell hallgatni.
