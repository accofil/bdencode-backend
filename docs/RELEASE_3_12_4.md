# BDEncode 3.12.4 kiadási jegyzet

Új: több forrásmappa közül lehet választani az Új kódolás oldalon.

## Mi változott

- Ha a szerveren több forrásgyökér van beállítva (`/etc/bdencode/config.toml`, `source_roots`), a forrásböngésző tetején mindegyikhez gomb jelenik meg (például **storage** és **torrents**). A gomb a mappa nevét mutatja, a teljes útvonal a buborékban látszik. Kattintásra a böngésző az adott gyökérbe lép, a keresőmező kiürül.
- Egyetlen gyökérnél a felület változatlan.
- A böngésző a jelenlegi mappához a leghosszabb illeszkedő gyökeret választja, így például a `/storage2` nem számít a `/storage` részének.

## Forrásgyökér hozzáadása

A gyökereket a `source_roots` lista adja, például:

```toml
source_roots = ["/home/accofil/storage", "/home/accofil/torrents"]
```

- A program a forrásokat csak olvassa: a szolgáltatások `ProtectHome=read-only` beállítással futnak.
- A frissítés csak az első gyökeret ellenőrzi, a többit megtartja.
- A módosítás után az API-t és a workert újra kell indítani.

Torrent-mappánál csak a teljesen letöltött forrást válaszd: egy félig letöltött lemez vagy MKV scanje hibás eredményt adhat.

## Ellenőrzőlista

1. `GET /api/v1/capabilities` `backend_version`: `3.12.4`.
2. Két gyökérnél az Új kódolás oldalon megjelenik a **storage** és a **torrents** gomb, és a második gyökér tartalma böngészhető.
