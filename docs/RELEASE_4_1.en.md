# Accofil BDEncode 4.1.0 release notes

Two fixes to audio timing, and a new action: start a finished job again as a new job.

## Fix: the sound played 11 seconds early (Taffin 1988)

**The bug.** Playlist 4 of the Taffin (1988) Blu-ray opens with an about 11 second clip without audio. In the reference MKV the first audio packet is at 11.053 s, but ffprobe gives the container's start (0.042 s) as the audio's `start_time`, because that first packet lies outside its probe window. The mux planner built on that wrong value and shifted the sound by −11,053 ms: in the finished file the sound began at 0.000 s, during the picture's 11 second opening. The post-mux check read `start_time` the same way, so it did not notice. The audio continuity QC stopped the job (NEEDS_REVIEW); nothing was uploaded.

**The fix.** The program takes an audio stream's start from its **first packet**: in the reference when planning, in the finished file when checking. Subtitles have worked this way since 3.11.2. On the sidecar side, priming and rounding are handled as before. On a normal disc, where the audio starts at the beginning, both values are the same and nothing changes.

## Fix: an audio overlap next to a clip join, on the title's timeline

The audio continuity QC measured where the sound jumps from the audio's first frame, but the playlist's clip joins on the title's (the picture's) timeline. When the audio starts 11 s late, an allowed overlap at a join "moves" 11 s away from it and looks like an error. The jump's position is now moved onto the title's timeline (the audio's first frame minus the video's start) before the comparison. On Taffin: a 512 sample (10.7 ms) overlap at the end of the film, 11 ms from the join, which is now a join overlap. Lost or added sound (the sample count) still fails.

## New: start a finished job again as a new job

The **Actions** menu of a finished job has a new item: **Start again as a new job**. A new job is made from the same source; the finished job and its release stay unchanged. Two choices:

- **With a clean slate:** only the source, the name, the disc and content type and the job type are kept; the wizard starts from its defaults.
- **With the same settings:** the wizard is filled in with the earlier approved settings. Above it a note lists the suggestions of the earlier encode's evaluation (for example CRF 18 → 17, with the reason and the estimated size change). **None of them is applied**; you decide what to change.

The new job starts with a scan; encoding starts only after approval. API: `POST /api/v1/jobs/{id}/reload`, `{"mode": "clean" | "same"}`, COMPLETED jobs only.

## Good to know

- A finished output with the wrong timing is fixed by restarting the job: the mux plan changes, so only the mux and the QC run again; the video encode and the reference remux are kept.
- Older finished releases are not affected (they need no redo when their audio starts at the beginning).

## Checklist

1. `GET /api/v1/capabilities` `backend_version`: `4.1.0`.
2. After restarting the Taffin job, the first audio packet of the finished file is at ~11.01 s and the QC passes.
3. On a finished job, the Actions menu shows "Start again as a new job".
