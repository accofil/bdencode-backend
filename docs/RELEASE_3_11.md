# BDEncode 3.11.0 kiadási jegyzet

Új: a **képfeltöltők kulcsai a Rendszer oldalon is beállíthatók**, és ott választható a **tárhelyek sorrendje** is. A „libvmaf hiányzik” üzenet mostantól **szürke tájékoztatás**, nem figyelmeztetés.

## Képfeltöltő kulcsok a Rendszer oldalon

- A **Rendszer** oldal új **Képfeltöltés** kártyáján minden tárhelynek saját sora van: **ImgBB** (API-kulcs), **Catbox** (userhash, nem kötelező) és **Freeimage** (API-kulcs).
- Minden sorban a kulcs **beállítható, cserélhető és törölhető**, ugyanúgy, mint az AI-tanácsadó kulcsa. Az oldal sosem kapja vissza a kulcsot, csak azt, hogy be van-e állítva („Kulcs beállítva” / „Nincs kulcs”, Catboxnál „Névtelen feltöltés”).
- Mentés előtt a felület és a szerver is ellenőrzi a formát: az ImgBB és a Freeimage kulcsa pontosan 32 karakter, a Catbox userhash 16–64 karakter, csak betű és szám (szóköz, sortörés nem lehet benne; a bemásolt kulcs elején és végén lévő szóköz nem számít). Próbafeltöltés nincs; a kulcsot a tárhely az első feltöltésnél ellenőrzi.
- **A futó worker újraindítás nélkül** a következő feltöltésnél már az új kulcsot használja, egy épp futó kódolás mellett is. Törlés után a régi kulcsot sem használja tovább.
- A kulcs útja ugyanaz, mint az AI-kulcsoké: az API egyszeri kérést tesz a saját futásidejű mappájába, a `bdencode-credentials` segédprogram (root) `systemd-creds`-szel titkosítja a `~/.config/bdencode/<név>.cred` fájlba, és bekötteti a workerhez. Ezen felül átadja a futó workernek is: a worker saját, csak általa olvasható futásidejű mappájába (`/run/bdencode-worker/credentials`, tmpfs) írja, amit a worker minden feltöltésnél elolvas. Ez a mappa a worker leállásakor eltűnik; újraindulás után a worker a titkosított, bekötött kulcsot tölti be.
- A kézi beállítás (README 8. pont, `install_bdencode_secret` + telepítő) továbbra is működik.

## Tárhelyek sorrendje

- Ugyanezen a kártyán a nyilakkal állítható, melyik tárhellyel kezdjen az automatikus mód, és melyik a tartalék. Az alapértelmezett sorrend változatlan: ImgBB → Catbox → Freeimage.
- A sorrend a `<state>/image-upload-settings.json` fájlba kerül; a worker minden feltöltési lépésnél újraolvassa, ezért ehhez sem kell újraindítás. Az **Alapértelmezett sorrend** gomb visszaállítja a beépített sorrendet.
- Az **Új kódolás** oldal, a beállítóvarázsló és a feltöltési hiba űrlapja az „Automatikus” választásnál a mentett sorrendet mutatja.
- A már elkezdett feltöltés tárhelye továbbra is rögzített: a sorrend csak még el nem kezdett feltöltésre hat.

## A libvmaf üzenet szürke tájékoztatás

- Ha az FFmpeg-ben nincs `libvmaf` szűrő, a program a hivatalos, önálló VMAF parancssori programot használja. Ez nem hiba, ezért a Rendszer oldalon **Tájékoztatás** cím alatt, szürkén jelenik meg, a valódi figyelmeztetésektől külön. A **Runtime figyelmeztetések** blokk csak akkor látszik, ha van valódi figyelmeztetés.
- Az API-ban a `runtime-capabilities` válasz `warnings` listája csak a valódi figyelmeztetéseket tartalmazza (szövegként, mint eddig); az új `notices` lista minden tételt `severity` mezővel (`warning` vagy `info`) ad vissza.

## A varázsló nem jelez tévesen „Hiányzó nyelv”-et

Eddig minden megtartott sáv „bizonytalan nyelvű” volt, amelynél nem írtál be kézzel nyelvet, akkor is, ha a forrás címkéje rendben volt. Remux MKV-nál ez minden sávra kiírta a figyelmeztetést. Mostantól csak az a sáv számít bizonytalannak, amelynek
- nincs kézzel megadott nyelve,
- a címkéje hiányzik vagy ellenőrzésre szorul,
- és ezt a sávelemzés (hangnál a beszéd, feliratnál a szöveg) sem erősíti meg; címke nélküli sávnál a felismerésnek legalább 75%-osnak kell lennie.

A figyelmeztetés szövege sem állítja többé, hogy a PGS felirat nyelvét kézzel kell megadni.

## Új API-végpontok

- `GET /api/v1/system/image-upload`: a tárhelyek a sorrendjükben, `configured` jelzéssel; kulcsot sosem ad vissza.
- `PUT /api/v1/system/image-upload-settings`: `{"provider_order": ["freeimage", "imgbb", "catbox"]}` vagy `null` (alapértelmezett).
- `PUT /api/v1/system/image-upload-credentials/{imgbb|catbox|freeimage}`: `{"api_key": "…"}`, válasz `202`.
- `DELETE /api/v1/system/image-upload-credentials/{imgbb|catbox|freeimage}`: válasz `202`.

## Telepítés

- A telepítő újra kirajzolja a `bdencode-worker.service` egységet (új `RuntimeDirectory=bdencode-worker` és `BDENCODE_LIVE_CREDENTIAL_DIR`) és a `bdencode-credentials.service` egységet (írhatja a worker credential drop-injét). Az új worker-egység a worker következő indulásától érvényes; addig a Rendszer oldalon mentett képfeltöltő kulcsot a worker csak újraindulás után kapja meg.
- Az eltávolító listái nem változtak: a három kulcs `.cred` fájlját eddig is ismerte, a futásidejű mappát a systemd maga törli.

## Ellenőrzőlista

1. `GET /api/v1/capabilities` `backend_version`: `3.11.0`.
2. A Rendszer oldalon megjelenik a **Képfeltöltés** kártya; egy kulcs mentése után néhány másodpercen belül „Kulcs beállítva” lesz.
3. `systemctl show -p ActiveEnterTimestamp bdencode-worker` a kulcs mentése előtt és után ugyanaz (a worker nem indult újra).
4. A következő feltöltés az új kulccsal megy; a `bdencode-worker.service.d/credential.conf` tartalmazza a kulcs sorát.
5. libvmaf nélküli FFmpeg-nél a VMAF-üzenet szürkén, a **Tájékoztatás** alatt látszik.
