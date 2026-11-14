# Accofil BDEncode 4.3.4 release notes

Fix: an empty `Sample` folder left by an interrupted attempt no longer stops the finalization.

## The bug

On The Last Whale Singer remux, the failed sample move before 4.3.3 created an empty `Sample` folder in the completed folder. The retry's finalization checked the folder's contents before the sample was made and took the empty folder for an error: "the Sample directory may hold only the release's own sample".

## The fix

The check accepts an empty `Sample` folder; the sample step then puts the sample in it. Anything in the folder other than the release's own sample is still an error.

The Whale Singer remux is already complete: I removed the empty folder and the finalization ran.

## Checklist

1. `GET /api/v1/capabilities` `backend_version`: `4.3.4`.
