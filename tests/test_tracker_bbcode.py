"""Aither's comparison block and nCore's screenshots and comparison links."""

from __future__ import annotations

import pytest

from bdencode.qc.video import tracker_type_counts
from bdencode.tracker_bbcode import (
    comparison_pairs,
    encoder_summary,
    screenshot_pair_numbers,
    tracker_bbcode,
)


def make_pairs(categories: str, screenshots: set[int] = frozenset()) -> list[dict]:
    pairs = []
    for number, category in enumerate(categories, start=1):
        label = f"{number:02d}-{category}-f{number * 1000:09d}"
        pair = {
            "category": category,
            "presentation_index": number * 1000,
            "encoded_pts_seconds": str(number * 41.7),
            "reference_png": f"{label}-reference.png",
            "encode_png": f"{label}-encode.png",
            "reference_sdr_png": f"{label}-reference-sdr.png",
            "encode_sdr_png": f"{label}-encode-sdr.png",
        }
        if number in screenshots:
            pair["screenshot_png"] = f"{label}-screenshot.png"
        pairs.append(pair)
    return pairs


def upload_all(pairs: list[dict], *, sdr: bool = True) -> dict[str, dict]:
    uploaded = {}
    for pair in pairs:
        keys = ["reference_png", "encode_png", *(["reference_sdr_png", "encode_sdr_png"] if sdr else []), "screenshot_png"]
        for key in keys:
            if key in pair:
                name = pair[key]
                uploaded[name] = {"image_url": f"https://i.example/{name}", "viewer_url": f"https://v.example/{name}"}
    return uploaded


CATEGORIES = "IPBBPBIBB" * 2 + "PBIBPB"  # 24 pairs, B-heavy like a tracker job
AITHER_SHOTS = screenshot_pair_numbers(list(CATEGORIES), "aither")
PAIRS = make_pairs(CATEGORIES, AITHER_SHOTS)


def test_tracker_jobs_get_half_b_pairs_and_keep_i_and_p() -> None:
    assert tracker_type_counts(24) == {"I": 6, "P": 6, "B": 12}
    assert tracker_type_counts(12) == {"I": 1, "P": 1, "B": 10}


def test_screenshots_are_spread_b_pairs() -> None:
    assert len(AITHER_SHOTS) == 6 and all(CATEGORIES[number - 1] == "B" for number in AITHER_SHOTS)
    assert len(screenshot_pair_numbers(list(CATEGORIES), "ncore")) == 3
    assert screenshot_pair_numbers(list(CATEGORIES), "none") == set()


def test_comparisons_prefer_b_frames_never_i() -> None:
    chosen = comparison_pairs(PAIRS)
    assert len(chosen) == 12 and {item["category"] for item in chosen} == {"B"}
    indexes = [item["presentation_index"] for item in chosen]
    assert indexes == sorted(indexes)
    # Without enough B pairs, P pairs fill up to ten.
    assert [item["category"] for item in comparison_pairs(make_pairs("IPB" * 8))].count("P") == 2


def test_aither_block_follows_the_comparison_guide() -> None:
    lines = tracker_bbcode("aither", PAIRS, upload_all(PAIRS), encoder_log="x265 [info]: frame B: 1", codec="x265")
    block = next(line for line in lines if line.startswith("[comparison=Source, Encode]"))
    urls = block.removeprefix("[comparison=Source, Encode]").removesuffix("[/comparison]").split(" ")
    assert len(urls) == 24
    assert urls[0].endswith("-reference-sdr.png") and urls[1].endswith("-encode-sdr.png")
    start = lines.index("[center]")
    shots = lines[start + 1 : lines.index("[/center]")]
    assert len(shots) == 6 and all("[img=350]" in line and "-screenshot.png" in line for line in shots)
    assert "[spoiler=x265 log][code]" in lines and "x265 [info]: frame B: 1" in lines


def test_native_views_are_used_when_no_sdr_view_was_uploaded() -> None:
    lines = tracker_bbcode("aither", PAIRS, upload_all(PAIRS, sdr=False))
    block = next(line for line in lines if line.startswith("[comparison="))
    assert "-encode.png" in block and "-sdr.png" not in block


def test_ncore_has_three_clean_screenshots_and_comparison_links() -> None:
    pairs = make_pairs(CATEGORIES, screenshot_pair_numbers(list(CATEGORIES), "ncore"))
    lines = tracker_bbcode("ncore", pairs, upload_all(pairs))
    shots = [line for line in lines if line.startswith("[imgw]")]
    assert len(shots) == 3 and all("-screenshot.png" in line for line in shots)
    assert "[center][size=12pt][highlight]Forrás vs. Encode[/highlight][/size]" in lines
    links = [line for line in lines if line.startswith("[url=") and "Forrás" in line]
    assert len(links) == 12 and all("(B-frame, 00:" in line for line in links)
    assert lines[-1] == "[/center]"


def test_nothing_without_a_profile_or_without_uploads() -> None:
    assert tracker_bbcode("none", PAIRS, upload_all(PAIRS)) == []
    assert tracker_bbcode("aither", PAIRS, {}) == []


@pytest.mark.parametrize(
    ("log", "expected"),
    (
        (
            "frame=  100 fps= 2.4\nx265 [info]: HEVC encoder version 4.1\nx265 [info]: frame I:     10, Avg QP:13.01  kb/s: 70311.65\n"
            "Input #0, yuv4mpegpipe\nencoded 209389 frames in 84776.41s (2.47 fps), 37350.62 kb/s, Avg QP:15.83\n",
            "x265 [info]: HEVC encoder version 4.1\nx265 [info]: frame I:     10, Avg QP:13.01  kb/s: 70311.65\n"
            "encoded 209389 frames in 84776.41s (2.47 fps), 37350.62 kb/s, Avg QP:15.83",
        ),
        (
            "[libx264 @ 0x55d2c1a0] frame I:1234  Avg QP:14.20  size:123456\n[out#0/matroska @ 0x1] video:1kB\n",
            "libx264: frame I:1234  Avg QP:14.20  size:123456",
        ),
    ),
)
def test_the_encoder_summary_keeps_only_encoder_lines(log: str, expected: str) -> None:
    assert encoder_summary(log) == expected
