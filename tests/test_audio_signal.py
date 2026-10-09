from __future__ import annotations

from decimal import Decimal

import pytest

from bdencode.audio import effective_audio_policy
from bdencode.qc.audio import parse_audio_analysis, verify_audio_signal


def _analysis_log(
    *,
    integrated: str = "-18.2",
    loudness_range: str = "7.4",
    true_peak: str = "-0.8",
    sample_peak: str = "-1.0",
    peak_count: str = "2.000000",
    nan_samples: str = "0.000000",
    inf_samples: str = "0.000000",
    denormal_samples: str = "0.000000",
    extra: str = "",
) -> str:
    return f"""
[Parsed_ebur128_0 @ 000001] t: 1.0 TARGET:-23 LUFS M:-70.0 S:-70.0 I:-70.0 LUFS LRA:0.0 LU
[Parsed_astats_1 @ 000002] Channel: 1
[Parsed_astats_1 @ 000002] Peak level dB: -6.0
[Parsed_astats_1 @ 000002] Peak count: 1.000000
[Parsed_astats_1 @ 000002] Overall
[Parsed_astats_1 @ 000002] Peak level dB: {sample_peak}
[Parsed_astats_1 @ 000002] Peak count: {peak_count}
[Parsed_astats_1 @ 000002] Number of NaNs: {nan_samples}
[Parsed_astats_1 @ 000002] Number of Infs: {inf_samples}
[Parsed_astats_1 @ 000002] Number of denormals: {denormal_samples}
[Parsed_ebur128_0 @ 000001] Summary:

[Parsed_ebur128_0 @ 000001]   Integrated loudness:
[Parsed_ebur128_0 @ 000001]     I:          {integrated} LUFS

[Parsed_ebur128_0 @ 000001]   Loudness range:
[Parsed_ebur128_0 @ 000001]     LRA:         {loudness_range} LU

[Parsed_ebur128_0 @ 000001]   True peak:
[Parsed_ebur128_0 @ 000001]     Peak:        {true_peak} dBFS
{extra}
"""


def _policy(action: str = "ac3"):
    return effective_audio_policy(
        action,
        source_codec="truehd",
        source_profile="TrueHD",
        source_channels=8,
        source_sample_rate=48_000,
    )


def test_parser_uses_final_ebur128_summary_and_astats_overall_values() -> None:
    analysis = parse_audio_analysis(_analysis_log().encode())

    assert analysis.integrated_lufs == Decimal("-18.2")
    assert analysis.loudness_range_lu == Decimal("7.4")
    assert analysis.true_peak_dbfs == Decimal("-0.8")
    assert analysis.sample_peak_dbfs == Decimal("-1.0")
    assert analysis.peak_count == 2
    assert analysis.clipped_samples == 0
    assert analysis.clipping_detection == "below_full_scale"
    assert analysis.nan_samples == 0
    assert analysis.inf_samples == 0
    assert analysis.denormal_samples == 0
    assert analysis.complete


def test_parser_derives_clipping_from_full_scale_peak_count() -> None:
    analysis = parse_audio_analysis(
        _analysis_log(sample_peak="-0.000000", peak_count="12.000000")
    )

    assert analysis.sample_peak_dbfs == 0
    assert analysis.clipped_samples == 12
    assert analysis.clipping_detection == "full_scale_peak_count"
    assert analysis.has_clipping


def test_explicit_clipping_counter_takes_precedence() -> None:
    analysis = parse_audio_analysis(
        _analysis_log(
            sample_peak="-0.2",
            peak_count="2",
            extra="[Parsed_astats_1] Number of clipped samples: 4.0",
        )
    )

    assert analysis.clipped_samples == 4
    assert analysis.clipping_detection == "explicit_counter"


def test_silent_negative_infinity_is_a_valid_complete_analysis() -> None:
    analysis = parse_audio_analysis(
        _analysis_log(
            integrated="-inf",
            loudness_range="0.0",
            true_peak="-inf",
            sample_peak="-inf",
            peak_count="0",
        )
    )

    assert analysis.complete
    assert analysis.invalid_metric_fields == ()
    assert analysis.clipped_samples == 0


def test_missing_analysis_fields_fail_closed() -> None:
    missing = parse_audio_analysis("ffmpeg exited before filter summaries")
    complete = parse_audio_analysis(_analysis_log())

    result = verify_audio_signal(missing, complete, _policy())

    assert not result.passed
    assert not result.source_complete
    assert any(
        "source audio analysis is incomplete" in item for item in result.failures
    )


def test_non_finite_and_clipped_samples_are_rejected_and_denormals_reported() -> None:
    source = parse_audio_analysis(_analysis_log(denormal_samples="3"))
    encode = parse_audio_analysis(
        _analysis_log(
            sample_peak="0.0",
            peak_count="8",
            nan_samples="1",
            inf_samples="2",
        )
    )

    result = verify_audio_signal(source, encode, _policy("flac"))

    assert not result.passed
    assert any("non-finite samples" in item for item in result.failures)
    assert any("8 clipped/full-scale samples" in item for item in result.failures)
    assert any("3 denormal samples" in item for item in result.warnings)


def test_lossless_pcm_match_reports_inherited_clipping_as_warning() -> None:
    source = parse_audio_analysis(
        _analysis_log(sample_peak="0.0", peak_count="2")
    )
    encode = parse_audio_analysis(
        _analysis_log(sample_peak="0.0", peak_count="2")
    )

    result = verify_audio_signal(
        source,
        encode,
        _policy("copy"),
        decoded_pcm_sha256_match=True,
    )

    assert result.passed
    assert not any("clipped/full-scale" in item for item in result.failures)
    assert any("pre-existing clipped/full-scale" in item for item in result.warnings)


@pytest.mark.parametrize("pcm_match", (False, None))
def test_lossless_clipping_without_pcm_proof_still_fails(
    pcm_match: bool | None,
) -> None:
    source = parse_audio_analysis(
        _analysis_log(sample_peak="0.0", peak_count="2")
    )
    encode = parse_audio_analysis(
        _analysis_log(sample_peak="0.0", peak_count="2")
    )

    result = verify_audio_signal(
        source,
        encode,
        _policy("copy"),
        decoded_pcm_sha256_match=pcm_match,
    )

    assert not result.passed
    assert any("clipped/full-scale" in item for item in result.failures)


def test_lossy_transcode_reports_true_peak_overshoot_as_a_warning() -> None:
    source = parse_audio_analysis(_analysis_log(true_peak="-0.5"))
    encode = parse_audio_analysis(_analysis_log(true_peak="0.2", sample_peak="-0.1"))

    result = verify_audio_signal(source, encode, _policy("eac3"))

    assert result.passed
    assert result.lossy_transcode
    assert result.true_peak_increase_db == Decimal("0.7")
    assert result.failures == ()
    assert any("above 0 dBTP" in item for item in result.warnings)
    assert any("increased near-ceiling true peak" in item for item in result.warnings)


@pytest.mark.parametrize(
    ("encode_peak", "warned"),
    (("-0.5", False), ("-0.4", True)),
)
def test_lossy_near_ceiling_true_peak_increase_over_point_three_db_is_a_warning(
    encode_peak: str, warned: bool
) -> None:
    source = parse_audio_analysis(_analysis_log(true_peak="-0.8"))
    encode = parse_audio_analysis(
        _analysis_log(true_peak=encode_peak, sample_peak="-0.9")
    )

    result = verify_audio_signal(source, encode, _policy())

    assert result.passed
    assert (
        any("increased near-ceiling true peak" in item for item in result.warnings)
        is warned
    )


@pytest.mark.parametrize("action", ("ac3", "eac3", "dts"))
def test_loud_master_with_full_scale_source_samples_passes_a_lossy_encode(
    action: str,
) -> None:
    """A loud Blu-ray master touches full scale; its lossy encode overshoots."""

    source = parse_audio_analysis(
        _analysis_log(true_peak="0.4", sample_peak="0.0", peak_count="37")
    )
    encode = parse_audio_analysis(
        _analysis_log(
            integrated="-18.4",
            true_peak="0.9",
            sample_peak="0.3",
            peak_count="2",
        )
    )

    result = verify_audio_signal(source, encode, _policy(action))

    assert result.passed, result.failures
    assert any(
        "source audio contains 37 clipped/full-scale samples" in item
        for item in result.warnings
    )
    assert any(
        "encode audio contains 2 clipped/full-scale samples" in item
        for item in result.warnings
    )
    assert any("encode true peak is 0.9 dBTP" in item for item in result.warnings)


def test_dts_core_extraction_reports_source_clipping_as_a_warning() -> None:
    source = parse_audio_analysis(_analysis_log(sample_peak="0.0", peak_count="12"))
    encode = parse_audio_analysis(_analysis_log(sample_peak="0.0", peak_count="9"))
    policy = effective_audio_policy(
        "dts",
        source_codec="dts",
        source_profile="DTS-HD MA",
        source_channels=8,
        source_sample_rate=48_000,
    )

    result = verify_audio_signal(source, encode, policy)

    assert result.passed
    assert any("12 clipped/full-scale" in item for item in result.warnings)


@pytest.mark.parametrize(
    ("source_count", "encode_count", "passed"),
    (
        ("0", "1000", True),
        ("0", "1001", False),
        ("500", "5000", True),
        ("500", "5001", False),
    ),
)
def test_lossy_encode_fails_only_on_far_more_clipping_than_the_source(
    source_count: str, encode_count: str, passed: bool
) -> None:
    source = parse_audio_analysis(
        _analysis_log(
            sample_peak="0.0" if source_count != "0" else "-0.5",
            peak_count=source_count,
        )
    )
    encode = parse_audio_analysis(
        _analysis_log(sample_peak="0.0", peak_count=encode_count)
    )

    result = verify_audio_signal(source, encode, _policy())

    assert result.passed is passed
    if not passed:
        assert any("far above the source's" in item for item in result.failures)


@pytest.mark.parametrize(
    ("encode_loudness", "passed"),
    (("-15.2", True), ("-21.2", True), ("-15.1", False), ("-21.3", False)),
)
def test_lossy_encode_fails_on_a_large_integrated_loudness_shift(
    encode_loudness: str, passed: bool
) -> None:
    source = parse_audio_analysis(_analysis_log(integrated="-18.2"))
    encode = parse_audio_analysis(_analysis_log(integrated=encode_loudness))

    result = verify_audio_signal(source, encode, _policy())

    assert result.passed is passed
    if not passed:
        assert any("integrated loudness differs" in item for item in result.failures)


def test_lossy_encode_of_an_audible_source_must_not_be_silent() -> None:
    source = parse_audio_analysis(_analysis_log(integrated="-24.0"))
    silent = parse_audio_analysis(
        _analysis_log(
            integrated="-inf",
            loudness_range="0.0",
            true_peak="-inf",
            sample_peak="-inf",
            peak_count="0",
        )
    )

    result = verify_audio_signal(source, silent, _policy())

    assert not result.passed
    assert "encode audio is silent while the source is audible" in result.failures


def test_lossless_and_core_extraction_report_intersample_peak_without_false_failure() -> (
    None
):
    source = parse_audio_analysis(_analysis_log(true_peak="-0.1"))
    encode = parse_audio_analysis(_analysis_log(true_peak="0.2", sample_peak="-0.05"))
    flac = verify_audio_signal(source, encode, _policy("flac"))
    dts_core_policy = effective_audio_policy(
        "dts",
        source_codec="dts",
        source_profile="DTS-HD MA",
        source_channels=8,
        source_sample_rate=48_000,
    )
    dts_core = verify_audio_signal(source, encode, dts_core_policy)

    assert flac.passed and not flac.lossy_transcode
    assert dts_core.passed and not dts_core.lossy_transcode
    assert dts_core.strategy == "dts_core_extract"
    assert any("above 0 dBTP" in item for item in flac.warnings)
    assert any("above 0 dBTP" in item for item in dts_core.warnings)


def test_parser_rejects_non_finite_counter_values() -> None:
    with pytest.raises(ValueError, match="finite non-negative"):
        parse_audio_analysis(_analysis_log(nan_samples="nan"))


def test_analysis_and_verification_are_manifest_serializable() -> None:
    source = parse_audio_analysis(_analysis_log(true_peak="-0.8"))
    encode = parse_audio_analysis(_analysis_log(true_peak="-0.6"))
    result = verify_audio_signal(source, encode, _policy())

    assert source.to_dict()["true_peak_dbfs"] == "-0.8"
    assert source.to_dict()["complete"] is True
    assert result.to_dict()["true_peak_increase_db"] == "0.2"
    assert result.to_dict()["failures"] == []


def test_truehd_packets_without_duration_use_their_mean_spacing() -> None:
    """FFmpeg 5.1 prints no duration_time for TrueHD packets (Debian 12)."""

    import json as json_module

    from bdencode.qc.audio import parse_audio_probe

    step = 1 / 1200
    packets = [
        {"stream_index": 1, "pts_time": f"{0.042 + index * step:.6f}", "dts_time": f"{0.042 + index * step:.6f}"}
        for index in range(12001)
    ]
    document = {
        "packets": packets,
        "streams": [
            {"index": 1, "codec_name": "truehd", "codec_type": "audio", "sample_rate": "48000",
             "channels": 6, "start_time": "0.042000", "nb_read_packets": str(len(packets))}
        ],
    }

    probe = parse_audio_probe(json_module.dumps(document))

    assert probe.duration_evidence == "complete_packet_tail"
    assert abs(float(probe.duration) - 10.000833) < 0.00001
