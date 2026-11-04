"""Opening an external source: a video file, a DVD folder or a DVD image."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any, Sequence

from .frame_map import SIGNATURE_HEIGHT, SIGNATURE_WIDTH

FILE_SUFFIXES = {".mkv", ".mp4", ".m4v", ".m2ts", ".mts", ".ts", ".vob", ".mpg", ".mpeg", ".avi"}
SUBTITLE_SUFFIXES = {".srt"}

KIND_FILE = "file"
KIND_DVD_FOLDER = "dvd-folder"
KIND_DVD_IMAGE = "dvd-image"

_VOB_NAME = re.compile(r"^VTS_(\d\d)_([1-9])\.VOB$", re.IGNORECASE)
_LSDVD_TITLE = re.compile(r"^Title:\s*(\d+),\s*Length:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
_LSDVD_VTS = re.compile(r"VTS:\s*(\d+).*?FPS:\s*([\d.]+).*?Width:\s*(\d+),\s*Height:\s*(\d+)")
_LSDVD_AUDIO = re.compile(
    r"Audio:\s*\d+,\s*Language:\s*(\S+).*?Format:\s*(\S+?),\s*Frequency:\s*(\d+).*?"
    r"Channels:\s*(\d+).*?Stream id:\s*(0x[0-9a-fA-F]+)"
)


class ExternalSourceError(ValueError):
    """The source cannot be read as an external source."""


@dataclass(frozen=True, slots=True)
class SourceTrack:
    """``stream`` is an FFmpeg stream specifier: ``a:0`` or, on a DVD, ``#0x80``."""

    stream: str
    codec: str
    channels: int
    sample_rate: int
    bit_rate: int | None
    language: str | None
    title: str | None = None


@dataclass(frozen=True, slots=True)
class SourceInfo:
    kind: str
    path: str
    fps: str
    duration_seconds: float
    width: int | None
    height: int | None
    tracks: tuple[SourceTrack, ...]
    title_set: int | None = None

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["tracks"] = [asdict(track) for track in self.tracks]
        return value


def external_support() -> dict[str, Any]:
    """Whether this host can fit external sources, and what is missing."""

    missing = [tool for tool in ("ffmpeg", "ffprobe", "mkvmerge") if shutil.which(tool) is None]
    dvd_tools = [tool for tool in ("lsdvd", "7z") if shutil.which(tool) is None]
    try:
        import numpy  # noqa: F401
    except ImportError:
        missing.append("numpy")
    return {"available": not missing, "missing": missing, "dvd_missing": dvd_tools}


def exact_fps(value: object) -> Fraction | None:
    """The frame rate as an exact fraction; a rounded decimal means the usual one."""

    if value is None:
        return None
    try:
        rate = Fraction(str(value))
    except (ValueError, ZeroDivisionError):
        return None
    if rate <= 0:
        return None
    for usual in (Fraction(24000, 1001), Fraction(30000, 1001), Fraction(60000, 1001)):
        if abs(float(rate - usual)) < 0.002:
            return usual
    return rate


def _fps_from_lsdvd(value: str) -> Fraction:
    number = float(value)
    if abs(number - 25.0) < 0.01:
        return Fraction(25)
    if abs(number - 29.97) < 0.02:
        return Fraction(30000, 1001)
    raise ExternalSourceError(f"unexpected DVD frame rate: {value}")


def resolve_kind(path: Path) -> tuple[str, Path]:
    """What the path is; a release folder holding one DVD image means that image."""

    if path.is_file():
        suffix = path.suffix.casefold()
        if suffix == ".iso":
            return KIND_DVD_IMAGE, path
        if suffix in FILE_SUFFIXES:
            return KIND_FILE, path
        raise ExternalSourceError(f"unsupported source file: {path.name}")
    if path.is_dir():
        if path.name.casefold() == "video_ts":
            return KIND_DVD_FOLDER, path
        inner = path / "VIDEO_TS"
        if inner.is_dir():
            return KIND_DVD_FOLDER, inner
        images = sorted(item for item in path.iterdir() if item.suffix.casefold() == ".iso")
        if len(images) == 1:
            return KIND_DVD_IMAGE, images[0]
        raise ExternalSourceError(f"no VIDEO_TS folder or single DVD image in {path.name}")
    raise ExternalSourceError(f"source not found: {path}")


def parse_lsdvd(text: str) -> list[dict[str, Any]]:
    titles: list[dict[str, Any]] = []
    for line in text.splitlines():
        match = _LSDVD_TITLE.match(line.strip())
        if match:
            hours, minutes, seconds = match.group(2, 3, 4)
            titles.append(
                {
                    "number": int(match.group(1)),
                    "seconds": int(hours) * 3600 + int(minutes) * 60 + float(seconds),
                    "audio": [],
                }
            )
            continue
        if not titles:
            continue
        match = _LSDVD_VTS.search(line)
        if match:
            titles[-1].update(
                title_set=int(match.group(1)),
                fps=match.group(2),
                width=int(match.group(3)),
                height=int(match.group(4)),
            )
            continue
        match = _LSDVD_AUDIO.search(line)
        if match:
            language = match.group(1)
            titles[-1]["audio"].append(
                {
                    "language": None if language in {"xx", "--"} else language,
                    "codec": match.group(2).casefold(),
                    "sample_rate": int(match.group(3)),
                    "channels": int(match.group(4)),
                    "stream": f"#{match.group(5).lower()}",
                }
            )
    return titles


def probe_dvd(kind: str, path: Path, *, run: Any = subprocess.run) -> SourceInfo:
    completed = run(
        ["lsdvd", "-x", str(path)], capture_output=True, text=True, timeout=120, check=False
    )
    titles = [title for title in parse_lsdvd(completed.stdout or "") if "title_set" in title]
    if not titles:
        raise ExternalSourceError("lsdvd found no title on the DVD")
    main = max(titles, key=lambda title: title["seconds"])
    tracks = tuple(
        SourceTrack(
            stream=item["stream"],
            codec=item["codec"],
            channels=item["channels"],
            sample_rate=item["sample_rate"],
            bit_rate=None,
            language=item["language"],
        )
        for item in main["audio"]
    )
    return SourceInfo(
        kind=kind,
        path=str(path),
        fps=str(_fps_from_lsdvd(main["fps"])),
        duration_seconds=float(main["seconds"]),
        width=main["width"],
        height=main["height"],
        tracks=tracks,
        title_set=main["title_set"],
    )


def _rate(value: object) -> Fraction | None:
    try:
        rate = Fraction(str(value))
    except (ValueError, ZeroDivisionError):
        return None
    return rate if rate > 0 else None


def probe_file(path: Path, *, run: Any = subprocess.run) -> SourceInfo:
    completed = run(
        [
            "ffprobe", "-hide_banner", "-v", "error",
            "-show_entries",
            "format=duration:stream=index,codec_type,codec_name,channels,sample_rate,bit_rate,"
            "r_frame_rate,avg_frame_rate,width,height:stream_tags=language,title",
            "-of", "json", str(path),
        ],
        capture_output=True, text=True, timeout=300, check=False,
    )
    try:
        document = json.loads(completed.stdout or "{}")
    except ValueError as exc:
        raise ExternalSourceError(f"ffprobe could not read {path.name}") from exc
    streams = document.get("streams") or []
    video = next((item for item in streams if item.get("codec_type") == "video"), None)
    if video is None:
        raise ExternalSourceError(f"{path.name} holds no video to match against the title")
    fps = _rate(video.get("r_frame_rate")) or _rate(video.get("avg_frame_rate"))
    if fps is None:
        raise ExternalSourceError(f"{path.name} has no usable frame rate")
    tracks = []
    for ordinal, item in enumerate(s for s in streams if s.get("codec_type") == "audio"):
        tags = item.get("tags") or {}
        bit_rate = item.get("bit_rate")
        tracks.append(
            SourceTrack(
                stream=f"a:{ordinal}",
                codec=str(item.get("codec_name") or "").casefold(),
                channels=int(item.get("channels") or 0),
                sample_rate=int(item.get("sample_rate") or 0),
                bit_rate=int(bit_rate) if str(bit_rate or "").isdigit() else None,
                language=tags.get("language"),
                title=tags.get("title"),
            )
        )
    return SourceInfo(
        kind=KIND_FILE,
        path=str(path),
        fps=str(exact_fps(fps) or fps),
        duration_seconds=float((document.get("format") or {}).get("duration") or 0.0),
        width=video.get("width"),
        height=video.get("height"),
        tracks=tuple(tracks),
    )


def probe_source(path: Path, *, run: Any = subprocess.run) -> SourceInfo:
    kind, resolved = resolve_kind(path)
    if kind == KIND_FILE:
        return probe_file(resolved, run=run)
    return probe_dvd(kind, resolved, run=run)


def image_vob_names(listing: str, title_set: int) -> list[str]:
    """The title set's ``VIDEO_TS/VTS_nn_m.VOB`` members in a ``7z l`` listing, in order."""

    found: list[tuple[int, str]] = []
    for line in listing.splitlines():
        name = line.strip().split(" ")[-1].replace("\\", "/")
        base = name.rsplit("/", 1)[-1]
        match = _VOB_NAME.match(base)
        if match and int(match.group(1)) == title_set:
            found.append((int(match.group(2)), name))
    return [name for _number, name in sorted(found)]


def image_list_command(image: Path) -> list[str]:
    return ["7z", "l", "-ba", str(image)]


def image_extract_command(image: Path, names: Sequence[str], directory: Path) -> list[str]:
    return ["7z", "e", "-y", f"-o{directory}", str(image), *names]


def folder_vobs(folder: Path, title_set: int) -> list[Path]:
    found: list[tuple[int, Path]] = []
    for item in folder.iterdir():
        match = _VOB_NAME.match(item.name)
        if match and int(match.group(1)) == title_set:
            found.append((int(match.group(2)), item))
    return [path for _number, path in sorted(found)]


def input_arguments(info_kind: str, path: Path, vobs: Sequence[Path] = ()) -> list[str]:
    """FFmpeg input for the source; VOBs of a title set read as one program stream.

    ``concat:`` splits on ``|``, so the worker gives it links with safe names.
    """

    if info_kind == KIND_FILE:
        return ["-i", str(path)]
    if not vobs:
        raise ExternalSourceError("the DVD title set has no VOB files")
    joined = "|".join(str(item) for item in vobs)
    if joined.count("|") != len(vobs) - 1:
        raise ExternalSourceError("a VOB path contains a pipe character")
    return ["-f", "mpeg", "-probesize", "200M", "-analyzeduration", "200M", "-i", f"concat:{joined}"]


def signature_command(input_args: Sequence[str], output: Path, *, ffmpeg: str = "ffmpeg") -> list[str]:
    """Every decoded picture as a tiny grey frame; frame numbers are what the map counts."""

    return [
        ffmpeg, "-hide_banner", "-nostdin", "-v", "error",
        *input_args,
        "-map", "0:v:0", "-an", "-sn", "-dn",
        "-fps_mode", "passthrough",
        "-vf", f"scale={SIGNATURE_WIDTH}:{SIGNATURE_HEIGHT}:flags=area,format=gray",
        "-f", "rawvideo", "-y", str(output),
    ]


def first_time_command(
    input_args: Sequence[str], specifier: str, *, ffprobe: str = "ffprobe"
) -> list[str]:
    """The presentation time of the stream's first decoded frame."""

    return [
        ffprobe, "-hide_banner", "-v", "error",
        *input_args,
        "-select_streams", specifier,
        "-read_intervals", "%+#1",
        "-show_entries", "frame=pts_time,best_effort_timestamp_time",
        "-of", "json",
    ]


def parse_first_time(text: str) -> float | None:
    try:
        frames = json.loads(text or "{}").get("frames") or []
    except ValueError:
        return None
    for frame in frames:
        for key in ("pts_time", "best_effort_timestamp_time"):
            value = frame.get(key)
            if value not in {None, "N/A"}:
                return float(value)
    return None
