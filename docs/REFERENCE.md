# BDEncode – részletes technikai leírás

Ez a BDEncode teljes, részletes kézikönyve: minden beállítás, állapot, biztonsági szabály és üzemeltetési tudnivaló. **Ha most ismerkedsz a programmal, a lépésről lépésre vezető [kezdő útmutatóval](../README.md) kezdj** (angolul: [README.en.md](../README.en.md)); ide akkor gyere, ha valaminek a részleteire vagy kíváncsi.

> [!IMPORTANT]
> A BDEncode fejlesztés alatt áll. Első használatkor érdemes egy rövidebb vagy kevésbé fontos lemezzel próbát végezni, és az elkészült MKV-t lejátszással is ellenőrizni.

> [!NOTE]
> A **3.0** trackerkompatibilitási kiadás. Egy munka az Aither vagy az nCore (és a magyar release-szabvány) szabályai szerint készülhet. A sávterv, a kiadásnév, a kötelező kódolóbeállítások, a tracker-BBCode és az nCore-minta automatikus. Új a magyar nyelvű kódolási súgó és az Aither-presetek. Részletek: [3.0 kiadási jegyzet](RELEASE_3_0.md), illetve a 7.3.1. pont.
>
> A 2.3 a minőségkapu (színeltolódás-mérés) és a kiadási folyamat finomítása, a [2.3 kiadási jegyzet](RELEASE_2_3.md) szerint. A 2.2 automatikus VMAF-alapú CRF-keresést, zaj- és szemcseprofilokat, változó képarány-kezelést, opcionális HDR10+/Dolby Vision megtartást, beépített lejátszót, statisztikát, adatbázis-mentést, valamint napi kiadáskeresést és felügyelet nélküli frissítést vezet be. Frissítés előtt olvasd el a [BDEncode 2.2 kiadási jegyzetet](RELEASE_2_2.md) és a [2.2.1 biztonsági finomítás](RELEASE_2_2_1.md) jegyzetét. A [2.1](RELEASE_2_1.md) és a [2.0](RELEASE_2_0.md) kiadási jegyzet történeti dokumentumként továbbra is elérhető.

## Tartalomjegyzék

- [1. Mire képes a rendszer?](#1-mire-képes-a-rendszer)
- [2. Fontos fogalmak](#2-fontos-fogalmak)
- [3. Telepítés Windows 10/11-re](#3-telepítés-windows-1011-re)
- [4. Telepítés Debian szerverre](#4-telepítés-debian-szerverre)
- [5. Képfeltöltő és release szolgáltatások beállítása](#5-képfeltöltő-és-release-szolgáltatások-beállítása)
- [6. A telepítés ellenőrzése](#6-a-telepítés-ellenőrzése)
- [7. Első kódolás lépésről lépésre](#7-első-kódolás-lépésről-lépésre)
- [8. A várólista és az állapotok](#8-a-várólista-és-az-állapotok)
- [9. Naplók, elemzések és comparison](#9-naplók-elemzések-és-comparison)
- [10. Gyakori hibák és javításuk](#10-gyakori-hibák-és-javításuk)
- [11. Frissítés](#11-frissítés)
- [12. Eltávolítás Linux vagy szerver esetén](#12-eltávolítás-linux-vagy-szerver-esetén)
- [13. Eltávolítás Windows esetén](#13-eltávolítás-windows-esetén)
- [14. Haladó üzemeltetési tudnivalók](#14-haladó-üzemeltetési-tudnivalók)
- [15. Fejlesztés és tesztelés](#15-fejlesztés-és-tesztelés)

## 1. Mire képes a rendszer?

A főbb funkciók:

- normál Blu-ray AVC, VC-1 vagy MPEG-2 forrás feldolgozása x264/AVC kimenettel;
- UHD Blu-ray HEVC forrás feldolgozása x265/HEVC kimenettel, statikus HDR10 megtartásával;
- film, koncert, anime és sorozatlemez kezelése;
- több filmváltozat vagy playlist esetén grafikus választás;
- hangsávok és feliratok kiválasztása, nyelvének felülbírálása;
- sávonként `copy`, `flac`, `ac3`, `eac3`, `dts` vagy `omit` hangművelet;
- rögzített minőségi hangprofilok: AC-3 640 kb/s, E-AC-3 1024 kb/s és DTS core 1536 kb/s, 48 kHz-en, legfeljebb 5.1 csatornával;
- DTS-HD forrásnál lehetőség szerint újrakódolás nélküli DTS core kinyerés, TrueHD vagy más forrásnál ellenőrzött DTS-kódolás;
- Blu-ray LPCM esetén a Matroska által nem támogatott bitstream-copy helyett FLAC/AC-3/E-AC-3/DTS átalakítás vagy elhagyás;
- Kezdő, Haladó és Profi beállítási szint;
- opcionális AI-tanácsadó, amely a technikai scan és a megadott minőségi cél alapján szerkeszthető x264/x265 profiljavaslatot készít;
- egyszerre egy teljes kódolás, miközben további lemezek előkészíthetők és sorba állíthatók;
- legfeljebb a gép logikai CPU-kapacitásának beállított hányadát használó worker;
- tartós pause-kérés, worker-visszaigazolás és biztonságos folytatás a webes felületről;
- megszakított vagy hibás munka biztonságos folytatása;
- hibás vagy megszakított munka teljes törlése az ideiglenes fájlokkal együtt;
- tárhely-előnézet és a befejezett jobok ideiglenes munkaterületének célzott takarítása;
- teljes dekódolási video QC, valamint codec-, profil-, szín- és HDR10-ellenőrzés;
- veszteségmentes hangnál PCM-hash, veszteséges hangnál célkodek-, bitráta-, mintavétel-, csatorna- és időzítés-ellenőrzés;
- alapértelmezetten 24, a címen elosztott, veszteségmentes PNG comparison képpár;
- I-, P- és B-frame összehasonlítás azonos képtípusok között;
- a képeken forrásmegjelölés, képkockaszám és frame-típus;
- hangosság-, fázis- és spektrális hangelemzés;
- ImgBB, Catbox és Freeimage képfeltöltés, hibánál tartalék szolgáltatóval;
- BBCode készítése;
- MPLS/CLPI/PMT nyelvi adatok összesítése, ismeretlen hangnál választható CPU-s beszédfelismerési segítség és bizonytalanságnál kézi ellenőrzés;
- privát nyers és tisztított napló; a publikus MKV nem kap naplót vagy más csatolmányt, a comparison külön sidecar marad;
- release-csomag (NFO, BBCode-leírás, MediaInfo, ellenőrzött képek, checksumok) és dupe check; torrentet 3.0-tól nem készít, és a trackerre sem tölt fel;
- napi kiadáskeresés, és új kiadásnál felügyelet nélküli, visszagörgethető frissítés;
- opcionális **automatikus CRF-keresés**: rövid, VMAF-pontozott mintakódolásokból választja ki a célminőséghez tartozó CRF-et;
- **zaj- és szemcseprofilok** (szemcse megtartása, enyhe/közepes/erős kódolóoldali zajszűrés);
- **változó képarányú** (például IMAX-jeleneteket tartalmazó) filmek felismerése és biztonságos, veszteségmentes kezelése;
- opcionális **HDR10+ és Dolby Vision (8.1) megtartás** külső eszközökkel, a kész MKV kötelező bizonyításával;
- **beépített lejátszó** a kész MKV böngészőbarát kivonataival, és nagyítható, húzható előtte/utána **pixelnézet** a comparison képekhez;
- **statisztika**: helymegtakarítás, VMAF/SSIM/PSNR és kódolási sebesség fájlonként és összesítve, CSV exporttal;
- **profilkönyvtár**: kódolási profilok mentése, exportja és importja;
- **adatbázis-migráció előtti automatikus mentés**, ütemezett ellenőrzött mentések és parancssori visszaállítás.

A rendszer nem támogatja:

- a 3D Blu-ray megtartását;
- a Dolby Vision profil 5 és a dual-layer (FEL) enhancement réteg megtartását;
- egyszerre több teljes encode futtatását;
- GPU-s kódolást. A rendszer CPU-val dolgozik, ezért kijelző vagy videokártya nélküli szerveren is használható. GPU nem kell; ha van, csak a crop-keresés gyorsul vele (lásd 14.3).

## 2. Fontos fogalmak

### Forrásmappa

Az a mappa, ahol az érintetlen lemezek találhatók. Egy teljes lemez általában `BDMV` és `CERTIFICATE` mappát tartalmaz. A telepítő és a BDEncode ezt a forrást nem törli és nem módosítja.

### Munkamappa

Az alkalmazás saját területe. Linuxon alapértelmezetten:

```text
~/encode
```

Itt található az alkalmazás, a várólista adatbázisa, az ideiglenes fájlok, a naplók és az elkészült munkák.

### WSL2

A Windows Subsystem for Linux lehetővé teszi Linux programok futtatását Windows alatt. A Windows-telepítés során a BDEncode egy Debian WSL2 környezetben fut; a weboldalt továbbra is a Windows böngészőjéből kell megnyitni.

### Job vagy munka

Egy kiválasztott lemezhez tartozó teljes feldolgozás. Egy job tartalmazza a forrást, a playlistet, a sávválasztást, a kodekbeállításokat, a munkafájlokat és az eredményeket.

### Előkészítés és teljes feldolgozás

Az előkészítés a lemez gyorsabb beolvasása és a beállítások összeállítása. Ez egy másik encode futása közben is elvégezhető. A teljes feldolgozás a videókódolástól a comparison befejezéséig tart, és egyszerre csak egy ilyen folyamat futhat.

## 3. Telepítés Windows 10/11-re

### 3.1. Követelmények

Szükséges:

- 64 bites Windows 10 2004 vagy újabb, illetve Windows 11;
- rendszergazdai jogosultság;
- bekapcsolható hardveres virtualizáció;
- működő internetkapcsolat a telepítés alatt;
- legalább 100 GB szabad hely ajánlott a Windows rendszermeghajtón a WSL számára; teljes lemezes munkákhoz ennél lényegesen több is kellhet;
- külön elegendő hely a források és a kész fájlok számára;
- egy helyi meghajtóbetűjeles forrásmappa, például `D:\Filmek`.

> [!NOTE]
> A közvetlen `\\szerver\megosztas` UNC útvonalat a Windows-telepítő nem fogadja el. Az egykattintásos telepítéshez helyi meghajtóbetűjeles mappát használj. Hálózati forrást haladó módon, a WSL alatt kell felcsatolni és a Linux-telepítőnek átadni.

### 3.2. A projekt letöltése

#### Egyszerű módszer: ZIP

1. Nyisd meg a projekt GitHub-oldalát.
2. Kattints a **Code**, majd a **Download ZIP** lehetőségre.
3. Csomagold ki egy állandó helyre, például:

   ```text
   C:\BDEncode
   ```

4. Ne futtasd közvetlenül a ZIP-fájlból.

#### Git használatával

Ha a Git már telepítve van, nyiss PowerShellt, és futtasd:

```powershell
cd C:\
git clone --branch main https://github.com/accofil/bdencode-backend.git BDEncode
cd C:\BDEncode
```

### 3.3. A telepítő elindítása

1. Nyisd meg a kicsomagolt projekt `install` mappáját.
2. Kattints jobb gombbal a `windows-install.cmd` fájlra.
3. Válaszd a **Futtatás rendszergazdaként** lehetőséget.
4. Az UAC kérdésnél válaszd az **Igen** gombot.

Parancssorból ugyanez:

```powershell
cd C:\BDEncode
.\install\windows-install.cmd
```

A telepítő:

1. ellenőrzi vagy telepíti a WSL2-t;
2. szükség esetén bekapcsolja a virtualizációs Windows-összetevőket;
3. telepíti a Debian disztribúciót;
4. létrehozza a Linux felhasználót;
5. megkéri a forrásmappa kiválasztására;
6. telepíti a médiaprogramokat és a BDEncode-ot;
7. létrehozza a háttérben futó szolgáltatásokat;
8. létrehozza az asztali parancsikonokat;
9. megnyitja a webes felületet.

Az első telepítés a médiaprogramok fordítása miatt hosszabb ideig tarthat. Ne zárd be az ablakot csak azért, mert néhány percig nem jelenik meg új sor.

### 3.4. Ha újraindítást kér

Ez az első WSL-telepítéskor normális.

1. Nyomj Entert.
2. Indítsd újra a számítógépet.
3. Jelentkezz vissza ugyanabba a Windows-fiókba.
4. A telepítő automatikusan folytatódik.
5. Ha nem indulna el, futtasd ismét rendszergazdaként a `windows-install.cmd` fájlt. A telepítő felismeri a korábban elkezdett állapotot.

### 3.5. A forrásmappa kiválasztása

A mappaválasztóban azt a gyökérmappát add meg, amely alatt a lemezek külön almappákban találhatók. Példa:

```text
D:\Filmek\Film.Egy\BDMV
D:\Filmek\Film.Ketto\BDMV
```

Ebben az esetben a kiválasztandó gyökér:

```text
D:\Filmek
```

A Windows `D:\Filmek` útvonala WSL alatt jellemzően `/mnt/d/Filmek` formában jelenik meg. Ezt a telepítő automatikusan átalakítja.

### 3.6. Sikeres telepítés

Siker esetén a telepítő többek között ezt írja ki:

```text
BDEncode Windows/WSL installation is healthy.
Web: http://localhost:8787/encoder/
```

A kezelőfelület címe:

```text
http://localhost:8787/encoder/
```

Az asztalon két parancsikon jelenhet meg:

- **BDEncode** – megnyitja a webes kezelőfelületet;
- **BDEncode elkészült filmek** – megnyitja az elkészült fájlok Windowsból elérhető mappáját.

### 3.7. Fontos Windows útvonalak

| Tartalom | Hely |
|---|---|
| Telepítési napló | `%LOCALAPPDATA%\BDEncode\install.log` |
| WSL-életben tartó szkript | `%LOCALAPPDATA%\BDEncode\keepalive.ps1` |
| Debian WSL adatai | `%LOCALAPPDATA%\BDEncodeWSL\Debian` |
| Weboldal | `http://localhost:8787/encoder/` |
| WSL-en belüli munkaterület | `/home/<linux-felhasznalo>/encode` |
| WSL-en belüli kész munkák | `/home/<linux-felhasznalo>/encode/completed` |

## 4. Telepítés Debian szerverre

### 4.1. Követelmények

- Debian 12 `bookworm` vagy Debian 13 `trixie`;
- normál felhasználói fiók;
- a felhasználó használhassa a `sudo` parancsot;
- működő internetkapcsolat;
- nginx, ha a webes felületet reverse proxyn keresztül akarod használni;
- alapértelmezetten `~/storage` forrásmappa és `~/encode` munkamappa.

Ne `root` felhasználóként futtasd a telepítőt. A telepítő maga kér `sudo` jogosultságot azokhoz a lépésekhez, amelyekhez szükséges.

### 4.2. Csatlakozás és alapcsomagok

Jelentkezz be SSH-val, majd futtasd külön sorokban:

```bash
sudo apt-get update
sudo apt-get install -y git tmux
```

### 4.3. A projekt letöltése

```bash
cd ~
git clone --branch main https://github.com/accofil/bdencode-backend.git
cd ~/bdencode-backend
```

Ha a mappa már létezik:

```bash
cd ~/bdencode-backend
git fetch origin
git switch main
git pull --ff-only
```

### 4.4. Alapértelmezett telepítés

Az alapértelmezett útvonalak:

- forrás: `~/storage`;
- munka és adatok: `~/encode`;
- CPU-korlát: 80%;
- belső API: `127.0.0.1:8796`.

Telepítés:

```bash
cd ~/bdencode-backend
bash install/install.sh
```

### 4.5. Egyedi forrás- vagy munkamappa

Példa `/storage` forrással és a felhasználó saját `~/encode` munkamappájával:

```bash
cd ~/bdencode-backend
BDENCODE_SOURCE_ROOT=/storage \
BDENCODE_DATA_ROOT="$HOME/encode" \
BDENCODE_CPU_PERCENT=80 \
bash install/install.sh
```

Fontos:

- az útvonal legyen abszolút;
- a futtató felhasználónak olvasnia kell a forrást;
- a munkamappába írnia is kell;
- a telepítő megtagadja a nem biztonságos, túl tág vagy szimbolikus linkekkel félreérthető célokat;
- a forrás és a munkamappa ne fedje egymást.

### 4.6. Telepítés tmux alatt

SSH-kapcsolat megszakadásakor a `tmux` munkamenet tovább él:

```bash
tmux new -s bdencode-install
cd ~/bdencode-backend
bash install/install.sh
```

Leválás a futó munkamenetről: nyomd meg a `Ctrl+B`, majd a `D` billentyűt.

Visszacsatlakozás:

```bash
tmux attach -t bdencode-install
```

### 4.7. Swizzin és nginx

Swizzin telepítésnél a telepítő felismeri a szokásos nginx-struktúrát, és létrehozza az `/encoder/` útvonalhoz szükséges konfigurációt. Külső elérésnél használd a szerver HTTPS-címét, például:

```text
https://sajat-domain.example/encoder/
```

A `127.0.0.1:8796` belső API-portot nem kell közvetlenül kitenni az internetre.

**Swizzin nélküli szerver (3.5-től).** Ha a gépen nincs Swizzin (nincs `/etc/nginx/apps` vagy `/etc/htpasswd`), a telepítő egy csak a szerveren belül elérhető oldalt tesz fel: szükség esetén telepíti az nginx-et (a nyilvános alapoldalát kikapcsolja), és a `/etc/nginx/conf.d/bdencode-local.conf` fájlban a `127.0.0.1:8787` címen szolgálja ki a felületet. Kívülről nem érhető el, ezért jelszó sem kell hozzá: a saját gépedről SSH-alagúton nyitod meg:

```bash
ssh -L 8787:127.0.0.1:8787 felhasznalo@szerver
```

Amíg ez az SSH-kapcsolat nyitva van, a böngészőben a `http://localhost:8787/encoder/` cím a szerver BDEncode-oldalát mutatja. Másik port: `BDENCODE_LOCAL_WEB_PORT=9000 bash install/install.sh`; a frissítések megtartják a választott portot. Ha a port foglalt, a telepítő figyelmeztet, a kódoló ettől még települ. WSL alatt ezt a lépést a Windows-telepítő végzi (`install/wsl-install.sh`).

## 5. Képfeltöltő és release szolgáltatások beállítása

A comparison képek feltöltéséhez a rendszer az alábbi szolgáltatókat ismeri:

1. ImgBB;
2. Catbox;
3. Freeimage.

Nem kötelező mindhármat beállítani, de legalább kettő ajánlott. Ha az első szolgáltató átmenetileg hibázik, a rendszer megpróbálhatja a következőt.

### 5.1. A titkok kezelésének szabályai

- API-kulcsot ne írj a README-be, Git commitba vagy képernyőképre.
- Ne add meg nyíltan parancssori argumentumként, mert bekerülhet a shell előzményeibe.
- A BDEncode titkosított systemd credential fájlokat használ.
- A három credential neve: `imgbb-api-key`, `catbox-userhash`, `freeimage-api-key`.

### 5.2. Biztonságos, interaktív beállítás Debian alatt

Az alábbi függvény bekéri a titkot úgy, hogy a begépelt érték nem látszik. Másold be egyszer a teljes blokkot:

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

A `sudo` itt szándékos: Debian 12 alatt a gép helyi systemd credential-titkához csak root fér hozzá. A `chown` ezután visszaadja a titkosított fájlt a BDEncode felhasználójának; a telepítő kizárólag az ő tulajdonában levő, `0600` jogosultságú credentialt fogadja el.

Ezután csak azt futtasd, amelyik szolgáltatáshoz van azonosítód:

```bash
install_bdencode_secret imgbb-api-key
install_bdencode_secret catbox-userhash
install_bdencode_secret freeimage-api-key
```

Végül futtasd újra a telepítőt, hogy a szolgáltatások biztosan megkapják a credential fájlokat:

```bash
cd ~/bdencode-backend
bash install/install.sh
```

Windows alatt előbb lépj be a Debian környezetbe:

```powershell
wsl -d Debian
```

Ezután a megjelenő Linux parancssorban használd a fenti Linux-parancsokat.

### 5.2.1. Az opcionális AI-tanácsadó bekapcsolása

Az AI-tanácsadó saját API-kulccsal működik, OpenAI- vagy Claude-modellel (Anthropic). A BDEncode nem tartalmaz közös kulcsot, és a funkció kulcs nélkül is biztonságosan kikapcsolt állapotban marad. Kulcsot az [OpenAI API keys](https://platform.openai.com/api-keys) oldalon, illetve a Claude Console API Keys menüjében lehet létrehozni.

**A legegyszerűbb út: a weboldal (3.2-től).** **Rendszer → AI tanácsadó**:

1. A kívánt szolgáltató sorában írd be a kulcsot, és nyomd meg a **Kulcs mentése** gombot. A mező rejtett bevitelű; a kulcsot az oldal soha nem kapja vissza.
2. A szerver titkosított systemd credentialként menti (`openai-api-key.cred` vagy `anthropic-api-key.cred` a `~/.config/bdencode` mappában). Utána az API néhány másodpercre újraindul, és a sor állapota **Kulcs beállítva** lesz. Egy futó kódolást ez nem érint.
3. Ha mindkét kulcs megvan, az **Alapértelmezett szolgáltató** dönti el, melyiket használja a varázsló. A varázslóban munkánként is választhatsz. A **Modell** mező üresen az alapértelmezett modellt jelenti: OpenAI-nál `gpt-5.6-terra`, Claude-nál `claude-opus-5-5`. A modellt csak akkor írd át, ha ismered az elérhetőségét és a költségét.

Hogyan jut a kulcs a szerverre: az API a kulcsot egyszeri kérésként a saját, csak memóriában létező futási mappájába írja (`/run/bdencode-api`). Ezt a `bdencode-credentials.path` egység figyeli, és elindít egy root segédprogramot (`/usr/local/libexec/bdencode-credentials`). A segédprogram:

- azonnal törli a kérést;
- csak a két AI-kulcsot fogadja el;
- a kulcsot `systemd-creds encrypt`-tel, a standard bemenetén titkosítja, parancssorba sosem kerül;
- a telepítővel azonos módon köti be az API credentialjeit, majd újraindítja az API-t.

Az eredményt, kulcs nélkül, a `/var/lib/bdencode/credentials/status.json` rögzíti.

> [!IMPORTANT]
> A kulcsot ne másold GitHub issue-ba vagy chatüzenetbe. A weboldal csak a saját, jelszóval védett felületeden kérje.

**Parancssorból (régebbi telepítésnél vagy ha a weboldal nem elérhető).** Miután a teljes `install_bdencode_secret` függvényt már bemásoltad a terminálba, futtasd a szükséges sort, majd a telepítőt:

```bash
install_bdencode_secret openai-api-key
install_bdencode_secret anthropic-api-key
cd ~/bdencode-backend
bash install/install.sh
```

A telepítő mindkét titkosított credentialt a `bdencode-api.service` szolgáltatáshoz köti. Ha éppen kódolás vagy más blokkoló művelet fut, a telepítő nem szakítja meg: várd meg a munka biztonságos lezárását, majd futtasd újra.

Ellenőrzés: a weboldalon a **Rendszer → AI tanácsadó** kártya fejlécén **Használatra kész** felirat jelenik meg. Parancssorból a `doctor --json` jelentés `ai_recommendation.providers.<openai|anthropic>.credential.ready_for_consumer` mezője legyen `true`.

A Claude-hívás az `output_config` strukturált kimenetet használja (`effort: high`), és a szerveroldali tartalékmodellt (`fallbacks: "default"`), így egy elutasított kérést az Anthropic egy másik modellen automatikusan megismétel. Claude-nál egyszerre legfeljebb 16 mező lehet null típusú. Ezért a Claude csak a megváltoztatott mezőket küldi vissza, szövegként; a backend ezeket a mező típusa és tartománya szerint ellenőrzi, a hibásakat figyelmeztetéssel elveti.

Az OpenAI alapértelmezett modellje továbbra is a `/etc/bdencode/config.toml` `ai_model` beállítása. A weboldalon megadott modellnév ezt felülírja.

Adatvédelem és működés:

- a film videója, hangja, képkockái és fájlrendszerútvonala nem kerül az AI szolgáltatóhoz;
- csak egy tömör technikai scanösszefoglaló, a választott playlist adatai és az általad beírt cél kerül a kérésbe;
- a kérés `store: false` beállítást használ;
- az AI csak szigorú, előre engedélyezett mezőkben adhat javaslatot, parancssort nem készíthet;
- cropot, HDR-formátumot, kodeket, bitmélységet és más biztonsági korlátot nem írhat felül;
- a választ a helyi x264/x265 validátor újra ellenőrzi, és alkalmazás után is szükséges a **Terv ellenőrzése**.

### 5.3. Trackerprofil beállítása

3.0.1-től két release-profil beépített, ezeket nem kell beállítani:

| Profil | Képek a csomagban | Dupe check |
|---|---|---|
| `aither` (Aither) | 3–9 | nincs |
| `ncore` (nCore) | pontosan 3 | nincs |

Saját profilt, illetve dupe checket a profilfájlban állíthatsz be. A telepítő ezt üresen hozza létre, root által kezelt fájlként. Egy azonos azonosítójú (`aither` vagy `ncore`) bejegyzés a beépített profil helyére lép, például ha dupe-check címet adsz hozzá. Az aktív fájl helye:

```text
/etc/bdencode/release-profiles.json
```

Kiindulási mintának a repository [release-profiles.example.json](../config/release-profiles.example.json) fájlját használd. Másold át az aktív helyre, majd állítsd be a tracker saját adatait. A profilfájl root által olvasható konfiguráció:

- stabil `profile_id` és megjelenítési név;
- a release-csomag képszám-korlátai (`screenshot_minimum`, `screenshot_maximum`);
- opcionálisan fix, credential nélküli HTTPS dupe-check endpoint, külön host-allowlisttel.

3.0-tól a BDEncode nem készít torrentet, nem ad hozzá semmit qBittorrenthez, és nem tölt fel a trackerre. A torrent `source` token, az announce URL-ek, a darabméret-korlátok, a `publish_endpoint` és a `qbittorrent` szakasz ezért elhagyható. Egy régebbi profilfájl ezekkel együtt is betöltődik, de a rendszer nem használja őket. Ha a régi fájlban passkeyes announce URL maradt, nyugodtan töröld belőle.

API-token soha ne kerüljön a JSON-ba. A dupe-check API hitelesítési titka a 5.2. pontban bemutatott `systemd-creds` eljárással készüljön.

A tracker token credentialnevének pontosan egyeznie kell a profil `tracker.credential_name` mezőjével. A telepítő a fix `tracker-aither-api-token` nevet automatikusan átadja az API szolgáltatásnak. Egyedi trackercredentialhoz ne módosítsd a telepítő által kezelt `credential.conf` fájlt, mert frissítéskor felülíródik. Hozz létre külön, üzemeltető által kezelt drop-int:

```ini
# /etc/systemd/system/bdencode-api.service.d/tracker-local.conf
[Service]
LoadCredentialEncrypted=egyedi-tracker-token:/home/FELHASZNALO/.config/bdencode/egyedi-tracker-token.cred
```

Ezután futtasd a `sudo systemctl daemon-reload` parancsot, indítsd újra a `bdencode-api.service` szolgáltatást, majd ellenőrizd a rendszert a `bdencode doctor --json` paranccsal. A `tracker-local.conf` szándékosan nem telepítő által kezelt fájl; az üzemeltető felelőssége a karbantartása és eltávolítása.

### 5.4. Release-előkészítés biztonsági modellje

A művelet csak sikeresen befejezett, tulajdonosi rekorddal és SHA-256 hashsel kötött MKV-ból indulhat. A csomag pontosan ezt az egy payloadot írja le:

```text
Release.Name/Release.Name.mkv
```

A comparisonból csak ellenőrzött, encode-oldali képek kerülnek a csomagba. A MediaInfo, az NFO, a BBCode-leírás, a checksumok és a képek az alkalmazás privát `release-kits/<preparation-id>/` területén maradnak; nem kerülnek a publikus completed mappába. 3.0-tól a csomag nem tartalmaz torrentet és feltöltési kérést (manifest schema 2). A korábban készült csomagok érintetlenül maradnak, továbbra is ellenőrizhetők és törölhetők; a bennük lévő régi torrent az announce URL miatt titkos adat maradhat.

A dupe check közvetlenül a távoli kérés előtt újraellenőrzi a trackerprofil digestjét, valamint a completed payload tulajdonosi rekordját, útvonalát, méretét és hashét. Ha a kimenetele bizonytalan (`UNKNOWN`), a rendszer nem próbálkozik automatikusan újra: előbb a trackeren kézzel ellenőrizd. A torrentet a kész MKV-ból a tracker szabályai szerint te készíted el, és te töltöd fel.

## 6. A telepítés ellenőrzése

### 6.1. Windows

PowerShellben:

```powershell
wsl --list --verbose
Get-ScheduledTask -TaskName "BDEncode WSL"
curl.exe --noproxy "*" http://127.0.0.1:8787/encoder/
```

Elvárt eredmény:

- a `Debian` disztribúció VERSION oszlopa `2`;
- a `BDEncode WSL` ütemezett feladat létezik;
- a `curl` HTML-t kap, nem kapcsolódási hibát.

A szolgáltatások ellenőrzése:

```powershell
wsl -d Debian -- systemctl is-active bdencode-api.service
wsl -d Debian -- systemctl is-active bdencode-worker.service
wsl -d Debian -- systemctl is-active nginx.service
```

Mindháromnál az `active` válasz az ideális.

### 6.2. Debian szerver

```bash
systemctl is-active bdencode-api.service
systemctl is-active bdencode-worker.service
systemctl is-enabled bdencode-update.timer
sudo nginx -t
```

Részletes rendszerdiagnosztika:

```bash
"$HOME/encode/app/current/venv/bin/bdencode" doctor --json
```

Ha egyedi `BDENCODE_DATA_ROOT` értéket használtál, a parancsban a `$HOME/encode` részt cseréld ki arra.

A health endpoint két külön címen érhető el:

```bash
# Közvetlenül a csak helyben figyelő backend API-n:
curl --fail --silent http://127.0.0.1:8796/api/v1/health

# Swizzin/nginx mögött, HTTPS-en; a jelszót a curl külön bekéri:
curl --fail --silent --user FELHASZNALO \
    https://sajat-domain.example/encoder/api/v1/health
```

A Swizzin/nginx cím `/encoder/` előtagot és HTTP Basic hitelesítést használ. A `8796`-os belső portot ne nyisd meg az internet felé.

Windows WSL telepítésnél PowerShellből a helyi nginx ellenőrizhető:

```powershell
curl.exe --noproxy "*" http://127.0.0.1:8787/encoder/api/v1/health
```

A `runtime-capabilities` jelentésben a képfeltöltő credentialök tényleges fogyasztója a `bdencode-worker.service`. A fontos mezők:

- `configured`: az érvényes, titkosított credential fájl rendelkezésre áll;
- `service_bound`: a systemd a credentialt a worker szolgáltatáshoz köti;
- `service_active`: a worker pillanatnyilag fut-e;
- `ready_for_consumer`: a credential a megfelelő szolgáltatáshoz használatra készen be van kötve;
- `runtime_loaded`: csak a jelentést készítő folyamat saját runtime credentialjét tudja közvetlenül igazolni. A képfeltöltőknél az API válaszában ezért szabályosan `null`, nem pedig `false`; ez nem workerhiba.

### 6.3. A weboldal nem tölt be azonnal

A telepítés végén a szolgáltatásoknak néhány másodperc kellhet. Várj 10–20 másodpercet, majd frissítsd az oldalt. Ha továbbra sem működik, lásd a [hibaelhárítási fejezetet](#10-gyakori-hibák-és-javításuk).

## 7. Első kódolás lépésről lépésre

### 7.1. Új munka létrehozása

1. Nyisd meg a BDEncode weboldalát.
2. Válaszd az **Új kódolás** gombot.
3. Válaszd ki a forrásmappát.
4. Add meg a tartalomtípust: film, koncert, anime vagy sorozat.
5. Első alkalommal válaszd a **Kezdő** munkamódot.
6. Indítsd el a lemez beolvasását.

A scan még nem indítja el a hosszú videókódolást. Csak feltérképezi a lemezt és előkészíti a választási lehetőségeket.

### 7.2. Playlist és filmváltozat választása

Ha több hasonló hosszúságú playlist található, a rendszer több filmváltozatot jelezhet. Ilyenkor ellenőrizd:

- a játékidőt;
- a fejezetek számát;
- a videófelbontást és képkockasebességet;
- a hangsávok számát;
- hogy moziváltozat, rendezői változat vagy más vágás-e.

Ne csak a legnagyobb playlistet válaszd automatikusan, mert egyes lemezek hamis vagy összefűzött playlisteket tartalmazhatnak.

### 7.3. Hangsávok és feliratok

Minden megtartandó sávnál ellenőrizd:

- nyelv;
- kodek;
- csatornaszám;
- megjegyzés vagy cím;
- alapértelmezett és forced jelző.

Minden megtartott feliratot külön `full` vagy `forced` típusba is be kell sorolni. A 2.0 nem veszi át automatikusan a forrás forced jelzőjét, ha a tartalom besorolása nincs felülvizsgálva.

Ha a lemez nem tartalmaz megbízható nyelvkódot, a rendszer javaslatot adhat, de a felületen kézzel felülbírálható. Bizonytalan esetben rövid mintát kell meghallgatni vagy a feliratot meg kell nyitni.

A hangművelet lehet például:

- eredeti formátum változtatás nélküli megtartása;
- FLAC;
- DTS-HD/TrueHD mag vagy kompatibilis DTS kimenet, ha az eszközök és a kiválasztott profil engedi;
- DTS → AC3;
- más, a felületen felkínált kompatibilis átalakítás.

Az átalakítás veszteséges lehet. Ha nincs kompatibilitási vagy méretprobléma, az eredeti veszteségmentes hangsáv megtartása a legbiztonságosabb.

#### 7.3.1. Tracker-profil: Aither és nCore (3.0-tól)

A sávlépés tetején választható, melyik oldal szabályai szerint készüljön a release. A **Sávterv igazítása** gomb a szabályok szerint rendezi a sávokat. A **Mi változott** lista mindent felsorol, a **Kimeneti sávsorrend** pedig a mux sorrendjét mutatja.

| | nCore (+ magyar release-szabvány) | Aither |
|---|---|---|
| Hangnyelvek | magyar, eredeti, angol, német; más kimarad | eredeti és angol; más kimarad |
| Sorrend, alapértelmezett | magyar elöl és alapértelmezett, utána eredeti, angol, kommentár | eredeti elöl, utána angol, kommentár |
| 1080p hang | TrueHD/DTS-HD MA → E-AC3 5.1, 1024 kbps (7.1 → 5.1, mert FFmpeg-gel 7.1-es E-AC3 nem készíthető) | változatlan |
| Kompatibilitási sáv | DTS, TrueHD és DTS-HD mellé DD@640 | TrueHD mellé DD vagy DD+ |
| Felirat | forced csak szinkronnal rendelkező nyelven; sorrend: magyar forced, magyar, magyar SDH, eredeti… | angol hang nélkül angol felirat kell |

A megtartott TrueHD mellé a lemez saját AC3-magja automatikusan bekerül kompatibilitási sávnak, újrakódolás nélkül. DTS-családú sávhoz a DD@640-et egyelőre kézzel kell megoldani; a terv ellenőrzése jelzi.

A **Terv ellenőrzése** után magyar nyelvű lista mutatja, mi tér még el a szabályoktól, a rendszer viszont nem állítja meg a munkát. Az utolsó lépésben a **Név javaslata** gomb a választott stílusban állítja össze a kiadásnevet:

- Aither: `Cím.Év.2160p.UHD.BluRay.DTS-HD.MA.5.1.DV.HDR.x265-TAG`;
- magyar szabvány: `Cím.Év.2160p.UHD.BluRay.DV.HDR.TrueHD.7.1.Atmos.x265.HUN-TAG`.

A release-taget a böngésző megjegyzi. A rendszer minden névben szereplő jelölést ellenőriz a tervhez: kodeket, csatornaszámot, Atmost, DV/HDR-t, HUN-t.

Trackerprofilnál ezek automatikusak:

- **nCore x265:** level 5.1 (30 fps felett 5.2) high tierrel, HRD, AUD, ismételt fejlécek, 160 Mb/s VBV, limit-refs és lookahead-slices korlát.
- **nCore x264:** a level 4.1 szerinti legnagyobb referenciaszám.
- **Mindkét trackernél:**
  - IDR-képkocka minden fejezetkezdetnél;
  - B-túlsúlyos comparison: 24 párból 12 B;
  - tiszta képernyőképek;
  - trackerre kész BBCode (9.2.);
  - nCore-nál 2 GB fölött `Sample/<név>.sample.mkv` minta a kész mappában.

### 7.4. Videóbeállítások

- Normál BD esetén az alapértelmezett választás x264.
- UHD esetén az alapértelmezett választás x265 és HDR10.
- Alapértelmezetten a dinamikus HDR (Dolby Vision, HDR10+) nem marad meg; a HDR10 statikus réteg igen. A megtartás opcionális, lásd a 7.4.3. pontot.
- 3D tartalom nem támogatott.

Kezdő módban a rendszer biztonságos alapértékeket ad. Haladó és Profi módban több x264/x265 paraméter külön állítható. Ha nem tudod pontosan, mit jelent egy paraméter, hagyd a profil ajánlott értékén.

3.0-tól minden paraméter mellett „?” gomb nyitja meg a magyar nyelvű súgót. A súgó elmondja, mit csinál a beállítás, és mit javasolnak szemcsés, tiszta és animációs anyaghoz, Aitherhez és nCore-hoz. A teljes súgó a bal oldali menü **Súgó** pontjában kereshető. A **Minőségi opciók** között az **Aither-preset** választó hat kipróbált kiindulópontot ad: UHD x265 és 1080p x264 Quality, mindkettő szemcsés, tiszta és animációs változatban. Profi szinten az opcionális eszközök (például cutree, mbtree, rd, limit-refs) üresen a preset saját értékét hagyják.

#### 7.4.1. Automatikus CRF (VMAF-cél)

A rögzített CRF nem ad azonos minőséget minden filmnél. Az **automatikus CRF** bekapcsolásakor a worker az előkészítés végén:

1. a film törzséből egyenletesen elosztott, néhány másodperces mintákat választ (alapból 12 × 3 s; az első és utolsó 3% kimarad),
2. ezeket ugyanazzal a crop/IVTC/deinterlace gráffal és ugyanazokkal a kódolóbeállításokkal kódolja, mint a végleges kódolást,
3. a hivatalos libvmaf-fel megméri a pontszámot, és néhány próbálkozással megkeresi a célhoz tartozó legmagasabb CRF-et.

A kiválasztási JSON `video.auto_crf` objektuma:

```json
"auto_crf": {"enabled": true, "target_vmaf": 95.0, "min_crf": 12, "max_crf": 26}
```

Az opcionális mezők: `samples` (4–48), `sample_seconds` (1–10), `max_iterations` (3–10), `tolerance` (0,1–3), `metric` (`mean`, `harmonic_mean`, `percentile_1`) és `probe_preset` (gyorsabb preset a próbákhoz). Ilyenkor a megadott `crf` csak a keresés kiindulópontja.

- Minden próba önálló checkpoint: szünet, megszakítás vagy újraindítás után a kész próbák nem ismétlődnek.
- A minták csak pontozásra szolgálnak, a próbafájlok azonnal törlődnek. A `crf-search.json` jelentés (próbák, pontszámok, döntés) a manifestbe és a job artifactjai közé kerül.
- Ha a célpont a megadott CRF-tartományban nem érhető el, a job **felülvizsgálatra** kerül; a rendszer nem választ csendben gyengébb minőséget. Ilyenkor csökkentsd a célt, bővítsd a tartományt, vagy add meg fix CRF-et.
- UHD (1440 sor felett) esetén a 4K VMAF-modell, HDR10 esetén a rögzített, mindkét oldalra azonos tone-map proof átalakítás dolgozik; a HDR pontszámok ezért iránymutatók, nem abszolút mérőszámok.
- Költség: egy próba a minták teljes hosszát kódolja (alapból kb. 36 s videó), tipikusan 3–6 próbával. Lassú x265 preset mellett ez UHD-nál akár órákat is igénybe vehet; erre való a `probe_preset`.
- A pontozás csak a VMAF-ot számolja (a QC-ben használt PSNR, SSIM és MS-SSIM nélkül), a libvmaf pedig legfeljebb 8 szálon fut. A pontszám ettől nem változik: 432 képkockás 720p mintán, azonos bemenettel, egy szálon az összes jellemzővel 114 s, nyolc szálon csak VMAF-fal 2,5 s volt, mindkét esetben azonos 89,1751-es átlagpontszámmal. A próbakódolás ideje ettől független.
- A pontozás névvel ellátott csöveket (FIFO) használ. Ezeket a worker a `<data_root>/cache/vmaf` mappában hozza létre, nem a job fájában, mert a job tárhelyszámlálója a nem szabályos fájlt szándékosan elutasítja, és a tárhelykártya ilyenkor nem olvasható.
- A VMAF-cél és a QC-kapuk külön mérnek. A kész kódolásnak a mintavételezett natív-YUV PSNR/SSIM-küszöböket is teljesítenie kell (mintánként PSNR ≥ 35 dB, átlag ≥ 38 dB, SSIM ≥ 0,93, átlag ≥ 0,95), ezért túl alacsony VMAF-cél olyan CRF-et választhat, amely a comparison szakaszban felülvizsgálatot okoz. Hagyd a célt az alapértelmezett 95-ön, vagy szűkítsd a `max_crf` értékét.

**Méretcél.** A `target_size_gb` megadásával a keresés nem VMAF-ot mér, hanem a videó méretét:

```json
"auto_crf": {"enabled": true, "target_size_gb": 24, "samples": 24, "min_crf": 12, "max_crf": 26}
```

- A worker a mintákat pontosan a végleges beállításokkal kódolja, a méretüket a teljes filmre vetíti, és azt a **legkisebb CRF-et** (legjobb minőséget) választja, amelynek vetített videómérete még belefér a célba. A cél csak a videósávra vonatkozik, a hang és a felirat külön adódik hozzá.
- A keresés log-lineáris modellel dolgozik. Egy CRF-lépés egy valódi UHD-kódolásnál kb. 21%-os méretkülönbség volt; két próba után a film saját meredekségével számol. Akkor áll meg, ha a vetített méret a célon belül, attól legfeljebb 4%-ra van, vagy ha a következő 0,25-ös CRF-lépés már nem férne bele.
- A minták szóródása miatt a becslés pontossága kb. ±10%. Ezért méretcélhoz 24 minta ajánlott, ezt a felület be is állítja. UHD-n, slow presettel egy próba kb. 15 perc, és általában 3–4 próba kell.
- Ha a cél a legnagyobb megengedett CRF-fel sem érhető el, a job felülvizsgálatra kerül. Ha már a legkisebb CRF is bőven a cél alatt van (`min_crf_reached`), a rendszer jelzi, hogy alacsonyabb `min_crf` több minőséget adna.
- A kódolás alatt az állapotüzenet 10%-tól a várható videóméretet is mutatja („várható videóméret ~19.2 GB”). Ez az addig kódolt részből számolt becslés. Egy valódi filmnél 11%-nál még 15%-kal alábecsült, kb. 80%-tól már pontos volt.

#### 7.4.2. Zaj- és szemcseprofilok

Haladó és Profi módban új **`noise_reduction`** mező jelenik meg: x264-nél az `nr` (0–1000), x265-nél az `nr-intra`/`nr-inter` (0–2000) értéke. A 0 érintetlenül hagyja a forrás zaját. A `GET /api/v1/profiles/{encoder}/noise-profiles` névre szóló, szerkeszthető csomagokat ad vissza konkrét beállításértékekkel:

| Profil | Hatás |
| --- | --- |
| `off` | nincs külön zaj- vagy szemcsekezelés |
| `preserve_grain` | filmszemcsés forráshoz: grain tune, magasabb qcomp (x265-nél psy-rd/psy-rdoq is), enyhébb deblock; nagyobb fájl |
| `light_denoise` | enyhe kódolóoldali zajcsökkentés (x264 nr 40, x265 nr 100) |
| `medium_denoise` | közepes (x264 nr 120, x265 nr 250) |
| `strong_denoise` | erős (x264 nr 300, x265 nr 500); részletvesztést okozhat |

A profilok kölcsönösen kizárják egymást: egy profil mindig az ajánlott alapértékekből indul, ezért a szemcsemegtartó profil értékei nem maradnak vissza egy zajszűrő választása után.

A zajszűrés szándékosan a **kódolóban** történik, nem előszűrőként. Így a referencia érintetlen marad, és az SSIM/PSNR/VMAF-kapuk továbbra is a kodek hűségét mérik, nem egy előszűrő hatását. Erős zajszűrésnél a QC-kapuk jelezhetik az eltérést; ez szándékos védelem az észrevétlen túlszűrés ellen.

**Zajszűrés és automatikus CRF együtt.** A VMAF a referenciában lévő szemcsét részletnek méri, a zajszűrés pedig éppen ezt veszi el, ezért ugyanazon a CRF-en alacsonyabb pontszámot ad. Valódi eszközös mérésben (720p, mesterséges, zajos HDR10 tartalom, hat 3 s-os mintaablak, `veryfast` próba) a pontszám CRF 18-on zajszűrés nélkül 93,23, `nr-intra`/`nr-inter` 100 mellett 93,03, 500 mellett 92,90 volt; CRF 12-n 93,54, 93,49 és 93,39. A különbség ezen a tartalmon kicsi; erősen szemcsés valódi forrásnál nagyobb is lehet, ilyet nem mértünk. Ha a pontszám a CRF csökkentésével sem javul érdemben (ezen a mintán zajszűrés nélkül sem: CRF 18 és 12 között 0,3 pont), a keresés nem próbálkozik tovább: megméri az alsó határt is, és a 95-ös célnál ezen a mintán három próba után felülvizsgálatra küldi a jobot (`crf_target_unreachable`), nem választ csendben rosszabb minőséget. Ilyenkor csökkentsd a VMAF-célt, vagy adj meg fix CRF-et.

#### 7.4.3. HDR10+ és Dolby Vision megtartása

Az alapértelmezés (`discard`) változatlan: csak a statikus HDR10 marad meg, és a kész MKV-ban dinamikus metaadat hard hiba. Megtartás a `video.dynamic_hdr` mezővel kérhető:

| Érték | Jelentés |
| --- | --- |
| `discard` | alapértelmezett: dinamikus réteg eldobása |
| `hdr10plus` | a forrás HDR10+ metaadatát képkockánként megtartja |
| `dolby_vision` | a Dolby Vision RPU-t profil 8.1-ként tartja meg (a 7-es profil `dovi_tool -m 2`-vel alakul át; egyrétegű 8-as profilnál az RPU az alapréteg folyamában van, a kétrétegű 7-es profilú lemezeknél a másodlagos 1080p-s HEVC-folyamban, ezt a scan felismeri, lásd lent; az enhancement réteg a 8.1-ben elmarad, MEL-nél ez lényegében veszteség nélküli) |
| `auto` | ami a forrásban van és biztonságosan megtartható (előbb HDR10+, aztán Dolby Vision); különben csendben `discard`, indoklással |

Feltételek (a `selection/validate` végpont korán jelzi őket): x265 HDR10 (Main 10) kimenet; **progresszív** időzítés (a metaadat forráskockánkénti, IVTC/deinterlace után nem vihető át); a forrásnak ténylegesen hordoznia kell a metaadatot; Dolby Visionnél megerősített HDR10 alapréteg és 7-es vagy 8-as profil.

Eszközigény: `hdr10plus_tool` (HDR10+) és `dovi_tool` (Dolby Vision). **Mindkettőt a telepítő teszi fel** (2.4.0-tól a `dovi_tool`, 2.5.0-tól a `hdr10plus_tool` is) a hivatalos `quietvoid/*` rögzített kiadásaiból (`dovi_tool` 2.3.4, `hdr10plus_tool` 1.7.2), SHA-256 ellenőrzéssel az eszközkiadásba (`tools/current/bin`); ha a letöltés nem sikerül (nincs hálózat, nem x86_64 a gép, eltér az ellenőrzőösszeg), a telepítés ettől nem hiúsul meg, csak a megtartás marad elérhetetlen, és a `bdencode doctor` jelzi. Egyedi x265 nem kell: a metaadatot a worker a kész kódolásba utólag szúrja be (lásd lent), a Debian x265 HDR10+ támogatás nélkül is megfelel. A `bdencode doctor` kimenetének `dynamic_hdr` szakasza mutatja, mi érhető el; hiányzó eszköz nem befolyásolja a `status` értékét.

A biztonsági modell:

1. A worker a referencia HEVC-folyamát kinyeri, és az eszközzel metaadatot készít. Dolby Visionnél a `dovi_tool info --summary` megerősíti a 8-as profilt, cropolt kimenetnél a `-c` kapcsoló nullázza az active area értékeket.
2. A metaadat **képkockaszáma pontosan egyezik** a kódolt idővonaléval, különben a job felülvizsgálatra kerül.
3. Az FFmpeg libx265 burkolója ismeretlen paraméternél csak figyelmeztet, és megtartás nélkül kódol (a Debian x265 nem tud HDR10+-t, az RPU-fájlt pedig csak az x265 parancssori program olvassa); ezért a kész MKV-ból a QC **bizonyítja** a réteg meglétét (HDR10+: `SMPTE2094-40` side data; Dolby Vision: `DOVI configuration record`, profil 8, HDR10-kompatibilis, RPU jelen). Bármi hiányzik, a job felülvizsgálatra kerül, és nem készül félrecímkézett kiadás.
4. Dolby Visionnél, ha nem adtál meg VBV-t, a rendszer 160000/160000 kb/s VBV-t alkalmaz.
5. A megtartott metaadatot a worker a kódolás **után** szúrja be a kész HEVC-folyamba (Dolby Vision: `dovi_tool inject-rpu`, 2.4.0-tól; HDR10+: `hdr10plus_tool inject`, 2.5.0-tól), és az MKV sávot az eredeti időbélyegekkel, képkockaidővel és színleírással újraépíti (`mkvextract`, `mkvmerge`, `mkvpropedit`). Az újraépített sávból visszaolvassa a metaadatot, és csak akkor fogadja el, ha a képkockák száma pontosan egyezik a referencia idővonalával (és Dolby Visionnél a profil 8). Erre azért van szükség, mert az FFmpeg libx265-e nem tudja beolvasni az RPU-fájlt (az `--dolby-vision-rpu` az x265 parancssori programé), a Debian x265 pedig nincs HDR10+ támogatással fordítva. Az x265 `dhdr10-opt` blokkszintű optimalizálása HDR10+-nál így nem érvényesül; ez csekély minőségi finomítás.
6. **Kétrétegű (7-es profilú) Dolby Vision UHD-lemez** (2.6.0-tól): az ilyen lemezen az RPU nem az alapréteg 4K-s folyamában van, hanem egy másodlagos, 1080p-s HEVC-folyamban (kiegészítő réteg). Sem az FFmpeg, sem a libbluray nem jelzi Dolby Visionnek, ezért a scan megvizsgálja a fő lejátszási listák másodlagos HEVC-folyamait: lemásolja az első 120 képkockát, és a `dovi_tool` kiolvassa belőlük az RPU-t. Ha 7-es profilú, az alapréteget Dolby Visionnek jelöli (`dolby_vision_profile: 7`, a kiegészítő réteg azonosítójával és típusával: MEL vagy FEL), és a kinyerés ebből a rétegből dolgozik (`dovi_tool -m 2 extract-rpu`, vágásnál `-c`). FEL-nél a terv jelzi, hogy a teljes kiegészítő réteg a 8.1-es profilban nem fér el, és elmarad. A felismerés csak a scan idején fut; a korábban beolvasott lemezeket újra kell olvastatni.

> [!WARNING]
> A HDR10+ út a bitfolyamba (SEI) írja a metaadatot, ezért a mux nem érinti, de a Debian x265 nem tud HDR10+-t. A Dolby Vision megtartás szintetikus, generált 8.1-es forráson valódi eszközökkel végig lett próbálva (1440 RPU a forrásban, 1440 a kimeneten, 8-as profil), **valódi Dolby Vision lemezen még nem**: a 7-es profil átalakítása (`dovi_tool -m 2`), a minimális fényesség és a jelenethatárok valódi tartalomnál eltérhetnek. Első használat előtt próbáld ki egy rövid, valódi Dolby Vision lemezrészen; ha a konfigurációs rekord vagy az RPU-k száma nem egyezik, a QC kapu nem engedi tovább a jobot.

#### 7.4.4. Változó képarány (IMAX-jelenetek)

A worker a film crop-vizsgálatából **képarányprofilt** is készít (`crop-policy.json` › `aspect_profile`). Ha a kép a film elején mért képarányról később nagyobb vászonra bővül (tipikusan IMAX- vagy teljes képes jelenetek egy scope filmben), a job eseménynaplójába `worker.variable-aspect` bejegyzés kerül az első bővülés időpontjával.

Az ilyen film korábban gyakran felesleges kézi crop-felülvizsgálatot igényelt, mert nincs egyetlen domináns fekete sáv. Mostantól, ha a napló néhány (legfeljebb három) lépcsős, szigorúan csak növekvő burkológörbét mutat, és a legszélesebb vászon legalább 10 másodpercig látszik, az automatikus crop a **legszélesebb vásznat** tartja meg. Ez konstrukció szerint nem vág le képet; legrosszabb esetben néhány kódolt fekete sáv marad a szűkebb jelenetekben. Zajos vagy sok lépcsős napló továbbra is felülvizsgálatot kér, kézi cropnál a meglévő `variable_aspect_ratio` védelem érvényes.

#### 7.4.5. Profilkönyvtár

A videóbeállítások között a **Profilkönyvtár** kártya a beállítások újrahasznosítására és megosztására való.

- **Alkalmaz**: a profil beállításai, az automatikus CRF és a dinamikus HDR választása bekerül a szerkeszthető mezőkbe. Ez nem jóváhagyás: a Terv ellenőrzése lépés továbbra is kötelező.
- **Mentés**: az aktuális beállításokból profil készül. Csak *hordozható* mezők kerülnek bele; a lemezhez vagy a bitfolyam-szabályokhoz kötött értékek (`encoder`, `profile`, `level`, `bit_depth`, `pixel_format`, `color`, `vbv`, `hdr10`, `aud`, `repeat_headers`, `annexb`) nem, mert egy másik lemezen hibás vagy veszélyes eredményt adnának.
- **Export / Import**: egy profil `bdencode-profile`, a teljes könyvtár `bdencode-profile-bundle` JSON-ként tölthető le. Importnál minden bejegyzést valódi `EncoderSettings` felépítésével ellenőriz a backend, ezért egy megosztott fájl nem csempészhet be nem támogatott vagy nem hordozható paramétert. A fájlban lévő azonosító és időbélyeg figyelmen kívül marad; az azonosító a névből származik. Név ütközésekor választható az átnevezés (alapértelmezett), a kihagyás és a felülírás.

A profilok a `<data_root>/state/profile-library` mappában, profilonként egy JSON fájlban vannak (legfeljebb 200), ezért a `state` mappa mentésekor együtt mentődnek.

#### AI-javaslat kérése

Ha az 5.2.1. pont szerint beállítottad az API-kulcsot, a videóbeállításoknál megjelenik az **AI beállítási tanácsadó** csempe. Használata:

1. Válaszd ki a helyes playlistet, mert az ajánló ennek a scanadatait elemzi.
2. Válaszd ki a részletességet: Kezdő, Haladó vagy Profi.
3. Add meg a minőségi célt: **maximális minőség**, **kiegyensúlyozott** vagy **kompakt fájl**.
4. Opcionálisan adj meg célméretet GiB-ban. Ez tájékoztató cél: a CRF-alapú encode pontos fájlméretet nem tud garantálni.
5. Opcionálisan add meg a műfajt, például `szemcsés 35 mm-es dráma`, `anime`, `koncert` vagy `gyors akciófilm`.
6. A szabad szöveges mezőben leírhatod a prioritásokat, például: `A filmszemcsét őrizze meg, a fájl inkább lehet nagyobb.`
7. Nyomd meg az **AI-javaslat kérése** gombot.
8. Olvasd el az indoklást és a figyelmeztetéseket. Az AI válasza még nem változtatja meg a tervet.
9. Ha megfelelő, nyomd meg a **Javaslat alkalmazása a mezőkre** gombot. Ez csak a szerkeszthető mezőket tölti ki; ezután kézzel is módosíthatod őket.
10. Végül mindig nyomd meg a **Terv ellenőrzése** gombot. Kódolás csak a backend sikeres validálása és a kezelő jóváhagyása után indulhat.

Az AI nem helyettesíti a scan- és plannerellenőrzést. Ha a szolgáltató nem érhető el, a már meglévő determinisztikus szakértői profil használható tovább; emiatt nem kell megszakítani vagy törölni a jobot.

### 7.5. Terv ellenőrzése és sorba állítása

1. Nézd át a kiválasztott playlistet és sávokat.
2. Add meg a kimeneti fájlnevet.
3. Kattints a **Terv ellenőrzése** gombra.
4. Javítsd a pirossal jelzett kötelező hibákat.
5. Ha csak figyelmeztetés maradt, olvasd el, és szükség esetén erősítsd meg.
6. Hagyd jóvá a tervet.

A jóváhagyott munka **Indításra kész** állapotba kerül. Ha másik encode fut, nem indul el azonnal: szabályosan várakozik a sorban. Közben további lemezeket is beolvashatsz és beállíthatsz.

A képfeltöltésnél a **Feltöltött képek** mező dönti el, mely comparison képek kerülnek fel (2.10-től):

- minden kép;
- csak az SDR-nézet;
- csak a natív kép.

HDR-filmnél minden képpárnak natív és SDR-re leképezett nézete is van, ezért az egyik elhagyása felezi a feltöltést. A helyi PNG-k mind megmaradnak. Az első kép után a feltöltés tárhelyenként párhuzamosan, egyszerre három képpel halad.

### 7.6. A kész munka ellenőrzése

Az **Elkészült munkák** között ellenőrizd:

- az MKV meglétét és méretét;
- a MediaInfo és MKV-elemzés mellékletet;
- a videó QC eredményeit;
- a hang spektrumképeit;
- az alapértelmezett 24 comparison képpárt;
- a BBCode fájlt;
- a fő és szakaszonkénti naplókat.

Végül játssz le több részletet a filmből, különösen az elejét, a végét, egy fejezetváltást és több hangsávot/feliratot.

## 8. A várólista és az állapotok

A rendszer kétféle erőforrássávot kezel:

- egy scan/előkészítő sáv, amely a futó encode mellett is használható;
- egy teljes feldolgozási sáv, amelyből egyszerre pontosan egy futhat.

Ezért a helyes munkamenet:

1. az első job kódol;
2. közben a következő lemezt beolvasod;
3. kiválasztod a playlistet, sávokat és paramétereket;
4. jóváhagyod;
5. a job **Indításra kész** állapotban vár;
6. az előző teljes lezárása után automatikusan sorra kerül.

### Állapotok jelentése

| Állapot | Jelentés | Felhasználói teendő |
|---|---|---|
| `QUEUED` | Beolvasásra vár | Nincs |
| `SCANNING` | A lemez feltérképezése folyik | Várj |
| `AWAITING_SELECTION` | Választás vagy beállítás szükséges | Nyisd meg és állítsd be |
| `READY` | Minden jóváhagyva, teljes feldolgozásra vár | Nincs |
| `ENCODING` | Videókódolás folyik | Várj |
| `MUXING` | Az MKV összeállítása folyik | Várj |
| `QC` | Minőség-ellenőrzés folyik | Várj |
| `COMPARISON` | Kép- és hangelemzés készül | Várj; a hard időkeret 30 perc |
| `UPLOADING` | Comparison képek feltöltése folyik | Várj |
| `NEEDS_REVIEW` | Emberi döntés szükséges | Nyelvi vagy feltöltési kérdésnél a munka oldalán megjelenő kártyán dönts; egyébként olvasd el a jelzést és folytasd |
| `UPLOAD_FAILED` | A képfeltöltés hibázott | A munka oldalán: újrapróbálás, újrakezdés más tárhellyel vagy képkészlettel, vagy befejezés képek nélkül |
| `COMPLETED` | A munka teljesen elkészült | Ellenőrizd az eredményt |
| `FAILED` | Egy szakasz hibával leállt | Javítás után **Folytatás a hibától** |
| `CANCELLED` | A munkát megszakították | **Újraindítás** vagy **Munka törlése** |

### Az aktuális lépés és a lépések időtartama

A munka oldalán a teljes folyamat sávja alatt a **Most fut** panel az éppen futó részfolyamatot mutatja. Ilyen részfolyamat a helyi másolat, a remux, a crop-keresés, a nyelvellenőrzés, a CRF-keresés, a kódolás, a mux, a QC, az összehasonlítás és a feltöltés. A panelen látszik:

- a lépés saját százaléka, az eltelt és a hátralévő idő;
- ha az arány nem mérhető, mozgó sáv;
- a párhuzamosan futó feladatok külön sávval (forrásindex, forrás-integritás ellenőrzése);
- kódolás közben a sebesség, a már kiírt méret és a várható videóméret. Méretcélnál a céllal együtt, „célon belül” vagy „+N% a cél felett” jelzéssel.

A panel kétmásodpercenként frissül, értesítést nem küld. Az **Áttekintés** lapon a **Lépések időtartama** kártya minden befejezett lépést a kezdési idejével és időtartamával sorol fel. A kezdőlap aktív munka kártyája a futó lépést egy sorban mutatja.

### Felülvizsgálat megoldása a felületen

- **Nyelv:** ha a lemez nyelvjelölése és a hangfelismerés eltér, vagy egy felirat nyelve nem olvasható ki, a kártya minden megtartott hang- és feliratsávnál mutatja a lemez szerinti és a felismert nyelvet (biztonsággal), és felkínálja a valószínűt. A **Nyelvek megerősítése és folytatás** a nyelveket a beállításba írja; a munka visszakerül a sorba, a kész előkészítő lépések újrahasznosulnak.
- **Képfeltöltés:** a kártya mutatja a rögzített tárhelyet, a már feltöltött képek számát, a legnagyobb képet és tárhelyenként, hogy elfér-e. Lehetőségek:
  - **Újrapróbálás ugyanoda** átmeneti hibánál;
  - **Újrakezdés más beállítással** másik tárhellyel vagy képkészlettel. A régi checkpoint a privát `logs/upload-resets` mappába kerül, a régi képek a régi tárhelyen maradnak;
  - **Befejezés képek nélkül.**

  Videót egyik sem kódol újra.

### Megszakítás, folytatás és törlés

- A pipeline `state` mezője mellett külön `control_state` mutatja a kezelői vezérlést: `RUNNING`, `PAUSE_REQUESTED`, `PAUSED` vagy `CANCEL_REQUESTED`.
- A **Szüneteltetés** először tartós `PAUSE_REQUESTED` kérést ír az adatbázisba. A worker leállítja az adott szakasz folyamatait, biztonságosan eltávolítja a részleges kimenetet, és csak ezután igazolja vissza a `PAUSED` állapotot. Emiatt a gomb hatása nem feltétlenül azonnali, és a félbehagyott lépés folytatáskor újrafuthat.
- Csak a visszaigazolt `PAUSED` job engedi el a scan- vagy encode-sávját. Másik job ekkor sorra kerülhet; ezért a **Folytatás** `409` ütközést adhat, amíg a szükséges sáv foglalt.
- A **Folytatás** a meglévő pipeline-állapotot és az érvényes checkpointokat tartja meg. Ez nem azonos a `NEEDS_REVIEW` állapot jóváhagyásával vagy a `FAILED` job újrapróbálásával.
- A **Megszakítás** aktív folyamatnál `CANCEL_REQUESTED`, majd worker-visszaigazolás után `CANCELLED`. Már tétlen vagy szünetelő jobnál a lezárás azonnal, egy tranzakcióban megtörténhet.
- A **Folytatás a hibától** a meglevő érvényes checkpointokat használja; az **Újraindítás** a `CANCELLED` munkát teszi vissza a feldolgozásba.
- Egy már beállított, megszakított munkánál az **Újraindítás** ablak két utat kínál (3.4-től):
  - **Újraindítás ugyanígy:** a jóváhagyott beállításokkal vissza a várólistára.
  - **Beállítások módosítása:** a beállítóvarázsló a korábbi beállításokkal kitöltve nyílik meg, és a kódolás csak az új beállítások jóváhagyása után indul.

  Mindkét esetben megmarad minden checkpoint, amelyet a változás nem érint: azonos forrásnál és playlistnél a referencia-remux, a crop és a forrás-ellenőrzés. Ami a megváltozott beállításoktól függ (például a kódolás egy új CRF-fel), az újrafut.
- A `control_revision` és a job `version` optimista zárolása megakadályozza, hogy két megnyitott böngészőablak elavult gombnyomása felülírja egymást.

### Tárhely-előnézet, takarítás és törlés

A job tárhelynézete külön mutatja a privát munkaterületet és a publikus completed release-t. A **Takarítás** csak `COMPLETED` jobon, `temporary` scope-pal használható: a nagy ideiglenes `work` tartalmat karanténon keresztül törli, de az elkészült MKV-t és a publikus comparison bizonyítékokat megőrzi. A leválasztás szándéka és pontos célpontjai előbb SQLite maintenance journalba kerülnek; a fájlrendszer-mozgatás és a domain-adatbázis commit közötti processzhalál után az induláskori recovery determinisztikusan visszaállítja a nem commitolt, illetve végleg eltávolítja a commitolt karantént.

A **Munka törlése** csak terminális (`COMPLETED`, `FAILED` vagy `CANCELLED`) jobnál engedélyezett. Eltávolítja a job adatbázis-bejegyzését, privát munkaterületét és olyan release-előkészítési kitjeit, amelyekhez nem tartozik külső kimenetel, de a completed release-t mindig megőrzi. Az `UNKNOWN` állapotú, valamint a 3.0 előtti `PUBLISHED`, sikeres/bizonytalan qBittorrent- vagy publication-receipttel rendelkező auditrekord nem törölhető egyszerű preparation- vagy jobtörléssel.

A publikus release törlése külön, erős megerősítést kérő művelet: a release nevének és az MKV SHA-256 hashének egyeznie kell, továbbá a kliensnek az összes preparation azonosítóját és aktuális verzióját tartalmazó pontos snapshotot is vissza kell küldenie. A backend ugyanabban az adatbázis-tranzakcióban újraellenőrzi ezt a halmazt, mielőtt a release-t és a kapcsolódó auditrekordokat leválasztja. `UNKNOWN` kimenetelnél, illetve 3.0 előtti seedelt vagy publikált rekordnál külön force jóváhagyás szükséges.

> [!WARNING]
> A job és a release törlése nem visszavonható. Egyik sem módosítja az eredeti Blu-ray forrást; a completed release-t kizárólag a külön **Release törlése** művelet távolíthatja el.

### Release-csomag készítése

`COMPLETED` jobon a **Release előkészítése** panelen válassz trackerprofilt, töltsd ki a release metaadatait, majd haladj az alábbi ellenőrzött lépéseken. Ha a munka Aither vagy nCore tracker-profillal készült, a panel ezt a profilt választja ki előre:

1. **Validate** – újraellenőrzi az MKV tulajdonosi rekordját, útvonalát, méretét, hashét, a profil digestjét és a comparison képeket.
2. **Build** – elkészíti a hash-manifesttel rögzített release-csomagot: NFO, BBCode-leírás, MediaInfo, ellenőrzött képek és checksumok. Trackerprofilos munkánál a csomag a tiszta, jelölés nélküli képernyőképeket használja, ha a profil képszámához elég van belőlük; különben a comparison encode-oldali képeit.
3. **Dupe check** – a konfigurált tracker fix endpointján ellenőriz; `CLEAR` eredménynél az állapot „Dupe check: tiszta”.

3.0-tól a BDEncode nem készít torrentet, nem ad hozzá semmit qBittorrenthez, és nem tölt fel a trackerre: a torrentet a kész MKV-ból a tracker szabályai szerint te készíted el, és te töltöd fel.

A release-előkészítés saját tartós állapotgépet és verziót használ; böngészőfrissítés nem veszíti el a receipt-eket. Szolgáltatásindításkor a félbemaradt `PREPARING` művelet `FAILED` lesz és az árva build-staging kitakarítható, míg a félbemaradt dupe check (`SEEDING_CHECK`), illetve egy 3.0 előtti `SEEDING` vagy `PUBLISHING` művelet `UNKNOWN` állapotba kerül. A dupe checket a rendszer nem ismétli meg automatikusan. `NEEDS_REVIEW`, `FAILED` vagy különösen `UNKNOWN` esetén ne ismételd vakon: előbb ellenőrizd a tracker valós állapotát.

## 9. Naplók, elemzések és comparison

### 9.1. Mi marad meg?

A nagy ideiglenes `work` tartalom sikeres véglegesítés után eltávolítható; ha megmaradt, a tárhelynézetből célzottan takarítható. A publikus `completed/<release>/` csomagban megmaradnak:

- az elkészült MKV;
- a comparison PNG-k, metrikák és BBCode;
- az audió comparison és spektrumképek;
- a kimeneti nevet és MKV-hasht tartalmazó, jobazonosító nélküli tulajdonosi rekord.

A teljes munkanapló, a szakaszonkénti naplók, az alkalmazott x264/x265 és mux beállítások, a MediaInfo/MKV elemzés, a manifest és a részletes QC eredmények a privát job-munkatérben és az alkalmazás artifact-tárában maradnak. Nem kerülnek az MKV-ba vagy a publikus release-mappába.

Hibánál a szükséges munkafájlok szándékosan megmaradnak, hogy a job folytatható legyen. Ha nem akarod folytatni, előbb szakítsd meg vagy zárd le a jobot, majd használd a webes **Munka törlése** műveletet. Ez a completed release-t nem törli.

### 9.2. Videó comparison

A mintavételezett comparison célja nem a teljes film képkockánkénti átvizsgálása. A rendszer:

- alapértelmezetten 24, de konfigurálhatóan 20–50 képpárt készít;
- a címen elosztva azonos időponthoz és azonos frame-típushoz tartozó source/encode képet párosít;
- az alapértéknél 8 I-, 8 P- és 8 B-frame-et választ;
- veszteségmentes PNG-t használ;
- ráírja a forrást, a képkockaszámot és a frame-típust;
- a QC SSIM/PSNR értékeit külön, natív YUV síkokon számolja, ezért az annotáció és az RGB-konverzió nem módosítja a mérését;
- 30 perces teljes hard időkeretet használ (UHD-n arányosan többet), nem végez órákig tartó teljesfilm-metrikát;
- a kész fájlra **mintavett VMAF-ot** is mér (2.9-től). Ez 12 × 2 másodperc a film egészén elosztva, UHD-n a 4K-modellel, HDR-nél a CRF-keresés proof-átalakításával. Mindkét oldalt VapourSynth olvassa, a kész MKV-t L-SMASH-sel, így nem kell a teljes fájlt dekódolni. Az eredmény (átlag, harmonikus átlag, 1%-os alsó érték, ablakonként is) a `comparison/video-vmaf.json`-ba kerül. Tájékoztató érték, nem kapu: ha a mérés nem sikerül, „unavailable” állapottal rögzül, és nem állítja meg a jobot;
- a Comparison lapon a mintavett VMAF ablakait a leggyengébbtől sorolja időkóddal (2.10-től). A három leggyengébb kiemelést kap, a hozzájuk 60 másodpercen belül eső képpárok jelzést kapnak, így a gyenge részt célzottan meg lehet nézni a lejátszóban;
- a publikált PNG-ket soronként választott szűrővel tömöríti (`-pred mixed`), ami veszteségmentes és 8–15%-kal kisebb fájlt ad;
- a független lépéseket (hang-QC, a kész fájl ellenőrzései, a képtípus-vizsgálatok) egyszerre legfeljebb négyesével futtatja.

Trackerprofilos munkánál (3.0-tól) a 24 párból 12 B-típusú, és néhány B-párból tiszta, jelölés nélküli képernyőkép is készül. A `comparison.bbcode` végére trackerre kész szakasz kerül:

- **Aither:** `[comparison=Source, Encode]` blokk szóközzel elválasztott PNG-URL-ekkel, csupa B-párból (az Aither útmutatója szerint B-képkocka ajánlott, legalább 10 pár), 6 képernyőkép `[center]` és `[img=350]` formában, valamint az x264/x265-napló összesítője spoilerben.
- **nCore:** pontosan 3 `[imgw]` kép az encode felbontásában, és cseréhez használható „Forrás vs. Encode” linkek.

Ha az azonos típusú pár technikailag nem állítható elő, a felület ezt egyértelműen jelzi. A strict I/P/B egyezés nem cserélhető le észrevétlenül más képtípusra. A blokkoló küszöböket a [2.0 kiadási jegyzet](RELEASE_2_0.md#videó-és-comparison) sorolja fel.

### 9.3. Hang-összehasonlítás

A rendszer külön kezeli a forrás- és kimeneti hangot. A mellékletek között spektrális képek és technikai adatok találhatók. Veszteséges konverziónál a spektrum különösen hasznos, de önmagában nem bizonyítja a hallható minőséget; szükség esetén hallgatási próba is kell.

### 9.4. VMAF figyelmeztetés

Ha a diagnosztika ezt jelzi:

```text
FFmpeg libvmaf filter missing; the official standalone VMAF CLI will be used
```

az nem telepítési hiba. Az FFmpegből hiányzik a `libvmaf` szűrő, ezért a rendszer a telepített hivatalos önálló VMAF parancssori programot használja.

### 9.5. Beépített lejátszó és pixelnézet

**Pixelnézet.** A comparison képpárok kártyáján a *Nagyítás és pixelnézet* gomb nagy ablakot nyit. A source és az encode **ugyanabban a görgethető konténerben** fekszik, ezért nagyításkor és mozgatáskor sosem csúszhat el egymáshoz képest; az elválasztó a kép koordinátáiban mozog. Nagyítás: Illesztés, 100% és 200% (200%-nál pixelesen, simítás nélkül); a nagyított kép húzással mozgatható. Billentyűk: `Z` – nagyítás váltása, `[` és `]` – előző/következő képpár, `Esc` – bezárás. A korábbi kártyán belüli csúszka, A/B, villogtató és diff mód megmaradt.

**Lejátszó.** Elkészült munkánál a *Lejátszó* fül a kész MKV-ból készít néhány másodperces kivonatot. A böngészők a legtöbb kiadási MKV-t nem tudják lejátszani (HEVC, DTS, FLAC, HDR), ezért a backend kérésre H.264/AAC MP4-be kódolja a kijelölt részt (10/20/30 másodperc, 360p/480p/720p); HDR forrásnál SDR-re tone-map-elve. A kezdőpont csúszkával, percenkénti léptetéssel vagy a fejezetlistából választható. A kivonat:

- csak nézési segéd: **nem része** a kiadásnak, a completed mappának és a release-csomagnak;
- a `<data_root>/cache/previews/<job>` mappába kerül, jobonként legfeljebb 12 darab és összesen 2 GiB, a legrégebbi törlődik;
- egyszerre egy készül (`ffmpeg`, timeout 240 s); ugyanaz a kérés a gyorsítótárból szolgálódik ki;
- HTTP range-kéréssel tölt, ezért a tekerés működik.

Az `ffmpeg`/`ffprobe` hiánya esetén a fül érthető üzenettel jelzi, hogy a lejátszó nem érhető el.

### 9.6. Statisztika

A **Statisztika** oldal az elkészült munkákat összesíti: megtakarított hely (GiB és %), átlagos VMAF/SSIM/PSNR, átlagos CRF és bitráta, kódolási sebesség (fps és valós idejű többszörös) és a kódolással töltött órák. Fájlonként rendezhető táblázat és CSV-letöltés (UTF-8 BOM-mal, hogy a táblázatkezelők helyesen olvassák az ékezeteket) tartozik hozzá; a munka oldalán az áttekintés jobb oldalán ugyanez egy kártyán látszik.

Az adatok tartós bizonyítékból származnak: manifest, `comparison/video-metrics.json`, `analysis/crf-search.json`, a worker által a befejezéskor rögzített `analysis/source-size.json` (a kiválasztott playlist klipjeinek összmérete) és az eseménynapló. A kódolási idő az `ENCODING` szakaszban töltött falióra-idő, a szüneteltetett időt levonva; több próbálkozásnál minden szakasz beleszámít. Hiányzó bizonyíték (például régebbi kiadással készült munka) esetén a mező **üres marad („—”)**, a rendszer nem becsül. A VMAF csak az automatikus CRF mintakódolásaira vonatkozik, nem a teljes filmre; ezt az oldal is kiírja.

## 10. Gyakori hibák és javításuk

### 10.1. Hol keresd először a hibát?

Windows telepítési napló:

```text
%LOCALAPPDATA%\BDEncode\install.log
```

Gyors megnyitása PowerShellből:

```powershell
notepad "$env:LOCALAPPDATA\BDEncode\install.log"
```

Debian szolgáltatásnaplók:

```bash
journalctl -u bdencode-api.service -n 200 --no-pager
journalctl -u bdencode-worker.service -n 200 --no-pager
journalctl -u nginx.service -n 100 --no-pager
```

Élő worker-napló:

```bash
journalctl -u bdencode-worker.service -f
```

Kilépés az élő nézetből: `Ctrl+C`.

### 10.2. Hibatáblázat

| Jelenség vagy üzenet | Mit jelent? | Javítás |
|---|---|---|
| A telepítőablak rögtön bezáródik | Régi telepítő vagy korai PowerShell-hiba | Töltsd le a legfrissebb `main` ágat, csomagold ki teljesen, majd futtasd a `windows-install.cmd` fájlt rendszergazdaként. Az új telepítő hiba esetén Enterre vár. |
| „A Linuxos Windows-alrendszer nincs telepítve” | A WSL még nincs engedélyezve | Hagyd, hogy a telepítő bekapcsolja, majd indítsd újra a gépet és futtasd újra. |
| `WSL_E_VM_MODE_INVALID_STATE` | A Debian már létrejött, de a WSL2 konverzió még nem fejeződött be | Indítsd újra a Windowst, majd a friss telepítőt. A jelenlegi telepítő helyreállítja a félkész állapotot. |
| `invalid option name: pipefail` | Windows CRLF sorvég került a Bash szkriptbe | Régi telepítőhiba; frissítsd a repót és futtasd újra. A jelenlegi telepítő normalizálja a sorvégeket. |
| `sudo: python3: command not found` | A minimális Debianban még nincs Python | Régi telepítőhiba; a jelenlegi telepítő előbb telepíti a Python 3-at. Frissíts és futtasd újra. |
| `Command 'man apt(8)' failed with code 1` | A systemd unit ellenőrzése a hiányzó `man` programon bukott el | Régi telepítőhiba; frissíts és futtasd újra. A jelenlegi bootstrap telepíti a szükséges csomagot. |
| A telepítés sikeres, de a `localhost:8787` nem jön be | A WSL vagy nginx még nem fut, az ütemezett feladat hiányzik, vagy proxy zavar be | Várj 20 másodpercet, futtasd a 10.3. fejezet parancsait, majd ellenőrizd a szolgáltatásokat. |
| Régebbi telepítőn átmeneti `curl: (7) Failed to connect` látszik | A health check gyorsabban indult, mint a szolgáltatás | Frissítsd a repót. A jelenlegi telepítő legfeljebb 10 másodpercig csendben újrapróbálkozik, és csak a végleges health-check hibát jelzi. |
| `VapourSynth hiba` | A `vspipe` vagy egy szükséges plugin nem tölthető be | Futtasd a `doctor --json` parancsot, frissítsd a telepítést, majd nézd meg a worker naplóját. |
| ImgBB/Catbox/Freeimage credential nincs beállítva | Az adott képfeltöltő nem használható hitelesítve | Állítsd be az 5. fejezet szerint. A kódolás ettől még elkészülhet, de a feltöltés korlátozott vagy hibás lehet. |
| „A(z) OpenAI / Claude (Anthropic) API-kulcs nincs beállítva a szerveren” | A kiválasztott AI-szolgáltatónak nincs kulcsa | Add meg a kulcsot a **Rendszer → AI tanácsadó** kártyán, vagy válassz másik szolgáltatót (5.2.1. pont). A hagyományos profilajánló és a kódolás ettől még működik. |
| „…elutasította az API-kulcsot” | A szolgáltató a kulcsot érvénytelennek találta (401) | Hozz létre új kulcsot, és mentsd el újra a Rendszer oldalon. |
| „Az AI szolgáltatás nem adott használható választ” | Hálózati, szolgáltatói, jogosultsági vagy modellhiba történt | Ellenőrizd az internetkapcsolatot és az OpenAI API-fiókot, majd próbáld újra. Ha sürgős, használd a determinisztikus profilt; a job adatai nem vesznek el. |
| Az AI célmérete nem pontosan teljesül | A CRF minőséget céloz, nem garantált bájtméretet | A célméret csak tanácsadási szempont. Pontos méretigényhez később külön kétmenetes méretcélzó mód szükséges. |
| A forrás nem jelenik meg | Rossz gyökérmappa, jogosultsági hiba vagy közvetlen UNC útvonal | Ellenőrizd, hogy a gyökér alatt ténylegesen van `BDMV`, Windows alatt használj meghajtóbetűjelet. |
| `source color metadata is incomplete` | A lemez színinformációja hiányos vagy ellentmondásos | Nyisd meg a tervet, ellenőrizd a scan adatokat és erősítsd meg a helyes színprofilt. UHD-n ne hagyd figyelmen kívül automatikusan. |
| A comparison túl sokáig fut | Hibás vagy régi összehasonlító szakasz, nehezen található frame-pár | Frissítsd a rendszert. Az új gyors comparison időkorlátos. Ha review állapotba kerül, használd a folytatást. |
| `UPLOAD_FAILED` | Egyik képfeltöltő sem fogadta el a képeket | Ellenőrizd az internetet és credentialöket, majd a munka oldalán válassz: újrapróbálás, újrakezdés más tárhellyel vagy képkészlettel, vagy befejezés képek nélkül. A videót egyik sem kódolja újra. |
| `FAILED` vagy `CANCELLED`, és sok helyet foglal | A folytatáshoz megtartott checkpointok és munkafájlok foglalják a helyet | Folytasd a jobot, vagy válaszd a **Munka törlése** műveletet. Ne törölj kézzel fájlokat futó job alól. |
| Az uninstall azt írja, hogy aktív a várólista | Encode, scan vagy helyreállítás fut | Állítsd le vagy zárd le a munkát a weboldalon, várd meg a rendezett leállást, majd futtasd újra az eltávolítót. |

### 10.3. A Windows weboldal nem nyílik meg

Nyiss rendszergazdai PowerShellt, és futtasd sorrendben:

```powershell
wsl --list --verbose
Get-ScheduledTask -TaskName "BDEncode WSL"
Start-ScheduledTask -TaskName "BDEncode WSL"
wsl -d Debian -- systemctl restart bdencode-api.service bdencode-worker.service nginx.service
curl.exe --noproxy "*" http://127.0.0.1:8787/encoder/
```

Ezután nyisd meg:

```text
http://localhost:8787/encoder/
```

Ha a `Debian` nem szerepel a listában, a telepítés nem fejeződött be. Futtasd újra a legfrissebb Windows-telepítőt.

### 10.4. A szolgáltatás hibás

Windows PowerShellből lekérhető az utolsó 100 sor:

```powershell
wsl -d Debian -- journalctl -u bdencode-api.service -n 100 --no-pager
wsl -d Debian -- journalctl -u bdencode-worker.service -n 100 --no-pager
wsl -d Debian -- journalctl -u nginx.service -n 100 --no-pager
```

Újraindítás:

```powershell
wsl -d Debian -- systemctl restart bdencode-api.service
wsl -d Debian -- systemctl restart bdencode-worker.service
wsl -d Debian -- systemctl restart nginx.service
```

### 10.5. Kevés a szabad hely

Linuxon:

```bash
df -h "$HOME/encode"
du -sh "$HOME/encode/jobs"/* 2>/dev/null
```

Ne töröld kézzel egy aktív vagy folytatandó job belső fájljait. A webes **Munka törlése** ismeri a job pontos határait és az adatbázist is frissíti.

Lassú csatolású forrásnál (Windows-meghajtó WSL alatt) az előkészítés idejére a cím helyi másolata is helyet foglal a `cache/disc-stage` mappában (UHD-filmnél kb. 60 GB). A worker ezt a remux után magától törli; ha nincs elég hely, a másolás elmarad (14.3.).

### 10.6. Hibajelentéshez szükséges adatok

Hasznos adatok:

- a hiba pontos szövege;
- a job azonosítója;
- melyik szakaszban állt le;
- a worker napló érintett része;
- a `doctor --json` kimenete;
- a Debian verziója: `cat /etc/os-release`;
- Windows esetén a telepítési napló releváns része.

Titkos API-kulcsot, jelszót vagy teljes credential fájlt ne küldj hibajelentésben.

## 11. Frissítés

### 11.1. Automatikus frissítés

A telepítő létrehoz egy napi systemd timert (`bdencode-update.timer`). A timer **csak új kiadást keres**, az apt-csomagokat és a médiaeszközöket nem frissíti: a `bdencode-update.service` lekérdezi a beállított repository legmagasabb stabil `vX.Y.Z` tagjét, és összeveti a telepített verzióval. Ha nincs újabb kiadás, nem történik semmi.

Újabb kiadásnál a frissítő felügyelet nélkül telepít: letölti a kiadás tagjét, majd a kiadás saját telepítőjét futtatja a telepítő felhasználóként (`install/install.sh`, Windows/WSL alatt `install/wsl-install.sh`). Ezért ugyanaz a tranzakciós mentés, egészségellenőrzés és visszagörgetés védi, mint a kézi frissítést (11.2.). A telepítés csak akkor indul el, ha

- a tag `vX.Y.Z` alakú, újabb a telepítettnél, és a kiadás `pyproject.toml` verziója megegyezik vele;
- nincs a csővezetéket foglaló, futó vagy felülvizsgálatra váró munka (a várakozó, valamint a választásra vagy feltöltés újrapróbálására váró munkák nem akadályozzák); különben másnap újra próbálkozik;
- a telepítő felhasználónak van jelszó nélküli `sudo` joga. A Windows-telepítő ezt beállítja. Debian szerveren neked kell megadnod; addig a frissítő csak jelzi az új kiadást, a telepítést kézzel kell elvégezni (11.2.).

Ha egy kiadás telepítése kétszer meghiúsul, a frissítő addig nem próbálkozik vele, amíg újabb kiadás nem jelenik meg. Az előző kiadás ilyenkor is változatlanul fut.

A szerveren futó verzió a weboldal oldalsávjában, a BDEncode felirat alatt látszik (3.0.2-től). Ha frissítés után egy nyitott lap még a régi felületet futtatja, az oldalsáv ezt jelzi, és az **Oldal frissítése** gomb betölti az újat.

Ellenőrzése:

```bash
systemctl list-timers bdencode-update.timer
systemctl status bdencode-update.timer --no-pager
cat /var/lib/bdencode/release-update/status.json
tail -n 30 /var/lib/bdencode/release-update/release-update.log
sudo /usr/local/libexec/bdencode-release-update check   # csak keres, nem telepít
```

A futási idő naponta változhat, mert a rendszer terheléselosztás céljából legfeljebb 45 perces véletlen késleltetést használ. Ha a gép a tervezett időben ki volt kapcsolva, a `Persistent=true` miatt később pótolja a futást.

A `status.json` `state` mezője: `up_to_date`, `update_available`, `manual_update_required`, `deferred`, `installed`, `check_failed`, `install_failed`, `blocked` vagy `invalid_release`. A `release-update.log` tartalmazza a telepítő teljes kimenetét is; a régebbi rész a `release-update.log.1` fájlban marad. Ezek a fájlok a `/var/lib/bdencode/release-update/` mappában vannak, és bárki olvashatja őket.

A beállítás a `/etc/bdencode/release-update.toml` fájlban van. A telepítő egyszer hozza létre, és utána nem írja felül:

```toml
repository = "https://github.com/accofil/bdencode-backend.git"
automatic_install = true   # false: csak jelzi az új kiadást, a telepítést kézzel végzed
```

Az automatikus telepítés azt jelenti, hogy aki a beállított repository írási jogát megszerzi, a gépeden kódot futtathat. Ha ez nem elfogadható, állítsd `automatic_install = false` értékre, vagy tiltsd le a timert: `sudo systemctl disable --now bdencode-update.timer`. A frissítő a nem `https://` és a jelszót tartalmazó repository-címet, valamint az ismeretlen kulcsot is hibaként utasítja el, és a `release-update.toml` fájlnak root-tulajdonúnak kell lennie.

A **Rendszer** oldal „Kiadáskeresés és frissítés" kártyája ugyanezt mutatja (`GET /api/v1/system/release-update`). Opcionálisan értesítést is kérhetsz: a `release-update.toml` `notify_url = "https://ntfy.sh/a-te-temad"` sora (csak `https://`, jelszó nélkül) egy JSON POST-ot küld, amikor egy frissítés települt, megbukott, leállt vagy érvénytelen kiadást talált (ugyanarról az állapotról nem ismétel). **Visszaállás vagy kézi kiadás:** `sudo /usr/local/libexec/bdencode-release-update install --tag vX.Y.Z` pontosan azt a kiadást telepíti a megszokott védelmekkel (üres sor, jelszó nélküli sudo, tag és verzió egyezése, a kiadás saját tranzakciós telepítője), régebbit is. Régebbi kiadás csak akkor telepíthető, ha az adatbázis sémaverzióját ismeri (a 2.x kiadásoké 2).

#### Aláírt kiadások (opcionális)

Alapértelmezésben a frissítő a repository legmagasabb `vX.Y.Z` tagjét telepíti. Ha azt akarod, hogy csak a **te kulcsoddal aláírt** tag települhessen, a GitHub-fiók vagy az átvitel megsértése esetén sem, kapcsold be az SSH-aláírás ellenőrzését. Ez nem véd a gépen már megszerzett BDEncode-fiók ellen, csak a repository és az átvitel megbízhatatlanságától.

1. Készíts külön kiadási kulcsot (jelszóval védve), és állítsd be a gitet:

   ```bash
   ssh-keygen -t ed25519 -C "bdencode-release" -f ~/.ssh/bdencode-release
   git config --global gpg.format ssh
   git config --global user.signingkey ~/.ssh/bdencode-release.pub
   ```

2. Add hozzá a nyilvános kulcsot a frissítő bizalmi listájához (a fájlnak root-tulajdonúnak kell lennie, és nem lehet mások által írható):

   ```bash
   echo "release@bdencode namespaces=\"git\" $(cat ~/.ssh/bdencode-release.pub)" | sudo tee /etc/bdencode/release-signers
   sudo chmod 0644 /etc/bdencode/release-signers
   ```

3. Kapcsold be a `/etc/bdencode/release-update.toml` fájlban: `require_signed_tags = true` (opcionális a `signers_file = "/etc/bdencode/release-signers"` sor; ez az alapértelmezett útvonal). Ha a bizalmi lista hiányzik vagy üres, a frissítő `check_failed` állapotba kerül, és nem telepít, tehát nem kapcsolja ki magát csendben.
4. Új kiadás: `python tools/release.py tag vX.Y.Z` létrehozza az annotált, aláírt taget a `HEAD` commiton, és ellenőrzi a kiadás fájljait; utána `git push origin vX.Y.Z`. A GitHub API-val vagy a webes felületen létrehozott tag nincs aláírva, ezért ilyen tagek nem települnek.

Aláíratlan vagy ismeretlen kulccsal aláírt tag `invalid_release` állapotot kap, azonnal blokkolt marad, és semmi nem települ. A `status.json` üzenete aláírt tagnál a „(signed tag verified)" szöveget tartalmazza. A kézi `install --tag` parancs ugyanezt követeli; olyan régebbi kiadáshoz, amely az aláírás bevezetése előtt készült, használd a `--allow-unsigned` kapcsolót (csak a kézi parancsnál működik). A telepítő `openssh-client` csomagot is feltesz, mert az ellenőrzés az `ssh-keygen`-t használja.

A médiaeszközök (apt-csomagok, VapourSynth, natív szkenner) frissítését a timer már nem végzi, de a várakozó Debian-frissítéseket (ffmpeg, x264, x265, mkvtoolnix, mediainfo, libbluray) naponta jelzi a `status.json` `media_updates` mezőjében és a Rendszer oldalon. A korábbi, tranzakciós eszközfrissítő továbbra is telepítve van, és kézzel indítható: `sudo env BDENCODE_USER=<fiók> /usr/local/libexec/bdencode-daily-update`. A 2.4.0-ig ez a futás a `mkvtoolnix` biztonsági frissítésén elbukott és visszagörgetett (a rendszer ilyenkor sértetlen maradt): az `apt` az ellenőrzött helyi `.deb` fájlt eldobta, mert ugyanazt a verziót a tárolóból akarta letölteni, amit a `--no-download` tilt. Mostantól a tranzakció a hash-ellenőrzött fájlt egy privát apt-gyorsítótárba teszi, és név és verzió szerint telepíti, az apt pedig ezt is összeveti az aláírt csomagindexszel.

### 11.2. Kézi frissítés

```bash
cd ~/bdencode-backend
git fetch origin
git switch main
git pull --ff-only
bash install/install.sh
```

Windows alatt a repót Windowsból is frissítheted, majd újrafuttathatod a `windows-install.cmd` fájlt. A telepítő frissítésként kezeli a már létező környezetet; nem kell előtte eltávolítani.

A Windows-telepítő alapból a legfrissebb kiadást (a legmagasabb `vX.Y.Z` taget) telepíti, ahogy a napi frissítő is, így friss telepítés sem kap kiadatlan kódot a `main`-ből; `-Branch` megadásakor azt az ágat vagy taget klónozza. A kézi frissítési példa a `main` ágat használja. A Linux installer a sémamigráció előtt, leállított API és worker mellett a SQLite backup API-val konzisztens, root-only adatbázismentést készít és annak digestjét a telepítési tranzakcióhoz köti. Ha a candidate health/doctor ellenőrzése megbukik, vagy a telepítés a tartós `HEALTHY` döntés előtt megszakad, a rollback előbb ezt az adatbázismentést állítja vissza és ellenőrzi, utána állítja vissza az előző alkalmazáspointert és konfigurációt, és csak ezután indíthatja újra a régi szolgáltatásokat. A már tartós `HEALTHY` állapot utáni megszakítást a recovery a validált candidate commitjának finalizálásával zárja le, nem rollbackkel. Így a régi backend nem kap nála újabb adatbázissémát; sikertelen vagy nem bizonyítható schema-safe visszaállításnál a szolgáltatások blokkolva maradnak kézi helyreállításig.

## 12. Eltávolítás Linux vagy szerver esetén

### 12.1. Mielőtt elkezded

1. Fejezd be vagy szakítsd meg rendezetten az aktív munkát.
2. Mentsd ki azokat az eredményeket, amelyekre szükséged van.
3. Ellenőrizd a tényleges adatmappa és forrásmappa útvonalát.
4. Lépj be ugyanazzal a normál felhasználóval, amellyel telepítettél.
5. Ne futtasd az eltávolítót `root` felhasználóként.

A forráslemezeket az eltávolító soha nem törli.

### 12.2. Csak az alkalmazás eltávolítása, adatok megőrzésével

```bash
cd ~/bdencode-backend
bash install/uninstall.sh
```

Ez eltávolítja:

- a BDEncode systemd szolgáltatásokat és timert;
- a telepített alkalmazás aktív bekötését;
- a frontend és nginx/Swizzin integrációt;
- a rendszerállapothoz tartozó BDEncode fájlokat.

Ez alapértelmezetten megőrzi:

- a queue/job/output adatokat;
- a `~/encode` adatmappát;
- a képfeltöltő credentialöket;
- az eredeti forrásokat;
- az APT-tal telepített csomagokat;
- a Git checkoutot.

Az APT csomagokat azért nem távolítja el automatikusan, mert nem minden régebbi telepítésnél állapítható meg biztonságosan, melyiket használja más alkalmazás is.

### 12.3. Egyedi útvonalas telepítés eltávolítása

Ha a `/etc/bdencode/config.toml` hiányzik, vagy egyértelműen meg akarod adni a helyeket:

```bash
cd ~/bdencode-backend
bash install/uninstall.sh \
    --data-root /home/FELHASZNALO/encode \
    --source-root /storage
```

Több forrásgyökér esetén a `--source-root` többször megadható.

### 12.4. Teljes adatmappa törlése

> [!CAUTION]
> Ez visszavonhatatlanul törli a teljes megadott BDEncode adatmappát, benne a jobokkal, naplókkal, ideiglenes fájlokkal és az ott tárolt kész eredményekkel. Előtte készíts biztonsági mentést.

Az eltávolító szándékosan kétszer kéri ugyanazt a pontos útvonalat:

```bash
cd ~/bdencode-backend
bash install/uninstall.sh \
    --data-root /home/FELHASZNALO/encode \
    --source-root /storage \
    --purge-data \
    --confirm-data-root /home/FELHASZNALO/encode
```

A `--data-root` és `--confirm-data-root` értékének pontosan egyeznie kell. Ez véd a rossz mappa véletlen törlésétől.

### 12.5. Credentialök törlése

A nyolc, telepítő által ismert fix titkosított credential törlése:

```bash
cd ~/bdencode-backend
bash install/uninstall.sh --purge-credentials
```

A kapcsoló pontosan az `imgbb-api-key`, `catbox-userhash`, `freeimage-api-key`, `qbittorrent-username`, `qbittorrent-password`, `tracker-aither-api-token`, `openai-api-key` és `anthropic-api-key` credentialt törli. A két qBittorrent-credentialt a 3.0 már nem használja; a korábbi telepítésből megmaradtakat ez a kapcsoló is eltávolítja. Egyedi nevű trackercredentialt és az üzemeltető által kezelt `tracker-local.conf` drop-int szándékosan nem távolít el; ezeket szükség esetén külön, kézzel kell törölni.

Alkalmazás, adatok és credentialök együttes eltávolításakor a kapcsolókat egy parancsban add meg.

### 12.6. Beépített biztonsági ellenőrzések

Az eltávolító megtagadja a törlést, ha:

- aktív queue vagy helyreállítás fut;
- az útvonal nem abszolút;
- az útvonal túl tág, például `/` vagy a teljes home;
- a cél szimbolikus link vagy mountpoint;
- a forrás és az adatgyökér átfedi egymást;
- a cél más tulajdonoshoz tartozik;
- a megerősítő útvonal eltér.

Ne kerüld meg ezeket az ellenőrzéseket kézi `rm -rf` paranccsal.

## 13. Eltávolítás Windows esetén

Két lehetőség van:

- csak a BDEncode eltávolítása, a Debian WSL megtartásával;
- a teljes, kizárólag BDEncode céljára telepített Debian WSL törlése.

### 13.1. Csak a BDEncode eltávolítása, Debian megtartása

1. Nyiss PowerShellt.
2. Lépj be a Debianba:

   ```powershell
   wsl -d Debian
   ```

3. A Linux parancssorban lépj a repó Windowsból csatolt mappájába. Például `C:\BDEncode` esetén:

   ```bash
   cd /mnt/c/BDEncode
   bash install/uninstall.sh
   exit
   ```

4. Ezután rendszergazdai PowerShellben töröld az életben tartó ütemezett feladatot és a Windows-specifikus nginx fájlt:

   ```powershell
   Stop-ScheduledTask -TaskName "BDEncode WSL" -ErrorAction SilentlyContinue
   Unregister-ScheduledTask -TaskName "BDEncode WSL" -Confirm:$false -ErrorAction SilentlyContinue
   wsl -d Debian -u root -- rm -f /etc/nginx/conf.d/bdencode-wsl.conf
   ```

5. Töröld kézzel az asztali BDEncode parancsikonokat, ha megmaradtak.
6. Ha már nincs szükséged a telepítő naplójára, törölheted a `%LOCALAPPDATA%\BDEncode` mappát.

### 13.2. A teljes BDEncode Debian WSL törlése

> [!CAUTION]
> A `wsl --unregister Debian` visszavonhatatlanul törli a teljes Debian disztribúciót és minden benne lévő fájlt. Csak akkor használd, ha ez a Debian példány kizárólag a BDEncode számára készült. Előbb másold ki a kész munkákat.

1. Ellenőrizd a disztribúció pontos nevét:

   ```powershell
   wsl --list --verbose
   ```

2. Másold ki a szükséges fájlokat a `completed` mappából.
3. Nyiss rendszergazdai PowerShellt, majd futtasd:

   ```powershell
   Stop-ScheduledTask -TaskName "BDEncode WSL" -ErrorAction SilentlyContinue
   Unregister-ScheduledTask -TaskName "BDEncode WSL" -Confirm:$false -ErrorAction SilentlyContinue
   wsl --shutdown
   wsl --unregister Debian
   ```

4. Ellenőrizd, hogy eltűnt:

   ```powershell
   wsl --list --verbose
   ```

5. Ha megmaradtak, kézzel törölhetők:

   ```text
   %LOCALAPPDATA%\BDEncode
   %LOCALAPPDATA%\BDEncodeWSL\Debian
   ```

6. Töröld az asztali parancsikonokat és – ha már nem kell – a letöltött `C:\BDEncode` Git/ZIP mappát.

A Windows meghajtón levő eredeti forrásmappa, például `D:\Filmek`, a Debian unregister műveletétől nem törlődik.

## 14. Haladó üzemeltetési tudnivalók

### 14.1. CPU-korlát

A `BDENCODE_CPU_PERCENT=80` azt jelenti, hogy a worker a gép összes logikai CPU-kapacitásának 80%-át kaphatja. Például 32 logikai CPU-nál a systemd kvóta 2560%.

2.10-től a keret a **Rendszer** oldalon is állítható, telepítés nélkül:

- **Nappali CPU-keret** (10–100%);
- **Éjszakai mód** saját kerettel és idősávval, például 23:00–07:00 között 100%. Az idősáv a mentő böngésző időzónájában értendő.

A beállítás a `<adatmappa>/state/cpu-policy.json` fájlba kerül. A root jogú `bdencode-cpu-policy` segéd szigorúan ellenőrzi, majd a worker futásidejű `CPUQuota` értékeként alkalmazza. Mentéskor a `bdencode-cpu-policy.path` azonnal indítja, a `bdencode-cpu-policy.timer` ötpercenként vált a nappali és az éjszakai keret között. Az eredményt a `/var/lib/bdencode/cpu-policy/status.json` rögzíti. Futó kódolásnál is azonnal érvényes. Amíg nincs mentett beállítás, a telepítéskori érték marad érvényben.

Ez nem azt jelenti, hogy a Feladatkezelő mindig pontosan 80%-ot mutat. Egyes szakaszok nem használják ki az összes engedélyezett szálat, más háttérfolyamatok pedig szintén fogyaszthatnak CPU-t.

Más limit telepítéskor:

```bash
BDENCODE_CPU_PERCENT=60 bash install/install.sh
```

Az érték 1 és 100 közötti egész szám lehet.

### 14.2. Szolgáltatások

```bash
sudo systemctl status bdencode-api.service --no-pager
sudo systemctl status bdencode-worker.service --no-pager
sudo systemctl restart bdencode-api.service bdencode-worker.service
```

### 14.3. Konfiguráció

A gépszintű konfiguráció helye:

```text
/etc/bdencode/config.toml
```

Módosítás előtt készíts másolatot, és inkább futtasd újra a telepítőt a kívánt környezeti változókkal. Kézi szerkesztésnél egy hibás útvonal vagy jogosultság a workert indulásképtelenné teheti.

A trackerprofilok külön, root által kezelt fájlban vannak:

```text
/etc/bdencode/release-profiles.json
```

A fix dupe-check endpointot és a host-allowlistet itt, a hozzá tartozó API-titkot kizárólag titkosított systemd credentialként állítsd be. Egy 3.0 előtti profilfájlban maradt announce URL személyes passkeyt tartalmazhat: a rendszer már nem használja, ezért törölheted. A régi, torrentet is tartalmazó csomagokat továbbra is titokként kezeld. A részletes lépések az [5.3. fejezetben](#53-trackerprofil-beállítása) találhatók.

**Az előkészítés gyorsítása.** Három kulcs (környezeti változóval is: `BDENCODE_SOURCE_STAGING`, `BDENCODE_CROP_HWACCEL`, `BDENCODE_SOURCE_FILTER`):

- `source_staging = "auto"`: lassú csatolásról (Windows-meghajtó WSL alatt, hálózati megosztás) a kiválasztott cím lemezfájljai a referencia-remux előtt párhuzamos olvasással a helyi `<data_root>/cache/disc-stage` mappába másolódnak, és a remux onnan olvas. A másolat a remux után törlődik, a félbehagyott másolatok egy nap után. Helyigény a másolás idejére: a cím mérete plusz ugyanennyi a referenciának plusz 10 GB. Ha ez nincs meg, a lemez a helyén olvasódik (lassabban), és erről esemény kerül a jobhoz. `"always"` mindig másol, `"never"` soha.
- `crop_hwaccel = "auto"`: ha van NVIDIA GPU, a crop-keresés azon dekódol (NVDEC), különben, illetve GPU-hiba esetén a CPU-n. Nem kell hozzá semmit beállítani; `"none"` = mindig CPU.

**GPU nélküli szerver (3.3-tól).** A GPU teljesen opcionális. A worker szolgáltatás privát `/dev`-vel fut, ezért GPU-t csak a telepítő által írt `/etc/systemd/system/bdencode-worker.service.d/gpu.conf` kiegészítőn keresztül érhet el. A telepítő minden futáskor megnézi, mely GPU-eszközök vannak a gépen (WSL-en a `/dev/dxg`, natív Linuxon az NVIDIA-illesztő `/dev/nvidiactl`, `/dev/nvidia-uvm`, `/dev/nvidia0`… eszközei), és pontosan ezeket köti be. Ha nincs GPU, a kiegészítő nem készül el, és a crop-keresés CPU-n fut, párhuzamos szakaszokban, kb. ugyanolyan gyorsan. A **Rendszer** oldal Processzor kártyája mutatja, melyik eset áll fenn. Ha később kerül GPU vagy NVIDIA-illesztő a gépre, futtasd újra a telepítőt.

**Crop-keresés (3.1-től).** Az előkészítés csak a film kulcsképkockáit dekódolja (Blu-rayen kb. másodpercenként egyet). GPU-n ez egy menetben fut, CPU-n a filmet legfeljebb 16, egyenként legalább egyperces szakaszra bontja, és ezeket párhuzamosan dekódolja, mert a kulcsképkockás dekódolás egyszálú. Egy UHD filmen (La Femme Nikita, 117 perc) mindkettő kb. 4–4,5 perc, ugyanazzal a crop-pal, mint a minden képkockát dekódoló keresés (GPU-n 19, CPU-n kb. 56 perc). Ha a forrásban túl kevés a kulcsképkocka a döntéshez, minden képkockát dekódol.

A kulcsképkockák között megbújó, egy másodpercnél rövidebb, szélesebb snittet (például egy teljes képes betét egy scope filmben) a kódolás melletti teljes dekódolás ellenőrzi, minden képkockán. Ha a választott crop ebből képet vágna le, a munka a muxolás előtt felülvizsgálatra kerül („crop verification…”). A megszakítás és újraindítás után az előkészítés minden képkockát dekódol, és olyan cropot választ, amely semmit nem vág le. Az eredmény az `analysis/crop-verification.json` fájlban van.
- `source_filter = "lsmas"`: a referencia VapourSynth-forrása az L-SMASH, amely a konténer csomagjaiból indexel (UHD-n kb. 90 mp). A `"bestsource"` minden képkockát dekódol az indexhez (UHD-n kb. 45 perc). A két forrás ugyanarra a képkockaszámra bitre azonos képet ad (valódi UHD-referencián ellenőrizve, véletlenszerű ugrásokkal is). Az index a crop-kereséssel egy időben készül.

A forrás teljes, szigorú dekódolása (integritás-ellenőrzés, UHD-n kb. egy óra) nem az előkészítésben fut, hanem a videókódolással párhuzamosan, alacsonyabb CPU-prioritással (`nice -n 10`). Sérült forrásnál leállítja a kódolást, és a job felülvizsgálatra kerül („source video integrity diagnostics require review”). Ugyanez a dekódolás ellenőrzi a cropot is (lásd fent).

**Többklipes playlistek (3.1.1-től).** Ha a film több klipből áll (például egy rövid záróklip vagy seamless branching), a remux a klipváltásoknál időbélyeg-ugrást jelez, és jelezheti az előző klip levágott utolsó csomagját is („Packet corrupt”, TrueHD „Parity check failed”). Az előkészítés ilyenkor minden klipváltás körül (−20 s … +10 s) szigorúan dekódolja a referencia videóját és minden hangsávját. Ha ez hibátlan, a váltásnál keletkezett üzenetek nem számítanak forrássérülésnek (`analysis/clip-joins.json`); minden más jelzés, és a klipváltástól távoli sérülés is, továbbra is megállítja a munkát. A muxolás csak sikeres ellenőrzés után indul. Az előkészítés csak a remux naplóját nézi át, mert az pillanatok alatt megvan.

### 14.4. Opcionális eszközök a dinamikus HDR-hez

A `dovi_tool`-t és a `hdr10plus_tool`-t a telepítő felteszi (a letöltés hibája nem akasztja meg a telepítést; 7.4.3. pont). A telepítés után a `bdencode doctor` kimenetében ellenőrizd:

```bash
bdencode doctor | python3 -m json.tool | grep -A10 '"dynamic_hdr"'
```

Minden módnál négy érték látszik: az eszköz neve, elérhetősége, verziója és az, hogy az x265 támogatja-e a szükséges paramétert. `available: true` HDR10+-nál, ha az eszköz megvan (az x265 támogatása nem kell, a metaadatot utólag szúrjuk be), Dolby Visionnél az eszköz és az x265 profiljelzése is kell. Hiányzó eszköz mellett az `auto` mód csendben eldob, az explicit `hdr10plus`/`dolby_vision` mód felülvizsgálatot kér.

### 14.5. Adatbázis: migráció, mentés és visszaállítás

A várólista egyetlen SQLite adatbázis (`<data_root>/state/encoder.sqlite3`). Három védelem szól mellette:

1. **Migráció előtti mentés.** Sémafrissítés (jelenleg v1 → v2) előtt az adatbázis induláskor automatikusan mentésre kerül `pre-migration-v<N>` címkével. A telepítő ettől függetlenül saját pillanatképet is készít; ha a belső mentés valamiért nem sikerül, a hiba naplózódik és a (tranzakciós) migráció folytatódik, mert a telepítői pillanatkép így is megvan. Minden migráció bekerül a `schema_migrations` táblába (mikor, melyik verzióról melyikre, melyik mentéssel, melyik BDEncode-verzióval).
2. **Ütemezett mentés.** A worker üresjáratban naponta ellenőrzött online mentést ír a `state/backups` mappába. Beállítás a `config.toml`-ban (vagy `BDENCODE_BACKUP_INTERVAL_HOURS`, `BDENCODE_BACKUP_KEEP_SCHEDULED` környezeti változóval): `backup_interval_hours = 24` (0 = kikapcsolva), `backup_keep_scheduled = 14`. Megőrzés fajtánként: ütemezett 14, kézi 10, migráció előtti 5, visszaállítás előtti 3.
3. **Kézi mentés.** A Rendszer oldal „Mentés most” gombjával, vagy parancssorból.

A mentés SQLite online backup API-val készül, ezért futó API és worker mellett is konzisztens (a WAL-ba még nem checkpointolt, véglegesített adatokkal együtt), a másolat egyetlen önálló fájl (`journal_mode=DELETE`), és csak `PRAGMA integrity_check` sikere után, atomi átnevezéssel kerül a végleges nevére. Mellé JSON manifest kerül (méret, SHA-256, sémaverzió, munkák száma).

```bash
bdencode db-status                 # séma, integritás, migrációs előzmények, mentések
bdencode db-backup                # kézi mentés (--label, --output-dir)
bdencode db-backups --verify      # a mentések újrahashelése és integritásellenőrzése
```

**Visszaállítás** szándékosan csak parancssorból, leállított szolgáltatásokkal lehetséges:

```bash
sudo systemctl stop bdencode-api.service bdencode-worker.service
bdencode db-restore encoder-20260501T030000Z-scheduled-1a2b3c4d.sqlite3 --yes
sudo systemctl start bdencode-worker.service bdencode-api.service
```

A parancs előbb ellenőrzi a mentést (hash, integritás, támogatott séma), majd a jelenlegi adatbázisról `pre-restore` mentést készít, törli a régi `-wal`/`-shm` fájlokat, és atomi cserével visszaírja a mentést. Ha még van olyan munka, amely a pipeline-t foglalja, a parancs megtagadja a futást (`--force` felülírja). Régebbi sémájú mentés is visszaállítható: a következő indulás migrálja, előtte újabb `pre-migration` mentéssel. A visszaállítás csak az adatbázist érinti, a fájlrendszeren lévő munkamappákat nem.

### 14.6. Adatbiztonság

- A forrást a BDEncode olvassa, nem módosítja.
- A munkamappában nagy ideiglenes fájlok keletkezhetnek.
- A kész eredményt csak sikeres lezárás után tekintsd véglegesnek.
- Fontos kiadásnál a kész MKV és mellékletei kerüljenek külön mentésbe.
- Futó job alatt ne mozgass vagy törölj kézzel fájlokat.

## 15. Fejlesztés és tesztelés

### 15.1. Python környezet

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[test]'
pytest
```

Windows PowerShellben:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[test]"
pytest
```

### 15.2. Frontend fejlesztés

```bash
cd frontend
corepack pnpm install --frozen-lockfile   # pnpm 11.9.0, a lockfile szerint
corepack pnpm typecheck
corepack pnpm test
corepack pnpm build                        # újraépíti a commitolt frontend/dist mappát
```

A `frontend/dist` előre lefordítva a tárolóban van, mert a telepítő ezt publikálja. Felületi módosítás után építsd újra és commitold; a CI ellenőrzi, hogy a commitolt kiadás megegyezik a forrás buildjével. Windowson a Vite az `index.html` sorvégeit CRLF-re alakíthatja: commit előtt a `dist/index.html`-ben csak a két eszköznév (`assets/index-….js/css`) térhet el, a sorvégek LF-ek maradjanak.

Fejlesztői szerverhez a projekt `frontend` mappájának csomagszkriptjeit használd. A telepített produkciós frontend a buildelt fájlokat nginx mögül szolgálja ki; a fejlesztői szerver nem helyettesíti a telepített API-t és workert.

### 15.3. Tesztek Windowson (PowerShell 5.1 és 7)

A `tests/test_windows_install_powershell.py` a `install/windows.ps1` argumentumkezelő útjait **ténylegesen lefuttatja**, a WSL, a rendszerleíró adatbázis és az UAC érintése nélkül. A `tests/powershell/build_windows_harness.ps1` a PowerShell-elemzővel (AST) kivágja a valódi telepítőből a paraméterblokkot, a fenntartott 8796-os port védelmét, az argumentum-továbbító függvényeket, az emelt jogú újraindítás blokkját és a `Register-ContinuationAfterRestart` függvényt; csak a rendszert érintő parancsokat (`Start-Process`, `New-Item`, `New-ItemProperty`) cseréli felvevőkre. A tesztek minden telepített shellben lefutnak: a `pwsh` (PowerShell 7) mellett Windowson a **Windows PowerShell 5.1**-ben is, amelyre a telepítő valójában készül.

Ellenőrzik, hogy minden kötött paraméter (szóközös, ékezetes, idézőjeles és visszaperjeles útvonalak) pontosan átmegy az emelt jogú újraindításon és a reboot utáni RunOnce folytatáson; hogy a második lépésben a shell **saját parancssor-értelmezője** ugyanazokra a paraméterekre köti vissza az átadott sort; hogy a 8796-os port és a tartományon kívüli portok az újraindítás előtt elutasítódnak; hogy az elutasított emelés hibaüzenettel, 1-es kilépőkóddal végződik; és hogy maga az `install/windows.ps1` mindkét verzióban hibátlanul elemezhető, valamint megőrzi az UTF-8 BOM-ot.

### 15.4. Folyamatos integráció

A `.github/workflows/ci.yml` minden pushra és pull requestre lefut: frontend (típusellenőrzés, tesztek, build, a commitolt `dist` frissességének ellenőrzése), Python 3.11/3.12/3.13 **Linuxon**, a teljes tesztsor **Windowson** (windows-latest, PowerShell 7 és 5.1 egyaránt), a shellszkriptek szintaxisa és sorvégei, valamint a natív libbluray-szkenner fordítása. A Windows-specifikus hibák (például egy `C:\Users` a TOML-sztringben) így azonnal kiderülnek.

A Linux-legek telepítik az `ffmpeg`, `mkvtoolnix` és `mediainfo` csomagot, hogy a valódi-eszközös tesztek (színkonverzió a kódolócsőben, 10 bites Y4M, mux) ne maradjanak ki. A VapourSynth és a libvmaf nincs a CI-ben, ezért a teljes csővezetéket szintetikus HDR10 „lemezen" a `tools/e2e/synthetic_disc.py` próbálja ki valódi eszközökkel (a lemezbeolvasás és a libbluray-remux kivételével). Futtasd a kódolás-, QC- vagy comparison-kód módosítása, valamint az ffmpeg, x265, VapourSynth vagy libvmaf frissítése után, a telepített eszközkészlettel (kb. 8 perc): `python tools/e2e/synthetic_disc.py --work /tmp/bdencode-e2e`, vagy `BDENCODE_E2E=1 python -m pytest tests/test_e2e_synthetic.py`.

A Windows-leg szándékosan **Python 3.13**-mal fut: ezt használja a Windows-gép, és ezt a WSL-beli Debian 13 is. Windowson 3.12-ig a csak Linuxon használt telepítő- és worker-tesztek platformokozta okból buknak: az `os.fchmod` nem létezik, a `time.time()` pedig durva óra, amely elmarad az NTFS `mtime`-tól, így egy közvetlenül a checkpoint előtt írt fájl újabbnak látszhat nála (helyi méréssel a fájlok kb. 10%-ánál). A 3.11-es és 3.12-es verziót a Linux-leg fedi le.

### 15.5. Fontos fejlesztői szabály

Tesztadatot vagy API-kulcsot ne commitolj. A valós Blu-ray források helyett kis, mesterséges mintákkal teszteld azokat a funkciókat, amelyekhez nincs szükség teljes lemezre.

---

Ha hibát találsz, először mentsd el a pontos hibaüzenetet és a kapcsolódó naplórészletet. A „nem működik” önmagában kevés; a job állapota, a hibás szakasz és az utolsó parancs általában azonnal megmutatja, hol kell javítani.
