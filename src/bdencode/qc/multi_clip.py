"""A multi-clip title checked against its clips, not against the reference.

FFmpeg's reference of a multi-clip playlist has the disc's packets but not its
timeline: it restamps them at each join, so everything after a join sits early
(God Forgives, I Don't: 53.5 ms by the last clip, while a correct remux was
measured 54 ms late against it).  Where a sound belongs follows from the
playlist alone, ``title time = time before the clip + (PTS - clip's in time)``,
so each clip is decoded at its own PTS and the remux at that title time.

eac3to removes overlapping audio by whole frames, which leaves two more
differences from a single-clip title:

* the decoded samples stop being equal: a decoder needs up to six DTS frames to
  settle after a cut, though no bit of what remains has changed.  So the
  bitstream packets are compared: the remux must be the reference minus whole
  packets, removed only at the joins;
* a track can be up to one frame away from where it belongs, as frames are all
  it can lose.  That frame is the tolerance.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping, Sequence

from ..media.bluray import PlaylistSegment
from . import av_sync

# How far from the edges of a clip a window stays: its sound must be the clip's
# own even with the largest lag the search looks for.
_EDGE_SECONDS = Decimal(1)
_MIN_WINDOW_SECONDS = Decimal(3)
_WINDOW_FRACTIONS = (Decimal("0.25"), Decimal("0.75"))

# Tolerance: one frame of the codecs eac3to can cut.  TrueHD and PCM stay at the
# measurement's own tolerance: eac3to cannot cut a TrueHD bitstream, and no PCM
# title has been measured.
_FRAME_MS = {
    "DD": Decimal("32"),
    "DDP": Decimal("32"),
    "DTS": Decimal("10.667"),
    "DTSHDHRA": Decimal("10.667"),
    "DTSHDMA": Decimal("10.667"),
    "DTSX": Decimal("10.667"),
}

# Where a removed packet may be: the reference's time of it, which is off by
# what FFmpeg restamped, against the join.
JOIN_SLACK_SECONDS = av_sync.MAX_LAG_SECONDS
_RESYNC_PACKETS = 4
_MAX_REMOVED_PACKETS = 64


def tolerance_ms(family: str) -> Decimal:
    return _FRAME_MS.get(family, av_sync.TOLERANCE_MS)


@dataclass(frozen=True, slots=True)
class ClipWindow:
    clip_id: str
    clip_start_seconds: Decimal  # the clip's own PTS
    title_start_seconds: Decimal
    seconds: Decimal


def _bounds(segment: PlaylistSegment) -> tuple[Decimal, Decimal]:
    return Decimal(str(segment.in_time_seconds)), Decimal(str(segment.out_time_seconds))


def clip_windows(segments: Sequence[PlaylistSegment]) -> tuple[ClipWindow, ...]:
    """Windows inside each clip: the lag changes only at a join, so every clip counts.

    A clip too short for a window is covered by the next one, as the lag it
    adds stays in the rest of the track.
    """

    windows: list[ClipWindow] = []
    title = Decimal(0)
    for segment in segments:
        in_time, out_time = _bounds(segment)
        duration = out_time - in_time
        seconds = min(av_sync.WINDOW_SECONDS, duration - 2 * _EDGE_SECONDS)
        if seconds >= _MIN_WINDOW_SECONDS:
            latest = duration - _EDGE_SECONDS - seconds
            offsets = sorted(
                {
                    min(latest, max(_EDGE_SECONDS, (duration * fraction - seconds / 2).quantize(Decimal("0.001"))))
                    for fraction in _WINDOW_FRACTIONS
                }
            )
            windows.extend(
                ClipWindow(segment.clip_id, in_time + offset, title + offset, seconds)
                for offset in offsets
            )
        title += duration
    return tuple(windows)


def join_seconds(segments: Sequence[PlaylistSegment]) -> tuple[Decimal, ...]:
    """Title time of each join."""

    joins: list[Decimal] = []
    title = Decimal(0)
    for segment in segments[:-1]:
        in_time, out_time = _bounds(segment)
        title += out_time - in_time
        joins.append(title)
    return tuple(joins)


def clip_streams_command(path: object, *, ffprobe: str = "ffprobe") -> list[str]:
    return [
        ffprobe,
        "-v",
        "error",
        "-show_entries",
        "stream=id,codec_name,codec_type",
        "-of",
        "json",
        str(path),
    ]


def clip_ordinal(
    document: Mapping[str, Any], kind: str, pid: int | None, codec: str
) -> int | None:
    """A stream's ordinal among the clip's streams of its kind; None if it has none.

    A TrueHD PID holds two streams (TrueHD and its AC-3), so the codec decides;
    the PID alone is enough when it holds one, however FFmpeg names its codec.
    """

    ordinal = 0
    same_pid: list[tuple[int, str]] = []
    for stream in document.get("streams", ()):
        if stream.get("codec_type") != kind:
            continue
        try:
            stream_pid = int(str(stream.get("id")), 16)
        except ValueError:
            stream_pid = None
        if stream_pid == pid:
            same_pid.append((ordinal, str(stream.get("codec_name"))))
        ordinal += 1
    for found, name in same_pid:
        if name == codec:
            return found
    return same_pid[0][0] if len(same_pid) == 1 else None


def packet_hash_command(path: object, stream: str, *, ffmpeg: str = "ffmpeg") -> list[str]:
    """One hash line per bitstream packet of a stream (``a:2``)."""

    return [
        ffmpeg,
        "-hide_banner",
        "-nostdin",
        "-v",
        "error",
        "-i",
        str(path),
        "-map",
        f"0:{stream}",
        "-c",
        "copy",
        "-f",
        "framemd5",
        "-",
    ]


@dataclass(frozen=True, slots=True)
class Packets:
    time_base: Decimal
    pts: tuple[int, ...]
    contents: tuple[tuple[str, str], ...]  # size, hash

    def seconds(self, index: int) -> Decimal:
        return self.pts[index] * self.time_base


def parse_packets(text: str) -> Packets:
    """FFmpeg's ``framemd5``: ``stream, dts, pts, duration, size, hash``."""

    time_base = Decimal(1)
    pts: list[int] = []
    contents: list[tuple[str, str]] = []
    for line in text.splitlines():
        if line.startswith("#tb"):
            numerator, denominator = line.rsplit(":", 1)[1].strip().split("/")
            time_base = Decimal(numerator) / Decimal(denominator)
        elif line and not line.startswith("#"):
            fields = [item.strip() for item in line.split(",")]
            pts.append(int(fields[2]))
            contents.append((fields[4], fields[5]))
    return Packets(time_base, tuple(pts), tuple(contents))


@dataclass(frozen=True, slots=True)
class PacketComparison:
    packets: int
    removed: tuple[dict[str, str | int], ...]
    problem: str | None

    @property
    def passed(self) -> bool:
        return self.problem is None


def compare_packets(
    reference: Packets, final: Packets, joins: Sequence[Decimal]
) -> PacketComparison:
    """Is the remux the reference minus whole packets, removed only at the joins?"""

    ours, theirs = reference.contents, final.contents
    removed: list[dict[str, str | int]] = []

    def problem(text: str) -> PacketComparison:
        return PacketComparison(len(theirs), tuple(removed), text)

    def cut(start: int, count: int) -> bool:
        # Equal packets (silence) leave open which of them went: any may be at the join.
        earliest = start
        while earliest > 0 and ours[earliest - 1] == ours[earliest + count - 1]:
            earliest -= 1
        low = reference.seconds(earliest) - JOIN_SLACK_SECONDS
        high = reference.seconds(start + count - 1) + JOIN_SLACK_SECONDS
        removed.append({"at_seconds": str(reference.seconds(start)), "packets": count})
        return any(low <= join <= high for join in joins)

    i = j = 0
    while j < len(theirs):
        if i < len(ours) and ours[i] == theirs[j]:
            i += 1
            j += 1
            continue
        wanted = theirs[j : j + _RESYNC_PACKETS]
        count = next(
            (
                size
                for size in range(1, _MAX_REMOVED_PACKETS + 1)
                if ours[i + size : i + size + len(wanted)] == wanted
            ),
            None,
        )
        if count is None:
            return problem(f"packet {j} of the remux is not the disc's")
        if not cut(i, count):
            return problem(
                f"{count} packet(s) are missing at {reference.seconds(i)} s, away from every clip join"
            )
        i += count
    if i < len(ours):
        return problem(f"the remux ends {len(ours) - i} packet(s) before the disc's track")
    if not removed:
        return problem("the packets are equal, yet they decode differently")
    return PacketComparison(len(theirs), tuple(removed), None)


__all__ = [
    "ClipWindow",
    "JOIN_SLACK_SECONDS",
    "PacketComparison",
    "Packets",
    "clip_ordinal",
    "clip_streams_command",
    "clip_windows",
    "compare_packets",
    "join_seconds",
    "packet_hash_command",
    "parse_packets",
    "tolerance_ms",
]
