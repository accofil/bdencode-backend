from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from bdencode.media.bluray import (
    ContentKind,
    DiscKind,
    DiscScan,
    MediaStream,
    PlaylistCandidate,
    PlaylistSegment,
    StreamKind,
    ToolCapabilities,
)
from bdencode.object_audio_scan import detect_object_audio, object_audio_pids
from bdencode.process import ProcessFailure, ProcessResult

# Real MediaInfo 23.04 fields of a UHD disc (Housemaid 2025, canada).
REPORT = {
    "media": {
        "track": [
            {"@type": "General"},
            {"@type": "Video", "ID": "4113"},
            {
                "@type": "Audio",
                "ID": "4352",
                "Format": "MLP FBA",
                "Format_Commercial_IfAny": "Dolby TrueHD with Dolby Atmos",
            },
            {"@type": "Audio", "ID": "4353", "Format": "AC-3", "Format_Commercial_IfAny": "Dolby Digital"},
            {"@type": "Audio", "ID": "4354-1", "Format": "DTS", "Format_Commercial_IfAny": "DTS:X"},
        ]
    }
}


def _audio(stream_id: str, pid: int, codec: str) -> MediaStream:
    return MediaStream(id=stream_id, index=pid, pid=pid, kind=StreamKind.AUDIO, codec=codec)


def _scan(*playlists: PlaylistCandidate) -> DiscScan:
    return DiscScan(
        source=Path("/discs/Movie"),
        disc_kind=DiscKind.UHD,
        content_kind=ContentKind.FILM,
        playlists=playlists,
        capabilities=ToolCapabilities(),
        fingerprint="f" * 64,
    )


def _main(playlist_id: str = "00800", clip: str = "00002", duration: float = 7000.0) -> PlaylistCandidate:
    return PlaylistCandidate(
        playlist_id=playlist_id,
        duration_seconds=duration,
        segments=(PlaylistSegment(clip, 0.0, duration),),
        streams=(
            _audio("audio:4352:truehd", 4352, "truehd"),
            _audio("audio:4352:ac3", 4352, "ac3"),
            _audio("audio:4353", 4353, "ac3"),
        ),
        recommended=True,
    )


def test_atmos_and_dts_x_are_found_by_pid() -> None:
    assert object_audio_pids(REPORT) == {4352, 4354}
    assert object_audio_pids({"media": None}) == frozenset()
    assert object_audio_pids({}) == frozenset()


def test_the_truehd_is_marked_and_its_embedded_ac3_is_not(tmp_path: Path) -> None:
    commands: list[list[str]] = []

    def run(argv: list[str], *, stdout_path: Path, **_kwargs: Any) -> None:
        commands.append(argv)
        stdout_path.write_text(json.dumps(REPORT), encoding="utf-8")

    result = detect_object_audio(
        _scan(_main()),
        Path("/discs/Movie"),
        run=run,
        read_text=lambda path: path.read_text(encoding="utf-8"),
        work=tmp_path / "work",
        logs=tmp_path,
    )

    marked = {stream.id: stream.object_audio for stream in result.playlists[0].streams}
    assert marked == {"audio:4352:truehd": True, "audio:4352:ac3": False, "audio:4353": False}
    assert commands[0][1:] == ["--Output=JSON", str(Path("/discs/Movie/BDMV/STREAM/00002.m2ts"))]


def test_only_the_main_playlists_are_probed_and_a_clip_only_once(tmp_path: Path) -> None:
    commands: list[list[str]] = []

    def run(argv: list[str], *, stdout_path: Path, **_kwargs: Any) -> None:
        commands.append(argv)
        stdout_path.write_text(json.dumps(REPORT), encoding="utf-8")

    extra = PlaylistCandidate(
        playlist_id="00300",
        duration_seconds=300.0,
        segments=(PlaylistSegment("00009", 0.0, 300.0),),
        streams=(_audio("audio:4352", 4352, "truehd"),),
    )
    edition = PlaylistCandidate(
        playlist_id="00801",
        duration_seconds=7100.0,
        segments=(PlaylistSegment("00002", 0.0, 7100.0),),
        streams=(_audio("audio:4352", 4352, "truehd"),),
    )

    result = detect_object_audio(
        _scan(_main(), extra, edition),
        Path("/discs/Movie"),
        run=run,
        read_text=lambda path: path.read_text(encoding="utf-8"),
        work=tmp_path / "work",
        logs=tmp_path,
    )

    assert len(commands) == 1
    assert result.playlists[1].streams[0].object_audio is False
    assert result.playlists[2].streams[0].object_audio is True


def test_a_failed_probe_leaves_the_scan_as_it_was(tmp_path: Path) -> None:
    def run(argv: list[str], **_kwargs: Any) -> None:
        raise ProcessFailure(ProcessResult(tuple(argv), 1, 0.0, 0.0, None, None))

    scan = _scan(_main())

    result = detect_object_audio(
        scan,
        Path("/discs/Movie"),
        run=run,
        read_text=lambda path: path.read_text(encoding="utf-8"),
        work=tmp_path / "work",
        logs=tmp_path,
    )

    assert all(not stream.object_audio for stream in result.playlists[0].streams)
