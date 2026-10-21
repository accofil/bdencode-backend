"""The video encoder's own log of a job, cleaned for reading and sharing.

``logs/video-encode.log`` is ffmpeg's stderr while it feeds x264/x265.  Most of
it is ``-progress`` noise (``frame=``, ``fps=``, ``out_time=`` ... every two
seconds: thousands of lines).  What matters is the encoder's banner and options
at the start and, at the end, the statistics: frame types with their average
QP and size, macroblock statistics and the final bitrate.

This module keeps those lines, drops the noise and masks host paths, secrets
and identifiers with :func:`bdencode.logs.sanitize_text`.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .logs import sanitize_text

LOG_NAME = "video-encode.log"
# Beyond this the cleaned log is cut (a 4K x265 log with many warnings).
MAX_CLEAN_BYTES = 400_000

_PROGRESS_KEY = re.compile(
    r"^(frame|fps|stream_\d+_\d+_q|bitrate|total_size|out_time(?:_us|_ms)?|"
    r"dup_frames|drop_frames|speed|progress)=\s*\S*$"
)
# ffmpeg's in-place statistics line; only the last one (the final totals) is kept.
_STATS_LINE = re.compile(r"^frame=\s*\d+\s+fps=")
_VIDEO_TOTALS = re.compile(r"^video:\s*\d")
_OPTIONS = re.compile(r"options:\s*(.+)$")


def clean_encoder_log(raw: str) -> str:
    """The encoder-relevant lines of ``raw``: no progress noise, one stats line."""

    kept: list[str] = []
    last_stats: str | None = None
    for line in raw.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        stripped = line.rstrip()
        if _PROGRESS_KEY.match(stripped):
            continue
        if _STATS_LINE.match(stripped):
            last_stats = stripped
            continue
        if not stripped and (not kept or not kept[-1]):
            continue
        kept.append(stripped)
    if last_stats is not None:
        # Right before the "video:" totals, where ffmpeg prints it.
        position = next(
            (index for index, line in enumerate(kept) if _VIDEO_TOTALS.match(line)),
            len(kept),
        )
        kept.insert(position, last_stats)
    return "\n".join(kept).strip() + "\n"


def _encoder_name(text: str) -> str | None:
    if "libx265" in text or "x265 [info]" in text:
        return "x265"
    if "libx264" in text:
        return "x264"
    return None


def _summary(lines: list[str]) -> list[str]:
    """The closing statistics: from the ``video:`` totals on, or the last lines."""

    start = next(
        (index for index in range(len(lines) - 1, -1, -1) if _VIDEO_TOTALS.match(lines[index])),
        None,
    )
    if start is None:
        return []
    # The stats line sits just before the totals.
    if start > 0 and _STATS_LINE.match(lines[start - 1]):
        start -= 1
    return lines[start:]


def read_encoder_log(job_root: Path) -> dict[str, Any]:
    """The cleaned log of one job as the API returns it."""

    path = job_root / "logs" / LOG_NAME
    try:
        if path.is_symlink() or not path.is_file():
            return {"available": False}
        raw_bytes = path.stat().st_size
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {"available": False}
    cleaned = sanitize_text(clean_encoder_log(raw), replacements={str(job_root): "<job>"})
    truncated = len(cleaned.encode("utf-8")) > MAX_CLEAN_BYTES
    if truncated:
        cleaned = cleaned.encode("utf-8")[:MAX_CLEAN_BYTES].decode("utf-8", errors="ignore")
    lines = cleaned.splitlines()
    options = next(
        (match.group(1) for line in lines if (match := _OPTIONS.search(line))), None
    )
    summary = _summary(lines)
    return {
        "available": True,
        "encoder": _encoder_name(cleaned),
        "finished": bool(summary),
        "options": options,
        "summary": summary,
        "text": cleaned,
        "line_count": len(lines),
        "raw_bytes": raw_bytes,
        "truncated": truncated,
        "updated_at": path.stat().st_mtime,
    }


__all__ = ["LOG_NAME", "clean_encoder_log", "read_encoder_log"]
