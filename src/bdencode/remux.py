"""Blu-ray and UHD Blu-ray remuxes the way Aither's REMUX guide makes them.

Nothing is re-encoded.  eac3to (under Wine) demuxes the playlist, exactly as
the guide does it, and its log is the evidence Aither asks for with every
personal remux.  The guide does not trust eac3to with HEVC timing, so an UHD
disc's video comes from the independent FFmpeg demux instead, and a dual-layer
Dolby Vision disc's two layers become one track with ``dovi_tool mux`` (what
MakeMKV writes).  Everything is muxed untouched with mkvmerge, apart from the
two conversions the guide itself prescribes:

* Blu-ray LPCM becomes FLAC (eac3to strips 24-bit zero padding on the way);
* every TrueHD track keeps its embedded AC-3 as a separate compatibility
  track, placed straight after it.

Track names follow BDInfo's Quick Summary (``MPEG-4 AVC Video / 31990 kbps /
1080p / 23.976 fps / 16:9 / High Profile 4.1``), the release name follows
Aither's remux scheme (``Title.Year.1080p.BluRay.REMUX.AVC.DTS-HD.MA.5.1-TAG``)
and the container title is ``Title (Year)``.

This module is pure: it builds commands and parses tool output, the worker
runs them.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction
import json
from pathlib import PurePosixPath
import re
import struct
import sys
from typing import Mapping, Sequence

from .media.bluray import MediaStream, PlaylistCandidate, StreamKind, VideoProperties
from .release_naming import audio_codec_family, channel_layout

# Aither's remux guide demuxes with eac3to; its log is part of every PR remux.
EAC3TO_EXE = r"C:\eac3to\eac3to.exe"
# Wine drive letters: the disc and the job's demux folder.  The log then says
# ``S:\BDMV\PLAYLIST\00800.mpls`` instead of a server path and user name.
SOURCE_DRIVE = "s:"
WORK_DRIVE = "w:"
LOG_NAME = "eac3to.log"
CHAPTERS_NAME = "chapters.txt"

VIDEO_FAMILIES = frozenset({"AVC", "HEVC", "VC1", "MPEG2"})
AUDIO_FAMILIES = frozenset(
    {"TRUEHD", "DTSHDMA", "DTSX", "DTSHDHRA", "DTS", "DTSEXPRESS", "DD", "DDP", "LPCM"}
)
LOSSLESS_FAMILIES = frozenset({"TRUEHD", "DTSHDMA", "DTSX", "LPCM", "FLAC"})
# The guide: "Tick Remove dialog normalization on all lossless tracks and
# DTS-HD HRA."  mkvmerge does it for AC-3, DTS and TrueHD bitstreams.
REMOVE_DIALNORM_FAMILIES = frozenset({"TRUEHD", "DTSHDMA", "DTSX", "DTSHDHRA"})
# Lossy tracks keep their dialog normalization (eac3to -keepDialnorm); DTS-HD
# HRA is the guide's one exception.
KEEP_DIALNORM_FAMILIES = frozenset({"DD", "DDP", "DTS", "DTSEXPRESS"})

DEMUX_EXTENSIONS = {
    "AVC": "h264",
    "HEVC": "h265",
    "VC1": "vc1",
    "MPEG2": "m2v",
    "TRUEHD": "thd",
    "DTSHDMA": "dtsma",
    "DTSX": "dtsma",
    "DTSHDHRA": "dtshr",
    "DTS": "dts",
    # eac3to needs the explicit extension for DTS Express.
    "DTSEXPRESS": "dts",
    "DD": "ac3",
    "DDP": "eac3",
    "LPCM": "flac",
    "PGS": "sup",
}


class RemuxError(ValueError):
    """The disc or the selection cannot be remuxed as the guide requires."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


# --- eac3to's track listing -------------------------------------------------


@dataclass(frozen=True, slots=True)
class Eac3toTrack:
    number: int
    label: str  # eac3to's codec text, e.g. "TrueHD/AC3 (Atmos)"
    family: str  # CHAPTERS, AVC, HEVC, ..., TRUEHD, DTSHDMA, ..., PGS, OTHER
    kind: str  # chapters, video, audio, subtitle, other
    language: str | None = None  # eac3to's English language name
    channels: int | None = None
    bit_depth: int | None = None
    sample_rate: int | None = None
    kbps: int | None = None
    dialnorm_db: int | None = None
    atmos: bool = False
    video_format: str | None = None  # "1080p24 /1.001"
    aspect: str | None = None  # "16:9"
    chapter_count: int | None = None
    # "(embedded: AC3, 5.1 channels, 448kbps, 48kHz)" of a TrueHD/AC3 track.
    embedded_ac3_channels: int | None = None
    embedded_ac3_kbps: int | None = None
    details: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    @property
    def has_embedded_ac3(self) -> bool:
        return self.family == "TRUEHD" and self.embedded_ac3_channels is not None


@dataclass(frozen=True, slots=True)
class Eac3toListing:
    header: str
    tracks: tuple[Eac3toTrack, ...]

    def of_kind(self, kind: str) -> tuple[Eac3toTrack, ...]:
        return tuple(item for item in self.tracks if item.kind == kind)

    @property
    def chapters(self) -> Eac3toTrack | None:
        return next((item for item in self.tracks if item.kind == "chapters"), None)


_TRACK_LINE = re.compile(r"^(?P<number>\d{1,3}): (?P<text>.+?)\s*$")
_NOTE_LINE = re.compile(r"^\[?(?P<kind>[avs])(?P<number>\d{2,3})\]? (?P<text>.+?)\s*$")
_CHANNELS = re.compile(r"^(?P<main>\d)\.(?P<lfe>\d) channels$")
_BITS = re.compile(r"^(?P<bits>\d{1,2}) bits$")
_RATE = re.compile(r"^(?P<rate>\d{2,3})kHz$")
_KBPS = re.compile(r"^(?P<kbps>\d{2,5})kbps$")
_DIALNORM = re.compile(r"^dialnorm: (?P<db>-?\d{1,2})dB$")
_VIDEO_FORMAT = re.compile(
    r"^(?P<format>(?:\d{3,4}[pi]\d{2}|\d{3,4}x\d{3,4} \d{2}[pi]?)(?: /1\.001)?)"
    r"(?: \((?P<aspect>\d+:\d+)\))?$"
)
_CHAPTER_COUNT = re.compile(r"^(?P<count>\d+) chapters?$")
_EMBEDDED_AC3 = re.compile(
    r"^\(embedded: AC3, (?P<main>\d)\.(?P<lfe>\d) channels, (?P<kbps>\d+)kbps"
)
_TECHNICAL = re.compile(r"\d|^(?:HDR10|HDR10\+|BT\.\d+|SDR|Dolby Vision|stereo|mono|multi-channel)$")


def track_family(label: str) -> tuple[str, str]:
    """``(family, kind)`` of an eac3to codec label."""

    text = label.strip()
    upper = text.upper()
    if text == "Chapters":
        return "CHAPTERS", "chapters"
    if upper.startswith("SUBTITLE"):
        return ("PGS" if "PGS" in upper else "OTHER"), "subtitle"
    if upper.startswith("H264") or "/AVC" in upper or upper.startswith("MPEG4"):
        return ("OTHER" if "MVC" in upper else "AVC"), "video"
    if upper.startswith("H265") or "HEVC" in upper:
        return "HEVC", "video"
    if upper.startswith("VC-1") or upper.startswith("VC1"):
        return "VC1", "video"
    if upper.startswith("MPEG2") or upper.startswith("MPEG-2"):
        return "MPEG2", "video"
    if upper.startswith("TRUEHD") or upper.startswith("MLP"):
        return "TRUEHD", "audio"
    if upper.startswith("DTS"):
        if "DTS:X" in upper or "DTS-X" in upper:
            return "DTSX", "audio"
        if "MASTER" in upper:
            return "DTSHDMA", "audio"
        if "HI-RES" in upper or "HIGH RES" in upper:
            return "DTSHDHRA", "audio"
        if "EXPRESS" in upper:
            return "DTSEXPRESS", "audio"
        return "DTS", "audio"
    if upper.startswith("E-AC3") or upper.startswith("EAC3") or upper.startswith("DD+"):
        return "DDP", "audio"
    if upper.startswith("AC3"):
        return "DD", "audio"
    if "PCM" in upper:
        return "LPCM", "audio"
    return "OTHER", "other"


def _parse_track(number: int, text: str) -> Eac3toTrack:
    parts = [item.strip() for item in text.split(", ")]
    label = parts[0]
    family, kind = track_family(label)
    values: dict[str, object] = {}
    for part in parts[1:]:
        if match := _CHANNELS.fullmatch(part):
            values["channels"] = int(match["main"]) + int(match["lfe"])
        elif match := _BITS.fullmatch(part):
            values["bit_depth"] = int(match["bits"])
        elif match := _RATE.fullmatch(part):
            values["sample_rate"] = int(match["rate"]) * 1000
        elif match := _KBPS.fullmatch(part):
            values["kbps"] = int(match["kbps"])
        elif match := _DIALNORM.fullmatch(part):
            values["dialnorm_db"] = int(match["db"])
        elif match := _CHAPTER_COUNT.fullmatch(part):
            values["chapter_count"] = int(match["count"])
        elif kind == "video" and (match := _VIDEO_FORMAT.fullmatch(part)):
            values["video_format"] = match["format"]
            if match["aspect"]:
                values["aspect"] = match["aspect"]
        elif (
            kind in {"audio", "subtitle"}
            and "language" not in values
            and not _TECHNICAL.search(part)
        ):
            values["language"] = part
    return Eac3toTrack(
        number=number,
        label=label,
        family=family,
        kind=kind,
        atmos="ATMOS" in label.upper(),
        **values,  # type: ignore[arg-type]
    )


def parse_listing(text: str) -> Eac3toListing:
    """Parse ``eac3to <playlist.mpls>`` output (or the head of its log)."""

    header = ""
    tracks: list[Eac3toTrack] = []
    details: dict[int, list[str]] = {}
    notes: dict[int, list[str]] = {}
    for raw in text.replace("\b", "").splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped or set(stripped) <= {"-"}:
            continue
        # eac3to overwrites its progress line; the header may follow dashes.
        candidate = stripped.lstrip("-").strip()
        if not header and re.match(r"^(?:M2TS|EVO|TS|MKV)\b", candidate) and "," in candidate:
            header = candidate
            continue
        if match := _TRACK_LINE.fullmatch(stripped):
            number = int(match["number"])
            if not line.startswith(" ") and not any(item.number == number for item in tracks):
                tracks.append(_parse_track(number, match["text"]))
                continue
        if stripped.startswith("(") and tracks and line.startswith(" "):
            details.setdefault(tracks[-1].number, []).append(stripped)
            continue
        if match := _NOTE_LINE.fullmatch(stripped):
            notes.setdefault(int(match["number"]), []).append(match["text"])
    result: list[Eac3toTrack] = []
    for track in tracks:
        extra = tuple(details.get(track.number, ()))
        embedded = next(
            (match for item in extra if (match := _EMBEDDED_AC3.match(item))), None
        )
        result.append(
            Eac3toTrack(
                **{
                    **{name: getattr(track, name) for name in track.__slots__},
                    "details": extra,
                    "notes": tuple(notes.get(track.number, ())),
                    "embedded_ac3_channels": (
                        int(embedded["main"]) + int(embedded["lfe"]) if embedded else None
                    ),
                    "embedded_ac3_kbps": int(embedded["kbps"]) if embedded else None,
                }
            )
        )
    if not result:
        raise RemuxError("eac3to listed no tracks for the playlist", code="eac3to_listing_empty")
    return Eac3toListing(header=header, tracks=tuple(result))


# --- matching eac3to's tracks to the scan -----------------------------------


def stream_family(stream: MediaStream) -> str:
    codec = (stream.codec or "").casefold()
    if stream.kind is StreamKind.VIDEO:
        return {
            "h264": "AVC",
            "hevc": "HEVC",
            "vc1": "VC1",
            "mpeg2video": "MPEG2",
        }.get(codec, "OTHER")
    if stream.kind is StreamKind.SUBTITLE:
        return "PGS" if codec == "hdmv_pgs_subtitle" else "OTHER"
    family = audio_codec_family(codec, stream.codec_profile)
    if family == "DTS" and "EXPRESS" in (stream.codec_profile or "").upper():
        return "DTSEXPRESS"
    return family


def embedded_core_parent(
    stream: MediaStream, audio_streams: Sequence[MediaStream]
) -> MediaStream | None:
    """The TrueHD whose embedded AC-3 this stream is.

    The scan lists a TrueHD PID twice (``audio:4352:truehd``, ``audio:4352:ac3``);
    eac3to lists it once, as ``TrueHD/AC3``.
    """

    if stream.kind is not StreamKind.AUDIO or stream.pid is None or stream_family(stream) != "DD":
        return None
    return next(
        (
            other
            for other in audio_streams
            if other is not stream and other.pid == stream.pid and stream_family(other) == "TRUEHD"
        ),
        None,
    )


def _families_agree(scan_family: str, listed: str) -> bool:
    # FFmpeg 5 reports DTS:X as plain DTS-HD MA; eac3to may name it either way.
    dts_hd = {"DTSHDMA", "DTSX"}
    return scan_family == listed or (scan_family in dts_hd and listed in dts_hd)


def match_tracks(
    playlist: PlaylistCandidate, listing: Eac3toListing
) -> dict[str, Eac3toTrack]:
    """Scan stream id -> eac3to track, or a ``RemuxError`` naming the conflict.

    eac3to lists a playlist's streams in their STN-table order, which is also
    the order of the scan; the codec families and channel counts must agree
    stream by stream, otherwise the remux would mix up tracks.
    """

    matched: dict[str, Eac3toTrack] = {}
    audio_streams = playlist.audio_streams
    embedded = {
        stream.id: parent
        for stream in audio_streams
        if (parent := embedded_core_parent(stream, audio_streams)) is not None
    }
    for kind, streams in (
        ("video", playlist.video_streams),
        ("audio", tuple(item for item in audio_streams if item.id not in embedded)),
        ("subtitle", playlist.subtitle_streams),
    ):
        listed = listing.of_kind(kind)
        if len(listed) != len(streams):
            raise RemuxError(
                f"eac3to lists {len(listed)} {kind} track(s), the scan "
                f"{len(streams)}; the playlist cannot be matched safely",
                code="eac3to_track_count_mismatch",
            )
        for stream, track in zip(streams, listed):
            family = stream_family(stream)
            if not _families_agree(family, track.family):
                raise RemuxError(
                    f"{stream.id} is {family} in the scan but eac3to track "
                    f"{track.number} is {track.label}",
                    code="eac3to_track_mismatch",
                )
            if (
                kind == "audio"
                and stream.channels
                and track.channels
                and stream.channels != track.channels
            ):
                raise RemuxError(
                    f"{stream.id} has {stream.channels} channels in the scan but "
                    f"eac3to track {track.number} has {track.channels}",
                    code="eac3to_track_mismatch",
                )
            matched[stream.id] = track
    for stream_id, parent in embedded.items():
        matched[stream_id] = matched[parent.id]
    return matched


# --- the demux --------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DemuxOutput:
    """One file eac3to writes: a whole track, or a TrueHD track's AC-3."""

    stream_id: str
    track: int
    family: str
    filename: str
    compatibility: bool = False  # the embedded AC-3 of a TrueHD track


def demux_outputs(
    selected: Sequence[tuple[MediaStream, Eac3toTrack]],
) -> tuple[DemuxOutput, ...]:
    """The eac3to outputs of the retained streams, in selection order."""

    outputs: list[DemuxOutput] = []
    for stream, track in selected:
        if track.family == "TRUEHD" and stream_family(stream) == "DD":
            # Only the AC-3 of a TrueHD/AC3 track is kept: eac3to takes it by
            # the extension.
            outputs.append(
                DemuxOutput(
                    stream_id=stream.id,
                    track=track.number,
                    family="DD",
                    filename=f"{track.number:02d}-audio.ac3",
                )
            )
            continue
        if track.family not in DEMUX_EXTENSIONS:
            raise RemuxError(
                f"{stream.id} ({track.label}) cannot be remuxed",
                code="remux_unsupported_track",
            )
        stem = f"{track.number:02d}-{track.kind}"
        outputs.append(
            DemuxOutput(
                stream_id=stream.id,
                track=track.number,
                family="FLAC" if track.family == "LPCM" else track.family,
                filename=f"{stem}.{DEMUX_EXTENSIONS[track.family]}",
            )
        )
        if track.has_embedded_ac3:
            outputs.append(
                DemuxOutput(
                    stream_id=stream.id,
                    track=track.number,
                    family="DD",
                    filename=f"{track.number:02d}-compatibility.ac3",
                    compatibility=True,
                )
            )
    names = [item.filename for item in outputs]
    if len(set(names)) != len(names):
        raise RemuxError("a demux output was planned twice", code="remux_duplicate_output")
    return tuple(outputs)


EAC3TO_WRAPPER = "bdencode-eac3to"


def _playlist_argument(playlist_id: str) -> str:
    if not re.fullmatch(r"\d{5}", playlist_id):
        raise RemuxError("playlist id must have five digits", code="remux_playlist")
    return rf"S:\BDMV\PLAYLIST\{playlist_id}.mpls"


def _clips_argument(clips: Sequence[str]) -> str:
    if not clips or not all(re.fullmatch(r"\d{5}", clip) for clip in clips):
        raise RemuxError("clip ids must have five digits", code="remux_playlist")
    return "+".join(rf"S:\BDMV\STREAM\{clip}.m2ts" for clip in clips)


# A CLPI file's clock.
CLPI_TICKS_PER_SECOND = 45_000


def clip_presentation(clpi: bytes) -> tuple[int, int] | None:
    """Start and end of a clip in 45 kHz ticks; None unless it has one time base."""

    try:
        if clpi[:4] != b"HDMV":
            return None
        sequence_info = struct.unpack_from(">I", clpi, 8)[0]
        if clpi[sequence_info + 5] != 1:
            return None
        if clpi[sequence_info + 10] != 1:
            return None
        return struct.unpack_from(">II", clpi, sequence_info + 12 + 6)
    except (IndexError, struct.error):
        return None


def whole_clips(
    playlist: PlaylistCandidate, presentation: Mapping[str, tuple[int, int] | None]
) -> tuple[str, ...]:
    """The clips to hand eac3to instead of the playlist, or nothing.

    eac3to 3.36 skips its second pass for a Blu-ray playlist, and with it the
    removal of the audio that overlaps at the clip joins: the concatenated
    audio then runs later and later (God Forgives, I Don't: 33 ms by the last
    clip).  Given the clips themselves it does run it, but it reads each clip
    from end to end, so this is safe only when the playlist does the same.
    """

    segments = playlist.segments
    if len(segments) < 2 or playlist.angle_count != 1:
        return ()
    clips = tuple(segment.clip_id for segment in segments)
    if len(set(clips)) != len(clips):
        return ()
    tolerance = 1.5 / CLPI_TICKS_PER_SECOND
    for segment in segments:
        bounds = presentation.get(segment.clip_id)
        if bounds is None:
            return ()
        start, end = (value / CLPI_TICKS_PER_SECOND for value in bounds)
        if abs(segment.in_time_seconds - start) > tolerance:
            return ()
        if abs(segment.out_time_seconds - end) > tolerance:
            return ()
    return clips


def eac3to_demux_command(
    disc_root: object,
    playlist_id: str,
    outputs: Sequence[DemuxOutput],
    *,
    chapters: bool = True,
    clips: Sequence[str] = (),
    wrapper: str = EAC3TO_WRAPPER,
) -> list[str]:
    """The guide's demux: ``eac3to playlist.mpls 1:chapters.txt 2:video.* ...``.

    The wrapper maps the disc to ``S:`` and the working directory to ``W:``
    and runs eac3to as ``C:\\eac3to\\eac3to.exe``, so the log names no server
    path.  Outputs and the log are relative: they land in the working
    directory.  ``clips`` (see ``whole_clips``) replaces the playlist.
    """

    source = _clips_argument(clips) if clips else _playlist_argument(playlist_id)
    command = [wrapper, str(disc_root), source]
    if chapters:
        command.append(f"1:{CHAPTERS_NAME}")
    for item in outputs:
        command.append(f"{item.track}:{item.filename}")
        if item.family in KEEP_DIALNORM_FAMILIES:
            command.append("-keepDialnorm")
    command.extend(["-progressnumbers", f"-log={LOG_NAME}"])
    return command


def eac3to_listing_command(
    disc_root: object, playlist_id: str, *, wrapper: str = EAC3TO_WRAPPER
) -> list[str]:
    # Given only the playlist, eac3to prints a summary; "1)" lists its tracks.
    return [wrapper, str(disc_root), _playlist_argument(playlist_id), "1)"]


def eac3to_clips_listing_command(
    disc_root: object, clips: Sequence[str], *, wrapper: str = EAC3TO_WRAPPER
) -> list[str]:
    # "1)" picks a title of a disc structure; joined clips are not one.
    return [wrapper, str(disc_root), _clips_argument(clips)]


_PROGRESS = re.compile(r"(?:process|analyze): (\d{1,3})%")


def eac3to_progress(console: str) -> float | None:
    """Fraction done from eac3to's ``-progressnumbers`` console output."""

    values = _PROGRESS.findall(console[-4096:])
    return int(values[-1]) / 100 if values else None


@dataclass(frozen=True, slots=True)
class LogFinding:
    severity: str  # "error", "warning" or "info"
    text: str


# eac3to tags its own warnings and errors at the end of the line.
_LOG_MARK = re.compile(r"\s*<(?P<mark>WARNING|ERROR)>\s*$")
# Warnings that say nothing about the remux: 24p without /1.001 is "unusual".
_LOG_BENIGN_WARNINGS = re.compile(
    r"(?i)the video framerate is correct, but rather unusual"
)
# Not tagged, but a reviewer must see them: forced captions mixed into a
# subtitle track (the guide extracts them separately) and stripped padding.
_LOG_INFO = re.compile(
    r"(?i)\d+ normal and \d+ forced captions|zero padding|bits? (?:are|is) zero|"
    r"removing dialnorm|dialog normalization"
)
_LOG_UNTAGGED_ERRORS = re.compile(r"(?i)^(?:aborted|error\b|.*\bfailed\b|.*\bcrashed\b)")


def log_findings(log: str) -> tuple[LogFinding, ...]:
    """Lines of an eac3to log worth a reviewer's attention.

    The guide: "Minor timing discrepancies (audio delayed by a few
    milliseconds) are insignificant. More substantial warnings should be
    investigated."  Errors stop the job; warnings and notes are shown and
    kept with the release.
    """

    findings: list[LogFinding] = []
    for raw in log.replace("\b", "").splitlines():
        line = raw.strip()
        if not line or set(line) <= {"-"} or _TRACK_LINE.fullmatch(line):
            continue
        mark = _LOG_MARK.search(line)
        text = _LOG_MARK.sub("", line)
        body = re.sub(r"^\[[avs]\d+\]\s*", "", text)
        if mark and mark["mark"] == "ERROR":
            findings.append(LogFinding("error", text))
        elif mark:
            if not _LOG_BENIGN_WARNINGS.search(body):
                findings.append(LogFinding("warning", text))
        elif _LOG_UNTAGGED_ERRORS.match(body):
            findings.append(LogFinding("error", text))
        elif _LOG_INFO.search(body):
            findings.append(LogFinding("info", text))
    return tuple(findings)


_FRAME_COUNT = re.compile(r"Video track (?P<track>\d+) contains (?P<frames>\d+) frames")


def logged_frame_count(log: str) -> int | None:
    match = _FRAME_COUNT.search(log)
    return int(match["frames"]) if match else None


def public_log(log: str) -> str:
    """The log as Aither gets it: Windows line ends folded, progress dropped."""

    lines = []
    for raw in log.replace("\r\n", "\n").replace("\r", "\n").replace("\b", "").split("\n"):
        if _PROGRESS.fullmatch(raw.strip()):
            continue
        lines.append(raw.rstrip())
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines) + "\n"


# --- BDInfo-style track names -----------------------------------------------


def kbps(size_bytes: int, duration_seconds: Decimal | float) -> int:
    """Average bitrate as BDInfo prints it: whole kilobits per second."""

    duration = Decimal(str(duration_seconds))
    if duration <= 0:
        raise RemuxError("duration must be positive", code="remux_duration")
    value = Decimal(size_bytes) * 8 / duration / 1000
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def fps_text(frame_rate: str) -> str:
    """``24000/1001`` -> ``23.976 fps``."""

    rate = Fraction(frame_rate)
    value = (Decimal(rate.numerator) / Decimal(rate.denominator)).quantize(
        Decimal("0.001"), rounding=ROUND_HALF_UP
    )
    return f"{value} fps"


def resolution_text(height: int | None, field_order: str | None, frame_rate: str | None) -> str:
    height = height or 0
    line = 2160 if height > 1088 else 1080 if height > 720 else 720 if height > 576 else 576 if height > 480 else 480
    interlaced = (field_order or "progressive").casefold() not in {"progressive", "unknown", ""}
    # The guide: 25 fps 1080i sources are listed as 1080p.
    if interlaced and frame_rate and Fraction(frame_rate) == 25:
        interlaced = False
    return f"{line}{'i' if interlaced else 'p'}"


def _level_text(level: int | None, family: str) -> str | None:
    if level is None or level <= 0:
        return None
    if family == "HEVC":
        return f"{Decimal(level) / 30:.1f}".rstrip("0").rstrip(".") if level % 30 else str(level // 30)
    return f"{level // 10}.{level % 10}" if family == "AVC" else str(level)


def video_track_name(
    *,
    family: str,
    kbps_value: int,
    height: int | None,
    frame_rate: str,
    aspect: str | None,
    profile: str | None,
    level: int | None,
    field_order: str | None = None,
    bit_depth: int | None = None,
    hdr: str | None = None,
    max_luminance_nits: int | None = None,
    color_primaries: str | None = None,
    hevc_tier: str | None = None,
    dolby_vision: str | None = None,
    dolby_vision_kbps: int | None = None,
) -> str:
    """BDInfo's Quick Summary video line, the guide's video track title."""

    codec = {
        "AVC": "MPEG-4 AVC Video",
        "HEVC": "MPEG-H HEVC Video",
        "VC1": "VC-1 Video",
        "MPEG2": "MPEG-2 Video",
    }[family]
    parts = [
        codec,
        f"{kbps_value} kbps",
        resolution_text(height, field_order, frame_rate),
        fps_text(frame_rate),
        aspect or "16:9",
    ]
    level_text = _level_text(level, family)
    if family == "HEVC":
        profile_text = profile or "Main 10"
        if level_text:
            profile_text += f" @ Level {level_text}"
        if hevc_tier:
            profile_text += f" @ {hevc_tier}"
        parts.extend([profile_text, "4:2:0"])
        # The scan's FFmpeg often leaves the depth of a disc's HEVC open; Main 10 says it.
        depth = bit_depth or (10 if profile_text.startswith("Main 10") else None)
        if depth:
            parts.append(f"{depth} bits")
        if max_luminance_nits:
            parts.append(f"{max_luminance_nits}nits")
        if hdr:
            parts.append(hdr)
        if color_primaries:
            parts.append(color_primaries)
        if dolby_vision:
            parts.append(
                f"Dolby Vision {dolby_vision}"
                + (f" @ {dolby_vision_kbps} kbps" if dolby_vision_kbps else "")
            )
    else:
        profile_text = f"{profile} Profile" if profile else None
        if profile_text and level_text:
            profile_text += f" {level_text}"
        if profile_text:
            parts.append(profile_text)
    return " / ".join(parts)


AUDIO_NAMES = {
    "TRUEHD": "Dolby TrueHD Audio",
    "DTSHDMA": "DTS-HD Master Audio",
    "DTSX": "DTS:X Master Audio",
    "DTSHDHRA": "DTS-HD High-Res Audio",
    "DTS": "DTS Audio",
    "DTSEXPRESS": "DTS Express",
    "DD": "Dolby Digital Audio",
    "DDP": "Dolby Digital Plus Audio",
    "FLAC": "FLAC Audio",
    "LPCM": "LPCM Audio",
}


def audio_track_name(
    *,
    family: str,
    channels: int | None,
    sample_rate: int | None,
    kbps_value: int,
    bit_depth: int | None = None,
    atmos: bool = False,
    prefix: str | None = None,
) -> str:
    """BDInfo's audio line, e.g. ``DTS-HD Master Audio / 5.1 / 48 kHz / 3611 kbps / 24-bit``.

    ``prefix`` carries the guide's role names: ``Compatibility Track``,
    ``Commentary by ...``, ``Dub``, ``Original Mix``.
    """

    codec = AUDIO_NAMES[family]
    if atmos and family == "TRUEHD":
        codec = "Dolby TrueHD/Atmos Audio"
    elif atmos and family == "DDP":
        codec = "Dolby Digital Plus/Atmos Audio"
    parts = [codec]
    layout = channel_layout(channels)
    if layout:
        parts.append(layout)
    if sample_rate:
        parts.append(f"{sample_rate // 1000} kHz")
    parts.append(f"{kbps_value} kbps")
    if bit_depth and family not in {"DD", "DDP"}:
        parts.append(f"{bit_depth}-bit")
    text = " / ".join(parts)
    return f"{prefix} / {text}" if prefix else text


# --- release name and container title ---------------------------------------


VIDEO_NAME_CODECS = {"AVC": "AVC", "HEVC": "HEVC", "VC1": "VC-1", "MPEG2": "MPEG-2"}

_YEAR = re.compile(r"^(?:19|20)\d{2}$")
_EPISODE = re.compile(r"^S\d{2}(?:E\d{2,3})?$", re.IGNORECASE)


def container_title(output_name: str) -> str:
    """``The.Quiet.2005.1080p.BluRay.REMUX...`` -> ``The Quiet (2005)``.

    The guide: ``Movie Name (Year)`` for films, ``Show - S01E04`` for an
    episode without a name.
    """

    words: list[str] = []
    for word in output_name.split("."):
        if re.fullmatch(r"\d{3,4}[pi]", word, re.IGNORECASE):
            break
        words.append(word)
    episode = next((index for index, word in enumerate(words) if _EPISODE.fullmatch(word)), None)
    if episode is not None:
        title = " ".join(word for word in words[:episode] if not _YEAR.fullmatch(word))
        return f"{title} - {words[episode].upper()}"
    year_index = next(
        (index for index in range(len(words) - 1, 0, -1) if _YEAR.fullmatch(words[index])),
        None,
    )
    if year_index is None:
        return " ".join(words)
    return f"{' '.join(words[:year_index])} ({words[year_index]})"


# --- the mux ----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RemuxTrack:
    """One track of the final MKV, in output order."""

    path: PurePosixPath | object  # a Path at runtime
    kind: str  # video, audio, subtitle
    language: str  # BCP 47
    name: str | None = None
    default: bool = False
    forced: bool = False
    original: bool = False
    commentary: bool = False
    hearing_impaired: bool = False
    visual_impaired: bool = False
    remove_dialnorm: bool = False
    default_duration: str | None = None  # "24000/1001p" for raw video


def remux_mkvmerge_command(
    output: object,
    tracks: Sequence[RemuxTrack],
    *,
    title: str,
    chapters: object | None,
    chapter_language: str = "en",
    global_tags: object | None = None,
    mkvmerge: str = "mkvmerge",
) -> list[str]:
    """mkvmerge with the guide's flags: names, languages, default/forced/
    original/commentary/hearing- and visual-impaired, no compression, and
    dialog normalization removed from the lossless tracks."""

    if not tracks or tracks[0].kind != "video":
        raise RemuxError("the video track goes first", code="remux_track_order")
    command = [mkvmerge, "--output", str(output), "--title", title]
    if chapters is not None:
        command.extend(["--chapter-language", chapter_language, "--chapters", str(chapters)])
    if global_tags is not None:
        command.extend(["--global-tags", str(global_tags)])
    for track in tracks:
        flag = "yes" if track.default else "no"
        command.extend(["--language", f"0:{track.language}"])
        if track.name:
            command.extend(["--track-name", f"0:{track.name}"])
        command.extend(["--default-track-flag", f"0:{flag}"])
        if track.kind == "subtitle":
            command.extend(["--forced-display-flag", f"0:{'yes' if track.forced else 'no'}"])
        if track.original:
            command.extend(["--original-flag", "0:yes"])
        if track.commentary:
            command.extend(["--commentary-flag", "0:yes"])
        if track.hearing_impaired:
            command.extend(["--hearing-impaired-flag", "0:yes"])
        if track.visual_impaired:
            command.extend(["--visual-impaired-flag", "0:yes"])
        if track.remove_dialnorm:
            command.extend(["--remove-dialog-normalization-gain", "0"])
        if track.default_duration:
            command.extend(["--default-duration", f"0:{track.default_duration}"])
        command.extend(["--compression", "0:none", str(track.path)])
    command.extend(
        ["--track-order", ",".join(f"{index}:0" for index in range(len(tracks)))]
    )
    return command


def video_extract_command(
    reference: object, ordinal: int, output: object, *, ffmpeg: str = "ffmpeg"
) -> list[str]:
    """One HEVC layer of the reference as a raw Annex B stream, bit for bit."""

    return [
        ffmpeg,
        "-hide_banner",
        "-nostdin",
        "-v",
        "error",
        "-i",
        str(reference),
        "-map",
        f"0:v:{ordinal}",
        "-c",
        "copy",
        "-bsf:v",
        "hevc_mp4toannexb",
        "-f",
        "hevc",
        "-y",
        str(output),
    ]


def dovi_mux_command(bl: object, el: object, output: object, *, tool: str = "dovi_tool") -> list[str]:
    """Interleave the enhancement layer into the base layer: one profile 7 track."""

    return [tool, "mux", "--bl", str(bl), "--el", str(el), "--no-add-aud", "--output", str(output)]


def dovi_probe_command(path: object, *, ffprobe: str = "ffprobe") -> list[str]:
    """The Dolby Vision configuration record the container announces."""

    return [
        ffprobe,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream_side_data",
        "-of",
        "json",
        str(path),
    ]


def enhancement_layer_command(path: object, ordinal: int, form: str) -> list[str]:
    """Hash a Dolby Vision enhancement layer as NAL units, without decoding it."""

    return [sys.executable, "-m", "bdencode.dovi_layers", str(path), str(ordinal), form]


def parse_dovi_record(report: str) -> dict[str, int] | None:
    """Profile and layer flags from ``dovi_probe_command``; None without a record."""

    try:
        streams = json.loads(report).get("streams") or []
    except (AttributeError, ValueError):
        return None
    for stream in streams:
        for item in stream.get("side_data_list") or []:
            if "dv_profile" in item:
                return {
                    key: int(item.get(key, 0))
                    for key in ("dv_profile", "rpu_present_flag", "el_present_flag", "bl_present_flag")
                }
    return None


def hevc_tier(path: object, *, read_bytes: int = 4 * 1024 * 1024) -> str | None:
    """``High`` or ``Main`` from the first SPS of a raw HEVC stream, as BDInfo prints it."""

    with open(str(path), "rb") as handle:
        head = handle.read(read_bytes)
    position = 0
    while (position := head.find(b"\x00\x00\x01", position)) >= 0:
        nal = position + 3
        if nal + 4 > len(head):
            return None
        if (head[nal] >> 1) & 0x3F == 33:
            # NAL header (2), VPS id / sub-layers / nesting (1), then
            # general_profile_space (2 bits), general_tier_flag (1 bit).
            return "High" if head[nal + 3] & 0x20 else "Main"
        position = nal
    return None


_MAX_LUMINANCE = re.compile(r"L\((?P<maximum>\d+),\s*\d+\)")


def mastering_nits(mastering_display: str | None) -> int | None:
    """The mastering peak of an x265-style ``...L(10000000,1)`` string."""

    match = _MAX_LUMINANCE.search(mastering_display or "")
    return round(int(match["maximum"]) / 10000) if match else None


def dynamic_range(video: VideoProperties) -> frozenset[str]:
    """What the untouched video is: any of SDR, HDR, HDR10+, DV, HLG."""

    transfer = (video.color_transfer or "").casefold()
    values: set[str] = set()
    if video.hdr10 or transfer == "smpte2084":
        values.add("HDR")
    elif transfer in {"arib-std-b67", "hlg"}:
        values.add("HLG")
    if video.hdr10_plus:
        values.add("HDR10+")
    if video.dolby_vision:
        values.add("DV")
    return frozenset(values or {"SDR"})


def default_duration(frame_rate: str | None, field_order: str | None) -> str | None:
    """mkvmerge's frame duration for a raw progressive elementary stream."""

    if not frame_rate:
        return None
    if (field_order or "progressive").casefold() not in {"progressive", "unknown", ""}:
        return None
    rate = Fraction(frame_rate)
    return f"{rate.numerator}/{rate.denominator}p"


def tags_xml(*, imdb: str | None, tmdb: str | None, tvdb: str | None = None) -> str | None:
    """The guide's global tags (IMDB/TMDB/TVDB), or None when none is known."""

    values = [("IMDB", imdb), ("TMDB", tmdb), ("TVDB", tvdb)]
    present = [(name, value) for name, value in values if value]
    if not present:
        return None
    target = "70" if tmdb and tmdb.startswith("tv/") else "50"
    simple = "".join(
        f"<Simple><Name>{name}</Name><String>{value}</String></Simple>"
        for name, value in present
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE Tags SYSTEM "matroskatags.dtd">\n'
        f"<Tags><Tag><Targets><TargetTypeValue>{target}</TargetTypeValue></Targets>"
        f"{simple}</Tag></Tags>\n"
    )


def stream_probe_command(path: object, *, ffprobe: str = "ffprobe") -> list[str]:
    """The first stream of a demuxed file: codec, profile, level, rate, bits."""

    return [
        ffprobe,
        "-hide_banner",
        "-v",
        "error",
        "-select_streams",
        "0",
        "-show_entries",
        "stream=codec_name,profile,level,width,height,sample_rate,channels,"
        "bits_per_raw_sample,bits_per_sample,sample_fmt",
        "-of",
        "json",
        str(path),
    ]


def decoded_md5_command(
    path: object,
    stream: str,
    *,
    input_args: Sequence[str] = (),
    ffmpeg: str = "ffmpeg",
    end_sample: int | None = None,
) -> list[str]:
    """MD5 of one stream's decoded content (``v:0``, ``a:2``).

    Video decodes to its native pixel format; audio to 32-bit PCM, so a
    16-bit FLAC made from zero-padded 24-bit LPCM still hashes the same
    samples.
    """

    kind = stream.split(":", 1)[0]
    if kind not in {"v", "a"}:
        raise RemuxError("only video and audio decode to content", code="remux_decode")
    # A multi-clip title's audio timestamps step back at the joins, and -xerror
    # stops on that; only the samples count here, so they are numbered afresh.
    # ``end_sample`` hashes only the first samples (an audio track's part
    # that the reference also has).
    trim = f",atrim=end_sample={int(end_sample)}" if end_sample is not None else ""
    codec = ["-af", f"asetpts=N/SR/TB{trim}", "-c:a", "pcm_s32le"] if kind == "a" else []
    return [
        ffmpeg,
        "-hide_banner",
        "-nostdin",
        "-v",
        "error",
        "-xerror",
        *input_args,
        "-i",
        str(path),
        "-map",
        f"0:{stream}",
        *codec,
        "-f",
        "md5",
        "-",
    ]


_MD5_LINE = re.compile(r"^MD5=(?P<digest>[0-9a-f]{32})\s*$", re.MULTILINE)

# eac3to writes a clip's audio to the clip's end, libbluray (the reference)
# stops at the playlist's out point: the remux's track may run on for a moment
# after the picture, as digital silence.  Up to this much is accepted when every
# sample before it equals the disc's.
SILENT_TAIL_MAX_SECONDS = 2
# volumedetect reports all-zero samples as -91.0 dB; a 16-bit LSB is -90.3 dB.
SILENT_TAIL_MAX_DB = -90.0


def audio_level_command(
    path: object, stream: str, *, start_sample: int | None = None, ffmpeg: str = "ffmpeg"
) -> list[str]:
    """Decode one audio stream (from ``start_sample``) and report its sample
    count and peak with volumedetect (on the standard error, at info level)."""

    trim = f",atrim=start_sample={int(start_sample)}" if start_sample is not None else ""
    return [
        ffmpeg, "-hide_banner", "-nostdin", "-v", "info",
        "-i", str(path),
        "-map", f"0:{stream}",
        "-af", f"asetpts=N/SR/TB{trim},volumedetect",
        "-f", "null", "-",
    ]


_VOLUMEDETECT_SAMPLES = re.compile(r"n_samples:\s*(?P<count>\d+)")
_VOLUMEDETECT_MAX = re.compile(r"max_volume:\s*(?P<db>-?(?:\d+(?:\.\d+)?|inf))\s*dB")


def parse_audio_level(text: str) -> tuple[int, float | None]:
    """(samples over all channels, peak in dB or None when nothing was decoded)."""

    counts = _VOLUMEDETECT_SAMPLES.findall(text)
    peaks = _VOLUMEDETECT_MAX.findall(text)
    count = int(counts[-1]) if counts else 0
    peak = float(peaks[-1]) if peaks and peaks[-1] not in {"-inf", "inf"} else None
    return count, peak


def judge_silent_tail(
    *,
    reference_md5: str,
    shared_md5: str,
    tail_samples: int,
    tail_peak_db: float | None,
    sample_rate: int,
) -> tuple[bool, str]:
    """Whether a track that hashes differently is the disc's sound plus digital
    silence after the reference's end, and how the report says it."""

    if shared_md5 != reference_md5:
        return False, "decodes differently from the disc"
    seconds = tail_samples / sample_rate if sample_rate else 0.0
    if tail_samples <= 0:
        return False, "decodes differently from the disc (no extra samples to explain it)"
    if seconds > SILENT_TAIL_MAX_SECONDS:
        return False, f"equals the disc's but runs on {seconds:.3f} s after it"
    if tail_peak_db is not None and tail_peak_db > SILENT_TAIL_MAX_DB:
        return False, (
            f"equals the disc's but runs on {seconds:.3f} s after it with sound "
            f"(peak {tail_peak_db:.1f} dB)"
        )
    return True, (
        f"every decoded sample equals the disc's; then {seconds * 1000:.0f} ms of digital "
        "silence past the playlist's end (eac3to keeps the clip's audio to its end)"
    )


def parse_md5(text: str) -> str:
    match = _MD5_LINE.search(text)
    if match is None:
        raise RemuxError("FFmpeg printed no MD5", code="remux_decode")
    return match["digest"]


IMDB_ID = re.compile(r"^tt\d{7,9}$")
TMDB_ID = re.compile(r"^(?:movie|tv)/\d{1,9}$")


__all__ = [
    "AUDIO_NAMES",
    "CHAPTERS_NAME",
    "DEMUX_EXTENSIONS",
    "DemuxOutput",
    "EAC3TO_EXE",
    "Eac3toListing",
    "Eac3toTrack",
    "IMDB_ID",
    "LOG_NAME",
    "LOSSLESS_FAMILIES",
    "LogFinding",
    "REMOVE_DIALNORM_FAMILIES",
    "RemuxError",
    "RemuxTrack",
    "TMDB_ID",
    "VIDEO_NAME_CODECS",
    "audio_track_name",
    "clip_presentation",
    "container_title",
    "default_duration",
    "dovi_mux_command",
    "dovi_probe_command",
    "dynamic_range",
    "demux_outputs",
    "decoded_md5_command",
    "eac3to_demux_command",
    "embedded_core_parent",
    "eac3to_clips_listing_command",
    "eac3to_listing_command",
    "eac3to_progress",
    "fps_text",
    "hevc_tier",
    "kbps",
    "log_findings",
    "logged_frame_count",
    "mastering_nits",
    "match_tracks",
    "parse_listing",
    "parse_dovi_record",
    "parse_md5",
    "public_log",
    "remux_mkvmerge_command",
    "resolution_text",
    "stream_family",
    "stream_probe_command",
    "tags_xml",
    "timestamp_text",
    "track_family",
    "video_extract_command",
    "video_track_name",
    "whole_clips",
]


def timestamp_text(seconds: Decimal) -> str:
    """``01:23:45.678``."""

    millis = int((seconds * 1000).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    hours, rest = divmod(millis, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    return f"{hours:02d}:{minutes:02d}:{rest // 1000:02d}.{rest % 1000:03d}"
