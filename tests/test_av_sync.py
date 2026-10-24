"""Audio placement: encoder priming in the plan, and the independent sync check (3.12.0)."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import numpy as np

from bdencode.mux import encoder_priming_seconds, plan_common_zero_timeline
from bdencode.qc import av_sync

RATE = av_sync.SYNC_RATE


def noise(seconds: float = 3.0, seed: int = 3) -> np.ndarray:
    return (np.random.default_rng(seed).standard_normal(int(seconds * RATE)) * 0.1).astype("<f4")


def delayed(samples: np.ndarray, by: int) -> np.ndarray:
    if by >= 0:
        return np.concatenate((np.zeros(by, dtype=samples.dtype), samples[: len(samples) - by]))
    return np.concatenate((samples[-by:], np.zeros(-by, dtype=samples.dtype)))


def test_ac3_and_eac3_carry_256_samples_of_priming() -> None:
    assert encoder_priming_seconds("ac3", 48000) == Decimal(256) / 48000
    assert encoder_priming_seconds("eac3", 48000) == Decimal(256) / 48000
    assert encoder_priming_seconds("flac", 48000) == 0
    assert encoder_priming_seconds("dts", 48000) == 0


def test_a_primed_track_moves_the_common_zero_instead_of_losing_a_frame() -> None:
    plan = plan_common_zero_timeline(
        "0", ["0", "0"],
        sidecar_start_times=["0", "0"],
        sidecar_priming_seconds=[Decimal(256) / 48000, 0],
    )

    # Every stream starts 5 ms later; the AC-3 packets stay at 0, so its
    # content (after 5.333 ms of priming) lands 0.333 ms after the others.
    assert plan.origin_seconds == Decimal("-0.005")
    assert plan.video_sync_offset_ms == 5
    assert plan.track_sync_offsets_ms == (Decimal(0), Decimal(5))
    assert plan.expected_start_seconds == (Decimal("0.005"), Decimal(0), Decimal("0.005"))


def test_offsets_are_whole_milliseconds_and_unprimed_plans_are_unchanged() -> None:
    plan = plan_common_zero_timeline("0.042", ["0.042"], sidecar_start_times=["0.042"])

    assert plan.origin_seconds == Decimal("0.042")
    assert plan.track_sync_offsets_ms == (Decimal(-42),)
    assert plan.video_sync_offset_ms == 0
    rounded = plan_common_zero_timeline("0", ["0"], sidecar_start_times=["0.0004"])
    assert rounded.track_sync_offsets_ms == (Decimal(0),)


def test_the_lag_of_a_delayed_sound_is_found_to_the_sample() -> None:
    source = noise()
    for by in (0, 256, -48, 1200):
        lag, correlation, rms = av_sync.measure_lag(source, delayed(source, by))
        assert lag == by
        assert correlation > 0.9 and rms > 0.05


def test_windows_decide_the_verdict() -> None:
    source = noise()
    good = av_sync.window_result(Decimal(5), Decimal(5), source, delayed(source, 24))  # 0.5 ms
    late = av_sync.window_result(Decimal(5), Decimal(5), source, delayed(source, 256))  # 5.3 ms
    quiet = av_sync.window_result(Decimal(5), Decimal(5), source * 0, source * 0)

    assert av_sync.judge([good, quiet]).status == "passed"
    verdict = av_sync.judge([good, late])
    assert verdict.status == "out_of_sync" and Decimal(verdict.lag_ms) == Decimal("5.333")
    assert av_sync.judge([quiet]).status == "inconclusive"
    assert quiet.reason == "too_quiet"


def test_unrelated_sound_is_not_a_match() -> None:
    result = av_sync.window_result(Decimal(5), Decimal(5), noise(seed=1), noise(seed=2))
    assert not result.conclusive and result.reason == "no_clear_match"


def test_windows_sit_inside_the_title_and_the_command_decodes_mono_48k(tmp_path: Path) -> None:
    assert av_sync.window_starts(Decimal(5400)) == (Decimal("1080.0"), Decimal("2700.0"), Decimal("4320.0"))
    assert av_sync.window_starts(Decimal(20)) == (Decimal(0),)
    command = av_sync.sync_window_command(
        tmp_path / "final.mkv", 1, Decimal("2700"), tmp_path / "w.f32", input_args=["-drc_scale", "0"]
    )
    assert command[command.index("-ss") + 1] == "2700.000000"
    assert command.index("-ss") < command.index("-i")
    # An absolute timestamp, not a distance from the file's start time (a
    # reference starting at 0.042 s measured a correct mux one frame late).
    assert command[command.index("-seek_timestamp") + 1] == "1"
    assert command.index("-seek_timestamp") < command.index("-ss")
    assert command[command.index("-map") + 1] == "0:a:1"
    assert ["-ac", "1", "-ar", "48000", "-f", "f32le"] == command[command.index("-ac"):command.index("-f") + 2]
