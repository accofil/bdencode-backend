/**
 * Built-in help for the selectable x264/x265 settings.
 *
 * Compiled from the Aither forum (encode reviews, guides and the encode
 * approval checklist), nCore's wiki and the Hungarian release standard it
 * points to (github.com/encoding-hun/rules-and-standards), the Silent
 * Aperture encoding guide, the x265
 * documentation and the x264 settings reference; values are starting points
 * that a test encode of the actual source confirms or corrects.
 *
 * Every visible text is a Hungarian/English pair (`LocalText`), resolved in
 * the current language when shown: `encoderHelp()` and `resolveHelpEntry()`
 * return plain strings, the page resolves sections, groups and sources with
 * `tx()`.
 */
import { tx } from "./i18n";
import type { LocalText } from "./i18n";

export type HelpEncoder = "x264" | "x265";

/** One setting's help as stored: every text in both languages. */
export interface EncoderHelpData {
  field: string;
  title: LocalText;
  encoders: HelpEncoder[];
  /** What the setting does. */
  what: LocalText;
  /** Effect on quality, size and speed. */
  effect?: LocalText;
  /** Range, default and the usual values. */
  values?: LocalText;
  grain?: LocalText;
  clean?: LocalText;
  animation?: LocalText;
  /** What experienced Aither encoders use. */
  aither?: LocalText;
  /** nCore and the Hungarian release standard (encoding-hun) it points to. */
  ncore?: LocalText;
  caution?: LocalText;
}

/** One setting's help in the current language. */
export interface EncoderHelpEntry {
  field: string;
  title: string;
  encoders: HelpEncoder[];
  what: string;
  effect?: string;
  values?: string;
  grain?: string;
  clean?: string;
  animation?: string;
  aither?: string;
  ncore?: string;
  caution?: string;
}

export interface HelpSection {
  id: string;
  title: LocalText;
  paragraphs: LocalText[];
}

export interface HelpSource {
  title: LocalText;
  url?: string;
  note: LocalText;
}

export interface HelpGroup {
  id: string;
  title: LocalText;
  fields: string[];
}

export const HELP_SOURCES: HelpSource[] = [
  {
    title: { hu: "Aither – Guides fórum", en: "Aither – Guides forum" },
    note: {
      hu: "Ether's Encoding Scratchpad, Comprehensive Beginner's Guide to Video Encoding, Guide to Encoding Dolby Vision Content (bejelentkezés szükséges)",
      en: "Ether's Encoding Scratchpad, Comprehensive Beginner's Guide to Video Encoding, Guide to Encoding Dolby Vision Content (login required)",
    },
  },
  {
    title: { hu: "Aither – Release Review és Release Help", en: "Aither – Release Review and Release Help" },
    note: {
      hu: "kódolások bírálatai: Demolition Man UHD DV x265, Mona Lisa and the Blood Moon 1080p x264, x265 performance comparison",
      en: "encode reviews: Demolition Man UHD DV x265, Mona Lisa and the Blood Moon 1080p x264, x265 performance comparison",
    },
  },
  {
    title: { hu: "Aither – szabályzat, slotok, elnevezés, összehasonlítás", en: "Aither – rules, slots, naming, comparisons" },
    url: "https://aither.cc/pages/1",
    note: { hu: "Rules, Slots, Naming Guide, Video Comparisons Guide, Screenshots", en: "Rules, Slots, Naming Guide, Video Comparisons Guide, Screenshots" },
  },
  {
    title: { hu: "Silent Aperture – Advanced Encoding Guide", en: "Silent Aperture – Advanced Encoding Guide" },
    url: "https://silentaperture.gitlab.io/mdbook-guide/encoding/x264.html",
    note: { hu: "x264 és x265 beállítások, tesztelési módszertan", en: "x264 and x265 settings, testing methodology" },
  },
  {
    title: {
      hu: "nCore Wiki – Feltöltési szabályok, Dupe szabályzat, Torrent nevének helyes megadása",
      en: "nCore Wiki – Upload rules, Dupe rules, Naming the torrent correctly",
    },
    note: {
      hu: "film-, hang- és felirat-szabályok, 1080p/2160p hangformátumok, minta és tech infó (bejelentkezés szükséges)",
      en: "film, audio and subtitle rules, 1080p/2160p audio formats, sample and tech info (login required)",
    },
  },
  {
    title: { hu: "Magyar release-szabványok (encoding-hun)", en: "Hungarian release standards (encoding-hun)" },
    url: "https://github.com/encoding-hun/rules-and-standards",
    note: {
      hu: "x264 HD és x265 UHD-HD szabályok, nuke-indokok; erre mutat az nCore Wiki a megfelelő minőséghez",
      en: "x264 HD and x265 UHD-HD rules, nuke reasons; the nCore Wiki points here for adequate quality",
    },
  },
  {
    title: { hu: "x265 dokumentáció", en: "x265 documentation" },
    url: "https://x265.readthedocs.io/en/master/cli.html",
    note: { hu: "a kapcsolók pontos jelentése és alapértékei", en: "the exact meaning and default of every option" },
  },
  {
    title: { hu: "MeGUI x264 Settings (Wikibooks)", en: "MeGUI x264 Settings (Wikibooks)" },
    url: "https://en.wikibooks.org/wiki/MeGUI/x264_Settings",
    note: { hu: "az x264 kapcsolók leírása", en: "a description of the x264 options" },
  },
  {
    title: { hu: "JET Encoding Guide", en: "JET Encoding Guide" },
    url: "https://jaded-encoding-thaumaturgy.github.io/JET-guide/master/",
    note: { hu: "VapourSynth-alapú munkafolyamat, szűrés, összehasonlítás", en: "VapourSynth-based workflow, filtering, comparison" },
  },
];

export const HELP_SECTIONS: HelpSection[] = [
  {
    id: "ncore",
    title: { hu: "nCore és a magyar release-szabvány", en: "nCore and the Hungarian release standard" },
    paragraphs: [
      {
        hu: "Az nCore Wiki a „megfelelő minőséghez” a magyar release-szabványra (encoding-hun) mutat; ezt a magyar csapatok aláírták. A BDEncode nCore-profilja ezek alapján dolgozik: a bitstream-előírásokat (level, high tier, HRD, VBV, limit-refs, lookahead-slices, x264-nél a legnagyobb ref) automatikusan beállítja, a minőségi minimumoknál (B-frame, merange, subme, psy) figyelmeztet.",
        en: "For “adequate quality” the nCore Wiki points to the Hungarian release standard (encoding-hun), which the Hungarian groups have signed. BDEncode's nCore profile works from these rules: it sets the bitstream requirements (level, high tier, HRD, VBV, limit-refs, lookahead-slices and, for x264, the maximum ref) automatically and warns about the quality minimums (B-frames, merange, subme, psy).",
      },
      {
        hu: "Videó: SDR anyag csak x264 lehet, x265 csak HDR/DV-hez (2160p mindig x265). Tonemapping és darabolt kódolás tilos. Egy filmből csak egy minőségi encode lehet fent; a BluRay-forrású 1080p SDR és 2160p HDR anyagot csak összehasonlító képekkel lehet lecserélni. A DV.HDR akkor előzi meg a sima HDR-t, ha a Dolby Vision metaadatban 10-nél több különböző L1 érték van.",
        en: "Video: SDR material may only be x264, x265 is for HDR/DV only (2160p is always x265). Tonemapping and chunked encoding are forbidden. Only one quality encode of a film may be up; a BluRay-sourced 1080p SDR or 2160p HDR release can only be replaced with comparison screenshots. DV.HDR takes precedence over plain HDR if the Dolby Vision metadata holds more than 10 distinct L1 values.",
      },
      {
        hu: "Hang: 1080p-n TrueHD és DTS-HD MA nem lehet (csak AAC 2.0, AC3, E-AC3, DTS, FLAC 2.0) – a BDEncode ilyenkor E-AC3 5.1-et (1024 kbps) javasol; 7.1-es E-AC3-at FFmpeg-gel nem lehet készíteni. DTS, TrueHD és DTS-HD mellé DD@640 (2.0-nál DD@256) kompatibilitási sáv kell. Sorrend: magyar (első, alapértelmezett), eredeti, angol, kommentár; más nyelv nem lehet. Legfeljebb 16 sáv.",
        en: "Audio: TrueHD and DTS-HD MA are not allowed at 1080p (only AAC 2.0, AC3, E-AC3, DTS, FLAC 2.0) – BDEncode then suggests E-AC3 5.1 (1024 kbps); 7.1 E-AC3 cannot be made with FFmpeg. DTS, TrueHD and DTS-HD need a DD@640 (DD@256 for 2.0) compatibility track alongside. Order: Hungarian (first, default), original, English, commentary; no other language is allowed. At most 16 tracks.",
      },
      {
        hu: "Felirat: forced csak olyan nyelven, amilyen szinkron van. Sorrend: magyar forced, magyar, magyar SDH, eredeti forced, eredeti, eredeti SDH. A magyar szabvány SRT-t kér (x264 HD-nél PGS nem is mehet), az nCore Wiki ezt nem írja elő.",
        en: "Subtitles: forced subtitles only in a language that has a dub. Order: Hungarian forced, Hungarian, Hungarian SDH, original forced, original, original SDH. The Hungarian standard asks for SRT (PGS is not even allowed for x264 HD); the nCore Wiki does not require this.",
      },
      {
        hu: "Feltöltés: nem eredeti release-nél a torrent neve a magyar cím + felbontás (+ HDR/DV), szóközökkel, például „A függetlenség napja 2160p DV HDR”. Pontosan 3 kép kell az encode felbontásában, 2 GB felett legalább 1 perces minta (UHD-nál legalább 200 MB), a tech infó MediaInfo TEXT kimenet a kódolási beállításokkal.",
        en: "Upload: for a non-original release the torrent name is the Hungarian title + resolution (+ HDR/DV), with spaces, for example “A függetlenség napja 2160p DV HDR” (Independence Day). Exactly 3 screenshots at the encode's resolution are required, a sample of at least 1 minute above 2 GB (at least 200 MB for UHD), and the tech info is the MediaInfo TEXT output with the encode settings.",
      },
    ],
  },
  {
    id: "content",
    title: { hu: "Szemcsés, tiszta vagy animáció?", en: "Grainy, clean or animation?" },
    paragraphs: [
      {
        hu: "Szemcsés film: régebbi, filmre forgatott anyag látható, mozgó filmszemcsével. Itt a cél a szemcse megtartása: SAO és erős simítás ki, erősebb pszichovizuális beállítások (psy-rd, psy-rdoq), negatív deblock (-3:-3), x264-nél mbtree nélkül. Az ilyen kódolás nagyobb lesz: átlátszó UHD-nél a remux 40–80%-a is lehet.",
        en: "Grainy film: older material shot on film, with visible, moving film grain. The goal here is to keep the grain: SAO and strong smoothing off, stronger psychovisual settings (psy-rd, psy-rdoq), negative deblock (-3:-3), and no mbtree for x264. Such an encode will be larger: a transparent UHD encode can be 40–80% of the remux.",
      },
      {
        hu: "Tiszta, digitális film: modern digitális kamera, kevés zaj, sima felületek. A fő veszély a sávosodás (banding) és a sötét jelenetek bitszegénysége. Itt mbtree/cutree bekapcsolva jól spórol, az AQ erőssége kicsit magasabb, a psy-értékek mérsékeltebbek, a deblock kevésbé negatív (-2:-2…0:0).",
        en: "Clean, digital film: modern digital camera, little noise, smooth surfaces. The main dangers are banding and bit-starved dark scenes. Here mbtree/cutree switched on saves a lot, the AQ strength is a little higher, the psy values are more moderate and the deblock is less negative (-2:-2…0:0).",
      },
      {
        hu: "Animáció: éles kontúrok, nagy egyszínű felületek. Alacsonyabb psy-rd (gyűrődés ellen), enyhébb deblock (0:0…-1:-1), AQ 0,6–0,7, sok B-frame.",
        en: "Animation: sharp outlines, large flat-coloured areas. Lower psy-rd (against ringing), milder deblock (0:0…-1:-1), AQ 0.6–0.7, many B-frames.",
      },
      {
        hu: "A végső értéket mindig a konkrét forrás próbakódolása dönti el: azonos méretre kódolt változatokat B-frame–B-frame képpárokon hasonlítanak össze, sötét, világos, mozgalmas és statikus jelenetekből.",
        en: "The final value is always decided by a test encode of the actual source: versions encoded to the same size are compared on B-frame–B-frame screenshot pairs taken from dark, bright, busy and static scenes.",
      },
    ],
  },
  {
    id: "rate",
    title: { hu: "CRF, méret és sebesség", en: "CRF, size and speed" },
    paragraphs: [
      {
        hu: "A CRF a minőséget rögzíti, a méret a forrástól függ. Egy CRF-lépés nagyjából 12–21% méretváltozást jelent (UHD-n a BDEncode mérése szerint kb. 17–21%). Az x264 és az x265 CRF-skálája nem összehasonlítható.",
        en: "CRF fixes the quality; the size depends on the source. One CRF step means a size change of roughly 12–21% (on UHD about 17–21% by BDEncode's measurements). The CRF scales of x264 and x265 are not comparable.",
      },
      {
        hu: "Az Aither 1080p x264-nél két slotot tart: Quality (átlátszó, nagyobb, jellemzően a remux 45–60%-a) és Retention (helytakarékos). 20%-nál kisebb méretkülönbségnél a két kódolás ugyanazért a slotért versenyez. 2160p-n csak x265 kódolás lehet, SDR, HDR/DV és HDR10+ külön slotban; a DV/HDR előnyt élvez a sima HDR-rel szemben.",
        en: "For 1080p x264 Aither keeps two slots: Quality (transparent, larger, typically 45–60% of the remux) and Retention (space-saving). With a size difference under 20% the two encodes compete for the same slot. At 2160p only x265 encodes are allowed, with SDR, HDR/DV and HDR10+ in separate slots; DV/HDR takes precedence over plain HDR.",
      },
      {
        hu: "A preset a sebesség és a tömörítési hatékonyság közti cserét állítja. Aither-kódolók x264-nél veryslow/placebo, x265 UHD-nél a gépidő miatt slow/slower/veryslow presetet használnak, és utána a fontos kapcsolókat kézzel állítják be.",
        en: "The preset sets the trade-off between speed and compression efficiency. Aither encoders use the veryslow/placebo preset for x264 and, because of machine time, slow/slower/veryslow for x265 UHD, then set the important options by hand.",
      },
    ],
  },
  {
    id: "aither",
    title: { hu: "Aither-szabályok röviden", en: "Aither rules in brief" },
    paragraphs: [
      {
        hu: "Hang: csak az eredeti nyelvű fő sáv és opcionálisan egy angol sáv; kommentár, izolált zene és történeti sáv megengedett. Minden TrueHD mellé kötelező egy külön DD vagy DD+ kompatibilitási sáv. Ha a fő hang nem angol és nincs angol szinkron, angol felirat kötelező.",
        en: "Audio: only the original-language main track and optionally one English track; commentary, isolated score and historical tracks are allowed. Every TrueHD track must be accompanied by a separate DD or DD+ compatibility track. If the main audio is not English and there is no English dub, English subtitles are mandatory.",
      },
      {
        hu: "Név: Cím Év Felbontás Forrás Hangkodek Csatornák [Atmos] [HDR-típus] Videókodek-Csoport, például „Film 1990 2160p UHD BluRay DTS-HD MA 5.1 DV HDR x265-Csoport”. Nyelvi tag csak akkor kell, ha nincs angol hang; eredeti hang és angol szinkron együtt: Dual-Audio.",
        en: "Name: Title Year Resolution Source AudioCodec Channels [Atmos] [HDR type] VideoCodec-Group, for example “Film 1990 2160p UHD BluRay DTS-HD MA 5.1 DV HDR x265-Group”. A language tag is only needed if there is no English audio; original audio together with an English dub: Dual-Audio.",
      },
      {
        hu: "Leírás: 3–9 PNG-képernyőkép a kész fájl felbontásában, 350 px-es bélyegképpel, MediaInfo és a kódolási beállítások. Saját kódolásnál (PR) kötelező az x264/x265 napló és a forrás–kódolás összehasonlítás; ha a slot foglalt, a meglévő kódolással is.",
        en: "Description: 3–9 PNG screenshots at the finished file's resolution with 350 px thumbnails, MediaInfo and the encode settings. For your own encode (PR) the x264/x265 log and a source–encode comparison are mandatory; if the slot is taken, a comparison with the existing encode as well.",
      },
      {
        hu: "Összehasonlítás: ugyanaz a képkocka minden forrásból, PNG, B-frame (ha nincs, P-frame; I-frame-et kerülni), legalább 10 kép a teljes hosszon, vegyes jelenetekből, a [comparison=Source, Encode] BBCode-dal.",
        en: "Comparison: the same frame from every source, PNG, B-frames (P-frames if there are none; avoid I-frames), at least 10 images across the full length from mixed scenes, using the [comparison=Source, Encode] BBCode.",
      },
      {
        hu: "Torrent (ezt te készíted, a BDEncode 3.0-tól nem): privát, v1, csak a videófájl; darabméret: 1 GB alatt 1 MiB, 1–4 GB 2 MiB, 4–12 GB 4 MiB, 12–20 GB 8 MiB, 20 GB felett 16 MiB.",
        en: "Torrent (you create it; BDEncode no longer does since 3.0): private, v1, the video file only; piece size: under 1 GB 1 MiB, 1–4 GB 2 MiB, 4–12 GB 4 MiB, 12–20 GB 8 MiB, above 20 GB 16 MiB.",
      },
    ],
  },
];

export const ENCODER_HELP: EncoderHelpData[] = [
  {
    field: "crf",
    title: { hu: "CRF minőség", en: "CRF quality" },
    encoders: ["x264", "x265"],
    ncore: {
      hu: "Csak CRF vagy 2-pass megengedett; a bitráta nem lehet nagyobb a forrásénál, a kép legyen transzparens. Az mHD/HDLight-szerű bitszegény encode-ok tilosak.",
      en: "Only CRF or 2-pass is allowed; the bitrate may not exceed the source's, and the picture must be transparent. Bit-starved mHD/HDLight-style encodes are forbidden.",
    },
    what: {
      hu: "Állandó minőségi cél: a kódoló a kép bonyolultságához igazítja a bitrátát.",
      en: "A constant quality target: the encoder adapts the bitrate to the complexity of the picture.",
    },
    effect: {
      hu: "Alacsonyabb érték: jobb kép, nagyobb fájl. Egy lépés kb. 12–21% méretváltozás.",
      en: "Lower value: better picture, larger file. One step is a size change of about 12–21%.",
    },
    values: {
      hu: "x264 1080p: Quality slotban jellemzően 15–18 (például 16,5). x265 UHD: 16–20 (szemcsés anyagnál inkább 15–18, tiszta anyagnál 18–20).",
      en: "x264 1080p: typically 15–18 for the Quality slot (for example 16.5). x265 UHD: 16–20 (rather 15–18 for grainy material, 18–20 for clean material).",
    },
    aither: {
      hu: "Az Aither-bírálók a CRF-et a forráshoz hangolják; a beállítások összevetését azonos méreten (kétmenetes kódolással vagy méretcéllal) javasolják, mert a CRF önmagában nem mond semmit a minőségről.",
      en: "Aither reviewers tune the CRF to the source; they recommend comparing settings at the same size (with a two-pass encode or a size target), because the CRF on its own says nothing about the quality.",
    },
    caution: {
      hu: "Az x264 és az x265 CRF-értéke nem összevethető. A BDEncode automatikus CRF-keresése VMAF- vagy méretcélra is be tudja állítani.",
      en: "x264 and x265 CRF values are not comparable. BDEncode's automatic CRF search can also set it for a VMAF or size target.",
    },
  },
  {
    field: "preset",
    title: { hu: "Preset", en: "Preset" },
    encoders: ["x264", "x265"],
    ncore: {
      hu: "Szegmentált (darabolt) kódolás és GPU-kódolás tilos; x264 legalább r3000, x265 legalább 3.3.",
      en: "Segmented (chunked) encoding and GPU encoding are forbidden; x264 at least r3000, x265 at least 3.3.",
    },
    what: {
      hu: "Előre beállított kapcsolócsomag a sebesség és a tömörítési hatékonyság között.",
      en: "A predefined bundle of options that trades speed against compression efficiency.",
    },
    effect: {
      hu: "Lassabb preset: azonos minőség kisebb méretben, de jóval hosszabb kódolás. A BDEncode a kézzel megadott kapcsolókat a preset után alkalmazza, azok felülírják a preset értékeit.",
      en: "Slower preset: the same quality at a smaller size, but a much longer encode. BDEncode applies manually set options after the preset, so they override the preset's values.",
    },
    values: {
      hu: "x264: veryslow vagy placebo. x265 UHD: slow, slower, ha az idő engedi veryslow. UHD-n slow presettel egy film kb. egy nap.",
      en: "x264: veryslow or placebo. x265 UHD: slow, slower, or veryslow if time allows. On UHD with the slow preset a film takes about a day.",
    },
    aither: {
      hu: "x264-nél a placebo/veryslow az alap, x265 UHD-nél a gépidő miatt gyakori a slow/slower kézi kiegészítésekkel.",
      en: "For x264 placebo/veryslow is the norm; for x265 UHD, because of machine time, slow/slower with manual additions is common.",
    },
  },
  {
    field: "tune",
    title: { hu: "Tartalmi hangolás", en: "Content tune" },
    encoders: ["x264", "x265"],
    what: {
      hu: "Kész beállításcsomag egy tartalomtípushoz (film, grain, animation stb.).",
      en: "A ready-made settings bundle for a content type (film, grain, animation, etc.).",
    },
    effect: {
      hu: "A grain hangolás erősen szemcsemegtartó, de gyakran túl nagy fájlt ad; az animation enyhébb psy-t és erősebb deblockot állít.",
      en: "The grain tune strongly preserves grain but often produces too large a file; the animation tune sets milder psy and stronger deblocking.",
    },
    values: {
      hu: "Javaslat: none (vagy film), és a fontos kapcsolók kézi beállítása.",
      en: "Recommendation: none (or film), and set the important options by hand.",
    },
    aither: {
      hu: "A tapasztalt kódolók nem használnak tune-t, a kapcsolókat egyenként állítják.",
      en: "Experienced encoders do not use a tune; they set the options one by one.",
    },
  },
  {
    field: "profile",
    title: { hu: "Profil", en: "Profile" },
    encoders: ["x264", "x265"],
    what: {
      hu: "A bitstream kódolási profilja (High, Main10…). A forrásból és a kimenetből következik, ezért zárolt.",
      en: "The coding profile of the bitstream (High, Main10…). It follows from the source and the output, so it is locked.",
    },
    values: {
      hu: "1080p SDR x264: High (8 bit). UHD HDR x265: Main10.",
      en: "1080p SDR x264: High (8-bit). UHD HDR x265: Main10.",
    },
  },
  {
    field: "level",
    title: { hu: "Dekóderszint", en: "Decoder level" },
    encoders: ["x264"],
    ncore: {
      hu: "x264 1080p: level 4.1 (30 fps felett 4.2), High profil. x265 2160p: level 5.1 (30 fps felett 5.2) high tierrel – nCore-profilnál automatikus.",
      en: "x264 1080p: level 4.1 (4.2 above 30 fps), High profile. x265 2160p: level 5.1 (5.2 above 30 fps) with high tier – automatic with the nCore profile.",
    },
    what: {
      hu: "H.264-szint, amely a referenciaképek számát és a bitrátát a lejátszók képességeihez köti.",
      en: "The H.264 level, which ties the number of reference frames and the bitrate to the capabilities of players.",
    },
    values: {
      hu: "1080p-n 4.1. A BDEncode SDR x264 kimenetnél automatikusan alkalmazza.",
      en: "4.1 at 1080p. BDEncode applies it automatically for SDR x264 output.",
    },
    aither: {
      hu: "Az Aither x264-sablonokban --level 4.1 szerepel; emiatt 1080p-n legfeljebb 4 referenciakép lehet.",
      en: "Aither x264 templates use --level 4.1; this allows at most 4 reference frames at 1080p.",
    },
  },
  {
    field: "bit_depth",
    title: { hu: "Bitmélység", en: "Bit depth" },
    encoders: ["x264", "x265"],
    ncore: {
      hu: "x264 csak 8 bites lehet; x265 2160p SDR csak 8, HDR csak 10 bites. Tonemapping (HDR→SDR) tilos.",
      en: "x264 may only be 8-bit; x265 2160p SDR only 8-bit, HDR only 10-bit. Tonemapping (HDR→SDR) is forbidden.",
    },
    what: {
      hu: "A kimenet bitmélysége; a forrásból következik és zárolt (HDR: 10 bit).",
      en: "The bit depth of the output; it follows from the source and is locked (HDR: 10-bit).",
    },
  },
  {
    field: "pixel_format",
    title: { hu: "Pixelformátum", en: "Pixel format" },
    encoders: ["x264", "x265"],
    what: {
      hu: "A kimenet pixelformátuma (yuv420p, yuv420p10le); a forrásból következik és zárolt.",
      en: "The pixel format of the output (yuv420p, yuv420p10le); it follows from the source and is locked.",
    },
  },
  {
    field: "color",
    title: { hu: "Színtér", en: "Colour space" },
    encoders: ["x264", "x265"],
    what: {
      hu: "Színalapok, átviteli függvény, mátrix és tartomány. A lemezről olvasott értékek, csak hiányzó adatnál kell jóváhagyni.",
      en: "Colour primaries, transfer function, matrix and range. The values are read from the disc and only need approval when data is missing.",
    },
  },
  {
    field: "hdr10",
    title: { hu: "HDR10 metaadat", en: "HDR10 metadata" },
    encoders: ["x265"],
    what: {
      hu: "Statikus HDR10 metaadat (mastering display, MaxCLL/MaxFALL) a lemezről.",
      en: "Static HDR10 metadata (mastering display, MaxCLL/MaxFALL) from the disc.",
    },
    caution: {
      hu: "Dolby Visionnél a HDR10 metaadatnak egyeznie kell az RPU-val; a BDEncode a lemez adatait viszi át.",
      en: "With Dolby Vision the HDR10 metadata must match the RPU; BDEncode carries over the disc's data.",
    },
  },
  {
    field: "vbv",
    title: { hu: "VBV korlátozás", en: "VBV limit" },
    encoders: ["x264", "x265"],
    ncore: {
      hu: "x264: maxrate 50000–62500, bufsize 50000–78125. x265: mindkettő 100000–160000; nCore-profilnál a BDEncode 160000/160000-et állít be.",
      en: "x264: maxrate 50000–62500, bufsize 50000–78125. x265: both 100000–160000; with the nCore profile BDEncode sets 160000/160000.",
    },
    what: {
      hu: "Bitráta-plafon és puffer; a lejátszók kompatibilitását szolgálja.",
      en: "A bitrate ceiling and buffer; it serves player compatibility.",
    },
    effect: {
      hu: "Fájlba kódolásnál általában nem kell. Túl alacsony plafon a bonyolult jelenetek minőségét rontja.",
      en: "Usually not needed when encoding to a file. Too low a ceiling hurts the quality of complex scenes.",
    },
    aither: {
      hu: "Néhány UHD DV kódoló 160 000 kb/s-os VBV-t használ, mert egyes eszközök (és a staxrip) igénylik; nem kötelező.",
      en: "Some UHD DV encoders use a 160,000 kb/s VBV because some devices (and staxrip) require it; it is not mandatory.",
    },
  },
  {
    field: "keyint",
    title: { hu: "Maximális GOP-hossz", en: "Maximum GOP length" },
    encoders: ["x264", "x265"],
    ncore: {
      hu: "Legfeljebb FPS×20 (FPS×10 ajánlott; a BDEncode 10 másodpercet használ), x264-nél legalább FPS×5.",
      en: "At most FPS×20 (FPS×10 recommended; BDEncode uses 10 seconds), for x264 at least FPS×5.",
    },
    what: {
      hu: "Két kulcskép közti legnagyobb távolság képkockában.",
      en: "The largest distance between two keyframes, in frames.",
    },
    effect: {
      hu: "Hosszabb GOP: kisebb fájl, lassabb tekerés.",
      en: "Longer GOP: smaller file, slower seeking.",
    },
    values: {
      hu: "A BDEncode a képkockasebességből állítja be (kb. 10 másodperc, 23,976 fps-nél 240). Aither x264-sablon: 250.",
      en: "BDEncode sets it from the frame rate (about 10 seconds, 240 at 23.976 fps). Aither x264 template: 250.",
    },
  },
  {
    field: "min_keyint",
    title: { hu: "Minimális GOP-hossz", en: "Minimum GOP length" },
    encoders: ["x264", "x265"],
    ncore: {
      hu: "FPS/2 és FPS×2 között; FPS (1 másodperc) az ajánlott – a BDEncode ezt használja.",
      en: "Between FPS/2 and FPS×2; FPS (1 second) is recommended – BDEncode uses this.",
    },
    what: {
      hu: "Ennél közelebb nem kerül új IDR-kulcskép; az ennél közelebbi jelenetváltás sima I-frame lesz.",
      en: "No new IDR keyframe is placed closer than this; a scene change closer than this becomes a plain I-frame.",
    },
    values: {
      hu: "Kb. 1 másodperc (23–24).",
      en: "About 1 second (23–24).",
    },
  },
  {
    field: "scenecut",
    title: { hu: "Jelenetváltás-érzékenység", en: "Scene-cut sensitivity" },
    encoders: ["x264", "x265"],
    what: {
      hu: "Mennyire hajlamos a kódoló jelenetváltásnál kulcsképet beszúrni.",
      en: "How readily the encoder inserts a keyframe at a scene change.",
    },
    values: {
      hu: "Alapérték 40; ritkán kell változtatni.",
      en: "Default 40; rarely needs changing.",
    },
  },
  {
    field: "open_gop",
    title: { hu: "Nyitott GOP", en: "Open GOP" },
    encoders: ["x264", "x265"],
    what: {
      hu: "Engedi, hogy a kulcskép utáni B-frame-ek az előző GOP-ra hivatkozzanak (nem IDR I-frame-ek).",
      en: "Allows the B-frames after a keyframe to reference the previous GOP (non-IDR I-frames).",
    },
    effect: {
      hu: "Kicsit jobb tömörítés, de rosszabb vágás és tekerés; a fejezetek IDR-képre tétele zárt GOP-pal megbízható.",
      en: "Slightly better compression, but worse cutting and seeking; placing chapters on IDR frames is reliable with a closed GOP.",
    },
    values: {
      hu: "Aither x264: kikapcsolva. x265-nél a bevett gyakorlat a bekapcsolt nyitott GOP, de a fejezetek elejére a BDEncode IDR-képet kényszerít.",
      en: "Aither x264: off. For x265 open GOP switched on is the established practice, but BDEncode forces an IDR frame at the start of every chapter.",
    },
  },
  {
    field: "bframes",
    title: { hu: "B-framek száma", en: "Number of B-frames" },
    encoders: ["x264", "x265"],
    ncore: {
      hu: "x264: legalább 5, x265: legalább 4 egymás utáni B-frame; kikapcsolni tilos.",
      en: "x264: at least 5, x265: at least 4 consecutive B-frames; switching them off is forbidden.",
    },
    what: {
      hu: "Legfeljebb ennyi B-frame jöhet egymás után.",
      en: "At most this many B-frames may follow one another.",
    },
    effect: {
      hu: "Több B-frame: jobb tömörítés, lassabb kódolás. Az x264 naplóban a „consecutive B-frames” sor utolsó értéke legyen 5% alatt, de ne essen 1% alá.",
      en: "More B-frames: better compression, slower encode. In the x264 log the last value of the “consecutive B-frames” line should be below 5% but not drop below 1%.",
    },
    values: {
      hu: "x264: 16 (Aither). x265: 8–16.",
      en: "x264: 16 (Aither). x265: 8–16.",
    },
    animation: {
      hu: "Animációnál sok B-frame különösen hasznos.",
      en: "Many B-frames are especially useful for animation.",
    },
  },
  {
    field: "b_adapt",
    title: { hu: "Adaptív B-frame", en: "Adaptive B-frames" },
    encoders: ["x264", "x265"],
    what: {
      hu: "Hogyan dönt a kódoló a B-frame-ek elhelyezéséről (2 = trellis, a legjobb).",
      en: "How the encoder decides where to place B-frames (2 = trellis, the best).",
    },
    values: { hu: "2.", en: "2." },
  },
  {
    field: "b_pyramid",
    title: { hu: "B-piramis", en: "B-pyramid" },
    encoders: ["x264", "x265"],
    what: {
      hu: "B-frame-eket is használhat referenciaként.",
      en: "B-frames may also be used as references.",
    },
    values: {
      hu: "Bekapcsolva (x264: normal).",
      en: "On (x264: normal).",
    },
  },
  {
    field: "ref",
    title: { hu: "Referenciaképek", en: "Reference frames" },
    encoders: ["x264", "x265"],
    ncore: {
      hu: "x264: kötelező a level 4.1 szerinti legnagyobb ref (1920×1080: 4, 1920×800: 5) – nCore-profilnál a BDEncode automatikusan beállítja. x265: 4–6 (1080p-n 6); level 5.1-nél teljes 3840×2160-on B-piramissal legfeljebb 5.",
      en: "x264: the maximum ref allowed by level 4.1 is mandatory (1920×1080: 4, 1920×800: 5) – with the nCore profile BDEncode sets it automatically. x265: 4–6 (6 at 1080p); at level 5.1, full 3840×2160 with B-pyramid allows at most 5.",
    },
    what: {
      hu: "Hány korábbi képre hivatkozhat a mozgásbecslés.",
      en: "How many earlier frames motion estimation may reference.",
    },
    effect: {
      hu: "Több referencia: jobb tömörítés, lassabb kódolás, nagyobb memóriaigény.",
      en: "More references: better compression, slower encode, higher memory use.",
    },
    values: {
      hu: "x264 1080p, level 4.1: legfeljebb 4. x265: 4–6.",
      en: "x264 1080p, level 4.1: at most 4. x265: 4–6.",
    },
    aither: {
      hu: "x264-nél ref 4 (a 4.1-es szint miatt), x265-nél jellemzően 4.",
      en: "ref 4 for x264 (because of level 4.1), typically 4 for x265.",
    },
  },
  {
    field: "rc_lookahead",
    title: { hu: "Előretekintés", en: "Lookahead" },
    encoders: ["x264", "x265"],
    ncore: {
      hu: "x264: legalább az FPS kétszerese, x265: legalább az FPS.",
      en: "x264: at least twice the FPS, x265: at least the FPS.",
    },
    what: {
      hu: "Hány jövőbeli képkockát elemez a frame-típus döntéshez és az mbtree/cutree-hez.",
      en: "How many future frames are analysed for frame-type decisions and for mbtree/cutree.",
    },
    effect: {
      hu: "Több előretekintés: jobb döntések, több memória.",
      en: "More lookahead: better decisions, more memory.",
    },
    values: {
      hu: "x264 mbtree-vel: 250, mbtree nélkül 60 is elég. x265: 40–80 (gyakori a 60 és a 80).",
      en: "x264 with mbtree: 250, without mbtree 60 is enough. x265: 40–80 (60 and 80 are common).",
    },
  },
  {
    field: "weightp",
    title: { hu: "Súlyozott P-predikció", en: "Weighted P-prediction" },
    encoders: ["x264", "x265"],
    ncore: {
      hu: "x265: a weightp kötelező, a weightb ajánlott.",
      en: "x265: weightp is mandatory, weightb is recommended.",
    },
    what: {
      hu: "Fényerőváltozásoknál (áttűnés, villanás) súlyozott előrejelzés a P-frame-ekben.",
      en: "Weighted prediction in P-frames for brightness changes (fades, flashes).",
    },
    values: {
      hu: "x264: 2 (smart). x265: bekapcsolva.",
      en: "x264: 2 (smart). x265: on.",
    },
  },
  {
    field: "weightb",
    title: { hu: "Súlyozott B-predikció", en: "Weighted B-prediction" },
    encoders: ["x264", "x265"],
    what: {
      hu: "Súlyozott előrejelzés a B-frame-ekben.",
      en: "Weighted prediction in B-frames.",
    },
    values: { hu: "Bekapcsolva.", en: "On." },
  },
  {
    field: "me",
    title: { hu: "Mozgásbecslési mód", en: "Motion estimation method" },
    encoders: ["x264", "x265"],
    ncore: {
      hu: "x264-nél csak umh, esa vagy tesa elfogadott.",
      en: "For x264 only umh, esa or tesa are accepted.",
    },
    what: {
      hu: "Az egész pixeles mozgáskeresés módszere.",
      en: "The method of the full-pixel motion search.",
    },
    effect: {
      hu: "Alaposabb mód: jobb mozgáskövetés, lassabb kódolás.",
      en: "More thorough method: better motion tracking, slower encode.",
    },
    values: {
      hu: "x264: umh. A tesa ritkán éri meg: elmozdítja a szemcsemintát, látható nyereség nélkül. x265: umh vagy star (a minőségi UHD-kódolásokban gyakori a star).",
      en: "x264: umh. tesa is rarely worth it: it shifts the grain pattern without a visible gain. x265: umh or star (star is common in quality UHD encodes).",
    },
  },
  {
    field: "merange",
    title: { hu: "Keresési tartomány", en: "Search range" },
    encoders: ["x264", "x265"],
    ncore: {
      hu: "x264: legalább 24, x265: legalább 32.",
      en: "x264: at least 24, x265: at least 32.",
    },
    what: {
      hu: "Hány pixeles körzetben keres mozgást a kódoló.",
      en: "The radius, in pixels, within which the encoder searches for motion.",
    },
    values: {
      hu: "x264 1080p: 24–32. x265: 57 (az alapérték), legalább 32.",
      en: "x264 1080p: 24–32. x265: 57 (the default), at least 32.",
    },
  },
  {
    field: "subme",
    title: { hu: "Részpixeles finomság", en: "Subpixel refinement" },
    encoders: ["x264", "x265"],
    ncore: {
      hu: "x264: legalább 8, x265: legalább 3.",
      en: "x264: at least 8, x265: at least 3.",
    },
    what: {
      hu: "A mozgásvektorok részpixeles finomítása és a módválasztás alapossága.",
      en: "Subpixel refinement of the motion vectors and the thoroughness of the mode decision.",
    },
    effect: {
      hu: "Magasabb érték: jobb minőség, lassabb kódolás.",
      en: "Higher value: better quality, slower encode.",
    },
    values: {
      hu: "x264: 10–11 (11 a legalaposabb, nagyon lassú). x265: 4–5; a 7 élesíthet.",
      en: "x264: 10–11 (11 is the most thorough and very slow). x265: 4–5; 7 can sharpen.",
    },
  },
  {
    field: "trellis",
    title: { hu: "Trellis", en: "Trellis" },
    encoders: ["x264"],
    what: {
      hu: "Rate-distortion alapú kvantálás.",
      en: "Rate-distortion based quantization.",
    },
    values: {
      hu: "2 (minden döntésnél).",
      en: "2 (on all decisions).",
    },
  },
  {
    field: "partitions",
    title: { hu: "Partíciók", en: "Partitions" },
    encoders: ["x264"],
    what: {
      hu: "Mely makroblokk-felosztásokat vizsgálja az x264.",
      en: "Which macroblock partitions x264 examines.",
    },
    values: { hu: "all.", en: "all." },
  },
  {
    field: "direct",
    title: { hu: "Direkt predikció", en: "Direct prediction" },
    encoders: ["x264"],
    what: {
      hu: "A B-frame-ek direkt mozgásvektor-előrejelzési módja.",
      en: "The direct motion vector prediction mode of B-frames.",
    },
    values: { hu: "auto.", en: "auto." },
  },
  {
    field: "aq_mode",
    title: { hu: "AQ mód", en: "AQ mode" },
    encoders: ["x264", "x265"],
    ncore: {
      hu: "Az adaptív kvantálás kötelező (x264: 3 ajánlott, x265: 3 vagy 4 ajánlott).",
      en: "Adaptive quantization is mandatory (x264: 3 recommended, x265: 3 or 4 recommended).",
    },
    what: {
      hu: "Adaptív kvantálás: a képen belül átcsoportosítja a biteket a sík és a részletes területek között.",
      en: "Adaptive quantization: redistributes bits within the frame between flat and detailed areas.",
    },
    values: {
      hu: "x264: 3 (sötét jelenetek felé hangolt auto-variance). x265: 2 (auto-variance), 3 (sötét jelenetek felé) vagy 4 (élérzékeny).",
      en: "x264: 3 (auto-variance biased towards dark scenes). x265: 2 (auto-variance), 3 (biased towards dark scenes) or 4 (edge-aware).",
    },
    aither: {
      hu: "x264-nél 3. x265 UHD-n gyakori a 2 (0,8 erősséggel) vagy a 4 (1,0 erősséggel).",
      en: "3 for x264. On x265 UHD, 2 (at strength 0.8) or 4 (at strength 1.0) is common.",
    },
    caution: {
      hu: "Ha a sötét jelenetek bitszegények, a 3-as mód és egy kicsit nagyobb erősség segít.",
      en: "If dark scenes are bit-starved, mode 3 and a slightly higher strength help.",
    },
  },
  {
    field: "aq_strength",
    title: { hu: "AQ erősség", en: "AQ strength" },
    encoders: ["x264", "x265"],
    what: {
      hu: "Az adaptív kvantálás ereje.",
      en: "The strength of adaptive quantization.",
    },
    effect: {
      hu: "Nagyobb érték: több bit a sima és sötét területekre (kevesebb sávosodás), kevesebb a részletes területekre.",
      en: "Higher value: more bits for smooth and dark areas (less banding), fewer for detailed areas.",
    },
    values: {
      hu: "x264: 0,7–0,85. x265: 0,8–1,0 (2-es és 3-as mód), 4-es módnál 0,5–1,0.",
      en: "x264: 0.7–0.85. x265: 0.8–1.0 (modes 2 and 3), 0.5–1.0 with mode 4.",
    },
    grain: {
      hu: "Apró szemcsénél 0,8–0,85, durva szemcsénél 0,7–0,75 (x264).",
      en: "0.8–0.85 for fine grain, 0.7–0.75 for coarse grain (x264).",
    },
    clean: {
      hu: "0,8 körül; sávosodásnál egy kicsit feljebb.",
      en: "Around 0.8; a little higher if there is banding.",
    },
    animation: {
      hu: "0,6–0,7, a torzuló kontúrok elkerülésére.",
      en: "0.6–0.7, to avoid distorted outlines.",
    },
    aither: {
      hu: "Az Aither-bírálók tipikus tanácsa: ha a sötét jelenetek bitszegények, emeld kicsit az AQ erősségét, és csökkentsd kicsit az ip/pb arányt.",
      en: "Typical advice from Aither reviewers: if dark scenes are bit-starved, raise the AQ strength a little and lower the ip/pb ratio a little.",
    },
  },
  {
    field: "qcomp",
    title: { hu: "Kvantálási görbe", en: "Quantizer curve" },
    encoders: ["x264", "x265"],
    what: {
      hu: "Mennyire kapjanak a bonyolult (mozgalmas) jelenetek több bitet a nyugodtakhoz képest.",
      en: "How many more bits complex (high-motion) scenes get compared with calm ones.",
    },
    values: {
      hu: "x264 mbtree nélkül 0,60–0,70, mbtree-vel 0,70–0,85. x265: 0,6–0,7.",
      en: "x264 without mbtree 0.60–0.70, with mbtree 0.70–0.85. x265: 0.6–0.7.",
    },
    caution: {
      hu: "Ok nélkül ne állítsd: a legtöbbször az AQ erőssége a jobb eszköz. Az alacsonyabb qcomp-pal való méretspórolás gyakran visszafelé sül el.",
      en: "Do not change it without a reason: AQ strength is usually the better tool. Saving size with a lower qcomp often backfires.",
    },
  },
  {
    field: "mbtree",
    title: { hu: "Macroblock-tree (mbtree)", en: "Macroblock-tree (mbtree)" },
    encoders: ["x264"],
    what: {
      hu: "Az előretekintés alapján csökkenti a biteket azokon a területeken, amelyekre később kevés kép hivatkozik.",
      en: "Based on the lookahead, it reduces the bits spent on areas that few later frames reference.",
    },
    effect: {
      hu: "Sík, tiszta anyagnál nagy megtakarítás; szemcsés anyagnál rombolja a szemcsét.",
      en: "Large savings on flat, clean material; on grainy material it destroys the grain.",
    },
    grain: {
      hu: "Kikapcsolva (qcomp 0,6).",
      en: "Off (qcomp 0.6).",
    },
    clean: {
      hu: "Bekapcsolva, qcomp 0,7–0,85 mellett, nagy előretekintéssel.",
      en: "On, with qcomp 0.7–0.85 and a long lookahead.",
    },
    aither: {
      hu: "Az Aither x264-sablonokban gyakori a --no-mbtree.",
      en: "--no-mbtree is common in Aither x264 templates.",
    },
  },
  {
    field: "cutree",
    title: { hu: "CU-tree (cutree)", en: "CU-tree (cutree)" },
    encoders: ["x265"],
    what: {
      hu: "Az x264 mbtree-jének x265-ös megfelelője: az előretekintés alapján osztja el a QP-t.",
      en: "The x265 counterpart of x264's mbtree: it distributes the QP based on the lookahead.",
    },
    effect: {
      hu: "Tiszta anyagnál spórol; szemcsés anyagnál a háttér szemcséjét elsimíthatja.",
      en: "Saves bits on clean material; on grainy material it can smooth away the grain in the background.",
    },
    grain: {
      hu: "Gyakran kikapcsolják (például több elismert, szemcsés UHD-kódolásban).",
      en: "Often switched off (for example in several well-regarded grainy UHD encodes).",
    },
    clean: { hu: "Bekapcsolva.", en: "On." },
    caution: {
      hu: "Az útmutatók megosztottak; a forrás próbakódolása dönt.",
      en: "The guides are divided; a test encode of the source decides.",
    },
  },
  {
    field: "psy_rd",
    title: { hu: "Psy-RD", en: "Psy-RD" },
    encoders: ["x264", "x265"],
    ncore: {
      hu: "x265-nél a psy-rd és a psy-rdoq kikapcsolása tilos.",
      en: "For x265 switching off psy-rd and psy-rdoq is forbidden.",
    },
    what: {
      hu: "Pszichovizuális optimalizálás: a forrás „energiáját” (textúráját, szemcséjét) őrzi meg akkor is, ha ez a mérőszámok szerint torzítás.",
      en: "Psychovisual optimization: it preserves the “energy” of the source (its texture and grain) even where the metrics count this as distortion.",
    },
    effect: {
      hu: "Magasabb érték: élesebbnek, részletesebbnek ható kép, kicsit nagyobb fájl; túl magas érték gyűrődést (ringing) és műtermékeket okoz. A PSNR/SSIM/VMAF értékeket rontja, a látott minőséget javítja.",
      en: "Higher value: a sharper, more detailed-looking picture and a slightly larger file; too high a value causes ringing and artefacts. It worsens PSNR/SSIM/VMAF scores but improves the perceived quality.",
    },
    values: {
      hu: "x264: élőszereplős anyagnál 0,95–1,10. x265: 1,0–2,5.",
      en: "x264: 0.95–1.10 for live action. x265: 1.0–2.5.",
    },
    grain: { hu: "x265: 1,8–2,5.", en: "x265: 1.8–2.5." },
    clean: {
      hu: "x264: 1,0. x265: 1,0–1,5.",
      en: "x264: 1.0. x265: 1.0–1.5.",
    },
    animation: {
      hu: "x264: 0,6–0,9; x265-nél is alacsonyabb érték.",
      en: "x264: 0.6–0.9; a lower value for x265 as well.",
    },
  },
  {
    field: "psy_rdoq",
    title: { hu: "Psy-RDOQ / psy-trellis", en: "Psy-RDOQ / psy-trellis" },
    encoders: ["x264", "x265"],
    ncore: {
      hu: "x265-nél a psy-rdoq kikapcsolása tilos.",
      en: "For x265 switching off psy-rdoq is forbidden.",
    },
    what: {
      hu: "x265-nél a kvantálás pszichovizuális erőssége; x264-nél ugyanez a mező a psy-trellis értéke (a psy-rd második tagja).",
      en: "For x265 the psychovisual strength of quantization; for x264 the same field holds the psy-trellis value (the second term of psy-rd).",
    },
    effect: {
      hu: "x265: magasabb érték több szemcsét és textúrát tart meg, nagyobb fájllal; túl magas érték műtermékeket okoz.",
      en: "x265: a higher value keeps more grain and texture, with a larger file; too high a value causes artefacts.",
    },
    values: {
      hu: "x265: 0–2 (szemcsés anyagnál 1,0–1,25, tiszta anyagnál 0,5–1,0). x264 (psy-trellis): mindig 0.",
      en: "x265: 0–2 (1.0–1.25 for grainy material, 0.5–1.0 for clean material). x264 (psy-trellis): always 0.",
    },
  },
  {
    field: "deblock_alpha",
    title: { hu: "Deblock (erősség)", en: "Deblock (strength)" },
    encoders: ["x264", "x265"],
    ncore: {
      hu: "A deblock kikapcsolása tilos; filmhez -3:-3 az ajánlott.",
      en: "Switching off deblock is forbidden; -3:-3 is recommended for film.",
    },
    what: {
      hu: "A blokkosodásszűrő ereje (az első érték). Negatív érték: kevesebb simítás, több részlet.",
      en: "The strength of the deblocking filter (the first value). Negative value: less smoothing, more detail.",
    },
    values: {
      hu: "Élőszereplős anyag: -3…-1. Animáció: -2…0.",
      en: "Live action: -3…-1. Animation: -2…0.",
    },
    grain: {
      hu: "-3:-3 (az Aither-kódolók kiindulópontja).",
      en: "-3:-3 (the starting point of Aither encoders).",
    },
    clean: {
      hu: "-2:-2…0:0, tesztelve.",
      en: "-2:-2…0:0, tested.",
    },
    animation: { hu: "0:0…-1:-1.", en: "0:0…-1:-1." },
    aither: {
      hu: "x264-nél a -3:-3 a kiindulópont; ritkán jobb a -4:-4, a 0:0 csak animációnál jön szóba.",
      en: "For x264 -3:-3 is the starting point; occasionally -4:-4 is better, and 0:0 only comes into question for animation.",
    },
  },
  {
    field: "deblock_beta",
    title: { hu: "Deblock (küszöb)", en: "Deblock (threshold)" },
    encoders: ["x264", "x265"],
    what: {
      hu: "A blokkosodásszűrő küszöbe (a második érték). Általában az első értékkel együtt mozog (-3:-3, -2:-2).",
      en: "The threshold of the deblocking filter (the second value). It usually moves together with the first value (-3:-3, -2:-2).",
    },
  },
  {
    field: "chroma_qp_offset",
    title: { hu: "Chroma QP eltérés", en: "Chroma QP offset" },
    encoders: ["x264"],
    what: {
      hu: "A színcsatornák kvantálásának eltérése a fényességhez képest. Negatív érték: több bit a színre.",
      en: "The offset of the colour channels' quantization relative to luma. Negative value: more bits for colour.",
    },
    values: {
      hu: "Jellemzően -2…-1. Az x264 a psy-rd miatt maga is módosítja; a kijelzett érték a ténylegesen alkalmazott.",
      en: "Typically -2…-1. x264 also adjusts it itself because of psy-rd; the value shown is the one actually applied.",
    },
  },
  {
    field: "cbqpoffs",
    title: { hu: "Chroma Cb QP eltérés", en: "Chroma Cb QP offset" },
    encoders: ["x265"],
    what: {
      hu: "A kék-sárga színcsatorna kvantálásának eltérése a fényességhez képest.",
      en: "The offset of the blue–yellow colour channel's quantization relative to luma.",
    },
    values: {
      hu: "4:2:0 anyagnál -3…0; alapérték 0. Negatív érték jobb színrészletet ad nagyobb fájllal.",
      en: "-3…0 for 4:2:0 material; default 0. A negative value gives better colour detail with a larger file.",
    },
  },
  {
    field: "crqpoffs",
    title: { hu: "Chroma Cr QP eltérés", en: "Chroma Cr QP offset" },
    encoders: ["x265"],
    what: {
      hu: "A vörös-zöld színcsatorna kvantálásának eltérése a fényességhez képest.",
      en: "The offset of the red–green colour channel's quantization relative to luma.",
    },
    values: {
      hu: "4:2:0 anyagnál -3…0; alapérték 0. Vörös felületeken (ahol a kódolók gyengébbek) segíthet.",
      en: "-3…0 for 4:2:0 material; default 0. It can help on red surfaces (where encoders are weaker).",
    },
  },
  {
    field: "ipratio",
    title: { hu: "I/P arány", en: "I/P ratio" },
    encoders: ["x264", "x265"],
    what: {
      hu: "Mennyivel jobb minőséget kapjanak az I-frame-ek a P-frame-eknél.",
      en: "How much better quality I-frames get than P-frames.",
    },
    values: { hu: "Alapérték 1,40.", en: "Default 1.40." },
    aither: {
      hu: "Ha a sötét jelenetek bitszegények, az Aither-bírálók az ip/pb arány kis csökkentését javasolják (például 1,30/1,20).",
      en: "If dark scenes are bit-starved, Aither reviewers recommend lowering the ip/pb ratio slightly (for example to 1.30/1.20).",
    },
  },
  {
    field: "pbratio",
    title: { hu: "P/B arány", en: "P/B ratio" },
    encoders: ["x264", "x265"],
    what: {
      hu: "Mennyivel jobb minőséget kapjanak a P-frame-ek a B-frame-eknél.",
      en: "How much better quality P-frames get than B-frames.",
    },
    values: {
      hu: "Alapérték 1,30. Kisebb érték: jobb B-frame-ek, nagyobb fájl.",
      en: "Default 1.30. Lower value: better B-frames, larger file.",
    },
  },
  {
    field: "fast_pskip",
    title: { hu: "Gyors P-skip", en: "Fast P-skip" },
    encoders: ["x264"],
    what: {
      hu: "Korai döntés a P-frame-ek kihagyható blokkjairól.",
      en: "An early decision on the skippable blocks of P-frames.",
    },
    effect: {
      hu: "Gyorsít, de sötét és sík területeken blokkosodást okozhat.",
      en: "Speeds up encoding, but can cause blocking in dark and flat areas.",
    },
    values: {
      hu: "Minőségi kódolásnál kikapcsolva (--no-fast-pskip).",
      en: "Off for quality encodes (--no-fast-pskip).",
    },
  },
  {
    field: "dct_decimate",
    title: { hu: "DCT-tizedelés", en: "DCT decimation" },
    encoders: ["x264"],
    what: {
      hu: "Elhagyja a jelentéktelennek ítélt együtthatókat.",
      en: "Drops the coefficients judged insignificant.",
    },
    effect: {
      hu: "Kisebb fájl, de a finom szemcse és a sík felületek finom átmenetei sérülhetnek.",
      en: "Smaller file, but fine grain and the subtle gradients of flat surfaces can suffer.",
    },
    values: {
      hu: "Minőségi kódolásnál kikapcsolva (--no-dct-decimate).",
      en: "Off for quality encodes (--no-dct-decimate).",
    },
  },
  {
    field: "noise_reduction",
    title: { hu: "Zajcsökkentés", en: "Noise reduction" },
    encoders: ["x264", "x265"],
    what: {
      hu: "A kódoló saját zajcsökkentése (x264 nr, x265 nr-intra/nr-inter).",
      en: "The encoder's own noise reduction (x264 nr, x265 nr-intra/nr-inter).",
    },
    effect: {
      hu: "Kisebb fájl, de a kódolás nem lesz átlátszó: a szemcse és a finom részlet elveszik.",
      en: "Smaller file, but the encode will not be transparent: grain and fine detail are lost.",
    },
    values: { hu: "0 (kikapcsolva).", en: "0 (off)." },
    aither: {
      hu: "Csak akkor szokás zajt csökkenteni, ha a forrás egyáltalán nem tömöríthető; ezt a leírásban jelezni kell.",
      en: "Noise is customarily reduced only when the source cannot be compressed at all otherwise; this must be stated in the description.",
    },
  },
  {
    field: "sao",
    title: { hu: "SAO", en: "SAO" },
    encoders: ["x265"],
    ncore: {
      hu: "A magyar szabvány az SAO kikapcsolását ajánlja (--no-sao --selective-sao 0).",
      en: "The Hungarian standard recommends switching SAO off (--no-sao --selective-sao 0).",
    },
    what: {
      hu: "Sample Adaptive Offset szűrő: a kódolás után simítja a kép egyes részeit.",
      en: "Sample Adaptive Offset filter: smooths parts of the picture after encoding.",
    },
    effect: {
      hu: "A finom részletet és a szemcsét elkeni.",
      en: "It smears fine detail and grain.",
    },
    values: {
      hu: "Élőszereplős anyagnál szinte mindig kikapcsolva (--no-sao). Csak erős gyűrődésnél érdemes visszakapcsolni.",
      en: "Almost always off for live action (--no-sao). Only worth switching back on when there is heavy ringing.",
    },
    aither: {
      hu: "Az Aither UHD-kódolásaiban szinte mindig no-sao.",
      en: "Aither UHD encodes almost always use no-sao.",
    },
  },
  {
    field: "limit_sao",
    title: { hu: "Korlátozott SAO", en: "Limited SAO" },
    encoders: ["x265"],
    what: {
      hu: "A SAO korlátozott (gyorsabb) változata; kikapcsolt SAO mellett nincs hatása.",
      en: "A limited (faster) variant of SAO; it has no effect when SAO is off.",
    },
  },
  {
    field: "strong_intra_smoothing",
    title: { hu: "Erős intra simítás", en: "Strong intra smoothing" },
    encoders: ["x265"],
    what: {
      hu: "32×32-es intra blokkok erős simítása.",
      en: "Strong smoothing of 32×32 intra blocks.",
    },
    grain: {
      hu: "Kikapcsolva: éles, szemcsés anyagon elkeni a részletet.",
      en: "Off: on sharp, grainy material it smears the detail.",
    },
    clean: {
      hu: "Lágy, homályos képnél bekapcsolva maradhat.",
      en: "Can stay on for a soft, blurry picture.",
    },
  },
  {
    field: "rect",
    title: { hu: "Négyszögletes partíciók", en: "Rectangular partitions" },
    encoders: ["x265"],
    what: {
      hu: "Nem négyzetes mozgáspartíciók vizsgálata.",
      en: "Examines non-square motion partitions.",
    },
    effect: {
      hu: "Kicsit jobb tömörítés, lassabb kódolás.",
      en: "Slightly better compression, slower encode.",
    },
    values: {
      hu: "Minőségi kódolásnál bekapcsolva.",
      en: "On for quality encodes.",
    },
  },
  {
    field: "amp",
    title: { hu: "Aszimmetrikus partíciók", en: "Asymmetric partitions" },
    encoders: ["x265"],
    what: {
      hu: "Aszimmetrikus (75/25) partíciók; a négyszögletes partíciókra épül.",
      en: "Asymmetric (75/25) partitions; builds on the rectangular partitions.",
    },
    effect: {
      hu: "Kis nyereség jelentős lassulással.",
      en: "A small gain for a significant slowdown.",
    },
    values: {
      hu: "Gyakran kikapcsolva; gyors gépen bekapcsolható.",
      en: "Often off; can be switched on with a fast machine.",
    },
  },
  {
    field: "early_skip",
    title: { hu: "Korai skip", en: "Early skip" },
    encoders: ["x265"],
    ncore: {
      hu: "x265: az early-skip bekapcsolása tilos (a split-rd-skip, tskip-fast és frame-dup sem lehet bekapcsolva).",
      en: "x265: switching on early-skip is forbidden (split-rd-skip, tskip-fast and frame-dup may not be on either).",
    },
    what: {
      hu: "Ha egy blokk egyszerű összevonással maradék nélkül kódolható, a többi módot nem vizsgálja.",
      en: "If a block can be coded by a simple merge with no residual, the other modes are not examined.",
    },
    effect: {
      hu: "Gyorsít, kevés részletvesztéssel.",
      en: "Speeds up encoding with a small loss of detail.",
    },
    values: {
      hu: "Minőségi kódolásnál kikapcsolva (no-early-skip).",
      en: "Off for quality encodes (no-early-skip).",
    },
  },
  {
    field: "rskip",
    title: { hu: "Rekurzív skip", en: "Recursion skip" },
    encoders: ["x265"],
    what: {
      hu: "Korai kilépés a CU-rekurzióból (1 = szomszédsági heurisztika, 2 = élsűrűség).",
      en: "Early exit from the CU recursion (1 = neighbourhood heuristic, 2 = edge density).",
    },
    values: {
      hu: "A legjobb minőséghez 0; az Aither-kódolásokban az 1 is gyakori.",
      en: "0 for the best quality; 1 is also common in Aither encodes.",
    },
  },
  {
    field: "tu_intra_depth",
    title: { hu: "TU-mélység (intra)", en: "TU depth (intra)" },
    encoders: ["x265"],
    what: {
      hu: "A transzformációs egységek további felosztása intra blokkokban.",
      en: "Further subdivision of the transform units in intra blocks.",
    },
    effect: {
      hu: "Nagyobb mélység: finomabb részlet, lassabb kódolás.",
      en: "Greater depth: finer detail, slower encode.",
    },
    values: {
      hu: "1–4; az Aither UHD-kódolásaiban 3–4.",
      en: "1–4; 3–4 in Aither UHD encodes.",
    },
  },
  {
    field: "tu_inter_depth",
    title: { hu: "TU-mélység (inter)", en: "TU depth (inter)" },
    encoders: ["x265"],
    what: {
      hu: "A transzformációs egységek további felosztása inter blokkokban.",
      en: "Further subdivision of the transform units in inter blocks.",
    },
    values: {
      hu: "1–4; az Aither UHD-kódolásaiban 3–4.",
      en: "1–4; 3–4 in Aither UHD encodes.",
    },
  },
  {
    field: "limit_tu",
    title: { hu: "TU-korlát", en: "TU limit" },
    encoders: ["x265"],
    what: {
      hu: "Korai kilépés a transzformációs fa vizsgálatából a szomszédos blokkok alapján.",
      en: "Early exit from the transform tree search based on the neighbouring blocks.",
    },
    values: {
      hu: "0 (nincs korlát) a legjobb minőséghez; 4 a leggyorsabb.",
      en: "0 (no limit) for the best quality; 4 is the fastest.",
    },
  },
  {
    field: "rd",
    title: { hu: "RD-szint", en: "RD level" },
    encoders: ["x265"],
    ncore: { hu: "x265: legalább 3.", en: "x265: at least 3." },
    what: {
      hu: "A rate-distortion alapú módválasztás alapossága.",
      en: "The thoroughness of the rate-distortion based mode decision.",
    },
    effect: {
      hu: "Magasabb szint: kisebb fájl azonos minőségen, lassabb kódolás.",
      en: "Higher level: a smaller file at the same quality, slower encode.",
    },
    values: {
      hu: "3–4 (a slow preset 4); ha az idő engedi, akár 6.",
      en: "3–4 (the slow preset uses 4); up to 6 if time allows.",
    },
  },
  {
    field: "rdoq_level",
    title: { hu: "RDOQ-szint", en: "RDOQ level" },
    encoders: ["x265"],
    what: {
      hu: "Rate-distortion optimalizált kvantálás (0 = ki, 1 = együtthatók, 2 = a tizedelési döntésekkel együtt).",
      en: "Rate-distortion optimized quantization (0 = off, 1 = coefficients, 2 = including the decimation decisions).",
    },
    values: { hu: "2.", en: "2." },
  },
  {
    field: "b_intra",
    title: { hu: "Intra a B-frame-ekben", en: "Intra in B-frames" },
    encoders: ["x265"],
    what: {
      hu: "Intra módokat is vizsgál a B-frame-ekben.",
      en: "Also examines intra modes in B-frames.",
    },
    values: {
      hu: "A preset szerint; a minőségi kódolások vegyesen használják.",
      en: "As the preset sets it; quality encodes are divided on it.",
    },
  },
  {
    field: "max_merge",
    title: { hu: "Összevonási jelöltek", en: "Merge candidates" },
    encoders: ["x265"],
    ncore: { hu: "x265: legalább 2.", en: "x265: at least 2." },
    what: {
      hu: "Hány térbeli/időbeli összevonási jelöltet vizsgál a kódoló.",
      en: "How many spatial/temporal merge candidates the encoder examines.",
    },
    values: {
      hu: "3–5 (a több jobb, lassabb).",
      en: "3–5 (more is better and slower).",
    },
  },
  {
    field: "limit_refs",
    title: { hu: "Referencia-korlátozás (limit-refs)", en: "Reference limit (limit-refs)" },
    encoders: ["x265"],
    what: {
      hu: "Mennyire szűkítse a referenciakeresést a kisebb blokkok döntései alapján: 0 = nincs korlát (leglassabb, legjobb), 3 = mindkét korlát (a slow preset alapértéke).",
      en: "How far to narrow the reference search based on the decisions for smaller blocks: 0 = no limit (slowest, best), 3 = both limits (the slow preset's default).",
    },
    effect: {
      hu: "Kisebb érték: alaposabb mozgásbecslés, lassabb kódolás.",
      en: "Lower value: more thorough motion estimation, slower encode.",
    },
    values: {
      hu: "0–3; preset szerint 3 (slow), 2 (slower), 1 (veryslow), 0 (placebo).",
      en: "0–3; by preset 3 (slow), 2 (slower), 1 (veryslow), 0 (placebo).",
    },
    ncore: {
      hu: "Legfeljebb 2, ha a rect és az amp is be van kapcsolva, különben legfeljebb 1. nCore-profilnál a BDEncode ezt állítja be.",
      en: "At most 2 if both rect and amp are on, otherwise at most 1. With the nCore profile BDEncode sets this.",
    },
  },
  {
    field: "lookahead_slices",
    title: { hu: "Előretekintési szeletek", en: "Lookahead slices" },
    encoders: ["x265"],
    what: {
      hu: "Hány szeletre bontja a lookahead a képet a párhuzamos elemzéshez.",
      en: "How many slices the lookahead splits the frame into for parallel analysis.",
    },
    effect: {
      hu: "Több szelet: gyorsabb, de pontatlanabb képtípus- és bitráta-döntés.",
      en: "More slices: faster, but less accurate frame-type and bitrate decisions.",
    },
    values: {
      hu: "0–16; 0 vagy 1 = nincs szeletelés.",
      en: "0–16; 0 or 1 = no slicing.",
    },
    ncore: {
      hu: "2160p-n legfeljebb 4, 1080p-n legfeljebb 2. nCore-profilnál automatikus.",
      en: "At most 4 at 2160p, at most 2 at 1080p. Automatic with the nCore profile.",
    },
  },
  {
    field: "hrd",
    title: { hu: "HRD-paraméterek", en: "HRD parameters" },
    encoders: ["x265"],
    what: {
      hu: "A VBV-adatok (Hypothetical Reference Decoder) beírása a bitstreambe; VBV nélkül nem használható.",
      en: "Writes the VBV data (Hypothetical Reference Decoder) into the bitstream; it cannot be used without VBV.",
    },
    values: {
      hu: "Be/ki; a képminőségre nincs hatása.",
      en: "On/off; it has no effect on picture quality.",
    },
    ncore: {
      hu: "Kötelező; nCore-profilnál automatikus (a 160000/160000-es VBV-vel együtt).",
      en: "Mandatory; automatic with the nCore profile (together with the 160000/160000 VBV).",
    },
  },
  {
    field: "high_tier",
    title: { hu: "High tier", en: "High tier" },
    encoders: ["x265"],
    what: {
      hu: "A HEVC high tier a level magasabb bitráta- és pufferhatárait engedi (level 5.1-nél 160 Mb/s).",
      en: "The HEVC high tier allows the level's higher bitrate and buffer limits (160 Mb/s at level 5.1).",
    },
    values: {
      hu: "Be/ki; az x265 alapból high tiert választ, ha a level megengedi.",
      en: "On/off; x265 chooses high tier by default if the level allows it.",
    },
    ncore: {
      hu: "Kötelező; nCore-profilnál automatikus.",
      en: "Mandatory; automatic with the nCore profile.",
    },
  },
  {
    field: "aud",
    title: { hu: "AUD NAL egységek", en: "AUD NAL units" },
    encoders: ["x264", "x265"],
    ncore: {
      hu: "x265-nél kötelező; nCore-profilnál automatikus.",
      en: "Mandatory for x265; automatic with the nCore profile.",
    },
    what: {
      hu: "Képkocka-határjelzők a bitstreamben; egyes dekóderek igénylik.",
      en: "Frame boundary markers in the bitstream; some decoders require them.",
    },
    values: {
      hu: "Ártalmatlan, bekapcsolható.",
      en: "Harmless; can be switched on.",
    },
  },
  {
    field: "repeat_headers",
    title: { hu: "Fejlécek ismétlése", en: "Repeat headers" },
    encoders: ["x264", "x265"],
    ncore: {
      hu: "x265-nél kötelező; nCore-profilnál automatikus.",
      en: "Mandatory for x265; automatic with the nCore profile.",
    },
    what: {
      hu: "A paraméterkészleteket minden kulcskép előtt megismétli; vágásnál és streamváltásnál hasznos.",
      en: "Repeats the parameter sets before every keyframe; useful for cutting and stream switching.",
    },
  },
  {
    field: "annexb",
    title: { hu: "Annex B", en: "Annex B" },
    encoders: ["x264", "x265"],
    what: {
      hu: "Annex B (start code) formátumú bitstream; a BDEncode feldolgozási lánca igényli.",
      en: "A bitstream in Annex B (start code) format; BDEncode's processing chain requires it.",
    },
  },
];

/** The wizard's setting groups, in the order the help page shows them. */
export const HELP_GROUPS: HelpGroup[] = [
  { id: "rate_control", title: { hu: "Minőség és sebesség", en: "Quality and speed" }, fields: ["crf", "preset", "tune", "qcomp", "mbtree", "cutree", "rc_lookahead", "lookahead_slices", "ipratio", "pbratio", "vbv"] },
  { id: "psychovisual", title: { hu: "Pszichovizuális finomhangolás", en: "Psychovisual tuning" }, fields: ["aq_mode", "aq_strength", "psy_rd", "psy_rdoq", "noise_reduction"] },
  { id: "gop", title: { hu: "GOP és képtípusok", en: "GOP and frame types" }, fields: ["keyint", "min_keyint", "scenecut", "open_gop", "bframes", "b_adapt", "b_pyramid", "b_intra"] },
  { id: "motion", title: { hu: "Mozgásbecslés és predikció", en: "Motion estimation and prediction" }, fields: ["ref", "me", "merange", "subme", "weightp", "weightb", "direct", "partitions", "max_merge", "limit_refs"] },
  { id: "transform", title: { hu: "Transzformáció és kvantálás", en: "Transform and quantization" }, fields: ["trellis", "fast_pskip", "dct_decimate", "chroma_qp_offset", "cbqpoffs", "crqpoffs", "rd", "rdoq_level", "tu_intra_depth", "tu_inter_depth", "limit_tu", "rect", "amp", "early_skip", "rskip"] },
  { id: "filter", title: { hu: "Képszűrés", en: "Filtering" }, fields: ["deblock_alpha", "deblock_beta", "sao", "limit_sao", "strong_intra_smoothing"] },
  { id: "format", title: { hu: "Formátum, szín és bitstream", en: "Format, colour and bitstream" }, fields: ["profile", "level", "bit_depth", "pixel_format", "color", "hdr10", "aud", "repeat_headers", "hrd", "high_tier", "annexb"] },
];

const HELP_BY_FIELD = new Map(ENCODER_HELP.map((entry) => [entry.field, entry]));

function optional(text: LocalText | undefined): string | undefined {
  return text ? tx(text) : undefined;
}

/** A help entry with every text in the current language. */
export function resolveHelpEntry(entry: EncoderHelpData): EncoderHelpEntry {
  return {
    field: entry.field,
    title: tx(entry.title),
    encoders: entry.encoders,
    what: tx(entry.what),
    effect: optional(entry.effect),
    values: optional(entry.values),
    grain: optional(entry.grain),
    clean: optional(entry.clean),
    animation: optional(entry.animation),
    aither: optional(entry.aither),
    ncore: optional(entry.ncore),
    caution: optional(entry.caution),
  };
}

/** A setting's help in the current language. */
export function encoderHelp(field: string): EncoderHelpEntry | undefined {
  const entry = HELP_BY_FIELD.get(field);
  return entry ? resolveHelpEntry(entry) : undefined;
}

export function encoderHelpFor(encoder: HelpEncoder): EncoderHelpEntry[] {
  return ENCODER_HELP.filter((entry) => entry.encoders.includes(encoder)).map(resolveHelpEntry);
}
