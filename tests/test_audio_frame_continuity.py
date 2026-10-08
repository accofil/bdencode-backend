from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from bdencode.audio import effective_audio_policy
from bdencode.qc.audio import (
    audio_frame_continuity_probe_command,
    compare_audio_frame_continuity,
    parse_audio_frame_continuity,
)


def _frame_document(
    pts_values: tuple[str, ...] = ("10.000", "10.032", "10.064", "10.096"),
    *,
    samples_per_frame: int = 1536,
    counted_frames: int | None = None,
) -> dict[str, object]:
    return {
        "streams": [
            {
                "index": 1,
                "codec_type": "audio",
                "codec_name": "eac3",
                "sample_rate": "48000",
                "time_base": "1/1000",
                "nb_read_frames": str(
                    len(pts_values) if counted_frames is None else counted_frames
                ),
            }
        ],
        "frames": [
            {
                "media_type": "audio",
                "stream_index": 1,
                "pts_time": pts,
                "nb_samples": samples_per_frame,
                "sample_rate": "48000",
            }
            for pts in pts_values
        ],
    }


def test_audio_frame_probe_is_full_decode_counted_and_codec_aware() -> None:
    command = audio_frame_continuity_probe_command(
        Path("input.eac3"), input_codec="E-AC-3"
    )

    assert command[:6] == [
        "ffprobe",
        "-v",
        "error",
        "-drc_scale",
        "0",
        "-select_streams",
    ]
    assert "-count_frames" in command
    assert "-show_frames" in command
    assert "-show_streams" in command
    entries = command[command.index("-show_entries") + 1]
    assert "nb_read_frames" in entries
    assert "pts_time" in entries
    assert "nb_samples" in entries
    assert "sample_rate" in entries
    assert command[-1] == "input.eac3"


def test_audio_frame_parser_builds_continuous_normalized_sample_cursor() -> None:
    evidence = parse_audio_frame_continuity(_frame_document())

    assert evidence.continuous
    assert evidence.frame_count == 4
    assert evidence.first_pts_seconds == Decimal("10.000")
    assert evidence.normalized_end_seconds == Decimal("0.128")
    assert evidence.total_samples == 6144
    assert evidence.timestamp_tolerance_samples == 48
    assert evidence.discontinuity_frame_indexes == ()


def test_ffprobe_without_frame_sample_rates_uses_the_stream_rate() -> None:
    """Debian 12's ffprobe 5.1 prints no per-frame sample_rate."""

    document = _frame_document()
    for frame in document["frames"]:  # type: ignore[union-attr]
        del frame["sample_rate"]

    evidence = parse_audio_frame_continuity(document)

    assert evidence.continuous
    assert evidence.sample_rate == 48000
    assert evidence.total_samples == 6144
    assert evidence.frame_sample_rates_reported is False
    assert evidence.to_dict()["frame_sample_rates_reported"] is False
    assert parse_audio_frame_continuity(_frame_document()).frame_sample_rates_reported is True


def test_a_reported_rate_change_or_a_partly_reported_walk_still_fails() -> None:
    changed = _frame_document()
    changed["frames"][2]["sample_rate"] = "44100"  # type: ignore[index]
    with pytest.raises(ValueError, match="sample rate changed"):
        parse_audio_frame_continuity(changed)

    partial = _frame_document()
    del partial["frames"][1]["sample_rate"]  # type: ignore[index]
    with pytest.raises(ValueError, match="missing for some frames"):
        parse_audio_frame_continuity(partial)


def test_audio_frame_parser_rejects_truncated_counted_evidence() -> None:
    with pytest.raises(ValueError, match="frame count mismatch"):
        parse_audio_frame_continuity(_frame_document(counted_frames=5))


def test_internal_gap_and_overlap_fail_with_same_endpoint_and_total_samples() -> None:
    source = parse_audio_frame_continuity(_frame_document())
    # Frame 1 moves forward by exactly one E-AC-3 frame, then frame 2 returns
    # to the original timeline.  The track endpoint and payload sample count
    # are unchanged, but there is one internal gap followed by one overlap.
    broken = parse_audio_frame_continuity(
        _frame_document(("10.000", "10.064", "10.064", "10.096"))
    )
    policy = effective_audio_policy(
        "eac3",
        source_codec="truehd",
        source_channels=8,
        source_sample_rate=48_000,
    )

    verdict = compare_audio_frame_continuity(source, broken, policy)

    assert broken.gap_count == 1
    assert broken.overlap_count == 1
    assert broken.total_samples == source.total_samples
    assert broken.normalized_end_seconds == source.normalized_end_seconds
    assert verdict.total_sample_delta == 0
    assert verdict.normalized_end_delta_seconds == 0
    assert verdict.total_samples_within_tolerance
    assert verdict.normalized_end_within_tolerance
    assert not verdict.encoded_continuous
    assert not verdict.passed


def test_lossy_total_sample_padding_is_bounded_by_codec_policy() -> None:
    source = parse_audio_frame_continuity(_frame_document())
    one_frame_padded = parse_audio_frame_continuity(
        _frame_document(("10.000", "10.032", "10.064", "10.096", "10.128"))
    )
    policy = effective_audio_policy(
        "eac3",
        source_codec="truehd",
        source_channels=8,
        source_sample_rate=48_000,
    )

    verdict = compare_audio_frame_continuity(source, one_frame_padded, policy)

    assert verdict.tolerance_samples == 3072
    assert verdict.total_sample_delta == 1536
    assert verdict.passed


def test_a_frame_without_sample_rate_among_reported_ones_fails() -> None:
    document = _frame_document()
    frames = document["frames"]
    assert isinstance(frames, list)
    assert isinstance(frames[1], dict)
    del frames[1]["sample_rate"]

    with pytest.raises(ValueError, match="missing for some frames"):
        parse_audio_frame_continuity(document)


@pytest.mark.parametrize("invalid_count", [True, 1536.0])
def test_audio_frame_integer_evidence_is_strict(invalid_count: object) -> None:
    document = _frame_document()
    frames = document["frames"]
    assert isinstance(frames, list)
    assert isinstance(frames[1], dict)
    frames[1]["nb_samples"] = invalid_count

    with pytest.raises(ValueError, match="integer audio-frame evidence|malformed"):
        parse_audio_frame_continuity(document)


def _clip_track(
    *,
    jump_seconds: str = "0",
    jump_at_frame: int = 100,
    frames: int = 200,
) -> tuple[str, ...]:
    """A 1536-sample track whose timestamps jump once (a clip join)."""

    jump = Decimal(jump_seconds)
    return tuple(
        str(
            Decimal("10.000")
            + Decimal("0.032") * index
            + (jump if index >= jump_at_frame else Decimal(0))
        )
        for index in range(frames)
    )


def _eac3_policy():
    return effective_audio_policy(
        "eac3",
        source_codec="truehd",
        source_channels=8,
        source_sample_rate=48_000,
    )


# Frame 100 starts 3.2 s after the first frame: the playlist's clip join.
_JOIN = (Decimal("3.2"),)


@pytest.mark.parametrize("jump", ("0.010", "-0.012", "0.200"))
def test_gap_or_overlap_at_a_clip_join_is_recorded_not_failed(jump: str) -> None:
    source = parse_audio_frame_continuity(
        _frame_document(_clip_track(jump_seconds=jump))
    )
    encoded = parse_audio_frame_continuity(
        _frame_document(_clip_track(jump_seconds=jump))
    )

    verdict = compare_audio_frame_continuity(
        source, encoded, _eac3_policy(), join_seconds=_JOIN
    )

    assert not source.continuous
    assert len(source.discontinuities) == 1
    assert source.discontinuities[0].delta_samples == int(Decimal(jump) * 48_000)
    assert verdict.passed
    assert verdict.source_unexcused_discontinuities == 0
    assert verdict.encoded_unexcused_discontinuities == 0
    assert verdict.excused_join_discontinuities == 2
    assert verdict.total_sample_delta == 0


def test_an_encode_that_closes_a_join_gap_keeps_its_samples_and_passes() -> None:
    source = parse_audio_frame_continuity(
        _frame_document(_clip_track(jump_seconds="0.200"))
    )
    closed = parse_audio_frame_continuity(_frame_document(_clip_track()))

    verdict = compare_audio_frame_continuity(
        source, closed, _eac3_policy(), join_seconds=_JOIN
    )

    assert closed.continuous
    assert verdict.normalized_end_delta_seconds == Decimal("-0.200")
    assert verdict.join_slack_seconds == Decimal("0.2")
    assert verdict.normalized_end_within_tolerance
    assert verdict.passed
    # Without the join the same endpoint difference is a failure.
    assert not compare_audio_frame_continuity(source, closed, _eac3_policy()).passed


def test_a_gap_away_from_every_clip_join_still_fails() -> None:
    source = parse_audio_frame_continuity(
        _frame_document(_clip_track(jump_seconds="0.010"))
    )

    verdict = compare_audio_frame_continuity(
        source, source, _eac3_policy(), join_seconds=(Decimal("1.5"),)
    )

    assert not verdict.passed
    assert verdict.source_unexcused_discontinuities == 1
    assert verdict.excused_join_discontinuities == 0


def test_a_join_gap_beyond_half_a_second_still_fails() -> None:
    source = parse_audio_frame_continuity(
        _frame_document(_clip_track(jump_seconds="0.600"))
    )

    verdict = compare_audio_frame_continuity(
        source, source, _eac3_policy(), join_seconds=_JOIN
    )

    assert not verdict.passed
    assert verdict.source_unexcused_discontinuities == 1


def test_lost_sound_at_a_join_fails_on_the_total_sample_count() -> None:
    source = parse_audio_frame_continuity(
        _frame_document(_clip_track(jump_seconds="0.010"))
    )
    # The encode dropped three frames at the join and kept the timeline.
    shortened = _clip_track(jump_seconds="0.010")
    shortened = shortened[:100] + shortened[103:]
    encoded = parse_audio_frame_continuity(_frame_document(shortened))

    verdict = compare_audio_frame_continuity(
        source, encoded, _eac3_policy(), join_seconds=_JOIN
    )

    assert verdict.total_sample_delta == -3 * 1536
    assert not verdict.total_samples_within_tolerance
    assert not verdict.passed


def test_join_evidence_is_manifest_serializable() -> None:
    source = parse_audio_frame_continuity(
        _frame_document(_clip_track(jump_seconds="0.010"))
    )
    verdict = compare_audio_frame_continuity(
        source, source, _eac3_policy(), join_seconds=_JOIN
    )

    assert source.to_dict()["discontinuities"] == [
        {"position_seconds": "3.210", "delta_samples": 480}
    ]
    value = verdict.to_dict()
    assert value["join_seconds"] == ["3.2"]
    assert value["excused_join_discontinuities"] == 2
    assert value["join_slack_seconds"] == "0.02"
    assert value["passed"] is True
