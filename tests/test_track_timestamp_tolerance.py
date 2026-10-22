"""A copied track of a remux MKV source may move by one more 1 ms tick."""

from __future__ import annotations

from types import SimpleNamespace

from bdencode.qc.integrity import compare_packet_timelines, parse_packet_timeline
from bdencode.worker import _track_timestamp_tolerance_ms


def timeline(times_ms: list[int], sizes: list[int] | None = None):
    sizes = sizes or [2080] * len(times_ms)
    return parse_packet_timeline(
        {
            "packets": [
                {
                    "pts_time": f"{at / 1000:.6f}",
                    "dts_time": f"{at / 1000:.6f}",
                    "duration_time": "0.010000",
                    "size": str(size),
                }
                for at, size in zip(times_ms, sizes)
            ]
        }
    )


# The Florist 2026 remux: 10.67 ms DTS packets, the source muxer's timeline
# against mkvmerge's re-timed one (real values around packet 106).
SOURCE = [1108, 1119, 1131, 1141, 1152, 1163]
FINAL = [1108, 1118, 1129, 1139, 1150, 1160]


def test_an_mkv_source_allows_three_ticks_a_disc_two() -> None:
    assert _track_timestamp_tolerance_ms(SimpleNamespace(is_mkv=True)) == 3
    assert _track_timestamp_tolerance_ms(SimpleNamespace(is_mkv=False)) == 2


def test_the_real_remux_drift_passes_for_an_mkv_source_only() -> None:
    mkv = compare_packet_timelines(timeline(SOURCE), timeline(FINAL), timestamp_tolerance_ms=3)
    disc = compare_packet_timelines(timeline(SOURCE), timeline(FINAL), timestamp_tolerance_ms=2)

    assert mkv.passed
    assert not disc.passed and disc.first_mismatch_indexes == (5,)


def test_a_dropped_or_shifted_packet_still_fails() -> None:
    dropped = compare_packet_timelines(timeline(SOURCE), timeline(FINAL[:-1]), timestamp_tolerance_ms=3)
    shifted = compare_packet_timelines(
        timeline(SOURCE), timeline([*FINAL[:3], 1150, 1160, 1170]), timestamp_tolerance_ms=3
    )
    resized = compare_packet_timelines(
        timeline(SOURCE), timeline(FINAL, [2080] * 5 + [2048]), timestamp_tolerance_ms=3
    )

    assert not dropped.passed and not dropped.packet_count_matches
    assert not shifted.passed
    assert not resized.passed
