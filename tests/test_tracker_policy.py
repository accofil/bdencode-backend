"""Aither and nCore rules applied to a planned track list."""

from __future__ import annotations

from dataclasses import replace

from bdencode.external.spec import ExternalSource, ExternalSubtitle, ExternalTrack
from bdencode.media.bluray import (
    MediaStream,
    PlaylistCandidate,
    StreamKind,
    TrackRole,
    VideoCodec,
    VideoProperties,
)
from bdencode.media.planner import TrackSelection
from bdencode.tracker_policy import TrackerProfile, tracker_findings


def audio(stream_id: str, codec: str, channels: int, *, profile: str | None = None, roles=()) -> MediaStream:
    return MediaStream(
        stream_id, 0, None, StreamKind.AUDIO, codec, codec_profile=profile, channels=channels, roles=tuple(roles)
    )


def subtitle(stream_id: str, *, roles=()) -> MediaStream:
    return MediaStream(stream_id, 0, None, StreamKind.SUBTITLE, "hdmv_pgs_subtitle", roles=tuple(roles))


PLAYLIST = PlaylistCandidate(
    "00800",
    6000.0,
    streams=(
        audio("en-truehd", "truehd", 8, roles=(TrackRole.MAIN,)),
        audio("en-ac3", "ac3", 6, roles=(TrackRole.MAIN,)),
        audio("hu-dts", "dts", 6, profile="DTS", roles=(TrackRole.DUB,)),
        audio("hu-ac3", "ac3", 6, roles=(TrackRole.DUB,)),
        audio("fr-ac3", "ac3", 6, roles=(TrackRole.DUB,)),
        audio("en-comm", "ac3", 2, roles=(TrackRole.COMMENTARY,)),
        subtitle("hu-forced"),
        subtitle("hu-full"),
        subtitle("en-full"),
        subtitle("de-forced"),
    ),
)


def pick(stream_id: str, action: str, order: int, language: str, **extra) -> TrackSelection:
    return TrackSelection(stream_id, action, language=language, order=order, **extra)


def codes(profile: TrackerProfile, tracks, encoder: str = "x264") -> list[str]:
    return [item.code for item in tracker_findings(profile, encoder=encoder, playlist=PLAYLIST, tracks=tracks)]


def test_no_profile_means_no_findings() -> None:
    assert codes(TrackerProfile.NONE, [pick("fr-ac3", "copy", 1, "fre")]) == []


def test_a_compliant_ncore_1080p_plan_is_clean() -> None:
    tracks = [
        pick("hu-ac3", "copy", 1, "hun"),
        pick("en-truehd", "eac3", 2, "eng"),
        pick("en-comm", "copy", 3, "eng"),
        pick("hu-forced", "copy", 4, "hun", subtitle_kind="forced"),
        pick("hu-full", "copy", 5, "hun", subtitle_kind="full"),
        pick("en-full", "copy", 6, "eng", subtitle_kind="full"),
    ]
    # The 7.1 -> 5.1 E-AC3 downmix and the PGS subtitles are the only remarks.
    assert codes(TrackerProfile.NCORE, tracks) == ["ncore_channels", "ncore_pgs"]


def test_ncore_1080p_rejects_lossless_and_wants_compat_order_and_dubbed_forced() -> None:
    tracks = [
        pick("en-truehd", "copy", 1, "eng"),
        pick("hu-dts", "copy", 2, "hun"),
        pick("fr-ac3", "copy", 3, "fre"),
        pick("de-forced", "copy", 4, "ger", subtitle_kind="forced"),
        pick("hu-full", "copy", 5, "hun", subtitle_kind="full"),
    ]
    found = codes(TrackerProfile.NCORE, tracks)
    assert "ncore_audio_format" in found  # TrueHD at 1080p
    assert found.count("ncore_compat_missing") == 2  # TrueHD and DTS without DD
    assert "ncore_language" in found  # French is neither HU/EN/DE nor the original
    assert "ncore_order" in found  # Hungarian audio must come first
    assert "ncore_forced_without_dub" in found  # German forced, no German dub
    assert "ncore_subtitle_order" in found


def test_ncore_2160p_allows_truehd_with_its_dd_compat_track() -> None:
    tracks = [
        pick("hu-ac3", "copy", 1, "hun"),
        pick("en-truehd", "copy", 2, "eng"),
        pick("en-comm", "copy", 3, "eng"),
    ]
    assert "ncore_audio_format" not in codes(TrackerProfile.NCORE, tracks, "x265")
    # The English commentary is not a compatibility track.
    assert codes(TrackerProfile.NCORE, tracks, "x265") == ["ncore_compat_missing"]
    # The disc's AC3 core of the same language is.
    assert codes(TrackerProfile.NCORE, [*tracks, pick("en-ac3", "copy", 4, "eng")], "x265") == []


def test_aither_wants_original_and_english_only_and_a_truehd_compat() -> None:
    tracks = [
        pick("en-truehd", "copy", 1, "eng"),
        pick("hu-ac3", "copy", 2, "hun"),
    ]
    found = codes(TrackerProfile.AITHER, tracks)
    assert found == ["aither_language", "aither_compat_missing"]


def test_aither_requires_english_subtitles_without_english_audio() -> None:
    tracks = [pick("fr-ac3", "copy", 1, "fre"), pick("hu-full", "copy", 2, "hun", subtitle_kind="full")]
    assert "aither_english_subtitles" in codes(TrackerProfile.AITHER, tracks)
    tracks.append(pick("en-full", "copy", 3, "eng", subtitle_kind="full"))
    assert "aither_english_subtitles" not in codes(TrackerProfile.AITHER, tracks)


def test_a_hungarian_dub_may_be_default_only_under_the_ncore_rule() -> None:
    import pytest

    from bdencode.media.planner import resolve_audio_defaults

    streams = {item.id: item for item in PLAYLIST.streams}
    retained = [
        (pick("hu-ac3", "copy", 1, "hun", default=True), streams["hu-ac3"]),
        (pick("en-truehd", "copy", 2, "eng"), streams["en-truehd"]),
    ]
    with pytest.raises(ValueError, match="dubbed audio track cannot be default"):
        resolve_audio_defaults(retained)
    assert resolve_audio_defaults(retained, allow_dub_default=True) == {"hu-ac3": True, "en-truehd": False}


def _encode_playlist(height: int) -> PlaylistCandidate:
    return PlaylistCandidate(
        "00900",
        6000.0,
        streams=(
            MediaStream(
                "video",
                0,
                None,
                StreamKind.VIDEO,
                "h264",
                video=VideoProperties(codec=VideoCodec.AVC, width=1920, height=height),
            ),
            audio("it-mono", "dts", 1, profile="DTS-HD MA", roles=(TrackRole.MAIN,)),
            audio("en-51", "truehd", 6, roles=(TrackRole.MAIN,)),
            audio("en-71", "dts", 8, profile="DTS-HD MA", roles=(TrackRole.MAIN,)),
            audio("en-dd", "ac3", 6, roles=(TrackRole.MAIN,)),
            replace(audio("en-20", "dts", 2, profile="DTS-HD MA", roles=(TrackRole.MAIN,)), bit_depth=24),
            replace(audio("en-20-16", "dts", 2, profile="DTS-HD MA", roles=(TrackRole.MAIN,)), bit_depth=16),
        ),
    )


def _aither_codes(playlist, *tracks, content_type="FILM", remux=False, external=()) -> list[str]:
    return [
        item.code
        for item in tracker_findings(
            TrackerProfile.AITHER,
            encoder="x264",
            playlist=playlist,
            tracks=list(tracks),
            content_type=content_type,
            remux=remux,
            external=external,
        )
        if item.code.startswith("aither_1080p") or item.code == "aither_language"
    ]


def test_aither_lossless_surround_makes_a_1080p_encode_trumpable() -> None:
    playlist = _encode_playlist(1080)
    assert _aither_codes(playlist, pick("en-51", "copy", 1, "eng")) == ["aither_1080p_lossless_surround"]
    assert _aither_codes(playlist, pick("en-71", "flac", 1, "eng")) == ["aither_1080p_lossless_surround"]
    assert _aither_codes(playlist, pick("en-51", "eac3", 1, "eng")) == []
    assert _aither_codes(playlist, pick("en-dd", "copy", 1, "eng")) == []


def test_aither_only_excuses_16_bit_flac_up_to_two_channels() -> None:
    playlist = _encode_playlist(1080)
    assert _aither_codes(playlist, pick("en-20", "copy", 1, "eng")) == ["aither_1080p_stereo_flac16"]
    assert _aither_codes(playlist, pick("en-20", "flac", 1, "eng")) == ["aither_1080p_stereo_flac16"]
    assert _aither_codes(playlist, pick("en-20", "flac16", 1, "eng")) == []
    assert _aither_codes(playlist, pick("en-20-16", "flac", 1, "eng")) == []
    # The rule names 5.1, but 2.0 is the only exception it gives.
    assert _aither_codes(playlist, pick("it-mono", "copy", 1, "ita")) == ["aither_1080p_stereo_flac16"]


def test_the_lossless_rule_is_about_live_action_encodes_up_to_1080p() -> None:
    track = pick("en-51", "copy", 1, "eng")
    assert _aither_codes(_encode_playlist(2160), track) == []
    assert _aither_codes(_encode_playlist(1080), track, content_type="ANIME") == []
    assert _aither_codes(_encode_playlist(1080), track, remux=True) == []


def _source(language: str, position: int = 0, subtitle: str | None = None) -> ExternalSource:
    return ExternalSource(
        id="e1",
        path="/x.iso",
        tracks=(ExternalTrack(stream="#0x80", language=language, position=position),),
        subtitles=(ExternalSubtitle(path="/x.srt", language=subtitle),) if subtitle else (),
    )


def test_aither_sees_a_fitted_dub_like_any_other_language() -> None:
    playlist = _encode_playlist(1080)
    plain = pick("en-dd", "copy", 1, "eng")
    assert _aither_codes(playlist, plain, external=[_source("hun")]) == ["aither_language"]
    assert _aither_codes(playlist, plain, external=[_source("eng")]) == []
    # A fitted track never passes for the original language.
    only_italian = pick("it-mono", "omit", 1, "ita")
    assert "aither_language" not in _aither_codes(playlist, only_italian, external=[_source("hun")])


def test_ncore_judges_a_fitted_hungarian_dub_by_its_place() -> None:
    playlist = _encode_playlist(1080)
    tracks = [pick("en-dd", "copy", 1, "eng")]

    def found(position: int) -> list[str]:
        return [
            item.code
            for item in tracker_findings(
                TrackerProfile.NCORE,
                encoder="x264",
                playlist=playlist,
                tracks=tracks,
                external=[_source("hun", position)],
            )
        ]

    assert "ncore_order" not in found(0)
    assert "ncore_order" in found(5)


def test_a_fitted_english_srt_counts_as_the_required_subtitle() -> None:
    playlist = _encode_playlist(1080)
    italian = pick("it-mono", "flac16", 1, "ita")
    def found(*external):
        return [
            item.code
            for item in tracker_findings(
                TrackerProfile.AITHER, encoder="x264", playlist=playlist, tracks=[italian], external=external
            )
        ]
    assert "aither_english_subtitles" in found()
    assert "aither_english_subtitles" not in found(_source("ita", subtitle="eng"))
