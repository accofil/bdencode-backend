# Accofil BDEncode 4.3.6 release notes

Fix: audio fitted from an AVI external source ran out of sync.

## The bug

Fitting the Hungarian audio of Swept from the Sea from "Érzelmek hullámain.avi" left it about 5.5 seconds behind the picture throughout, although the frame match looked flawless (163,433 frames, similarity 0.99).

An AVI marks a held picture with an empty frame. This file has empty frames 1-132 (the opening picture holds for 5.3 s) and 43 more at the end. FFmpeg decodes no picture for an empty frame, and the fingerprint was made with `-fps_mode passthrough`, so they were left out. The map takes a decoded frame's number as its time (n / fps), so every frame number was 132 short and each picture got the sound of 132 frames earlier: 5.5 s late on the film clock. Mapped again at a constant rate, the offset went from -64 to +68 frames, exactly the 132 empty frames.

## The fix

- An AVI source is fingerprinted at a constant frame rate (`-fps_mode cfr -r <fps>`): an empty frame repeats the picture before it, as a player shows it, so frame n really is at n / fps.
- Other sources (MKV, MP4, DVD) are fingerprinted as before.
- The AVI fingerprint stage has a new input, so existing jobs make the fingerprint and the map again, and an approval of the old, shifted map no longer holds.

## Checklist

1. `GET /api/v1/capabilities` `backend_version`: `4.3.6`.
2. Restart the Swept from the Sea fit; the new map differs, so it needs a new approval after listening to the excerpts.
