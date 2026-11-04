"""Moving an SRT made for the external source onto the title's timeline."""

from __future__ import annotations

import re
from dataclasses import dataclass
from fractions import Fraction
from typing import Any, Mapping, Sequence

_TIME = re.compile(r"(\d+):(\d\d):(\d\d)[,.](\d{1,3})")
_LINE = re.compile(rf"^\s*{_TIME.pattern}\s*-->\s*{_TIME.pattern}")


class SubtitleError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Cue:
    start_ms: int
    end_ms: int
    text: str


def decode_text(data: bytes) -> str:
    """UTF-8 when it is valid; older Hungarian subtitle files are Windows-1250."""

    for encoding in ("utf-8-sig", "cp1250"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise SubtitleError("the subtitle file has an unknown text encoding")


def _ms(hours: str, minutes: str, seconds: str, fraction: str) -> int:
    return (
        int(hours) * 3_600_000
        + int(minutes) * 60_000
        + int(seconds) * 1000
        + int(fraction.ljust(3, "0"))
    )


def parse_srt(text: str) -> list[Cue]:
    cues: list[Cue] = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n").replace("\r", "\n")):
        lines = block.strip("\n").split("\n")
        for index, line in enumerate(lines):
            match = _LINE.match(line)
            if match:
                groups = match.groups()
                start = _ms(*groups[:4])
                end = _ms(*groups[4:])
                body = "\n".join(lines[index + 1 :]).strip()
                if end > start and body:
                    cues.append(Cue(start, end, body))
                break
    if not cues:
        raise SubtitleError("the file holds no SRT cue")
    return cues


def _stamp(ms: int) -> str:
    hours, rest = divmod(ms, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    seconds, millis = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def render_srt(cues: Sequence[Cue]) -> str:
    return "\n".join(
        f"{number}\n{_stamp(cue.start_ms)} --> {_stamp(cue.end_ms)}\n{cue.text}\n"
        for number, cue in enumerate(cues, 1)
    )


def retime(
    cues: Sequence[Cue],
    segments: Sequence[Mapping[str, Any]],
    *,
    target_fps: Fraction,
    donor_grid_fps: Fraction,
) -> tuple[list[Cue], dict[str, int]]:
    """Each cue follows its picture.  ``donor_grid_fps`` is how many map frames the
    source shows per second of its own time: its frame rate when frame locked, the
    title's when time locked.

    A cue starting in a part the title lacks starts at the next part it has; one
    entirely in such a part is dropped and counted.
    """

    spans = [
        (int(item["target_start"]) + int(item["offset"]), int(item["target_end"]) + int(item["offset"]), int(item["offset"]))
        for item in segments
    ]
    spans.sort()

    def to_title(position: Fraction, offset: int) -> int:
        return int((position - offset) / target_fps * 1000 + Fraction(1, 2))

    moved: list[Cue] = []
    dropped = clipped = 0
    for cue in cues:
        start = Fraction(cue.start_ms, 1000) * donor_grid_fps
        end = Fraction(cue.end_ms, 1000) * donor_grid_fps
        touching = [span for span in spans if span[0] < end and start < span[1]]
        if not touching:
            dropped += 1
            continue
        first = touching[0]
        last = touching[-1]
        new_start = to_title(max(start, Fraction(first[0])), first[2])
        new_end = to_title(min(end, Fraction(last[1])), last[2])
        if start < first[0] or end > last[1] or len(touching) > 1:
            clipped += 1
        if new_end <= new_start:
            dropped += 1
            continue
        moved.append(Cue(new_start, new_end, cue.text))
    moved.sort(key=lambda item: item.start_ms)
    return moved, {"kept": len(moved), "dropped": dropped, "clipped": clipped}
