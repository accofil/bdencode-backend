"""Tracker jobs get an IDR frame at every chapter start."""

from __future__ import annotations

from pathlib import Path

from bdencode.encode import encode_pipeline_commands
from bdencode.media import recommended_profile
from bdencode.media.bluray import PlaylistCandidate
from bdencode.worker import chapter_keyframe_seconds


def test_chapter_starts_skip_the_first_frame_and_the_last_second() -> None:
    playlist = PlaylistCandidate("00800", 600.0, chapters=(0.0, 0.2, 120.04166, 300.5, 599.5, 120.04166))
    assert chapter_keyframe_seconds(playlist) == (120.042, 300.5)


def test_forced_idr_frames_are_requested_only_when_asked() -> None:
    settings = recommended_profile("x265")
    plain = encode_pipeline_commands(Path("title.vpy"), Path("out.hevc"), settings)[1]
    assert "-force_key_frames" not in plain
    forced = encode_pipeline_commands(Path("title.vpy"), Path("out.hevc"), settings, keyframe_seconds=(120.042, 300.5))[1]
    position = forced.index("-force_key_frames")
    assert forced[position + 1 : position + 4] == ["120.042,300.500", "-forced-idr", "1"]
    assert forced[-1] == "out.hevc"
