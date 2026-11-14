# Accofil BDEncode 4.3.0 release notes

Four requests: a selectable naming scheme that builds the name by itself; the name rules are only suggestions; the external source's audio and subtitle files can be browsed; `subme` can be set at the Advanced level, and a new field takes encoder switches that have no field.

## Naming scheme: Aither or nCore, the name built from the file's data

- The wizard's last step has a new field: **Naming rules**, Aither or nCore (Hungarian standard). The default comes from the tracker profile: the Hungarian standard with the nCore profile, otherwise Aither. You can change it at any time, and the browser remembers it.
- The output name is **built by itself** from the file's data by the chosen scheme (resolution, source, HDR/DV, audio codec and channels, languages, video codec, release tag). It updates on every change: track, scheme, tag.
- Once you edit the name it is **not overwritten**. The "Build the name again" button asks for it again and keeps the title part you edited.
- New schemes:
  - **Hungarian-standard remux** (encoding-hun `series-and-movies-remux.md`): `Title.Year.1080p.BluRay.REMUX[.HDR].DTS-HD.MA.5.1.AVC[.HUN]-TAG`. The original-language audio comes before the video codec, HUN after it. The codec tag is AVC, HEVC, VC1, MPEG2 or AV1.
  - **Fit job names:** the file's kind (encode or remux) comes from the source file's name. With the Hungarian scheme the fitted Hungarian track adds HUN. Example, The Last Whale Singer: `The.Last.Whale.Singer.2025.1080p.BluRay.DDP5.1.x264.HUN-TAG`.

## The name rules are suggestions

- The output name used to be a hard rule ("output_name must be a clean remux name…"). A deviation is now a **warning** in the validation result ("Name suggestion (optional): …"), and the job starts with the typed name.
- The backend recognises both remux schemes (Aither: audio after the codec; Hungarian: audio before it, HUN after) and says for both when the name is not true of the file. Examples are HUN without a Hungarian track, a missing DV or Atmos, or the wrong codec.
- The remux's run-time name check only adds an event-log entry.
- The file name's safety stays mandatory: allowed characters, no path separator.

## Browsing for an external source

- The "Audio or subtitles from another source" browser shows every file the fitting can read: MKV, MP4, M4V, M2TS, MTS, TS, VOB, MPG, MPEG, AVI, ISO, plus folders.
- The SRT field gained a "Browse for an SRT" button that shows folders and `.srt` files. Clicking a file chooses it.
- `GET /api/v1/sources` has a new `files` parameter: `mkv` (default), `external` or `subtitle`.

## `subme` and other encoder switches

- **subme** (subpixel refinement) used to show only at the Pro level. It now also appears at the Advanced level in the "Motion estimation" group, with its help (x264: 0–11, x265: 0–7; for nCore x264 at least 8, x265 at least 3).
- A new field in the **"Other switches"** group, at the Advanced and Pro levels: x264/x265 switches with no field of their own, as `key=value:key=value` (like `-x264-params`). For example x264: `deadzone-inter=21:deadzone-intra=11`, x265: `selective-sao=2:aq-motion=1`. It has its own help.
  - The switches reach the encoder after the fields' values and are saved with the settings. Left empty, nothing changes, and the checksum of earlier settings stays the same.
  - The field allows nothing that has its own field (for example `ref`, `crf`; set those there), and nothing that reads or writes a file or changes the processing chain (for example `stats`, `qpfile`, `pass`, `input-res`, colour-space switches, threads). A bad form and a repeat are refused too, with an explanation.
  - A misspelt or unknown switch fails the encode as it starts.

## Checklist

1. `GET /api/v1/capabilities` `backend_version`: `4.3.0`.
2. In the last step, changing the naming scheme updates the name; an edited name stays.
3. A name off the rules gives a warning, not an error.
4. The external-source browser shows MP4/AVI/ISO files, the SRT browser `.srt` files.
5. At the Advanced level `subme` and the "Other switches" field appear; a `ref=6` switch gives an explained error.
