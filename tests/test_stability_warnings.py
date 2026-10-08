"""Measurement artefacts and FFmpeg-build differences warn; real defects stop."""

from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from bdencode.media.bluray import (
    LIBBLURAY_SCAN_ATTEMPTS,
    LIBBLURAY_SCAN_TIMEOUT_SECONDS,
    BluRayScanner,
    CaptureResult,
    PlaylistSegment,
    ToolCapabilities,
)
from bdencode.models import JobState
from bdencode.mux import (
    FinalTrackPolicy,
    FinalVideoPolicy,
    assess_ffprobe_stream_policy,
    validate_ffprobe_stream_policy,
)
from bdencode.qc import evaluate_video_completeness, require_video_completeness
from bdencode.qc.crop import verify_crop_against_full_decode
from bdencode.qc.subtitle import (
    SubtitleDecodeVerdict,
    assess_final_subtitle_decode,
    classify_subtitle_decode_stderr,
    subtitle_event_count_tolerance,
)
from bdencode.qc.video import CropMargins
from bdencode.queue import JobQueue
from bdencode.worker import JobPaths, PipelineWorker, _title_duration_is_estimate

from test_worker import (  # noqa: F401
    FAKE_REFERENCE_FRAMES,
    FakeRunner,
    _enqueue,
    _selection,
    context,
)
from test_worker_crop_scan import _line, _ready_job, _write_crop_logs


# --- 1. crop verification: a flash in the bar is not a cut ------------------


def _frame_line(t: float, width: int, height: int, x: int, y: int) -> str:
    return _line(t, width, height, x, y)


def _scope_film(seconds: int, fps: int = 24) -> list[str]:
    return [
        _frame_line(index / fps, 1920, 804, 0, 138) for index in range(seconds * fps)
    ]


def _insert(lines: list[str], at: int, frames: int, fps: int = 24) -> list[str]:
    inserted = [
        _frame_line((at + index) / fps, 1920, 1080, 0, 0) for index in range(frames)
    ]
    return lines[:at] + inserted + lines[at + frames :]


def test_one_bright_frame_in_the_bar_is_a_warning_not_a_cut() -> None:
    log = "\n".join(_insert(_scope_film(60), 24 * 30, 1))

    verification = verify_crop_against_full_decode(
        log, CropMargins(0, 138, 0, 138), source_width=1920, source_height=1080
    )

    assert verification.passed
    assert verification.flash_runs == 1 and verification.persistent_runs == 0
    assert verification.cut_frames == 1
    assert verification.envelope == CropMargins(0, 0, 0, 0)
    assert verification.first_cut_seconds is None
    assert verification.frame_interval_seconds == pytest.approx(1 / 24, abs=1e-5)
    assert "1 short flash(es)" in verification.summary()
    document = verification.to_dict()
    assert document["passed"] is True
    assert document["runs"][0]["persistent"] is False
    assert document["runs"][0]["start_seconds"] == 30.0


def test_scattered_flashes_never_add_up_to_a_cut() -> None:
    lines = _scope_film(120)
    for second in range(5, 115, 10):
        lines = _insert(lines, 24 * second, 3)

    verification = verify_crop_against_full_decode(
        "\n".join(lines), CropMargins(0, 138, 0, 138), source_width=1920, source_height=1080
    )

    assert verification.passed
    assert verification.flash_runs == 11 and verification.cut_frames == 33


def test_half_a_second_of_wider_picture_still_stops() -> None:
    crop = CropMargins(0, 138, 0, 138)
    eleven = verify_crop_against_full_decode(
        "\n".join(_insert(_scope_film(60), 24 * 30, 11)),
        crop,
        source_width=1920,
        source_height=1080,
    )
    twelve = verify_crop_against_full_decode(
        "\n".join(_insert(_scope_film(60), 24 * 30, 12)),
        crop,
        source_width=1920,
        source_height=1080,
    )

    assert eleven.passed and eleven.flash_runs == 1
    assert not twelve.passed
    assert twelve.first_cut_seconds == pytest.approx(30.0)
    assert "top 138px where the picture starts at 0px" in twelve.summary()


@pytest.mark.parametrize(
    ("fps", "frames"),
    [(24000 / 1001, 12), (24, 12), (25, 13), (60000 / 1001, 30)],
)
def test_half_a_second_is_counted_in_frames_at_every_rate(fps, frames) -> None:
    def log(cut: int) -> str:
        lines = []
        for index in range(1500):
            wide = 600 <= index < 600 + cut
            lines.append(
                _frame_line(
                    index / fps, 1920, 1080 if wide else 804, 0, 0 if wide else 138
                )
            )
        return "\n".join(lines)

    crop = CropMargins(0, 138, 0, 138)
    assert not verify_crop_against_full_decode(
        log(frames), crop, source_width=1920, source_height=1080
    ).passed
    assert verify_crop_against_full_decode(
        log(frames - 1), crop, source_width=1920, source_height=1080
    ).passed


def test_burnt_in_text_in_the_bar_for_seconds_stops() -> None:
    lines = _scope_film(60)
    # Subtitles burnt into the lower bar: the picture reaches 1060 for 3 s.
    for index in range(24 * 20, 24 * 23):
        lines[index] = _frame_line(index / 24, 1920, 922, 0, 138)

    verification = verify_crop_against_full_decode(
        "\n".join(lines), CropMargins(0, 138, 0, 138), source_width=1920, source_height=1080
    )

    assert not verification.passed
    assert "bottom 138px where the picture starts at 20px" in verification.summary()


def test_a_black_frame_breaks_a_run_of_cutting_frames() -> None:
    lines = _scope_film(60)
    lines = _insert(lines, 24 * 30, 6)
    # cropdetect prints negative sizes for an all-black frame.
    lines[24 * 30 + 6] = (
        "[Parsed_cropdetect_0 @ 0x1] x1:1919 x2:0 y1:1079 y2:0 w:-1918 h:-1078 "
        "x:1920 y:1080 pts:30250 t:30.250000 crop=-1918:-1078:1920:1080"
    )
    lines = _insert(lines, 24 * 30 + 7, 6)

    verification = verify_crop_against_full_decode(
        "\n".join(lines), CropMargins(0, 138, 0, 138), source_width=1920, source_height=1080
    )

    assert verification.passed
    assert verification.flash_runs == 2 and verification.cut_frames == 12


def test_a_cumulative_log_is_never_judged_more_leniently() -> None:
    # reset=0: after one bright frame the envelope stays wide to the end.
    lines = _scope_film(60)
    lines = lines[: 24 * 30] + [
        _frame_line(index / 24, 1920, 1080, 0, 0) for index in range(24 * 30, 24 * 60)
    ]

    verification = verify_crop_against_full_decode(
        "\n".join(lines), CropMargins(0, 138, 0, 138), source_width=1920, source_height=1080
    )

    assert not verification.passed


def test_a_flash_in_the_full_decode_keeps_the_job_running(context) -> None:
    database, settings, _scan, _scanner, runner, worker = context
    job, ready = _ready_job(context)
    letterbox = [_line(t, 1920, 804, 0, 138) for t in range(30)]
    full = [_line(t / 24, 1920, 804, 0, 138) for t in range(30 * 24)]
    full[24 * 12] = _line(12.0, 1920, 1080, 0, 0)
    _write_crop_logs(
        runner,
        keyframes="\n".join(letterbox) + "\n",
        full="\n".join(full) + "\n",
    )
    paths = JobPaths.create(settings, job.id)
    encoding = worker.process_one_stage(ready)
    assert encoding.state is JobState.ENCODING

    result = worker.process_one_stage(encoding)

    assert result.state is JobState.MUXING
    report = json.loads((paths.analysis / "crop-verification.json").read_text("utf-8"))
    assert report["status"] == "passed_with_warnings"
    assert report["flash_runs"] == 1
    assert (paths.stages / "crop-policy.json").exists()
    events = [
        item
        for item in database.list_events(job_id=job.id, limit=1000)
        if item.kind == "worker.crop-verification-warning"
    ]
    assert len(events) == 1
    assert events[0].message.startswith("crop verification: 1 short flash(es)")


# --- 2. final subtitle decode -------------------------------------------------


def _verdict(
    events: int, *, first: str = "1.0", last: str = "7190.0"
) -> SubtitleDecodeVerdict:
    return SubtitleDecodeVerdict(
        codec_name="hdmv_pgs_subtitle",
        stream_index=2,
        decoded_event_count=events,
        visible_event_count=events // 2,
        missing_timestamp_count=0,
        missing_duration_count=events,
        non_monotonic_timestamp_count=0,
        first_timestamp=Decimal(first),
        last_timestamp=Decimal(last),
        last_end_timestamp=None,
        passed=True,
        reasons=(),
    )


def test_subtitle_stderr_separates_known_pgs_quirks_from_defects() -> None:
    diagnostics = classify_subtitle_decode_stderr(
        "[pgssub @ 0x5581] Invalid object id 3\n"
        "    Last message repeated 2 times\n"
        "\n"
        "[pgssub @ 0x5581] Invalid palette id 1\n"
        "[matroska,webm @ 0x55] Read error at pos. 1234 (0x4d2)\n"
        "    Last message repeated 1 times\n"
    )

    assert diagnostics.informational_count == 4
    assert len(diagnostics.informational) == 2
    assert diagnostics.fatal == ("[matroska,webm @ 0x55] Read error at pos. 1234 (0x4d2)",)


def test_subtitle_event_count_tolerates_a_few_display_sets() -> None:
    assert subtitle_event_count_tolerance(20) == 5
    assert subtitle_event_count_tolerance(2000) == 100

    errors, warnings = assess_final_subtitle_decode(
        _verdict(1996),
        stderr_text="[pgssub @ 0x1] Invalid object id 7\n",
        packet_count=2000,
        title_duration_seconds=Decimal("7200"),
    )
    assert errors == ()
    assert any("known PGS display-set quirk" in item for item in warnings)
    assert any("within the tolerance of 100" in item for item in warnings)

    errors, _warnings = assess_final_subtitle_decode(
        _verdict(1000),
        stderr_text="",
        packet_count=2000,
        title_duration_seconds=Decimal("7200"),
    )
    assert errors and "differs from the sidecar packet count" in errors[0]


def test_subtitle_timestamps_get_a_couple_of_seconds_of_slack() -> None:
    title = Decimal("7200")
    passed = assess_final_subtitle_decode(
        _verdict(100, last="7200.05"), stderr_text="", packet_count=100,
        title_duration_seconds=title,
    )
    trailing = assess_final_subtitle_decode(
        _verdict(100, last="7201.8"), stderr_text="", packet_count=100,
        title_duration_seconds=title,
    )
    beyond = assess_final_subtitle_decode(
        _verdict(100, last="7210"), stderr_text="", packet_count=100,
        title_duration_seconds=title,
    )

    assert passed == ((), ())
    assert trailing[0] == ()
    assert trailing[1] == (
        "the last subtitle event starts 1.800 s after the title end, within the allowed slack",
    )
    assert beyond[0] and "outside the reviewed title" in beyond[0][0]


def test_unknown_subtitle_decoder_output_still_stops() -> None:
    errors, _warnings = assess_final_subtitle_decode(
        _verdict(100),
        stderr_text="decoder error despite rc=0\n",
        packet_count=100,
        title_duration_seconds=Decimal("7200"),
    )

    assert errors == (
        "subtitle decoder emitted error-level diagnostics: decoder error despite rc=0",
    )


# --- 3. frame-count and duration completeness ---------------------------------


def test_an_estimated_title_duration_only_warns() -> None:
    values: dict[str, Any] = {
        "fps_numerator": 24000,
        "fps_denominator": 1001,
        "title_duration_seconds": "7203.5",
        "final_video_duration_seconds": Decimal(172_627 * 1001) / Decimal(24000),
    }

    estimate = require_video_completeness(
        172_627, 172_627, title_duration_is_estimate=True, **values
    )
    assert estimate.passed and not estimate.duration_matches
    assert estimate.warnings and "estimated playlist/title duration" in estimate.warnings[0]
    assert estimate.to_dict()["title_duration_is_estimate"] is True

    exact = evaluate_video_completeness(172_627, 172_627, **values)
    assert not exact.passed and exact.warnings == ()
    # A lost frame is never excused by an estimate.
    missing = evaluate_video_completeness(
        172_627, 172_626, title_duration_is_estimate=True, **values
    )
    assert not missing.passed


def test_the_title_duration_is_an_estimate_without_libbluray_segments(context) -> None:
    _database, _settings, scan, _scanner, _runner, _worker = context
    playlist = scan.playlists[0]
    with_segments = replace(
        playlist,
        segments=(PlaylistSegment("00001", 0.0, 7200.0),),
    )

    assert _title_duration_is_estimate(scan, playlist)
    assert not _title_duration_is_estimate(replace(scan, playlists=(with_segments,)), with_segments)
    assert _title_duration_is_estimate(
        replace(
            scan,
            playlists=(with_segments,),
            warnings=(
                "No libbluray playlist backend is available; only the largest M2TS "
                "clip was inspected.",
            ),
        ),
        with_segments,
    )


def test_an_estimated_duration_mismatch_lets_the_job_finish(context) -> None:
    database, settings, scan, scanner, _runner, _worker = context
    # ffprobe's estimate is 3 s off the 172,627 frames of the reference.
    scanner.result = replace(
        scan, playlists=(replace(scan.playlists[0], duration_seconds=7203.0),)
    )
    runner = FakeRunner()
    worker = PipelineWorker(
        database,
        settings,
        scanner_factory=lambda _settings: scanner,
        runner_factory=lambda _paths: runner,
    )
    job = _enqueue(database, scan.source)
    claimed = JobQueue(database).claim_next()
    assert claimed is not None
    worker.process_one_stage(claimed)
    ready = database.set_selection(job.id, _selection())

    result = worker.process_job(ready)

    assert result.state is JobState.COMPLETED
    report = json.loads(
        (settings.job_root(job.id) / "analysis" / "video-frame-completeness.json").read_text(
            "utf-8"
        )
    )
    assert report["status"] == "passed_with_warnings"
    assert report["verdict"]["title_duration_is_estimate"] is True
    assert any(
        item.kind == "worker.video-duration-warning"
        for item in database.list_events(job_id=job.id, limit=1000)
    )


class _FlakyCapture:
    def __init__(self, outcomes: list[Any]) -> None:
        self.outcomes = outcomes
        self.timeouts: list[float] = []

    def capture(self, argv, *, timeout: float = 30, check: bool = True) -> Any:
        self.timeouts.append(timeout)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def test_the_libbluray_reader_gets_a_long_limit_and_a_second_try(tmp_path: Path) -> None:
    payload = CaptureResult(0, json.dumps({"playlists": [{"id": 1, "duration": 7200}]}))
    runner = _FlakyCapture(
        [subprocess.TimeoutExpired(["bdencode-libbluray-scan"], 600), payload]
    )
    scanner = BluRayScanner(
        runner=runner,
        capabilities=ToolCapabilities(libbluray_json="/usr/bin/bdencode-libbluray-scan"),
        source_root=tmp_path,
    )

    native = scanner._native_metadata(tmp_path)

    assert native["playlists"][0]["duration"] == 7200
    assert runner.timeouts == [LIBBLURAY_SCAN_TIMEOUT_SECONDS] * 2
    assert LIBBLURAY_SCAN_TIMEOUT_SECONDS >= 600 and LIBBLURAY_SCAN_ATTEMPTS == 2


def test_a_failed_libbluray_reader_falls_back_instead_of_failing(tmp_path: Path) -> None:
    runner = _FlakyCapture(
        [
            subprocess.TimeoutExpired(["bdencode-libbluray-scan"], 600),
            CaptureResult(1, ""),
        ]
    )
    scanner = BluRayScanner(
        runner=runner,
        capabilities=ToolCapabilities(libbluray_json="/usr/bin/bdencode-libbluray-scan"),
        source_root=tmp_path,
    )

    assert scanner._native_metadata(tmp_path) == {}
    assert len(runner.timeouts) == 2


# --- 4. ffprobe naming differences between FFmpeg builds ----------------------


def _hevc_stream(**updates: Any) -> dict[str, Any]:
    stream = {
        "codec_type": "video",
        "codec_name": "hevc",
        "profile": "Main 10",
        "level": 153,
        "width": 3840,
        "height": 1600,
        "pix_fmt": "yuv420p10le",
        "color_range": "tv",
        "color_space": "bt2020nc",
        "color_transfer": "smpte2084",
        "color_primaries": "bt2020",
        "chroma_location": "left",
    }
    stream.update(updates)
    return {"streams": [stream, {"codec_type": "audio", "codec_name": "eac3"}]}


def _hevc_policy(**updates: Any) -> FinalVideoPolicy:
    values: dict[str, Any] = {
        "codec_name": "hevc",
        "profile": "Main 10",
        "width": 3840,
        "height": 1600,
        "pixel_format": "yuv420p10le",
        "color_range": "tv",
        "color_space": "bt2020nc",
        "color_transfer": "smpte2084",
        "color_primaries": "bt2020",
        "chroma_location": "left",
        "level": 153,
    }
    values.update(updates)
    return FinalVideoPolicy(**values)


def _assess(document: dict[str, Any], policy: FinalVideoPolicy):
    return assess_ffprobe_stream_policy(
        document, video=policy, media_tracks=[FinalTrackPolicy("audio", "eac3")]
    )


@pytest.mark.parametrize("reported", ["unspecified", None, "left"])
def test_an_unsignalled_default_chroma_location_matches(reported) -> None:
    document = _hevc_stream(chroma_location=reported)
    if reported is None:
        del document["streams"][0]["chroma_location"]

    assert _assess(document, _hevc_policy()) == ((), ())


def test_an_unreported_non_default_chroma_location_only_warns() -> None:
    errors, warnings = _assess(
        _hevc_stream(chroma_location="unspecified"),
        _hevc_policy(chroma_location="topleft"),
    )

    assert errors == ()
    assert warnings == ("video chroma location is reported as unspecified (expected topleft)",)
    # An explicit different location is a real difference.
    errors, _warnings = _assess(
        _hevc_stream(chroma_location="topleft"), _hevc_policy(chroma_location="left")
    )
    assert errors == ("video chroma_location differs: expected left, got topleft",)


def test_profile_aliases_and_a_lower_level_only_warn() -> None:
    errors, warnings = _assess(
        _hevc_stream(profile="Main 12", pix_fmt="yuv420p12le", level=150),
        _hevc_policy(profile="Rext", pixel_format="yuv420p12le"),
    )

    assert errors == ()
    assert warnings == (
        "video profile is reported as Main 12 for Rext",
        "video level is reported as 150 (configured 153)",
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("color_primaries", "bt709"),
        ("color_transfer", "bt709"),
        ("color_space", "bt709"),
        ("pix_fmt", "yuv420p"),
        ("profile", "Main"),
        ("level", 156),
    ],
)
def test_real_colour_and_format_differences_still_stop(field, value) -> None:
    errors = validate_ffprobe_stream_policy(
        _hevc_stream(**{field: value}),
        video=_hevc_policy(),
        media_tracks=[FinalTrackPolicy("audio", "eac3")],
    )

    assert len(errors) == 1 and errors[0].startswith("video ")


# --- 5. a larger encode is a warning ------------------------------------------


def test_an_encode_larger_than_its_source_finishes_with_a_warning(context) -> None:
    database, settings, scan, scanner, _runner, _worker = context

    class LargerEncodeRunner(FakeRunner):
        def run(self, argv, **kwargs):
            result = super().run(argv, **kwargs)
            stdout_path = kwargs.get("stdout_path")
            if isinstance(stdout_path, Path) and stdout_path.name in {
                "encoded-video-packet-sizes.csv",
                "final-video-packet-sizes.csv",
            }:
                self._write(stdout_path, "1100\n" * FAKE_REFERENCE_FRAMES)
            return result

    runner = LargerEncodeRunner()
    worker = PipelineWorker(
        database,
        settings,
        scanner_factory=lambda _settings: scanner,
        runner_factory=lambda _paths: runner,
    )
    job = _enqueue(database, scan.source)
    claimed = JobQueue(database).claim_next()
    assert claimed is not None
    worker.process_one_stage(claimed)
    ready = database.set_selection(job.id, _selection())

    result = worker.process_job(ready)

    assert result.state is JobState.COMPLETED
    report = json.loads(
        (settings.job_root(job.id) / "analysis" / "video-efficiency.json").read_text("utf-8")
    )
    assert report["status"] == "passed_with_warnings"
    assert report["verdict"]["passed"] is False
    events = [
        item
        for item in database.list_events(job_id=job.id, limit=1000)
        if item.kind == "worker.video-efficiency-warning"
    ]
    assert len(events) == 1
    assert events[0].payload["encoded_bytes"] > events[0].payload["source_bytes"]
