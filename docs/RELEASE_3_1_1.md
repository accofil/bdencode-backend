# BDEncode 3.1.1 kiadási jegyzet

Többklipes playlistek: a klipváltásnál keletkező remux-üzenetek nem állítják meg a munkát, ha a forrás a váltásnál ép.

## A hiba

A The Last Boy Scout UHD lemezének 2-es playlistje két klipből áll: a fő film (00004, 6327,9 s) és egy 1,04 másodperces záróklip (00459), zökkenőmentes (seamless) átmenettel. A libbluray a playlistet egyetlen folyamként játssza le. A klipváltásnál az időbélyegek ugranak, ezért az FFmpeg minden sávra „timestamp discontinuity” üzenetet ír. Az előző klip utolsó, levágott csomagjára pedig „Packet corrupt”, a TrueHD-sávnál „mlpparse: Parity check failed” üzenetet. Az előkészítés ezt forrássérülésnek vette, és a munka felülvizsgálatra került („source corruption appeared in the retained command history”).

A lemez fájljai épek (minden klip 6144 bájtos egységekre végződik). A referencia szigorú dekódolása a klipváltáson át minden sávon hibátlan volt. A kódolás melletti integritás-ellenőrzés a javítás nélkül az időbélyeg-ugrások miatt minden többklipes playlistet megállított volna.

## Változások

- **Klipváltások ellenőrzése.** Ha a playlist több klipből áll, a remux-naplóban klipváltásonként egy időbélyeg-ugrás csoport van. A csoport előtti és utáni néhány üzenet a váltáshoz tartozik. Az előkészítés minden váltás körül (−20 s … +10 s) szigorúan dekódolja a referencia videóját és minden hangsávját (`-xerror -err_detect explode`).
  - Ha ez hibátlan, a váltáshoz tartozó üzenetek nem számítanak forrássérülésnek: sem az előkészítésnél, sem a kódolás melletti integritás-ellenőrzésnél.
  - Az eredmény az `analysis/clip-joins.json` fájlban van, és a munka eseménynaplójába `worker.clip-joins-verified` bejegyzés kerül.
- **Ami továbbra is megállítja a munkát:**
  - a klipváltástól távoli sérülés;
  - a hibás dekódolás a váltásnál;
  - ha a naplóban több időbélyeg-ugrás csoport van, mint ahány klipváltás;
  - egyklipes címnél bármilyen sérülés-jelzés, a korábbiak szerint.

## Ha egy munka emiatt áll

Előbb szakítsd meg a munkát (Műveletek → Megszakítás): a felülvizsgálatra váró munka visszatartja a frissítést. Utána telepítsd a 3.1.1-et, majd indítsd újra a munkát (Újraindítás). Az előkészítés a meglévő referenciát használja, nem remuxol újra, és elvégzi a klipváltások ellenőrzését.

## Ellenőrzőlista

1. `GET /api/v1/capabilities` `backend_version`: `3.1.1`.
2. Egy többklipes playlistnél az `analysis/clip-joins.json` `verified` mezője `true`, és a munka továbbmegy.

## További dokumentáció

- [BDEncode 3.1 kiadási jegyzet](RELEASE_3_1.md)
