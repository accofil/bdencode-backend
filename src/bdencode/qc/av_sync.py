"""Where each final audio track's sound actually is, measured against the source.

Every other audio check compares the final MKV with the plan: packet starts
against ``expected_start_seconds``, decoded frames against their own first
frame.  A wrong plan therefore passes them all.  This check is independent:
it decodes the same moments of the reference and of the final MKV (the final
at ``reference time - origin``) and finds the lag between the two sounds by
normalised cross-correlation.  It caught the AC-3/E-AC-3 encoder priming
(256 samples, 5.333 ms late) that nothing else saw.

The decode is mono at 48 kHz, so a downmixed or re-encoded track still
correlates with its source; one sample is 0.0208 ms.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Sequence

SYNC_RATE = 48_000
WINDOW_SECONDS = Decimal(20)
# A sync error is a few milliseconds; a lag search of a quarter second still
# catches a gross one (a dropped AC-3 frame is 32 ms) without false peaks.
MAX_LAG_SECONDS = Decimal("0.25")
# Matroska stores whole milliseconds and mkvmerge shifts by whole
# milliseconds: half a millisecond of rounding plus one of measurement.
TOLERANCE_MS = Decimal("1.5")
# Below these the window has too little sound to locate.
MIN_RMS = 10 ** (-50 / 20)
MIN_CORRELATION = 0.5
WINDOW_FRACTIONS = (Decimal("0.2"), Decimal("0.5"), Decimal("0.8"))


@dataclass(frozen=True, slots=True)
class SyncWindow:
    final_start_seconds: str
    reference_start_seconds: str
    lag_ms: str | None
    correlation: float | None
    conclusive: bool
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class SyncVerdict:
    status: str  # "passed", "out_of_sync" or "inconclusive"
    lag_ms: str | None
    windows: tuple[SyncWindow, ...]
    tolerance_ms: str = str(TOLERANCE_MS)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["windows"] = [asdict(window) for window in self.windows]
        return value


def window_starts(duration_seconds: Decimal) -> tuple[Decimal, ...]:
    """Final-timeline starts of the windows, inside the title and apart."""

    usable = duration_seconds - WINDOW_SECONDS - Decimal(10)
    if usable <= 0:
        return (Decimal(0),)
    starts = sorted({max(Decimal(5), (duration_seconds * f).quantize(Decimal("0.001"))) for f in WINDOW_FRACTIONS})
    return tuple(min(start, Decimal(5) + usable) for start in starts)


def sync_window_command(
    path: Path,
    audio_ordinal: int,
    start_seconds: Decimal,
    output: Path,
    *,
    input_args: Sequence[str] = (),
    ffmpeg: str = "ffmpeg",
) -> list[str]:
    """Decode one window to raw mono 48 kHz float samples.

    ``-ss`` before ``-i`` with FFmpeg's default accurate seek starts the output
    at exactly ``start_seconds`` of the input timeline, the same way for the
    reference and the final MKV.
    """

    if start_seconds < 0:
        raise ValueError("a sync window cannot start before zero")
    return [
        ffmpeg,
        "-hide_banner",
        "-nostdin",
        "-v",
        "error",
        "-ss",
        f"{start_seconds:.6f}",
        *input_args,
        "-i",
        str(path),
        "-map",
        f"0:a:{audio_ordinal}",
        "-t",
        f"{WINDOW_SECONDS:.3f}",
        "-ac",
        "1",
        "-ar",
        str(SYNC_RATE),
        "-f",
        "f32le",
        "-y",
        str(output),
    ]


def measure_lag(reference: Any, final: Any) -> tuple[int, float, float]:
    """``(lag in samples, correlation, rms)``; positive lag: the final is late."""

    import numpy as np

    n = min(len(reference), len(final))
    if n < SYNC_RATE:
        return 0, 0.0, 0.0
    a = np.asarray(reference[:n], dtype=np.float64)
    b = np.asarray(final[:n], dtype=np.float64)
    a -= a.mean()
    b -= b.mean()
    rms = float(min(np.sqrt(np.mean(a * a)), np.sqrt(np.mean(b * b))))
    norm = float(np.linalg.norm(a) * np.linalg.norm(b))
    if norm == 0.0:
        return 0, 0.0, rms
    size = 1 << (2 * n - 1).bit_length()
    corr = np.fft.irfft(np.fft.rfft(b, size) * np.conj(np.fft.rfft(a, size)), size)
    max_lag = int(MAX_LAG_SECONDS * SYNC_RATE)
    window = np.concatenate((corr[-max_lag:], corr[: max_lag + 1]))
    peak = int(np.argmax(window))
    return peak - max_lag, float(window[peak] / norm), rms


def read_samples(path: Path) -> Any:
    import numpy as np

    return np.fromfile(path, dtype="<f4")


def judge(windows: Sequence[SyncWindow]) -> SyncVerdict:
    conclusive = [window for window in windows if window.conclusive and window.lag_ms is not None]
    if not conclusive:
        return SyncVerdict("inconclusive", None, tuple(windows))
    lags = [Decimal(window.lag_ms) for window in conclusive]  # type: ignore[arg-type]
    worst = max(lags, key=abs)
    status = "passed" if all(abs(lag) <= TOLERANCE_MS for lag in lags) else "out_of_sync"
    return SyncVerdict(status, str(worst), tuple(windows))


def window_result(
    final_start: Decimal, reference_start: Decimal, reference: Any, final: Any
) -> SyncWindow:
    lag, correlation, rms = measure_lag(reference, final)
    lag_ms = (Decimal(lag) * Decimal(1000) / Decimal(SYNC_RATE)).quantize(Decimal("0.001"))
    if rms < MIN_RMS:
        reason = "too_quiet"
    elif correlation < MIN_CORRELATION:
        reason = "no_clear_match"
    else:
        reason = None
    return SyncWindow(
        final_start_seconds=str(final_start),
        reference_start_seconds=str(reference_start),
        lag_ms=str(lag_ms),
        correlation=round(correlation, 4),
        conclusive=reason is None,
        reason=reason,
    )


__all__ = [
    "MAX_LAG_SECONDS",
    "SYNC_RATE",
    "SyncVerdict",
    "SyncWindow",
    "TOLERANCE_MS",
    "WINDOW_SECONDS",
    "judge",
    "measure_lag",
    "read_samples",
    "sync_window_command",
    "window_result",
    "window_starts",
]
