"""The encode-time language stage takes a subtitle's language from its captions."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from bdencode.media.language import settle_track_language
from bdencode.worker import PipelineWorker as Worker


def write_analysis(root: Path, record: dict) -> SimpleNamespace:
    (root / "track-analysis.json").write_bytes(
        json.dumps({"00002": {"subtitles": {"subtitle:4609": {"language": record}}}}).encode()
    )
    return SimpleNamespace(analysis=root)


def test_the_caption_reading_is_found_by_playlist_and_stream(tmp_path: Path) -> None:
    paths = write_analysis(tmp_path, {"status": "detected", "iso639_2t": "ger", "confidence": 0.86})

    assert Worker._subtitle_detection(paths, "00002", "subtitle:4609") == ("deu", 0.86)
    assert Worker._subtitle_detection(paths, "2", "subtitle:4609") == ("deu", 0.86)
    assert Worker._subtitle_detection(paths, "00002", "subtitle:4610") == (None, 0.0)
    assert Worker._subtitle_detection(paths, "00001", "subtitle:4609") == (None, 0.0)


def test_an_unknown_reading_or_no_analysis_gives_nothing(tmp_path: Path) -> None:
    paths = write_analysis(tmp_path, {"status": "unknown", "reason": "too_little_text"})
    assert Worker._subtitle_detection(paths, "00002", "subtitle:4609") == (None, 0.0)
    assert Worker._subtitle_detection(SimpleNamespace(analysis=tmp_path / "none"), "00002", "subtitle:4609") == (None, 0.0)


def test_the_reading_settles_an_unlabelled_or_contradicted_subtitle() -> None:
    # Unlabelled (a remux track tagged und): the captions name it.
    assert settle_track_language({}, "deu", 0.92).language == "deu"
    # Contradicting labels: the captions decide.
    assert settle_track_language({"mpls": "eng", "clpi": "deu"}, "deu", 0.9).language == "deu"
    # Agreeing labels are kept; a different reading only warns.
    kept = settle_track_language({"mpls": "eng", "clpi": "eng"}, "deu", 0.9)
    assert kept.language == "eng" and kept.warning
