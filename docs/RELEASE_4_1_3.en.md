# Accofil BDEncode 4.1.3 release notes

Fix: comparison source frames and the first frame of sample windows can no longer be L-SMASH's stale picture from its first seek.

## The bug

The Taffin (1988) job got through with 4.1.2, but the comparison's picture-quality metrics stopped it: in 11 of 24 samples the source frame was entirely black (all the same picture, Y = 16) while the encode was right. That gave the "+24.15 Y shift" and PSNR of 8–20 dB. The comparison images showed a black source too.

Reproduced with the disc's reference:

- L-SMASH-Works can return a stale picture for the **first seek of a new source instance** when that seek lands on or beside an I-frame. Frame 66334 requested on its own was black (Y 16.0); requested after any earlier frame it was exact (Y 111.98, equal to a linear decode). Every later seek is exact.
- The comparison requested every source frame with its own `vspipe --start N --end N`, from a new instance. That is why every I-sample and a few B-samples hit this.
- The VMAF sample-window scripts start the same way. There the first frame of the first window could be wrong (without a warm-up it was black, reproduced). Taffin's VMAF was not affected.

The other servers' recent jobs show no such mismatch; this disc brought it out.

## The fix

- A source frame is decoded by `vspipe` from 8 frames earlier, and ffmpeg keeps only the last (`select`). The first, possibly wrong picture never reaches an image or a metric. The intermediate-result markers record this, so a retried comparison extracts the frames again.
- The L-SMASH sample-window script (VMAF, CRF search) spends its first seek on a discarded frame 24 frames before the first window.
- Measured on Taffin's reference: all 11 previously black samples are right and equal a linear decode.

Encoding does not change; the finished Taffin encode was right, only the measurement and the source images were wrong.

## Checklist

1. `GET /api/v1/capabilities` `backend_version`: `4.1.3`.
2. A new comparison has no black source frame and no repeated reference hashes.
