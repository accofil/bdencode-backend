# Accofil BDEncode 4.1.6 release notes

Fix: one of 4.1.5's new tests kept 4.1.5 from installing on any server. The program code is unchanged; 4.1.6 carries 4.1.5's content.

## The bug

The server installer runs the full test suite and restores the previous release on a failure. `test_a_disc_window_is_read_from_its_clip_by_the_clip_s_stream_indexes` counted every ffmpeg call as an analysis window. The servers have tesseract installed, so there PGS caption OCR calls ffmpeg too, and the test saw 12 calls instead of 6. CI and the development machine have no tesseract, and there the test passed.

## The fix

- The test counts only window reads (those that write a WAV) and, like its sibling test, pins that there is no tesseract.
- Checked on a server with tesseract installed.

## Checklist

1. `GET /api/v1/capabilities` `backend_version`: `4.1.6`.
2. The install goes through on the servers without an error.
