"""Scan a disc-origin Matroska remux (MakeMKV-style ``.mkv``) as a job source.

A remux carries the disc's video, audio and subtitle streams copied into
Matroska.  The scan describes it as one title (playlist ``00001``, no segments,
one angle) so everything after preparation, which works from the reference
file, treats it like a Blu-ray title.  Only remuxes are accepted: the file must
hold exactly one Blu-ray video stream (AVC, HEVC, VC-1 or MPEG-2) and may not be
a streaming-only Dolby Vision profile 5 file.  Cover images (attached pictures)
and attachment/data streams are not part of the title and are left out; text
subtitles (SRT, ASS) are kept and marked.

Streams have no transport PID in Matroska, so their identifiers are
``kind:index`` with the ffprobe stream index of the file; ``MediaStream.index``
is that index too, so ``-map 0:<index>`` addresses the stream in the file and
in its byte-identical reference copy.

The scanner never writes to the source; every subprocess gets an argv list.
"""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
from typing import Any, Mapping, Sequence

from .bluray import (
    DEFAULT_SOURCE_ROOT,
    SOURCE_KIND_MKV,
    BluRayScanner,
    CaptureRunner,
    ContentKind,
    DiscScan,
    HdrStaticMetadata,
    MediaStream,
    PlaylistCandidate,
    StreamKind,
    SubprocessCaptureRunner,
    ToolCapabilities,
    _float,
    _hdr_static_from_frame_payload,
    _int,
    _json_object,
)

MKV_SUFFIXES = frozenset({".mkv"})
MKV_PLAYLIST_ID = "00001"
# FFmpeg codec names of subtitles stored as text rather than as bitmaps.
TEXT_SUBTITLE_CODECS = frozenset(
    {"subrip", "srt", "ass", "ssa", "webvtt", "mov_text", "text"}
)
# The video codecs a Blu-ray (and UHD Blu-ray) can carry.
BLURAY_VIDEO_CODECS = frozenset({"h264", "hevc", "vc1", "mpeg2video"})
# Language tags that name no language (``zxx``: no linguistic content).
UNKNOWN_LANGUAGE_TAGS = frozenset({"und", "zxx", ""})
PROBE_TIMEOUT_SECONDS = 180
FRAME_PROBE_TIMEOUT_SECONDS = 90
_EDGE_BYTES = 1024 * 1024

NO_SOURCE_ID_WARNING = (
    "The video track carries no SOURCE_ID tag (written by MakeMKV/mkvmerge from "
    "the disc); make sure the file is an untouched disc remux, not an encode."
)


class MkvSourceError(ValueError):
    """The file is not an acceptable disc-origin Matroska remux."""


def is_mkv_source(path: str | os.PathLike[str]) -> bool:
    """A source path that names a Matroska file (by its suffix)."""

    return Path(path).suffix.casefold() in MKV_SUFFIXES


def is_text_subtitle_codec(codec: str | None) -> bool:
    return str(codec or "").casefold() in TEXT_SUBTITLE_CODECS


def validate_mkv_source_path(
    source: str | os.PathLike[str], source_root: Path = DEFAULT_SOURCE_ROOT
) -> Path:
    """Resolve a remux path and reject traversal/symlink escapes from storage."""

    if "\x00" in os.fspath(source):
        raise MkvSourceError("source path contains a NUL byte")
    root = source_root.expanduser().resolve(strict=True)
    resolved = Path(source).expanduser().resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise MkvSourceError(f"source must be within {root}") from exc
    if not is_mkv_source(resolved):
        raise MkvSourceError("an MKV source must be a .mkv file")
    if not resolved.is_file():
        raise MkvSourceError("the MKV source is not a regular file")
    return resolved


def mkv_fingerprint(path: Path) -> str:
    """Identify the file: name, size, modification time and its first/last MiB."""

    details = path.stat()
    edges = hashlib.sha256()
    with path.open("rb") as handle:
        edges.update(handle.read(_EDGE_BYTES))
        if details.st_size > _EDGE_BYTES:
            handle.seek(max(0, details.st_size - _EDGE_BYTES))
            edges.update(handle.read(_EDGE_BYTES))
    document = {
        "kind": SOURCE_KIND_MKV,
        "name": path.name,
        "size_bytes": details.st_size,
        "mtime_ns": details.st_mtime_ns,
        "edge_sha256": edges.hexdigest(),
    }
    return hashlib.sha256(
        json.dumps(document, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _codec_type(item: Mapping[str, Any]) -> str:
    return str(item.get("codec_type", item.get("type", ""))).lower()


def _disposition(item: Mapping[str, Any]) -> Mapping[str, Any]:
    value = item.get("disposition")
    return value if isinstance(value, Mapping) else {}


def _tags(item: Mapping[str, Any]) -> Mapping[str, Any]:
    value = item.get("tags")
    return value if isinstance(value, Mapping) else {}


def _is_cover(item: Mapping[str, Any]) -> bool:
    return bool(_int(_disposition(item).get("attached_pic"), 0))


def _dovi_record(item: Mapping[str, Any]) -> Mapping[str, Any] | None:
    side_data = item.get("side_data_list")
    for side in side_data if isinstance(side_data, list) else ():
        if isinstance(side, Mapping) and "dovi" in str(
            side.get("side_data_type", "")
        ).lower():
            return side
    return None


class MkvScanner:
    """Describe one remux file as a :class:`DiscScan` with ``source_kind="mkv"``.

    The interface matches :class:`BluRayScanner` (``scan(source,
    content_kind=...)``), so the worker's scanner hook serves both.
    """

    def __init__(
        self,
        *,
        runner: CaptureRunner | None = None,
        capabilities: ToolCapabilities | None = None,
        source_root: Path = DEFAULT_SOURCE_ROOT,
    ) -> None:
        self.runner = runner or SubprocessCaptureRunner()
        self.capabilities = capabilities or ToolCapabilities(
            ffprobe=shutil.which("ffprobe"),
            mediainfo=shutil.which("mediainfo"),
            mkvmerge=shutil.which("mkvmerge"),
        )
        self.source_root = source_root
        # Stream parsing (codec, language evidence, roles, colour, Dolby
        # Vision record) is shared with the disc scanner.
        self._streams = BluRayScanner(
            runner=self.runner,
            capabilities=self.capabilities,
            source_root=source_root,
        )

    def scan(
        self,
        source: str | os.PathLike[str],
        *,
        content_kind: ContentKind | str = ContentKind.FILM,
    ) -> DiscScan:
        path = validate_mkv_source_path(source, self.source_root)
        content = ContentKind(content_kind)
        probe = self._probe(path)
        raw_streams = [
            item for item in probe.get("streams", []) if isinstance(item, Mapping)
        ]
        kept, dropped = self._remux_streams(raw_streams)
        warnings: list[str] = []
        video_item = next(item for item in kept if _codec_type(item) == "video")
        hdr_static, hdr10_plus = self._frame_metadata(path, video_item)
        streams = tuple(
            self._stream(item, hdr_static=hdr_static, hdr10_plus=hdr10_plus)
            for item in kept
        )
        duration = _float(probe.get("format", {}).get("duration"), 0.0) or 0.0
        if duration <= 0:
            raise MkvSourceError("the MKV file reports no duration")
        chapters = tuple(
            _float(item.get("start_time"), 0.0) or 0.0
            for item in probe.get("chapters", []) or []
            if isinstance(item, Mapping)
        )
        if not _tags(video_item).get("SOURCE_ID"):
            warnings.append(NO_SOURCE_ID_WARNING)
        if dropped:
            warnings.append(
                "Not part of the title and left out: "
                + ", ".join(dropped)
                + "."
            )
        playlist = PlaylistCandidate(
            playlist_id=MKV_PLAYLIST_ID,
            duration_seconds=duration,
            chapters=chapters,
            streams=streams,
            recommended=True,
        )
        return DiscScan(
            source=path,
            disc_kind=BluRayScanner._disc_kind([playlist]),
            content_kind=content,
            playlists=(playlist,),
            capabilities=self.capabilities,
            fingerprint=mkv_fingerprint(path),
            warnings=tuple(warnings),
            source_kind=SOURCE_KIND_MKV,
        )

    def _probe(self, path: Path) -> Mapping[str, Any]:
        ffprobe = self.capabilities.ffprobe
        if not ffprobe:
            raise MkvSourceError("ffprobe is required to scan an MKV source")
        completed = self.runner.capture(
            [
                ffprobe,
                "-v",
                "error",
                "-show_streams",
                "-show_format",
                "-show_chapters",
                "-of",
                "json",
                os.fspath(path),
            ],
            timeout=PROBE_TIMEOUT_SECONDS,
            check=False,
        )
        if getattr(completed, "returncode", 1) != 0:
            raise MkvSourceError("ffprobe could not read the MKV file")
        payload = _json_object(getattr(completed, "stdout", ""))
        format_name = str(payload.get("format", {}).get("format_name", ""))
        if "matroska" not in format_name.lower():
            raise MkvSourceError("the file is not a Matroska container")
        return payload

    @staticmethod
    def _remux_streams(
        raw_streams: Sequence[Mapping[str, Any]],
    ) -> tuple[list[Mapping[str, Any]], list[str]]:
        """The title's streams in file order, and what was left out of it.

        Fails closed on anything that is not a single-video disc remux.
        """

        kept: list[Mapping[str, Any]] = []
        dropped: list[str] = []
        for item in raw_streams:
            kind = _codec_type(item)
            index = _int(item.get("index"), None)
            if kind == "video" and _is_cover(item):
                dropped.append(
                    f"cover image (stream {index}, "
                    f"{str(item.get('codec_name', 'unknown')).lower()})"
                )
                continue
            if kind in {"audio", "subtitle", "video"}:
                if index is None:
                    raise MkvSourceError("ffprobe reported a stream without an index")
                kept.append(item)
                continue
            dropped.append(f"{kind or 'unknown'} stream {index}")
        videos = [item for item in kept if _codec_type(item) == "video"]
        if not videos:
            raise MkvSourceError(
                "the MKV file has no video stream; only disc remuxes are accepted"
            )
        if len(videos) > 1:
            raise MkvSourceError(
                "the MKV file has more than one video stream; only single-video "
                "disc remuxes are accepted"
            )
        video = videos[0]
        first_video = next(item for item in raw_streams if _codec_type(item) == "video")
        if first_video is not video:
            # Every later stage reads the picture as the first video stream of
            # the reference copy (``0:v:0``); a cover in front would be read.
            raise MkvSourceError(
                "a cover image precedes the video stream in the MKV file; "
                "remux it with the video first"
            )
        codec = str(video.get("codec_name", "")).lower()
        if codec not in BLURAY_VIDEO_CODECS:
            raise MkvSourceError(
                f"the video codec {codec or 'unknown'} is not a Blu-ray codec; "
                "only disc remuxes (AVC, HEVC, VC-1, MPEG-2) are accepted"
            )
        record = _dovi_record(video)
        if record is not None and (
            _int(record.get("dv_profile"), None) == 5
            or _int(record.get("dv_bl_signal_compatibility_id"), None) == 0
        ):
            raise MkvSourceError(
                "Dolby Vision profile 5 (no HDR10 base layer) is a streaming "
                "format, not a disc remux"
            )
        return kept, dropped

    def _frame_metadata(
        self, path: Path, video: Mapping[str, Any]
    ) -> tuple[HdrStaticMetadata, bool]:
        """HDR10 static metadata and HDR10+ presence from the first decoded frames.

        The stream header names the PQ transfer but rarely the mastering
        display; both come as frame side data, as on a disc clip.  An HDR10+
        (SMPTE ST 2094-40) frame record is the only evidence of HDR10+; the
        file name is not.  The encode-time extraction verifies it again.
        """

        if str(video.get("color_transfer", "")).lower() != "smpte2084":
            return HdrStaticMetadata(), False
        ffprobe = self.capabilities.ffprobe
        assert ffprobe
        completed = self.runner.capture(
            [
                ffprobe,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-read_intervals",
                "%+3",
                "-show_frames",
                "-show_entries",
                "frame=side_data_list",
                "-of",
                "json",
                os.fspath(path),
            ],
            timeout=FRAME_PROBE_TIMEOUT_SECONDS,
            check=False,
        )
        if getattr(completed, "returncode", 1) != 0:
            return HdrStaticMetadata(), False
        payload = _json_object(getattr(completed, "stdout", ""))
        hdr10_plus = any(
            isinstance(side, Mapping)
            and "2094-40" in str(side.get("side_data_type", ""))
            for frame in payload.get("frames", []) or []
            if isinstance(frame, Mapping)
            for side in frame.get("side_data_list", []) or []
        )
        return _hdr_static_from_frame_payload(payload), hdr10_plus

    def _stream(
        self,
        item: Mapping[str, Any],
        *,
        hdr_static: HdrStaticMetadata,
        hdr10_plus: bool,
    ) -> MediaStream:
        index = _int(item.get("index"), 0) or 0
        kind = _codec_type(item)
        probe = dict(item)
        # Matroska has no PIDs: the identifier is always ``kind:index``.
        probe.pop("id", None)
        tags = dict(_tags(item))
        language = str(tags.get("language", "")).strip().lower()
        if language in UNKNOWN_LANGUAGE_TAGS:
            tags.pop("language", None)
        probe["tags"] = tags
        disposition = _disposition(item)
        native: dict[str, Any] = {}
        roles: list[str] = []
        if _int(disposition.get("hearing_impaired"), 0):
            roles.append("sdh")
        if _int(disposition.get("visual_impaired"), 0):
            roles.append("audio_description")
        if _int(disposition.get("comment"), 0):
            roles.append("commentary")
        if _int(disposition.get("dub"), 0):
            roles.append("dub")
        if roles:
            native["roles"] = roles
        if kind == "video":
            if probe.get("bits_per_raw_sample") in (None, ""):
                match = re.search(r"p(\d+)(?:le|be)$", str(item.get("pix_fmt", "")))
                if match:
                    probe["bits_per_raw_sample"] = match.group(1)
                elif str(item.get("pix_fmt", "")) in {"yuv420p", "yuvj420p"}:
                    probe["bits_per_raw_sample"] = "8"
            if hdr_static.mastering_display is not None:
                probe.setdefault("mastering_display", hdr_static.mastering_display)
            if hdr_static.max_cll is not None:
                probe.setdefault("max_cll", hdr_static.max_cll)
            if hdr_static.max_fall is not None:
                probe.setdefault("max_fall", hdr_static.max_fall)
            if hdr10_plus:
                native["hdr10_plus"] = True
        stream = self._streams._stream_from_probe(
            index, probe, native, tag_language_source="matroska"
        )
        if kind == "subtitle" and is_text_subtitle_codec(stream.codec):
            stream = replace(stream, text_subtitle=True)
        return stream
