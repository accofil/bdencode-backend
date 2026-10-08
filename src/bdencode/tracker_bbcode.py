"""Tracker-ready BBCode: Aither's comparison block and nCore's description parts.

Aither's Video Comparisons Guide asks for at least ten source/encode pairs of
the same frame type (B-frames preferred, P acceptable, I-frames avoided) in a
``[comparison=Source, Encode]`` block with space-separated PNG URLs; frame-info
labels on comps are normal.  Its screenshot rules ask for 3–9 *clean* PNGs at
the MediaInfo resolution, full-linked with ``[img=350]`` inside ``[center]``;
personal encodes also need the x264/x265 log.  nCore wants exactly three
screenshots at the encode's resolution (``[imgw]`` above 640×480) and, for a
quality trump, comparison links under the usual centred header.

Comparisons use the uploaded labelled pairs; screenshots use the clean frames
the comparison stage copies for tracker jobs.  HDR titles use their SDR views,
which browsers show correctly.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Sequence

COMPARISON_MINIMUM = 10
COMPARISON_MAXIMUM = 12
SCREENSHOT_COUNTS = {"aither": 6, "ncore": 3}

# x264/x265 log lines worth publishing: the encoder's own [info]/[warning]
# lines (settings at the start, frame statistics at the end) and the summary.
_ENCODER_LINE = re.compile(
    r"^(?:x26[45] \[(?:info|warning)\]: .*"
    r"|\[libx26[45] @ [^\]]+\] .*"
    r"|encoded \d+ frames in .*)$"
)
_LIBX_PREFIX = re.compile(r"^\[(libx26[45]) @ [^\]]+\] ")


def comparison_pairs(pairs: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """B pairs first, P pairs only to reach ten; never I-frames; in time order."""

    b_frames = [item for item in pairs if item.get("category") == "B"]
    p_frames = [item for item in pairs if item.get("category") == "P"]
    chosen = b_frames[:COMPARISON_MAXIMUM]
    if len(chosen) < COMPARISON_MINIMUM:
        chosen += p_frames[: COMPARISON_MINIMUM - len(chosen)]
    return sorted(chosen, key=lambda item: int(item.get("presentation_index") or 0))


def _spread(items: Sequence[Any], count: int) -> list[Any]:
    if len(items) <= count:
        return list(items)
    step = (len(items) - 1) / (count - 1) if count > 1 else 0
    return [items[round(index * step)] for index in range(count)]


def screenshot_pair_numbers(categories: Sequence[str], profile: str) -> set[int]:
    """1-based pair numbers whose clean encode frame becomes a screenshot.

    B pairs spread over the runtime (P pairs only when B pairs run out); none
    without a tracker profile.
    """

    wanted = SCREENSHOT_COUNTS.get(profile, 0)
    if not wanted:
        return set()
    numbered = list(enumerate(categories, start=1))
    b_pairs = [number for number, category in numbered if category == "B"]
    p_pairs = [number for number, category in numbered if category == "P"]
    chosen = _spread(b_pairs, wanted)
    if len(chosen) < wanted:
        chosen += _spread(p_pairs, wanted - len(chosen))
    return set(chosen)


def encoder_summary(log_text: str) -> str:
    """The encoder's settings and statistics lines from an FFmpeg encode log."""

    lines = []
    for raw in log_text.splitlines():
        line = raw.strip()
        if _ENCODER_LINE.match(line):
            lines.append(_LIBX_PREFIX.sub(lambda match: f"{match.group(1)}: ", line))
    return "\n".join(lines)


def _image(
    pair: Mapping[str, Any], role: str, uploaded: Mapping[str, Mapping[str, Any]]
) -> Mapping[str, Any] | None:
    # SDR view first: a tone-mapped HDR picture is what a browser can show.
    for key in (f"{role}_sdr_png", f"{role}_png"):
        name = pair.get(key)
        if isinstance(name, str) and name in uploaded:
            return uploaded[name]
    return None


def _timestamp(value: Any) -> str:
    try:
        seconds = int(Decimal(str(value)))
    except (InvalidOperation, ValueError):
        return "?"
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def _complete(
    pairs: Sequence[Mapping[str, Any]], uploaded: Mapping[str, Mapping[str, Any]]
) -> list[tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]]]:
    rows = []
    for pair in comparison_pairs(pairs):
        reference = _image(pair, "reference", uploaded)
        encode = _image(pair, "encode", uploaded)
        if reference is not None and encode is not None:
            rows.append((pair, reference, encode))
    return rows


def _screenshots(
    pairs: Sequence[Mapping[str, Any]], uploaded: Mapping[str, Mapping[str, Any]]
) -> list[Mapping[str, Any]]:
    ordered = sorted(pairs, key=lambda item: int(item.get("presentation_index") or 0))
    return [
        uploaded[name]
        for pair in ordered
        if isinstance(name := pair.get("screenshot_png"), str) and name in uploaded
    ]


def aither_bbcode(
    pairs: Sequence[Mapping[str, Any]],
    uploaded: Mapping[str, Mapping[str, Any]],
    *,
    encoder_log: str = "",
    codec: str = "x265",
) -> list[str]:
    rows = _complete(pairs, uploaded)
    lines: list[str] = []
    screenshots = _screenshots(pairs, uploaded)
    if screenshots:
        lines.extend(("", "[b]Aither — screenshots[/b]", "[center]"))
        lines.extend(
            f"[url={item['viewer_url']}][img=350]{item['image_url']}[/img][/url]"
            for item in screenshots
        )
        lines.append("[/center]")
    if rows:
        urls = " ".join(
            f"{reference['image_url']} {encode['image_url']}" for _pair, reference, encode in rows
        )
        lines.extend(
            (
                "",
                "[b]Aither — comparison (same frame type, B preferred)[/b]",
                f"[comparison=Source, Encode]{urls}[/comparison]",
            )
        )
        if len(rows) < COMPARISON_MINIMUM:
            lines.append(
                f"[i]Only {len(rows)} B/P pairs were uploaded; Aither asks for at least "
                f"{COMPARISON_MINIMUM}.[/i]"
            )
    if encoder_log:
        lines.extend(("", f"[spoiler={codec} log][code]", encoder_log, "[/code][/spoiler]"))
    return lines


def ncore_bbcode(
    pairs: Sequence[Mapping[str, Any]], uploaded: Mapping[str, Mapping[str, Any]]
) -> list[str]:
    rows = _complete(pairs, uploaded)
    lines: list[str] = []
    screenshots = _screenshots(pairs, uploaded)
    if screenshots:
        lines.extend(("", "[b]nCore — képek (pontosan 3, az encode felbontásában)[/b]"))
        lines.extend(f"[imgw]{item['image_url']}[/imgw]" for item in screenshots)
    if rows:
        lines.extend(
            (
                "",
                "[b]nCore — összehasonlítás (cseréhez)[/b]",
                "[center][size=12pt][highlight]Forrás vs. Encode[/highlight][/size]",
                "",
            )
        )
        for number, (pair, reference, encode) in enumerate(rows, start=1):
            lines.append(
                f"[url={reference['viewer_url']}]Forrás {number:02d}[/url] · "
                f"[url={encode['viewer_url']}]Encode {number:02d}[/url] "
                f"({pair.get('category')}-frame, {_timestamp(pair.get('encoded_pts_seconds'))})"
            )
        lines.append("[/center]")
    return lines


def tracker_bbcode(
    profile: str,
    pairs: Sequence[Mapping[str, Any]],
    uploaded: Mapping[str, Mapping[str, Any]],
    *,
    encoder_log: str = "",
    codec: str = "x265",
) -> list[str]:
    if profile == "aither":
        return aither_bbcode(pairs, uploaded, encoder_log=encoder_log, codec=codec)
    if profile == "ncore":
        return ncore_bbcode(pairs, uploaded)
    return []


__all__ = [
    "COMPARISON_MAXIMUM",
    "COMPARISON_MINIMUM",
    "SCREENSHOT_COUNTS",
    "aither_bbcode",
    "comparison_pairs",
    "encoder_summary",
    "ncore_bbcode",
    "screenshot_pair_numbers",
    "tracker_bbcode",
]
