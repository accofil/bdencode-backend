"""The frame map on a made-up film, cut the way real prints are."""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")

from bdencode.external.frame_map import (  # noqa: E402
    FrameMapError,
    build_frame_map,
    frame_grid,
)

WIDTH, HEIGHT = 64, 36
FILM = Fraction(24000, 1001)


def film(frames: int, seed: int = 1) -> np.ndarray:
    """Shots with their own texture and a slow drift, as a film's picture has."""

    random = np.random.default_rng(seed)
    out = np.zeros((frames, HEIGHT, WIDTH * 2), dtype=np.uint8)
    frame = 0
    while frame < frames:
        length = int(random.integers(30, 160))
        base = random.random((HEIGHT // 3 + 1, WIDTH // 2 + 2))
        texture = np.kron(base, np.ones((3, 4)))[:HEIGHT, : WIDTH * 2]
        level = random.uniform(40, 200)
        for step in range(length):
            if frame >= frames:
                break
            moved = np.roll(texture, step // 4, axis=1)
            out[frame] = np.clip(level * 0.5 + moved * level, 0, 255)
            frame += 1
    return out


def title_view(master: np.ndarray) -> np.ndarray:
    """The whole width, squeezed to the signature."""

    return master[:, :, ::2]


def cropped_view(master: np.ndarray) -> np.ndarray:
    """A 75% wide part of the picture, shown over the full signature width."""

    start = WIDTH // 4
    span = np.linspace(start, start + int(WIDTH * 1.5) - 1, WIDTH).astype(int)
    return master[:, :, span]


def write(path: Path, frames: np.ndarray) -> Path:
    path.write_bytes(frames.tobytes())
    return path


def test_pal_print_with_small_cuts_and_a_missing_scene(tmp_path: Path) -> None:
    master = film(9000)
    # The donor lacks frames 2000-2004 and 6000-6299 of the title, and has
    # 12 frames the title lacks after frame 4000.
    extra = film(12, seed=9)
    donor = np.concatenate(
        (master[:2000], master[2005:4000], extra, master[4000:6000], master[6300:])
    )
    target_path = write(tmp_path / "t.gray", title_view(master))
    donor_path = write(tmp_path / "d.gray", title_view(donor))
    document = build_frame_map(target_path, donor_path, target_fps=FILM, donor_fps=Fraction(25))
    assert document["mode"] == "frame-locked"
    segments = document["segments"]
    assert [item["offset"] for item in segments] == [0, -5, 7, -293]
    assert segments[0]["target_end"] == pytest.approx(2000, abs=3)
    assert segments[1]["target_start"] == pytest.approx(2005, abs=3)
    assert segments[1]["target_end"] == pytest.approx(4000, abs=3)
    # The missing scene is a gap of exactly its length.
    assert segments[3]["target_start"] - segments[2]["target_end"] == 300
    assert segments[2]["target_end"] == pytest.approx(6000, abs=3)
    assert document["unmatched_frames"] == pytest.approx(305, abs=3)
    assert document["similarity_median"] > 0.9


def test_a_crop_of_the_picture_is_found(tmp_path: Path) -> None:
    master = film(6000, seed=3)
    target_path = write(tmp_path / "t.gray", title_view(master))
    donor_path = write(tmp_path / "d.gray", cropped_view(master)[40:])
    document = build_frame_map(target_path, donor_path, target_fps=FILM, donor_fps=Fraction(25))
    assert document["segments"][0]["offset"] == -40
    assert document["segments"][0]["target_start"] == 40
    assert document["geometry"]["scale_x"] == pytest.approx(0.75, abs=0.03)
    assert document["similarity_median"] > 0.8


def test_unrelated_pictures_do_not_pass_as_a_match(tmp_path: Path) -> None:
    target_path = write(tmp_path / "t.gray", title_view(film(6000, seed=4)))
    donor_path = write(tmp_path / "d.gray", title_view(film(6000, seed=5)))
    try:
        document = build_frame_map(target_path, donor_path, target_fps=FILM, donor_fps=Fraction(25))
    except FrameMapError:
        return
    assert document["similarity_median"] < 0.5 or document["matched_frames"] < 3000


def test_same_running_time_at_another_frame_rate_is_time_locked(tmp_path: Path) -> None:
    master = film(7000, seed=6)
    step = Fraction(30000, 1001) / FILM
    # Each title frame shown for 1.25 donor frames on average.
    positions = np.floor(np.arange(int(len(master) * step)) / float(step)).astype(int)
    donor = master[np.clip(positions, 0, len(master) - 1)]
    target_path = write(tmp_path / "t.gray", title_view(master))
    donor_path = write(tmp_path / "d.gray", title_view(donor))
    document = build_frame_map(
        target_path, donor_path, target_fps=FILM, donor_fps=Fraction(30000, 1001)
    )
    assert document["mode"] == "time-locked"
    assert document["segments"][0]["offset"] == pytest.approx(0, abs=1)
    assert document["similarity_median"] > 0.9


def test_too_short_a_source_is_refused(tmp_path: Path) -> None:
    target_path = write(tmp_path / "t.gray", title_view(film(6000, seed=7)))
    donor_path = write(tmp_path / "d.gray", title_view(film(300, seed=7)))
    with pytest.raises(FrameMapError):
        build_frame_map(target_path, donor_path, target_fps=FILM, donor_fps=Fraction(25))


def test_grid_never_points_outside_the_donor() -> None:
    grid = frame_grid(100, Fraction(5, 4))
    assert grid[0] == 0
    assert grid[-1] == 99
    assert grid.max() < 100
