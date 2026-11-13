# Accofil BDEncode 4.1.7 kiadási jegyzet

Javítások: a forrásböngésző egy nagy mappában is minden fájlt mutat és megtalál; a Windowsos életben tartó feladat ott is elindul, ahol a feladatütemező nem futtat fájlból PowerShell-szkriptet.

## A hibák

**Hiányzó MKV-k a forrásválasztóban.** A canada2 `aither` mappájában 2259 elem van (522 mappa, 1737 MKV). A szerver a mappa listáját 1000 elemnél szó nélkül elvágta. A mappák jöttek előre, utána ábécérendben az MKV-k, így csak az első 478 MKV látszott. A „The.Last.Whale.Singer…PENICILLIN.mkv” ezért nem jelent meg. A névkereső a böngészőben, a már csonka listán futott, ezért arra keresve sem került elő. A külső sávok tallózója ugyanezt a listát kapta, névkereső nélkül. Ha ott egy MKV nevére kattintottál, a felület mappaként próbálta megnyitni.

**A „BDEncode WSL” feladat azonnal leállt (Windows).** Egy gépen a feladatütemező által indított PowerShell nem futtatta a `%LOCALAPPDATA%\BDEncode\keepalive.ps1` szkriptet (`-File`, eredmény `0xFFFD0000`). A `-Command` és az `-EncodedCommand` ugyanott működött. Ha a feladat nem fut, a WSL és benne a BDEncode leállhat, amikor más nem használja.

## A javítások

- **Forráslista:** a `GET /api/v1/sources` legfeljebb 5000 elemet ad vissza (eddig 1000). Az új `q` paraméter a név szerinti szűrést a szerveren, a teljes mappára végzi, a korlát előtt. A válaszban új mező a `truncated` és a `total`.
- **Új munka oldal:** a névkereső a szervernek is elmegy (rövid késleltetéssel). Ha a lista csonka, a felület kiírja, hány elemből hány látszik.
- **Külső sávok tallózója:** névkeresőt kapott és csonkolási figyelmeztetést. Egy MKV nevére kattintva kiválasztja a fájlt, nem próbálja megnyitni.
- **Windows-telepítő:** az életben tartó ciklus magában a feladatban van (`-EncodedCommand`), a `keepalive.ps1` fájlt a telepítő törli.

## Ellenőrzőlista

1. `GET /api/v1/capabilities` `backend_version`: `4.1.7`.
2. A canada2 `aither` mappájában a „whale” keresés megtalálja a PENICILLIN MKV-t.
3. Windowson a „BDEncode WSL” feladat állapota `Running`.
