# BDEncode

**Blu-ray és UHD Blu-ray lemezek kódolása böngészőből, lépésről lépésre.**

A BDEncode egy kész Blu-ray-mappából (a lemez `BDMV` mappájából) elkészíti a kész MKV-fájlt: kiválasztod a filmet, a hang- és feliratsávokat, a program pedig elvégzi a videó és a hang kódolását, ellenőrzi a minőséget, összehasonlító képeket készít, és összeállítja a release-csomagot (NFO, leírás, MediaInfo, képek). Mindezt egy weboldalon kezeled; parancssort csak a telepítésnél kell használnod.

> [!IMPORTANT]
> A BDEncode **tesztelési (béta) állapotban** van. Első alkalommal egy rövidebb vagy kevésbé fontos lemezzel próbáld ki, és a kész MKV-t mindig nézd is meg lejátszóval.

*English version: [README.en.md](README.en.md). A részletes technikai leírás (minden beállítás és belső működés): [docs/REFERENCE.md](docs/REFERENCE.md).*

## Tartalom

1. [Mire jó, és mire nem?](#1-mire-jó-és-mire-nem)
2. [Mire lesz szükséged?](#2-mire-lesz-szükséged)
3. [Melyik telepítést válaszd?](#3-melyik-telepítést-válaszd)
4. [Telepítés: Windows](#4-telepítés-windows)
5. [Telepítés: Debian szerver](#5-telepítés-debian-szerver)
6. [Telepítés: Swizzin seedbox](#6-telepítés-swizzin-seedbox)
7. [Első belépés és ellenőrzés](#7-első-belépés-és-ellenőrzés)
8. [Képfeltöltés beállítása (nem kötelező)](#8-képfeltöltés-beállítása-nem-kötelező)
9. [AI-tanácsadó (nem kötelező)](#9-ai-tanácsadó-nem-kötelező)
10. [Az első kódolás lépésről lépésre](#10-az-első-kódolás-lépésről-lépésre)
11. [Mindennapi használat](#11-mindennapi-használat)
12. [Frissítés](#12-frissítés)
13. [Ha valami nem működik](#13-ha-valami-nem-működik)
14. [Eltávolítás](#14-eltávolítás)
15. [Adatvédelem és biztonság](#15-adatvédelem-és-biztonság)
16. [Kisszótár](#16-kisszótár)

---

## 1. Mire jó, és mire nem?

**Amit csinál:**

- beolvassa a lemezt, és megmutatja a filmváltozatokat (playlisteket), hang- és feliratsávokat;
- elkészíti a videót: 1080p Blu-raynél x264-gyel, UHD-nál x265-tel, a HDR10 megtartásával (kérésre a Dolby Visiont és a HDR10+-t is);
- a hangot megtartja vagy átalakítja (például FLAC, AC-3, E-AC-3, DTS);
- automatikusan levágja a fekete sávokat (crop);
- minden képkockát ellenőriz, és mérőszámokkal (SSIM, PSNR, VMAF) igazolja a minőséget;
- összehasonlító (comparison) képeket készít a forrásról és a kódolásról, és kérésre feltölti őket egy képtárhelyre;
- az Aither és az nCore szabályai szerint rendezi a sávokat, javasol kiadásnevet, és release-csomagot készít;
- egyszerre egy kódolás fut, de közben a következő lemezeket már előkészítheted.

**Amit nem csinál:**

- **nem töri fel a lemez másolásvédelmét**: egy már kicsomagolt, `BDMV` mappát tartalmazó lemezmappát vár (ISO-fájlt nem);
- **nem készít torrentet, és nem tölt fel trackerre**: a kész MKV-ból a torrentet a tracker szabályai szerint te készíted el;
- nem kezeli a 3D-t;
- nem kódol GPU-val (a videókódolás mindig CPU-n fut; ha van NVIDIA GPU, a crop-keresés gyorsabb).

> [!NOTE]
> A programot saját lemezeid biztonsági mentéséhez készült. A trackerek szabályainak betartása a felhasználó felelőssége.

## 2. Mire lesz szükséged?

Pipáld végig, mielőtt nekiállsz:

| | Mi kell? | Megjegyzés |
|---|---|---|
| ☐ | **Egy gép**: Windows 10/11-es PC, vagy Debian 12/13-as szerver (seedbox is lehet) | lásd a [3. pontot](#3-melyik-telepítést-válaszd) |
| ☐ | **Processzor**: minél több mag, annál jobb | a kódolás teljesen leterheli a CPU-t; a terhelés felső határát te állítod be |
| ☐ | **Memória**: legalább 8 GB, UHD-hoz 16 GB vagy több | |
| ☐ | **Szabad hely**: a lemez méretének kb. 2,5-szerese | UHD-filmhez kb. 150–200 GB, 1080p-hez kb. 60–100 GB; a kész fájl ennek csak egy része |
| ☐ | **Lemezmappa**: a lemez kicsomagolt mappája (`BDMV` és általában `CERTIFICATE` alkönyvtárral) | ISO-t előbb csomagold ki |
| ☐ | **Internet** a telepítés idejére | a telepítő programokat tölt le |
| ☐ | **Türelem**: egy UHD-film kódolása 1–2 nap is lehet | lásd lent |

**Mennyi ideig tart?** Ez a géptől és a beállításoktól függ. Tájékoztatásul: egy kétórás UHD-film x265-tel, a `slow` beállítással egy 16 magos/32 szálas gépen nagyjából egy nap; nehezebb beállításokkal két nap is lehet. Egy 1080p-s film x264-gyel általában néhány óra. A program a kódolás alatt kiírja a sebességet és a várható befejezést.

## 3. Melyik telepítést válaszd?

| A helyzeted | Ezt kövesd |
|---|---|
| Otthoni Windows 10/11-es gépen akarod futtatni | [4. Telepítés: Windows](#4-telepítés-windows) |
| Van egy Debian szervered (VPS, saját gép, bérelt szerver) **Swizzin nélkül** | [5. Telepítés: Debian szerver](#5-telepítés-debian-szerver) |
| Van egy seedboxod **Swizzinnel** (ezen fut például a qBittorrent webes felülete) | [6. Telepítés: Swizzin seedbox](#6-telepítés-swizzin-seedbox) |

Nem tudod, van-e Swizzin a szervereden? Jelentkezz be SSH-val (lásd [5.2](#52-csatlakozás-a-szerverhez)), és futtasd: `ls /etc/swizzin`. Ha a mappa létezik, Swizzined van.

---

## 4. Telepítés: Windows

Windows alatt a BDEncode egy beépített Linux-környezetben (WSL2, Debian) fut, de ezzel neked nem kell foglalkoznod: a telepítő mindent beállít, a programot pedig a böngésződből használod.

### 4.1. Előkészületek

1. Legyen rendszergazdai jogod a gépen.
2. Legyen a C: meghajtón legalább **100 GB** szabad hely (ide kerül a Linux-környezet és a munkafájlok).
3. Hozz létre egy mappát a lemezeknek, egy betűjeles meghajtón, például `D:\Filmek`. Minden lemez egy külön almappa legyen benne:

   ```text
   D:\Filmek\Egy.Film.2001\BDMV
   D:\Filmek\Masik.Film.1999\BDMV
   ```

   Hálózati útvonalat (`\\szerver\megosztás`) a telepítő nem fogad el.
4. Laptopon állítsd be, hogy töltőn **ne aludjon el** (Beállítások → Rendszer → Energiagazdálkodás), különben a kódolás megáll, amíg a gép alszik.

### 4.2. A program letöltése

1. Nyisd meg a [projekt GitHub-oldalát](https://github.com/accofil/bdencode-backend).
2. Kattints a zöld **Code** gombra, majd a **Download ZIP** pontra.
3. Csomagold ki a ZIP-et egy állandó helyre, például `C:\BDEncode` mappába (a ZIP-en belülről ne indítsd el!).

### 4.3. A telepítő elindítása

1. Nyisd meg a kicsomagolt mappában az `install` mappát.
2. Kattints **jobb gombbal** a `windows-install.cmd` fájlra, és válaszd a **Futtatás rendszergazdaként** pontot.
3. A Windows kérdésére („Engedélyezi, hogy az alkalmazás módosításokat hajtson végre…”) válaszd az **Igen** gombot.
4. Egy kék/fekete ablak nyílik meg, amelyben a telepítő dolgozik. **Ne zárd be**, akkor sem, ha percekig nem jelenik meg új sor.

A telepítő magától bekapcsolja a WSL2-t, telepíti a Debiant, létrehoz egy Linux-felhasználót (a Windows-felhasználóneved alapján; jelszót nem kér), telepíti a médiaprogramokat és a BDEncode-ot.

### 4.4. Ha újraindítást kér

Az első telepítéskor ez normális (a WSL bekapcsolása miatt):

1. Nyomj **Entert**, és indítsd újra a gépet.
2. Jelentkezz be ugyanabba a Windows-fiókba.
3. A telepítő magától folytatódik. Ha mégsem, futtasd újra rendszergazdaként a `windows-install.cmd` fájlt: ott folytatja, ahol abbahagyta.

### 4.5. A lemezmappa kiválasztása

A telepítés közben egy mappaválasztó ablak nyílik meg. Azt a mappát válaszd ki, **amelyben a lemezek mappái vannak** (a fenti példában `D:\Filmek`), ne egy lemez mappáját.

### 4.6. Kész!

A telepítés az első alkalommal akár egy órát is igénybe vehet. A végén ezt látod:

```text
BDEncode Windows/WSL installation is healthy.
Web: http://localhost:8787/encoder/
```

Az asztalon két új parancsikon jelenik meg:

- **BDEncode** – megnyitja a kezelőfelületet (`http://localhost:8787/encoder/`);
- **BDEncode elkészült filmek** – megnyitja a kész fájlok mappáját.

Lépj tovább a [7. pontra](#7-első-belépés-és-ellenőrzés).

---

## 5. Telepítés: Debian szerver

Ez az út egy Swizzin nélküli Debian 12 vagy 13 szerverhez való. A kezelőfelület a szerveren csak belül érhető el; a saját gépedről egy biztonságos SSH-alagúton nyitod meg (lásd [5.8](#58-a-felület-megnyitása-ssh-alagúton)). Így nem kell portot nyitnod, és jelszót sem kell beállítanod a weboldalhoz.

### 5.1. Amit tudnod kell a szerverről

- a szerver címe (IP-cím vagy domain név), és ha nem a szokásos 22-es, az SSH-port;
- a felhasználóneved és jelszavad (vagy SSH-kulcsod);
- hogy a felhasználód használhatja-e a `sudo` parancsot (rendszergazdai jog). Ezt a szolgáltatód tudja megmondani, vagy kipróbálod az [5.3-ban](#53-ellenőrzések).

> [!WARNING]
> Ne a `root` felhasználóval telepíts. A telepítő maga kér `sudo` jogot oda, ahol kell.

### 5.2. Csatlakozás a szerverhez

Windows 10/11-en a PowerShell már tartalmazza az `ssh` parancsot. Nyiss egy PowerShell-ablakot (Start menü → „PowerShell”), és írd be (a `felhasznalo` és a `szerver` helyére a sajátodat):

```bash
ssh felhasznalo@szerver
```

Ha nem a 22-es porton fut az SSH, add meg a portot is: `ssh -p 2222 felhasznalo@szerver`. Az első csatlakozáskor a gép rákérdez a szerver azonosítójára: írd be, hogy `yes`. Utána add meg a jelszavadat (gépelés közben nem látszik semmi, ez normális).

### 5.3. Ellenőrzések

Futtasd egyenként, és nézd meg a választ:

```bash
cat /etc/os-release
```

A `VERSION_CODENAME` sor `bookworm` (Debian 12) vagy `trixie` (Debian 13) legyen.

```bash
sudo -v
```

Ha jelszót kér, és utána nem ír hibát, van `sudo` jogod. Ha azt írja, hogy nem vagy a „sudoers” között, kérj jogot a szerver gazdájától.

### 5.4. Alapcsomagok

```bash
sudo apt-get update
```

```bash
sudo apt-get install -y git tmux
```

### 5.5. Mappák és lemezek

Alapértelmezésben a BDEncode itt keresi a lemezeket és ide dolgozik:

| Mappa | Mire való? |
|---|---|
| `~/storage` | a lemezek mappái (forrás) – a program csak olvassa |
| `~/encode` | a program saját területe: adatbázis, munkafájlok, kész filmek (`~/encode/completed`) |

Hozd létre a forrásmappát:

```bash
mkdir -p ~/storage
```

A lemezeket (egész mappákat, `BDMV`-vel együtt) egy fájlátviteli programmal másold fel ide, például **WinSCP**-vel vagy **FileZillá**val (SFTP, ugyanazzal a felhasználóval és jelszóval, mint az SSH). Az eredmény így nézzen ki:

```text
~/storage/Egy.Film.2001/BDMV
~/storage/Masik.Film.1999/BDMV
```

Ha a lemezeid máshol vannak (például egy torrentkliens letöltési mappájában), azt a mappát is megadhatod a telepítőnek, lásd [5.6](#56-a-telepítő-futtatása).

### 5.6. A telepítő futtatása

A telepítés eltarthat egy ideig (gyors gépen pár perc, lassú gépen egy óra is lehet). Hogy egy megszakadt SSH-kapcsolat ne állítsa le, egy `tmux` nevű „munkamenetben” futtatjuk:

```bash
tmux new -s bdencode
```

Töltsd le a programot:

```bash
git clone https://github.com/accofil/bdencode-backend.git ~/bdencode-backend
```

```bash
cd ~/bdencode-backend
```

Indítsd el a telepítőt az alapértelmezett mappákkal (`~/storage` és `~/encode`):

```bash
bash install/install.sh
```

**Ha a lemezeid máshol vannak**, a mappát így adhatod meg (a példában `~/torrents`):

```bash
BDENCODE_SOURCE_ROOT="$HOME/torrents" bash install/install.sh
```

Hasznos még: `BDENCODE_CPU_PERCENT=60` (a gép processzorának legfeljebb ennyi százalékát használja; alapból 80, és később a weboldalon is átállíthatod).

A telepítő közben többször is kérheti a `sudo` jelszavadat. A végén ezt írja ki:

```text
Web page (loopback only): http://127.0.0.1:8787/encoder/
From your own computer: ssh -L 8787:127.0.0.1:8787 felhasznalo@<server>, then open http://localhost:8787/encoder/
```

**Ha megszakad a kapcsolat:** jelentkezz be újra SSH-val, és csatlakozz vissza a futó telepítéshez: `tmux attach -t bdencode`. A `tmux`-ból úgy lépsz ki a telepítés leállítása nélkül, hogy megnyomod a `Ctrl+B`, majd a `D` billentyűt.

### 5.7. Automatikus frissítés engedélyezése (ajánlott, de nem kötelező)

A BDEncode naponta megnézi, van-e új kiadás. Telepíteni csak akkor tudja magától, ha a felhasználód **jelszó nélkül** használhatja a `sudo`-t. Ennek kockázata: aki a felhasználódhoz hozzáfér, jelszó nélkül rendszergazda lesz. Ha ezt vállalod:

```bash
echo "$USER ALL=(ALL) NOPASSWD:ALL" | sudo tee /etc/sudoers.d/bdencode-$USER
```

```bash
sudo chmod 0440 /etc/sudoers.d/bdencode-$USER
```

Ha kihagyod, a program jelzi az új kiadást a weboldalon, és a frissítést a [12. pont](#12-frissítés) szerint kézzel végzed.

### 5.8. A felület megnyitása SSH-alagúton

A kezelőfelület a szerveren csak belülről érhető el. A saját gépeden nyiss egy **új** PowerShell-ablakot, és futtasd:

```bash
ssh -L 8787:127.0.0.1:8787 felhasznalo@szerver
```

Jelentkezz be, és **hagyd nyitva ezt az ablakot**. Amíg nyitva van, a böngésződben ez a cím a szerver BDEncode-oldalát mutatja:

```text
http://localhost:8787/encoder/
```

Ha bezárod az ablakot, az oldal elérhetetlen lesz, de a kódolás a szerveren tovább fut. Legközelebb ugyanezzel a paranccsal nyitod meg újra.

Lépj tovább a [7. pontra](#7-első-belépés-és-ellenőrzés).

---

## 6. Telepítés: Swizzin seedbox

Swizzines szerveren a telepítő felismeri a Swizzin webszerverét, és a kezelőfelületet a seedbox saját címén, a Swizzin jelszavával védve teszi elérhetővé: `https://a-seedboxod-címe/encoder/`.

### 6.1. A telepítés

Kövesd a Debian-telepítés lépéseit [5.1-től 5.6-ig](#51-amit-tudnod-kell-a-szerverről), ezekkel az eltérésekkel:

- **A lemezmappa:** Swizzinen a letöltések gyakran a `~/torrents` vagy a `~/storage` alatt vannak. Ha a lemezeid a `~/torrents` alatt vannak, így indítsd a telepítőt:

  ```bash
  BDENCODE_SOURCE_ROOT="$HOME/torrents" bash install/install.sh
  ```

- **A processzor megosztása:** a seedboxon a torrentkliens is fut. Ha a kódolás alatt lassul a seedelés, adj kisebb CPU-keretet: `BDENCODE_CPU_PERCENT=60` (vagy később a weboldalon, lásd [7.3](#73-a-cpu-keret-beállítása)).
- **Lassú, csak HDD-s gépen** a telepítés akár egy óráig is tarthat (közben teszteket futtat). Ezért fontos a `tmux`.

### 6.2. Automatikus frissítés

Ugyanaz, mint a Debian szervernél: [5.7](#57-automatikus-frissítés-engedélyezése-ajánlott-de-nem-kötelező).

### 6.3. A felület megnyitása

Nyisd meg a böngészőben:

```text
https://a-seedboxod-címe/encoder/
```

A felhasználónév és a jelszó ugyanaz, mint a Swizzin többi webes felületén. SSH-alagút itt nem kell.

Lépj tovább a [7. pontra](#7-első-belépés-és-ellenőrzés).

---

## 7. Első belépés és ellenőrzés

### 7.1. A kezelőfelület

Bal oldalon a menü:

| Menüpont | Mire való? |
|---|---|
| **Áttekintés** | a futó munka és a sor összefoglalója |
| **Új kódolás** | új lemez hozzáadása |
| **Várólista** | az összes munka és állapotuk |
| **Elkészült munkák** | a kész filmek |
| **Összehasonlítások** | a comparison képek |
| **Statisztika** | méretek, minőség, sebesség |
| **Rendszer** | a szerver állapota és beállításai |
| **Súgó** | magyar nyelvű súgó minden kódolási beállításhoz |

A menü tetején, a BDEncode felirat alatt látszik a telepített verzió. A menü alján a **HU / EN** gombbal válthatsz nyelvet (magyar vagy angol); első alkalommal a böngésződ nyelvét használja.

### 7.2. A Rendszer oldal ellenőrzése

Nyisd meg a **Rendszer** oldalt, és nézd meg:

- **Backend: Online** – a program fut;
- **Telepített programok**: mindegyik mellett **Elérhető**, és a kártya fejlécén **VapourSynth OK** szerepel;
- **Tárhely**: van-e elég szabad hely;
- **Processzor**: a logikai CPU-k száma, a CPU-keret, és hogy van-e GPU a crop-kereséshez (ha nincs, az is rendben van).

Ha valami pirosan jelez, nézd meg a [13. pontot](#13-ha-valami-nem-működik).

### 7.3. A CPU-keret beállítása

A **Rendszer** oldal **CPU-keret** kártyáján állíthatod be, hogy a kódolás a processzor legfeljebb hány százalékát használja. Megadhatsz külön éjszakai értéket is (például éjjel 100%, nappal 60%), ha napközben más is fut a gépen. A változás néhány másodpercen belül életbe lép, egy futó kódolásnál is.

---

## 8. Képfeltöltés beállítása (nem kötelező)

A program az összehasonlító képeket fel tudja tölteni egy képtárhelyre, és kész BBCode-ot készít belőlük a tracker-leíráshoz. Ehhez legalább egy szolgáltató kulcsa kell:

| Szolgáltató | Mi kell? | A beállítás neve |
|---|---|---|
| ImgBB | API-kulcs (regisztráció után az ImgBB API oldalán) | `imgbb-api-key` |
| Catbox | felhasználói azonosító, „userhash” (a fiókod oldalán) | `catbox-userhash` |
| Freeimage | API-kulcs (a Freeimage API oldalán) | `freeimage-api-key` |

Elég egy is, de kettő ajánlott: ha az egyik nem működik, a program a másikkal próbálkozik. Képfeltöltés nélkül is minden működik; a képek a kész mappában megmaradnak.

> [!IMPORTANT]
> A kulcsot ne írd be chatbe, hibajelentésbe, és ne tedd képernyőképre. Az alábbi módszer titkosítva menti, és begépeléskor sem látszik.

**1. Nyiss parancssort a BDEncode gépén.** Windows-telepítésnél nyiss PowerShellt, és írd be: `wsl -d Debian` (ezzel a BDEncode Linux-környezetébe lépsz). Szerveren jelentkezz be SSH-val.

**2. Másold be ezt a teljes blokkot egyben, és nyomj Entert** (ez egy segédparancsot hoz létre):

```bash
install_bdencode_secret() {
    credential_name="$1"
    credential_dir="$HOME/.config/bdencode"
    temporary_file="$(mktemp)"
    mkdir -p "$credential_dir"
    chmod 700 "$credential_dir"
    read -r -s -p "$credential_name értéke: " credential_value
    printf '\n'
    printf '%s' "$credential_value" > "$temporary_file"
    unset credential_value
    sudo systemd-creds encrypt \
        --name="$credential_name" \
        "$temporary_file" \
        "$credential_dir/$credential_name.cred"
    rm -f "$temporary_file"
    sudo chown "$USER:$(id -gn)" \
        "$credential_dir/$credential_name.cred"
    chmod 600 "$credential_dir/$credential_name.cred"
}
```

**3. Add meg a kulcsokat.** Csak azt a sort futtasd, amelyikhez van kulcsod; a program bekéri az értéket (gépelés közben nem látszik):

```bash
install_bdencode_secret imgbb-api-key
```

```bash
install_bdencode_secret catbox-userhash
```

```bash
install_bdencode_secret freeimage-api-key
```

**4. Futtasd újra a telepítőt**, hogy a program megkapja a kulcsokat:

- Windowson: lépj ki a Linux-környezetből (`exit`), és futtasd újra rendszergazdaként a `windows-install.cmd` fájlt.
- Szerveren:

  ```bash
  cd ~/bdencode-backend && bash install/install.sh
  ```

Ellenőrzés: a **Rendszer** oldalon a képfeltöltők mellett **Használatra kész** szerepel.

## 9. AI-tanácsadó (nem kötelező)

Egy AI (OpenAI vagy Claude) a lemez technikai adatai és a megadott célod alapján kódolási beállításokat javasolhat. Ehhez saját API-kulcs kell (ez a szolgáltatónál fizetős lehet). Kulcs nélkül minden más működik.

1. Nyisd meg a **Rendszer** oldalt, és keresd meg az **AI tanácsadó** kártyát.
2. A kívánt szolgáltató sorában írd be a kulcsot, és kattints a **Kulcs mentése** gombra.
3. Néhány másodperc múlva a sor állapota **Kulcs beállítva** lesz.

Az AI nem kapja meg a filmet, a képeket vagy a fájlneveket, csak egy rövid technikai összefoglalót. A javaslata csak kitölti a mezőket; jóvá neked kell hagynod.

---

## 10. Az első kódolás lépésről lépésre

### 10.1. Új munka létrehozása

1. Kattints az **Új kódolás** menüpontra.
2. **Forrás:** kattints a lemez mappájára. A program a `BDMV`-t tartalmazó mappákat **Blu-ray forrás** felirattal jelöli. Ha nem látod a lemezt, kattints a **Frissítés** gombra.
3. Kattints a **Tovább** gombra.
4. **Tartalom:** add meg a munka nevét (például a film címét), ellenőrizd a lemeztípust (BD vagy UHD), és válaszd ki, mi van a lemezen: **Film**, **Koncert**, **Anime** vagy **Sorozatlemez**.
5. **Munkamód:** első alkalommal válaszd a **Kezdő** módot. Itt kapcsolhatod ki vagy be a **Comparison képek feltöltése** lehetőséget is.
6. Kattints a **Munka létrehozása és scan** gombra.

A scan néhány perc alatt feltérképezi a lemezt. Ez még nem a kódolás.

### 10.2. A beállítóvarázsló

Ha a scan elkészült, a munka oldalán megjelenik a **Te következel** kártya. Nyisd meg a **Beállítások** fület. A varázsló négy lépésből áll:

**1. Playlist** – a lemezen lévő filmváltozatok. Általában a leghosszabb a film, de figyelj:

- ha több hasonló hosszúságú van, lehet moziváltozat, rendezői változat vagy más vágás: nézd meg a hosszt, a fejezetek és a hangsávok számát;
- egyes lemezek hamis, „csapda” playlisteket tartalmaznak; a program ezeket jelzi.

**2. Sávok** – a hang- és feliratsávok.

- A tetején választhatsz **tracker-profilt** (Aither vagy nCore). A **Sávterv igazítása** gomb ilyenkor a tracker szabályai szerint rendezi a sávokat, és a **Mi változott** lista megmutatja, mit módosított.
- Minden hangsávnál kiválaszthatod, mi legyen vele: **Copy** (változatlanul megtartja), **FLAC**, **AC-3**, **E-AC-3**, **DTS** vagy **Kihagyás**. Ha nem tudod, hagyd a javasolt értéken.
- Minden megtartott feliratnál meg kell adnod, hogy **Teljes felirat** vagy **Forced / signs** (csak a nem magyar/nem angol beszédrészeket feliratozó).
- **Sávelemzés a lemezből:** a scan végén a program a film néhány rövid részletéből (6 × 30 másodperc) beszédfelismeréssel megállapítja a hangsávok nyelvét, és megszámolja a feliratok eseményeit. A sorokban ezt látod:
  - hangsávnál „A hang alapján: angol, 95%”; ha ez eltér a lemez jelölésétől, sárga figyelmeztetés és **Elfogadás** gomb jelenik meg;
  - feliratnál „Javaslat: Teljes felirat (31 esemény 3 perc mintában…)” vagy „Javaslat: Forced / signs”, és **Javaslat elfogadása** gomb. A teljes feliratnak percenként több eseménye van, a forcednak csak néhány az egész filmben.

  A **Minden javaslat elfogadása** gomb egyszerre elfogadja őket. Ezek javaslatok: ha bizonytalan, nézz bele a kész fájlba, vagy hagyd ki a sávot.
- Ha egy sáv nyelve hiányzik vagy bizonytalan, a program jelzi; ilyenkor válaszd ki kézzel.

**3. Videó** – a kódolás beállításai.

- Kezdő módban a program biztonságos alapértékeket ad; ezeket nyugodtan hagyd így.
- Minden beállítás mellett egy **?** gomb nyitja meg a magyar nyelvű magyarázatot.
- Ha beállítottad az AI-tanácsadót, itt kérhetsz tőle javaslatot (**AI-javaslat kérése**).
- A fekete sávok levágása (crop) automatikus.

**4. Ellenőrzés**

1. Add meg a kimeneti nevet. Tracker-profilnál a **Név javaslata** gomb a szabályoknak megfelelő nevet állít össze (a release-taget a böngésző megjegyzi).
2. Kattints a **Terv ellenőrzése** gombra. A program ellenőrzi az összes beállítást.
3. Ha pirossal jelez hibát, javítsd. A sárga figyelmeztetéseket olvasd el.
4. Kattints a **Jóváhagyás és automatikus indítás** gombra.

A munka ezzel **Kódolásra vár** állapotba kerül, és ha nem fut más kódolás, el is indul.

### 10.3. A munka követése

A munka oldalán a **Most fut** panel mutatja, éppen mit csinál a program (például: referencia-remux, crop-keresés, kódolás, minőség-ellenőrzés), mennyi van még hátra, és kódolás közben a sebességet és a várható fájlméretet. Az oldalt be is zárhatod: a munka a háttérben fut tovább.

A munka állapotai sorban (a Várólistán és a munka oldalán is ezek látszanak): **Scanre vár** → **Lemez elemzése** → **Beállításra vár** (itt te következel) → **Kódolásra vár** → **Videó kódolása** (az előkészítéssel együtt ez a leghosszabb) → **MKV összeállítása** → **Minőség-ellenőrzés** → **Kép-összehasonlítás** → **Képek feltöltése** (ha kérted) → **Elkészült**.

### 10.4. A kész film

Ha a munka **Elkészült** állapotba került:

- **Windowson** az asztali **BDEncode elkészült filmek** parancsikon nyitja meg a kész fájlok mappáját.
- **Szerveren** a kész filmek itt vannak: `~/encode/completed/<a-film-neve>/`.

A mappában találod az MKV-t, és mellette a MediaInfót, a BBCode-ot és az összehasonlító képeket. Az **Elkészült munkák** oldalon a munkára kattintva megnézheted a minőségi eredményeket, a képeket és a naplókat, sőt a beépített lejátszóval bele is nézhetsz a filmbe.

**Mindig nézd meg a kész filmet egy lejátszóval:** az elejét, a végét, egy fejezetváltást, és kapcsolgass a hang- és feliratsávok között.

### 10.5. Release-csomag (nem kötelező)

A kész munka oldalán a **Release előkészítése** panel összeállítja a feltöltéshez szükséges anyagokat: NFO, BBCode-leírás, MediaInfo, ellenőrzött képek, ellenőrzőösszegek. A torrentet a kész MKV-ból a tracker szabályai szerint te készíted el, és te töltöd fel.

---

## 11. Mindennapi használat

**Egyszerre egy kódolás fut**, de közben új lemezeket adhatsz hozzá és beállíthatsz: ezek **Kódolásra vár** állapotban várnak, és sorban automatikusan elindulnak.

**Ha a program kérdez** (a munka **Ellenőrzést kér** állapotba kerül), a munka oldalán egy kártya mutatja, mi a teendő. Gyakori esetek:

- **nyelv:** egy sáv nyelve nem egyértelmű – válaszd ki, és kattints a **Nyelvek megerősítése és folytatás** gombra;
- **képfeltöltés:** a feltöltés nem sikerült – próbáld újra, válassz másik tárhelyet, vagy fejezd be képek nélkül (a videót egyik sem kódolja újra).

**Szüneteltetés, megszakítás, újraindítás** – a munka oldalán a **Műveletek** menüben:

| Művelet | Mire jó? |
|---|---|
| **Szüneteltetés** / **Folytatás** | ideiglenesen megállítja a munkát; a már elkészült lépések megmaradnak |
| **Megszakítás** | leállítja a munkát |
| **Újraindítás** (megszakított munkánál) | **Újraindítás ugyanígy**: ugyanazokkal a beállításokkal újra a sorba; **Beállítások módosítása**: a varázsló a korábbi beállításokkal nyílik meg, és átírhatsz bármit |
| **Folytatás a hibától** (hibás munkánál) | onnan folytatja, ahol a hiba történt |
| **Munka törlése** | a munka és az ideiglenes fájljai törlődnek; a kész film és az eredeti lemez megmarad |

Újraindításkor a program megtartja, amit a változás nem érint (például a lemez beolvasását és a crop-keresést), és csak azt csinálja újra, amit kell.

**Hely felszabadítása:** egy kész munka ideiglenes fájljai a munka oldalán a **Takarítás** gombbal törölhetők; a kész film megmarad. Futó munka alól ne törölj kézzel fájlokat.

---

## 12. Frissítés

**Automatikusan:** a program naponta egyszer megnézi, van-e új kiadás, és ha a gépen éppen nem fut munka, magától frissít (szerveren ehhez az [5.7](#57-automatikus-frissítés-engedélyezése-ajánlott-de-nem-kötelező) szerinti beállítás kell). Hiba esetén a régi verzió marad meg. Az állapotot a **Rendszer** oldal **Kiadáskeresés és frissítés** kártyája mutatja.

Ha a böngészőben nyitva felejtett lap még a régi felületet mutatja, a menüben megjelenik az **Oldal frissítése** gomb.

**Kézzel, Windowson:** töltsd le újra a ZIP-et ([4.2](#42-a-program-letöltése)), csomagold ki a régi helyére, és futtasd rendszergazdaként a `windows-install.cmd` fájlt. A beállításaid és a munkáid megmaradnak.

**Kézzel, szerveren:**

```bash
cd ~/bdencode-backend && git pull --ff-only && bash install/install.sh
```

Frissítés előtt várd meg, hogy a futó kódolás befejeződjön.

---

## 13. Ha valami nem működik

| Jelenség | Mit tegyél? |
|---|---|
| **Windows:** a `localhost:8787` oldal nem jön be | Várj fél percet, és frissítsd az oldalt. Ha így sem megy, nyiss rendszergazdai PowerShellt, és futtasd: `Start-ScheduledTask -TaskName "BDEncode WSL"`, majd `wsl -d Debian -- sudo systemctl restart bdencode-api bdencode-worker nginx` |
| **Szerver:** a `localhost:8787` oldal nem jön be | Nyitva van az SSH-alagút ablaka ([5.8](#58-a-felület-megnyitása-ssh-alagúton))? Ha igen, a szerveren: `sudo systemctl restart bdencode-api bdencode-worker nginx` |
| **Swizzin:** az `/encoder/` oldal hibát ad | A szerveren: `sudo systemctl restart bdencode-api bdencode-worker` és `sudo systemctl reload nginx` |
| A lemez nem látszik az **Új kódolás** oldalon | Jó mappát adtál meg a telepítéskor? A lemez mappájában közvetlenül legyen ott a `BDMV`. Kattints a **Frissítés** gombra. |
| A laptop elaludt, és a kódolás megállt | Ébresztés után a munka folytatódik. Állítsd be, hogy töltőn ne aludjon el. |
| Elfogyott a hely | Töröld a régi, kész munkák ideiglenes fájljait (**Takarítás**), vagy a felesleges munkákat (**Munka törlése**). A [2. pontban](#2-mire-lesz-szükséged) megadott hely kell egy munkához. |
| **Ellenőrzést kér** állapot | Nyisd meg a munkát: a kártya leírja, mi a teendő ([11. pont](#11-mindennapi-használat)). |
| **Feltöltési hiba** állapot | A program előbb kb. 33 percig magától újrapróbálja. Ha így sem sikerül, a munka oldalán: újrapróbálás, másik tárhely, vagy befejezés képek nélkül. Ellenőrizd a képfeltöltő kulcsokat ([8. pont](#8-képfeltöltés-beállítása-nem-kötelező)). |
| **Hibás** állapot | Olvasd el a hibaüzenetet a munka oldalán. A **Folytatás a hibától** onnan folytatja, ahol abbamaradt. |
| Nagyon lassú a kódolás | A Rendszer oldalon nézd meg a CPU-keretet ([7.3](#73-a-cpu-keret-beállítása)). Lassabb beállítás (például `slower` preset) sokkal tovább tart. |

**Naplók** (ha segítséget kérsz, ezek kellenek):

- Windows-telepítés: `%LOCALAPPDATA%\BDEncode\install.log` (PowerShellben: `notepad "$env:LOCALAPPDATA\BDEncode\install.log"`);
- a futó program naplója (szerveren, illetve Windowson a `wsl -d Debian` után):

  ```bash
  journalctl -u bdencode-worker.service -n 200 --no-pager
  ```

- teljes rendszerállapot:

  ```bash
  "$HOME/encode/app/current/venv/bin/bdencode" doctor --json
  ```

**Gyors állapotellenőrzés** (ha az oldal nem jön be, ezzel kiderül, fut-e a program):

- szerveren, a programon belül: `curl --fail --silent http://127.0.0.1:8796/api/v1/health`
- Windowson, PowerShellből: `curl.exe --noproxy "*" http://127.0.0.1:8787/encoder/api/v1/health`
- Swizzinen, kívülről (a curl bekéri a jelszót): `curl --fail --silent --user FELHASZNALO https://sajat-domain.example/encoder/api/v1/health`

Ha a válasz `"status":"ok"`-ot tartalmaz, a program fut.

**Hibajelentés:** nyiss egy *issue*-t a [GitHub-oldalon](https://github.com/accofil/bdencode-backend/issues). Írd le, mit csináltál, mi történt, melyik verzió fut (a menü tetején), és másold be a fenti naplók érintett részét. **API-kulcsot, jelszót és credential fájlt soha ne küldj.**

---

## 14. Eltávolítás

- **Szerveren** (a munkáid és a kész filmjeid megmaradnak):

  ```bash
  cd ~/bdencode-backend && bash install/uninstall.sh
  ```

  A teljes adatmappa törléséről és a többi lehetőségről a [részletes leírás 12. fejezete](docs/REFERENCE.md#12-eltávolítás-linux-vagy-szerver-esetén) szól.
- **Windowson:** lásd a [részletes leírás 13. fejezetét](docs/REFERENCE.md#13-eltávolítás-windows-esetén).

Az eredeti lemezeidhez az eltávolítás nem nyúl.

## 15. Adatvédelem és biztonság

- **Mi hagyja el a gépet?** Csak az, amit kérsz: az összehasonlító képek a beállított képtárhelyre (ha bekapcsoltad), az AI-tanácsadónál egy rövid technikai összefoglaló (ha beállítottad), és a napi frissítéskeresés a GitHubra. Statisztikát, telemetriát a program nem küld.
- **A kezelőfelület** Windowson csak a saját gépedről, Debian szerveren csak SSH-alagúton, Swizzinen a Swizzin jelszavával érhető el. A belső `8796`-os portot soha ne nyisd meg az internet felé.
- **A kulcsok** titkosítva, a gép saját systemd-kulcsával kerülnek a `~/.config/bdencode` mappába.
- **Az automatikus frissítés** azt jelenti, hogy a gépeden a GitHub-repóban megjelenő új kiadás települ. Ha ezt nem szeretnéd, kapcsold ki: `sudo systemctl disable --now bdencode-update.timer` (ilyenkor kézzel frissítesz). Részletek: [részletes leírás 11. fejezet](docs/REFERENCE.md#11-frissítés).
- **A lemezeidet** a program csak olvassa, soha nem módosítja és nem törli.

## 16. Kisszótár

| Kifejezés | Jelentése |
|---|---|
| **BDMV** | a Blu-ray lemez tartalmát tartalmazó mappa |
| **Playlist** | egy lejátszási lista a lemezen; egy filmváltozat vagy epizód |
| **Remux** | a lemez sávjainak átcsomagolása kódolás nélkül (a program ebből dolgozik) |
| **x264 / x265** | a videókódolók: 1080p-hez x264 (AVC), UHD-hoz x265 (HEVC) |
| **CRF** | a minőségi szint; kisebb szám = jobb minőség és nagyobb fájl |
| **Preset** | a kódoló alapossága (`slow`, `slower`…); lassabb = hatékonyabb, de tovább tart |
| **HDR10, Dolby Vision, HDR10+** | a nagyobb fényerő- és színtartomány formátumai UHD-n |
| **Crop** | a fekete sávok levágása a kép széleiről |
| **Comparison** | összehasonlító képpárok a forrásról és a kódolásról |
| **VMAF, SSIM, PSNR** | a képminőséget számszerűen mérő mutatók |
| **WSL2** | a Windows beépített Linux-környezete; Windowson ebben fut a BDEncode |
| **SSH** | titkosított távoli bejelentkezés egy szerverre |
| **SSH-alagút** | egy SSH-kapcsolaton átvezetett biztonságos út a szerver belső weboldalához |
| **tmux** | egy program, amelyben a parancsok a kapcsolat megszakadása után is tovább futnak |
| **sudo** | rendszergazdaként futtat egy parancsot |
| **Swizzin** | seedboxokon gyakori kezelőrendszer webes felületekkel |

---

A BDEncode MIT-licenc alatt érhető el, lásd: [LICENSE](LICENSE). A változások listája a [docs](docs) mappa `RELEASE_*.md` fájljaiban található.
