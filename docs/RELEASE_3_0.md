# BDEncode 3.0 kiadási jegyzet

Trackerkompatibilitási kiadás. Egy munka mostantól az Aither vagy az nCore szabályai szerint készülhet. Az nCore esetén a magyar release-szabványt (encoding-hun) is követi, amelyre az nCore Wiki a megfelelő minőséghez hivatkozik. A varázsló a sávtervet és a kiadásnevet a választott tracker szerint javasolja. A kódoló a kötelező bitstream-beállításokat magától alkalmazza. Az összehasonlító képekből trackerre kész BBCode készül. Új a beépített, magyar nyelvű kódolási súgó és az Aither-gyakorlatra épülő presetkészlet.

A régi munkák viselkedése nem változik: minden új működés a trackerprofilhoz kötött. A folyamatban lévő munkák kódolási és összehasonlítási checkpointja érvényes marad, nem indul újrakódolás.

## Változások

- **Kódolási súgó.** Új „Súgó” oldal az x264- és x265-beállításokhoz. Minden beállításnál szerepel:
  - mit csinál, és milyen hatása van a minőségre, a méretre és a sebességre;
  - a szokásos értékek;
  - javaslat szemcsés filmhez, tiszta digitális filmhez és animációhoz;
  - Aither-gyakorlat és nCore/magyar szabvány.

  A varázslóban minden beállítás mellett „?” gomb nyitja meg ugyanezt. Az oldal kodekre szűrhető és kereshető. Forrásai az Aither fórum és wiki, az nCore Wiki, a magyar release-szabvány, a Silent Aperture útmutató és a kodekdokumentációk.
- **Választható kódolóeszközök.** Profi szinten megjelentek ezek a beállítások:
  - x264: mbtree, fast-pskip, dct-decimate;
  - x265: cutree, tu-intra/inter-depth, limit-tu, rd, rdoq-level, cb/cr QP-eltolás, b-intra, max-merge, limit-refs, lookahead-slices, hrd, high-tier;
  - mindkettőnél: ip/pb arány.

  Üresen hagyva a preset saját értéke marad, és a parancssorba sem kerül.
- **Aither-presetek.** Hat beépített kiindulópont az Aitheren elfogadott encode-ok és útmutatók alapján:
  - UHD x265: szemcsés, tiszta és animáció;
  - 1080p x264 Quality slot: szemcsés, tiszta és animáció.

  Kiválasztáskor a beállítások konkrét értékként kerülnek a profilba, CRF-ajánlással. A presetváltás nem hagy maga után beállítást.
- **Tracker-profil (Aither / nCore).** A varázsló sávlépésében választható. A „Sávterv igazítása” gomb és a sávszabályok:
  - **nCore:**
    - A magyar szinkron az első és alapértelmezett sáv, utána az eredeti, az angol, végül a kommentár. Más nyelvű hang kimarad.
    - 1080p-n a TrueHD- és DTS-HD MA-sávból E-AC3 5.1 lesz 1024 kbps-on. 7.1-es forrás 5.1-re keveredik, mert FFmpeg-gel 7.1-es E-AC3 nem készíthető.
    - Szinkron nélküli nyelv forced felirata kimarad.
    - A magyar szinkron akkor is lehet alapértelmezett, ha az eredeti is megmarad.
  - **Aither:** csak az eredeti és az angol hang marad (plusz kommentár).
  - **Mindkettő:** a megtartott TrueHD mellett a lemez saját AC3-magja kompatibilitási sávként, újrakódolás nélkül megmarad.

  A terv ellenőrzése után magyar nyelvű lista mutatja, mi tér még el a szabálytól. Ilyen például a hiányzó DD@640 kompatibilitási sáv DTS mellett, a nem engedett hangformátum vagy nyelv, a felirat-sorrend, a 16 sávos korlát, az angol felirat hiánya, illetve hogy PGS felirat marad.
- **Kiadásnév.** Egy nyelvtan fogadja az Aither (`…2160p.UHD.BluRay.DTS-HD.MA.5.1.DV.HDR.x265-TAG`) és a magyar (`…2160p.UHD.BluRay.DV.HDR.TrueHD.7.1.Atmos.x265.HUN-TAG`) formát is. Minden jelölésnek igaznak kell lennie a tervre: hangkodek, csatornaszám, Atmos, DV/HDR/HDR10+/HLG/SDR, Dual-Audio, MULTi, HUN/2xHUN. A cím részben maradt kodek- és remux-jelölést a rendszer elutasítja. A „Név javaslata” gomb a választott stílusban állítja össze a nevet a megadott release-taggel; a taget a böngésző megjegyzi.
- **nCore kódolószabályok.** nCore-profilnál ezek automatikusak:
  - **x265:**
    - level 5.1, 30 fps felett 5.2, high tierrel;
    - HRD, AUD, ismételt fejlécek;
    - 160 Mb/s VBV;
    - limit-refs legfeljebb 1, illetve rect+amp mellett 2;
    - lookahead-slices legfeljebb 4;
    - az a referenciaszám, amelyet az x265 a level képpufferében megtartana.
  - **x264:** a level 4.1 szerinti legnagyobb referenciaszám.

  A minőségi minimumokat (B-frame, merange, subme, psy, rc-lookahead) a rendszer csak jelzi. Explicit x265 level mostantól megadható, ha a high tier be van kapcsolva, és a VBV belefér a level határaiba.
- **Összehasonlítás és BBCode.** Trackerprofilos munkánál:
  - A 24 képpárból 12 B-képkocka, így az Aither-összehasonlítás csupa B-párból áll.
  - Néhány B-párból tiszta, jelölés nélküli encode-kép is készül képernyőképnek.
  - A `comparison.bbcode` végére trackerre kész szakasz kerül:
    - **Aither:** `[comparison=Source, Encode]` blokk szóközzel elválasztott PNG-URL-ekkel, 6 képernyőkép `[center]` és `[img=350]` formában, valamint az x264/x265-napló összesítője spoilerben.
    - **nCore:** pontosan 3 `[imgw]` kép az encode felbontásában, és a cseréhez használható összehasonlító linkek.
- **nCore-minta.** 2 GB fölötti kész fájlnál a véglegesítés újrakódolás nélkül kivág egy mintát: `Sample/<név>.sample.mkv`. A minta kb. 5:00-tól indul. Hossza 60 s, UHD-nál annyi, hogy elérje a 200 MB-ot, de legfeljebb 4 perc. A Fájlok lapon is letölthető.
- **IDR a fejezethatárokon.** Trackerprofilos munkánál a végső kódolás minden fejezetkezdetnél IDR-képkockát kényszerít (`-force_key_frames` és `forced-idr`), ahogy az Aither encoderei ajánlják.
- **Torrent, qBittorrent és trackerfeltöltés kikerült.** A BDEncode nem készít torrentet, nem ad hozzá semmit qBittorrenthez, és nem tölt fel a trackerre. A torrentet és a feltöltést kézzel végzed. Ami megmarad:
  - a Release panel és a release-profilok;
  - a release-csomag: NFO, BBCode-leírás, MediaInfo, ellenőrzött képek és checksumok (manifest schema 2, torrent nélkül);
  - a dupe check: `CLEAR` eredménynél az állapot „Dupe check: tiszta”;
  - az összehasonlító képek feltöltése a képtárhelyekre.

  A meglévő adatok érintetlenek. A korábbi csomagok (a régi torrenttel együtt), a receiptek és a credentialök a helyükön maradnak; a régi csomagok továbbra is ellenőrizhetők és törölhetők. A release-profil torrentmezői (`torrent_source`, `announce_urls`, darabméretek), a `publish_endpoint` és a `qbittorrent` szakasz elhagyható. Egy régi profilfájl ezekkel is betöltődik, de a rendszer nem használja őket. A telepítő a qBittorrent-credentialöket már nem köti az API szolgáltatáshoz.

## Ismert korlátok

- DTS-családú sáv mellé a DD@640 kompatibilitási sávot (nCore) még nem készíti el automatikusan a rendszer: ugyanabból a forrássávból egy második kimenetet kellene kódolni. A terv ellenőrzése jelzi a hiányát. A TrueHD AC3-magja már automatikus.
- PGS-ből SRT (OCR) nem készül. Az nCore elfogadja a PGS-t, a magyar szabvány viszont SRT-t kér; erre a terv ellenőrzése figyelmeztet.
- Ha egy Aither-slot foglalt, az ott lévő encode-dal való összevetéshez harmadik oszlop kellene; ez még nincs.
- A Dolby Vision L1-értékek számlálása az nCore DV.HDR-elsőbbségéhez (több mint 10 különböző L1) még nincs.

## Új és bővített API-mezők

- Kiválasztás: `tracker_profile` (`aither`, `ncore`, vagy elhagyva az általános mód).
- `POST /api/v1/jobs/{id}/selection/validate` válasza: `tracker_profile` és `tracker_findings` (`code`, `message`, `severity`).
- `GET /api/v1/profiles/{encoder}/aither-presets`: a beépített Aither-presetek konkrét beállításokkal.

## Megszűnt API-végpontok és mezők

- `POST /api/v1/release-preparations/{id}/export`, `/seed` és `/upload`.
- A release-profilok nyilvános nézetében a `supports_publish` és a `supports_qbittorrent`.
- A `capabilities` válaszban a `private_v1_torrent`, a `qbittorrent_paused_recheck` és a `tracker_publish_requires_dupe_receipt` korlát.

## Frissítés

A napi időzítő magától telepíti, ha a sor üres (README 11.1.). Adatbázis-migráció nincs.

## Ellenőrzőlista

1. `GET /api/v1/capabilities` `backend_version`: `3.0.0`.
2. A Súgó oldal megnyílik, és a varázsló „?” gombjai a beállítás súgóját mutatják.
3. Egy UHD lemeznél a varázslóban nCore-profilt választva és a „Sávterv igazítása” után a magyar hang az első. A „Terv ellenőrzése” után az nCore-szabályok listája megjelenik, a videóbeállításokban `level-idc=5.1`, `hrd=1`, `vbv-maxrate=160000` látszik.
4. Trackerprofilos munka végén a `comparison.bbcode` tartalmazza az Aither vagy az nCore szakaszt.
5. A Release panelen nincs „Torrent export”, „Seed előkészítése” és „Trackerfeltöltés” gomb; a csomag építése és a dupe check működik, a csomagban nincs `.torrent` fájl.
