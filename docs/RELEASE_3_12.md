# BDEncode 3.12.0 kiadási jegyzet

**A hang helyét a program most a forráshoz méri, és az AC-3/E-AC-3 hang már nem késik.**

## Új: független hangszinkron-ellenőrzés

A hangra eddig minden ellenőrzés a tervhez mért: a csomagok kezdetét a tervezett kezdőidőhöz, a dekódolt kereteket a saját első keretükhöz. Ha maga a terv volt rossz, mindegyik átment. A 3.11.3-ban javított feliratcsúszás ugyanilyen hiba volt.

Az új ellenőrzés (`analysis/av-sync.json`) független ettől:
- a kész MKV minden hangsávjából és a forrás ugyanazon sávjából három 20 másodperces ablakot dekódol (a film 20, 50 és 80%-ánál), ugyanarra az időpontra igazítva;
- mono 48 kHz-en normalizált keresztkorrelációval megméri, mennyivel szól később vagy korábban a kész hang (egy minta 0,02 ms);
- **1,5 ms fölötti eltérésnél a munka megáll** („audio track … is … ms out of sync with the source”);
- ha egy ablak túl csendes, vagy nincs benne egyértelmű egyezés, azt kihagyja; ha egyik ablak sem dönthető el, figyelmeztetés kerül az eseményekbe, és a munka folytatódik.

Másolt és átalakított (FLAC, AC-3, E-AC-3, DTS) sávra egyaránt fut.

## Javítva: az AC-3 és E-AC-3 hang 5,3 ms-mal késett

Az új mérés azonnal megtalálta: az FFmpeg AC-3/E-AC-3 kódolója 256 minta (48 kHz-en 5,333 ms) előtöltést tesz a hang elé, és a kész MKV ezt lejátssza. A FLAC, a DTS és a másolat nem érintett.

- Az időterv most ismeri ezt az előtöltést. A hangot nem lehet korábbra tolni (az mkvmerge a nulla elé eső első keretet eldobná, az még nagyobb hibát okoz), ezért **a közös nullpont kerül korábbra**: a videó, a többi hang és a felirat egész ezredmásodperccel később kezdődik.
- Valódi mérés egy DTS-HD MA forráson: AC-3 és E-AC-3 −0,17 ms, FLAC 0,5 ms, DTS és másolat 0 ms. A maradék a Matroska ezredmásodperces időbélyegeiből adódik.
- Minden mkvmerge-eltolás egész ezredmásodperc. Az mkvmerge tört értéket el sem fogad.

## Javítva: fejezetek és a kezdőidő-ellenőrzés

- **Fejezetek:** a fejezetek a videóval együtt tolódnak. Ha a videó a kész fájlban néhány ezredmásodperccel később kezdődik, a fejezetek ugyanannyival később vannak, így a fejezetek kulcskockái a helyükön maradnak.
- **Kezdőidő-ellenőrzés:** a feliratok kimaradnak a végső kezdőidő-ellenőrzésből. Több sávos MKV-ban a feliratok `start_time`-ja a konténer kezdete, nem az első esemény, így ez téves hibát adhatott. A feliratok helyét a 3.11.3 óta az első csomaguk alapján ellenőrzi a sáv-QC.

## Ellenőrzőlista

1. `GET /api/v1/capabilities` `backend_version`: `3.12.0`.
2. Egy kész munka `analysis/av-sync.json` fájljában minden hangsáv `passed`, a `lag_ms` legfeljebb néhány tized ms.
3. AC-3/E-AC-3 hangos munkánál az `analysis/timeline-plan.json` `origin_seconds` értéke 5 ms-mal kisebb a videó kezdeténél, és a videó eltolása `+5`.
