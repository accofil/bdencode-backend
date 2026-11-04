# Fitting audio and subtitles from another source

*Magyar változat: [EXTERNAL_SOURCES.md](EXTERNAL_SOURCES.md)*

This feature adds an audio track or an SRT subtitle from another source to an encode or a remux. The typical case: Blu-ray picture, Hungarian dub from a PAL DVD. The program handles a different speed and a different cut.

## The three kinds of job

The **New job** page starts by asking what you want to do. After that you only see the steps that belong to your choice.

| Choice | What is made | What the source is | Is anything encoded? |
|---|---|---|---|
| **Encode or remux** | A new encode or remux with the source's own tracks | A disc or a disc remux MKV | Yes; a remux demuxes |
| **Fit audio or subtitles** | The finished file with the added tracks | A finished encode or remux MKV, or a disc | Not for an MKV; a disc becomes a remux |
| **Encode and fit** | A new encode or remux, with external tracks too | A disc or a disc remux MKV | Yes |

A disc cannot take new tracks, so fitting to a disc makes a remux with the external tracks. The limits of remuxes apply there too.

## Step by step

1. **New job:** choose the kind of job, then the source. When fitting, this is the file or disc that receives the tracks. The scan takes a few minutes.
2. **Wizard, Tracks step:** on the **Audio or subtitles from another source** card, enter the external source or find it with **Browse**. It can be a video file, a DVD folder, a DVD image (`.iso`) or a folder holding a single `.iso`.
3. **Read:** the source's tracks appear. Tick the ones you need and set:
   - the language,
   - the place among the audio tracks (0 is first),
   - whether it is the default.
4. **SRT (optional):** enter its full path and language. The SRT's timing must belong to the external source.
5. **Approve and start:** the program fits the tracks and stops. Nothing is encoded yet.
6. **The external source's fit card:** look through the result, listen to the critical points and approve. If it is wrong, **Leave this source out** drops it.
7. **Finish:** the encode or remux runs, if there is one. The title's own tracks are made and checked the usual way, then a second mux step adds the external tracks.

## How the fit works

**It compares the two pictures, not the sound.** On old films each language has its own sound master, so the shared music and effects are not an exact time reference. On the Blu-ray of *God Forgives, I Don't* (1967) the German and Italian tracks differ by up to ±400 ms from each other, although they are on the same disc.

1. A 64×36 grey signature is made of every frame of both videos.
2. The rhythm of the shot changes gives the rough offset every 25 seconds. Cropping and grading do not disturb this.
3. Reliable frame pairs give the picture geometry. A PAL DVD is often a 1.78 crop of a 2.39 film, and the crop can move from shot to shot (pan & scan).
4. Every frame gets its offset, then every change is solved as one splice between its two trusted neighbours.
5. The speed is chosen between two assumptions:
   - **Frame for frame** (PAL speed-up): every film frame is there, only shown faster.
   - **Same running time:** another frame rate, the same length.

With the 25 → 23.976 ratio one DVD frame in the stretched audio is exactly 2002 samples at 48 kHz, so the pieces land on their place to the sample.

## The approval card

- **Speed, number of parts, picture match:** the median and the share of frames above 0.8. Title cards in another language can lower the match; that alone is not a fault.
- **Timeline:** green is a good match, yellow a weaker one, a gap is what the source lacks.
- **Silent parts:** the external track is silent here because the source lacks the picture.
- **Points to listen to:** every splice and silent part, plus three plain parts.
- **What to listen to:**
  - **Ear test:** the title's own first track in the left ear, the fitted one in the right. The shared music and effects echo if they are apart, whatever the delay of the browser or the headphones.
  - **The fitted audio only** or **the title's own only**.

Nothing needs downloading: the server makes a short 480p H.264/AAC excerpt that plays in the browser. With a UHD source this can take up to half a minute.

> [!IMPORTANT]
> Between different sound masters a slight echo can remain even when the picture-based fit is exact. So watch the lips too.

## What happens to the audio

| Case | Result |
|---|---|
| Same speed, one uncut part, at most 200 ms of delay | Not re-encoded, the track goes in unchanged (HU 9.12) |
| Speed change or cuts, lossy source | AC-3 at the source's bitrate |
| Speed change or cuts, lossless source | AC-3 640 kbps (up to 2.0: 384 kbps) |
| More than 6 channels | Not fitted, because it would have to be downmixed |

- The channel count and the dialnorm stay, and DRC is off while decoding.
- At a sample rate with no whole-sample ratio, such as 44.1 kHz, restoring is not exact, and the program stops.

**Pitch.** The default is **restore**: slowing down exactly undoes the PAL speed-up, and the music returns to its original pitch. **Keep** changes the tempo only. If the dub was recorded to the PAL picture, restoring makes the voices deeper, so you can switch per track on the card; the track is then made again and needs a new approval.

**Subtitles.** Each SRT cue follows its picture. A cue in a part the title lacks is dropped; one crossing a splice is clipped. The card shows the counts. The file can be UTF-8 or Windows-1250.

## Checks

After the second mux (`analysis/external-merge-streams.json`):

- The title's own streams are byte for byte those before the mux.
- The external track lies where the map puts it, part by part and on both sides of the splices, within 1.5 ms. If not, the job stops.
- MediaInfo and the other reports are made again, so they describe the finished file.

When fitting to a finished MKV, the copy of the chosen tracks is proven too: the picture and the kept tracks are byte for byte the original's.

## Trackers

- **Aither:** an encode or remux may only carry the original-language and optionally an English main track, and the wizard warns about this. A track added later to someone's release can be a retag, which is prohibited.
- **nCore:** the Hungarian track is expected first, and the wizard looks at the external track's place too. By the HU rules a re-encoded 5.1 is AC-3 at 640 kbps or at the source's bitrate. Decide about the `RETAiL` tag yourself for audio that is not from the disc.
- Missing parts (`incomplete.audio`) and slips (`audio.oos`) can be nuke reasons, so look through the silent parts.

## Disk space

- With a DVD image, the main title's VOBs are unpacked (about 7 GB for a DVD9).
- For a 2-channel film the stretched audio is about 2.6 GB, and it is deleted after the mux is checked.
- With a finished MKV the program makes a working copy of the file, and the version before the second mux stays in the workspace until cleanup. That is about three times the file's size.

## Limits

- The source must have a picture; a standalone dub file cannot be fitted yet.
- Subtitles can only be SRT. Image subtitles (PGS, VobSub) and a DVD's own subtitles cannot be fitted yet.
- On real material the PAL speed-up has been tried. A 29.97 fps source of the same running time has only run in a synthetic test, and a DVD folder only in an automatic test.
- The picture-based map's resolution is one frame. In a still shot the place of a splice is less certain, but the error is at most the size of that splice.
- Silent parts are not filled, not even from the original audio.
- If a source DVD's audio and picture differ cell by cell, the program does not correct that.
