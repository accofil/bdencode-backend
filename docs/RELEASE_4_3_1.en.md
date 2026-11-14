# Accofil BDEncode 4.3.1 release notes

Fix: the remux QC accepts an audio track that runs on for a few tenths of a second of digital silence after the disc's sound.

## The bug

The remux of The Last Whale Singer (2025) German disc stopped at QC: "03-audio.dtsma decodes differently from the disc". The video, the subtitles and the sync were fine.

- eac3to writes a clip's audio to the clip's end; the reference (libbluray) stops at the playlist's out point. So the remux's English DTS-HD MA track came out 38,912 samples (0.81 s) longer, and that part plays after the picture's end.
- Up to the reference's length the two decoded tracks were bit-identical (the same MD5); the extra part is all-zero samples (−91 dB).
- QC compared the MD5 of the whole decoded track, so it saw a difference.

## The fix

When an audio track's MD5 differs (on a single-clip playlist), QC looks further:

- whether the finished track's MD5 up to the reference's sample count equals the disc's;
- whether the extra part at the end is at most 2 s long and digitally silent (at most −90 dB).

When both hold, QC passes and the report says how many ms of silence remain at the end. Any other difference (other samples, sound in the extra part, a longer extra part) still fails. Multi-clip join handling is unchanged.

## Checklist

1. `GET /api/v1/capabilities` `backend_version`: `4.3.1`.
2. The Whale Singer remux passes QC, and the report says "811 ms of digital silence".
