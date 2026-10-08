# BDEncode 2.8.1 kiadási jegyzet

A képfeltöltés UHD-összehasonlításnál nem akad el többé a szolgáltató méretkorlátján.

## A hiba

Az első valódi UHD-job (La Femme Nikita) összehasonlító képei 0,1–34,5 MB-osak: 96 PNG, ebből 8 nagyobb 32 MB-nál, ezek a szemcsés referenciaképek. Az „auto” feltöltés az ImgBB-vel kezdett, 15 képet feltöltött, és ezzel a szolgáltató rögzült, mert a BBCode-csomag minden képe egy helyre kerül. A 16. kép (34,4 MB) feltöltését az ImgBB „File too big - max 32 MB” üzenettel utasította el. A job „image upload failed; retry is safe” állapotba került, de minden újrapróba ugyanígy elbukott volna.

## Változások

- **A szolgáltatók méretkorlátja ismert:** ImgBB 32 MB, Freeimage 64 MB, Catbox 200 MB. „auto” módban csak olyan szolgáltató jön szóba, amelynek a korlátjába a legnagyobb feltöltendő kép is belefér. A nagy UHD-képek így eleve a Catboxra kerülnek.
- **Érthető üzenet, ha a kép nem fér bele:** ha egy kézzel választott vagy már rögzült szolgáltatóba nem fér bele egy kép, a job felülvizsgálatra kerül („comparison image … exceeds the upload limit of the image host …”), és nem egy újrapróbálható hibába, amely sosem javulna.
- **A feltöltési lépés felülvizsgálati okai nem vesznek el:** eddig egy általános kivételkezelő „image upload provider initialization failed” hibává alakította őket. Ez a szolgáltató-ütközésről szóló, már meglévő üzenetet is érintette.

## Ellenőrzőlista

1. `GET /api/v1/capabilities` `backend_version`: `2.8.1`.
2. Egy UHD-job „auto” feltöltése a Catboxot választja, ha van 32 MB-nál nagyobb összehasonlító kép.

## További dokumentáció

- [BDEncode 2.8 kiadási jegyzet](RELEASE_2_8.md)
