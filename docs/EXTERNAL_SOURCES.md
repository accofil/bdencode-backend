# Hang és felirat illesztése más forrásból

*English version: [EXTERNAL_SOURCES.en.md](EXTERNAL_SOURCES.en.md)*

Ezzel a funkcióval egy másik forrás hangsávja vagy SRT-felirata kerülhet egy encode-ba vagy remuxba. A tipikus eset: Blu-ray kép, PAL DVD magyar szinkronnal. A program eltérő sebességet és eltérő vágást is kezel.

## A három munkatípus

Az **Új munka** oldal azzal kezd, hogy mit szeretnél csinálni. Utána csak az ehhez tartozó lépések látszanak.

| Választás | Mi készül | Mi a forrás | Fut kódolás? |
|---|---|---|---|
| **Kódolás vagy remux** | Új encode vagy remux a forrás saját sávjaival | Lemez vagy lemezről készült remux MKV | Igen, remuxnál bontás |
| **Hang vagy felirat illesztése** | A kész fájl a hozzáadott sávokkal | Kész encode vagy remux MKV, vagy lemez | MKV-nál nem; lemeznél remux készül |
| **Kódolás és illesztés** | Új encode vagy remux, külső sávokkal is | Lemez vagy lemezről készült remux MKV | Igen |

A lemezt nem lehet utólag bővíteni, ezért lemezre illesztéskor remux készül a külső sávokkal. A remux korlátai ilyenkor is érvényesek.

## Lépésről lépésre

1. **Új munka:** válaszd ki a munkatípust, majd a forrást. Illesztésnél ez az a fájl vagy lemez, amire a sávok kerülnek. A beolvasás néhány percig tart.
2. **Varázsló, Sávok lépés:** a **Hang vagy felirat más forrásból** kártyán add meg a külső forrást, vagy keresd meg a **Tallózás** gombbal. Lehet videófájl, DVD-mappa, DVD-képfájl (`.iso`), vagy olyan mappa, amelyben egyetlen `.iso` van.
3. **Beolvasás:** megjelennek a forrás sávjai. Jelöld be, amelyik kell, és add meg:
   - a nyelvét,
   - a helyét a hangsávok között (0 az első),
   - hogy alapértelmezett legyen-e.
4. **SRT (nem kötelező):** add meg a teljes útvonalát és a nyelvét. Az SRT időzítése a külső forráshoz kell, hogy tartozzon.
5. **Jóváhagyás és indítás:** a program elkészíti az illesztést, és megáll. Kódolás még nem indul.
6. **A külső forrás illesztése kártya:** nézd át az eredményt, hallgasd meg a kritikus pontokat, és hagyd jóvá. Ha nem jó, a **Ezt a forrást kihagyom** gomb elveti.
7. **Befejezés:** lefut a kódolás vagy a remux, ha van. A cím saját sávjai a szokásos módon készülnek és ellenőrződnek, utána egy második mux-lépés teszi be a külső sávokat.

## Hogyan illeszt a program?

**A két képet hasonlítja össze, nem a hangot.** A régi filmek nyelvi változatainak saját hangmesterük van, ezért a közös zene és effektek nem pontos időreferenciák. A *God Forgives, I Don't* (1967) BD-jén a német és az olasz sáv egymáshoz képest ±400 ms-ot is eltér, pedig ugyanazon a lemezen vannak.

1. Mindkét videóból 64×36-os szürke lenyomat készül, minden képkockáról.
2. A vágások ritmusából a program 25 másodpercenként megkeresi a durva eltolást. Ezt a kivágás és a színezés nem zavarja.
3. A biztos képkockapárokból kiszámolja a kép geometriáját. Egy PAL DVD gyakran egy 2,39-es film 1,78-as kivágása, és a kivágás jelenetenként vándorolhat (pan & scan).
4. Minden képkockára megkeresi az eltolást, majd minden törést egyetlen vágásként old meg a két biztos szomszédja között.
5. A sebességet két feltevés közül választja ki:
   - **Kockáról kockára** (PAL-gyorsítás): minden filmkocka megvan, csak gyorsabban pereg.
   - **Azonos futásidő:** más képfrissítés, ugyanaz a hossz.

A 25 → 23,976 aránnyal a nyújtott hangban egy DVD-kocka pontosan 2002 minta 48 kHz-en, ezért a darabok mintára pontosan kerülnek a helyükre.

## A jóváhagyó kártya

- **Sebesség, szakaszok száma, kép-egyezés:** a medián és a 0,8 fölötti képkockák aránya. Feliratos nyitánynál, más nyelvű címkártyáknál az egyezés alacsonyabb lehet, ez önmagában nem hiba.
- **Idősáv:** zöld a jó egyezésű, sárga a gyengébb szakasz, a rés az, ami nincs meg a forrásban.
- **Néma részek:** itt a külső sáv csendes, mert a forrásból hiányzik a kép.
- **Meghallgatható pontok:** minden illesztés és néma rész, plusz három egyszerű szakasz.
- **Mit hallgass:**
  - **Fülpróba:** bal fülben a cím saját első hangsávja, jobb fülben az illesztett. A közös zene és effektek csúszásnál visszhangosak, és a böngésző vagy a fejhallgató késése ezt nem befolyásolja.
  - **Csak az illesztett** vagy **csak a saját** hang.

Semmit nem kell letölteni: a szerver rövid, 480p-s H.264/AAC kivonatot készít, ami a böngészőben szól. UHD forrásnál ez fél percig is tarthat.

> [!IMPORTANT]
> Eltérő hangmesterek közt kisebb visszhang akkor is lehet, ha a kép szerinti illesztés pontos. Ezért a szájmozgást is figyeld.

## Mi történik a hanggal?

| Eset | Eredmény |
|---|---|
| Azonos sebesség, egyetlen vágatlan szakasz, legfeljebb 200 ms késés | Nincs újrakódolás, a sáv változatlanul kerül be (HU 9.12) |
| Sebességváltás vagy vágás, veszteséges forrás | AC-3 a forrás bitrátáján |
| Sebességváltás vagy vágás, veszteségmentes forrás | AC-3 640 kbps (legfeljebb 2.0: 384 kbps) |
| Több mint 6 csatorna | A program nem illeszti, mert le kellene keverni |

- A csatornaszám és a dialnorm marad, dekódoláskor a DRC ki van kapcsolva.
- A nem mintára egész arányú 44,1 kHz-es hangnál a visszaállítás nem pontos, ilyenkor a program megáll.

**Hangmagasság.** Az alapértelmezett a **visszaállítás**: a lassítás pontosan visszafordítja a PAL-gyorsítást, a zene az eredeti magasságára áll vissza. A **megtartás** csak a tempót változtatja. Ha a szinkront PAL-képre vették fel, a visszaállítás mélyebbé teszi a hangokat, ezért a kártyán sávonként válthatsz; ilyenkor a sáv újra elkészül, és újra jóvá kell hagynod.

**Felirat.** Az SRT minden sora a képét követi. Ami a célból hiányzó részre esik, kimarad; ami vágáson lóg át, levágódik. A kártya kiírja a darabszámokat. A fájl lehet UTF-8 vagy Windows-1250.

## Ellenőrzés

A második mux után (`analysis/external-merge-streams.json`):

- A cím saját streamjei bájtra azonosak a mux előttivel.
- A külső sáv szakaszonként és a törések két oldalán a térkép szerinti helyen van, 1,5 ms-on belül. Ha nem, a munka megáll.
- A MediaInfo és a többi riport újra elkészül, így a kész fájlt írja le.

Kész MKV-ra illesztésnél a kiválasztott sávok másolata is bizonyított: a kép és a megtartott sávok bájtra azonosak az eredetivel.

## Trackerek

- **Aither:** encode-on és remuxon csak az eredeti nyelvű és opcionálisan angol fősáv mehet, a varázsló erre figyelmeztet. Más release-hez utólag hozzáadott sáv retag lehet, ami tiltott.
- **nCore:** a magyar sáv elsőként várt, a varázsló a külső sáv helyét is nézi. A HU szabály szerint az újrakódolt 5.1 AC-3 640 kbps vagy a forrás bitrátája. A nem lemezről származó hangnál a `RETAiL` címke kérdését magad döntsd el.
- A hiányzó részek (`incomplete.audio`) és a csúszás (`audio.oos`) nuke-ok lehetnek, ezért nézd át a néma részeket.

## Helyigény

- DVD-képfájlnál a fő cím VOB-jai kicsomagolódnak (DVD9-nél kb. 7 GB).
- Egy 2 csatornás filmnél a nyújtott hang kb. 2,6 GB, a mux ellenőrzése után törlődik.
- Kész MKV-nál a program a fájlról munkamásolatot készít, a második mux előtti változat is megmarad a munkaterületen a takarításig. Ez a fájlméret kb. háromszorosa.

## Korlátok

- A forrásban kép is kell, önálló szinkronfájl még nem illeszthető.
- Felirat csak SRT lehet. Képes felirat (PGS, VobSub) és a DVD saját felirata még nem illeszthető.
- Valódi anyagon a PAL-gyorsítás van kipróbálva. A 29,97 fps-es, azonos futásidejű forrás csak szintetikus teszten futott, a DVD-mappa pedig csak automatikus teszten.
- A kép alapú térkép felbontása egy képkocka. Mozdulatlan felvételben a törés helye bizonytalanabb, de az eltérés ilyenkor is legfeljebb a törés mérete.
- A néma részek nincsenek kitöltve, az eredeti hangból sem.
- Ha a külső forrás DVD-jén a hang és a kép cellánként eltér, azt a program nem javítja.
