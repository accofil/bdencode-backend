# BDEncode 3.7.0 kiadási jegyzet

Sávelemzés a beállítás előtt: hangsávok nyelve és a feliratok Teljes/Forced javaslata.

## Változások

- **Nincs többé találgatás a sávoknál.** A scan végén a program a javasolt playlist(ek)ből 6 rövid részletet (egyenként 30 másodperc) olvas ki a lemezről, mindegyiket egyetlen olvasással.
  - **Hangsávok:** a beszédfelismerés (faster-whisper, CPU) megállapítja a nyelvüket. A varázsló Sávok lépése mutatja: „A hang alapján: francia, 97%”. Ha ez eltér a lemez jelölésétől, sárga figyelmeztetés és **Elfogadás** gomb jelenik meg.
  - **Feliratok:** a program megszámolja a feliratok eseményeit. Percenként legalább 3 esemény esetén **Teljes felirat**, legfeljebb 1 esetén **Forced / signs** a javaslat; két azonos nyelvű felirat közül a ritkább a forced. A javaslat a kihagyott feliratoknál is látszik, így a megtartásuk előtt eldöntheted, melyik melyik.
  - A **Minden javaslat elfogadása** gomb egyszerre elfogad mindent. A program magától semmit nem állít be.
- **Mérés a La Femme Nikita UHD-lemezén** (Windows-meghajtóról, WSL alatt):
  - kb. 2 perc 45 másodperc;
  - a hangsávok francia, francia, angol (90–97%), egyezik a lemez jelölésével;
  - mindhárom felirat „Teljes”, percenként 8–10 eseménnyel.
- **Hibatűrés:** ha az elemzés nem sikerül, a scan ettől még elkészül, és a varázsló jelzi, hogy kézzel kell dönteni.
- **Kevesebb újramintázás:** egy elfogadott hangnyelvet az előkészítés már nem mintáz újra.

## Ellenőrzőlista

1. `GET /api/v1/capabilities` `backend_version`: `3.7.0`.
2. Egy új munka scanje után a „Most fut” panelen megjelenik a „Sávok elemzése” lépés, a varázsló Sávok lépésében pedig a „Sávelemzés a lemezből” doboz és a soronkénti javaslatok.

## További dokumentáció

- [BDEncode 3.6.1 kiadási jegyzet](RELEASE_3_6_1.md)
