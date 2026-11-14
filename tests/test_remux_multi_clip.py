"""A multi-clip remux: eac3to gets the clips, and QC holds the remux to them."""

from __future__ import annotations

import json
import os
import struct
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any, Sequence

import pytest

import bdencode.worker as worker_module
from bdencode.config import Settings
from bdencode.db import Database
from bdencode.media.bluray import PlaylistSegment
from bdencode.models import JobState
from bdencode.qc import av_sync, multi_clip
from bdencode.remux import (
    clip_presentation,
    eac3to_clips_listing_command,
    eac3to_demux_command,
    DemuxOutput,
    whole_clips,
)
from bdencode.worker import PipelineWorker

from test_worker import FakeScanner
from test_worker_remux import RemuxRunner, _remux_scan, _select

CLIPS = (("00001", 600.0, 3092.0), ("00006", 3092.0, 3154.0))
TICKS = 45_000


def _clpi(start: int, end: int, *, atc: int = 1, stc: int = 1) -> bytes:
    sequence_info = 40
    header = b"HDMV0200" + struct.pack(">I", sequence_info)
    body = struct.pack(">IBB", 0, 0, atc) + struct.pack(">IBB", 0, stc, 0)
    body += struct.pack(">HIII", 4097, 0, start, end)
    return header.ljust(sequence_info, b"\0") + body


def _segments() -> tuple[PlaylistSegment, ...]:
    return (
        PlaylistSegment("00001", 600.0, 3092.0),
        PlaylistSegment("00006", 3092.0, 3154.0, relative_start_seconds=2492.0),
    )


def _playlist(tmp_path: Path, **change: Any):
    playlist = _remux_scan(tmp_path).playlists[0]
    return replace(playlist, **{"segments": _segments(), **change})


# --- which route eac3to takes ------------------------------------------------


def test_a_clpi_gives_the_clip_bounds() -> None:
    assert clip_presentation(_clpi(27_000_000, 139_158_296)) == (27_000_000, 139_158_296)


@pytest.mark.parametrize(
    "data", [b"", b"HDMV", b"XXXX0200" + b"\0" * 60, _clpi(1, 2, atc=2), _clpi(1, 2, stc=2)]
)
def test_a_clip_without_one_time_base_has_no_bounds(data: bytes) -> None:
    assert clip_presentation(data) is None


def _presentation() -> dict[str, tuple[int, int]]:
    return {clip: (int(start * TICKS), int(end * TICKS)) for clip, start, end in CLIPS}


def test_whole_clips_replace_the_playlist(tmp_path: Path) -> None:
    assert whole_clips(_playlist(tmp_path), _presentation()) == ("00001", "00006")


def test_a_part_of_a_clip_keeps_the_playlist(tmp_path: Path) -> None:
    presentation = _presentation()
    presentation["00006"] = (int(3092.0 * TICKS), int(3200.0 * TICKS))
    assert whole_clips(_playlist(tmp_path), presentation) == ()
    presentation = _presentation()
    presentation["00001"] = (int(500.0 * TICKS), int(3092.0 * TICKS))
    assert whole_clips(_playlist(tmp_path), presentation) == ()


def test_a_single_clip_keeps_the_playlist(tmp_path: Path) -> None:
    playlist = _playlist(tmp_path, segments=_segments()[:1])
    assert whole_clips(playlist, _presentation()) == ()


def test_a_repeated_clip_or_a_second_angle_keeps_the_playlist(tmp_path: Path) -> None:
    repeated = _playlist(tmp_path, segments=(_segments()[0], replace(_segments()[0], relative_start_seconds=2492.0)))
    assert whole_clips(repeated, _presentation()) == ()
    assert whole_clips(_playlist(tmp_path, angle_count=2), _presentation()) == ()


def test_a_clip_without_bounds_keeps_the_playlist(tmp_path: Path) -> None:
    assert whole_clips(_playlist(tmp_path), {"00001": (0, 1), "00006": None}) == ()


def test_eac3to_is_given_the_clips_without_a_title_number() -> None:
    outputs = (DemuxOutput("audio:4352", 3, "DTSHDMA", "03-audio.dtsma"),)
    command = eac3to_demux_command("/disc", "00002", outputs, chapters=False, clips=("00001", "00006"))
    assert command[2] == r"S:\BDMV\STREAM\00001.m2ts+S:\BDMV\STREAM\00006.m2ts"
    assert eac3to_demux_command("/disc", "00002", outputs, chapters=False)[2] == r"S:\BDMV\PLAYLIST\00002.mpls"
    assert eac3to_clips_listing_command("/disc", ("00001", "00006")) == [
        "bdencode-eac3to",
        "/disc",
        r"S:\BDMV\STREAM\00001.m2ts+S:\BDMV\STREAM\00006.m2ts",
    ]


# --- where the clips are measured -------------------------------------------


def test_windows_stay_inside_each_clip_on_the_title_timeline() -> None:
    windows = multi_clip.clip_windows(
        (
            PlaylistSegment("00001", 600.0, 700.0),
            PlaylistSegment("00002", 1000.0, 1041.5),
            PlaylistSegment("00003", 5.0, 9.0),  # too short for a window
            PlaylistSegment("00004", 50.0, 58.0),
        )
    )
    assert [(item.clip_id, item.clip_start_seconds, item.title_start_seconds) for item in windows] == [
        ("00001", Decimal("615.000"), Decimal("15.000")),
        ("00001", Decimal("665.000"), Decimal("65.000")),
        ("00002", Decimal("1001.000"), Decimal("101.000")),
        ("00002", Decimal("1020.500"), Decimal("120.500")),
        ("00004", Decimal("51.0"), Decimal("146.5")),
    ]
    assert windows[0].seconds == av_sync.WINDOW_SECONDS
    assert windows[-1].seconds == Decimal("6.0")


def test_the_tolerance_is_one_frame_of_a_codec_eac3to_can_cut() -> None:
    assert multi_clip.tolerance_ms("DTSHDMA") == Decimal("10.667")
    assert multi_clip.tolerance_ms("DD") == Decimal("32")
    assert multi_clip.tolerance_ms("TRUEHD") == av_sync.TOLERANCE_MS
    assert multi_clip.tolerance_ms("LPCM") == av_sync.TOLERANCE_MS


def test_a_shorter_window_is_decoded_when_asked() -> None:
    command = av_sync.sync_window_command(Path("c.m2ts"), 0, Decimal(1), Path("o.f32"), seconds=Decimal(6))
    assert command[command.index("-t") + 1] == "6.000"


def test_judging_uses_the_given_tolerance() -> None:
    window = av_sync.SyncWindow("1", "1", "7.438", 1.0, True)
    assert av_sync.judge((window,)).status == "out_of_sync"
    verdict = av_sync.judge((window,), tolerance_ms=Decimal("10.667"))
    assert verdict.status == "passed"
    assert verdict.tolerance_ms == "10.667"


def test_a_clip_stream_is_found_by_pid_and_codec() -> None:
    document = {
        "streams": [
            {"codec_type": "video", "id": "0x1011", "codec_name": "h264"},
            {"codec_type": "audio", "id": "0x1100", "codec_name": "truehd"},
            {"codec_type": "audio", "id": "0x1100", "codec_name": "ac3"},
            {"codec_type": "audio", "id": "0x1101", "codec_name": "dts"},
            {"codec_type": "subtitle", "id": "0x1200", "codec_name": "hdmv_pgs_subtitle"},
        ]
    }
    assert multi_clip.clip_ordinal(document, "audio", 0x1100, "ac3") == 1
    assert multi_clip.clip_ordinal(document, "audio", 0x1100, "truehd") == 0
    assert multi_clip.clip_ordinal(document, "audio", 0x1101, "dca") == 2
    assert multi_clip.clip_ordinal(document, "subtitle", 0x1200, "hdmv_pgs_subtitle") == 0
    assert multi_clip.clip_ordinal(document, "audio", 0x1102, "dts") is None
    assert multi_clip.clip_ordinal(document, "audio", 0x1100, "eac3") is None


# --- comparing packets -------------------------------------------------------

FRAME = 10


def _packets(*names: str) -> multi_clip.Packets:
    return multi_clip.Packets(
        Decimal("0.001"),
        tuple(index * FRAME for index in range(len(names))),
        tuple(("100", name) for name in names),
    )


def _at_seconds(index: int) -> Decimal:
    return Decimal(index * FRAME) / 1000


def test_framemd5_is_read_with_its_time_base() -> None:
    packets = multi_clip.parse_packets(
        "#format: frame checksums\n#version: 2\n#hash: MD5\n#tb 0: 1/1000\n"
        "#media_type 0: audio\n#stream#, dts,        pts, duration,     size, hash\n"
        "0,         42,         42,       11,     1088, 83f6\n"
        "0,         53,         53,       11,     1090, 9a01\n"
    )
    assert packets.contents == (("1088", "83f6"), ("1090", "9a01"))
    assert packets.seconds(1) == Decimal("0.053")


def test_packets_removed_at_a_join_pass() -> None:
    names = [f"p{i}" for i in range(200)]
    final = names[:100] + names[101:]
    comparison = multi_clip.compare_packets(_packets(*names), _packets(*final), (_at_seconds(100),))
    assert comparison.passed
    assert comparison.removed == ({"at_seconds": "1.000", "packets": 1},)


def test_a_packet_removed_away_from_every_join_fails() -> None:
    names = [f"p{i}" for i in range(200)]
    final = names[:100] + names[101:]
    comparison = multi_clip.compare_packets(_packets(*names), _packets(*final), (Decimal(1000),))
    assert not comparison.passed
    assert "away from every clip join" in (comparison.problem or "")


def test_a_changed_packet_fails_even_at_a_join() -> None:
    names = [f"p{i}" for i in range(200)]
    final = list(names)
    final[100] = "other"
    comparison = multi_clip.compare_packets(_packets(*names), _packets(*final), (_at_seconds(100),))
    assert not comparison.passed
    assert "is not the disc's" in (comparison.problem or "")


def test_a_shortened_track_fails() -> None:
    names = [f"p{i}" for i in range(200)]
    comparison = multi_clip.compare_packets(_packets(*names), _packets(*names[:150]), (_at_seconds(100),))
    assert not comparison.passed


def test_identical_packets_with_nothing_removed_cannot_explain_a_different_decode() -> None:
    names = [f"p{i}" for i in range(10)]
    comparison = multi_clip.compare_packets(_packets(*names), _packets(*names), ())
    assert not comparison.passed


def test_silence_may_hide_which_packet_went_at_the_join() -> None:
    # The join is at packet 100; the walk only notices the loss after the silence.
    names = [f"p{i}" for i in range(90)] + ["silence"] * 60 + [f"q{i}" for i in range(50)]
    final = names[:100] + names[101:]
    comparison = multi_clip.compare_packets(_packets(*names), _packets(*final), (_at_seconds(100),))
    assert comparison.passed


def test_join_seconds_are_on_the_title_timeline() -> None:
    assert multi_clip.join_seconds(_segments()) == (Decimal("2492.0"),)


# --- the worker --------------------------------------------------------------


class MultiClipRunner(RemuxRunner):
    """RemuxRunner plus the clips' streams, first packets and packet hashes."""

    def __init__(self) -> None:
        super().__init__()
        self.final_audio_md5: str | None = None
        self.final_packets: str | None = None
        self.clips_listing: str | None = None
        # The fake mux puts a subtitle's first event at the start of the title.
        self.first_subtitle: dict[str, str | None] = {"00001": "600.000000", "00006": None}

    def run(
        self,
        argv: Sequence[str | os.PathLike[str]],
        *,
        stdout_path: Path | None = None,
        stderr_path: Path | None = None,
        **kwargs: Any,
    ) -> None:
        command = tuple(os.fspath(item) for item in argv)
        if command[0] == "bdencode-eac3to" and len(command) == 3:
            self.commands.append(command)
            assert stdout_path is not None and "+" in command[2]
            self._write(stdout_path, self.clips_listing if self.clips_listing is not None else self.listing)
            if stderr_path is not None:
                self._write(stderr_path, "")
            return
        if command[0] == "ffprobe" and "stream=id,codec_name,codec_type" in command:
            self.commands.append(command)
            assert stdout_path is not None
            self._write(
                stdout_path,
                json.dumps(
                    {
                        "streams": [
                            {"codec_type": "video", "id": "0x1011", "codec_name": "h264"},
                            {"codec_type": "audio", "id": "0x1100", "codec_name": "truehd"},
                            {"codec_type": "audio", "id": "0x1101", "codec_name": "pcm_bluray"},
                            {"codec_type": "subtitle", "id": "0x1200", "codec_name": "hdmv_pgs_subtitle"},
                        ]
                    }
                ),
            )
            return
        if command[0] == "ffprobe" and "packet=pts_time,dts_time" in command and command[-1].endswith(".m2ts"):
            self.commands.append(command)
            assert stdout_path is not None
            first = self.first_subtitle[Path(command[-1]).stem]
            self._write(
                stdout_path,
                json.dumps({"packets": [{"pts_time": first, "dts_time": first}] if first else []}),
            )
            return
        if command[0] == "ffmpeg" and "framemd5" in command:
            self.commands.append(command)
            assert stdout_path is not None
            final = Path(command[command.index("-i") + 1]).name == "output.mkv"
            reference = "#tb 0: 1/1000\n0, 2491990, 2491990, 11, 100, aa\n0, 2492000, 2492000, 11, 100, bb\n0, 2492010, 2492010, 11, 100, cc\n"
            self._write(stdout_path, (self.final_packets or reference) if final else reference)
            if stderr_path is not None:
                self._write(stderr_path, "")
            return
        if command[0] == "ffmpeg" and command[-3:] == ("-f", "md5", "-"):
            final = Path(command[command.index("-i") + 1]).name == "output.mkv"
            if final and self.final_audio_md5 and command[command.index("-map") + 1] != "0:v:0":
                self.commands.append(command)
                assert stdout_path is not None
                self._write(stdout_path, f"MD5={self.final_audio_md5}\n")
                if stderr_path is not None:
                    self._write(stderr_path, "")
                return
        super().run(argv, stdout_path=stdout_path, stderr_path=stderr_path, **kwargs)


@pytest.fixture
def multi_clip_context(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        worker_module,
        "capability_snapshot",
        lambda _names: {"host": {"hostname": "test"}, "tools": {}},
    )
    monkeypatch.setattr(worker_module, "remux_support", lambda: {"available": True})
    source_root = tmp_path / "storage"
    source = source_root / "Movie"
    for folder, names, content in (
        ("PLAYLIST", ("00001.mpls",), b""),
        ("STREAM", ("00001.m2ts", "00006.m2ts"), b"x"),
    ):
        (source / "BDMV" / folder).mkdir(parents=True)
        for name in names:
            (source / "BDMV" / folder / name).write_bytes(content)
    (source / "BDMV" / "CLIPINF").mkdir()
    for clip, start, end in CLIPS:
        (source / "BDMV" / "CLIPINF" / f"{clip}.clpi").write_bytes(_clpi(int(start * TICKS), int(end * TICKS)))
    settings = Settings(
        data_root=tmp_path / "encode",
        source_roots=(source_root,),
        comparison_frames_per_type=1,
        worker_poll_seconds=0,
    ).validate()
    settings.create_directories()
    base = _remux_scan(source)
    scan = replace(base, playlists=(replace(base.playlists[0], segments=_segments()),))
    database = Database(tmp_path / "state.sqlite3")
    database.initialize()
    runner = MultiClipRunner()
    worker = PipelineWorker(
        database,
        settings,
        scanner_factory=lambda _settings: FakeScanner(scan),
        runner_factory=lambda _paths: runner,
    )
    return database, settings, scan, runner, worker


def _demux(runner: MultiClipRunner) -> tuple[str, ...]:
    return next(
        command
        for command in runner.commands
        if command[0] == "bdencode-eac3to" and any(item.startswith("-log=") for item in command)
    )


def _qc_report(settings: Settings, job_id: str) -> dict[str, Any]:
    paths = worker_module.JobPaths.create(settings, job_id)
    return json.loads((paths.analysis / "remux-qc.json").read_text(encoding="utf-8"))


def test_a_multi_clip_remux_demuxes_the_clips(multi_clip_context) -> None:
    _database, _settings, _scan, runner, worker = multi_clip_context
    result = worker.process_job(_select(multi_clip_context))

    assert result.state is JobState.COMPLETED, result.status_message
    assert _demux(runner)[2] == r"S:\BDMV\STREAM\00001.m2ts+S:\BDMV\STREAM\00006.m2ts"


def test_clips_that_list_other_tracks_keep_the_playlist(multi_clip_context) -> None:
    _database, _settings, _scan, runner, worker = multi_clip_context
    runner.clips_listing = runner.listing.replace("4: RAW/PCM", "6: RAW/PCM")

    result = worker.process_job(_select(multi_clip_context))

    assert result.state is JobState.COMPLETED, result.status_message
    assert _demux(runner)[2] == r"S:\BDMV\PLAYLIST\00001.mpls"


def test_sync_is_measured_against_the_clips_not_the_reference(multi_clip_context) -> None:
    _database, settings, _scan, runner, worker = multi_clip_context
    result = worker.process_job(_select(multi_clip_context))

    assert result.state is JobState.COMPLETED, result.status_message
    sources = {
        Path(command[command.index("-i") + 1]).name
        for command in runner.commands
        if command[0] == "ffmpeg" and "f32le" in command
    }
    assert sources == {"00001.m2ts", "00006.m2ts", "output.mkv"}
    checks = {item["check"]: item for item in _qc_report(settings, result.id)["checks"]}
    assert any(name.startswith("sync:") for name in checks)


def test_a_subtitle_is_placed_by_the_clip_that_holds_its_first_event(multi_clip_context) -> None:
    _database, _settings, _scan, runner, worker = multi_clip_context
    runner.first_subtitle = {"00001": None, "00006": "3100.000000"}

    result = worker.process_job(_select(multi_clip_context))

    assert result.state is JobState.NEEDS_REVIEW
    # 2492 s of the first clip, 8 s into the second; the fake mux says 0.
    assert "first subtitle event -2500000.000 ms from the disc" in (result.status_message or "")


def test_a_lag_beyond_one_frame_stops_the_remux(multi_clip_context, monkeypatch) -> None:
    _database, _settings, _scan, _runner, worker = multi_clip_context
    # The tracks here are TrueHD and PCM, which keep the measurement's own 1.5 ms.
    monkeypatch.setattr(av_sync, "measure_lag", lambda _a, _b: (540, 1.0, 1.0))

    result = worker.process_job(_select(multi_clip_context))

    assert result.state is JobState.NEEDS_REVIEW
    assert "11.250 ms from the disc" in (result.status_message or "")


def test_audio_that_differs_passes_only_as_packets_removed_at_a_join(multi_clip_context) -> None:
    _database, settings, _scan, runner, worker = multi_clip_context
    runner.final_audio_md5 = "3" * 32
    runner.final_packets = "#tb 0: 1/1000\n0, 2491990, 2491990, 11, 100, aa\n0, 2492010, 2492010, 11, 100, cc\n"

    result = worker.process_job(_select(multi_clip_context))

    assert result.state is JobState.COMPLETED, result.status_message
    audio = [
        item
        for item in _qc_report(settings, result.id)["checks"]
        if item["check"].startswith("audio:") and item.get("removed_at_joins")
    ]
    assert audio and "1 removed at the clip joins" in audio[0]["message"]


def test_audio_with_a_changed_packet_stops_the_remux(multi_clip_context) -> None:
    _database, _settings, _scan, runner, worker = multi_clip_context
    runner.final_audio_md5 = "3" * 32
    runner.final_packets = "#tb 0: 1/1000\n0, 2491990, 2491990, 11, 100, aa\n0, 2492000, 2492000, 11, 100, xx\n0, 2492010, 2492010, 11, 100, cc\n"

    result = worker.process_job(_select(multi_clip_context))

    assert result.state is JobState.NEEDS_REVIEW
    assert "is not the disc's" in (result.status_message or "")


def test_a_single_clip_title_stays_on_the_strict_md5(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        worker_module,
        "capability_snapshot",
        lambda _names: {"host": {"hostname": "test"}, "tools": {}},
    )
    monkeypatch.setattr(worker_module, "remux_support", lambda: {"available": True})
    source_root = tmp_path / "storage"
    source = source_root / "Movie"
    (source / "BDMV" / "PLAYLIST").mkdir(parents=True)
    (source / "BDMV" / "STREAM").mkdir()
    (source / "BDMV" / "STREAM" / "00001.m2ts").write_bytes(b"x")
    settings = Settings(
        data_root=tmp_path / "encode",
        source_roots=(source_root,),
        comparison_frames_per_type=1,
        worker_poll_seconds=0,
    ).validate()
    settings.create_directories()
    base = _remux_scan(source)
    scan = replace(base, playlists=(replace(base.playlists[0], segments=_segments()[:1]),))
    database = Database(tmp_path / "state.sqlite3")
    database.initialize()
    runner = MultiClipRunner()
    runner.final_audio_md5 = "3" * 32
    worker = PipelineWorker(
        database,
        settings,
        scanner_factory=lambda _settings: FakeScanner(scan),
        runner_factory=lambda _paths: runner,
    )
    context = (database, settings, scan, runner, worker)

    result = worker.process_job(_select(context))

    assert result.state is JobState.NEEDS_REVIEW
    assert "decodes differently from the disc" in (result.status_message or "")
    # 4.3.2: a failed QC keeps no checkpoint, so a retry measures again.
    stages = settings.data_root / "jobs" / result.id / ".stages"
    assert stages.is_dir() and not (stages / "remux-qc.json").exists()
    assert not any("framemd5" in command for command in runner.commands)
    assert _demux(runner)[2] == r"S:\BDMV\PLAYLIST\00001.mpls"
