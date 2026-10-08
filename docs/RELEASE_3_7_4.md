# BDEncode 3.7.4 kiadási jegyzet

Javítás: a 3.7.3 előtt elkészült ellenőrzések nem futnak újra.

## Javítás

- **A forrás teljes dekódolása nem ismétlődik.**
  - **A hiba:** a 3.7.3 a képvágás-ellenőrzést képkockánkénti naplózásra állította, és ezzel új kulcsot kapott a teljes forrásdekódolás ellenőrzőpontja. Egy korábban elkezdett munka emiatt, ha újra a kódolás szakaszba lépett, az órás dekódolást még egyszer lefuttatta volna.
  - **A javítás:** a 3.7.3 előtt lefutott dekódolás eredménye érvényes marad. A régi, halmozott maximumot naplózó vizsgálat legalább olyan szigorú volt, ezért az ítélete áll.
- **A klipillesztések szigorú dekódolása nem ismétlődik.** A 3.7.3 előtti jelentés csak az illesztéseket fedte le, a film végét nem. Ez a jelentés elfogadott marad, a film végére nem fut külön dekódolás.

A 3.7.3 többi ellenőrzőpontja nem változott, így más szakasz sem fut újra.

## Forrásválasztás: olvasható mappanevek

- A hosszú mappanevek (például `El.Circulo.S01E02.1080p.NF.WEB-DL…`) kilógtak a csempéjükből, és rácsúsztak a szomszédokra; a kilógó szöveg a szomszéd csempe kattintható részét is eltakarta.
- A név most legfeljebb két sorba tördelődik, és a csempén belül marad.
- A teljes név egérrel rámutatva látszik.

## Ellenőrzőlista

1. `GET /api/v1/capabilities` `backend_version`: `3.7.4`.
