# BDEncode 3.7.3 kiadási jegyzet

Stabilitás: a munka mérési zajon, ártalmatlan eszköz-figyelmeztetésen, FFmpeg-verzióeltérésen vagy átmeneti hibán nem áll meg. Ezeket figyelmeztetésként rögzíti (eseménynapló + a szakasz JSON-jelentése), és továbbmegy. Megállás csak valódi hibánál van. Mellette: 10 feltöltött képpár és javított forrásválasztás.

## Kevesebb feltöltött kép

- A comparison továbbra is 24 képpárt mér, de csak **10 pár** kerül fel. A program elsősorban B-képeket választ, ha azok elfogynak, P-, végül I-képeket, mindegyiket a film hosszában elosztva.
- Mellettük mindig felkerülnek a hangelemzés képei, trackerprofilnál a kötelező tiszta képernyőképek is.
- A tracker-BBCode összehasonlító blokkja ugyanazt a 10 párt használja.

## Új munka: forrásválasztás

- Másik lemez kijelölésekor a forrás átváltott, de a munka neve az első lemezé maradt, és a böngésző ezt el is mentette. Most a név követi a kijelölt lemezt, amíg kézzel át nem írod.
- A kijelölés egy gombbal törölhető.

## Nem áll meg többé…

- **Nyelvellenőrzés:**
  - ha a lemez címkéi egyeznek: a címkét használja, akkor is, ha a nyelvfelismerő mást hall (dalok, feliratok, makronyelvek, pl. yue/zho, hrv/srp);
  - ha a felismerő nem fut: a lemez címkéjét használja;
  - ha semmi sem nevezi meg a nyelvet: „und” jelölést ad, ami a kódolás után is javítható.
  - Megállás csak akkor van, ha a címkék egymásnak ellentmondanak, és a felismerő magabiztosan egyiket sem igazolja.
- **mkvmerge:** a figyelmeztetései (sync frame, időbélyeg, PGS, fejléc) nem állítják meg. Elveszett, sérült vagy kihagyott adatnál és kilépési kód 2-nél továbbra is megáll.
- **Teljes dekódolás és forrásnapló:** a klipillesztésnél vágott csomagot vagy TrueHD paritáshibát a forrásellenőrzés már igazolta; a 5.1-es FFmpeg formátumát is felismeri, és a film végét is illesztésként kezeli. Valódi dekódolási hibánál továbbra is megáll.
- **Képvágás-ellenőrzés:**
  - egy-egy rövid felvillanás (villanás, logó, porszem) a fekete sávban csak figyelmeztetés;
  - legalább 0,5 másodpercig tartó belevágás a képbe továbbra is megállítja.
- **Hang:**
  - a hangos masterek túlvezérlése és true peak-értéke az átkódolt sávoknál csak figyelmeztetés;
  - megállás csak új, nagyarányú torzításnál, 3 LU-nál nagyobb hangerő-eltolódásnál vagy néma kimenetnél van;
  - a klipillesztéseknél (±1 s, legfeljebb 0,5 s) lévő kis hanghézag vagy átfedés is csak figyelmeztetés;
  - a bitrátánál ±3% az eltérés, a DTS 1509k/1509,75k értékei is elfogadottak, a hiányzó bitráta csak figyelmeztetés.
- **Feliratok:**
  - az ismert PGS-üzenetek csak tájékoztatók;
  - az eseményszámban max(5, 5%) eltérés elfogadott;
  - a film vége utáni legfeljebb 3 másodperc csak figyelmeztetés.
- **Időtartam, színleírás, méret:**
  - ha a libbluray-olvasó 600 s alatt, két próbálkozásból sem fut le, becsült hossz lesz, és az eltérés csak figyelmeztetés;
  - a chroma-hely és profil/level FFmpeg-verziónkénti eltérő leírása csak figyelmeztetés;
  - ha a kódolás a forrásnál nagyobb lesz, az is csak figyelmeztetés.
- **Comparison időkorlát:** kifutáskor 2×, majd 4× hosszabb időkerettel magától újrapróbálja, az elkészült képpárok megmaradnak.
- **Átmeneti tároló- vagy hálózati hiba** (EIO, ESTALE, ETIMEDOUT…): 1, 5, majd 15 perc múlva újrafuttatja a szakaszt, a kész checkpointok megmaradnak.
- **Elérhetetlen automatikus CRF-cél:** a legközelebbi mért CRF-fel kódol, és ezt az eseménynapló jelzi.

## Megjegyzés

A képvágás-ellenőrzés új, képkockánkénti naplózása miatt egy munka, amely újra a kódolás szakaszba lép, egyszer újra lefuttatja a teljes dekódolást.

## Ellenőrzőlista

1. `GET /api/v1/capabilities` `backend_version`: `3.7.3`.
2. Egy kész munkánál legfeljebb 20 comparison-kép, a spektrogramok és (trackernél) a képernyőképek kerülnek fel.
3. Új munkánál egy másik lemez kijelölése a munka nevét is átírja.
