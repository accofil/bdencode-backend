"""Blu-ray LPCM bit depth when ffprobe reports none (FFmpeg 5.1, Debian 12).

The Adventures of Sherlock Holmes DISC01: ``bits_per_sample=0``, no
``bits_per_raw_sample``; the job stopped with "unsupported bit depth: 0".
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Sequence

from bdencode.media.bluray import (
    BluRayScanner,
    CaptureResult,
    ToolCapabilities,
    _hexdump_bytes,
    _stream_bit_depth,
    pcm_bluray_header_bit_depth,
)

# The first packet of audio:4352 on that disc (16-bit stereo, 48 kHz).
SHERLOCK_DUMP = (
    "\n00000000: 03c0 3140 0000 0000 0000 0000 0000 0000  ..1@............"
    "\n00000010: 0000 0000 0000 0000 0000 0000 0000 0000  ................\n"
)


def test_header_bits_give_the_depth() -> None:
    assert pcm_bluray_header_bit_depth(bytes.fromhex("03c03140")) == 16
    assert pcm_bluray_header_bit_depth(bytes.fromhex("05a03180")) == 20
    assert pcm_bluray_header_bit_depth(bytes.fromhex("0b4031c0")) == 24
    # Code 0 is reserved; a short header says nothing.
    assert pcm_bluray_header_bit_depth(bytes.fromhex("03c03100")) is None
    assert pcm_bluray_header_bit_depth(b"\x03\xc0") is None


def test_hexdump_is_read_up_to_the_ascii_column() -> None:
    assert _hexdump_bytes(SHERLOCK_DUMP, 4) == bytes.fromhex("03c03140")
    assert _hexdump_bytes(SHERLOCK_DUMP, 18) == bytes.fromhex("03c03140" + "00" * 14)
    assert _hexdump_bytes("", 4) == b""


def test_zero_is_not_a_depth() -> None:
    assert _stream_bit_depth({"bits_per_sample": 0}, {}) is None
    assert _stream_bit_depth({"bits_per_raw_sample": "24", "bits_per_sample": 0}, {}) == 24
    assert _stream_bit_depth({"bits_per_sample": 0}, {"bit_depth": 16}) == 16
    assert _stream_bit_depth({"bits_per_raw_sample": "N/A"}, {}) is None


class PacketRunner:
    """Answers ffprobe packet reads per (clip name, PID)."""

    def __init__(self, dumps: dict[tuple[str, int], str]) -> None:
        self.dumps = dumps
        self.calls: list[tuple[str, ...]] = []

    def capture(
        self,
        argv: Sequence[str | Path],
        *,
        timeout: float = 30,
        check: bool = True,
    ) -> CaptureResult:
        args = tuple(str(item) for item in argv)
        self.calls.append(args)
        pid = int(args[args.index("-select_streams") + 1].removeprefix("i:"))
        dump = self.dumps.get((Path(args[-1]).name, pid))
        packets: list[dict[str, Any]] = [] if dump is None else [{"data": dump}]
        return CaptureResult(returncode=0, stdout=json.dumps({"packets": packets}), stderr="")


def _scanner(tmp_path: Path, runner: PacketRunner) -> tuple[BluRayScanner, Path]:
    root = tmp_path / "disc"
    stream_directory = root / "BDMV" / "STREAM"
    stream_directory.mkdir(parents=True)
    for name in ("00004.m2ts", "00000.m2ts"):
        (stream_directory / name).write_bytes(b"")
    scanner = BluRayScanner(
        runner=runner,
        capabilities=ToolCapabilities(ffprobe="/usr/bin/ffprobe", ffprobe_bluray=True),
        source_root=tmp_path,
    )
    return scanner, root


NATIVE = {
    "segments": [
        # A short opening clip without the audio, then the feature.
        {"clip_id": "00004", "in_time": 0, "out_time": 10, "duration": 10},
        {"clip_id": "00000", "in_time": 0, "out_time": 3000, "duration": 3000},
    ]
}


def _probe() -> dict[str, Any]:
    return {
        "streams": [
            {"index": 0, "id": "0x1011", "codec_type": "video", "codec_name": "h264"},
            {
                "index": 1,
                "id": "0x1100",
                "codec_type": "audio",
                "codec_name": "pcm_bluray",
                "sample_fmt": "s16",
                "bits_per_sample": 0,
            },
            {
                "index": 2,
                "id": "0x1101",
                "codec_type": "audio",
                "codec_name": "pcm_bluray",
                "bits_per_raw_sample": "24",
                "bits_per_sample": 0,
            },
        ]
    }


def test_scanner_reads_the_depth_from_the_lpcm_header(tmp_path: Path) -> None:
    runner = PacketRunner({("00004.m2ts", 4352): SHERLOCK_DUMP.replace("3140", "3100"),
                           ("00000.m2ts", 4352): SHERLOCK_DUMP})
    scanner, root = _scanner(tmp_path, runner)

    enriched = scanner._with_pcm_bluray_bit_depth(root, _probe(), NATIVE)

    assert enriched["streams"][1]["bits_per_raw_sample"] == 16
    # A depth ffprobe did report is kept, and its stream is not read again.
    assert enriched["streams"][2]["bits_per_raw_sample"] == "24"
    assert all("i:4353" not in call for call in runner.calls)
    # The feature clip (most running time) is read first.
    assert Path(runner.calls[0][-1]).name == "00000.m2ts"
    assert len(runner.calls) == 1

    stream = scanner._stream_from_probe(1, enriched["streams"][1], {})
    assert stream.bit_depth == 16


def test_scanner_falls_back_to_the_next_clip_and_leaves_unknown_alone(
    tmp_path: Path,
) -> None:
    runner = PacketRunner({("00004.m2ts", 4352): SHERLOCK_DUMP})
    scanner, root = _scanner(tmp_path, runner)

    enriched = scanner._with_pcm_bluray_bit_depth(root, _probe(), NATIVE)
    assert enriched["streams"][1]["bits_per_raw_sample"] == 16
    assert [Path(call[-1]).name for call in runner.calls] == ["00000.m2ts", "00004.m2ts"]

    nothing = PacketRunner({})
    scanner, root = _scanner(tmp_path / "other", nothing)
    probe = _probe()
    unchanged = scanner._with_pcm_bluray_bit_depth(root, probe, NATIVE)
    assert unchanged is probe
    # Still unknown: the worker asks for review instead of guessing.
    assert scanner._stream_from_probe(1, probe["streams"][1], {}).bit_depth is None
