# Accofil BDEncode 4.1.5 release notes

Fix: the pre-selection track analysis (audio language, subtitle kind and language) works on discs whose playlist opens with a short clip.

## The bug

On The Experts (1989) the wizard said "the automatic track analysis failed for this playlist". All 6 analysis windows stopped with an error ("Cannot determine format of input stream 0:1"). Playlist 00004 opens with an 11 s clip (00010), like Taffin's. There were two causes:

- The analysis opened the playlist with ffmpeg's short default probe window. The opening clip has no sound, so the audio format stayed unknown. 4.1.1 fixed this in the scanner, the remux and the planner, but not in the analysis.
- With a longer probe the command ran, but the audio came out empty. libbluray joins the clips without continuous timestamps: the opening clip is 600–611 s and the feature clip starts at 600 s again. A seek inside the playlist therefore found nothing.

## The fix

- For a disc source every analysis window is read from the clip file that holds the window's start. The seek uses the clip's own timestamps (`-seek_timestamp`), the window ends at the clip's end at the latest, and streams are chosen by the clip's own indexes (by PID, probed once per clip).
- If the clip cannot be identified or does not exist, the playlist is read as before, now with a long probe window.
- The analysis schema version is 3. A job that was already scanned and waits for selection does not scan again (a restart takes it back to the selection); for the fixed analysis, start a new job from the same source.
- Live on The Experts: all 6 windows read in 15 s, 6 × 30 s of audio, the subtitle is "full" (23.7 events/min) and English by OCR (0.91).

## Checklist

1. `GET /api/v1/capabilities` `backend_version`: `4.1.5`.
2. For a new job from The Experts the wizard suggests an audio language and a subtitle kind.
