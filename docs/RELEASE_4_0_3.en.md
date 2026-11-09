# Accofil BDEncode 4.0.3 release notes

Fix: the reference remux no longer fails on a disc whose playlist opens with a clip that has no audio.

## The bug

Playlist 4 of the Taffin (1988) Blu-ray starts with an about 11 second clip without audio (00010.m2ts, 712 KB), and only then comes the film (00004.m2ts). FFmpeg's default probe time is shorter than that, so it recognised the DTS audio with "0 channels, 0 Hz", and the Matroska muxer refused the header (`sample rate not set`). The job went to FAILED at the reference remux, before any encoding. The source was intact.

## The fix

- The commands that open the whole title of a disc (the reference remux and the planner) get the input option `-analyzeduration 120M`, which is 120 seconds of probing.
- **Measured** on the Taffin disc: 10 s still fails, 20 s and up is correct (48 kHz, 2 channels). `-probesize` alone does not help. 120 s is a six-fold margin.
- FFmpeg stops probing as soon as every stream is known, so on a normal disc the larger window costs nothing (0.13 s against 0.19 s on Taffin).
- Checked on the server: the fixed command shape copied 20 seconds of playlist 4 into Matroska, and the streams (H.264, DTS 48 kHz / 2 channels, PGS) were correct. The full 30 GB remux was not run.

## Good to know

- A job that already failed has to be restarted; it does not recover by itself.
- The track analysis windows seek with `-ss` and ran fine on this same disc, so they were left as they are.

## Checklist

1. `GET /api/v1/capabilities` `backend_version`: `4.0.3`.
2. After restarting the Taffin (1988) job, the reference remux completes.
