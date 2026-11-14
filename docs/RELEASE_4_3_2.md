# Accofil BDEncode 4.3.2 kiadási jegyzet

Javítás: egy bukott remux QC ítélete nem mentődik el, így egy újrapróbálás (például egy javított kiadás után) valóban újra mér.

## A hiba

A 4.3.1 után a The Last Whale Singer remux újraindítva is ugyanazzal a hibával állt meg („03-audio.dtsma decodes differently from the disc”). A 4.3.1 javított vizsgálata le sem futott: a QC a jelentést köztes eredményként akkor is elmentette, ha bukott volt, és az újraindítás ezt a régi, bukott jelentést olvasta vissza.

## A javítás

- A remux QC csak sikeres jelentést ment köztes eredményként. A bukottat minden újrapróbálás újra méri, azzal a kóddal, amely éppen fut.
- A köztes eredmény sémaverziója 2. A korábbi verzióval elmentett, esetleg bukott ítéletek érvénytelenek, így a már elakadt munkák is újra mérnek.

## Ellenőrzőlista

1. `GET /api/v1/capabilities` `backend_version`: `4.3.2`.
2. A Whale Singer remux QC-je újraindítás után átmegy.
