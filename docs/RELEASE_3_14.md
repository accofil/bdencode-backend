# BDEncode 3.14.0 kiadási jegyzet

Új: **remux mód** Blu-ray és UHD Blu-ray lemezekhez, az Aither REMUX útmutatója szerint. Semmi nem kódolódik újra.

## Hogyan készül

A választó első lépésében mostantól választható: **Kódolás** vagy **Remux**. Remuxnál nincs Videó lépés.

1. **Bontás eac3to-val** (Wine alatt), ahogy az útmutató kéri. Az Aither saját remuxhoz minden forráslemezről eac3to-naplót vár: ez elkészül, és bekerül a BBCode-ba és a kiadás mellé.
2. **Összefűzés mkvmerge-dzsel**, az útmutató jelzőivel:
   - a sávnevek BDInfo-formájúak (`MPEG-4 AVC Video / 31990 kbps / 1080p / 23.976 fps / 16:9 / High Profile 4.1`);
   - a konténer címe `Cím (Év)`;
   - beállított nyelv, alapértelmezett, kényszerített, eredeti nyelvű, kommentár, hallássérült és látássérült jelző;
   - tömörítés nélkül, a dialog normalization eltávolítva a veszteségmentes sávokról és a DTS-HD HRA-ról;
   - opcionális IMDb- és TMDB-címke.
3. **Ellenőrzés a lemezzel szemben.** Az összevetés az ffmpeg független bontásával történik, így az eac3to és az mkvmerge munkáját más olvasó ellenőrzi:
   - a videó minden képkockája és minden hangsáv minden mintája dekódolva azonos (MD5);
   - Dolby Visionnél az EL és az RPU NAL-egységenként azonos a lemezével (az ffmpeg csak az alapréteget dekódolja, ezért ezt külön kell nézni), és a konténer P7-es rekordot jelent;
   - a feliratok tartalma azonos;
   - a sávok nevei és jelzői megfelelnek a tervnek, a fejezetek száma egyezik;
   - minden hangsáv és felirat a lemezzel azonos időben szól, a videó kezdetétől mérve.
4. **Képernyőképek** a kész remuxból (Aither: 6, nCore: 3), feltöltés és BBCode 400 px-es képekkel, plusz MediaInfo a tracker mezőjéhez.

## A sávok kezelése

- A videó és minden hangsáv érintetlen marad.
- A Blu-ray LPCM FLAC lesz, bitpontos ellenőrzéssel, ahogy az útmutató kéri; a 24 bites zero-paddinget az eac3to levágja.
- Minden TrueHD mellé automatikusan bekerül a beágyazott AC-3 kompatibilitási sávként, közvetlenül utána.
- A többcsatornás (3.0+) LPCM-et az útmutató TrueHD-re vagy DTS-HD MA-ra kéri, ehhez viszont a fizetős Dolby vagy DTS kódoló kell. Ilyenkor FLAC készül, és az Aither-ellenőrzés figyelmeztet; feltöltés előtt te döntesz.
- Ha az eac3to `<ERROR>` sort ír a naplóba, a munka megáll; a `<WARNING>` sorok megjelennek az eseményeknél és a BBCode-ban.

## UHD Blu-ray

- Az útmutató szerint az eac3to HEVC-nél hibás időbélyegeket adhat, ezért UHD-nél csak a hangot, a feliratot és a fejezeteket bontja. A videó a lemez `reference.mkv` másolatából jön, kódolás nélkül.
- A kétrétegű Dolby Vision (P7, FEL és MEL) a `dovi_tool mux` lépéssel egyetlen sávba kerül, mert az mkvmerge külön hagyná a két réteget. Az eredmény egy HEVC-sáv BL+EL+RPU tartalommal.
- A sáv neve BDInfo-formájú: `MPEG-H HEVC Video / 63002 kbps / 2160p / 23.976 fps / 16:9 / Main 10 @ Level 5.1 @ High / 4:2:0 / 10 bits / 1000nits / HDR10 / BT.2020 / Dolby Vision FEL @ 17908 kbps`.
- Kétrétegű lemezhez a gépen `dovi_tool` is kell (`constraints.remux.dolby_vision`). Ha nincs, a munka `remux_unavailable` hibával megáll.
- Az mkvmerge a BL filler NAL-jait elhagyja és a paraméterkészleteket ismétli: ez minden mkvmerge-remuxnál így van, a videós adat bitre azonos marad.

Egy 4K film ellenőrzése a két teljes dekódolás miatt órákig tart.

## Atmos és DTS:X a vizsgálatban

Az FFmpeg 5 nem látja az Atmost, ezért a vizsgálat MediaInfóval megnézi a főbb lejátszási listák első klipjét (kb. 1 mp). A jelölés a kódolásoknál is megjelenik.

## A kiadás neve

Az Aither remux sémája: `Title.Year.1080p.BluRay.REMUX.AVC.DTS-HD.MA.5.1-TAG`, UHD-nél `Title.Year.2160p.UHD.BluRay.REMUX.DV.HDR.HEVC.TrueHD.7.1.Atmos-TAG`. A **Név javaslata** gomb ilyet ad, a program pedig ellenőrzi: a kodek, a felbontás, a HDR-jelölés, a hang és az Atmos csak akkor szerepelhet, ha igaz, és ha a főhang Atmos, a névnek ki is kell mondania.

## Korlátok ebben a kiadásban

- Csak lemezről (MKV-forrásból nem: az már egy másik remux lenne).
- Több szöget tartalmazó lejátszási listából az első szög készül.
- Hibrid forrás és több lemez összefűzése nincs.
- A kettős mono felismerése, a kényszerített feliratok szétválasztása és a fejezetnevek kézi javítása kézi feladat marad (az útmutató 6.2, 3.1 és 7. pontja).
- A sávnevek bitrátája a kibontott fájl méretéből számolt átlag, néhány kbps-sel eltérhet a BDInfótól.
- Az nCore remux-szabályait a program nem ellenőrzi.

## Telepítés

Az eac3to 3.36-ot a telepítő teszi fel rögzített SHA-256-tal (`lib/eac3to`, `bin/bdencode-eac3to`).

A Wine egyszeri kézi előfeltétel, mert az i386 architektúra engedélyezését a telepítő nem tudná visszagörgetni:

```bash
sudo dpkg --add-architecture i386
sudo apt-get update
sudo apt-get install --no-install-recommends wine wine64 wine32:i386
```

A BDEncode médiazárolása (`/etc/apt/preferences.d/bdencode-media`) a `libx265-199:i386` csomagot is tiltja, amelyet a Wine függősége kér. Ehhez kell egy szűk kivétel, pontosan a telepített amd64 verzióval, az `/etc/apt/preferences.d/bdencode-0-wine-i386` fájlban:

```
Package: libx265-199:i386
Pin: version <a telepített libx265-199:amd64 verzió>
Pin-Priority: 500
```

A `bdencode doctor` kimenetének `remux` mezője és a `capabilities` végpont `constraints.remux` értéke mutatja, hogy a gép képes-e remuxra. Ha nem, a Remux gomb le van tiltva.

## Ellenőrzőlista

1. `GET /api/v1/capabilities`: `backend_version` = `3.14.0`, `constraints.remux.available` = `true`, `constraints.remux.dolby_vision` = `true`.
2. Egy Blu-ray vagy UHD munka választójában a Remux gomb aktív, a Videó lépés eltűnik.
3. A kész munka Comparison lapján látszik a QC-összegzés, a képernyőképek, a BBCode-másolás és az eac3to-napló.
