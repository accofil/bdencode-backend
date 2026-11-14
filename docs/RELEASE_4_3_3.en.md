# Accofil BDEncode 4.3.3 release notes

Fix: the sample file (Sample) reaches the completed folder even when the workspace and the completed folder are separate mounts.

## The bug

After QC and the image upload, The Last Whale Singer remux went to UPLOAD_FAILED: "Invalid cross-device link". The sample (`sample.mkv`) was to move from the workspace (`jobs/…/work/sample`) to the completed folder (`completed/…/Sample`) by a plain rename. The worker's systemd unit gets `jobs` and `completed` as separate `ReadWritePaths` mounts, and a rename between them is impossible even on the same disk.

## The fix

The sample is copied into the target folder under a temporary name, renamed there atomically, and only then removed from the workspace. Where the rename is possible directly, that still happens.

## Checklist

1. `GET /api/v1/capabilities` `backend_version`: `4.3.3`.
2. The Whale Singer remux completes after an upload retry, with its sample in the `Sample` folder.
