"""The disc-remux MKV source: scanner, scan round trip, language, API."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from bdencode.api import create_app
from bdencode.config import Settings
from bdencode.db import Database
from bdencode.media.bluray import (
    ContentKind,
    DiscKind,
    DiscScan,
    MediaStream,
    PlaylistCandidate,
    StreamKind,
    ToolCapabilities,
    VideoCodec,
    VideoProperties,
)
from bdencode.media.language import (
    LanguageResolver,
    LanguageSource,
    LanguageStatus,
    settle_track_language,
)
from bdencode.media.mkv_source import (
    ENCODER_SIGNATURE_WARNING,
    MkvScanner,
    MkvSourceError,
    is_mkv_source,
)
from bdencode.worker import _scan_from_dict

_STATS = {
    "BPS": "2730577",
    "DURATION": "01:30:13.576000000",
    "_STATISTICS_WRITING_APP": "mkvmerge v95.0 ('Goodbye Stranger') 64-bit",
}


def _chapters(count: int, step: float) -> list[dict[str, Any]]:
    return [
        {
            "id": -2768167871652602230 + number,
            "time_base": "1/1000000000",
            "start_time": f"{number * step:.6f}",
            "end_time": f"{(number + 1) * step:.6f}",
            "tags": {"title": f"Chapter {number + 1:02d}"},
        }
        for number in range(count)
    ]


# Modelled on "I Want Your Sex 2026 Hybrid 2160p UHD Blu-ray Remux DoVi HDR10+
# HEVC TrueHD 7.1 Atmos.mkv": ffprobe gives no stream ``id`` for Matroska.
UHD_PROBE: dict[str, Any] = {
    "streams": [
        {
            "index": 0,
            "codec_name": "hevc",
            "profile": "Main 10",
            "codec_type": "video",
            "width": 3840,
            "height": 2160,
            "pix_fmt": "yuv420p10le",
            "color_range": "tv",
            "color_space": "bt2020nc",
            "color_transfer": "smpte2084",
            "color_primaries": "bt2020",
            "chroma_location": "topleft",
            "field_order": "progressive",
            "r_frame_rate": "24000/1001",
            "avg_frame_rate": "24000/1001",
            "disposition": {"default": 1, "attached_pic": 0},
            "tags": {"language": "zxx", "SOURCE_ID": "001011", **_STATS},
            "side_data_list": [
                {
                    "side_data_type": "DOVI configuration record",
                    "dv_version_major": 1,
                    "dv_version_minor": 0,
                    "dv_profile": 7,
                    "dv_level": 6,
                    "rpu_present_flag": 1,
                    "el_present_flag": 1,
                    "bl_present_flag": 1,
                    "dv_bl_signal_compatibility_id": 6,
                }
            ],
        },
        {
            "index": 1,
            "codec_name": "truehd",
            "codec_type": "audio",
            "sample_rate": "48000",
            "channels": 8,
            "channel_layout": "7.1",
            "bits_per_raw_sample": "24",
            "disposition": {"default": 1},
            "tags": {"language": "eng", **_STATS},
        },
        {
            "index": 2,
            "codec_name": "eac3",
            "codec_type": "audio",
            "sample_rate": "48000",
            "channels": 6,
            "channel_layout": "5.1(side)",
            "disposition": {"default": 0},
            "tags": {"language": "eng", **_STATS},
        },
        {
            "index": 3,
            "codec_name": "subrip",
            "codec_type": "subtitle",
            "disposition": {"default": 0},
            "tags": {"language": "eng", **_STATS},
        },
        {
            "index": 4,
            "codec_name": "hdmv_pgs_subtitle",
            "codec_type": "subtitle",
            "disposition": {"default": 0, "hearing_impaired": 1},
            "tags": {"language": "eng", "title": "SDH", **_STATS},
        },
        {
            "index": 5,
            "codec_name": "subrip",
            "codec_type": "subtitle",
            "disposition": {"default": 0, "hearing_impaired": 1},
            "tags": {"language": "eng", "title": "SDH", **_STATS},
        },
        {
            "index": 6,
            "codec_name": "subrip",
            "codec_type": "subtitle",
            "disposition": {"default": 0},
            "tags": {"language": "fre", **_STATS},
        },
        {
            "index": 7,
            "codec_name": "subrip",
            "codec_type": "subtitle",
            "disposition": {"default": 0},
            "tags": {"language": "fre", **_STATS},
        },
        {
            "index": 8,
            "codec_name": "mjpeg",
            "profile": "Baseline",
            "codec_type": "video",
            "width": 640,
            "height": 960,
            "disposition": {"default": 0, "attached_pic": 1},
            "tags": {"filename": "cover.jpg", "mimetype": "image/jpeg"},
        },
    ],
    "chapters": _chapters(12, 412.412),
    "format": {
        "format_name": "matroska,webm",
        "duration": "5413.600000",
        "nb_streams": 9,
        "tags": {"title": "I Want Your Sex (2026)", "IMDB": "tt32332915"},
    },
}

UHD_FRAMES: dict[str, Any] = {
    "frames": [
        {
            "side_data_list": [
                {
                    "side_data_type": "Mastering display metadata",
                    "red_x": "35400/50000",
                    "red_y": "14600/50000",
                    "green_x": "8500/50000",
                    "green_y": "39850/50000",
                    "blue_x": "6550/50000",
                    "blue_y": "2300/50000",
                    "white_point_x": "15635/50000",
                    "white_point_y": "16450/50000",
                    "min_luminance": "1/10000",
                    "max_luminance": "10000000/10000",
                },
                {
                    "side_data_type": "Content light level metadata",
                    "max_content": 1021,
                    "max_average": 413,
                },
                {
                    "side_data_type": "HDR Dynamic Metadata SMPTE2094-40 (HDR10+)",
                    "num_windows": 1,
                },
                {"side_data_type": "Dolby Vision RPU Data"},
            ]
        }
    ]
    * 3
}

# Modelled on "The Florist 2026 1080p Blu-ray Remux AVC DTS-HD MA 5.1-HDT.mkv".
BD_PROBE: dict[str, Any] = {
    "streams": [
        {
            "index": 0,
            "codec_name": "h264",
            "profile": "High",
            "codec_type": "video",
            "width": 1920,
            "height": 1080,
            "pix_fmt": "yuv420p",
            "bits_per_raw_sample": "8",
            "color_space": "bt709",
            "color_transfer": "bt709",
            "color_primaries": "bt709",
            "field_order": "progressive",
            "avg_frame_rate": "24000/1001",
            "disposition": {"default": 1},
            "tags": {"SOURCE_ID": "001011", **_STATS},
        },
        {
            "index": 1,
            "codec_name": "dts",
            "profile": "DTS-HD MA",
            "codec_type": "audio",
            "sample_rate": "48000",
            "channels": 6,
            "channel_layout": "5.1(side)",
            "disposition": {"default": 1},
            "tags": {"language": "eng", "SOURCE_ID": "001101"},
        },
        *(
            {
                "index": index,
                "codec_name": "hdmv_pgs_subtitle",
                "codec_type": "subtitle",
                "disposition": {"default": 1},
                "tags": {"language": "ger", "SOURCE_ID": f"00120{index - 2}"},
            }
            for index in (2, 3, 4)
        ),
    ],
    "chapters": _chapters(12, 334.208867),
    "format": {"format_name": "matroska,webm", "duration": "5893.355000"},
}


class ProbeRunner:
    """Answers the stream probe and the frame side-data probe."""

    def __init__(
        self,
        probe: dict[str, Any],
        frames: dict[str, Any] | None = None,
        elementary: str = "\x00\x00\x00\x01\x67disc picture data",
    ) -> None:
        self.probe = probe
        self.frames = frames or {"frames": []}
        self.elementary = elementary
        self.commands: list[tuple[str, ...]] = []

    def capture(self, argv, *, timeout: float = 30, check: bool = True):
        command = tuple(os.fspath(item) for item in argv)
        self.commands.append(command)
        if command[0] == "ffmpeg":
            # The first access units copied out for the encoder signature.
            return SimpleNamespace(returncode=0, stdout=self.elementary, stderr="")
        document = self.frames if "-show_frames" in command else self.probe
        return SimpleNamespace(returncode=0, stdout=json.dumps(document), stderr="")


def _scan(tmp_path: Path, probe: dict[str, Any], frames: dict[str, Any] | None = None,
          name: str = "Movie 2026 2160p UHD Blu-ray Remux.mkv",
          elementary: str | None = None) -> tuple[DiscScan, ProbeRunner]:
    root = tmp_path / "storage"
    root.mkdir(exist_ok=True)
    source = root / name
    source.write_bytes(b"\x1a\x45\xdf\xa3" + b"remux" * 64)
    runner = ProbeRunner(probe, frames) if elementary is None else ProbeRunner(probe, frames, elementary)
    scanner = MkvScanner(
        runner=runner,
        capabilities=ToolCapabilities(ffprobe="ffprobe"),
        source_root=root,
        ffmpeg="ffmpeg",
    )
    return scanner.scan(source, content_kind=ContentKind.FILM), runner


def test_uhd_remux_scan_keeps_the_title_and_drops_the_cover(tmp_path: Path) -> None:
    scan, runner = _scan(tmp_path, UHD_PROBE, UHD_FRAMES)

    assert scan.source_kind == "mkv" and scan.is_mkv
    assert scan.disc_kind is DiscKind.UHD
    (playlist,) = scan.playlists
    assert playlist.playlist_id == "00001"
    assert playlist.recommended is True
    assert playlist.segments == () and playlist.angle_count == 1
    assert playlist.duration_seconds == pytest.approx(5413.6)
    assert len(playlist.chapters) == 12 and playlist.chapters[1] == pytest.approx(412.412)
    # No ``id`` in Matroska: ``kind:index`` with the file's stream index.
    assert [stream.id for stream in playlist.streams] == [
        "video:0", "audio:1", "audio:2",
        "subtitle:3", "subtitle:4", "subtitle:5", "subtitle:6", "subtitle:7",
    ]
    assert all(stream.pid is None for stream in playlist.streams)
    assert [stream.index for stream in playlist.streams] == list(range(8))
    # The attached cover picture is not a video stream of the title.
    assert len(playlist.video_streams) == 1
    assert any("cover image (stream 8, mjpeg)" in item for item in scan.warnings)
    assert not any("encoder signature" in item for item in scan.warnings)

    video = playlist.video_streams[0].video
    assert video is not None
    assert video.codec is VideoCodec.HEVC and video.bit_depth == 10
    assert video.hdr10 and video.hdr10_base_layer
    assert video.dolby_vision and video.dolby_vision_profile == 7
    assert video.dolby_vision_el_stream_id is None
    # HDR10+ comes from the ST 2094-40 frame records, not from the file name.
    assert video.hdr10_plus is True
    assert video.hdr10_static.complete
    assert video.hdr10_static.max_cll == 1021 and video.hdr10_static.max_fall == 413
    assert video.hdr10_static.mastering_display == (
        "G(8500,39850)B(6550,2300)R(35400,14600)WP(15635,16450)L(10000000,1)"
    )
    # zxx names no language.
    assert playlist.video_streams[0].language is not None
    assert playlist.video_streams[0].language.status is LanguageStatus.UNKNOWN

    subtitles = {stream.id: stream for stream in playlist.subtitle_streams}
    assert [sid for sid, item in subtitles.items() if item.text_subtitle] == [
        "subtitle:3", "subtitle:5", "subtitle:6", "subtitle:7",
    ]
    pgs = subtitles["subtitle:4"]
    assert pgs.codec == "hdmv_pgs_subtitle" and not pgs.text_subtitle
    assert pgs.title == "SDH" and "sdh" in {role.value for role in pgs.roles}
    assert subtitles["subtitle:6"].language.iso639_2t == "fra"
    english = playlist.audio_streams[0].language
    assert english is not None and english.iso639_2t == "eng"
    assert english.status is LanguageStatus.DECLARED and not english.needs_review
    assert [item.source for item in english.evidence] == [LanguageSource.MATROSKA]

    # A stream probe, a frame probe and the encoder-signature copy, all of
    # the file itself.
    assert len(runner.commands) == 3
    for command in runner.commands:
        read = command[command.index("-i") + 1] if command[0] == "ffmpeg" else command[-1]
        assert read == os.fspath(scan.source)
        assert not any("bluray:" in item for item in command)
        assert "-playlist" not in command

    document = scan.to_dict()
    assert document["source_kind"] == "mkv"
    streams = document["playlists"][0]["streams"]
    assert streams[3]["text_subtitle"] is True
    assert "text_subtitle" not in streams[4]


def test_bd_remux_scan(tmp_path: Path) -> None:
    scan, runner = _scan(
        tmp_path, BD_PROBE, name="The Florist 2026 1080p Blu-ray Remux AVC DTS-HD MA 5.1-HDT.mkv"
    )

    assert scan.disc_kind is DiscKind.BD
    (playlist,) = scan.playlists
    assert len(playlist.chapters) == 12
    assert [stream.id for stream in playlist.streams] == [
        "video:0", "audio:1", "subtitle:2", "subtitle:3", "subtitle:4",
    ]
    assert [stream.language.iso639_2t for stream in playlist.subtitle_streams] == ["deu"] * 3
    assert not any(stream.text_subtitle for stream in playlist.subtitle_streams)
    video = playlist.video_streams[0].video
    assert video is not None and video.codec is VideoCodec.AVC
    assert not (video.hdr10 or video.hdr10_plus or video.dolby_vision)
    # SDR: no frame probe (only the encoder-signature copy), and a remux
    # without a cover has no warning.
    assert [command[0] for command in runner.commands] == ["ffprobe", "ffmpeg"]
    assert scan.warnings == ()


def test_hdr10_plus_in_the_file_name_is_no_evidence(tmp_path: Path) -> None:
    frames = copy.deepcopy(UHD_FRAMES)
    for frame in frames["frames"]:
        frame["side_data_list"] = [
            item for item in frame["side_data_list"] if "2094" not in item["side_data_type"]
        ]
    scan, _runner = _scan(tmp_path, UHD_PROBE, frames, name="Movie HDR10+ DoVi Remux.mkv")
    video = scan.playlists[0].video_streams[0].video
    assert video is not None and video.hdr10_plus is False and video.dolby_vision


def test_a_group_remux_without_source_id_gives_no_warning(tmp_path: Path) -> None:
    # Casanova S01 (EPSiLON): mkvmerge from the disc's m2ts, no SOURCE_ID
    # tag (only MakeMKV writes one), no encoder signature: a real remux.
    probe = copy.deepcopy(BD_PROBE)
    del probe["streams"][0]["tags"]["SOURCE_ID"]
    scan, runner = _scan(tmp_path, probe)

    assert not any("SOURCE_ID" in item or "encoder signature" in item for item in scan.warnings)
    copy_command = next(command for command in runner.commands if command[0] == "ffmpeg")
    assert copy_command[copy_command.index("-c") + 1] == "copy"
    assert copy_command[copy_command.index("-frames:v") + 1] == "5"
    assert copy_command[copy_command.index("-f") + 1] == "h264"


@pytest.mark.parametrize(
    ("signature", "encoder"),
    [
        # BDEncode's own outputs, as found on nvme.
        ("x264 - core 164 r3204 373697b - options: bluray_compat=0 crf=18.5 nal_hrd=none", "x264"),
        ("x265 (build 199) - 3.5+1-f0c1022b6 - options: high-tier=1 uhd-bd=0 rc=crf crf=18.0", "x265"),
    ],
)
def test_an_encoder_signature_is_a_warning(tmp_path: Path, signature: str, encoder: str) -> None:
    scan, _runner = _scan(tmp_path, BD_PROBE, elementary="\x00\x00\x01\x06\x05" + signature)
    assert ENCODER_SIGNATURE_WARNING.format(encoder=encoder) in scan.warnings


@pytest.mark.parametrize(
    "signature",
    [
        # The Florist 2026 disc: the label mastered it with x264 itself.
        "x264 - core 164 r3204 373697b - options: bluray_compat=1 bitrate=30000 vbv_maxrate=35000 nal_hrd=vbr",
        "x265 (build 199) - 3.5 - options: uhd-bd=1 hrd bitrate=60000",
    ],
)
def test_a_disc_mastered_with_x264_or_x265_is_not_an_encode(tmp_path: Path, signature: str) -> None:
    scan, _runner = _scan(tmp_path, BD_PROBE, elementary="\x00\x00\x01\x06\x05" + signature)
    assert not any("encoder signature" in item for item in scan.warnings)


def _without_video(probe: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(probe)
    result["streams"] = [
        item
        for item in result["streams"]
        if item["codec_type"] != "video" or item["disposition"].get("attached_pic")
    ]
    return result


def _with_streams(probe: dict[str, Any], streams: list[dict[str, Any]]) -> dict[str, Any]:
    result = copy.deepcopy(probe)
    result["streams"] = streams
    return result


@pytest.mark.parametrize(
    ("probe", "message"),
    [
        (_without_video(UHD_PROBE), "no video stream"),
        (
            _with_streams(UHD_PROBE, [UHD_PROBE["streams"][8], *UHD_PROBE["streams"][:8]]),
            "cover image precedes",
        ),
        (
            _with_streams(BD_PROBE, [*BD_PROBE["streams"], {**BD_PROBE["streams"][0], "index": 5}]),
            "more than one video stream",
        ),
        (
            _with_streams(BD_PROBE, [{**BD_PROBE["streams"][0], "codec_name": "av1"}]),
            "not a Blu-ray codec",
        ),
        (
            _with_streams(
                UHD_PROBE,
                [
                    {
                        **UHD_PROBE["streams"][0],
                        "side_data_list": [
                            {
                                "side_data_type": "DOVI configuration record",
                                "dv_profile": 5,
                                "dv_bl_signal_compatibility_id": 0,
                            }
                        ],
                    }
                ],
            ),
            "profile 5",
        ),
        ({**BD_PROBE, "format": {"format_name": "mov,mp4", "duration": "10"}}, "not a Matroska"),
        ({**BD_PROBE, "format": {"format_name": "matroska,webm"}}, "no duration"),
    ],
)
def test_only_disc_remuxes_are_accepted(tmp_path: Path, probe, message: str) -> None:
    with pytest.raises(MkvSourceError, match=message):
        _scan(tmp_path, probe, UHD_FRAMES)


def test_the_scanner_refuses_other_files_and_escapes(tmp_path: Path) -> None:
    root = tmp_path / "storage"
    root.mkdir()
    scanner = MkvScanner(
        runner=ProbeRunner(BD_PROBE),
        capabilities=ToolCapabilities(ffprobe="ffprobe"),
        source_root=root,
    )
    other = root / "movie.m2ts"
    other.write_bytes(b"x")
    with pytest.raises(MkvSourceError, match=r"\.mkv file"):
        scanner.scan(other)
    outside = tmp_path / "outside.mkv"
    outside.write_bytes(b"x")
    with pytest.raises(MkvSourceError, match="within"):
        scanner.scan(outside)
    link = root / "link.mkv"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks are not available")
    with pytest.raises(MkvSourceError, match="within"):
        scanner.scan(link)


def test_is_mkv_source_is_case_insensitive() -> None:
    assert is_mkv_source("/storage/A.MKV") and is_mkv_source("a.mkv")
    assert not is_mkv_source("/storage/BDMV") and not is_mkv_source("a.mks")


# -- scan round trip ----------------------------------------------------------


def _disc_scan() -> DiscScan:
    return DiscScan(
        source=Path("/storage/Movie"),
        disc_kind=DiscKind.BD,
        content_kind=ContentKind.FILM,
        playlists=(
            PlaylistCandidate(
                playlist_id="00800",
                duration_seconds=7200.0,
                chapters=(0.0, 600.0),
                streams=(
                    MediaStream(
                        id="video:4113",
                        index=0,
                        pid=4113,
                        kind=StreamKind.VIDEO,
                        codec="h264",
                        video=VideoProperties(codec=VideoCodec.AVC, width=1920, height=1080),
                    ),
                    MediaStream(
                        id="subtitle:4608",
                        index=1,
                        pid=4608,
                        kind=StreamKind.SUBTITLE,
                        codec="hdmv_pgs_subtitle",
                    ),
                ),
                recommended=True,
            ),
        ),
        capabilities=ToolCapabilities(ffprobe="ffprobe", ffprobe_bluray=True),
        fingerprint="a" * 64,
    )


def test_a_disc_scan_document_is_unchanged() -> None:
    document = _disc_scan().to_dict()
    # Exactly the keys a 3.9 disc scan had: nothing new is serialised.
    assert list(document) == [
        "source", "disc_kind", "content_kind", "playlists", "capabilities",
        "fingerprint", "has_multiple_editions", "has_seamless_branching",
        "has_three_d", "warnings",
    ]
    stream = document["playlists"][0]["streams"][1]
    assert list(stream) == [
        "id", "index", "pid", "kind", "codec", "codec_profile", "language",
        "title", "channels", "channel_layout", "sample_rate", "bit_depth",
        "default", "forced", "roles", "object_audio", "video",
    ]
    restored = _scan_from_dict(json.loads(json.dumps(document)))
    assert restored.source_kind == "disc" and not restored.is_mkv
    assert json.dumps(restored.to_dict()) == json.dumps(document)


def test_an_mkv_scan_round_trips(tmp_path: Path) -> None:
    scan, _runner = _scan(tmp_path, UHD_PROBE, UHD_FRAMES)
    document = json.loads(json.dumps(scan.to_dict()))
    restored = _scan_from_dict(document)
    assert restored.is_mkv
    assert restored.playlists[0].subtitle_streams[0].text_subtitle is True
    assert restored.playlists[0].audio_streams[0].language.evidence[0].source is (
        LanguageSource.MATROSKA
    )
    assert json.loads(json.dumps(restored.to_dict())) == document


def test_unknown_source_kind_is_refused() -> None:
    with pytest.raises(ValueError, match="source kind"):
        DiscScan(
            source=Path("/x"),
            disc_kind=DiscKind.BD,
            content_kind=ContentKind.FILM,
            playlists=(),
            capabilities=ToolCapabilities(),
            fingerprint="a" * 64,
            source_kind="iso",
        )


# -- language -----------------------------------------------------------------


def test_matroska_language_counts_like_the_weakest_disc_label() -> None:
    resolver = LanguageResolver()
    matroska = resolver.resolve(matroska="ger")
    pmt = resolver.resolve(pmt="ger")
    assert matroska.iso639_2t == pmt.iso639_2t == "deu"
    assert matroska.confidence == pmt.confidence
    assert matroska.status is LanguageStatus.DECLARED and not matroska.needs_review
    assert resolver.resolve(matroska="zxx").iso639_2t == "zxx"
    assert resolver.resolve(matroska="und").status is LanguageStatus.UNKNOWN
    # A disc decision is untouched by the new source.
    assert [item.source for item in resolver.resolve(mpls="eng", pmt="eng").evidence] == [
        LanguageSource.MPLS, LanguageSource.PMT,
    ]


def test_settlement_uses_the_matroska_label() -> None:
    settled = settle_track_language({"mpls": None, "clpi": None, "pmt": None, "matroska": "eng"})
    assert settled.language == "eng" and settled.warning is None
    kept = settle_track_language({"matroska": "eng"}, "fra", 0.95)
    assert kept.language == "eng" and kept.warning


# -- API ----------------------------------------------------------------------


def _client(tmp_path: Path) -> tuple[TestClient, Settings, Database]:
    source = tmp_path / "source"
    source.mkdir()
    settings = Settings(data_root=tmp_path / "data", source_roots=(source,)).validate()
    settings.create_directories()
    database = Database(tmp_path / "state.sqlite3")
    return TestClient(create_app(database, settings=settings), raise_server_exceptions=False), settings, database


def test_sources_lists_mkv_files_beside_folders(tmp_path: Path) -> None:
    client, settings, _ = _client(tmp_path)
    root = settings.source_roots[0]
    (root / "Disc" / "BDMV" / "PLAYLIST").mkdir(parents=True)
    (root / "Extras").mkdir()
    (root / "b Movie.MKV").write_bytes(b"x")
    (root / "a Movie.mkv").write_bytes(b"x")
    (root / "notes.txt").write_text("x", encoding="utf-8")
    (root / "subs.mks").write_bytes(b"x")
    outside = tmp_path / "outside.mkv"
    outside.write_bytes(b"x")
    try:
        (root / "escape.mkv").symlink_to(outside)
    except OSError:
        pass

    response = client.get("/api/v1/sources")

    assert response.status_code == 200
    entries = response.json()["entries"]
    assert [(item["name"], item["kind"], item["is_bluray"]) for item in entries] == [
        ("Disc", "bluray", True),
        ("Extras", "folder", False),
        ("a Movie.mkv", "mkv", False),
        ("b Movie.MKV", "mkv", False),
    ]


def test_a_job_can_be_created_for_an_mkv_inside_the_roots(tmp_path: Path) -> None:
    client, settings, _ = _client(tmp_path)
    root = settings.source_roots[0]
    remux = root / "The Florist 2026 1080p Blu-ray Remux AVC DTS-HD MA 5.1-HDT.mkv"
    remux.write_bytes(b"x")

    created = client.post("/api/v1/jobs", json={"source_path": str(remux)})
    assert created.status_code == 201, created.text
    assert created.json()["source_path"] == str(remux.resolve())
    assert created.json()["name"] == "The Florist 2026 1080p Blu-ray Remux AVC DTS-HD MA 5.1-HDT"

    outside = tmp_path / "outside.mkv"
    outside.write_bytes(b"x")
    refused = client.post("/api/v1/jobs", json={"source_path": str(outside)})
    assert refused.status_code == 422
    assert "outside configured roots" in refused.json()["detail"]

    other = root / "movie.m2ts"
    other.write_bytes(b"x")
    refused = client.post("/api/v1/jobs", json={"source_path": str(other)})
    assert refused.status_code == 422
    assert ".mkv" in refused.json()["detail"]
    assert client.get("/api/v1/jobs").json()["meta"]["count"] == 1
