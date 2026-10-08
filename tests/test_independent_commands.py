"""Independent QC/comparison commands run concurrently on a real runner, in order on test runners."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from bdencode.process import CommandRunner
from bdencode.worker import PipelineWorker


def _worker(runner: object) -> SimpleNamespace:
    return SimpleNamespace(_runner=lambda _paths: runner)


PATHS = SimpleNamespace(root=Path("job-1"))


def test_tasks_overlap_on_a_real_runner(tmp_path: Path) -> None:
    worker = _worker(CommandRunner(tmp_path / "commands.jsonl"))
    active, peak, lock = [0], [0], threading.Lock()

    def task() -> None:
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        time.sleep(0.2)
        with lock:
            active[0] -= 1

    PipelineWorker._run_independent(worker, PATHS, [task] * 4)  # type: ignore[arg-type]

    assert peak[0] > 1


def test_every_task_finishes_before_the_first_error_is_raised(tmp_path: Path) -> None:
    worker = _worker(CommandRunner(tmp_path / "commands.jsonl"))
    finished: list[str] = []

    def fails() -> None:
        raise RuntimeError("probe failed")

    def slow() -> None:
        time.sleep(0.3)
        finished.append("slow")

    with pytest.raises(RuntimeError, match="probe failed"):
        PipelineWorker._run_independent(worker, PATHS, [fails, slow])  # type: ignore[arg-type]
    assert finished == ["slow"]


def test_test_runners_keep_the_sequential_order() -> None:
    worker = _worker(object())
    order: list[int] = []

    PipelineWorker._run_independent(  # type: ignore[arg-type]
        worker, PATHS, [lambda index=index: order.append(index) for index in range(5)]
    )

    assert order == [0, 1, 2, 3, 4]
