# Accofil BDEncode 4.1.4 release notes

Fix: the audio continuity check allows two ticks of timestamp quantization in the step between two consecutive timestamps, not one.

## The bug

The Clementine (2019) job (MKV remux source, DTS-HD MA) stopped in QC: "decoded audio sample-cursor continuity failed for audio:1". It found 24,277 "gaps" of 64 samples (1.333 ms) in the source DTS track, while the finished E-AC-3 audio was gap-free.

No audio was actually missing:

- The decoded sample count is exactly 529,900 × 512, the endpoint matches, and the encoded audio has the same count (+1024 samples of encoder padding, within tolerance).
- The source MKV's timestamps use a 1 ms time base and scatter between -1.667 and +0.333 ms around the exact sample timeline, without drift. For example the 160 ms frame sits at 159 and the next at 171.
- A single timestamp can therefore be off by one tick, and the difference between two consecutive ones by two. The check allowed only one tick (48 samples).

## The fix

- The per-frame tolerance is 2 ticks (96 samples for a 1 ms time base, 2 samples for 90 kHz). Over all of Clementine's timestamps the steps are -32, +16 and +64 samples; none is flagged.
- A lost or added audio frame (DTS 512, AC-3 1536 samples) still fails, and the total-sample and endpoint checks do not change.
- QC re-evaluates the existing evidence (the decoded frame list); nothing has to be decoded again.

## Checklist

1. `GET /api/v1/capabilities` `backend_version`: `4.1.4`.
2. The Clementine job gets through the audio continuity check.
