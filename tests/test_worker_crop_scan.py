from __future__ import annotations

import json
import os
from typing import Any

import bdencode.worker as worker_module
from bdencode.models import JobState
from bdencode.queue import JobQueue
from bdencode.worker import JobPaths

from test_worker import (  # noqa: F401
    FakeRunner,
    _enqueue,
    _is_integrity_decode,
    _prepare_encoding,
    _selection,
    context,
)


def _line(t: float, width: int, height: int, x: int, y: int) -> str:
    return (
        f"[Parsed_cropdetect_0 @ 0x1] x1:{x} x2:{x + width - 1} y1:{y} "
        f"y2:{y + height - 1} w:{width} h:{height} x:{x} y:{y} pts:{int(t * 1000)} "
        f"t:{t:.6f} limit:0.094000 crop={width}:{height}:{x}:{y}"
    )


def _crop_scans(runner) -> list[tuple[str, ...]]:
    return [
        tuple(os.fspath(item) for item in command)
        for command in runner.commands
        if any("cropdetect=" in os.fspath(item) for item in command)
        and not _is_integrity_decode(command)
    ]


def _ready_job(context):
    database, _settings, scan, _scanner, _runner, worker = context
    job = _enqueue(database, scan.source)
    claimed = JobQueue(database).claim_next()
    assert claimed is not None
    worker.process_one_stage(claimed)
    return job, database.set_selection(job.id, _selection())


def _write_crop_logs(runner, *, keyframes: str, full: str) -> None:
    """Fake cropdetect output: ``keyframes`` for the keyframe scan, ``full`` otherwise."""

    real_run = runner.run

    def run(*args: Any, **kwargs: Any) -> None:
        real_run(*args, **kwargs)
        command = tuple(os.fspath(item) for item in args[0])
        stderr_path = kwargs.get("stderr_path")
        if stderr_path is None or not any("cropdetect=" in item for item in command):
            return
        runner._write(stderr_path, keyframes if "-skip_frame" in command else full)

    runner.run = run  # type: ignore[method-assign]


def test_preparation_scans_only_the_keyframes(context) -> None:
    _database, settings, _scan, _scanner, runner, _worker = context
    job, _encoding = _prepare_encoding(context)
    paths = JobPaths.create(settings, job.id)

    (scan,) = _crop_scans(runner)
    assert scan[scan.index("-skip_frame") + 1] == "nokey"
    report = json.loads((paths.analysis / "crop-policy.json").read_text("utf-8"))
    assert report["status"] == "passed"
    assert report["scan"] == "keyframes"
    assert (paths.logs / "crop-detect-keyframes.log").is_file()


def _real_runner_path(context, monkeypatch, *, gpu: bool) -> None:
    """Let the fake runner take the real-runner path (GPU probe and parallel scans)."""

    _database, _settings, _scan, _scanner, runner, _worker = context
    monkeypatch.setattr(worker_module, "CommandRunner", FakeRunner)
    monkeypatch.setattr(worker_module, "cuda_decode_available", lambda: gpu)
    monkeypatch.setattr(worker_module, "CROP_SCAN_SEGMENTS", 4)
    runner.set_interrupt_requested = lambda _callback: runner  # type: ignore[attr-defined]
    real_run = runner.run

    def run(argv, **kwargs):
        kwargs.pop("interrupt_requested", None)
        kwargs.pop("progress_probe", None)
        return real_run(argv, **kwargs)

    runner.run = run  # type: ignore[method-assign]


def test_with_a_gpu_the_keyframes_are_decoded_there_in_one_pass(context, monkeypatch) -> None:
    _database, _settings, _scan, _scanner, runner, _worker = context
    _real_runner_path(context, monkeypatch, gpu=True)

    _prepare_encoding(context)

    (scan,) = _crop_scans(runner)
    assert scan[scan.index("-hwaccel") + 1] == "cuda"
    assert "-skip_frame" in scan and "-ss" not in scan


def test_without_a_gpu_the_cpu_scans_time_ranges_side_by_side(context, monkeypatch) -> None:
    _database, settings, _scan, _scanner, runner, _worker = context
    _real_runner_path(context, monkeypatch, gpu=False)

    job, _encoding = _prepare_encoding(context)

    scans = _crop_scans(runner)
    assert len(scans) == 4
    assert all("-hwaccel" not in scan and "-skip_frame" in scan for scan in scans)
    starts = sorted(float(scan[scan.index("-ss") + 1]) for scan in scans)
    assert starts[0] == 0 and len(set(starts)) == 4
    paths = JobPaths.create(settings, job.id)
    # The ranges' logs become one log; the parts are removed.
    combined = (paths.logs / "crop-detect-keyframes.log").read_text("utf-8")
    assert combined.count("crop=") == 4 * 30
    assert not list(paths.logs.glob("crop-detect-keyframes-*.log"))


def test_a_short_title_gets_at_least_a_minute_per_range(context, monkeypatch) -> None:
    _database, settings, _scan, _scanner, runner, worker = context
    _real_runner_path(context, monkeypatch, gpu=False)
    job, _encoding = _prepare_encoding(context)
    paths = JobPaths.create(settings, job.id)
    before = len(_crop_scans(runner))

    worker._run_keyframe_crop_scan(paths, paths.logs / "short-title.log", 150.0)

    assert len(_crop_scans(runner)[before:]) == 2


def test_too_few_keyframes_fall_back_to_scanning_every_frame(context) -> None:
    _database, settings, _scan, _scanner, runner, worker = context
    job, ready = _ready_job(context)
    sparse = "".join(_line(t * 10, 1920, 804, 0, 138) + "\n" for t in range(5))
    dense = "".join(_line(t, 1920, 804, 0, 138) + "\n" for t in range(60))
    _write_crop_logs(runner, keyframes=sparse, full=dense)
    paths = JobPaths.create(settings, job.id)

    worker._prepare(ready, paths, advance=False)

    keyframe_scan, full_scan = _crop_scans(runner)
    assert "-skip_frame" in keyframe_scan
    assert "-skip_frame" not in full_scan
    report = json.loads((paths.analysis / "crop-policy.json").read_text("utf-8"))
    assert report["scan"] == "full"
    assert report["decision"]["requested"]["top"] == 138


def test_the_full_decode_beside_the_encode_verifies_the_crop(context) -> None:
    _database, settings, _scan, _scanner, runner, worker = context
    job, encoding = _prepare_encoding(context)

    result = worker.process_one_stage(encoding)

    assert result.state is JobState.MUXING
    paths = JobPaths.create(settings, job.id)
    (integrity,) = [
        tuple(os.fspath(item) for item in command)
        for command in runner.commands
        if _is_integrity_decode(command)
    ]
    assert integrity[integrity.index("-vf") + 1].startswith("cropdetect=")
    verification = json.loads(
        (paths.analysis / "crop-verification.json").read_text("utf-8")
    )
    assert verification["status"] == "passed"
    assert verification["observations"] == 30


def test_a_crop_that_cuts_a_short_wider_shot_stops_the_job_and_rescans_every_frame(
    context,
) -> None:
    _database, settings, _scan, _scanner, runner, worker = context
    job, ready = _ready_job(context)
    letterbox = [_line(t, 1920, 804, 0, 138) for t in range(30)]
    # Half a second of full-frame picture between two keyframes: only a full
    # decode sees it.
    full_frame = [_line(30 + t / 24, 1920, 1080, 0, 0) for t in range(12)]
    _write_crop_logs(
        runner,
        keyframes="\n".join(letterbox) + "\n",
        full="\n".join(letterbox + full_frame) + "\n",
    )
    paths = JobPaths.create(settings, job.id)
    encoding = worker.process_one_stage(ready)
    assert encoding.state is JobState.ENCODING
    chosen = json.loads((paths.analysis / "crop-policy.json").read_text("utf-8"))
    assert chosen["decision"]["requested"]["top"] == 138

    result = worker.process_job(encoding)

    assert result.state is JobState.NEEDS_REVIEW
    assert "crop verification" in (result.status_message or "") + (result.error or "")
    verification = json.loads(
        (paths.analysis / "crop-verification.json").read_text("utf-8")
    )
    assert verification["status"] == "needs_review"
    assert verification["first_cut_seconds"] == 30.0
    assert not (paths.stages / "crop-policy.json").exists()

    # A restart prepares again: every frame is scanned and nothing is cut.
    worker._prepare(ready, paths, advance=False)

    assert "-skip_frame" not in _crop_scans(runner)[-1]
    report = json.loads((paths.analysis / "crop-policy.json").read_text("utf-8"))
    assert report["scan"] == "full"
    assert report["decision"]["requested"] == {
        "left": 0,
        "top": 0,
        "right": 0,
        "bottom": 0,
    }
