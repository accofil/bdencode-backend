# Accofil BDEncode 4.1.5 kiadási jegyzet

Javítás: a választás előtti sávelemzés (hangnyelv, felirat típusa és nyelve) azoknál a lemezeknél is működik, amelyeknek a lejátszási listája rövid nyitóklippel kezdődik.

## A hiba

A The Experts (1989) lemeznél a varázsló ezt írta: „A sávok automatikus elemzése ennél a playlistnél nem sikerült”. Mind a 6 elemzőablak hibával állt le („Cannot determine format of input stream 0:1”). A 00004-es lejátszási lista egy 11 másodperces nyitóklippel (00010) kezdődik, mint a Taffiné. Két ok volt:

- Az elemző az ffmpeg rövid alapértelmezett vizsgálati ablakával nyitotta meg a listát. A nyitóklipben nincs hang, ezért a hangsáv formátuma ismeretlen maradt. A 4.1.1 ezt a szkennerben, a remuxban és a tervezőben már javította, az elemzőben nem.
- A hosszabb vizsgálati ablakkal a parancs lefutott, de üres hangot adott. A libbluray a klipeket nem folytonos időbélyegekkel fűzi össze: a nyitóklip 600–611 s, a fő klip újra 600 s-tól indul. Így a listán belüli időugrás (seek) nem talált semmit.

## A javítás

- Lemezforrásnál minden elemzőablakot abból a klipfájlból olvas, amelyikbe az ablak kezdete esik. A tekerés a klip saját időbélyegeivel történik (`-seek_timestamp`), az ablak legfeljebb a klip végéig tart, a sávokat pedig a klip saját indexei alapján választja ki (PID szerint, klipenként egyszer lekérdezve).
- Ha a klip nem azonosítható vagy nem létezik, marad a lejátszási listás olvasás, most már hosszú vizsgálati ablakkal.
- Az elemzés sémaverziója 3. Egy már szkennelt, lemezválasztásra váró munka nem szkennel újra (az újraindítás a választóhoz viszi vissza); a javított elemzéshez új munkát kell indítani ugyanarról a forrásról.
- Élesben a The Experts lemezen: mind a 6 ablak beolvasva 15 s alatt, 6 × 30 s hang, a felirat „teljes” típusú (23,7 esemény/perc), OCR-rel angol (0,91).

## Ellenőrzőlista

1. `GET /api/v1/capabilities` `backend_version`: `4.1.5`.
2. A The Experts lemezről indított új munkánál a varázsló hangnyelvet és felirattípust javasol.
