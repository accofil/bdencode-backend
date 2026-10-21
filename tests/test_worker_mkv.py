"""An MKV remux source through the worker: scan, reference copy, full pipeline."""

from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

import bdencode.worker as worker_module
from bdencode.media.bluray import MediaStream
from bdencode.media.mkv_source import mkv_fingerprint
from bdencode.models import JobState
from bdencode.process import ProcessInterrupted
from bdencode.queue import JobQueue
from bdencode.worker import (
    JobPaths,
    PipelineWorker,
    ReviewRequired,
    _mkv_reference_inputs,
    _recorded_output_sha256,
    _valid_stage,
    sha256_file,
)

from test_mkv_source import BD_PROBE
from test_worker import FakeRunner, _enqueue, _selection, context  # noqa: F401

REMUX_BYTES = b"\x1a\x45\xdf\xa3" + bytes(range(256)) * 64


def _no_disc_commands(commands) -> None:
    for command in commands:
        assert "-playlist" not in command, command
        assert not any("bluray:" in str(item) for item in command), command


def _mkv_context(context):
    database, settings, scan, scanner, runner, worker = context
    source = settings.source_roots[0] / "Movie 2026 1080p Blu-ray Remux.mkv"
    source.write_bytes(REMUX_BYTES)
    video = scan.playlists[0].streams[0]
    mkv_scan = replace(
        scan,
        source=source.resolve(),
        source_kind="mkv",
        fingerprint=mkv_fingerprint(source.resolve()),
        playlists=(
            replace(
                scan.playlists[0],
                streams=(replace(video, id="video:0", pid=None),),
            ),
        ),
    )
    scanner.result = mkv_scan
    return database, settings, mkv_scan, runner, worker


def _ready(database, worker, scan):
    job = _enqueue(database, scan.source)
    claimed = JobQueue(database).claim_next()
    assert claimed is not None
    awaiting = worker.process_one_stage(claimed)
    assert awaiting.state is JobState.AWAITING_SELECTION
    return job, database.set_selection(job.id, _selection())


def test_prepare_copies_an_mkv_source_as_the_reference(context) -> None:
    database, settings, scan, runner, worker = _mkv_context(context)
    job, ready = _ready(database, worker, scan)

    encoding = worker.process_one_stage(ready)

    assert encoding.state is JobState.ENCODING
    paths = JobPaths.create(settings, job.id)
    assert paths.reference.read_bytes() == REMUX_BYTES
    assert not paths.reference.is_symlink()
    assert not (paths.work / "reference.mkv.partial").exists()
    marker = paths.stages / "reference-remux.json"
    digest = _recorded_output_sha256(marker, paths.reference)
    assert digest is not None
    worker_module._HASH_CACHE.clear()
    assert digest == sha256_file(paths.reference)
    inputs = _mkv_reference_inputs(scan, "00001")
    assert inputs["source_kind"] == "mkv"
    assert inputs["source_file"]["size_bytes"] == len(REMUX_BYTES)
    assert _valid_stage(marker, inputs, [paths.reference])
    events = {event.kind for event in database.list_events(job_id=job.id)}
    assert "worker.mkv-reference-copied" in events
    _no_disc_commands(runner.commands)
    # Every reference command reads the copy, never the source file itself.
    assert not any(os.fspath(scan.source) in command for command in runner.commands)
    stored = database.list_scans(job_id=job.id, limit=1)[0].result
    assert stored["source_kind"] == "mkv"


def test_a_changed_mkv_source_invalidates_the_copy(context) -> None:
    database, settings, scan, _runner, worker = _mkv_context(context)
    job, ready = _ready(database, worker, scan)
    worker.process_one_stage(ready)
    paths = JobPaths.create(settings, job.id)
    marker = paths.stages / "reference-remux.json"
    assert _valid_stage(marker, _mkv_reference_inputs(scan, "00001"), [paths.reference])

    scan.source.write_bytes(REMUX_BYTES + b"replaced")

    assert not _valid_stage(marker, _mkv_reference_inputs(scan, "00001"), [paths.reference])
    with pytest.raises(ReviewRequired, match="changed since the scan"):
        worker._prepare(database.get_job(job.id), paths, advance=False)


def test_operator_control_stops_the_copy(context, monkeypatch) -> None:
    database, settings, scan, _runner, worker = _mkv_context(context)
    job, ready = _ready(database, worker, scan)
    paths = JobPaths.create(settings, job.id)
    monkeypatch.setattr(worker_module, "MKV_COPY_BLOCK_BYTES", 1024)
    monkeypatch.setattr(worker, "_process_interrupt_requested", lambda _job_id: True)

    with pytest.raises(ProcessInterrupted):
        worker._materialise_mkv_reference(ready, paths, scan)

    assert not paths.reference.exists()
    assert not (paths.work / "reference.mkv.partial").exists()


def test_mocked_pipeline_completes_an_mkv_job_without_disc_commands(context) -> None:
    database, settings, scan, runner, worker = _mkv_context(context)
    job, ready = _ready(database, worker, scan)

    result = worker.process_job(ready)

    assert result.state is JobState.COMPLETED, result.error or result.status_message
    final = settings.completed_root / "Movie.2026.1080p.BluRay.x264" / "Movie.2026.1080p.BluRay.x264.mkv"
    assert final.is_file()
    _no_disc_commands(runner.commands)
    # The source itself is only ever read by the copy; nothing ran against it.
    assert not any(os.fspath(scan.source) in command for command in runner.commands)
    assert scan.source.read_bytes() == REMUX_BYTES


class CaptureRunner(FakeRunner):
    """FakeRunner that also answers the scanner's ffprobe captures."""

    def capture(self, argv, *, timeout: float = 30, check: bool = True):
        command = tuple(os.fspath(item) for item in argv)
        self.commands.append(command)
        document = {"frames": []} if "-show_frames" in command else BD_PROBE
        return SimpleNamespace(returncode=0, stdout=json.dumps(document), stderr="")


def test_the_scan_stage_uses_the_mkv_scanner(context, monkeypatch) -> None:
    database, settings, _scan, _scanner, _runner, _worker = context
    source = settings.source_roots[0] / "The Florist 2026 1080p Blu-ray Remux.mkv"
    source.write_bytes(REMUX_BYTES)
    runner = CaptureRunner()
    worker = PipelineWorker(database, settings, runner_factory=lambda _paths: runner)
    monkeypatch.setattr(worker_module.shutil, "which", lambda name: name)

    def no_layer_probe(*_args, **_kwargs):
        raise AssertionError("a remux has no Dolby Vision layer stream to probe")

    monkeypatch.setattr(worker, "_detect_dolby_vision_layers", no_layer_probe)
    job = _enqueue(database, source)
    claimed = JobQueue(database).claim_next()
    assert claimed is not None

    awaiting = worker.process_one_stage(claimed)

    assert awaiting.state is JobState.AWAITING_SELECTION, awaiting.error
    paths = JobPaths.create(settings, job.id)
    document = json.loads(paths.scan_json.read_text(encoding="utf-8"))
    assert document["source_kind"] == "mkv"
    assert document["source"] == str(source.resolve())
    assert [item["id"] for item in document["playlists"][0]["streams"]] == [
        "video:0", "audio:1", "subtitle:2", "subtitle:3", "subtitle:4",
    ]
    _no_disc_commands(runner.commands)
    # The track analysis reads the file itself by stream index.
    stored = database.list_scans(job_id=job.id, limit=1)[0].result
    analysis = stored["playlists"][0]["track_analysis"]
    assert analysis.get("reason") != "mkv_source_unsupported"
    window_reads = [
        command for command in runner.commands
        if command and command[0] == "ffmpeg" and any(str(item).endswith(".wav") or str(item).endswith(".mks") for item in command)
    ]
    assert window_reads and all(command[command.index("-i") + 1] == str(source.resolve()) for command in window_reads)


def test_planner_reads_an_mkv_source_file_directly(context) -> None:
    _database, _settings, scan, _runner, _worker = _mkv_context(context)
    from bdencode.media.planner import EncodePlanner

    args = EncodePlanner._input_args(scan, scan.playlists[0], 1)
    assert args == ("-i", os.fspath(scan.source))
    disc = replace(scan, source=scan.source.parent, source_kind="disc")
    assert EncodePlanner._input_args(disc, scan.playlists[0], 1)[:2] == ("-playlist", "1")


def test_text_subtitle_flag_is_only_for_subtitles() -> None:
    from bdencode.media.bluray import StreamKind

    with pytest.raises(ValueError, match="text subtitles"):
        MediaStream(id="audio:1", index=1, pid=None, kind=StreamKind.AUDIO, codec="aac", text_subtitle=True)
