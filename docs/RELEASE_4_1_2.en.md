# Accofil BDEncode 4.1.2 release notes

Fix: the per-track audio check measures start and length from the audio's first packet, and accepts the overlap already justified at clip joins.

## The bug

After 4.1.1 the Taffin (1988) job stopped at the per-track audio check: `delay_seconds = -11.011`, `duration_delta = 0.011 s` (tolerance 0.002 s). The finished file was right (its first audio packet at 11.011 s, as planned); the measurement was wrong:

- The audio probe took the start from ffprobe's stream-level `start_time`. In the finished file that is the container's start (0), because the audio's first packet lies outside the probe window. The same cause as the mux plan fixed in 4.1.0.
- The length difference is the 512 sample (10.7 ms) overlap at the clip join at the end of the film. The continuity check had already accepted it as a join overlap; the length check did not know about it.

## The fix

- The audio probe takes the start from the **first packet** when it read packets (the probe always reads them); the stream-level `start_time` is only a fallback. The length is then the real audio length too.
- The length check's tolerance grows by the size of the join gaps and overlaps that the continuity check justified. The start and sample-count tolerances do not change: lost or added sound still fails.

## Checklist

1. `GET /api/v1/capabilities` `backend_version`: `4.1.2`.
2. The Taffin job gets through the per-track audio check.
