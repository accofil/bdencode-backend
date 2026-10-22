# BDEncode 3.11.2 kiadási jegyzet

Két javítás az első valódi remux MKV-próba nyomán (The Florist 2026 1080p).

## Foglalt kimeneti név: már a terv ellenőrzésekor kiderül

Eddig csak a kódolás legvégén, a kész kiadás áthelyezésekor derült ki, ha a `completed/<név>` mappában már van egy másik kiadás. A Florist-próbánál ez 8 óra kódolás után állította meg a munkát, mert ugyanezen a néven ott volt a lemezről készült kódolás.

- A **Terv ellenőrzése** és a **Jóváhagyás** most visszautasítja a foglalt nevet. A varázsló „A kimeneti név foglalt” üzenetet mutat, a **Név szerkesztése** gomb a névmezőre ugrik.
- Foglaltnak számít minden nem üres mappa ezen a néven; a régi kiadáshoz a program nem nyúl.
- Gépi „szabad” nevet nem talál ki: a számozott végződés (`.2`) nem érvényes kiadásnév. Adj meg másik nevet (általában a release-taggel, pl. `-TAG`), vagy helyezd át a régi kiadást.
- A kész kiadás tulajdonosi rekordja továbbra sem tartalmaz munka-azonosítót.

## Alapértelmezett sávok: csak az első hangsáv

A varázsló eddig a forrás „default” jelzőjét vette át. Matroskában ez a jelző 1, ha a muxer nem törli, ezért egy remux MKV-nál gyakran minden sáv „alapértelmezett”. A Florist kész fájljában így mindhárom német felirat alapértelmezett lett, és a lejátszó magától bekapcsolta volna valamelyiket.

- Új munkánál csak az **első hangsáv** alapértelmezett.
- A **feliratok** alapból nem alapértelmezettek. Kézzel, vagy a tracker-profil sávtervével (Aither/nCore) továbbra is bejelölhetők.
- A már elmentett beállítások (újraindítás, „Beállítások módosítása”) nem változnak.

## Ellenőrzőlista

1. `GET /api/v1/capabilities` `backend_version`: `3.11.2`.
2. Egy már létező kiadás nevével a **Terv ellenőrzése** „A kimeneti név foglalt” üzenetet ad.
3. Egy remux MKV varázslójában a feliratok „Alapértelmezett” jelölője üres, az első hangsávé be van jelölve.
