# Accofil BDEncode 4.0 release notes

*Magyar változat: [RELEASE_4_0.md](RELEASE_4_0.md)*

The program's new name is **Accofil BDEncode**. Torrent creation and upload, removed in 3.0, are back, but for two trackers only: **Aither** and **nCore**. qBittorrent does the seeding.

Only the display name changed. The services (`bdencode-api`, `bdencode-worker`), the command, the paths and the GitHub repository keep their old name, so updates and existing installations work unchanged.

## What's new

- **New job types:** the New job page first asks whether you want to encode or remux, fit tracks, or both.
- **Audio and subtitles from another source**, even at another speed and with another cut, on a finished file too, with no encoding. Full guide: [EXTERNAL_SOURCES.en.md](EXTERNAL_SOURCES.en.md).
- **Torrent, dupe check, upload and seeding** for Aither and nCore.
- **Aither audio rules for 1080p encodes**, with the new **FLAC 16** action.
- **Fixes to the 3.14.0 remux mode.**

## What would you like to do?

The **New job** page now starts with this question, and after it only the steps of the chosen path show:

- **Encode or remux:** the earlier flow, without external sources.
- **Fit audio or subtitles:** onto a finished encode or remux, with no encoding. The file's video and kept tracks stay byte for byte, which the program checks; existing tracks can be kept or left out, not converted. A disc cannot take new tracks, so choosing one makes a remux with the external tracks.
- **Encode and fit:** a new encode or remux, with external tracks too.

For a track fitted to a finished file, mind Aither's rule: a track added later to someone's release can be a retag, which is prohibited there.

## Aither: audio on 1080p encodes

By Aither's trumping rule, a live action 1080p encode is trumpable because of lossless 5.1 audio. The exception is audio of only 2 channels, as 16-bit FLAC. At 2160p the rule is the reverse: a lossy main track is trumpable there.

- **Default:** when you choose the Aither profile for an encode, the lossless tracks of a live action title of at most 1080p switch by themselves: above 2 channels to E-AC-3 1024 kbps, up to 2 channels to the new **FLAC 16**. The wizard lists the changes and you can undo them. **Arrange tracks** does the same.
- **Warning:** the plan check tells you if such a track stayed in the plan. It does not forbid it.
- **FLAC 16:** from a 16-bit source it is bit identical, checked sample by sample. From a deeper source it is dithered; QC then checks loudness, peaks, timing and sync.
- **Exceptions:** remuxes and 2160p are not affected. For anime the program leaves the tracks alone, because the rule only names live action, although no separate permission for animation is stated either.
- **7.1:** FFmpeg's E-AC-3 encoder goes up to 5.1, so 7.1 is downmixed, and the wizard says so. A real 7.1 E-AC-3 would need Dolby's encoder, which the servers do not have.
- **External tracks:** the language and order checks see the fitted audio and subtitles too. A Hungarian dub therefore gives a warning under the Aither profile, where only the original-language and English main tracks may go.

## Torrent, upload and seed

A new card appears on the Release tab after the kit is ready. You start every step.

1. **Make the torrent.** The MKV is hard linked to `seeding/<id>/` (no copy) and a private torrent is made there, with no external tool. The source tag is `Aither` or `nCore`. For nCore above 2 GiB the torrent is a folder holding the MKV and `sample.mkv`.
2. **Dupe check.** On Aither it searches by TMDB id and resolution and looks at the banned groups. On nCore it searches by name and IMDb, and asks for the site's own ban notice.
   - No match: the upload can go on.
   - A match: can be passed with a reason of at least 12 characters.
   - An identical name or a banned item: cannot be passed.
3. **Upload.** A dialog shows exactly what goes up, and the texts can be edited. It is sent only after you confirm the release name.
4. **Seed.** After acceptance the tracker's own torrent is downloaded, checked to describe the same data, and added to qBittorrent.

### Safety rules

- **Nothing goes up by itself.** There is no automatic upload after an encode.
- **A request goes out once.** If the answer is unclear, the state becomes `UNKNOWN` and it is not retried. On nCore the upload is first looked for by name and piece hash. The dupe check then looks at the tracker again; if it is there, the same name cannot go on.
- **On a rejection** the reason shows, the text can be edited and approved again.
- **Logins** are stored encrypted through the existing admin helper. The interface and the logs never show them. The tracker's download link is not stored, and the tracker's torrent (with the passkey) is a `0600` file.

### Seeding and your other qBittorrent automations

- The torrent goes into a separate **`bdencode` category** with the `accofil-bdencode` tag. `qbit-aither-relay` handles the `aither` category only, `qbit-upload-prep` the `other` tag only, and `qbittorrent-storage-mover` looks at its own source drive only, so none touches it.
- The program only adds and reads state; it moves and deletes nothing.
- qBittorrent rechecks the data in full. Below 100% the program reports an error and does not let it download.
- It waits at most 25 minutes, because nCore wants the seed to start within 30 minutes. A queued torrent is force-started.
- If qBittorrent cannot be reached, the upload stays valid: **Seed again** and the tracker torrent's download are still there.
- The hard links in `seeding` stay after the finished job is deleted, so the space is only freed when you also remove the seed.

### Settings

The System page's new **Trackers and seeding** panel:

- **Aither:** API key.
- **nCore:** the contents of `cookies.txt` exported from the browser. Paste it again when it expires; the program tells you.
- **qBittorrent:** address, user name, password. With an empty address seeding stays manual.

**Check the connection** only reads. The API restarts when a login is saved, so do not change them during an upload or seed.

### What goes into the Aither and nCore forms

- **Aither:** REMUX or ENCODE type from the job, resolution, TMDB and IMDb from the release plan, DV/HDR from the name. The name has spaces (`DTS-HD MA 5.1`). The description is the job's BBCode; without images it does not upload. The MediaInfo must contain the `Unique ID` line, and English audio or subtitles are needed. The TMDB id is required.
- **nCore:** own upload (`eredeti=nem`), `hd` or `hd_hun` category by whether the first audio track is Hungarian. The titles, country and length come from nCore's own IMDb lookup and can be edited. You write the description, and it must end with a "Forrás: …" line. The tech info is the MediaInfo of every file in the torrent, with relative names only. Three images go up; those above 5 MB become JPEG.

### What it is built on

- The nCore part is made from **AccoFIL NCUpload** (MIT).
- The Aither part follows the behaviour of **Audionut Upload-Assistant** but does not take its code, because its licence (UAPL) does not allow that here. Only the facts of using the API are the same.

### Limits

- **It has not yet run on a real tracker.** The clients are tested against fake servers, so watch the first real upload.
- One-MKV releases only. There is no full disc (BDMV) upload, and only films go to nCore.
- nCore's daily upload limit and rank-based minimum size are not checked; the site itself refuses those.
- nCore's remux rules are not checked.

## Fixes to the 3.14.0 remux mode

- **The remux did not start on the service.** It stopped with "the remux plan does not belong to the current selection", because the service moves a job straight into the encode queue and preparation was skipped. It runs in that case now.
- **QC stopped falsely on a multi-clip title.** The reference audio's timestamps step back at the clip joins, and the strict decode stopped on that. The hash now looks at the samples only; a decode error still stops it.
- **FFmpeg 5.1's "corrupt input packet in stream" line** at a clip join no longer counts as source damage when the join's strict decode is clean. Elsewhere it still stops the job.

- **The audio of a multi-clip (seamless branching) title no longer slips.** On the 1:53:19 version of *God Forgives, I Don't* the audio slipped in steps up to 87 ms at the clip joins, because the remux kept the disc's overlapping audio. For DTS and DTS-HD tracks, when the title is made of whole clips, the demux now runs as `clip1.m2ts+clip2.m2ts`, so eac3to's second pass removes the overlap. The published eac3to log shows that command instead of the `.mpls`; whether Aither accepts that has not been checked.
- **QC of a multi-clip title measures against the clips.** Sync is measured against the clips' own timestamps, with a tolerance of one codec frame (DTS 10.667 ms, AC-3 and E-AC-3 32 ms). If the MD5 differs, the bitstream packets are compared: the remux may only lose whole packets, at the clip joins. A single-clip title keeps the strict MD5.

Real test: playlist `00002` of God Forgives passed up to QC, with a worst lag of 7.1 ms and 3 packets removed per track. The steps after that have only been tried on this playlist with simulated tools.

**Known limits:** multi-clip TrueHD can stop for review, because eac3to cannot cut it. Multi-clip AC-3 and PCM have not been measured on a real disc yet.

## Installation

- New data folder: `seeding`. The installer creates it and the API service may write to it.
- New optional credentials: `tracker-ncore-cookies`, `qbittorrent-password`.
- New packages: `lsdvd` and `p7zip-full`, for reading DVDs.

## Checklist

1. `GET /api/v1/capabilities`: `backend_version` is `4.0.0`, `constraints.tracker_upload.trackers` is `["aither", "ncore"]`, `constraints.external_sources.available` is `true`.
2. The page title and the sidebar say Accofil BDEncode.
3. The System page shows the Trackers and seeding panel.
4. **New job** starts with the three choices.
5. On a finished job's Release tab the Upload card appears after the kit, and the dupe check cannot start before the torrent.
