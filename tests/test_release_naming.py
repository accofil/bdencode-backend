"""Release names: the Aither and Hungarian grammars and the claims they may make."""

from __future__ import annotations

import pytest

from bdencode.release_naming import (
    AudioOutput,
    ReleaseFacts,
    audio_codec_family,
    parse_release_name,
    release_name_problems,
)

TRUEHD_ATMOS_EN = AudioOutput("TRUEHD", 8, atmos=True, language="en")
DTSHD_FR = AudioOutput("DTSHDMA", 6, language="fr")
HDR_DV = frozenset({"HDR", "DV"})


def facts(*audio: AudioOutput, encoder: str = "x265", dynamic=frozenset({"HDR"})) -> ReleaseFacts:
    return ReleaseFacts(encoder=encoder, audio=audio, dynamic_range=dynamic)


@pytest.mark.parametrize(
    ("name", "plan"),
    (
        # Aither: audio, then HDR flavour, then the codec and the group.
        ("La.Femme.Nikita.1990.2160p.UHD.BluRay.DTS-HD.MA.5.1.DV.HDR.x265-TAG", facts(DTSHD_FR, dynamic=HDR_DV)),
        ("Movie.2020.1080p.BluRay.DDP5.1.x264-TAG", facts(AudioOutput("DDP", 6, language="en"), encoder="x264", dynamic=frozenset({"SDR"}))),
        ("Movie.2020.2160p.UHD.BluRay.Dual-Audio.TrueHD.7.1.Atmos.HDR10+.x265-TAG", facts(TRUEHD_ATMOS_EN, AudioOutput("DD", 6, language="fr"), dynamic=frozenset({"HDR", "HDR10+"}))),
        # Hungarian standard: dynamic range first, language tags after the codec.
        ("Movie.2020.2160p.UHD.BluRay.DV.HDR.TrueHD.7.1.Atmos.x265.HUN-TAG", facts(AudioOutput("DD", 6, language="hu"), TRUEHD_ATMOS_EN, dynamic=HDR_DV)),
        ("Movie.2020.1080p.BluRay.DD5.1.x264.HUN.ENG-TAG", facts(AudioOutput("DD", 6, language="hu"), AudioOutput("DD", 6, language="en"), encoder="x264", dynamic=frozenset({"SDR"}))),
        ("Movie.2020.1080p.BluRay.DD5.1.x264.2xHUN-TAG", facts(AudioOutput("DD", 6, language="hu"), AudioOutput("DD", 2, language="hu"), encoder="x264", dynamic=frozenset({"SDR"}))),
        # The names frontend/src/releaseName.test.ts generates for the same plans.
        ("La.Femme.Nikita.1990.FRENCH.2160p.UHD.BluRay.DTS-HD.MA.5.1.DV.HDR.x265-TAG", facts(DTSHD_FR, dynamic=HDR_DV)),
        ("Movie.2020.1080p.BluRay.DDP5.1.x264.2xHUN-TAG", facts(AudioOutput("DD", 6, language="hu"), AudioOutput("DD", 2, language="hu"), AudioOutput("DDP", 6, language="en"), encoder="x264", dynamic=frozenset({"SDR"}))),
        ("Valami.Amerika.2002.1080p.BluRay.DD5.1.x264", facts(AudioOutput("DD", 6, language="hu"), encoder="x264", dynamic=frozenset({"SDR"}))),
        # A DTS:X track rides on DTS-HD MA; either name is true.
        ("Movie.2020.2160p.UHD.BluRay.DTS-HD.MA.7.1.x265", facts(AudioOutput("DTSX", 8, language="en"))),
        ("Movie.2020.2160p.UHD.BluRay.x265-TAG", facts()),
    ),
)
def test_truthful_names_of_both_styles_pass(name: str, plan: ReleaseFacts) -> None:
    assert release_name_problems(name, plan) == []


@pytest.mark.parametrize(
    ("name", "plan", "message"),
    (
        ("Movie.Encode", facts(), "clean encode name"),
        ("Movie_2020.2160p.UHD.BluRay.x265-TAG", facts(), "clean encode name"),
        ("Movie.2020.1080p.BluRay.WEBDL.x264-TAG", facts(encoder="x264"), "clean encode name"),
        ("Movie.2026.DTS-HD.MA.1080p.BluRay.x264", facts(encoder="x264"), "before the resolution"),
        ("Movie.2020.2160p.UHD.BluRay.TrueHD.7.1.Atmos.x265-TAG", facts(AudioOutput("TRUEHD", 8, language="en")), "Atmos"),
        ("Movie.2020.2160p.UHD.BluRay.TrueHD.7.1.x265-TAG", facts(AudioOutput("TRUEHD", 6, language="en")), "7.1"),
        ("Movie.2020.2160p.UHD.BluRay.FLAC.2.0.x265-TAG", facts(TRUEHD_ATMOS_EN), "FLAC"),
        ("Movie.2020.2160p.UHD.BluRay.DV.HDR.x265-TAG", facts(), "Dolby Vision"),
        ("Movie.2020.1080p.BluRay.HDR.x264-TAG", facts(encoder="x264", dynamic=frozenset({"SDR"})), "HDR"),
        ("Movie.2020.2160p.UHD.BluRay.x265.HUN-TAG", facts(TRUEHD_ATMOS_EN), "HUN"),
        ("Movie.2020.2160p.UHD.BluRay.x265.2xHUN-TAG", facts(AudioOutput("DD", 6, language="hu")), "2xHUN"),
        ("Movie.2020.2160p.UHD.BluRay.x265.QQQ-TAG", facts(), "unknown language tag"),
        ("Movie.2020.2160p.UHD.BluRay.Dual-Audio.x265-TAG", facts(DTSHD_FR, AudioOutput("DD", 6, language="hu")), "Dual-Audio"),
        ("Movie.2020.2160p.UHD.BluRay.MULTi.x265-TAG", facts(DTSHD_FR), "MULTi"),
    ),
)
def test_untruthful_or_malformed_names_are_explained(name: str, plan: ReleaseFacts, message: str) -> None:
    problems = release_name_problems(name, plan)
    assert problems and all(item.startswith("output_name") for item in problems)
    assert any(message in item for item in problems), problems


def test_commentary_does_not_count_as_a_language() -> None:
    commentary = AudioOutput("DD", 2, language="en", commentary=True)
    problems = release_name_problems("Movie.2020.2160p.UHD.BluRay.Dual-Audio.x265-TAG", facts(DTSHD_FR, commentary))
    assert any("Dual-Audio" in item for item in problems)


def test_the_parser_splits_the_technical_tokens() -> None:
    parsed = parse_release_name("Movie.2020.Directors.Cut.2160p.UHD.BluRay.DTS-HD.MA.5.1.DV.HDR.x265.HUN.ENG-TAG", "x265")
    assert parsed is not None
    assert parsed.title == "Movie.2020.Directors.Cut"
    assert parsed.tokens == ("DTS-HD.MA.5.1", "DV", "HDR")
    assert (parsed.codec, parsed.languages, parsed.group) == ("x265", ("HUN", "ENG"), "TAG")


@pytest.mark.parametrize(
    ("codec", "profile", "family"),
    (
        ("truehd", None, "TRUEHD"),
        ("dts", "DTS-HD MA", "DTSHDMA"),
        ("dts", "DTS-HD MA + DTS:X", "DTSX"),
        ("dts", "DTS-HD HRA", "DTSHDHRA"),
        ("dts", "DTS", "DTS"),
        ("ac3", None, "DD"),
        ("eac3", None, "DDP"),
        ("pcm_bluray", None, "LPCM"),
        ("flac", None, "FLAC"),
        ("vorbis", None, "OTHER"),
    ),
)
def test_source_codecs_map_to_name_families(codec: str, profile: str | None, family: str) -> None:
    assert audio_codec_family(codec, profile) == family
