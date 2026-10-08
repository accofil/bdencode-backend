"""nCore's sample: when it is needed, where it is cut, what the package may hold."""

from __future__ import annotations

from pathlib import Path

import pytest

from bdencode.worker import ReviewRequired, _validate_completed_members, sample_window

GIB = 1024**3


def test_no_sample_at_or_below_two_gigabytes() -> None:
    assert sample_window(duration_seconds=6000, size_bytes=2 * GIB, uhd=False) is None


def test_a_1080p_sample_is_a_minute_from_five_minutes_in() -> None:
    assert sample_window(duration_seconds=6000, size_bytes=12 * GIB, uhd=False) == (300.0, 60.0)


def test_a_uhd_sample_reaches_200_mb() -> None:
    # 25 GB over 100 minutes is about 4.4 MB/s: 200 MiB needs about 48 s, so a minute.
    assert sample_window(duration_seconds=6000, size_bytes=25 * GIB, uhd=True) == (300.0, 60.0)
    # 9 GB over 100 minutes is about 1.5 MiB/s: 200 MiB needs about 131 s.
    assert sample_window(duration_seconds=6000, size_bytes=9 * GIB, uhd=True) == (300.0, 136.0)
    # Never longer than four minutes.
    assert sample_window(duration_seconds=6000, size_bytes=3 * GIB, uhd=True) == (300.0, 240.0)


def test_a_short_title_starts_its_sample_a_quarter_in() -> None:
    assert sample_window(duration_seconds=900, size_bytes=3 * GIB, uhd=False) == (225, 60.0)


def test_the_package_may_hold_only_its_own_sample(tmp_path: Path) -> None:
    (tmp_path / "Movie.mkv").write_bytes(b"x")
    sample = tmp_path / "Sample"
    sample.mkdir()
    (sample / "Movie.sample.mkv").write_bytes(b"x")
    _validate_completed_members(tmp_path, "Movie", allow_legacy=False)
    (sample / "other.mkv").write_bytes(b"x")
    with pytest.raises(ReviewRequired, match="only the release's own sample"):
        _validate_completed_members(tmp_path, "Movie", allow_legacy=False)
