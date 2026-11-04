"""The remux mode end to end: eac3to under Wine, mkvmerge, untouched-QC."""

from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path
from typing import Any, Sequence

import pytest

import bdencode.worker as worker_module
from bdencode.config import Settings
from bdencode.db import Database
from bdencode.media.bluray import (
    ContentKind,
    DiscKind,
    DiscScan,
    HdrStaticMetadata,
    MediaStream,
    PlaylistCandidate,
    StreamKind,
    ToolCapabilities,
    VideoCodec,
    VideoProperties,
)
from bdencode.media.language import LanguageDecision, LanguageStatus
from bdencode.models import JobState
from bdencode.queue import JobQueue
from bdencode.worker import PipelineWorker, ReviewRequired, parse_selection

from test_worker import FakeRunner, FakeScanner, _enqueue  # noqa: F401

NAME = "Movie.2026.1080p.BluRay.REMUX.AVC.TrueHD.5.1-TAG"

LISTING = """\
M2TS, 1 video track, 2 audio tracks, 1 subtitle track, 2:00:00, 24p /1.001
1: Chapters, 12 chapters
2: h264/AVC, 1080p24 /1.001 (16:9)
3: TrueHD/AC3, English, 5.1 channels, 48kHz, dialnorm: -27dB
   (embedded: AC3, 5.1 channels, 640kbps, 48kHz)
4: RAW/PCM, English, 2.0 channels, 24 bits, 48kHz
5: Subtitle (PGS), English
"""


def _language(code: str, bcp47: str) -> LanguageDecision:
    return LanguageDecision(
        iso639_2t=code, bcp47=bcp47, status=LanguageStatus.DECLARED, confidence=1.0
    )


def _remux_scan(source: Path, *, disc_kind: DiscKind = DiscKind.BD) -> DiscScan:
    return DiscScan(
        source=source.resolve(),
        disc_kind=disc_kind,
        content_kind=ContentKind.FILM,
        playlists=(
            PlaylistCandidate(
                playlist_id="00001",
                duration_seconds=7200,
                chapters=tuple(float(value * 600) for value in range(12)),
                streams=(
                    MediaStream(
                        id="video:4113",
                        index=0,
                        pid=4113,
                        kind=StreamKind.VIDEO,
                        codec="h264",
                        codec_profile="High",
                        video=VideoProperties(
                            codec=VideoCodec.AVC,
                            width=1920,
                            height=1080,
                            frame_rate="24000/1001",
                            field_order="progressive",
                            bit_depth=8,
                            pixel_format="yuv420p",
                            color_primaries="bt709",
                            color_transfer="bt709",
                            color_matrix="bt709",
                        ),
                    ),
                    MediaStream(
                        id="audio:4352",
                        index=1,
                        pid=4352,
                        kind=StreamKind.AUDIO,
                        codec="truehd",
                        language=_language("eng", "en"),
                        channels=6,
                        sample_rate=48000,
                        bit_depth=24,
                    ),
                    MediaStream(
                        id="audio:4353",
                        index=2,
                        pid=4353,
                        kind=StreamKind.AUDIO,
                        codec="pcm_bluray",
                        language=_language("eng", "en"),
                        channels=2,
                        sample_rate=48000,
                        bit_depth=24,
                    ),
                    MediaStream(
                        id="subtitle:4608",
                        index=3,
                        pid=4608,
                        kind=StreamKind.SUBTITLE,
                        codec="hdmv_pgs_subtitle",
                        language=_language("eng", "en"),
                    ),
                ),
                recommended=True,
            ),
        ),
        capabilities=ToolCapabilities(),
        fingerprint="b" * 64,
    )


def _remux_selection(**updates: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "schema_version": 2,
        "mode": "remux",
        "playlist_id": "00001",
        "angle": 1,
        "tracks": [
            {"stream_id": "audio:4352", "action": "copy", "language": "eng", "order": 0},
            {"stream_id": "audio:4353", "action": "flac", "language": "eng", "order": 1},
            {
                "stream_id": "subtitle:4608",
                "action": "copy",
                "language": "eng",
                "subtitle_kind": "full",
                "order": 2,
            },
        ],
        "output_name": NAME,
        "upload_images": False,
        "tracker_profile": "aither",
        "remux": {"imdb": "tt0123456", "tmdb": "movie/42"},
    }
    value.update(updates)
    return value


class RemuxRunner(FakeRunner):
    """FakeRunner plus eac3to, ffprobe of elementary streams and mkvmerge -J."""

    def __init__(self) -> None:
        super().__init__()
        self.listing = LISTING
        self.log_extra = ""
        self.final_video_md5 = "1" * 32
        self.dovi_report: dict[str, Any] = {
            "streams": [
                {
                    "side_data_list": [
                        {
                            "dv_profile": 7,
                            "rpu_present_flag": 1,
                            "el_present_flag": 1,
                            "bl_present_flag": 1,
                        }
                    ]
                }
            ]
        }
        self.layer_reports: dict[str, dict[str, Any]] = {
            "reference": {"units": 5, "sha256": "a" * 64},
            "final": {"units": 5, "sha256": "a" * 64},
        }
        self.last_mux: tuple[str, ...] | None = None

    def run(
        self,
        argv: Sequence[str | os.PathLike[str]],
        *,
        cwd: Path | None = None,
        env: Any = None,
        stdout_path: Path | None = None,
        stderr_path: Path | None = None,
        check: bool = True,
        ok_returncodes: Sequence[int] = (0,),
        timeout: float | None = None,
        **_kwargs: Any,
    ) -> None:
        command = tuple(os.fspath(item) for item in argv)
        if command[0] == "bdencode-eac3to":
            self.commands.append(command)
            assert env is not None and env["BDENCODE_WINEPREFIX"].endswith(os.path.join("work", "wine"))
            assert cwd is not None and cwd.name == "remux"
            outputs = [item for item in command[3:] if ":" in item and not item.startswith("-")]
            if stderr_path is not None:
                self._write(stderr_path, "")
            if not outputs:
                assert stdout_path is not None
                self._write(stdout_path, self.listing)
                return
            for item in outputs:
                self._write(cwd / item.split(":", 1)[1], b"es-" + item.encode())
            self._write(
                cwd / "eac3to.log",
                "eac3to v3.36\ncommand line: \"C:\\eac3to\\eac3to.exe\" S:\\BDMV\\PLAYLIST\\00001.mpls\n"
                + self.listing
                + self.log_extra
                + "Video track 2 contains 172627 frames.\neac3to processing took 3 minutes.\nDone.\n",
            )
            if stdout_path is not None:
                self._write(stdout_path, "process: 100%\n")
            return
        if command[0] == "ffprobe" and "stream=codec_name,profile,level,width,height,sample_rate,channels," \
                "bits_per_raw_sample,bits_per_sample,sample_fmt" in command:
            self.commands.append(command)
            name = Path(command[-1]).name
            stream: dict[str, Any] = {
                "h264": {"codec_name": "h264", "profile": "High", "level": 41},
                "hevc": {"codec_name": "hevc", "profile": "Main 10", "level": 153},
                "thd": {"codec_name": "truehd", "sample_rate": "48000", "channels": 6, "bits_per_raw_sample": "24"},
                "ac3": {"codec_name": "ac3", "sample_rate": "48000", "channels": 6},
                "flac": {"codec_name": "flac", "sample_rate": "48000", "channels": 2, "bits_per_raw_sample": "16"},
            }[name.rsplit(".", 1)[-1]]
            assert stdout_path is not None
            self._write(stdout_path, json.dumps({"streams": [stream]}))
            return
        if command[0] == "dovi_tool" and command[1] == "mux":
            self.commands.append(command)
            self._write(Path(command[command.index("--output") + 1]), b"\x00\x00\x01dual-layer")
            return
        if "bdencode.dovi_layers" in command:
            self.commands.append(command)
            assert stdout_path is not None
            side = "final" if command[-1] == "joined" else "reference"
            self._write(stdout_path, json.dumps(self.layer_reports[side]))
            if stderr_path is not None:
                self._write(stderr_path, "")
            return
        if command[0] == "ffprobe" and "stream_side_data" in command:
            self.commands.append(command)
            assert stdout_path is not None
            self._write(stdout_path, json.dumps(self.dovi_report))
            if stderr_path is not None:
                self._write(stderr_path, "")
            return
        if command[:2] == ("mkvmerge", "-J"):
            self.commands.append(command)
            assert stdout_path is not None and self.last_mux is not None
            self._write(stdout_path, json.dumps(_identify(self.last_mux)))
            return
        if command[0] == "ffmpeg" and command[-3:] == ("-f", "md5", "-"):
            self.commands.append(command)
            assert stdout_path is not None
            stream = command[command.index("-map") + 1]
            final = Path(command[command.index("-i") + 1]).name == "output.mkv"
            digest = self.final_video_md5 if final and stream == "0:v:0" else (
                "1" * 32 if stream == "0:v:0" else "2" * 32
            )
            self._write(stdout_path, f"MD5={digest}\n")
            if stderr_path is not None:
                self._write(stderr_path, "")
            return
        if command[0] == "mkvmerge" and "--output" in command:
            self.last_mux = command
        super().run(
            argv,
            cwd=cwd,
            env=env,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            check=check,
            ok_returncodes=ok_returncodes,
            timeout=timeout,
        )


def _identify(mux: tuple[str, ...]) -> dict[str, Any]:
    """What ``mkvmerge -J`` reports for the file the mux command wrote."""

    tracks: list[dict[str, Any]] = []
    current: dict[str, Any] = {}
    index = mux.index("--language")
    while index < len(mux) and mux[index] != "--track-order":
        item = mux[index]
        if item.startswith("--"):
            value = mux[index + 1].split(":", 1)[-1]
            current[item] = value
            index += 2
            continue
        kind = {"h264": "video", "hevc": "video", "sup": "subtitles"}.get(item.rsplit(".", 1)[-1], "audio")
        properties = {
            "language_ietf": current.get("--language"),
            "track_name": current.get("--track-name"),
            "default_track": current.get("--default-track-flag") == "yes",
            "forced_track": current.get("--forced-display-flag") == "yes",
            "flag_original": current.get("--original-flag") == "yes",
            "flag_commentary": current.get("--commentary-flag") == "yes",
            "flag_hearing_impaired": current.get("--hearing-impaired-flag") == "yes",
            "flag_visual_impaired": current.get("--visual-impaired-flag") == "yes",
        }
        tracks.append({"type": kind, "properties": properties})
        current = {}
        index += 1
    return {"tracks": tracks, "chapters": [{"num_entries": 12}]}


@pytest.fixture
def remux_context(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        worker_module,
        "capability_snapshot",
        lambda _names: {"host": {"hostname": "test"}, "tools": {}},
    )
    monkeypatch.setattr(worker_module, "remux_support", lambda: {"available": True})
    source_root = tmp_path / "storage"
    source = source_root / "Movie"
    (source / "BDMV" / "PLAYLIST").mkdir(parents=True)
    settings = Settings(
        data_root=tmp_path / "encode",
        source_roots=(source_root,),
        comparison_frames_per_type=1,
        worker_poll_seconds=0,
    ).validate()
    settings.create_directories()
    scan = _remux_scan(source)
    database = Database(tmp_path / "state.sqlite3")
    database.initialize()
    scanner = FakeScanner(scan)
    runner = RemuxRunner()
    worker = PipelineWorker(
        database,
        settings,
        scanner_factory=lambda _settings: scanner,
        runner_factory=lambda _paths: runner,
    )
    return database, settings, scan, runner, worker


def _select(remux_context, selection: dict[str, Any] | None = None):
    database, _settings, scan, _runner, worker = remux_context
    job = _enqueue(database, scan.source)
    claimed = JobQueue(database).claim_next()
    assert claimed is not None
    awaiting = worker.process_one_stage(claimed)
    assert awaiting.state is JobState.AWAITING_SELECTION
    return database.set_selection(job.id, selection or _remux_selection())


def test_a_remux_runs_from_eac3to_to_the_published_release(remux_context) -> None:
    database, settings, _scan, runner, worker = remux_context
    ready = _select(remux_context)

    result = worker.process_job(ready)

    assert result.state is JobState.COMPLETED, result.status_message
    eac3to = [command for command in runner.commands if command[0] == "bdencode-eac3to"]
    assert eac3to[1][2:] == (
        "S:\\BDMV\\PLAYLIST\\00001.mpls",
        "1:chapters.txt",
        "2:02-video.h264",
        "3:03-audio.thd",
        "3:03-compatibility.ac3",
        "-keepDialnorm",
        "4:04-audio.flac",
        "5:05-subtitle.sup",
        "-progressnumbers",
        "-log=eac3to.log",
    )
    mux = runner.last_mux
    assert mux is not None
    assert mux[mux.index("--title") + 1] == "Movie (2026)"
    assert mux[mux.index("--global-tags") + 1].endswith("tags.xml")
    names = [mux[index + 1].removeprefix("0:") for index, item in enumerate(mux) if item == "--track-name"]
    assert names[0].startswith("MPEG-4 AVC Video / ")
    assert names[0].endswith(" kbps / 1080p / 23.976 fps / 16:9 / High Profile 4.1")
    assert names[1].startswith("Dolby TrueHD Audio / 5.1 / 48 kHz / ")
    assert names[1].endswith(" kbps / 24-bit")
    assert names[2].startswith("Compatibility Track / Dolby Digital Audio / 5.1 / 48 kHz / ")
    assert names[3].startswith("FLAC Audio / 2.0 / 48 kHz / ") and names[3].endswith("/ 16-bit")
    thd = mux.index(next(item for item in mux if item.endswith("03-audio.thd")))
    compat = mux.index(next(item for item in mux if item.endswith("03-compatibility.ac3")))
    assert "--remove-dialog-normalization-gain" in mux[mux.index(next(item for item in mux if item.endswith("02-video.h264"))) : thd]
    assert "--remove-dialog-normalization-gain" not in mux[thd:compat]
    assert mux.count("--compression") == 5

    completed = settings.completed_root / NAME
    assert (completed / f"{NAME}.mkv").is_file()
    log = (completed / "comparison" / "eac3to.log").read_text(encoding="utf-8")
    assert "S:\\BDMV\\PLAYLIST\\00001.mpls" in log
    bbcode = (completed / "comparison" / "comparison.bbcode").read_text(encoding="utf-8")
    assert "[spoiler=eac3to log][code]" in bbcode
    assert f"{NAME} — remux" in bbcode
    assert len(list((completed / "comparison").glob("*-screenshot.png"))) == 6
    qc = json.loads((completed / "analysis" / "remux-qc.json").read_text(encoding="utf-8"))
    assert qc["status"] == "passed"
    assert {item["check"] for item in qc["checks"]} >= {
        "tracks",
        "chapters",
        "video:video",
        "audio:03-audio.thd",
        "audio:04-audio.flac",
        "subtitle:05-subtitle.sup",
        "sync:03-audio.thd",
        "sync:03-compatibility.ac3",
        "sync:04-audio.flac",
        "subtitle-sync:05-subtitle.sup",
    }
    assert not any(
        command[0] in {"x264", "x265", "vspipe"} for command in runner.commands
    ), "a remux encodes nothing"


def test_a_video_that_decodes_differently_stops_the_remux(remux_context) -> None:
    database, _settings, _scan, runner, worker = remux_context
    runner.final_video_md5 = "9" * 32
    ready = _select(remux_context)

    result = worker.process_job(ready)

    assert result.state is JobState.NEEDS_REVIEW
    assert "decodes differently from the disc" in (result.status_message or "")


def test_an_eac3to_error_stops_the_remux_before_the_mux(remux_context) -> None:
    _database, _settings, _scan, runner, worker = remux_context
    runner.log_extra = "[v02] The video bitstream is broken.  <ERROR>\n"
    ready = _select(remux_context)

    result = worker.process_job(ready)

    assert result.state is JobState.NEEDS_REVIEW
    assert "eac3to reported an error" in (result.status_message or "")
    assert runner.last_mux is None


def test_eac3to_and_scan_disagreement_stops_at_prepare(remux_context) -> None:
    _database, _settings, _scan, runner, worker = remux_context
    runner.listing = LISTING.replace("4: RAW/PCM, English, 2.0 channels", "4: DTS Master Audio, English, 2.0 channels")
    ready = _select(remux_context)

    result = worker.process_job(ready)

    assert result.state is JobState.NEEDS_REVIEW
    assert "eac3to and the scan disagree" in (result.status_message or "")


def test_an_atmos_track_needs_atmos_in_the_name(remux_context) -> None:
    _database, _settings, _scan, runner, worker = remux_context
    runner.listing = LISTING.replace("TrueHD/AC3, English", "TrueHD/AC3 (Atmos), English")
    ready = _select(remux_context)

    result = worker.process_job(ready)

    assert result.state is JobState.NEEDS_REVIEW
    assert "must say Atmos" in (result.status_message or "")


def _job(scan: DiscScan, selection: dict[str, Any]):
    class _Job:
        pass

    job = _Job()
    job.selection = selection
    job.content_type = type("C", (), {"value": "FILM"})()
    return job


@pytest.mark.parametrize(
    ("change", "message"),
    (
        (
            lambda value: value["tracks"][1].update(action="copy"),
            "keeps pcm_bluray audio as flac",
        ),
        (lambda value: value["tracks"][0].update(action="ac3"), "keeps truehd audio as copy"),
        (lambda value: value.update(output_name="Movie.2026.1080p.BluRay.TrueHD.5.1.x264-TAG"), "clean remux name"),
        (lambda value: value.update(output_name="Movie.2026.1080p.BluRay.REMUX.AVC.FLAC.2.0-TAG"), "default audio track is TrueHD"),
        (lambda value: value.update(video={"crop": {}}), "unknown remux selection field"),
        (lambda value: value.update(angle=2), "angle must be 1"),
        (lambda value: value["remux"].update(imdb="123"), "remux.imdb"),
        (lambda value: value.update(tracks=[]), "at least one audio track"),
    ),
)
def test_remux_selection_is_validated(tmp_path: Path, change, message: str) -> None:
    scan = _remux_scan(tmp_path)
    selection = _remux_selection()
    change(selection)

    with pytest.raises(ReviewRequired, match=message):
        parse_selection(_job(scan, selection), scan)


def test_a_remux_needs_the_disc_itself(tmp_path: Path) -> None:
    mkv = replace(_remux_scan(tmp_path), source_kind="mkv")
    with pytest.raises(ReviewRequired, match="from the disc itself"):
        parse_selection(_job(mkv, _remux_selection()), mkv)


def test_a_valid_remux_selection_parses_as_a_remux(tmp_path: Path) -> None:
    scan = _remux_scan(tmp_path)

    parsed = parse_selection(_job(scan, _remux_selection()), scan)

    assert parsed.is_remux
    assert parsed.remux is not None and parsed.remux.imdb == "tt0123456"
    assert [item.action.value for item in parsed.tracks] == ["copy", "flac", "copy"]


def test_a_host_without_eac3to_stops_the_remux_at_prepare(remux_context, monkeypatch) -> None:
    _database, _settings, _scan, runner, worker = remux_context
    monkeypatch.setattr(
        worker_module,
        "remux_support",
        lambda: {"available": False, "eac3to": False, "wine": True, "uhd": False},
    )
    ready = _select(remux_context)

    result = worker.process_job(ready)

    assert result.state is JobState.NEEDS_REVIEW
    assert "eac3to or Wine is missing" in (result.status_message or "")
    assert not any(command[0] == "bdencode-eac3to" for command in runner.commands)


def _with_embedded_core(scan: DiscScan) -> DiscScan:
    """A TrueHD PID as the scan really lists it: two streams on one PID."""

    playlist = scan.playlists[0]
    video, truehd, pcm, subtitle = playlist.streams
    return replace(
        scan,
        playlists=(
            replace(
                playlist,
                streams=(
                    video,
                    replace(truehd, id="audio:4352:truehd"),
                    replace(truehd, id="audio:4352:ac3", index=2, codec="ac3", bit_depth=0),
                    replace(pcm, index=3),
                    replace(subtitle, index=4),
                ),
            ),
        ),
    )


def test_a_truehd_listed_twice_by_the_scan_gets_one_compatibility_track(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        worker_module,
        "capability_snapshot",
        lambda _names: {"host": {"hostname": "test"}, "tools": {}},
    )
    monkeypatch.setattr(worker_module, "remux_support", lambda: {"available": True})
    source_root = tmp_path / "storage"
    source = source_root / "Movie"
    (source / "BDMV" / "PLAYLIST").mkdir(parents=True)
    settings = Settings(
        data_root=tmp_path / "encode",
        source_roots=(source_root,),
        comparison_frames_per_type=1,
        worker_poll_seconds=0,
    ).validate()
    settings.create_directories()
    scan = _with_embedded_core(_remux_scan(source))
    database = Database(tmp_path / "state.sqlite3")
    database.initialize()
    scanner = FakeScanner(scan)
    runner = RemuxRunner()
    worker = PipelineWorker(
        database,
        settings,
        scanner_factory=lambda _settings: scanner,
        runner_factory=lambda _paths: runner,
    )
    selection = _remux_selection()
    selection["tracks"] = [
        {"stream_id": "audio:4352:truehd", "action": "copy", "language": "eng", "order": 0},
        # The wizard leaves this row out; a stored copy must not double the track.
        {"stream_id": "audio:4352:ac3", "action": "copy", "language": "eng", "order": 1},
        {"stream_id": "audio:4353", "action": "flac", "language": "eng", "order": 2},
        {"stream_id": "subtitle:4608", "action": "copy", "language": "eng", "subtitle_kind": "full", "order": 3},
    ]
    job = _enqueue(database, scan.source)
    claimed = JobQueue(database).claim_next()
    assert claimed is not None
    worker.process_one_stage(claimed)
    ready = database.set_selection(job.id, selection)

    result = worker.process_job(ready)

    assert result.state is JobState.COMPLETED, result.status_message
    demux = [command for command in runner.commands if command[0] == "bdencode-eac3to"][-1]
    assert [item for item in demux if item.startswith("3:")] == ["3:03-audio.thd", "3:03-compatibility.ac3"]
    finals = [
        command[command.index("-map") + 1]
        for command in runner.commands
        if command[-3:] == ("-f", "md5", "-") and Path(command[command.index("-i") + 1]).name == "reference.mkv"
    ]
    # The reference's own AC-3 (ordinal 1) proves the compatibility track.
    assert finals == ["0:v:0", "0:a:0", "0:a:1", "0:a:2"]


UHD_LISTING = """\
M2TS, 2 video tracks, 1 audio track, 1 subtitle track, 2:11:22, 24p /1.001
1: Chapters, 12 chapters
2: h265/HEVC, 2160p24 /1.001 (16:9), 10 bits
3: h265/HEVC, 1920x1088 24p /1.001 (30:17), 10 bits
4: TrueHD/AC3 (Atmos), English, 7.1 channels, 48kHz, dialnorm: -28dB
   (embedded: AC3, 5.1 channels, 448kbps, 48kHz)
5: Subtitle (PGS), English
"""
UHD_NAME = "Housemaid.2025.2160p.UHD.BluRay.REMUX.DV.HDR.HEVC.TrueHD.7.1.Atmos-TAG"


def _uhd_scan(source: Path) -> DiscScan:
    scan = _remux_scan(source, disc_kind=DiscKind.UHD)
    playlist = scan.playlists[0]
    video, truehd, _pcm, subtitle = playlist.streams
    base = replace(
        video,
        codec="hevc",
        codec_profile="Main 10",
        video=replace(
            video.video,
            codec=VideoCodec.HEVC,
            width=3840,
            height=2160,
            bit_depth=10,
            color_primaries="bt2020",
            color_transfer="smpte2084",
            color_matrix="bt2020nc",
            hdr10=True,
            hdr10_static=HdrStaticMetadata(
                "G(13250,34500)B(7500,3000)R(34000,16000)WP(15635,16450)L(10000000,1)", 1000, 400
            ),
            dolby_vision=True,
            dolby_vision_profile=7,
            dolby_vision_el_stream_id="video:4117",
            dolby_vision_el_type="FEL",
            hdr10_base_layer=True,
        ),
    )
    enhancement = replace(
        video,
        id="video:4117",
        index=1,
        pid=4117,
        codec="hevc",
        video=replace(video.video, codec=VideoCodec.HEVC, bit_depth=10),
    )
    return replace(
        scan,
        playlists=(
            replace(
                playlist,
                streams=(
                    base,
                    enhancement,
                    replace(truehd, id="audio:4352:truehd", index=2, channels=8, object_audio=True),
                    replace(truehd, id="audio:4352:ac3", index=3, codec="ac3", channels=6, bit_depth=0),
                    replace(subtitle, index=4),
                ),
            ),
        ),
    )


def _uhd_selection() -> dict[str, Any]:
    return _remux_selection(
        output_name=UHD_NAME,
        tracks=[
            {"stream_id": "audio:4352:truehd", "action": "copy", "language": "eng", "order": 0},
            {"stream_id": "audio:4352:ac3", "action": "omit", "language": "eng", "order": 1},
            {"stream_id": "subtitle:4608", "action": "copy", "language": "eng", "subtitle_kind": "full", "order": 2},
        ],
    )


def _uhd_worker(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        worker_module,
        "capability_snapshot",
        lambda _names: {"host": {"hostname": "test"}, "tools": {}},
    )
    monkeypatch.setattr(
        worker_module, "remux_support", lambda: {"available": True, "dolby_vision": True}
    )
    source_root = tmp_path / "storage"
    source = source_root / "Movie"
    (source / "BDMV" / "PLAYLIST").mkdir(parents=True)
    settings = Settings(
        data_root=tmp_path / "encode",
        source_roots=(source_root,),
        comparison_frames_per_type=1,
        worker_poll_seconds=0,
    ).validate()
    settings.create_directories()
    scan = _uhd_scan(source)
    database = Database(tmp_path / "state.sqlite3")
    database.initialize()
    scanner = FakeScanner(scan)
    runner = RemuxRunner()
    runner.listing = UHD_LISTING
    worker = PipelineWorker(
        database,
        settings,
        scanner_factory=lambda _settings: scanner,
        runner_factory=lambda _paths: runner,
    )
    job = _enqueue(database, scan.source)
    claimed = JobQueue(database).claim_next()
    assert claimed is not None
    worker.process_one_stage(claimed)
    return database.set_selection(job.id, _uhd_selection()), settings, runner, worker


def test_an_uhd_dolby_vision_remux_joins_its_layers_into_one_track(tmp_path: Path, monkeypatch) -> None:
    ready, settings, runner, worker = _uhd_worker(tmp_path, monkeypatch)

    result = worker.process_job(ready)

    assert result.state is JobState.COMPLETED, result.status_message
    eac3to = [command for command in runner.commands if command[0] == "bdencode-eac3to"][-1]
    # eac3to does not touch the HEVC video (the guide: wrong PTS on HEVC).
    assert not any(item.startswith(("2:", "3:")) for item in eac3to)
    assert "4:04-audio.thd" in eac3to and "4:04-compatibility.ac3" in eac3to
    extracted = [
        command[command.index("-map") + 1]
        for command in runner.commands
        if command[0] == "ffmpeg" and "hevc_mp4toannexb" in command
    ]
    assert extracted == ["0:v:0", "0:v:1"]
    assert any(command[:2] == ("dovi_tool", "mux") and "--no-add-aud" in command for command in runner.commands)
    mux = runner.last_mux
    assert mux is not None
    video_name = next(mux[index + 1] for index, item in enumerate(mux) if item == "--track-name")
    assert video_name.startswith("0:MPEG-H HEVC Video / ")
    assert "2160p / 23.976 fps / 16:9 / Main 10 @ Level 5.1 / 4:2:0 / 10 bits / 1000nits / HDR10 / BT.2020 / Dolby Vision FEL" in video_name
    assert (settings.completed_root / UHD_NAME / f"{UHD_NAME}.mkv").is_file()
    qc = json.loads((settings.completed_root / UHD_NAME / "analysis" / "remux-qc.json").read_text(encoding="utf-8"))
    assert next(item for item in qc["checks"] if item["check"] == "dolby_vision")["status"] == "passed"
    layer = next(item for item in qc["checks"] if item["check"] == "dolby_vision_layer")
    assert layer["status"] == "passed"
    hashed = [command for command in runner.commands if "bdencode.dovi_layers" in command]
    assert {tuple(command[-2:]) for command in hashed} == {("1", "layer"), ("0", "joined")}
    assert "audio:04-compatibility.ac3" in {item["check"] for item in qc["checks"]}


def test_a_remux_that_lost_its_dolby_vision_stops(tmp_path: Path, monkeypatch) -> None:
    ready, _settings, runner, worker = _uhd_worker(tmp_path, monkeypatch)
    runner.dovi_report = {"streams": [{}]}

    result = worker.process_job(ready)

    assert result.state is JobState.NEEDS_REVIEW
    assert "Dolby Vision record: None" in (result.status_message or "")


def test_a_remux_with_a_changed_enhancement_layer_stops(tmp_path: Path, monkeypatch) -> None:
    ready, _settings, runner, worker = _uhd_worker(tmp_path, monkeypatch)
    runner.layer_reports["final"] = {"units": 4, "sha256": "b" * 64}

    result = worker.process_job(ready)

    assert result.state is JobState.NEEDS_REVIEW
    assert "the enhancement layer differs from the disc's" in (result.status_message or "")


def test_a_second_video_stream_must_be_the_enhancement_layer(tmp_path: Path) -> None:
    scan = _uhd_scan(tmp_path)
    playlist = scan.playlists[0]
    base = playlist.streams[0]
    unknown = replace(base, video=replace(base.video, dolby_vision_el_stream_id=None))
    broken = replace(scan, playlists=(replace(playlist, streams=(unknown, *playlist.streams[1:])),))

    with pytest.raises(ReviewRequired, match="not a recognized Dolby Vision enhancement layer"):
        parse_selection(_job(broken, _uhd_selection()), broken)
