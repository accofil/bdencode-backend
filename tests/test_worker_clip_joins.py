from __future__ import annotations

import json
import os
from dataclasses import replace
from typing import Any

import pytest

from bdencode.media.bluray import PlaylistSegment
from bdencode.models import JobState
from bdencode.process import ProcessFailure, ProcessResult
from bdencode.queue import JobQueue
from bdencode.worker import JobPaths, ReviewRequired

from test_worker import _enqueue, _selection, context  # noqa: F401

PROGRESS = "frame=1000 fps=287 q=-1.0 size=74980608KiB time=01:49:59.00 speed=12x    \r"
JOIN = (
    "[mpegts @ 0x1] Packet corrupt (stream = 0, dts = NOPTS).\n"
    "[vist#0:0/h264 @ 0x2] timestamp discontinuity (stream id=4113): -718000000, new offset= 718000000\n"
    "[truehd @ 0x3] mlpparse: Parity check failed.\n"
    "[aist#0:1/ac3 @ 0x4] timestamp discontinuity (stream id=4352): 718000000, new offset= -10666\n"
)
JOIN_SECONDS = 7180.0


def _two_clip_disc(context) -> None:
    """The main clip and a short closing clip, joined seamlessly."""

    _database, _settings, scan, scanner, _runner, _worker = context
    stream = scan.source / "BDMV" / "STREAM"
    stream.mkdir(parents=True, exist_ok=True)
    for clip in ("00001", "00002"):
        (stream / f"{clip}.m2ts").write_bytes(b"\x47" * 192)
    playlist = replace(
        scan.playlists[0],
        segments=(
            PlaylistSegment("00001", 600.0, 600.0 + JOIN_SECONDS),
            PlaylistSegment("00002", 600.0, 620.0, relative_start_seconds=JOIN_SECONDS),
        ),
    )
    scanner.result = replace(scan, playlists=(playlist,))


def _remux_logs(runner, remux_log: str, *, failing_join_decode: bool = False) -> list[tuple[str, ...]]:
    """Write ``remux_log`` for the remux; record (and optionally fail) the join decodes."""

    real_run = runner.run
    join_decodes: list[tuple[str, ...]] = []

    def run(*args: Any, **kwargs: Any):
        command = tuple(os.fspath(item) for item in args[0])
        if "0:a?" in command:
            join_decodes.append(command)
            if failing_join_decode:
                raise ProcessFailure(
                    ProcessResult(command, 1, 0.0, 0.0, None, kwargs.get("stderr_path"))
                )
        result = real_run(*args, **kwargs)
        if "-playlist" in command and kwargs.get("stderr_path") is not None:
            runner._write(kwargs["stderr_path"], remux_log)
        return result

    runner.run = run  # type: ignore[method-assign]
    return join_decodes


def _ready(context):
    database, _settings, scan, _scanner, _runner, worker = context
    job = _enqueue(database, scan.source)
    claimed = JobQueue(database).claim_next()
    assert claimed is not None
    worker.process_one_stage(claimed)
    return job, database.set_selection(job.id, _selection())


def test_join_messages_cleared_by_a_strict_decode_do_not_stop_the_job(context) -> None:
    database, settings, _scan, _scanner, runner, worker = context
    _two_clip_disc(context)
    join_decodes = _remux_logs(runner, PROGRESS * 10 + JOIN + PROGRESS * 2)
    job, ready = _ready(context)

    encoding = worker.process_one_stage(ready)

    assert encoding.state is JobState.ENCODING
    # The end of the title logged nothing, so only the join is decoded.
    (decode,) = join_decodes
    assert decode[decode.index("-ss") + 1] == f"{JOIN_SECONDS - 20:.3f}"
    paths = JobPaths.create(settings, job.id)
    report = json.loads((paths.analysis / "clip-joins.json").read_text("utf-8"))
    assert report["verified"] is True
    assert report["joins"] == [JOIN_SECONDS]
    assert report["title_end"] == 7200.0 and report["title_end_verified"] is False
    assert any("Packet corrupt" in line for line in report["join_messages"])
    events = [e for e in database.list_events(job_id=job.id) if e.kind == "worker.clip-joins-verified"]
    assert len(events) == 1

    # The full decode beside the encode reads the same remux log.
    assert worker.process_one_stage(encoding).state is JobState.MUXING


def test_a_failed_decode_across_the_join_still_stops_the_job(context) -> None:
    _database, settings, _scan, _scanner, runner, worker = context
    _two_clip_disc(context)
    _remux_logs(runner, PROGRESS * 10 + JOIN + PROGRESS * 2, failing_join_decode=True)
    job, ready = _ready(context)

    with pytest.raises(ReviewRequired, match="source corruption"):
        worker.process_one_stage(ready)

    report = json.loads(
        (JobPaths.create(settings, job.id).analysis / "clip-joins.json").read_text("utf-8")
    )
    assert report["verified"] is False
    assert report["failed_joins"] == [JOIN_SECONDS]


def test_damage_away_from_the_join_still_stops_the_job(context) -> None:
    _database, _settings, _scan, _scanner, runner, worker = context
    _two_clip_disc(context)
    damage = "[mpegts @ 0x9] Packet corrupt (stream = 0, dts = 4512000).\n"
    _remux_logs(runner, damage + PROGRESS * 12 + JOIN + PROGRESS * 2)
    _job, ready = _ready(context)

    with pytest.raises(ReviewRequired, match="source corruption"):
        worker.process_one_stage(ready)


def test_a_single_clip_title_is_judged_as_before(context) -> None:
    _database, _settings, _scan, _scanner, runner, worker = context
    join_decodes = _remux_logs(runner, PROGRESS * 10 + JOIN + PROGRESS * 2)
    _job, ready = _ready(context)

    # No join to explain the jumps: the corrupt packet is source damage.
    with pytest.raises(ReviewRequired, match="source corruption"):
        worker.process_one_stage(ready)
    assert join_decodes == []


def _progress(seconds: float) -> str:
    minutes, secs = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"frame=1000 fps=287 q=-1.0 size=74980608kB time={int(hours):02d}:{int(minutes):02d}:{secs:05.2f} speed=12x    \r"


# FFmpeg 5.1 (Debian 12) logs no timestamp jump at -v info, only the cut packet.
JOIN_51 = (
    "[mpegts @ 0x1] Packet corrupt (stream = 0, dts = NOPTS).\n"
    "[truehd @ 0x3] mlpparse: Parity check failed.\n"
)


def test_ffmpeg_51_join_messages_are_verified_by_their_time(context) -> None:
    _database, settings, _scan, _scanner, runner, worker = context
    _two_clip_disc(context)
    log = (
        "".join(_progress(t) for t in range(7150, 7180, 5))
        + JOIN_51
        + "".join(_progress(t) for t in range(7180, 7200, 5))
        # The title's own last packet is cut too.
        + JOIN_51
    )
    join_decodes = _remux_logs(runner, log)
    job, ready = _ready(context)

    encoding = worker.process_one_stage(ready)

    assert encoding.state is JobState.ENCODING
    assert [decode[decode.index("-ss") + 1] for decode in join_decodes] == [
        f"{JOIN_SECONDS - 20:.3f}",
        f"{7200 - 20:.3f}",
    ]
    report = json.loads(
        (JobPaths.create(settings, job.id).analysis / "clip-joins.json").read_text("utf-8")
    )
    assert report["verified"] is True and report["title_end_verified"] is True
    assert len(report["join_messages"]) == 4
    assert worker.process_one_stage(encoding).state is JobState.MUXING


def test_a_failed_decode_at_the_title_end_keeps_the_end_messages_only(context) -> None:
    _database, settings, _scan, _scanner, runner, worker = context
    _two_clip_disc(context)
    log = (
        "".join(_progress(t) for t in range(7150, 7180, 5))
        + JOIN_51
        + "".join(_progress(t) for t in range(7180, 7200, 5))
        + JOIN_51
    )
    _remux_logs(runner, log)
    real_run = runner.run

    def run(*args: Any, **kwargs: Any):
        command = tuple(os.fspath(item) for item in args[0])
        if "0:a?" in command and command[command.index("-ss") + 1] == f"{7200 - 20:.3f}":
            real_run(*args, **kwargs)
            raise ProcessFailure(
                ProcessResult(command, 1, 0.0, 0.0, None, kwargs.get("stderr_path"))
            )
        return real_run(*args, **kwargs)

    runner.run = run  # type: ignore[method-assign]
    job, ready = _ready(context)

    with pytest.raises(ReviewRequired, match="source corruption"):
        worker.process_one_stage(ready)
    report = json.loads(
        (JobPaths.create(settings, job.id).analysis / "clip-joins.json").read_text("utf-8")
    )
    assert report["verified"] is True and report["title_end_verified"] is False
    assert len(report["join_messages"]) == 2


def test_the_cut_last_packet_of_a_single_clip_title_is_verified(context) -> None:
    _database, _settings, _scan, _scanner, runner, worker = context
    log = "".join(_progress(t) for t in range(7170, 7200, 5)) + JOIN_51
    join_decodes = _remux_logs(runner, log)
    _job, ready = _ready(context)

    assert worker.process_one_stage(ready).state is JobState.ENCODING
    (decode,) = join_decodes
    assert decode[decode.index("-ss") + 1] == f"{7200 - 20:.3f}"


def _full_decode_log(runner, text: str) -> None:
    real_run = runner.run

    def run(*args: Any, **kwargs: Any):
        result = real_run(*args, **kwargs)
        stderr_path = kwargs.get("stderr_path")
        if stderr_path is not None and stderr_path.name == "full-decode.log":
            runner._write(stderr_path, text)
        return result

    runner.run = run  # type: ignore[method-assign]


def test_final_decode_notes_are_recorded_and_the_job_completes(context) -> None:
    database, settings, _scan, _scanner, runner, worker = context
    _full_decode_log(runner, "[truehd @ 0x7] mlpparse: Parity check failed.\n")
    job, ready = _ready(context)

    assert worker.process_job(ready).state is JobState.COMPLETED
    events = [
        event
        for event in database.list_events(job_id=job.id)
        if event.kind == "worker.full-decode-warning"
    ]
    assert len(events) == 1
    assert events[0].message == (
        "the full decode of the final file logged messages that are not decode errors; "
        "the job continues"
    )
    assert events[0].payload["warnings"] == ["[truehd @ 0x7] mlpparse: Parity check failed."]


def test_a_final_decode_error_still_stops_the_job(context) -> None:
    _database, settings, _scan, _scanner, runner, worker = context
    _full_decode_log(
        runner, "[h264 @ 0x2] concealing 120 DC, 120 AC, 120 MV errors in P frame\n"
    )
    job, ready = _ready(context)

    result = worker.process_job(ready)

    assert result.state is JobState.NEEDS_REVIEW
    assert result.resume_state is JobState.QC
    assert "full decode emitted an error-level diagnostic" in (result.status_message or "")
    report = json.loads(
        (
            JobPaths.create(settings, job.id).analysis
            / "container"
            / "full-decode-diagnostics.json"
        ).read_text("utf-8")
    )
    assert report["status"] == "needs_review"


def test_a_copied_join_packet_in_the_final_decode_is_excused(context) -> None:
    _database, _settings, _scan, _scanner, runner, worker = context
    _two_clip_disc(context)
    _remux_logs(runner, PROGRESS * 10 + JOIN + PROGRESS * 2)
    _full_decode_log(
        runner, "[matroska,webm @ 0x9] Packet corrupt (stream = 3, dts = NOPTS).\n"
    )
    _job, ready = _ready(context)

    assert worker.process_job(ready).state is JobState.COMPLETED


def test_a_join_report_from_before_3_7_3_is_not_decoded_again(context) -> None:
    from bdencode.worker import _recorded_output_sha256

    _database, settings, _scan, scanner, runner, worker = context
    _two_clip_disc(context)
    join_decodes = _remux_logs(runner, PROGRESS * 10 + JOIN + PROGRESS * 2)
    job, ready = _ready(context)
    worker.process_one_stage(ready)
    paths = JobPaths.create(settings, job.id)
    report_path = paths.analysis / "clip-joins.json"
    report = json.loads(report_path.read_text("utf-8"))
    # The 3.7.2 shape: no title end at all.
    legacy = {key: value for key, value in report.items() if not key.startswith("title_end")}
    legacy["schema_version"] = 1
    report_path.write_text(json.dumps(legacy), encoding="utf-8")
    join_decodes.clear()

    worker._verify_clip_joins(
        paths,
        scanner.result.playlists[0],
        _recorded_output_sha256(paths.stages / "reference-remux.json", paths.reference),
    )

    assert join_decodes == []
    assert json.loads(report_path.read_text("utf-8")) == legacy
