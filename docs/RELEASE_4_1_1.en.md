# Accofil BDEncode 4.1.1 release notes

Fix: the audio check no longer stops when the scan recorded an audio track at 0 Hz with 0 channels.

## The bug

After 4.1.0 the Taffin (1988) job reached the audio check and stopped there with `ValueError: sample rate must be positive`. The audio timing was right by then (the finished file starts it at 11.011 s). The cause: the **scan** also read the playlist with FFmpeg's default, short probe window, so because of the opening clip without audio it recorded the DTS audio at 0 Hz with 0 channels (the same cause as the remux fixed in 4.0.3). The audio policy took 0 as a real value.

## The fix

- The scan's ffprobe also reads the playlist with `-analyzeduration 120M`, so a new job gets correct audio track data.
- The audio policy takes 0 Hz and 0 channels as **unknown**. The check then uses the values measured on the reference itself (48 kHz, 2 channels on Taffin).

## Good to know

- Jobs scanned earlier keep their scan data, but the zeros no longer stop the check.
- A failed job has to be restarted; the mux and the encode are kept, only the QC runs again.

## Checklist

1. `GET /api/v1/capabilities` `backend_version`: `4.1.1`.
2. The Taffin job gets through the QC.
