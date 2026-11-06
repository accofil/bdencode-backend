from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from bdencode.qc.crop import (
    DEFAULT_TIGHT_CROP_SUPPORT_RATIO,
    automatic_crop,
    count_crop_observations,
    CropDetectionEvidence,
    CropPolicyError,
    distributed_cropdetect_commands,
    full_title_cropdetect_command,
    keyframe_cropdetect_commands,
    parse_stable_cropdetect,
    plan_cropdetect_intervals,
    tightened_edges,
    validate_operator_crop,
    variable_aspect_evidence,
    verify_crop_against_full_decode,
)
from bdencode.qc.video import CropMargins


def _crop_lines(value: str, count: int) -> list[str]:
    return [f"frame={index} crop={value}" for index in range(count)]


def _evidence(crop: CropMargins) -> CropDetectionEvidence:
    return CropDetectionEvidence(
        crop=crop,
        source_width=1920,
        source_height=1080,
        observations=100,
        supporting_observations=92,
        support_ratio=Decimal("0.92"),
        jitter_pixels=2,
    )


def test_cropdetect_plan_is_bounded_and_distributed_across_title() -> None:
    intervals = plan_cropdetect_intervals(7200)
    assert len(intervals) == 12
    assert {interval.duration_seconds for interval in intervals} == {Decimal("2")}
    assert intervals[0].start_seconds == Decimal("299")
    assert intervals[-1].start_seconds == Decimal("6899")
    assert sum(item.duration_seconds for item in intervals) == Decimal("24")

    commands = distributed_cropdetect_commands(Path("reference.mkv"), 7200)
    assert len(commands) == 12
    for interval, command in zip(intervals, commands):
        assert command.index("-ss") < command.index("-i")
        assert Decimal(command[command.index("-ss") + 1]) == max(
            Decimal(0), interval.start_seconds - Decimal(12)
        )
        output_seek = command.index("-ss", command.index("-i") + 1)
        assert Decimal(command[output_seek + 1]) == Decimal(12)
        assert command[command.index("-t") + 1] == "2"
        assert command[command.index("-map") + 1] == "0:v:0"
        assert command[command.index("-vf") + 1] == (
            "cropdetect=limit=0.094:round=2:reset=0"
        )
        assert command[-2:] == ["null", "-"]


def test_full_title_cropdetect_inspects_every_frame_before_rate_limiting() -> None:
    command = full_title_cropdetect_command(Path("reference.mkv"))

    assert "-ss" not in command
    assert "-t" not in command
    assert command[command.index("-map") + 1] == "0:v:0"
    assert command[command.index("-vf") + 1] == (
        "cropdetect=limit=0.094:round=2:reset=0,fps=1"
    )
    assert "-xerror" in command
    assert command[command.index("-err_detect") + 1] == "explode"
    assert command[-2:] == ["null", "-"]


def test_keyframe_scan_decodes_only_keyframes_of_the_whole_title() -> None:
    ((interval, command),) = keyframe_cropdetect_commands(Path("reference.mkv"), 7038)

    assert (interval.start_seconds, interval.duration_seconds) == (0, 7038)
    assert command.index("-skip_frame") < command.index("-i")
    assert command[command.index("-skip_frame") + 1] == "nokey"
    assert "-ss" not in command and "-t" not in command
    # Skipping frames trips FFmpeg's strict checks; integrity is the full decode's job.
    assert "-xerror" not in command and "-err_detect" not in command
    # Every keyframe counts: no initial frames are skipped.
    assert command[command.index("-vf") + 1] == "cropdetect=limit=0.094:round=2:reset=0:skip=0"
    gpu = keyframe_cropdetect_commands(Path("reference.mkv"), 7038, hwaccel="cuda")[0][1]
    assert gpu[gpu.index("-hwaccel") + 1] == "cuda"
    assert gpu.index("-hwaccel") < gpu.index("-i")


def test_parallel_keyframe_segments_cover_the_title_on_its_own_timeline() -> None:
    plan = keyframe_cropdetect_commands(Path("reference.mkv"), "7038.5", segments=3)

    assert [item.start_seconds for item, _command in plan] == [
        Decimal("0"),
        Decimal("2346.167"),
        Decimal("4692.334"),
    ]
    assert {item.duration_seconds for item, _command in plan} == {Decimal("2346.167")}
    last, _command = plan[-1]
    assert last.end_seconds >= Decimal("7038.5")
    for interval, command in plan:
        assert command[command.index("-threads") + 1] == "1"
        assert "-copyts" in command
        assert Decimal(command[command.index("-ss") + 1]) == interval.start_seconds
        assert Decimal(command[command.index("-t") + 1]) == interval.duration_seconds
        assert command.index("-t") < command.index("-i")
    with pytest.raises(ValueError):
        keyframe_cropdetect_commands(Path("reference.mkv"), 7038, segments=0)
    with pytest.raises(ValueError):
        keyframe_cropdetect_commands(Path("reference.mkv"), 0)


def test_short_title_uses_fewer_non_overlapping_samples() -> None:
    intervals = plan_cropdetect_intervals(Decimal("5"), samples=12, sample_seconds=2)
    assert len(intervals) == 2
    assert intervals == (
        type(intervals[0])(Decimal("0.25"), Decimal("2")),
        type(intervals[0])(Decimal("2.75"), Decimal("2")),
    )


def test_parse_stable_cropdetect_accepts_modal_border_with_small_jitter() -> None:
    log = "\n".join(
        _crop_lines("1480:1080:220:0", 28)
        + _crop_lines("1478:1080:222:0", 6)
        + _crop_lines("1920:1080:0:0", 6)
    )
    evidence = parse_stable_cropdetect(
        log, source_width=1920, source_height=1080
    )
    assert evidence.crop == CropMargins(left=220, right=220)
    assert evidence.observations == 40
    assert evidence.supporting_observations == 34
    assert evidence.support_ratio == Decimal("0.85")
    assert evidence.safe_crop == CropMargins()


def test_crop_policy_preserves_variable_aspect_picture_across_windows() -> None:
    logs = tuple(
        "\n".join(_crop_lines(value, 3))
        for value in (["1920:804:0:138"] * 9 + ["1920:1080:0:0"] * 3)
    )
    evidence = parse_stable_cropdetect(
        logs, source_width=1920, source_height=1080
    )

    assert evidence.crop == CropMargins(top=138, bottom=138)
    assert evidence.support_ratio == Decimal("0.75")
    assert evidence.safe_crop == CropMargins()
    assert validate_operator_crop(None, evidence).release_safe == CropMargins()
    with pytest.raises(CropPolicyError) as error:
        validate_operator_crop(CropMargins(top=138, bottom=138), evidence)
    assert error.value.code == "variable_aspect_ratio"


def test_crop_policy_accepts_constant_letterbox_crop_across_windows() -> None:
    logs = tuple("\n".join(_crop_lines("1920:804:0:138", 3)) for _ in range(12))
    evidence = parse_stable_cropdetect(
        logs, source_width=1920, source_height=1080
    )

    selected = CropMargins(top=138, bottom=138)
    assert evidence.safe_crop == selected
    assert validate_operator_crop(selected, evidence).release_safe == selected


def test_parse_stable_cropdetect_rejects_weak_or_sparse_evidence() -> None:
    sparse = "\n".join(_crop_lines("1480:1080:220:0", 10))
    with pytest.raises(CropPolicyError, match="too few") as sparse_error:
        parse_stable_cropdetect(sparse, source_width=1920, source_height=1080)
    assert sparse_error.value.code == "insufficient_detection"

    unstable = "\n".join(
        _crop_lines("1480:1080:220:0", 13)
        + _crop_lines("1920:1080:0:0", 12)
    )
    with pytest.raises(CropPolicyError, match="not stable") as unstable_error:
        parse_stable_cropdetect(unstable, source_width=1920, source_height=1080)
    assert unstable_error.value.code == "unstable_detection"


def test_crop_policy_allows_no_crop_when_no_bar_is_detected() -> None:
    decision = validate_operator_crop(None, _evidence(CropMargins()))
    assert decision.status == "accepted"
    assert decision.requested == CropMargins()
    assert decision.residual == CropMargins()


def _border_log(*counts: tuple[int, int, int]) -> str:
    """Cropdetect lines of a 1920x1080 title: (lines, top border, bottom border)."""

    return "".join(
        f"crop=1920:{1080 - top - bottom}:0:{top}\n" * lines
        for lines, top, bottom in counts
    )


def _gap_evidence(
    detected: CropMargins, widest: CropMargins, support: str = "0.99"
) -> CropDetectionEvidence:
    return CropDetectionEvidence(
        crop=detected,
        source_width=1920,
        source_height=1080,
        observations=1000,
        supporting_observations=int(Decimal(support) * 1000),
        support_ratio=Decimal(support),
        jitter_pixels=2,
        safe_crop=widest,
    )


def test_a_stable_two_pixel_gap_uses_the_detected_border() -> None:
    """Super Troopers 3: one bright frame moved the widest canvas to 20, and a
    nearly black row stayed at the top and the bottom of the encode."""

    # A narrow opening line, then the running envelope of the three real heights.
    evidence = parse_stable_cropdetect(
        _border_log((1, 60, 60), (3317, 22, 22), (2103, 20, 22), (2047, 20, 20)),
        source_width=1920,
        source_height=1080,
    )
    assert evidence.crop == CropMargins(top=22, bottom=22)
    assert evidence.safe_crop == CropMargins(top=20, bottom=20)
    assert evidence.support_ratio > Decimal("0.999")

    selected = automatic_crop(evidence)

    assert selected == CropMargins(top=22, bottom=22)
    decision = validate_operator_crop(selected, evidence)
    assert decision.requested == CropMargins(top=22, bottom=22)
    assert decision.release_safe == CropMargins(top=20, bottom=20)
    assert decision.residual == CropMargins()
    assert tightened_edges(selected, decision.release_safe) == ("top", "bottom")


def test_a_variable_aspect_title_keeps_the_widest_canvas() -> None:
    detected = CropMargins(top=22, bottom=22)
    widest = CropMargins(top=20, bottom=20)
    evidence = _gap_evidence(detected, widest)
    assert automatic_crop(evidence) == detected

    assert automatic_crop(evidence, widest_only=True) == widest
    flagged = CropDetectionEvidence(
        crop=detected,
        source_width=1920,
        source_height=1080,
        observations=1000,
        supporting_observations=990,
        support_ratio=Decimal("0.99"),
        jitter_pixels=2,
        safe_crop=widest,
        variable_aspect=True,
    )
    assert automatic_crop(flagged) == widest


@pytest.mark.parametrize(
    ("detected", "widest"),
    [
        # More than the margin on one edge: every edge keeps the widest canvas.
        (CropMargins(top=24, bottom=22), CropMargins(top=20, bottom=20)),
        (CropMargins(left=12, top=22, bottom=22), CropMargins(left=8, top=20, bottom=20)),
        # A detected border wider than the canvas is no tightening at all.
        (CropMargins(top=18, bottom=22), CropMargins(top=20, bottom=20)),
    ],
)
def test_a_larger_gap_keeps_the_widest_canvas(
    detected: CropMargins, widest: CropMargins
) -> None:
    assert automatic_crop(_gap_evidence(detected, widest)) == widest


def test_low_support_keeps_the_widest_canvas() -> None:
    detected = CropMargins(top=22, bottom=22)
    widest = CropMargins(top=20, bottom=20)

    assert DEFAULT_TIGHT_CROP_SUPPORT_RATIO == Decimal("0.95")
    assert automatic_crop(_gap_evidence(detected, widest, "0.95")) == detected
    assert automatic_crop(_gap_evidence(detected, widest, "0.94")) == widest


def test_a_border_below_eight_pixels_stays_uncropped() -> None:
    # Eight detected, six on the widest canvas: the tightening starts no crop.
    assert automatic_crop(
        _gap_evidence(CropMargins(top=8, bottom=8), CropMargins(top=6, bottom=6))
    ) == CropMargins()
    assert automatic_crop(
        _gap_evidence(CropMargins(top=6, bottom=6), CropMargins(top=4, bottom=4))
    ) == CropMargins()
    # Eight on the canvas is a real border, so the detected one applies.
    assert automatic_crop(
        _gap_evidence(CropMargins(top=10, bottom=10), CropMargins(top=8, bottom=8))
    ) == CropMargins(top=10, bottom=10)
    # A thin side stays uncropped beside a tightened letterbox.
    assert automatic_crop(
        _gap_evidence(
            CropMargins(left=2, top=22, bottom=22), CropMargins(top=20, bottom=20)
        )
    ) == CropMargins(top=22, bottom=22)


def test_the_automatic_crop_still_refuses_an_unaligned_border() -> None:
    with pytest.raises(ValueError, match="chroma"):
        automatic_crop(
            _gap_evidence(CropMargins(top=21, bottom=20), CropMargins(top=20, bottom=20))
        )


def _frames(*counts: tuple[int, int, int]) -> str:
    """A per-frame log at 24 fps: (frames, top border, bottom border)."""

    lines: list[str] = []
    for frames, top, bottom in counts:
        for _ in range(frames):
            t = len(lines) / 24
            lines.append(f"t:{t:.6f} crop=1920:{1080 - top - bottom}:0:{top}")
    return "\n".join(lines) + "\n"


def _verify_tight(log: str):
    return verify_crop_against_full_decode(
        log,
        CropMargins(top=22, bottom=22),
        source_width=1920,
        source_height=1080,
        release_safe=CropMargins(top=20, bottom=20),
    )


def test_a_faint_row_in_bright_frames_passes_and_stays_on_record() -> None:
    # Super Troopers 3 per frame: 2.2% of the frames touching the top edge reach
    # past it, in runs of up to 8.6 seconds.
    verification = _verify_tight(_frames((1000, 22, 22), (206, 20, 22), (5000, 22, 22)))

    assert verification.passed
    top, bottom = verification.tight_edges
    assert (top.edge, top.used, top.frames_touching, top.frames_past) == ("top", 22, 6206, 206)
    assert top.share == pytest.approx(206 / 6206)
    assert (bottom.edge, bottom.frames_past) == ("bottom", 0)
    assert verification.to_dict()["tight_edges"][0]["failed"] is False
    assert "206 of the 6206 frames" in verification.tight_summary()


def test_a_real_picture_edge_past_the_tightened_crop_fails() -> None:
    verification = _verify_tight(_frames((300, 22, 22), (700, 20, 20)))

    assert not verification.passed
    assert verification.persistent_runs == 0
    assert [item.failed for item in verification.tight_edges] == [True, True]
    assert "shows picture past it" in verification.summary()
    assert "top 22px: 700 of the 1000 frames" in verification.summary()

    # Exactly at the limit counts as a real edge, just below it does not.
    assert not _verify_tight(_frames((750, 22, 22), (250, 20, 20))).passed
    assert _verify_tight(_frames((751, 22, 22), (249, 20, 20))).passed


def test_a_few_frames_past_the_tightened_crop_are_a_flash_even_at_a_high_share() -> None:
    # Half a second is twelve frames at 24 fps.
    assert _verify_tight(_frames((3, 22, 22), (11, 20, 20), (20, 40, 40))).passed
    assert not _verify_tight(_frames((3, 22, 22), (12, 20, 20), (20, 40, 40))).passed


def test_picture_beyond_the_margin_still_fails_a_tightened_crop() -> None:
    verification = _verify_tight(_frames((1000, 22, 22), (12, 18, 22), (5000, 22, 22)))

    assert not verification.passed
    assert verification.persistent_runs == 1
    assert "cuts into the picture" in verification.summary()


def test_a_crop_within_the_widest_canvas_has_no_tight_edges() -> None:
    log = _frames((300, 22, 22), (700, 20, 20))
    same = verify_crop_against_full_decode(
        log,
        CropMargins(top=20, bottom=20),
        source_width=1920,
        source_height=1080,
        release_safe=CropMargins(top=20, bottom=20),
    )
    assert same.passed and same.tight_edges == ()
    assert "tight_edges" not in same.to_dict()
    # Without the canvas (a manual crop) only the margin rule applies.
    manual = verify_crop_against_full_decode(
        log, CropMargins(top=22, bottom=22), source_width=1920, source_height=1080
    )
    assert manual.passed and manual.tight_edges == ()


def test_automatic_crop_uses_release_safe_borders_and_preserves_thin_noise() -> None:
    letterbox = _evidence(CropMargins(top=138, bottom=138))
    assert automatic_crop(letterbox) == CropMargins(top=138, bottom=138)

    thin = _evidence(CropMargins(left=6, right=6))
    assert automatic_crop(thin) == CropMargins()


def test_crop_policy_allows_thin_noise_and_conservative_safety_margin() -> None:
    thin = validate_operator_crop(None, _evidence(CropMargins(top=6, bottom=6)))
    assert thin.residual == CropMargins(top=6, bottom=6)

    conservative = validate_operator_crop(
        CropMargins(left=214, right=218),
        _evidence(CropMargins(left=220, right=220)),
    )
    assert conservative.residual == CropMargins(left=6, right=2)


def test_crop_policy_rejects_substantial_uncropped_black_border() -> None:
    evidence = _evidence(CropMargins(left=220, right=220))
    with pytest.raises(CropPolicyError, match="stable 220px black border") as error:
        validate_operator_crop(None, evidence)
    assert error.value.code == "under_crop"

    with pytest.raises(CropPolicyError, match="stable 12px black border"):
        validate_operator_crop(CropMargins(left=208, right=220), evidence)


def test_crop_policy_rejects_material_overcrop() -> None:
    evidence = _evidence(CropMargins(left=220, right=220))
    with pytest.raises(CropPolicyError, match="exceeds the release-safe") as error:
        validate_operator_crop(CropMargins(left=224, right=220), evidence)
    assert error.value.code == "over_crop"

    # A two-pixel operator safety trim is intentionally accepted.
    decision = validate_operator_crop(
        CropMargins(left=222, right=220), evidence
    )
    assert decision.status == "accepted"


def _timed_line(t: float, width: int, height: int, x: int, y: int) -> str:
    return (
        f"[Parsed_cropdetect_0 @ 0x55d0] x1:{x} x2:{x + width - 1} y1:{y} "
        f"y2:{y + height - 1} w:{width} h:{height} x:{x} y:{y} "
        f"pts:{int(t * 1000)} t:{t:.6f} limit:0.094118 crop={width}:{height}:{x}:{y}"
    )


def _running_envelope_log(events: list[tuple[float, int, int, int, int]], end: float) -> str:
    """Cumulative cropdetect (reset=0) log: one line per second."""

    lines: list[str] = []
    current = events[0]
    pending = list(events[1:])
    for second in range(int(end)):
        if pending and second >= pending[0][0]:
            current = pending.pop(0)
        lines.append(_timed_line(second, *current[1:]))
    return "\n".join(lines)


def test_aspect_profile_reports_imax_style_expansion() -> None:
    from bdencode.qc.crop import parse_aspect_profile

    log = _running_envelope_log(
        [
            (0, 1920, 500, 0, 290),  # dark opening
            (40, 1920, 800, 0, 140),  # scope picture
            (3600, 1920, 1080, 0, 0),  # first expanded (IMAX) scene
        ],
        7200,
    )
    profile = parse_aspect_profile(
        log, source_width=1920, source_height=1080, duration_seconds=7200
    )
    assert profile is not None and profile.variable
    assert (profile.baseline_width, profile.baseline_height) == (1920, 800)
    assert (profile.widest_width, profile.widest_height) == (1920, 1080)
    assert profile.timing == "exact"
    assert [item.time_seconds for item in profile.expansions] == [3600.0]
    assert profile.expansions[0].aspect_ratio == pytest.approx(1.7778)
    assert "variable aspect ratio" in profile.summary()
    assert profile.to_dict()["widest"]["aspect_ratio"] == pytest.approx(1.7778)


def test_aspect_profile_ignores_the_opening_minutes_and_constant_titles() -> None:
    from bdencode.qc.crop import parse_aspect_profile

    constant = _running_envelope_log(
        [(0, 1920, 400, 0, 340), (20, 1920, 800, 0, 140)], 7200
    )
    profile = parse_aspect_profile(
        constant, source_width=1920, source_height=1080, duration_seconds=7200
    )
    assert profile is not None and not profile.variable and not profile.expansions
    assert (profile.baseline_width, profile.baseline_height) == (1920, 800)
    assert profile.summary() == "constant aspect ratio"


def test_aspect_profile_ignores_edge_noise_below_the_change_threshold() -> None:
    from bdencode.qc.crop import parse_aspect_profile

    log = _running_envelope_log(
        [(0, 1920, 800, 0, 140), (4000, 1920, 806, 0, 137)], 7200
    )
    profile = parse_aspect_profile(
        log, source_width=1920, source_height=1080, duration_seconds=7200
    )
    assert profile is not None and not profile.variable


def test_aspect_profile_without_timestamps_is_marked_approximate() -> None:
    from bdencode.qc.crop import parse_aspect_profile

    lines = ["crop=1920:800:0:140"] * 60 + ["crop=1920:1080:0:0"] * 40
    profile = parse_aspect_profile(
        "\n".join(lines),
        source_width=1920,
        source_height=1080,
        duration_seconds=6000,
    )
    assert profile is not None and profile.variable
    assert profile.timing == "approximate"
    assert 3000 < profile.expansions[0].time_seconds < 4000


def test_aspect_profile_edge_cases() -> None:
    from bdencode.qc.crop import parse_aspect_profile

    assert (
        parse_aspect_profile(
            "nothing to see", source_width=1920, source_height=1080, duration_seconds=10
        )
        is None
    )
    # An observation larger than the source canvas is not trusted.
    assert (
        parse_aspect_profile(
            "crop=4000:3000:0:0",
            source_width=1920,
            source_height=1080,
            duration_seconds=10,
        )
        is None
    )
    with pytest.raises(ValueError):
        parse_aspect_profile("", source_width=0, source_height=1, duration_seconds=1)
    with pytest.raises(ValueError):
        parse_aspect_profile("", source_width=1, source_height=1, duration_seconds=0)


def test_variable_aspect_evidence_accepts_a_few_step_envelope() -> None:
    from bdencode.qc.crop import variable_aspect_evidence

    log = _running_envelope_log(
        [(0, 1920, 800, 0, 140), (2500, 1920, 1080, 0, 0)], 7200
    )
    with pytest.raises(CropPolicyError) as unstable:
        parse_stable_cropdetect(log, source_width=1920, source_height=1080)
    assert unstable.value.code == "unstable_detection"

    evidence = variable_aspect_evidence(
        log, source_width=1920, source_height=1080, duration_seconds=7200
    )
    assert evidence is not None and evidence.variable_aspect
    assert evidence.crop == evidence.safe_crop == CropMargins(0, 0, 0, 0)
    assert evidence.to_dict()["variable_aspect"] is True
    # The widest canvas removes no picture, so it passes the operator policy.
    decision = validate_operator_crop(automatic_crop(evidence), evidence)
    assert decision.status == "accepted"


def test_variable_aspect_evidence_refuses_noisy_or_flash_only_logs() -> None:
    from bdencode.qc.crop import variable_aspect_evidence

    noisy = _running_envelope_log(
        [(0, 1920, 600, 0, 240)]
        + [(1000 + 900 * step, 1920, 600 + 60 * (step + 1), 0, 240 - 30 * (step + 1)) for step in range(7)],
        7200,
    )
    assert (
        variable_aspect_evidence(
            noisy, source_width=1920, source_height=1080, duration_seconds=7200
        )
        is None
    )

    flash_at_the_very_end = _running_envelope_log(
        [(0, 1920, 800, 0, 140), (7195, 1920, 1080, 0, 0)], 7200
    )
    assert (
        variable_aspect_evidence(
            flash_at_the_very_end,
            source_width=1920,
            source_height=1080,
            duration_seconds=7200,
        )
        is None
    )

    constant = _running_envelope_log([(0, 1920, 800, 0, 140)], 7200)
    assert (
        variable_aspect_evidence(
            constant, source_width=1920, source_height=1080, duration_seconds=7200
        )
        is None
    )


def test_ordinary_evidence_serializes_without_the_variable_flag() -> None:
    assert "variable_aspect" not in _evidence(CropMargins(0, 138, 0, 138)).to_dict()


def test_widest_canvas_needs_the_same_screen_time_at_any_log_density() -> None:
    def log(rate: int, widest_from: float) -> str:
        lines = []
        for index in range(1200 * rate):
            moment = index / rate
            if moment >= widest_from:
                lines.append(_timed_line(moment, 1920, 1080, 0, 0))
            else:
                lines.append(_timed_line(moment, 1920, 800, 0, 140))
        return "\n".join(lines)

    for rate in (1, 24):  # a keyframe log and a per-frame log
        twelve_seconds = variable_aspect_evidence(
            log(rate, 1188), source_width=1920, source_height=1080, duration_seconds=1200
        )
        five_seconds = variable_aspect_evidence(
            log(rate, 1195), source_width=1920, source_height=1080, duration_seconds=1200
        )
        assert twelve_seconds is not None and twelve_seconds.variable_aspect
        assert five_seconds is None


def test_crop_verification_passes_when_every_frame_fits_the_crop() -> None:
    log = "\n".join(_timed_line(t, 3840, 1638, 0, 262) for t in range(100))

    verification = verify_crop_against_full_decode(
        log, CropMargins(0, 262, 0, 260), source_width=3840, source_height=2160
    )

    assert verification.passed
    assert verification.envelope == CropMargins(0, 262, 0, 260)
    assert verification.observations == 100
    assert verification.to_dict()["first_cut_seconds"] is None
    # A two-pixel trim beyond the picture is within the safety margin.
    assert verify_crop_against_full_decode(
        log, CropMargins(0, 264, 0, 262), source_width=3840, source_height=2160
    ).passed


def test_crop_verification_finds_a_short_full_frame_insert() -> None:
    lines = [_timed_line(t, 3840, 1638, 0, 262) for t in range(100)]
    # Half a second of full-frame picture, between two keyframes.
    lines += [_timed_line(100 + t / 24, 3840, 2160, 0, 0) for t in range(12)]

    verification = verify_crop_against_full_decode(
        "\n".join(lines), CropMargins(0, 262, 0, 260), source_width=3840, source_height=2160
    )

    assert not verification.passed
    assert verification.envelope == CropMargins(0, 0, 0, 0)
    assert verification.first_cut_seconds == pytest.approx(100.0)
    assert "top 262px where the picture starts at 0px" in verification.summary()
    assert verification.to_dict()["passed"] is False


def test_crop_verification_without_observations_requires_review() -> None:
    with pytest.raises(CropPolicyError) as error:
        verify_crop_against_full_decode(
            "frame=1 fps=24", CropMargins(), source_width=1920, source_height=1080
        )
    assert error.value.code == "missing_verification"
    assert count_crop_observations("crop=1920:800:0:140\ncrop=-1:-1:0:0") == 1
