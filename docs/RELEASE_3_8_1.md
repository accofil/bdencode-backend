# BDEncode 3.8.1 kiadási jegyzet

Javítás: a Rendszer oldal lassú gépen sem mondja, hogy „a rendszerállapot nem olvasható”.

## Mi történt

A canadai szerveren egy OpenAI-kulcs mentése után a Rendszer oldal „A rendszerállapot nem olvasható” hibát mutatott. A kulcs elmentődött, a hiba három dolog együttes hatása volt:

1. **A `runtime-capabilities` végpont 26–90 másodpercig tartott.** Minden híváskor elindította az összes eszközt (ffmpeg, x264, x265, mkvmerge, vspipe…), és lemezről ellenőrizte őket. A lassú canadai lemezen ez percekig is eltarthat.
2. **A kulcsmentés újraindítja az API-t, és az újraindítás 40 másodpercig tartott,** mert az uvicorn megvárta a még futó, lassú kérést. Közben az oldal nem kapott választ.
3. **Az oldal ilyenkor eldobta a már betöltött adatokat,** és csak a hibaüzenetet mutatta.

## Javítás

- Az API az eszközök vizsgálatát indításkor a háttérben elvégzi, és az eredményt 10 percig megtartja. A régi eredményt azonnal adja, és az elévültet a háttérben frissíti.
  - A többi adat (hitelesítő adatok, szolgáltatások, tárhely) továbbra is minden híváskor friss.
  - Az eszközök csak telepítéskor változnak, és a telepítés újraindítja az API-t.
- Az API leállításakor a nyitva maradt kapcsolatokat 10 másodperc után lezárja, így egy újraindítás nem vár 30 másodpercet.
- A Rendszer oldal rövid kiesésnél megtartja az utoljára betöltött adatokat, és „Újracsatlakozás…” jelzést mutat a hibaüzenet helyett. A lap magától frissül.

## Ellenőrzőlista

1. `GET /api/v1/capabilities` `backend_version`: `3.8.1`.
2. A Rendszer oldal a canadán másodpercek alatt betöltődik.
3. Egy kulcs mentése után az oldal nem mutat hibaüzenetet, legfeljebb „Újracsatlakozás…”-t.
