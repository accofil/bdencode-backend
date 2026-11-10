# Accofil BDEncode 4.1.0 kiadási jegyzet

Két javítás a hang időzítésében, és egy új művelet: kész munka újrakezdése új munkaként.

## Javítás: a hang 11 másodperccel előbb szólt (Taffin 1988)

**A hiba.** A Taffin (1988) Blu-ray 4-es playlistje egy kb. 11 másodperces, hang nélküli klippel indul. A referencia-MKV-ban a hang első csomagja 11,053 s-nál van, az ffprobe viszont a hang `start_time`-jára a konténer kezdetét (0,042 s) adja, mert az első csomag kívül esik a vizsgálati ablakán. A mux-tervező erre a hibás értékre épített, ezért a hangot −11 053 ms-mal eltolta: a kész fájlban a hang 0,000 s-nál indult, a kép 11 másodperces bevezetője alatt. A mux utáni ellenőrzés ugyanígy `start_time`-ot olvasott, ezért nem vette észre. A munkát a hang-folytonossági QC állította meg (NEEDS_REVIEW), feltöltés nem történt.

**A javítás.** A hang kezdetét a program az **első csomagja** idejéből számolja: a tervezésnél a referenciában, az ellenőrzésnél a kész fájlban. A feliratoknál ez már korábban is így volt (3.11.2). A sidecar-oldalon a priming és a kerekítés kezelése nem változott. Normál lemeznél, ahol a hang a kezdetnél indul, a két érték azonos, ott semmi sem változik.

## Javítás: illesztés melletti hang-átfedés a cím idővonalán

A hang-folytonossági QC a hangban talált ugrás helyét a hang első kockájától mérte, a playlist klip-illesztéseit viszont a cím (a kép) idővonalán. Ha a hang 11 s-mal később indul, egy illesztésnél lévő, megengedett átfedés 11 s-ra „kerül" az illesztéstől, és hibának látszik. Most az ugrás helye a cím idővonalára kerül át (a hang első kockája mínusz a videó kezdete) az összevetés előtt. A Taffinon: egy 512 mintás (10,7 ms) átfedés a film végén, 11 ms-ra az illesztéstől, ez így illesztési átfedés. Az elveszett vagy hozzáadott hang (mintaszám) továbbra is hibát ad.

## Új: kész munka újrakezdése új munkaként

A kész munka **Műveletek** menüjében új pont van: **Újrakezdés új munkaként**. Ugyanabból a forrásból új munka készül; a kész munka és a kiadása változatlan marad. Két lehetőség:

- **Tiszta lappal:** csak a forrás, a név, a lemez- és tartalomtípus és a munka célja marad; a varázsló alapbeállításokkal indul.
- **Ugyanazokkal a beállításokkal:** a varázsló a korábbi jóváhagyott beállításokkal van kitöltve. Fölötte egy megjegyzés sorolja fel a korábbi encode értékelésének javaslatait (például CRF 18 → 17, indoklással és becsült méretváltozással). **Egyik javaslat sincs alkalmazva**, te döntöd el, mit változtatsz.

Az új munka scannel indul, a kódolás csak a jóváhagyás után kezdődik. API: `POST /api/v1/jobs/{id}/reload`, `{"mode": "clean" | "same"}`, csak COMPLETED munkára.

## Amit érdemes tudni

- A már kész, de hibás időzítésű kimenetet a munka újraindítása javítja: a mux-terv megváltozik, ezért csak a mux és a QC fut újra; a videó-encode és a referencia-remux megmarad.
- Régebbi, kész kiadásokat a javítás nem érint (nem kell őket újracsinálni, ha a hangjuk a kezdetnél indul).

## Ellenőrzőlista

1. `GET /api/v1/capabilities` `backend_version`: `4.1.0`.
2. A Taffin munka újraindítása után a kész fájlban a hang első csomagja ~11,01 s-nál van, és a QC átmegy.
3. Kész munkánál a Műveletek menüben megjelenik az „Újrakezdés új munkaként".
