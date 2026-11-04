# Accofil BDEncode 4.0 kiadási jegyzet

*English version: [RELEASE_4_0.en.md](RELEASE_4_0.en.md)*

A program új neve **Accofil BDEncode**. A 3.0-ban kivett torrentkészítés és feltöltés visszakerült, de csak két trackerre: **Aither** és **nCore**. A seedelést a qBittorrent végzi.

A név csak a felületen és a kiadásokban változott. A szolgáltatások (`bdencode-api`, `bdencode-worker`), a parancs, az útvonalak és a GitHub-repó neve a régi marad, így a frissítés és a meglévő telepítések változatlanul működnek.

## A folyamat

A Release lapon, a kész csomag után egy új kártya jelenik meg. Minden lépést te indítasz.

1. **Torrent készítése.** A program hardlinket készít az MKV-ról a `seeding/<azonosító>/` mappába (nincs másolat), és ott készít privát torrentet. Külső eszköz nem kell hozzá. A forrás-címke `Aither` vagy `nCore`. Az nCore-nál 2 GiB fölött a torrent egy mappa, benne az MKV és a `sample.mkv`.
2. **Dupe check.** Az Aithernél a TMDB-azonosító és a felbontás alapján keres, és megnézi a tiltott csoportokat. Az nCore-nál név és IMDb alapján keres, és lekérdezi az oldal saját tiltólistás jelzését.
   - Nincs találat: jöhet a feltöltés.
   - Van találat: legalább 12 karakteres indoklással továbbengedhető.
   - Pontosan azonos név vagy tiltott tétel: nem engedi tovább.
3. **Feltöltés.** A párbeszédablak megmutatja, pontosan mi megy fel, a szövegek javíthatók. Csak a kiadás nevének megerősítése után küldi el.
4. **Seed.** Elfogadás után letölti a tracker saját torrentjét, ellenőrzi, hogy ugyanazt az adatot írja-e le, és hozzáadja a qBittorrenthez.

## Biztonsági szabályok

- **Magától semmi nem kerül fel.** Nincs automatikus feltöltés kódolás után.
- **Egy kérés csak egyszer megy ki.** Ha a válasz nem egyértelmű, az állapot `UNKNOWN` lesz, és a program nem próbálja újra. Az nCore-nál előbb név és darab-hash alapján megkeresi a feltöltést. Utána a Dupe check újra megnézi a trackert; ha ott van, azonos névvel nem enged tovább.
- **Elutasításnál** az ok látszik, a szöveg javítható, és újra jóváhagyható.
- **Belépési adatok:** titkosítva, a meglévő rendszergazdai segédprogramon át kerülnek a tárolóba. A felület és a naplók soha nem mutatják őket. A tracker letöltési linkjét a program nem tárolja, a tracker torrentje (benne a passkey) `0600` jogú fájl.

## Seedelés és a többi qBittorrent-automatizmus

- A torrent külön **`bdencode` kategóriába** és `accofil-bdencode` címkével kerül. A `qbit-aither-relay` csak az `aither` kategóriát, a `qbit-upload-prep` csak az `other` címkét kezeli, a `qbittorrent-storage-mover` pedig csak a saját forrásmeghajtóját nézi, így egyik sem nyúl hozzá.
- A program csak hozzáad és állapotot olvas; semmit nem mozgat és nem töröl.
- A qBittorrent teljesen újraellenőrzi az adatot. Ha nem 100%, a program hibát jelez, és nem hagyja letölteni.
- A várakozás legfeljebb 25 perc, mert az nCore 30 percen belül kéri a seed indulását. Sorban álló torrentet kényszerítve indít el.
- Ha a qBittorrent nem érhető el, a feltöltés érvényes marad: a **Seed újra** gomb és a tracker torrentjének letöltése ilyenkor is ott van.
- A `seeding` mappa hardlinkjei a kész munka törlése után is megmaradnak, ezért a hely csak akkor szabadul fel, ha a seedet is leveszed.

## Beállítás

A Rendszer lap új **Trackerek és seedelés** panelje:

- **Aither:** API-kulcs.
- **nCore:** a böngészőből exportált `cookies.txt` tartalma. Lejárat után újra be kell illeszteni; a program jelzi.
- **qBittorrent:** cím, felhasználó, jelszó. Üres címnél a seedelés kézi.

A **Kapcsolat ellenőrzése** gomb csak olvas. Az API a belépési adat mentésekor újraindul, ezért futó feltöltés vagy seed közben ne módosítsd.

## Az Aither és az nCore kitöltése

- **Aither:** REMUX vagy ENCODE típus a munkából, felbontás, TMDB és IMDb a release-tervből, DV/HDR a névből. A név szóközös (`DTS-HD MA 5.1`). A leírás a munka BBCode-ja; képek nélkül nem enged feltölteni. A MediaInfónak tartalmaznia kell a `Unique ID` sort, és kell angol hang vagy felirat. A TMDB-azonosító kötelező.
- **nCore:** saját feltöltés (`eredeti=nem`), `hd` vagy `hd_hun` kategória aszerint, hogy az első hangsáv magyar-e. A címeket, az országot és a hosszt az nCore saját IMDb-lekérdezése adja, javíthatók. A leírást neked kell megírni, és „Forrás: …” sorral kell végződnie. A techinfo minden torrentbeli fájl MediaInfója, csak relatív névvel. Három kép megy fel; az 5 MB fölöttieket a program JPEG-gé alakítja.

## Mire épül

- Az nCore-rész az **AccoFIL NCUpload** kódjából készült (MIT).
- Az Aither-rész az **Audionut Upload-Assistant** viselkedését követi, de a kódját nem veszi át, mert a licence (UAPL) ezt itt nem engedi. Csak az API használatának tényei azonosak.

## Korlátok

- **Valódi trackeren még nem futott.** A kliensek hamis szerverek ellen vannak tesztelve; az első éles feltöltést érdemes kísérni.
- Egyetlen MKV-s kiadás. Teljes lemez (BDMV) feltöltése nincs, és nCore-ra csak film megy.
- Az nCore napi feltöltési korlátját és rang szerinti minimális méretét a program nem nézi, ezeket az oldal maga utasítja el.
- Az nCore remux-szabályait a program nem ellenőrzi.

## Telepítés

Új adatmappa: `seeding`, a telepítő létrehozza, az API-szolgáltatás írhatja. Új, opcionális hitelesítő adatok: `tracker-ncore-cookies`, `qbittorrent-password`. Új csomagok a DVD-k olvasásához: `lsdvd`, `p7zip-full`.

## Ellenőrzőlista

1. `GET /api/v1/capabilities`: `backend_version` = `4.0.0`, `constraints.tracker_upload.trackers` = `["aither", "ncore"]`.
2. Az oldal címe és az oldalsáv: Accofil BDEncode.
3. A Rendszer lapon megjelenik a Trackerek és seedelés panel.
4. Egy kész munka Release lapján a csomag után megjelenik a Feltöltés kártya, és a Dupe check a torrent előtt nem indítható.

## Mit szeretnél csinálni?

Az **Új munka** oldal most ezzel a kérdéssel kezd, és utána csak a választott út lépései látszanak:

- **Kódolás vagy remux:** a korábbi folyamat, külső forrás nélkül.
- **Hang vagy felirat illesztése:** kész encode-ra vagy remuxra, kódolás nélkül. A fájl videója és megtartott sávjai bájtra azonosak maradnak, ezt a program ellenőrzi; a meglévő sávok megtarthatók vagy elhagyhatók, de nem alakíthatók át. Lemezt választva, mivel az nem bővíthető, remux készül a külső sávokkal.
- **Kódolás és illesztés:** új encode vagy remux, és külső sávok is kerülnek bele.

A kész fájlra illesztett sávnál az Aither szabálya külön figyelmet kér: egy más release-hez utólag hozzáadott sáv retag lehet, ami ott tiltott.

## Hang és felirat más forrásból

Remuxhoz és kódoláshoz is hozzáadható hangsáv vagy SRT-felirat egy másik forrásból: videófájlból, DVD-mappából vagy DVD-képfájlból. Eltérő sebesség (PAL) és eltérő vágás mellett is működik. A teljes útmutató: [EXTERNAL_SOURCES.md](EXTERNAL_SOURCES.md).

**Hogyan illeszt?** A két **képet** hasonlítja össze, kockáról kockára. A hangot nem használja időreferenciának, mert a régi filmek nyelvi változatainak saját hangmestere van: a *God Forgives, I Don't* (1967) BD-jén a német és az olasz sáv közös alapja ±400 ms-ot is eltér egymástól, pedig egy lemezen vannak.

1. A varázsló **Sávok** lépésének végén megadod a forrást, és kiválasztod a sávokat. A kódolás nem indul el.
2. A program kockára pontos térképet készít, és eszerint elkészíti a sávot.
3. A munka **operátori ellenőrzésre** áll meg. A kártyán látszik a térkép, a kép-egyezés és a néma részek, és letöltés nélkül, a böngészőben meghallgathatod bármelyik illesztési pontot.
4. Jóváhagyás után fut a kódolás vagy a remux. A cím saját sávjai a szokásos módon készülnek és ellenőrződnek, a külső sávok egy második mux-lépésben kerülnek be.

**Fülpróba:** a kivonatban a bal fülben a cím saját első hangsávja, a jobb fülben az illesztett szól. A közös zene és effektek csúszásnál visszhangosak, és a böngésző vagy a fejhallgató késése ezt nem befolyásolja. Eltérő hangmesterek közt (lásd fent) kisebb visszhang akkor is lehet, ha a kép szerinti illesztés pontos, ezért a szájmozgást is figyeld.

**A hang kezelése**

- Azonos sebességnél és egyetlen vágatlan szakasznál **nincs újrakódolás**, a sáv változatlanul kerül be (HU 9.12).
- Sebességváltásnál vagy vágásnál a sáv újra AC-3 lesz: veszteséges forrásnál a forrás bitrátáján, jobb forrásnál 640 kbps-sel (2.0: 384 kbps). A csatornaszám és a dialnorm marad, a DRC ki van kapcsolva. Hat csatorna fölött a program nem illeszt, mert le kellene keverni.
- **Hangmagasság:** a „visszaállítás” lassítással pontosan visszafordítja a PAL-gyorsítást, a „megtartás” csak a tempót változtatja. Ha a magyar szinkront PAL-képre vették fel, a visszaállítás mélyebbé teszi a hangokat. Ezért a kártyán váltható és meghallgatható; váltás után a sáv újra elkészül.
- Ahol a külső forrásból hiányzik a kép, a sáv **néma**. A kártya ezt időpontokkal kiírja, mert a HU szabályok nukeolhatják (`incomplete.audio`).
- A képtérkép töréseinél 5 ms-os ki- és beúsztatás van, hogy ne kattanjon.

**Ellenőrzés a mux után** (`analysis/external-merge-streams.json`): a cím saját sávjai bájtra azonosak a második mux előttivel, a külső sáv pedig szakaszonként és minden illesztés két oldalán a térkép szerinti helyen van (1,5 ms-on belül). Ha nem, a munka megáll.

**Korlátok az első körben:** csak olyan forrás illeszthető, amelyben van kép (önálló szinkronfájl még nem). Felirat csak SRT lehet; a képes felirat és a DVD saját felirata még nem. Csak képkocka-azonos (PAL-gyorsítás) és azonos futásidejű forrás támogatott. Valódi anyagon egyelőre csak a PAL-gyorsítás van kipróbálva; a 29,97-es, azonos futásidejű eset csak szintetikus teszttel.

## Aither: hang az 1080p encode-okon

Az Aither trump-szabálya szerint az élőszereplős 1080p encode a veszteségmentes 5.1 hang miatt trumpolható. Kivétel a csak 2 csatornás hang, ha 16 bites FLAC. 2160p-n fordított a szabály: ott a veszteséges fősáv trumpolható.

- **Alapérték:** ha kódolásnál az Aither-profilt választod, az élőszereplős, legfeljebb 1080p magas cím veszteségmentes sávjai maguktól átállnak: 2 csatorna fölött E-AC-3 1024 kbps, legfeljebb 2 csatornán az új **FLAC 16**. A változásokat a varázsló kiírja, és visszaállíthatod őket. A **Sávterv igazítása** gomb ugyanezt teszi.
- **Figyelmeztetés:** a terv ellenőrzése jelez, ha ilyen sáv mégis a tervben maradt. Nem tiltja meg, csak szól.
- **FLAC 16:** 16 bites forrásból bitre azonos, ezt a QC minta szerint ellenőrzi. Mélyebb forrásból ditherrel készül, ilyenkor a QC a hangerőt, a csúcsokat, az időzítést és a szinkront ellenőrzi.
- **Kivételek:** a remuxra és a 2160p-re ez nem vonatkozik. Anime esetén a program nem nyúl a sávokhoz, mert a szabály csak élőszereplős tartalmat említ, de külön engedélyt az animációra sem ad.
- **7.1:** az ffmpeg E-AC-3 kódolója legfeljebb 5.1-es, ezért a 7.1 lekeveredik; erről is szól a varázsló. Valódi 7.1-es E-AC-3-hoz a Dolby kódolója kellene, ami nincs a szervereken.
- **Külső sávok:** a nyelvi és sorrendi ellenőrzés a más forrásból illesztett hangot és feliratot is látja. A magyar szinkron ezért Aither-profilnál figyelmeztetést ad, mert ott csak az eredeti nyelvű és az angol fősáv mehet.

## Javítások a 3.14.0 remux módjához

- **A remux nem indult el a szolgáltatáson.** Megállt ezzel: „the remux plan does not belong to the current selection”, mert a szolgáltatás a munkát egyből a kódolási sorba teszi, és az előkészítés kimaradt. Most ilyenkor is lefut.
- **Többklipes címnél a QC hamisan állt meg.** A referencia hangjának időbélyegei a klipillesztéseknél visszaugranak, és a szigorú dekód emiatt leállt. A hash már csak a mintákat nézi, a dekódhiba továbbra is megállít.
- **Az ffmpeg 5.1 „corrupt input packet in stream” sora** a klipillesztésnél nem számít forrássérülésnek, ha az illesztés szigorú dekódja hibátlan. Máshol továbbra is megállít.

- **Többklipes (seamless branching) cím hangja nem csúszik.** A *God Forgives, I Don't* 1:53:19-es változatán a hang a klipillesztéseknél lépcsőzetesen 87 ms-ig csúszott, mert a remux megtartotta a lemez átfedő hangját. DTS és DTS-HD sávnál, ha a cím egész klipekből áll, a bontás most `klip1.m2ts+klip2.m2ts` alakban fut, így az eac3to második menete eltávolítja az átfedést. A közzétett eac3to-naplóban ez a parancs áll az `.mpls` helyett; hogy az Aither ezt elfogadja-e, azt nem ellenőriztük.
- **A többklipes cím QC-je a klipekhez mér.** A szinkront a klipek saját időbélyegéhez képest nézi, egy kodekkeretnyi tűréssel (DTS 10,667 ms, AC-3 és E-AC-3 32 ms). Ha az MD5 eltér, a bitfolyam csomagjait hasonlítja össze: a remux csak a klipillesztéseknél veszíthet egész csomagokat. Az egyklipes cím marad a szigorú MD5-nél.

Valódi próba: a God Forgives `00002`-es listája a QC-ig átment, a legnagyobb csúszás 7,1 ms, sávonként 3 csomag esett ki. Az ez utáni lépéseket ezen a listán csak szimulált eszközökkel próbáltuk.

**Ismert korlátok:** többklipes TrueHD megállhat ellenőrzésre, mert az eac3to nem tudja vágni. Többklipes AC-3 és PCM valódi lemezen még nincs lemérve.
