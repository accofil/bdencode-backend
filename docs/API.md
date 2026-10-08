# API contract

Minden endpoint prefixe `/api/v1`. Nginx alatt a külső prefix `/encoder`, tehát például `/encoder/api/v1/health`.

## Job létrehozása

```json
{
  "source_path": "/srv/media/Example.Disc",
  "name": "Example",
  "disc_type": "AUTO",
  "content_type": "FILM",
  "priority": 0,
  "settings": {}
}
```

A `source_path` csak a konfigurált source root alatt lehet. `work_path` csak a jobs root, `output_path` csak a completed root alatt engedélyezett.

Az új job `QUEUED` állapotból az egyetlen előkészítési sávban `SCANNING`
állapotba léphet akkor is, ha egy másik job éppen kódol, muxol, QC-t vagy
comparisont végez. Több scan eredménye várhat egyszerre `AWAITING_SELECTION`
állapotban. A jóváhagyott selection `READY` állapotot jelent; innen prioritás,
majd létrehozási idő szerint kerül az egyetlen soros encode sávba. Új encode
csak az előző teljes lezárása után indul.

## Job vezérlése

A 2.1-ben a pipeline `state` és a kezelői `control_state` két külön állapot. A job válasz az alábbi vezérlési mezőket is tartalmazza:

```json
{
  "state": "ENCODING",
  "control_state": "PAUSE_REQUESTED",
  "control_revision": 4,
  "control_requested_at": "2026-08-16T12:00:00Z",
  "control_message": "karbantartás",
  "allowed_operations": ["cancel"]
}
```

A `control_state` értékei: `RUNNING`, `PAUSE_REQUESTED`, `PAUSED`, `CANCEL_REQUESTED`. Az `allowed_operations` backendből származik; a kliens ezt használja a gombok megjelenítéséhez, de a szerver a tranzakcióban újra ellenőrzi az állapotot és a sávfoglalást.

### Pause, folytatás és cancel

```text
POST /jobs/{id}/pause
POST /jobs/{id}/continue
POST /jobs/{id}/cancel
```

Mindhárom kérés törzse opcionális, alakja:

```json
{
  "expected_control_revision": 4,
  "message": "kezelői megjegyzés"
}
```

Sikeres elfogadáskor `202 Accepted` és az aktuális `Job` érkezik. Az `expected_control_revision` optimista concurrency guard; elavult értéknél `409`. Aktív job pause/cancel kérése először csak tartós request. A worker a futó folyamatok leállítása és a részleges kimenet biztonságos takarítása után írja vissza a `PAUSED`, illetve `CANCELLED` visszaigazolást. Tétlen job pause/cancel művelete azonnal visszaigazolható.

Csak a visszaigazolt `PAUSED` job engedi el a hozzá tartozó scan- vagy encode-sávot. A `POST /continue` változatlan pipeline-állapotból és checkpointokból folytat, és `409` választ adhat, ha időközben egy másik job foglalta el a sávot.

> [!IMPORTANT]
> A `POST /jobs/{id}/resume` továbbra is a `NEEDS_REVIEW` állapot jóváhagyására szolgáló régi végpont, nem pause-folytatás. A `DELETE /jobs/{id}` API v1 kompatibilitási alias, amely cancel műveletet végez; végleges jobtörléshez a `/purge` végpontot kell használni.

### Tárhely-előnézet és takarítás

```text
GET /jobs/{id}/storage
```

A válasz kategóriánkénti byte-számot, teljes méretet, `workspace_status`, `cleanup_allowed` és `release_present` mezőt ad. A mérés link/reparse pont vagy root-határ sérülése esetén fail-closed hibával leáll.

```text
POST /jobs/{id}/cleanup
```

```json
{
  "scope": "temporary",
  "expected_version": 17
}
```

A cleanup jelenleg csak `COMPLETED` jobon és kizárólag `temporary` scope-pal engedélyezett. Karanténon keresztül eltávolítja a privát ideiglenes `work` tartalmat, majd friss tárhelyriportot ad; a completed release-t nem módosítja. Az `expected_version` opcionális, de interaktív kliensnek ajánlott elküldenie.

### Job és completed release törlése

```text
DELETE /jobs/{id}/purge?expected_version=17&preserve_release=true
```

Csak `COMPLETED`, `FAILED` vagy `CANCELLED` job törölhető. A `preserve_release` értéke kizárólag `true` lehet: a művelet eltávolítja a job rekordját, privát munkaterületét és külső kimenetel nélküli privát release kitjeit, de a completed release-t mindig megőrzi. `UNKNOWN` állapot, illetve 3.0 előtti `PUBLISHED`, nem `REJECTED` qBittorrent-receipt vagy publication receipt esetén a job purge megtagadja az auditrekord elvesztését; előbb a külön, erősen megerősített completed-release törlést kell választani. A backend az összes preparation `{id: version}` snapshotját a job törlésének tranzakciójában újraellenőrzi. Siker: `204 No Content`.

A publikus completed release szándékos törlése külön végpont:

```text
DELETE /jobs/{id}/release
```

```json
{
  "confirmation": "Release.Name",
  "expected_sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  "force_if_seeded": false,
  "preparation_versions": {
    "0123456789abcdef0123456789abcdef": 6
  }
}
```

A `confirmation` az MKV fájlnév kiterjesztés nélküli stemje, az `expected_sha256` az aktuális MKV hash. A `preparation_versions` kötelező, pontos snapshot: kulcskészletének és minden verziójának egyeznie kell a jobhoz tartozó összes preparation aktuális állapotával; preparation nélküli jobnál az értéke `{}`. A backend ezt ugyanabban az adatbázis-tranzakcióban ellenőrzi újra, amelyben a preparation rekordokat törli és a completed-release-deleted audit eseményt rögzíti. Egy közben létrehozott vagy módosult preparation `409` konfliktust okoz még a fájlrendszer végleges leválasztása előtt.

`force_if_seeded: true` szükséges, ha bármely preparation `UNKNOWN` kimenetelű, vagy egy 3.0 előtti preparation alapján a release qBittorrentbe kerülhetett (`ADDED_AND_RECHECKING` vagy `UNKNOWN` qBittorrent-receipt). Aktív `PREPARING`, `SEEDING_CHECK`, `SEEDING` vagy `PUBLISHING` művelet mellett a törlés tiltott. Az `UNKNOWN` és `PUBLISHED` auditrekord nem törölhető egyszerű preparation- vagy jobtörléssel; csak ez a teljes, megerősített completed-release törlés távolíthatja el. Siker: `204 No Content`.

## Selection

A worker scanje után a `POST /jobs/{id}/selection` payload `selection` objektuma határozza meg a playlistet, szűrést és minden sáv műveletét. A backend nem talál ki nyelvet vagy sávszerepet alacsony confidence esetén.

A webes felület mentés előtt ugyanazt az objektumot a `POST /jobs/{id}/selection/validate` végpontra küldi. Ez a valódi plannerrel normalizálja az effektív x264/x265 profilt, cropot és filtert, visszaadja az FFmpeg videóargumentumokat és a figyelmeztetéseket, de nem módosítja a jobot, az eseménynaplót vagy a fájlrendszert. Sikeres ellenőrzés után a változatlan selection a `POST /jobs/{id}/selection` végponton hagyható jóvá; az `expected_version` mindkét kérésnél megakadályozza a stale felülírást.

```json
{
  "selection": {
    "schema_version": 2,
    "playlist_id": "00800",
    "angle": 1,
    "output_name": "Movie.2026.1080p.BluRay.x264.mkv",
    "video": {
      "detail_level": "advanced",
      "temporal_filter": "progressive",
      "crop": {"left": 0, "top": 138, "right": 0, "bottom": 138},
      "settings": {"crf": 17.5, "preset": "slow"}
    },
    "tracks": [
      {
        "stream_id": "audio:4352",
        "action": "copy",
        "language": "eng",
        "name": "English DTS-HD MA 5.1",
        "default": true,
        "forced": false,
        "order": 0
      },
      {
        "stream_id": "audio:4353",
        "action": "flac",
        "language": "hun",
        "name": "Hungarian FLAC 2.0",
        "default": false,
        "forced": false,
        "order": 1
      },
      {
        "stream_id": "subtitle:4608",
        "action": "copy",
        "language": "eng",
        "name": "English Forced",
        "default": false,
        "forced": true,
        "subtitle_kind": "forced",
        "order": 2
      }
    ],
    "upload_images": true,
    "image_upload_provider": "auto"
  }
}
```

### Minőségi opciók a `video` objektumban

Az alábbi mezők mind elhagyhatók; elhagyva a viselkedés megegyezik a korábbi kiadásokéval.

```json
"video": {
  "auto_crf": {"enabled": true, "target_vmaf": 95.0, "min_crf": 12, "max_crf": 26},
  "dynamic_hdr": "hdr10plus",
  "settings": {"noise_reduction": 120}
}
```

- `auto_crf`: automatikus CRF-keresés VMAF-célra. Mezők: `enabled`, `target_vmaf` (80–99,5), `min_crf`, `max_crf`, `samples` (4–48), `sample_seconds` (1–10), `max_iterations` (3–10), `tolerance` (0,1–3), `metric` (`mean`, `harmonic_mean`, `percentile_1`), `probe_preset`. Bekapcsolva a `settings.crf` csak kiindulópont. A `GET /capabilities` `constraints.auto_crf_defaults` mezője az alapértékeket adja.
- `dynamic_hdr`: `discard` (alapértelmezett), `auto`, `hdr10plus` vagy `dolby_vision`. Érvénytelen érték, nem x265 HDR10 kimenet, nem progresszív időzítés vagy a forrásból hiányzó metaadat esetén a `validate` és a mentés `dynamic_hdr_*` kódú hibát ad (`dynamic_hdr_invalid_mode`, `dynamic_hdr_unsupported_output`, `dynamic_hdr_temporal_filter`, `dynamic_hdr_source_missing`, `dynamic_hdr_no_hdr10_base`, `dynamic_hdr_unsupported_profile`). Ha a gazdagépen hiányzik az eszköz vagy az x265 támogatás, az `advisory_warnings` ezt jelzi; a `GET /runtime-capabilities` `dynamic_hdr` szakasza mutatja az elérhetőséget.
- `settings.noise_reduction`: x264-nél 0–1000, x265-nél 0–2000.

```text
GET /profiles/{encoder}/noise-profiles?content_type=film
```

Névre szóló zaj-/szemcsecsomagokat ad vissza (`off`, `preserve_grain`, `light_denoise`, `medium_denoise`, `strong_denoise`). Minden elem `settings` mezője konkrét, szerkeszthető beállításértékeket tartalmaz; a kliens ezeket egyesítheti a `video.settings` objektummal.

Új job-események: `worker.auto-crf-probe`, `worker.auto-crf`, `worker.dynamic-hdr`, `worker.variable-aspect`. Új analysis-artifactok: `crf-search.json`, `dynamic-hdr.json`; a `crop-policy.json` `aspect_profile` mezőt kap. Az elkészült manifest `auto_crf` és `dynamic_hdr` kulcs alatt tartalmazza őket. A befejezéskor a worker `analysis/source-size.json` fájlt is ír (a kiválasztott playlist klipjeinek összmérete), amelyből a statisztika a megtakarítást számolja.

Az `image_upload_provider` értéke `auto`, `imgbb`, `catbox` vagy `freeimage`.
Automatikus módban a sorrend ImgBB → Catbox → Freeimage, és csak az első
sikeres kép előtt engedélyezett a váltás. Kézi választásnál nincs failover.

Új kliensnek `schema_version: 2` értéket kell küldenie. A backend az 1-es sémájú, már sorban álló selectiont kompatibilitásból elfogadja és 2-es effektív tervvé migrálja; egy régi BD/x264 terv explicit `chroma_qp_offset: 0` értéke ekkor effektív `-2` lesz.

Minden audio- és feliratsávhoz explicit művelet szükséges. Audiónál: `copy`, `flac`, `ac3`, `eac3`, `dts` vagy `omit`; feliratnál csak `copy` vagy `omit`. Minden megtartott felirathoz explicit `subtitle_kind` (`full` vagy `forced`) kell, és a `forced` flagnek ezzel egyeznie kell. Az audio célok determinisztikusak: AC-3 640 kb/s, E-AC-3 1024 kb/s, DTS core 1536 kb/s, mind 48 kHz-en és legfeljebb 5.1 csatornával. DTS-HD forrás `dts` céljánál a beágyazott core újrakódolás nélkül kerül kiemelésre. Az effektív presetek a `GET /api/v1/capabilities` válasz `constraints.audio_transcode_presets` mezőjében is olvashatók. `temporal_filter`: `progressive`, `ivtc_tff`, `ivtc_bff`, `bwdif_tff`, `bwdif_bff`, `hybrid_safe_bob_tff`, `hybrid_safe_bob_bff`.

Az opcionális `tracker_profile` (3.0-tól) értéke `aither` vagy `ncore`; elhagyva (`none`) az általános mód érvényes.

- **Mindkét profil esetén:**
  - A kiadásnév az Aither- vagy a magyar szabvány szerinti nyelvtant követheti. Minden hirdetett jelölésnek igaznak kell lennie a tervre, ellenkező esetben `422` jön az eltérések `problems` listájával.
  - A validate válasz `tracker_findings` listája (`code`, `message`, `severity`) magyarul sorolja a szabálytól való eltéréseket. Ezek nem blokkolnak.
  - A végső kódolás IDR-t kényszerít a fejezetkezdeteken.
  - A comparison 12 B-párt választ, és tiszta `-screenshot.png` képeket is készít.
  - A `comparison.bbcode` trackerszakaszt kap.
- **Csak `ncore` esetén:**
  - Szinkron (magyar) hang is lehet alapértelmezett.
  - Az x265 a level 5.1/5.2 high tier, HRD, AUD, repeat-headers, 160 Mb/s VBV, limit-refs és lookahead-slices beállításokat kapja; az x264 a level 4.1 legnagyobb referenciaszámát.
  - A beállítások a `video_policy.tracker` alatt is rögzülnek.
  - 2 GB fölött a kész mappába `Sample/<név>.sample.mkv` kerül.

Az opcionális `dual_type_match` alapértéke `true`: progresszív timeline esetén az I/P/B pár csak akkor fogadható el, ha ugyanazon presentation frame az eredeti és a kész bitstreamben is ugyanabba a kategóriába tartozik. IVTC/deinterlace után a tömörítetlen referencia nem rendelkezik forrás-bitstream képtípussal, ezért ott a kategória a kész encode típusa, az index/PTS-egyezés továbbra is kötelező.

Ha a videó-bitfolyamból hiányzik a színprimerek, az átviteli karakterisztika vagy a mátrix jelölése, a validate végpont `422` választ ad `source_color_confirmation_required` kóddal, a hiányzó mezőkkel és – csak egyértelmű HD SDR BD vagy HDR10 UHD esetén – biztonságos javaslattal. A felhasználó a teljes `video.settings.color` objektummal erősítheti meg a `primaries`, `transfer`, `matrix`, `range` és `chroma_location` értékeket. A backend a lemezről ténylegesen kiolvasott érték felülírását továbbra is elutasítja; ez címkézés, nem színkonverzió.

Ha a job `NEEDS_REVIEW`, a korrigált teljes `selection` ugyanerre az endpointra küldhető. A backend ilyenkor mindig `READY` állapotból játssza újra a függőség-ellenőrzést; egy késői review nem párosíthat régi videót új beállítás-manifesttel.

Nyelv nélkül megtartott audiónál a worker a reference remuxból hat, filmen elosztott CPU-only beszédmintát elemez. Csak magas bizalmú konszenzust alkalmaz automatikusan; konfliktus, kevés beszéd, ismeretlen PGS vagy hiányzó modell esetén a job review-ba kerül, és kézi ISO 639-2/BCP 47 override szükséges.

## Operátori kiegészítők

Ezek az útvonalak a `bdencode.api_extras` modulban vannak, ugyanazt a `/api/v1` előtagot, hibaburkolót és same-origin mutációvédelmet használják, mint a többi.

### Statisztika

```text
GET /statistics?limit=200
GET /jobs/{id}/statistics
```

Az első az elkészült (`COMPLETED`) munkák fájlonkénti statisztikáját és összesítését adja (legutóbb befejezett elöl), a második egy munkáét. Egy sor mezői: `source_bytes`, `output_bytes`, `saved_bytes`, `saved_percent`, `media_seconds`, `frames`, `bitrate_kbps`, `encode_seconds` (az `ENCODING` szakaszban töltött falióra-idő, a szüneteltetett idő nélkül), `encode_fps`, `realtime_factor`, `total_seconds`, `encoder`, `crf`, `preset`, `auto_crf` és a `quality` objektum (`vmaf_sample`, `vmaf_target`, `ssim_mean`, `psnr_mean_db`). Amire nincs tartós bizonyíték (például a forrásméretre régebbi kiadással készült munkánál), az `null`; a rendszer nem becsül. A `vmaf_sample` az automatikus CRF mintakódolásaira vonatkozik, nem a teljes filmre.

### Profilkönyvtár

```text
GET    /profile-library                       # {"items": [...], "count": n}
POST   /profile-library[?overwrite=true]      # 201; 409 ha a név már létezik
GET    /profile-library/{id}
DELETE /profile-library/{id}                  # 204
GET    /profile-library/{id}/export           # bdencode-profile JSON (attachment)
GET    /profile-library/export                # bdencode-profile-bundle JSON (attachment)
POST   /profile-library/import[?on_conflict=rename|skip|overwrite]
```

Egy profil: `name`, `description`, `encoder`, `detail_level`, `settings`, opcionálisan `auto_crf` és `dynamic_hdr`. A `settings` csak hordozható mezőket tartalmazhat: a `encoder`, `detail_level`, `profile`, `level`, `bit_depth`, `pixel_format`, `color`, `vbv`, `hdr10`, `aud`, `repeat_headers` és `annexb` `not_portable` hibát ad. Minden mentés és import valódi `EncoderSettings` felépítésével ellenőriz. Hibakódok: `invalid`, `invalid_settings`, `invalid_auto_crf`, `invalid_dynamic_hdr`, `not_portable` (422), `unsupported_version` (422), `too_large` (413), `not_found` (404), `exists` és `limit` (409). Az azonosító a névből képződik; a fájlban megadott `id`, `created_at` és `updated_at` importnál figyelmen kívül marad. Az import válasza bejegyzésenként jelent: `{"imported": [...], "skipped": [...], "errors": [{"name", "code", "message"}]}`. Minden elem `selection` mezője a `video` objektumba egyesíthető töredék.

### Lejátszó és kivonatok

```text
GET    /jobs/{id}/player                      # MKV-adatok, fejezetek, meglévő kivonatok
GET    /jobs/{id}/previews
POST   /jobs/{id}/previews                    # {"start_seconds": 0, "duration_seconds": 20, "height": 720}
GET    /jobs/{id}/previews/{name}             # video/mp4, HTTP range támogatással
DELETE /jobs/{id}/previews/{name}
```

Csak kész (`OUTPUT` artifaktummal rendelkező) munkánál, és csak akkor, ha az MKV a `completed` vagy a `jobs` gyökéren belül van. A `duration_seconds` 5–30, a `height` 360, 480 vagy 720. A `POST` `201`-et ad új és `200`-at már meglévő (gyorsítótárból kiszolgált) kivonatnál; a válasz `created` mezője jelzi. Hibakódok: `invalid` (422), `no_output` (409), `not_found` (404), `unavailable` (503, hiányzó ffmpeg/ffprobe), `timeout` (504), `probe_failed` és `transcode_failed` (502). A kivonat H.264/AAC MP4, HDR forrásnál SDR-re tone-map-elt; nem része a kiadásnak, a completed fának vagy a torrentnek.

### Adatbázis és mentések

```text
GET  /system/database        # séma, méret, integritás (quick_check), migrációs előzmények, legutóbbi mentés
GET  /system/backups
POST /system/backups         # 201; ellenőrzött "manual" mentés
```

A visszaállítás szándékosan nincs az API-n: `bdencode db-restore`, leállított szolgáltatásokkal (lásd a README 14.5. pontját). Memóriában lévő adatbázis mentése `422`.

## Release-előkészítés

A release API csak konfigurált workspace gyökerekkel használható, és csak olyan `COMPLETED` jobot fogad el, amelynek egyetlen, tulajdonosi rekorddal, artifact SHA-256-tal és tényleges fájlhashsel egyező MKV-ja van. 3.0-tól a BDEncode nem készít torrentet, nem ad hozzá semmit qBittorrenthez és nem tölt fel a trackerre: a release-előkészítés a csomagot (NFO, BBCode-leírás, MediaInfo, képek, checksumok) és a dupe checket jelenti. A credential nélküli, fix dupe-check endpointhoz tartozó token systemd credentialből töltődik. A beállítást a [README release-konfigurációs fejezete](../README.md#53-trackerprofil-beállítása) ismerteti.

### Profilok

```text
GET /release-profiles
```

A válasz alakja `{"items": [...], "count": n}`. Egy elem mezői: `profile_id`, `display_name`, `screenshot_minimum`, `screenshot_maximum`, `supports_dupe_check` és `profile_digest`; endpointot, announce URL-t vagy credentialnevet nem adnak vissza.

A lista elején mindig a két beépített profil áll (3.0.1-től): `aither` (3–9 kép) és `ncore` (pontosan 3 kép), dupe check nélkül. Utánuk jönnek a profilfájl saját profiljai. A fájl azonos azonosítójú bejegyzése a beépített profil helyére lép. A `tracker.credential_name` csak dupe-check endpoint mellett kötelező.

### Előkészítés létrehozása és lekérése

```text
POST /jobs/{job_id}/release-preparations
```

```json
{
  "profile_id": "example",
  "metadata": {
    "schema_version": 1,
    "release_name": "Movie.2026.1080p.BluRay.x264-GROUP",
    "title": "Movie",
    "year": 2026,
    "edition": null,
    "imdb_id": "tt1234567",
    "tmdb_id": 12345,
    "category": "MOVIE",
    "source_media": "BluRay",
    "resolution": "1080p",
    "video_codec": "x264",
    "audio_codecs": ["DTS-HD MA", "FLAC"],
    "languages": ["eng", "hun"]
  }
}
```

A `release_name` értékének pontosan egyeznie kell a completed MKV stemjével. Siker: `201 Created`.

A metadata `schema_version` mezője elhagyható, alapértéke `1`; az `edition`, `imdb_id` és `tmdb_id` opcionális, a többi példabeli metadata mező kötelező.

```text
GET /jobs/{job_id}/release-preparations
GET /release-preparations/{preparation_id}
```

A jobhoz tartozó lista közvetlen JSON tömb. Egy `ReleasePreparationView` fő mezői: `id`, `job_id`, `state`, `profile_id`, `profile_digest`, `metadata`, logikai `payload_path`, `payload_size`, `payload_sha256`, `kit_ready`, `manifest_sha256`, `torrent_infohash`, `torrent_sha256`, `dupe_receipt`, `qbittorrent_receipt`, `publication_receipt`, `error`, `version`, `created_at`, `updated_at`. A `torrent_*`, a `qbittorrent_receipt` és a `publication_receipt` csak 3.0 előtti rekordban lehet nem `null`. Belső fájlrendszerútvonalat nem ad vissza.

### Validate és build

```text
POST /release-preparations/{id}/validate
POST /release-preparations/{id}/build
```

Mindkét kérés törzse:

```json
{"expected_version": 3}
```

A validate nem módosító preflight: újraellenőrzi a payloadot, profile digestet, comparison képeket és – ha már létezik – a csomag manifestjét. A build manifesttel kötött release-csomagot készít (manifest schema 2): MediaInfo, NFO, BBCode-leírás, ellenőrzött képek és `SHA256SUMS`. A manifest pontosan ezt az egy payloadot írja le, a méretével és SHA-256 hashével:

```text
Release.Name/Release.Name.mkv
```

A csomag nem a completed release-ben, hanem a konfigurált `release-kits/<id>/` területen található. A 3.0 előtti (schema 1) csomagok privát torrentet és feltöltési kérést is tartalmaznak; ezek továbbra is ellenőrizhetők és törölhetők.

### Dupe check

```text
POST /release-preparations/{id}/dupe-check
```

```json
{"expected_version": 4}
```

A dupe check csak `READY` csomagból indul. Közvetlenül a hálózati kérés előtt újraellenőrzi a preparationhöz kötött trackerprofil teljes digestjét, valamint a completed payload tulajdonosi rekordját, közvetlen útvonalát, méretét és SHA-256 hashét. A kérés idején az állapot `SEEDING_CHECK`. A tracker válasza receiptként rögzül: `CLEAR` esetén az állapot `READY_TO_PUBLISH` (a felületen „Dupe check: tiszta”), találatnál `NEEDS_REVIEW`, bizonytalan kimenetnél `UNKNOWN`.

A 2.x `POST /release-preparations/{id}/export`, `/seed` és `/upload` végpont 3.0-ban megszűnt (`404`).

### Előkészítés törlése

```text
DELETE /release-preparations/{id}?expected_version=6
```

A művelet a privát csomagot csak a manifest teljes újraellenőrzése után törli. `PREPARING`, `SEEDING_CHECK`, `SEEDING` vagy `PUBLISHING` állapotban nem engedélyezett. `UNKNOWN` állapot, illetve 3.0 előtti `PUBLISHED`, nem `REJECTED` qBittorrent-receipt vagy bármely publication receipt esetén az auditrekord szintén nem törölhető ezen a végponton. Ez nem törli sem a jobot, sem a completed release-t.

### Release állapotgép

```text
NOT_PREPARED / FAILED → PREPARING → READY
                                      └→ SEEDING_CHECK → READY_TO_PUBLISH
                                                 ├─────→ NEEDS_REVIEW
                                                 └─────→ UNKNOWN
```

A `SEEDING_CHECK` a dupe check futása, a `READY_TO_PUBLISH` a tiszta dupe check eredménye; a nevük a 2.x adatbázissal való kompatibilitás miatt maradt. A `SEEDING`, `PUBLISHING` és `PUBLISHED` állapot csak 3.0 előtti rekordban fordulhat elő.

Az aktív operation lease-ek: `PREPARING` és `SEEDING_CHECK` (régi rekordnál még `SEEDING` és `PUBLISHING`). API-szolgáltatás indulásakor a félbemaradt `PREPARING` állapot `FAILED` lesz, és a hozzá tartozó árva build-staging könyvtár karanténon keresztül eltávolítható. A félbemaradt `SEEDING_CHECK` (és a régi `SEEDING`, `PUBLISHING`) állapot `UNKNOWN` lesz, mert a távoli hatás nem bizonyítható; recovery a dupe checket nem ismétli meg.

Minden módosító művelet az aktuális `version` értéket várja. `409` után a kliensnek újra kell olvasnia a rekordot; ugyanazt a távoli műveletet nem szabad vakon megismételnie.

## Adatbázisséma és kompatibilitás

A 2.1 backend SQLite `schema_version = 2` sémát használ. Első megnyitáskor az 1-es sémát tranzakciósan egészíti ki a jobvezérlés mezőivel, majd idempotensen létrehozza a release-előkészítés és receipt-események, valamint a crash-safe maintenance operationök és célpontclaim-ek tábláit, továbbá a `PAUSED` lane policyhez tartozó indexeket. A meglévő job pipeline-állapotok és selectionök megmaradnak; az új control alapértéke `RUNNING`, revisionje `1`.

Az alkalmazás az ismeretlen, nem 1-es vagy 2-es sémát megtagadja. Frissítés előtt készíts konzisztens mentést az adatbázisról; a 2.1 által már megnyitott adatbázist ne próbáld 2.0 backenddel írni. A `GET /health` válasz `schema_version` mezője a tényleges adatbázissémát mutatja.

## Events

Az események növekvő integer cursorral olvashatók:

```text
GET /events?job_id=<id>&after_id=123
```

Ez alkalmas a későbbi frontend polling/SSE adapteréhez. A raw subprocess output nem kerül API event payloadba; csak stage, progress és sanitizált hibaösszefoglaló.
