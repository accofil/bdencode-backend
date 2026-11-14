# Accofil BDEncode 4.3.0 kiadási jegyzet

Négy kérés: választható névsablon, amelyből a név magától összeáll; a névszabályok csak javaslatok; a külső forrás hang- és feliratfájlja tallózható; a `subme` Haladó szinten is állítható, és új mezőben adhatók meg a beépítetlen kódolókapcsolók.

## Névsablon: Aither vagy nCore, a név a fájladatokból áll össze

- A varázsló utolsó lépésében új mező van: **Névsablon**, Aither vagy nCore (magyar szabvány). Az alapértelmezést a tracker-profil adja: nCore-profilnál a magyar szabvány, egyébként az Aither. Bármikor átállítható, és a böngésző megjegyzi.
- A kimeneti név a választott sablon szerint **magától összeáll** a fájladatokból (felbontás, forrás, HDR/DV, hangkodek és csatornák, nyelvek, videokodek, release-tag). Minden változásnál frissül: sáv, sablon, tag.
- Ha a nevet átírod, a program **nem írja felül**. A „Név újra összerakása” gombbal kérheted újra; ilyenkor az átírt címrészt megtartja.
- Új sémák:
  - **Magyar szabványú remux** (encoding-hun `series-and-movies-remux.md`): `Cím.Év.1080p.BluRay.REMUX[.HDR].DTS-HD.MA.5.1.AVC[.HUN]-TAG`. Az eredeti nyelvű hang a videokodek előtt áll, a HUN utána. A kodekjelölés AVC, HEVC, VC1, MPEG2 vagy AV1.
  - **Illesztős (fit) munka neve:** a fájl fajtáját (encode vagy remux) a forrásfájl nevéből veszi. Magyar sablonnál a beillesztett magyar sáv HUN jelölést ad. Például a The Last Whale Singer: `The.Last.Whale.Singer.2025.1080p.BluRay.DDP5.1.x264.HUN-TAG`.

## A névszabályok csak javaslatok

- A kimeneti név eddig kemény szabály volt („output_name must be a clean remux name…”). Mostantól az eltérés **figyelmeztetés** az Ellenőrzés eredményében („Névjavaslat (nem kötelező): …”), és a munka a beírt névvel indul.
- A backend mindkét remux-sémát felismeri (Aither: hang a kodek után; magyar: hang előtte, HUN utána), és mindkettőnél jelzi, ha a név nem igaz a fájlra. Ilyen például a HUN magyar sáv nélkül, a hiányzó DV vagy Atmos, vagy a rossz kodek.
- A remux futás közbeni névellenőrzése csak bejegyzést ír az eseménynaplóba.
- Kötelező marad a fájlnév biztonsága: megengedett karakterek, nincs útvonal-elválasztó.

## Tallózás a külső forrásnál

- A „Hang vagy felirat más forrásból” tallózója minden fájlt mutat, amit az illesztés be tud olvasni: MKV, MP4, M4V, M2TS, MTS, TS, VOB, MPG, MPEG, AVI, ISO, valamint mappát.
- Az SRT-mező „SRT tallózása” gombot kapott, amely mappákat és `.srt` fájlokat mutat. Fájlra kattintva kiválasztja.
- `GET /api/v1/sources` új paramétere: `files` = `mkv` (alapértelmezett), `external` vagy `subtitle`.

## `subme` és egyéb kódolókapcsolók

- A **subme** (részpixeles finomság) eddig csak Profi szinten látszott. Most Haladó szinten is megjelenik a „Mozgásbecslés” csoportban, a súgóval együtt (x264: 0–11, x265: 0–7; nCore-nál x264 legalább 8, x265 legalább 3).
- Új mező az **„Egyéb kapcsolók”** csoportban, Haladó és Profi szinten: az x264/x265 olyan kapcsolói, amelyeknek nincs saját mezője, `kulcs=érték:kulcs=érték` alakban (mint az `-x264-params`). Például x264: `deadzone-inter=21:deadzone-intra=11`, x265: `selective-sao=2:aq-motion=1`. Súgó is tartozik hozzá.
  - A kapcsolók a mezők értékei után kerülnek a kódolóhoz, és a beállításokkal együtt mentődnek. Üresen semmi nem változik, a korábbi beállítások ellenőrzőösszege ugyanaz marad.
  - A mező nem enged meg semmit, aminek saját mezője van (például `ref`, `crf`; azt ott kell állítani), sem olyat, ami fájlt ír vagy olvas, vagy a feldolgozási láncot változtatja (például `stats`, `qpfile`, `pass`, `input-res`, színtér-kapcsolók, szálak). A hibás alakot és az ismétlést is visszautasítja, magyarázattal.
  - Egy elírt vagy ismeretlen kapcsoló a kódolás indulásakor ad hibát.

## Ellenőrzőlista

1. `GET /api/v1/capabilities` `backend_version`: `4.3.0`.
2. Az utolsó lépésben a Névsablon váltásakor a név frissül; átírt név megmarad.
3. Egy szabálytól eltérő név figyelmeztetést ad, nem hibát.
4. A külső forrás tallózója mutatja az MP4/AVI/ISO fájlokat, az SRT tallózója a `.srt` fájlokat.
5. Haladó szinten megjelenik a `subme` és az „Egyéb kapcsolók” mező; egy `ref=6` kapcsoló magyarázott hibát ad.
