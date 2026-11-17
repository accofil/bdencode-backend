# Accofil BDEncode 4.3.5 release notes

Fix: the bit depth of a Blu-ray LPCM audio track when ffprobe does not report it.

## The bug

The Adventures of Sherlock Holmes DISC01 stopped before the reference remux with "Blu-ray PCM stream audio:4352 has an unsupported bit depth: 0". The servers' FFmpeg 5.1 (Debian 12) ffprobe reports `bits_per_sample=0` and no `bits_per_raw_sample` for `pcm_bluray`, and the scanner took the 0 for a depth. It was the first disc with LPCM audio in production.

## The fix

- 0 is not a depth: the scanner takes the first positive value of `bits_per_raw_sample`, `bits_per_sample` and the native disc reader's value.
- When a `pcm_bluray` track still has no depth, the scanner reads the first packet of its PID from the playlist's clips, starting with the clip that has the most running time. The top two bits of the 4-byte LPCM header's fourth byte give the depth: 16, 20 or 24.
- When the header cannot be read either, the job asks for review as before; it does not guess.

Both LPCM tracks on the Sherlock disc are 16-bit stereo at 48 kHz by their header (`03c0 3140`).

## Checklist

1. `GET /api/v1/capabilities` `backend_version`: `4.3.5`.
2. The Sherlock DISC01 job needs a fresh scan: its old `scan.json` still holds 0.
