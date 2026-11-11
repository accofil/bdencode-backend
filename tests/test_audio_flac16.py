"""16-bit FLAC: what Aither allows for lossless audio of at most 2 channels at 1080p."""

from __future__ import annotations

from decimal import Decimal

import pytest

from bdencode.audio import audio_encode_args, effective_audio_policy, expected_audio_codec
from bdencode.qc.audio import AudioProbe, verify_audio_output


def test_a_16_bit_source_stays_bit_identical() -> None:
    policy = effective_audio_policy("flac16", source_codec="dts", source_channels=2, source_bit_depth=16)
    assert policy.pcm_match_required
    assert policy.bit_depth == 16
    args = audio_encode_args("flac16", source_codec="dts", source_channels=2, source_bit_depth=16)
    assert args[args.index("-sample_fmt") + 1] == "s16"
    assert "-af" not in args


def test_a_deeper_source_is_dithered_and_not_claimed_identical() -> None:
    policy = effective_audio_policy("flac16", source_codec="dts", source_channels=2, source_bit_depth=24)
    assert not policy.pcm_match_required
    assert policy.strategy == "dithered_transcode"
    assert policy.codec_name == "flac"
    args = audio_encode_args("flac16", source_codec="dts", source_channels=2, source_bit_depth=24)
    assert args[args.index("-sample_fmt") + 1] == "s16"
    assert "dither_method=triangular" in args[args.index("-af") + 1]


def test_an_unknown_depth_is_not_assumed_to_be_16_bits() -> None:
    assert not effective_audio_policy("flac16", source_codec="dts", source_channels=2).pcm_match_required


def test_the_output_is_flac_with_the_sources_channels() -> None:
    assert expected_audio_codec("flac16", "dts") == "flac"
    assert effective_audio_policy("flac16", source_codec="dts", source_channels=1, source_bit_depth=24).channels == 1


def _probe(codec: str, *, start: str = "0", duration: str = "600", channels: int = 2, rate: int = 48_000) -> AudioProbe:
    return AudioProbe(
        codec=codec,
        sample_rate=rate,
        channels=channels,
        channel_layout="stereo",
        sample_count=None,
        start_time=Decimal(start),
        duration=Decimal(duration),
        bits_per_raw_sample=None,
    )


_DITHERED = effective_audio_policy("flac16", source_codec="dts", source_channels=2, source_sample_rate=48_000, source_bit_depth=24)


def test_qc_accepts_a_dithered_track_without_asking_for_identical_samples() -> None:
    # Matroska rounds the start and the end to whole milliseconds.
    encode = _probe("flac", start="0.001", duration="600.001")
    result = verify_audio_output(_probe("dts"), encode, _DITHERED, decoded_pcm_sha256_match=None)
    assert result.passed
    assert not result.decoded_pcm_sha256_required


def test_qc_refuses_a_dithered_track_that_is_late_changed_or_not_flac() -> None:
    source = _probe("dts")
    for encode in (
        _probe("flac", start="0.005"),
        _probe("flac", duration="600.1"),
        _probe("flac", channels=1),
        _probe("flac", rate=44_100),
        _probe("ac3"),
    ):
        assert not verify_audio_output(source, encode, _DITHERED, decoded_pcm_sha256_match=None).passed


def test_qc_still_wants_identical_samples_from_a_16_bit_source() -> None:
    exact = effective_audio_policy("flac16", source_codec="dts", source_channels=2, source_sample_rate=48_000, source_bit_depth=16)
    source = _probe("dts")
    assert verify_audio_output(source, _probe("flac"), exact, decoded_pcm_sha256_match=True).passed
    assert not verify_audio_output(source, _probe("flac"), exact, decoded_pcm_sha256_match=False).passed


@pytest.mark.parametrize("action", ["copy", "flac16", "flac"])
def test_a_zero_rate_or_channel_count_from_the_scan_counts_as_unknown(action: str) -> None:
    """FFmpeg reports 0 Hz and 0 channels for a stream it did not read long
    enough; the checks must then use what the reference itself measures."""

    policy = effective_audio_policy(
        action, source_codec="dts", source_channels=0, source_sample_rate=0
    )

    assert policy.sample_rate is None
    assert policy.channels is None
