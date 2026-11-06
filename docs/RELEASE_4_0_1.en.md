# Accofil BDEncode 4.0.1 release notes

Fix: the automatic crop no longer leaves a faint, almost black row at the edge of the picture when the detected border is stable and differs from the widest picture by only 2 pixels.

## The bug

The automatic crop always kept the **widest canvas** of the keyframe scan. A single bright frame moves that canvas for good. In the Super Troopers 3 scan the detected border was 22 pixels at the top and the bottom (7485 of 7486 observations agreed), but the widest canvas was 20 pixels, so the first and the last row of the finished encode stayed almost black. Another group released the same film at 1036 rows, which is a crop of 22.

## The fix

- **The detected border is used.** The automatic crop follows the detected border when all of these hold:
  - the detected border and the widest canvas differ by at most 2 pixels on every edge;
  - at least 95% of the scan agrees with the detected border;
  - the title keeps one aspect ratio;
  - the job is not a restart after a failed crop check.

  In every other case the widest canvas stays. Borders below 8 pixels are still not cropped, and the 4:2:0 even-crop rule applies.
- **A new check on the full decode.** The existing check works with a 2 pixel tolerance, so with a crop tightened to 22 it would not have noticed a picture that really reaches row 20. The new measurement counts, edge by edge, how many of the frames touching the edge go past it.
  - **25% or more**, over at least half a second of frames: the picture really has that edge. The job stops for review.
  - **After the restart** the program inspects every frame and keeps the widest canvas.
  - **Below that** the job continues; the numbers go into `crop-verification.json` and a `worker.crop-tight-reach` event.
- **Measured values.** On Super Troopers 3: 2.22% at the top, 0.15% at the bottom. The crop of The Quiet and of a title on canada does not change.

## Good to know

- The 25% rests on the measurement of one real title and on the assumption that on a real picture edge nearly every frame goes past it. It has not been measured on a film with a real picture edge. If the job does not stop, at most 2 rows can be lost on the frames concerned.
- The new rule does not run for a manual crop: the entered value and the existing 2 pixel tolerance apply.
- **Known limit.** When the detected border and the widest canvas are the same, there is nothing to tighten, so a faint edge row stays in the encode (The Quiet).
- Running jobs keep their earlier crop, because the saved crop checkpoint stays valid. To re-crop a finished or running job, start its preparation again.

## Checklist

1. `GET /api/v1/capabilities` `backend_version`: `4.0.1`.
2. On a new job, the `tightened_edges` field of `crop-policy.json` shows the edges where the program follows the detected border.
3. In the event log, the "Crop check: detected border" entry shows how many frames went past the crop.
