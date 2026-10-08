"""Progress of the step a job is running right now, for the web UI.

The worker writes two small JSON files below ``<job>/.live``:

* ``step.json``: the running step (key, label, fraction or ``None``
  when it cannot be measured, detail text, elapsed/ETA, optional metrics and
  side tasks running beside it, such as the source index or the integrity
  decode);
* ``timeline.json``: every finished step with its duration and outcome.

Files instead of database rows: updates arrive every second or two from
long-running commands, and the API only needs to read them while a page is
open.  Writing them is best effort: progress reporting never fails a job.

Labels and details are stored in both interface languages (``{"hu": ..., "en":
...}``, see :mod:`bdencode.i18n`) and resolved to the request's language when
the API reads them; plain strings (language-neutral texts, and files written
before 3.6) are served unchanged.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from pathlib import Path
from typing import Any, Callable, TypeAlias

from .i18n import bilingual, pick
from .utils import atomic_write_json

LOG = logging.getLogger(__name__)
LIVE_SCHEMA = 1
STEP_FILE = "step.json"
TIMELINE_FILE = "timeline.json"
_TAIL_BYTES = 64 * 1024
_OUT_TIME_US = re.compile(rb"out_time_(?:us|ms)=(\d+)")
_STATS_TIME = re.compile(rb"time=(\d+):(\d{2}):(\d{2}(?:\.\d+)?)")
_CROP_TIME = re.compile(rb"\bt:(\d+(?:\.\d+)?)")
_PERCENT = re.compile(rb"(\d{1,3}(?:\.\d+)?)\s*%")

# A live text: a ``(hungarian, english)`` pair, or a language-neutral string.
LiveText: TypeAlias = str | tuple[str, str]


def _stored(text: LiveText | None) -> str | dict[str, str] | None:
    """The JSON form of a live text: both languages, or the plain string."""

    if isinstance(text, tuple):
        return bilingual(*text)
    return text


def _tail(path: Path, size: int = _TAIL_BYTES) -> bytes:
    try:
        with path.open("rb") as handle:
            handle.seek(0, 2)
            length = handle.tell()
            handle.seek(max(0, length - size))
            return handle.read()
    except OSError:
        return b""


def media_seconds_in_tail(path: Path) -> float | None:
    """The latest media timestamp an FFmpeg run reported in ``path``.

    Understands ``-progress`` output (``out_time_us``), the classic stats line
    (``time=HH:MM:SS.ss``) and cropdetect's per-frame ``t:`` field.
    """

    tail = _tail(path)
    best: float | None = None
    for match in _OUT_TIME_US.finditer(tail):
        best = int(match.group(1)) / 1_000_000
    if best is not None:
        return best
    for match in _STATS_TIME.finditer(tail):
        best = int(match.group(1)) * 3600 + int(match.group(2)) * 60 + float(match.group(3))
    if best is not None:
        return best
    for match in _CROP_TIME.finditer(tail):
        best = float(match.group(1))
    return best


def percent_in_tail(path: Path) -> float | None:
    """The latest ``NN%`` a tool printed (L-SMASH indexing, mkvmerge)."""

    matches = list(_PERCENT.finditer(_tail(path, 8 * 1024)))
    if not matches:
        return None
    value = float(matches[-1].group(1))
    return min(1.0, max(0.0, value / 100)) if 0 <= value <= 100 else None


def time_fraction(path: Path, duration_seconds: float | None) -> float | None:
    if not duration_seconds or duration_seconds <= 0:
        return None
    seconds = media_seconds_in_tail(path)
    if seconds is None:
        return None
    return min(1.0, max(0.0, seconds / duration_seconds))


class LiveProgress:
    """Thread-safe writer of a job's live step and step timeline."""

    def __init__(
        self,
        root: Path,
        *,
        clock: Callable[[], float] = time.time,
        min_interval: float = 1.0,
    ) -> None:
        self.root = root
        self.clock = clock
        self.min_interval = min_interval
        self._lock = threading.Lock()
        self._step: dict[str, Any] | None = None
        self._last_write = 0.0

    # -- the running step ---------------------------------------------------
    def start(self, key: str, label: LiveText, *, detail: LiveText | None = None) -> None:
        with self._lock:
            now = self.clock()
            self._step = {
                "schema_version": LIVE_SCHEMA,
                "key": key,
                "label": _stored(label),
                "fraction": None,
                "detail": _stored(detail),
                "started_at": now,
                "updated_at": now,
                "eta_seconds": None,
                "metrics": {},
                "side": {},
            }
            self._write(force=True)

    def update(
        self,
        fraction: float | None = None,
        *,
        detail: LiveText | None = None,
        metrics: dict[str, Any] | None = None,
        force: bool = False,
    ) -> None:
        with self._lock:
            step = self._step
            if step is None:
                return
            now = self.clock()
            if fraction is not None:
                fraction = min(1.0, max(0.0, float(fraction)))
                # The meter never moves backwards within one step.
                previous = step["fraction"]
                fraction = fraction if previous is None else max(previous, fraction)
                step["fraction"] = fraction
                elapsed = now - step["started_at"]
                step["eta_seconds"] = (
                    elapsed * (1 - fraction) / fraction
                    if fraction >= 0.01 and elapsed > 0
                    else None
                )
            if detail is not None:
                step["detail"] = _stored(detail)
            if metrics:
                step["metrics"].update(metrics)
            step["updated_at"] = now
            self._write(force=force)

    def side(
        self, key: str, label: LiveText, fraction: float | None, *, done: bool = False
    ) -> None:
        """A task running beside the step (shown as a secondary bar)."""

        with self._lock:
            step = self._step
            if step is None:
                return
            step["side"][key] = {
                "label": _stored(label),
                "fraction": None if fraction is None else min(1.0, max(0.0, fraction)),
                "done": done,
            }
            step["updated_at"] = self.clock()
            self._write(force=done)

    def finish(self, outcome: str = "done") -> None:
        with self._lock:
            step = self._step
            if step is None:
                return
            self._close(step, self.clock(), outcome)
            self._step = None

    def discard_stale(self) -> None:
        """Close a step left behind by a worker that stopped in the middle of it.

        Only the worker process running a step writes its file, so a step file
        found before this tracker started anything belongs to an earlier run.
        """

        with self._lock:
            if self._step is not None:
                return
            try:
                stale = json.loads((self.root / STEP_FILE).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return
            started = stale.get("started_at") if isinstance(stale, dict) else None
            if isinstance(started, (int, float)) and isinstance(stale.get("key"), str):
                updated = stale.get("updated_at")
                ended = updated if isinstance(updated, (int, float)) else started
                self._close(stale, ended, "interrupted")
            else:
                self._remove_step_file()

    def _close(self, step: dict[str, Any], now: float, outcome: str) -> None:
        entry = {
            "key": step["key"],
            "label": step.get("label", step["key"]),
            "started_at": step["started_at"],
            "finished_at": now,
            "seconds": round(now - step["started_at"], 1),
            "outcome": outcome,
        }
        timeline = self._read_timeline()
        timeline["steps"].append(entry)
        self._safe_write(self.root / TIMELINE_FILE, timeline)
        self._remove_step_file()

    def _remove_step_file(self) -> None:
        try:
            (self.root / STEP_FILE).unlink(missing_ok=True)
        except OSError:
            pass

    # -- files --------------------------------------------------------------
    def _read_timeline(self) -> dict[str, Any]:
        try:
            document = json.loads((self.root / TIMELINE_FILE).read_text(encoding="utf-8"))
            if isinstance(document, dict) and isinstance(document.get("steps"), list):
                return document
        except (OSError, ValueError):
            pass
        return {"schema_version": LIVE_SCHEMA, "steps": []}

    def _write(self, *, force: bool) -> None:
        now = time.monotonic()
        if not force and now - self._last_write < self.min_interval:
            return
        self._last_write = now
        if self._step is not None:
            self._safe_write(self.root / STEP_FILE, self._step)

    def _safe_write(self, path: Path, document: dict[str, Any]) -> None:
        try:
            self.root.mkdir(mode=0o750, parents=True, exist_ok=True)
            atomic_write_json(path, document)
        except Exception:  # progress must never fail a job
            LOG.debug("live progress write failed", exc_info=True)


def _resolved_step(step: dict[str, Any]) -> dict[str, Any]:
    """``step`` with its texts in the current interface language."""

    resolved = {**step, "label": pick(step.get("label"))}
    if "detail" in step:
        resolved["detail"] = pick(step["detail"])
    side = step.get("side")
    if isinstance(side, dict):
        resolved["side"] = {
            key: {**item, "label": pick(item.get("label"))} if isinstance(item, dict) else item
            for key, item in side.items()
        }
    return resolved


def read_live(root: Path) -> dict[str, Any]:
    """The live step (or ``None``) and the finished steps, for the API.

    Bilingual labels and details come back as plain strings in the current
    interface language.
    """

    def load(name: str) -> Any:
        try:
            return json.loads((root / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    step = load(STEP_FILE)
    timeline = load(TIMELINE_FILE)
    steps = timeline.get("steps") if isinstance(timeline, dict) else None
    return {
        "step": _resolved_step(step) if isinstance(step, dict) else None,
        "timeline": [
            _resolved_step(item) if isinstance(item, dict) else item for item in steps
        ]
        if isinstance(steps, list)
        else [],
    }
