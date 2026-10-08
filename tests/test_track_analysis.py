"""Selection-time track analysis: commands, PGS event counts, suggestions."""

from __future__ import annotations

import json
import wave
from pathlib import Path
from typing import Any

from bdencode.media.inference import SampleWindow
from bdencode.media.track_analysis import (
    EVENT_MIN_BYTES,
    StreamRef,
    analyse_playlist,
    classify_subtitles,
    count_events,
    parse_stream_indexes,
    playlists_to_analyse,
    window_extract_command,
)


def test_stream_indexes_take_the_first_stream_of_each_pid() -> None:
    document = {
        "streams": [
            {"index": 0, "id": "0x1011", "codec_type": "video"},
            {"index": 1, "id": "0x1100", "codec_type": "audio"},
            {"index": 2, "id": "0x1102", "codec_type": "audio"},  # TrueHD
            {"index": 3, "id": "0x1102", "codec_type": "audio"},  # its AC-3 core
            {"index": 4, "id": "0x1200", "codec_type": "subtitle"},
        ]
    }
    assert parse_stream_indexes(json.dumps(document)) == {0x1011: 0, 0x1100: 1, 0x1102: 2, 0x1200: 4}


def test_one_disc_read_per_window_writes_wavs_and_subtitle_matroska(tmp_path: Path) -> None:
    command = window_extract_command(
        Path("/discs/Film"),
        16,
        SampleWindow(1200.0, 30.0),
        [StreamRef("audio:4352", 4352, 1)],
        [StreamRef("subtitle:4608", 4608, 4)],
        tmp_path,
    )
    assert command.count("-i") == 1
    assert command[command.index("-playlist") + 1] == "16"
    assert command[command.index("-ss") + 1] == "1200.000"
    assert command[command.index("-i") + 1] == "bluray:/discs/Film"
    audio = command.index(str(tmp_path / "audio-4352.wav"))
    assert command[audio - 11:audio] == ["-map", "0:1", "-vn", "-sn", "-dn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le"]
    subtitle = command.index(str(tmp_path / "subtitle-4608.mks"))
    assert command[subtitle - 6:subtitle] == ["-map", "0:4", "-c", "copy", "-f", "matroska"]


def test_events_are_the_large_packets() -> None:
    sizes = "\n".join(["20", str(EVENT_MIN_BYTES), "31000", "18", "9000", "bad", ""])
    assert count_events(sizes) == 3


def test_rates_decide_full_and_forced() -> None:
    result = classify_subtitles(
        {"subtitle:1": 30, "subtitle:2": 0, "subtitle:3": 6},
        180.0,
        {"subtitle:1": "eng", "subtitle:2": "hun", "subtitle:3": "spa"},
    )
    assert result["subtitle:1"]["suggested_kind"] == "full"
    assert result["subtitle:1"]["confidence"] == "high"
    assert result["subtitle:1"]["events_per_minute"] == 10.0
    assert result["subtitle:2"]["suggested_kind"] == "forced"
    assert result["subtitle:2"]["confidence"] == "high"
    # 2/min: neither clearly full nor clearly forced.
    assert result["subtitle:3"]["suggested_kind"] is None
    assert result["subtitle:3"]["confidence"] == "low"


def test_the_rarer_of_two_same_language_subtitles_is_forced() -> None:
    result = classify_subtitles(
        {"subtitle:1": 36, "subtitle:2": 7},
        180.0,
        {"subtitle:1": "eng", "subtitle:2": "eng"},
    )
    # 2.3/min alone would be unclear; next to a 12/min English stream it is forced.
    assert result["subtitle:1"]["suggested_kind"] == "full"
    assert result["subtitle:2"]["suggested_kind"] == "forced"
    assert result["subtitle:2"]["confidence"] == "medium"


def test_only_recommended_playlists_with_distinct_tracks_are_analysed() -> None:
    def playlist(playlist_id: str, recommended: bool, streams: list[str]) -> dict[str, Any]:
        return {
            "playlist_id": playlist_id,
            "recommended": recommended,
            "streams": [{"id": sid, "kind": sid.split(":")[0]} for sid in streams],
        }

    chosen = playlists_to_analyse(
        [
            playlist("00001", True, ["audio:4352", "subtitle:4608"]),
            playlist("00002", False, ["audio:4352"]),
            playlist("00003", True, ["audio:4352", "subtitle:4608"]),  # same tracks: skip
            playlist("00004", True, ["audio:4353"]),
            playlist("00005", True, ["audio:4354"]),
            playlist("00006", True, ["audio:4355"]),
        ]
    )
    assert [item["playlist_id"] for item in chosen] == ["00001", "00004", "00005"]


def _write_wav(path: Path) -> None:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\x00\x00" * 1600)


def test_a_playlist_is_read_once_per_window_and_every_stream_is_reported(tmp_path: Path) -> None:
    playlist = {
        "playlist_id": "00016",
        "duration_seconds": 6900.0,
        "streams": [
            {"id": "video:4113", "kind": "video", "pid": 4113},
            {"id": "audio:4352", "kind": "audio", "pid": 4352, "language": {"iso639_2t": "eng"}},
            {"id": "audio:4354:truehd", "kind": "audio", "pid": 4354, "language": {"iso639_2t": "hun"}},
            {"id": "audio:4354:ac3", "kind": "audio", "pid": 4354, "language": {"iso639_2t": "hun"}},
            {"id": "subtitle:4608", "kind": "subtitle", "pid": 4608, "language": {"iso639_2t": "eng"}},
            {"id": "subtitle:4609", "kind": "subtitle", "pid": 4609, "language": {"iso639_2t": "eng"}},
        ],
    }
    reads: list[list[str]] = []

    def run(argv: list[str], cwd: Path) -> str:
        if argv[0] == "ffprobe" and "-playlist" in argv:
            return json.dumps({"streams": [
                {"index": 0, "id": "0x1011"}, {"index": 1, "id": "0x1100"},
                {"index": 2, "id": "0x1102"}, {"index": 3, "id": "0x1102"},
                {"index": 4, "id": "0x1200"}, {"index": 5, "id": "0x1201"},
            ]})
        if argv[0] == "ffmpeg":
            reads.append(argv)
            for item in argv:
                if item.endswith(".wav"):
                    _write_wav(Path(item))
                elif item.endswith(".mks"):
                    Path(item).write_bytes(b"mks")
            return ""
        # Packet sizes: 4608 is a full subtitle, 4609 shows one caption.
        if argv[-1].endswith("subtitle-4608.mks"):
            return "\n".join(["9000", "20"] * 5)
        if argv[-1].endswith("subtitle-4609.mks") and "window-03" in argv[-1]:
            return "9000\n20"
        return "20"

    detected: list[int] = []

    def detect(samples: Any) -> dict[str, Any]:
        detected.append(len(samples))
        return {"iso639_2t": "eng", "confidence": 0.95, "needs_review": False, "reason": "consensus"}

    result = analyse_playlist(Path("/discs/Film"), playlist, tmp_path, run=run, detect_language=detect)

    assert len(reads) == 6  # one disc read per window, all streams at once
    assert detected == [6, 6]  # one detection per PID, six samples each
    assert result["audio"]["audio:4354:ac3"] == result["audio"]["audio:4354:truehd"]
    assert result["audio"]["audio:4352"]["status"] == "detected"
    assert result["subtitles"]["subtitle:4608"]["events"] == 30
    assert result["subtitles"]["subtitle:4608"]["suggested_kind"] == "full"
    assert result["subtitles"]["subtitle:4609"]["events"] == 1
    assert result["subtitles"]["subtitle:4609"]["suggested_kind"] == "forced"


def test_without_speech_detection_audio_is_reported_unavailable(tmp_path: Path) -> None:
    playlist = {
        "playlist_id": "1",
        "duration_seconds": 600.0,
        "streams": [{"id": "audio:4352", "kind": "audio", "pid": 4352}],
    }

    def run(argv: list[str], cwd: Path) -> str:
        if argv[0] == "ffprobe":
            return json.dumps({"streams": [{"index": 1, "id": "0x1100"}]})
        return ""

    result = analyse_playlist(Path("/d"), playlist, tmp_path, run=run, detect_language=None)
    assert result["audio"] == {"audio:4352": {"status": "unavailable"}}
    assert result["subtitles"] == {}
