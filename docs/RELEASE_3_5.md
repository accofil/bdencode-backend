# BDEncode 3.5.0 kiadási jegyzet

Kezdőbarát útmutató magyarul és angolul, és webes felület Swizzin nélküli szerveren is.

## Változások

- **Új README, lépésről lépésre.** A [README.md](../README.md) magyarul, a [README.en.md](../README.en.md) angolul vezet végig mindhárom telepítési úton:
  - Windows (WSL);
  - Debian szerver Swizzin nélkül;
  - Swizzin seedbox.

  Utána az első belépés, a képfeltöltők és az AI-tanácsadó beállítása, az első kódolás, a mindennapi használat, a frissítés, a hibaelhárítás, az eltávolítás és az adatvédelem jön, a végén kisszótárral.
- **A korábbi részletes README** a [docs/REFERENCE.md](REFERENCE.md) fájlba került, változatlan tartalommal, a hivatkozások javításával.
- **Webes felület Swizzin nélküli Debian szerveren.**
  - Eddig ilyen gépen a telepítő csak figyelmeztetett („/encoder was not installed”), és a felület nem volt elérhető.
  - Most egy csak a szerveren belül elérhető oldalt tesz fel (`/etc/nginx/conf.d/bdencode-local.conf`, `127.0.0.1:8787`), szükség esetén az nginx-szel együtt, amelynek nyilvános alapoldalát kikapcsolja.
  - A felhasználó SSH-alagúton nyitja meg: `ssh -L 8787:127.0.0.1:8787 felhasznalo@szerver`, majd `http://localhost:8787/encoder/`. Nyilvános port és webes jelszó nem kell.
  - Másik port: `BDENCODE_LOCAL_WEB_PORT`. A frissítések megtartják a választott portot.
  - Ha a port foglalt, a telepítő visszaállítja az előző beállítást és figyelmeztet, a kódoló ettől még települ.
  - A Swizzines és a WSL-es telepítés nem változik. Az eltávolító ezt a beállítást is törli.

## Ellenőrzőlista

1. `GET /api/v1/capabilities` `backend_version`: `3.5.0`.
2. Swizzin nélküli Debian szerveren a telepítés végén kiírt `ssh -L …` paranccsal a `http://localhost:8787/encoder/` oldal megnyílik.

## További dokumentáció

- [BDEncode 3.4 kiadási jegyzet](RELEASE_3_4.md)
