"""Whether the final MKV really holds the fitted track where the map says.

The map itself is checked by the operator and by the picture similarity; this
proves that what reached the file is the right sound at the right place.  It
decodes moments of the final MKV and finds their lag against the stretched source
at the position the map gives, in the middle of each piece and on both sides of
every splice.
"""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..qc.av_sync import MIN_CORRELATION, MIN_RMS, SYNC_RATE, TOLERANCE_MS, measure_lag
from .render import SAMPLE_RATE, sample_at, samples_per_frame

WINDOW_SECONDS = 6
MAX_WINDOWS = 80


def window_frames(
    segments: Sequence[Mapping[str, Any]], target_fps: Fraction
) -> list[tuple[int, int]]:
    """``(title frame, offset)``, windows lying wholly inside one piece."""

    length = int(WINDOW_SECONDS * target_fps) + 1
    margin = int(target_fps) // 2
    chosen: list[tuple[int, int]] = []
    for segment in segments:
        start = int(segment["target_start"])
        end = int(segment["target_end"])
        offset = int(segment["offset"])
        if end - start < length + 2 * margin:
            continue
        for frame in (start + margin, (start + end - length) // 2, end - length - margin):
            chosen.append((frame, offset))
    chosen = sorted(set(chosen))
    if len(chosen) > MAX_WINDOWS:
        step = len(chosen) / MAX_WINDOWS
        chosen = [chosen[int(index * step)] for index in range(MAX_WINDOWS)]
    return chosen


def final_window_command(
    path: Path, ordinal: int, start_seconds: float, output: Path, *, ffmpeg: str = "ffmpeg"
) -> list[str]:
    return [
        ffmpeg, "-hide_banner", "-nostdin", "-v", "error",
        "-seek_timestamp", "1", "-ss", f"{start_seconds:.6f}",
        "-i", str(path),
        "-map", f"0:a:{ordinal}",
        "-t", str(WINDOW_SECONDS),
        "-ac", "1", "-ar", str(SYNC_RATE),
        "-f", "f32le", "-y", str(output),
    ]


def expected_window(
    stretched: Any,
    channels: int,
    *,
    frame: int,
    offset: int,
    target_fps: Fraction,
    audio_offset_samples: int = 0,
    scale: float = 1.0,
) -> Any:
    """The same moment of the stretched source, as mono."""

    import numpy as np

    per_frame = samples_per_frame(target_fps)
    start = int(round((sample_at(frame + offset, per_frame) - audio_offset_samples) * scale))
    count = WINDOW_SECONDS * SAMPLE_RATE
    if start < 0:
        return np.zeros(0, dtype=np.float64)
    block = np.asarray(stretched[start * channels : (start + count) * channels], dtype=np.float64)
    usable = len(block) // channels
    return block[: usable * channels].reshape(usable, channels).mean(axis=1)


def judge(windows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Passed: enough windows could be measured and none of them is off."""

    conclusive = [item for item in windows if item["conclusive"]]
    off = [item for item in conclusive if abs(float(item["lag_ms"])) > float(TOLERANCE_MS)]
    if off:
        status = "out_of_sync"
    elif len(conclusive) >= max(3, len(windows) // 2):
        status = "passed"
    else:
        status = "inconclusive"
    return {
        "status": status,
        "tolerance_ms": str(TOLERANCE_MS),
        "windows_total": len(windows),
        "windows_conclusive": len(conclusive),
        "windows_off": len(off),
        "windows": list(windows),
    }


def measure_window(final: Any, expected: Any, frame: int, target_fps: Fraction) -> dict[str, Any]:
    import numpy as np

    lag, correlation, rms = measure_lag(np.asarray(expected), np.asarray(final))
    conclusive = rms >= MIN_RMS and correlation >= MIN_CORRELATION
    return {
        "title_seconds": round(float(Fraction(frame) / target_fps), 3),
        "lag_ms": f"{lag * 1000 / SYNC_RATE:.3f}",
        "correlation": round(correlation, 4),
        "conclusive": bool(conclusive),
    }
