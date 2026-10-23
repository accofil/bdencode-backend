"""Subtitle timing is measured on packets, and a moved subtitle track is caught.

Up to 3.11.2 every subtitle was planned from ffprobe's ``start_time``: the
container's start (0) in the reference, but the first event in the sidecar.
The difference became an mkvmerge ``--sync`` that put every first subtitle
event at 0:00 (The Florist 2026: 71.863 s, 6.840 s and 71.905 s early).
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from bdencode.mux import first_packet_probe_command, parse_first_packet_time
from bdencode.worker import _first_packet_seconds, _subtitle_shift_ms


def test_the_first_packet_probe_reads_one_packet_of_one_stream() -> None:
    command = first_packet_probe_command(Path("reference.mkv"), "s:2")

    assert command[command.index("-select_streams") + 1] == "s:2"
    assert command[command.index("-read_intervals") + 1] == "%+#1"
    with pytest.raises(ValueError):
        first_packet_probe_command(Path("x.mkv"), "0:s:2")


def test_the_first_packet_time_falls_back_to_dts_and_allows_an_empty_stream() -> None:
    assert parse_first_packet_time({"packets": [{"pts_time": "35.044000"}]}) == Decimal("35.044")
    assert parse_first_packet_time({"packets": [{"pts_time": "N/A", "dts_time": "6.84"}]}) == Decimal("6.84")
    assert parse_first_packet_time({"packets": []}) is None
    with pytest.raises(ValueError):
        parse_first_packet_time({"packets": [{"pts_time": "N/A"}]})


def timeline(path: Path, times: list[str]) -> Path:
    path.write_bytes(json.dumps({"packets": [{"pts_time": t, "dts_time": t} for t in times]}).encode())
    return path


def test_the_florist_shift_is_measured_and_a_correct_mux_is_zero(tmp_path: Path) -> None:
    reference = timeline(tmp_path / "reference.json", ["71.863000", "73.907000"])
    broken = timeline(tmp_path / "broken.json", ["0.000000", "2.044000"])
    correct = timeline(tmp_path / "correct.json", ["71.863000", "73.907000"])

    assert _subtitle_shift_ms(reference, broken, Decimal(0)) == Decimal(-71863)
    assert _subtitle_shift_ms(reference, correct, Decimal(0)) == 0
    # A common zero later than 0 rebases the subtitle by the same amount.
    rebased = timeline(tmp_path / "rebased.json", ["71.821000"])
    assert _subtitle_shift_ms(reference, rebased, Decimal("0.042")) == 0


def test_a_stream_without_packets_has_no_shift(tmp_path: Path) -> None:
    empty = timeline(tmp_path / "empty.json", [])

    assert _first_packet_seconds(empty) is None
    assert _subtitle_shift_ms(empty, empty, Decimal(0)) is None
