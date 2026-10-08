/**
 * Built-in help for the selectable x264/x265 settings.
 *
 * Compiled from the Aither forum (encode reviews, guides and the encode
 * approval checklist), nCore's wiki and the Hungarian release standard it
 * points to (github.com/encoding-hun/rules-and-standards), the Silent
 * Aperture encoding guide, the x265
 * documentation and the x264 settings reference; values are starting points
 * that a test encode of the actual source confirms or corrects.
 */

export type HelpEncoder = "x264" | "x265";

export interface EncoderHelpEntry {
  field: string;
  title: string;
  encoders: HelpEncoder[];
  /** What the setting does. */
  what: string;
  /** Effect on quality, size and speed. */
  effect?: string;
  /** Range, default and the usual values. */
  values?: string;
  grain?: string;
  clean?: string;
  animation?: string;
  /** What experienced Aither encoders use. */
  aither?: string;
  /** nCore and the Hungarian release standard (encoding-hun) it points to. */
  ncore?: string;
  caution?: string;
}

export interface HelpSection {
  id: string;
  title: string;
  paragraphs: string[];
}

export const HELP_SOURCES: Array<{ title: string; url?: string; note: string }> = [
  { title: "Aither – Guides fórum", note: "Ether's Encoding Scratchpad, Comprehensive Beginner's Guide to Video Encoding, Guide to Encoding Dolby Vision Content (bejelentkezés szükséges)" },
  { title: "Aither – Release Review és Release Help", note: "kódolások bírálatai: Demolition Man UHD DV x265, Mona Lisa and the Blood Moon 1080p x264, x265 performance comparison" },
  { title: "Aither – szabályzat, slotok, elnevezés, összehasonlítás", url: "https://aither.cc/pages/1", note: "Rules, Slots, Naming Guide, Video Comparisons Guide, Screenshots" },
  { title: "Silent Aperture – Advanced Encoding Guide", url: "https://silentaperture.gitlab.io/mdbook-guide/encoding/x264.html", note: "x264 és x265 beállítások, tesztelési módszertan" },
  { title: "nCore Wiki – Feltöltési szabályok, Dupe szabályzat, Torrent nevének helyes megadása", note: "film-, hang- és felirat-szabályok, 1080p/2160p hangformátumok, minta és tech infó (bejelentkezés szükséges)" },
  { title: "Magyar release-szabványok (encoding-hun)", url: "https://github.com/encoding-hun/rules-and-standards", note: "x264 HD és x265 UHD-HD szabályok, nuke-indokok; erre mutat az nCore Wiki a megfelelő minőséghez" },
  { title: "x265 dokumentáció", url: "https://x265.readthedocs.io/en/master/cli.html", note: "a kapcsolók pontos jelentése és alapértékei" },
  { title: "MeGUI x264 Settings (Wikibooks)", url: "https://en.wikibooks.org/wiki/MeGUI/x264_Settings", note: "az x264 kapcsolók leírása" },
  { title: "JET Encoding Guide", url: "https://jaded-encoding-thaumaturgy.github.io/JET-guide/master/", note: "VapourSynth-alapú munkafolyamat, szűrés, összehasonlítás" },
];

export const HELP_SECTIONS: HelpSection[] = [
  {
    id: "ncore",
    title: "nCore és a magyar release-szabvány",
    paragraphs: [
      "Az nCore Wiki a „megfelelő minőséghez” a magyar release-szabványra (encoding-hun) mutat; ezt a magyar csapatok aláírták. A BDEncode nCore-profilja ezek alapján dolgozik: a bitstream-előírásokat (level, high tier, HRD, VBV, limit-refs, lookahead-slices, x264-nél a legnagyobb ref) automatikusan beállítja, a minőségi minimumoknál (B-frame, merange, subme, psy) figyelmeztet.",
      "Videó: SDR anyag csak x264 lehet, x265 csak HDR/DV-hez (2160p mindig x265). Tonemapping és darabolt kódolás tilos. Egy filmből csak egy minőségi encode lehet fent; a BluRay-forrású 1080p SDR és 2160p HDR anyagot csak összehasonlító képekkel lehet lecserélni. A DV.HDR akkor előzi meg a sima HDR-t, ha a Dolby Vision metaadatban 10-nél több különböző L1 érték van.",
      "Hang: 1080p-n TrueHD és DTS-HD MA nem lehet (csak AAC 2.0, AC3, E-AC3, DTS, FLAC 2.0) – a BDEncode ilyenkor E-AC3 5.1-et (1024 kbps) javasol; 7.1-es E-AC3-at FFmpeg-gel nem lehet készíteni. DTS, TrueHD és DTS-HD mellé DD@640 (2.0-nál DD@256) kompatibilitási sáv kell. Sorrend: magyar (első, alapértelmezett), eredeti, angol, kommentár; más nyelv nem lehet. Legfeljebb 16 sáv.",
      "Felirat: forced csak olyan nyelven, amilyen szinkron van. Sorrend: magyar forced, magyar, magyar SDH, eredeti forced, eredeti, eredeti SDH. A magyar szabvány SRT-t kér (x264 HD-nél PGS nem is mehet), az nCore Wiki ezt nem írja elő.",
      "Feltöltés: nem eredeti release-nél a torrent neve a magyar cím + felbontás (+ HDR/DV), szóközökkel, például „A függetlenség napja 2160p DV HDR”. Pontosan 3 kép kell az encode felbontásában, 2 GB felett legalább 1 perces minta (UHD-nál legalább 200 MB), a tech infó MediaInfo TEXT kimenet a kódolási beállításokkal.",
    ],
  },
  {
    id: "content",
    title: "Szemcsés, tiszta vagy animáció?",
    paragraphs: [
      "Szemcsés film: régebbi, filmre forgatott anyag látható, mozgó filmszemcsével. Itt a cél a szemcse megtartása: SAO és erős simítás ki, erősebb pszichovizuális beállítások (psy-rd, psy-rdoq), negatív deblock (-3:-3), x264-nél mbtree nélkül. Az ilyen kódolás nagyobb lesz: átlátszó UHD-nél a remux 40–80%-a is lehet.",
      "Tiszta, digitális film: modern digitális kamera, kevés zaj, sima felületek. A fő veszély a sávosodás (banding) és a sötét jelenetek bitszegénysége. Itt mbtree/cutree bekapcsolva jól spórol, az AQ erőssége kicsit magasabb, a psy-értékek mérsékeltebbek, a deblock kevésbé negatív (-2:-2…0:0).",
      "Animáció: éles kontúrok, nagy egyszínű felületek. Alacsonyabb psy-rd (gyűrődés ellen), enyhébb deblock (0:0…-1:-1), AQ 0,6–0,7, sok B-frame.",
      "A végső értéket mindig a konkrét forrás próbakódolása dönti el: azonos méretre kódolt változatokat B-frame–B-frame képpárokon hasonlítanak össze, sötét, világos, mozgalmas és statikus jelenetekből.",
    ],
  },
  {
    id: "rate",
    title: "CRF, méret és sebesség",
    paragraphs: [
      "A CRF a minőséget rögzíti, a méret a forrástól függ. Egy CRF-lépés nagyjából 12–21% méretváltozást jelent (UHD-n a BDEncode mérése szerint kb. 17–21%). Az x264 és az x265 CRF-skálája nem összehasonlítható.",
      "Az Aither 1080p x264-nél két slotot tart: Quality (átlátszó, nagyobb, jellemzően a remux 45–60%-a) és Retention (helytakarékos). 20%-nál kisebb méretkülönbségnél a két kódolás ugyanazért a slotért versenyez. 2160p-n csak x265 kódolás lehet, SDR, HDR/DV és HDR10+ külön slotban; a DV/HDR előnyt élvez a sima HDR-rel szemben.",
      "A preset a sebesség és a tömörítési hatékonyság közti cserét állítja. Aither-kódolók x264-nél veryslow/placebo, x265 UHD-nél a gépidő miatt slow/slower/veryslow presetet használnak, és utána a fontos kapcsolókat kézzel állítják be.",
    ],
  },
  {
    id: "aither",
    title: "Aither-szabályok röviden",
    paragraphs: [
      "Hang: csak az eredeti nyelvű fő sáv és opcionálisan egy angol sáv; kommentár, izolált zene és történeti sáv megengedett. Minden TrueHD mellé kötelező egy külön DD vagy DD+ kompatibilitási sáv. Ha a fő hang nem angol és nincs angol szinkron, angol felirat kötelező.",
      "Név: Cím Év Felbontás Forrás Hangkodek Csatornák [Atmos] [HDR-típus] Videókodek-Csoport, például „Film 1990 2160p UHD BluRay DTS-HD MA 5.1 DV HDR x265-Csoport”. Nyelvi tag csak akkor kell, ha nincs angol hang; eredeti hang és angol szinkron együtt: Dual-Audio.",
      "Leírás: 3–9 PNG-képernyőkép a kész fájl felbontásában, 350 px-es bélyegképpel, MediaInfo és a kódolási beállítások. Saját kódolásnál (PR) kötelező az x264/x265 napló és a forrás–kódolás összehasonlítás; ha a slot foglalt, a meglévő kódolással is.",
      "Összehasonlítás: ugyanaz a képkocka minden forrásból, PNG, B-frame (ha nincs, P-frame; I-frame-et kerülni), legalább 10 kép a teljes hosszon, vegyes jelenetekből, a [comparison=Source, Encode] BBCode-dal.",
      "Torrent (ezt te készíted, a BDEncode 3.0-tól nem): privát, v1, csak a videófájl; darabméret: 1 GB alatt 1 MiB, 1–4 GB 2 MiB, 4–12 GB 4 MiB, 12–20 GB 8 MiB, 20 GB felett 16 MiB.",
    ],
  },
];

export const ENCODER_HELP: EncoderHelpEntry[] = [
  {
    field: "crf",
    title: "CRF minőség",
    encoders: ["x264", "x265"],
    ncore: "Csak CRF vagy 2-pass megengedett; a bitráta nem lehet nagyobb a forrásénál, a kép legyen transzparens. Az mHD/HDLight-szerű bitszegény encode-ok tilosak.",
    what: "Állandó minőségi cél: a kódoló a kép bonyolultságához igazítja a bitrátát.",
    effect: "Alacsonyabb érték: jobb kép, nagyobb fájl. Egy lépés kb. 12–21% méretváltozás.",
    values: "x264 1080p: Quality slotban jellemzően 15–18 (például 16,5). x265 UHD: 16–20 (szemcsés anyagnál inkább 15–18, tiszta anyagnál 18–20).",
    aither: "Az Aither-bírálók a CRF-et a forráshoz hangolják; a beállítások összevetését azonos méreten (kétmenetes kódolással vagy méretcéllal) javasolják, mert a CRF önmagában nem mond semmit a minőségről.",
    caution: "Az x264 és az x265 CRF-értéke nem összevethető. A BDEncode automatikus CRF-keresése VMAF- vagy méretcélra is be tudja állítani.",
  },
  {
    field: "preset",
    title: "Preset",
    encoders: ["x264", "x265"],
    ncore: "Szegmentált (darabolt) kódolás és GPU-kódolás tilos; x264 legalább r3000, x265 legalább 3.3.",
    what: "Előre beállított kapcsolócsomag a sebesség és a tömörítési hatékonyság között.",
    effect: "Lassabb preset: azonos minőség kisebb méretben, de jóval hosszabb kódolás. A BDEncode a kézzel megadott kapcsolókat a preset után alkalmazza, azok felülírják a preset értékeit.",
    values: "x264: veryslow vagy placebo. x265 UHD: slow, slower, ha az idő engedi veryslow. UHD-n slow presettel egy film kb. egy nap.",
    aither: "x264-nél a placebo/veryslow az alap, x265 UHD-nél a gépidő miatt gyakori a slow/slower kézi kiegészítésekkel.",
  },
  {
    field: "tune",
    title: "Tartalmi hangolás",
    encoders: ["x264", "x265"],
    what: "Kész beállításcsomag egy tartalomtípushoz (film, grain, animation stb.).",
    effect: "A grain hangolás erősen szemcsemegtartó, de gyakran túl nagy fájlt ad; az animation enyhébb psy-t és erősebb deblockot állít.",
    values: "Javaslat: none (vagy film), és a fontos kapcsolók kézi beállítása.",
    aither: "A tapasztalt kódolók nem használnak tune-t, a kapcsolókat egyenként állítják.",
  },
  {
    field: "profile",
    title: "Profil",
    encoders: ["x264", "x265"],
    what: "A bitstream kódolási profilja (High, Main10…). A forrásból és a kimenetből következik, ezért zárolt.",
    values: "1080p SDR x264: High (8 bit). UHD HDR x265: Main10.",
  },
  {
    field: "level",
    title: "Dekóderszint",
    encoders: ["x264"],
    ncore: "x264 1080p: level 4.1 (30 fps felett 4.2), High profil. x265 2160p: level 5.1 (30 fps felett 5.2) high tierrel – nCore-profilnál automatikus.",
    what: "H.264-szint, amely a referenciaképek számát és a bitrátát a lejátszók képességeihez köti.",
    values: "1080p-n 4.1. A BDEncode SDR x264 kimenetnél automatikusan alkalmazza.",
    aither: "Az Aither x264-sablonokban --level 4.1 szerepel; emiatt 1080p-n legfeljebb 4 referenciakép lehet.",
  },
  {
    field: "bit_depth",
    title: "Bitmélység",
    encoders: ["x264", "x265"],
    ncore: "x264 csak 8 bites lehet; x265 2160p SDR csak 8, HDR csak 10 bites. Tonemapping (HDR→SDR) tilos.",
    what: "A kimenet bitmélysége; a forrásból következik és zárolt (HDR: 10 bit).",
  },
  {
    field: "pixel_format",
    title: "Pixelformátum",
    encoders: ["x264", "x265"],
    what: "A kimenet pixelformátuma (yuv420p, yuv420p10le); a forrásból következik és zárolt.",
  },
  {
    field: "color",
    title: "Színtér",
    encoders: ["x264", "x265"],
    what: "Színalapok, átviteli függvény, mátrix és tartomány. A lemezről olvasott értékek, csak hiányzó adatnál kell jóváhagyni.",
  },
  {
    field: "hdr10",
    title: "HDR10 metaadat",
    encoders: ["x265"],
    what: "Statikus HDR10 metaadat (mastering display, MaxCLL/MaxFALL) a lemezről.",
    caution: "Dolby Visionnél a HDR10 metaadatnak egyeznie kell az RPU-val; a BDEncode a lemez adatait viszi át.",
  },
  {
    field: "vbv",
    title: "VBV korlátozás",
    encoders: ["x264", "x265"],
    ncore: "x264: maxrate 50000–62500, bufsize 50000–78125. x265: mindkettő 100000–160000; nCore-profilnál a BDEncode 160000/160000-et állít be.",
    what: "Bitráta-plafon és puffer; a lejátszók kompatibilitását szolgálja.",
    effect: "Fájlba kódolásnál általában nem kell. Túl alacsony plafon a bonyolult jelenetek minőségét rontja.",
    aither: "Néhány UHD DV kódoló 160 000 kb/s-os VBV-t használ, mert egyes eszközök (és a staxrip) igénylik; nem kötelező.",
  },
  {
    field: "keyint",
    title: "Maximális GOP-hossz",
    encoders: ["x264", "x265"],
    ncore: "Legfeljebb FPS×20 (FPS×10 ajánlott; a BDEncode 10 másodpercet használ), x264-nél legalább FPS×5.",
    what: "Két kulcskép közti legnagyobb távolság képkockában.",
    effect: "Hosszabb GOP: kisebb fájl, lassabb tekerés.",
    values: "A BDEncode a képkockasebességből állítja be (kb. 10 másodperc, 23,976 fps-nél 240). Aither x264-sablon: 250.",
  },
  {
    field: "min_keyint",
    title: "Minimális GOP-hossz",
    encoders: ["x264", "x265"],
    ncore: "FPS/2 és FPS×2 között; FPS (1 másodperc) az ajánlott – a BDEncode ezt használja.",
    what: "Ennél közelebb nem kerül új IDR-kulcskép; az ennél közelebbi jelenetváltás sima I-frame lesz.",
    values: "Kb. 1 másodperc (23–24).",
  },
  {
    field: "scenecut",
    title: "Jelenetváltás-érzékenység",
    encoders: ["x264", "x265"],
    what: "Mennyire hajlamos a kódoló jelenetváltásnál kulcsképet beszúrni.",
    values: "Alapérték 40; ritkán kell változtatni.",
  },
  {
    field: "open_gop",
    title: "Nyitott GOP",
    encoders: ["x264", "x265"],
    what: "Engedi, hogy a kulcskép utáni B-frame-ek az előző GOP-ra hivatkozzanak (nem IDR I-frame-ek).",
    effect: "Kicsit jobb tömörítés, de rosszabb vágás és tekerés; a fejezetek IDR-képre tétele zárt GOP-pal megbízható.",
    values: "Aither x264: kikapcsolva. x265-nél a bevett gyakorlat a bekapcsolt nyitott GOP, de a fejezetek elejére a BDEncode IDR-képet kényszerít.",
  },
  {
    field: "bframes",
    title: "B-framek száma",
    encoders: ["x264", "x265"],
    ncore: "x264: legalább 5, x265: legalább 4 egymás utáni B-frame; kikapcsolni tilos.",
    what: "Legfeljebb ennyi B-frame jöhet egymás után.",
    effect: "Több B-frame: jobb tömörítés, lassabb kódolás. Az x264 naplóban a „consecutive B-frames” sor utolsó értéke legyen 5% alatt, de ne essen 1% alá.",
    values: "x264: 16 (Aither). x265: 8–16.",
    animation: "Animációnál sok B-frame különösen hasznos.",
  },
  {
    field: "b_adapt",
    title: "Adaptív B-frame",
    encoders: ["x264", "x265"],
    what: "Hogyan dönt a kódoló a B-frame-ek elhelyezéséről (2 = trellis, a legjobb).",
    values: "2.",
  },
  {
    field: "b_pyramid",
    title: "B-piramis",
    encoders: ["x264", "x265"],
    what: "B-frame-eket is használhat referenciaként.",
    values: "Bekapcsolva (x264: normal).",
  },
  {
    field: "ref",
    title: "Referenciaképek",
    encoders: ["x264", "x265"],
    ncore: "x264: kötelező a level 4.1 szerinti legnagyobb ref (1920×1080: 4, 1920×800: 5) – nCore-profilnál a BDEncode automatikusan beállítja. x265: 4–6 (1080p-n 6); level 5.1-nél teljes 3840×2160-on B-piramissal legfeljebb 5.",
    what: "Hány korábbi képre hivatkozhat a mozgásbecslés.",
    effect: "Több referencia: jobb tömörítés, lassabb kódolás, nagyobb memóriaigény.",
    values: "x264 1080p, level 4.1: legfeljebb 4. x265: 4–6.",
    aither: "x264-nél ref 4 (a 4.1-es szint miatt), x265-nél jellemzően 4.",
  },
  {
    field: "rc_lookahead",
    title: "Előretekintés",
    encoders: ["x264", "x265"],
    ncore: "x264: legalább az FPS kétszerese, x265: legalább az FPS.",
    what: "Hány jövőbeli képkockát elemez a frame-típus döntéshez és az mbtree/cutree-hez.",
    effect: "Több előretekintés: jobb döntések, több memória.",
    values: "x264 mbtree-vel: 250, mbtree nélkül 60 is elég. x265: 40–80 (gyakori a 60 és a 80).",
  },
  {
    field: "weightp",
    title: "Súlyozott P-predikció",
    encoders: ["x264", "x265"],
    ncore: "x265: a weightp kötelező, a weightb ajánlott.",
    what: "Fényerőváltozásoknál (áttűnés, villanás) súlyozott előrejelzés a P-frame-ekben.",
    values: "x264: 2 (smart). x265: bekapcsolva.",
  },
  {
    field: "weightb",
    title: "Súlyozott B-predikció",
    encoders: ["x264", "x265"],
    what: "Súlyozott előrejelzés a B-frame-ekben.",
    values: "Bekapcsolva.",
  },
  {
    field: "me",
    title: "Mozgásbecslési mód",
    encoders: ["x264", "x265"],
    ncore: "x264-nél csak umh, esa vagy tesa elfogadott.",
    what: "Az egész pixeles mozgáskeresés módszere.",
    effect: "Alaposabb mód: jobb mozgáskövetés, lassabb kódolás.",
    values: "x264: umh. A tesa ritkán éri meg: elmozdítja a szemcsemintát, látható nyereség nélkül. x265: umh vagy star (a minőségi UHD-kódolásokban gyakori a star).",
  },
  {
    field: "merange",
    title: "Keresési tartomány",
    encoders: ["x264", "x265"],
    ncore: "x264: legalább 24, x265: legalább 32.",
    what: "Hány pixeles körzetben keres mozgást a kódoló.",
    values: "x264 1080p: 24–32. x265: 57 (az alapérték), legalább 32.",
  },
  {
    field: "subme",
    title: "Részpixeles finomság",
    encoders: ["x264", "x265"],
    ncore: "x264: legalább 8, x265: legalább 3.",
    what: "A mozgásvektorok részpixeles finomítása és a módválasztás alapossága.",
    effect: "Magasabb érték: jobb minőség, lassabb kódolás.",
    values: "x264: 10–11 (11 a legalaposabb, nagyon lassú). x265: 4–5; a 7 élesíthet.",
  },
  {
    field: "trellis",
    title: "Trellis",
    encoders: ["x264"],
    what: "Rate-distortion alapú kvantálás.",
    values: "2 (minden döntésnél).",
  },
  {
    field: "partitions",
    title: "Partíciók",
    encoders: ["x264"],
    what: "Mely makroblokk-felosztásokat vizsgálja az x264.",
    values: "all.",
  },
  {
    field: "direct",
    title: "Direkt predikció",
    encoders: ["x264"],
    what: "A B-frame-ek direkt mozgásvektor-előrejelzési módja.",
    values: "auto.",
  },
  {
    field: "aq_mode",
    title: "AQ mód",
    encoders: ["x264", "x265"],
    ncore: "Az adaptív kvantálás kötelező (x264: 3 ajánlott, x265: 3 vagy 4 ajánlott).",
    what: "Adaptív kvantálás: a képen belül átcsoportosítja a biteket a sík és a részletes területek között.",
    values: "x264: 3 (sötét jelenetek felé hangolt auto-variance). x265: 2 (auto-variance), 3 (sötét jelenetek felé) vagy 4 (élérzékeny).",
    aither: "x264-nél 3. x265 UHD-n gyakori a 2 (0,8 erősséggel) vagy a 4 (1,0 erősséggel).",
    caution: "Ha a sötét jelenetek bitszegények, a 3-as mód és egy kicsit nagyobb erősség segít.",
  },
  {
    field: "aq_strength",
    title: "AQ erősség",
    encoders: ["x264", "x265"],
    what: "Az adaptív kvantálás ereje.",
    effect: "Nagyobb érték: több bit a sima és sötét területekre (kevesebb sávosodás), kevesebb a részletes területekre.",
    values: "x264: 0,7–0,85. x265: 0,8–1,0 (2-es és 3-as mód), 4-es módnál 0,5–1,0.",
    grain: "Apró szemcsénél 0,8–0,85, durva szemcsénél 0,7–0,75 (x264).",
    clean: "0,8 körül; sávosodásnál egy kicsit feljebb.",
    animation: "0,6–0,7, a torzuló kontúrok elkerülésére.",
    aither: "Az Aither-bírálók tipikus tanácsa: ha a sötét jelenetek bitszegények, emeld kicsit az AQ erősségét, és csökkentsd kicsit az ip/pb arányt.",
  },
  {
    field: "qcomp",
    title: "Kvantálási görbe",
    encoders: ["x264", "x265"],
    what: "Mennyire kapjanak a bonyolult (mozgalmas) jelenetek több bitet a nyugodtakhoz képest.",
    values: "x264 mbtree nélkül 0,60–0,70, mbtree-vel 0,70–0,85. x265: 0,6–0,7.",
    caution: "Ok nélkül ne állítsd: a legtöbbször az AQ erőssége a jobb eszköz. Az alacsonyabb qcomp-pal való méretspórolás gyakran visszafelé sül el.",
  },
  {
    field: "mbtree",
    title: "Macroblock-tree (mbtree)",
    encoders: ["x264"],
    what: "Az előretekintés alapján csökkenti a biteket azokon a területeken, amelyekre később kevés kép hivatkozik.",
    effect: "Sík, tiszta anyagnál nagy megtakarítás; szemcsés anyagnál rombolja a szemcsét.",
    grain: "Kikapcsolva (qcomp 0,6).",
    clean: "Bekapcsolva, qcomp 0,7–0,85 mellett, nagy előretekintéssel.",
    aither: "Az Aither x264-sablonokban gyakori a --no-mbtree.",
  },
  {
    field: "cutree",
    title: "CU-tree (cutree)",
    encoders: ["x265"],
    what: "Az x264 mbtree-jének x265-ös megfelelője: az előretekintés alapján osztja el a QP-t.",
    effect: "Tiszta anyagnál spórol; szemcsés anyagnál a háttér szemcséjét elsimíthatja.",
    grain: "Gyakran kikapcsolják (például több elismert, szemcsés UHD-kódolásban).",
    clean: "Bekapcsolva.",
    caution: "Az útmutatók megosztottak; a forrás próbakódolása dönt.",
  },
  {
    field: "psy_rd",
    title: "Psy-RD",
    encoders: ["x264", "x265"],
    ncore: "x265-nél a psy-rd és a psy-rdoq kikapcsolása tilos.",
    what: "Pszichovizuális optimalizálás: a forrás „energiáját” (textúráját, szemcséjét) őrzi meg akkor is, ha ez a mérőszámok szerint torzítás.",
    effect: "Magasabb érték: élesebbnek, részletesebbnek ható kép, kicsit nagyobb fájl; túl magas érték gyűrődést (ringing) és műtermékeket okoz. A PSNR/SSIM/VMAF értékeket rontja, a látott minőséget javítja.",
    values: "x264: élőszereplős anyagnál 0,95–1,10. x265: 1,0–2,5.",
    grain: "x265: 1,8–2,5.",
    clean: "x264: 1,0. x265: 1,0–1,5.",
    animation: "x264: 0,6–0,9; x265-nél is alacsonyabb érték.",
  },
  {
    field: "psy_rdoq",
    title: "Psy-RDOQ / psy-trellis",
    encoders: ["x264", "x265"],
    ncore: "x265-nél a psy-rdoq kikapcsolása tilos.",
    what: "x265-nél a kvantálás pszichovizuális erőssége; x264-nél ugyanez a mező a psy-trellis értéke (a psy-rd második tagja).",
    effect: "x265: magasabb érték több szemcsét és textúrát tart meg, nagyobb fájllal; túl magas érték műtermékeket okoz.",
    values: "x265: 0–2 (szemcsés anyagnál 1,0–1,25, tiszta anyagnál 0,5–1,0). x264 (psy-trellis): mindig 0.",
  },
  {
    field: "deblock_alpha",
    title: "Deblock (erősség)",
    encoders: ["x264", "x265"],
    ncore: "A deblock kikapcsolása tilos; filmhez -3:-3 az ajánlott.",
    what: "A blokkosodásszűrő ereje (az első érték). Negatív érték: kevesebb simítás, több részlet.",
    values: "Élőszereplős anyag: -3…-1. Animáció: -2…0.",
    grain: "-3:-3 (az Aither-kódolók kiindulópontja).",
    clean: "-2:-2…0:0, tesztelve.",
    animation: "0:0…-1:-1.",
    aither: "x264-nél a -3:-3 a kiindulópont; ritkán jobb a -4:-4, a 0:0 csak animációnál jön szóba.",
  },
  {
    field: "deblock_beta",
    title: "Deblock (küszöb)",
    encoders: ["x264", "x265"],
    what: "A blokkosodásszűrő küszöbe (a második érték). Általában az első értékkel együtt mozog (-3:-3, -2:-2).",
  },
  {
    field: "chroma_qp_offset",
    title: "Chroma QP eltérés",
    encoders: ["x264"],
    what: "A színcsatornák kvantálásának eltérése a fényességhez képest. Negatív érték: több bit a színre.",
    values: "Jellemzően -2…-1. Az x264 a psy-rd miatt maga is módosítja; a kijelzett érték a ténylegesen alkalmazott.",
  },
  {
    field: "cbqpoffs",
    title: "Chroma Cb QP eltérés",
    encoders: ["x265"],
    what: "A kék-sárga színcsatorna kvantálásának eltérése a fényességhez képest.",
    values: "4:2:0 anyagnál -3…0; alapérték 0. Negatív érték jobb színrészletet ad nagyobb fájllal.",
  },
  {
    field: "crqpoffs",
    title: "Chroma Cr QP eltérés",
    encoders: ["x265"],
    what: "A vörös-zöld színcsatorna kvantálásának eltérése a fényességhez képest.",
    values: "4:2:0 anyagnál -3…0; alapérték 0. Vörös felületeken (ahol a kódolók gyengébbek) segíthet.",
  },
  {
    field: "ipratio",
    title: "I/P arány",
    encoders: ["x264", "x265"],
    what: "Mennyivel jobb minőséget kapjanak az I-frame-ek a P-frame-eknél.",
    values: "Alapérték 1,40.",
    aither: "Ha a sötét jelenetek bitszegények, az Aither-bírálók az ip/pb arány kis csökkentését javasolják (például 1,30/1,20).",
  },
  {
    field: "pbratio",
    title: "P/B arány",
    encoders: ["x264", "x265"],
    what: "Mennyivel jobb minőséget kapjanak a P-frame-ek a B-frame-eknél.",
    values: "Alapérték 1,30. Kisebb érték: jobb B-frame-ek, nagyobb fájl.",
  },
  {
    field: "fast_pskip",
    title: "Gyors P-skip",
    encoders: ["x264"],
    what: "Korai döntés a P-frame-ek kihagyható blokkjairól.",
    effect: "Gyorsít, de sötét és sík területeken blokkosodást okozhat.",
    values: "Minőségi kódolásnál kikapcsolva (--no-fast-pskip).",
  },
  {
    field: "dct_decimate",
    title: "DCT-tizedelés",
    encoders: ["x264"],
    what: "Elhagyja a jelentéktelennek ítélt együtthatókat.",
    effect: "Kisebb fájl, de a finom szemcse és a sík felületek finom átmenetei sérülhetnek.",
    values: "Minőségi kódolásnál kikapcsolva (--no-dct-decimate).",
  },
  {
    field: "noise_reduction",
    title: "Zajcsökkentés",
    encoders: ["x264", "x265"],
    what: "A kódoló saját zajcsökkentése (x264 nr, x265 nr-intra/nr-inter).",
    effect: "Kisebb fájl, de a kódolás nem lesz átlátszó: a szemcse és a finom részlet elveszik.",
    values: "0 (kikapcsolva).",
    aither: "Csak akkor szokás zajt csökkenteni, ha a forrás egyáltalán nem tömöríthető; ezt a leírásban jelezni kell.",
  },
  {
    field: "sao",
    title: "SAO",
    encoders: ["x265"],
    ncore: "A magyar szabvány az SAO kikapcsolását ajánlja (--no-sao --selective-sao 0).",
    what: "Sample Adaptive Offset szűrő: a kódolás után simítja a kép egyes részeit.",
    effect: "A finom részletet és a szemcsét elkeni.",
    values: "Élőszereplős anyagnál szinte mindig kikapcsolva (--no-sao). Csak erős gyűrődésnél érdemes visszakapcsolni.",
    aither: "Az Aither UHD-kódolásaiban szinte mindig no-sao.",
  },
  {
    field: "limit_sao",
    title: "Korlátozott SAO",
    encoders: ["x265"],
    what: "A SAO korlátozott (gyorsabb) változata; kikapcsolt SAO mellett nincs hatása.",
  },
  {
    field: "strong_intra_smoothing",
    title: "Erős intra simítás",
    encoders: ["x265"],
    what: "32×32-es intra blokkok erős simítása.",
    grain: "Kikapcsolva: éles, szemcsés anyagon elkeni a részletet.",
    clean: "Lágy, homályos képnél bekapcsolva maradhat.",
  },
  {
    field: "rect",
    title: "Négyszögletes partíciók",
    encoders: ["x265"],
    what: "Nem négyzetes mozgáspartíciók vizsgálata.",
    effect: "Kicsit jobb tömörítés, lassabb kódolás.",
    values: "Minőségi kódolásnál bekapcsolva.",
  },
  {
    field: "amp",
    title: "Aszimmetrikus partíciók",
    encoders: ["x265"],
    what: "Aszimmetrikus (75/25) partíciók; a négyszögletes partíciókra épül.",
    effect: "Kis nyereség jelentős lassulással.",
    values: "Gyakran kikapcsolva; gyors gépen bekapcsolható.",
  },
  {
    field: "early_skip",
    title: "Korai skip",
    encoders: ["x265"],
    ncore: "x265: az early-skip bekapcsolása tilos (a split-rd-skip, tskip-fast és frame-dup sem lehet bekapcsolva).",
    what: "Ha egy blokk egyszerű összevonással maradék nélkül kódolható, a többi módot nem vizsgálja.",
    effect: "Gyorsít, kevés részletvesztéssel.",
    values: "Minőségi kódolásnál kikapcsolva (no-early-skip).",
  },
  {
    field: "rskip",
    title: "Rekurzív skip",
    encoders: ["x265"],
    what: "Korai kilépés a CU-rekurzióból (1 = szomszédsági heurisztika, 2 = élsűrűség).",
    values: "A legjobb minőséghez 0; az Aither-kódolásokban az 1 is gyakori.",
  },
  {
    field: "tu_intra_depth",
    title: "TU-mélység (intra)",
    encoders: ["x265"],
    what: "A transzformációs egységek további felosztása intra blokkokban.",
    effect: "Nagyobb mélység: finomabb részlet, lassabb kódolás.",
    values: "1–4; az Aither UHD-kódolásaiban 3–4.",
  },
  {
    field: "tu_inter_depth",
    title: "TU-mélység (inter)",
    encoders: ["x265"],
    what: "A transzformációs egységek további felosztása inter blokkokban.",
    values: "1–4; az Aither UHD-kódolásaiban 3–4.",
  },
  {
    field: "limit_tu",
    title: "TU-korlát",
    encoders: ["x265"],
    what: "Korai kilépés a transzformációs fa vizsgálatából a szomszédos blokkok alapján.",
    values: "0 (nincs korlát) a legjobb minőséghez; 4 a leggyorsabb.",
  },
  {
    field: "rd",
    title: "RD-szint",
    encoders: ["x265"],
    ncore: "x265: legalább 3.",
    what: "A rate-distortion alapú módválasztás alapossága.",
    effect: "Magasabb szint: kisebb fájl azonos minőségen, lassabb kódolás.",
    values: "3–4 (a slow preset 4); ha az idő engedi, akár 6.",
  },
  {
    field: "rdoq_level",
    title: "RDOQ-szint",
    encoders: ["x265"],
    what: "Rate-distortion optimalizált kvantálás (0 = ki, 1 = együtthatók, 2 = a tizedelési döntésekkel együtt).",
    values: "2.",
  },
  {
    field: "b_intra",
    title: "Intra a B-frame-ekben",
    encoders: ["x265"],
    what: "Intra módokat is vizsgál a B-frame-ekben.",
    values: "A preset szerint; a minőségi kódolások vegyesen használják.",
  },
  {
    field: "max_merge",
    title: "Összevonási jelöltek",
    encoders: ["x265"],
    ncore: "x265: legalább 2.",
    what: "Hány térbeli/időbeli összevonási jelöltet vizsgál a kódoló.",
    values: "3–5 (a több jobb, lassabb).",
  },
  {
    field: "limit_refs",
    title: "Referencia-korlátozás (limit-refs)",
    encoders: ["x265"],
    what: "Mennyire szűkítse a referenciakeresést a kisebb blokkok döntései alapján: 0 = nincs korlát (leglassabb, legjobb), 3 = mindkét korlát (a slow preset alapértéke).",
    effect: "Kisebb érték: alaposabb mozgásbecslés, lassabb kódolás.",
    values: "0–3; preset szerint 3 (slow), 2 (slower), 1 (veryslow), 0 (placebo).",
    ncore: "Legfeljebb 2, ha a rect és az amp is be van kapcsolva, különben legfeljebb 1. nCore-profilnál a BDEncode ezt állítja be.",
  },
  {
    field: "lookahead_slices",
    title: "Előretekintési szeletek",
    encoders: ["x265"],
    what: "Hány szeletre bontja a lookahead a képet a párhuzamos elemzéshez.",
    effect: "Több szelet: gyorsabb, de pontatlanabb képtípus- és bitráta-döntés.",
    values: "0–16; 0 vagy 1 = nincs szeletelés.",
    ncore: "2160p-n legfeljebb 4, 1080p-n legfeljebb 2. nCore-profilnál automatikus.",
  },
  {
    field: "hrd",
    title: "HRD-paraméterek",
    encoders: ["x265"],
    what: "A VBV-adatok (Hypothetical Reference Decoder) beírása a bitstreambe; VBV nélkül nem használható.",
    values: "Be/ki; a képminőségre nincs hatása.",
    ncore: "Kötelező; nCore-profilnál automatikus (a 160000/160000-es VBV-vel együtt).",
  },
  {
    field: "high_tier",
    title: "High tier",
    encoders: ["x265"],
    what: "A HEVC high tier a level magasabb bitráta- és pufferhatárait engedi (level 5.1-nél 160 Mb/s).",
    values: "Be/ki; az x265 alapból high tiert választ, ha a level megengedi.",
    ncore: "Kötelező; nCore-profilnál automatikus.",
  },
  {
    field: "aud",
    title: "AUD NAL egységek",
    encoders: ["x264", "x265"],
    ncore: "x265-nél kötelező; nCore-profilnál automatikus.",
    what: "Képkocka-határjelzők a bitstreamben; egyes dekóderek igénylik.",
    values: "Ártalmatlan, bekapcsolható.",
  },
  {
    field: "repeat_headers",
    title: "Fejlécek ismétlése",
    encoders: ["x264", "x265"],
    ncore: "x265-nél kötelező; nCore-profilnál automatikus.",
    what: "A paraméterkészleteket minden kulcskép előtt megismétli; vágásnál és streamváltásnál hasznos.",
  },
  {
    field: "annexb",
    title: "Annex B",
    encoders: ["x264", "x265"],
    what: "Annex B (start code) formátumú bitstream; a BDEncode feldolgozási lánca igényli.",
  },
];

/** The wizard's setting groups, in the order the help page shows them. */
export const HELP_GROUPS: Array<{ id: string; title: string; fields: string[] }> = [
  { id: "rate_control", title: "Minőség és sebesség", fields: ["crf", "preset", "tune", "qcomp", "mbtree", "cutree", "rc_lookahead", "lookahead_slices", "ipratio", "pbratio", "vbv"] },
  { id: "psychovisual", title: "Pszichovizuális finomhangolás", fields: ["aq_mode", "aq_strength", "psy_rd", "psy_rdoq", "noise_reduction"] },
  { id: "gop", title: "GOP és képtípusok", fields: ["keyint", "min_keyint", "scenecut", "open_gop", "bframes", "b_adapt", "b_pyramid", "b_intra"] },
  { id: "motion", title: "Mozgásbecslés és predikció", fields: ["ref", "me", "merange", "subme", "weightp", "weightb", "direct", "partitions", "max_merge", "limit_refs"] },
  { id: "transform", title: "Transzformáció és kvantálás", fields: ["trellis", "fast_pskip", "dct_decimate", "chroma_qp_offset", "cbqpoffs", "crqpoffs", "rd", "rdoq_level", "tu_intra_depth", "tu_inter_depth", "limit_tu", "rect", "amp", "early_skip", "rskip"] },
  { id: "filter", title: "Képszűrés", fields: ["deblock_alpha", "deblock_beta", "sao", "limit_sao", "strong_intra_smoothing"] },
  { id: "format", title: "Formátum, szín és bitstream", fields: ["profile", "level", "bit_depth", "pixel_format", "color", "hdr10", "aud", "repeat_headers", "hrd", "high_tier", "annexb"] },
];

const HELP_BY_FIELD = new Map(ENCODER_HELP.map((entry) => [entry.field, entry]));

export function encoderHelp(field: string): EncoderHelpEntry | undefined {
  return HELP_BY_FIELD.get(field);
}

export function encoderHelpFor(encoder: HelpEncoder): EncoderHelpEntry[] {
  return ENCODER_HELP.filter((entry) => entry.encoders.includes(encoder));
}
