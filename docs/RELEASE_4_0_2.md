# Accofil BDEncode 4.0.2 kiadási jegyzet

Új: a forrásválasztónál kipipálható, hogy csak teljes lemezek látsszanak.

## Mi változott

- A **Szerver tárhely** lépés eszköztárában új **Csak teljes lemezek** jelölőnégyzet van.
- Bekapcsolva a lista elrejti az MKV-fájlokat (remuxot és kész encode-ot is). A Blu-ray mappák és a sima mappák megmaradnak, mert beljebb lépni csak a mappákon át lehet.
- A szűrő együtt működik a névkereséssel.
- A beállítást a böngésző megjegyzi, ezért újratöltés után is érvényben marad. Alapértelmezetten ki van kapcsolva.
- Üres mappánál a felület jelzi, hogy a szűrő rejtett el valamit.

## Amit érdemes tudni

- Csak a felület változott, a szerver és a munkák nem. Futó munkát a frissítés nem érint.
- A „teljes lemez" itt a szerver által Blu-ray forrásként felismert mappa. A hang- és felirat-illesztésnél (`fit`) is bekapcsolható, de ott a kész encode MKV-k is eltűnnek a listáról, ezért alapból ki van kapcsolva.

## Ellenőrzőlista

1. `GET /api/v1/capabilities` `backend_version`: `4.0.2`.
2. Új munka › forrás: a jelölőnégyzet látszik, és az MKV-fájlok eltűnnek, ha kipipálod.
