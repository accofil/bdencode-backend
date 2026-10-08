"""The live step indicator: tracker, log-tail parsers and the API view."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bdencode.api import create_app
from bdencode.config import Settings
from bdencode.db import Database
from bdencode.live_progress import (
    LiveProgress,
    media_seconds_in_tail,
    percent_in_tail,
    read_live,
    time_fraction,
)
from bdencode.models import JobCreate


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_a_step_reports_its_fraction_eta_side_tasks_and_lands_in_the_timeline(tmp_path: Path) -> None:
    clock = Clock()
    live = LiveProgress(tmp_path / ".live", clock=clock, min_interval=0)

    live.start("crop-scan", "Crop-keresés (GPU)")
    clock.now += 60
    live.update(0.25, detail="29 / 117 perc")
    live.side("index", "Forrásindex", 0.5)
    step = read_live(tmp_path / ".live")["step"]
    assert step["key"] == "crop-scan" and step["label"] == "Crop-keresés (GPU)"
    assert step["fraction"] == 0.25 and step["detail"] == "29 / 117 perc"
    assert step["eta_seconds"] == pytest.approx(180.0)
    assert step["side"]["index"] == {"label": "Forrásindex", "fraction": 0.5, "done": False}

    # The meter never moves backwards within a step.
    live.update(0.2)
    assert read_live(tmp_path / ".live")["step"]["fraction"] == 0.25

    clock.now += 120
    live.finish()
    view = read_live(tmp_path / ".live")
    assert view["step"] is None
    assert view["timeline"] == [
        {
            "key": "crop-scan",
            "label": "Crop-keresés (GPU)",
            "started_at": 1000.0,
            "finished_at": 1180.0,
            "seconds": 180.0,
            "outcome": "done",
        }
    ]


def test_a_step_left_behind_by_a_stopped_worker_is_closed_as_interrupted(tmp_path: Path) -> None:
    clock = Clock()
    crashed = LiveProgress(tmp_path / ".live", clock=clock, min_interval=0)
    crashed.start("encode", "Videókódolás")
    clock.now += 30
    crashed.update(0.4)
    # The worker dies here: nothing calls finish().

    clock.now += 600
    restarted = LiveProgress(tmp_path / ".live", clock=clock, min_interval=0)
    restarted.discard_stale()

    view = read_live(tmp_path / ".live")
    assert view["step"] is None
    assert view["timeline"] == [
        {
            "key": "encode",
            "label": "Videókódolás",
            "started_at": 1000.0,
            "finished_at": 1030.0,
            "seconds": 30.0,
            "outcome": "interrupted",
        }
    ]
    # Nothing to close the second time, and a running step is never touched.
    restarted.discard_stale()
    restarted.start("mux", "Muxolás")
    restarted.discard_stale()
    assert read_live(tmp_path / ".live")["step"]["key"] == "mux"
    assert len(read_live(tmp_path / ".live")["timeline"]) == 1


def test_updates_are_throttled_but_forced_ones_are_written(tmp_path: Path) -> None:
    live = LiveProgress(tmp_path / ".live", min_interval=3600)
    live.start("encode", "Videókódolás")
    live.update(0.1)
    assert read_live(tmp_path / ".live")["step"]["fraction"] is None
    live.update(0.2, force=True)
    assert read_live(tmp_path / ".live")["step"]["fraction"] == 0.2


def test_log_tails_yield_media_time_and_percentages(tmp_path: Path) -> None:
    progress = tmp_path / "progress.txt"
    progress.write_text("frame=10\nout_time_us=1500000\nprogress=continue\nout_time_us=3000000\n")
    assert media_seconds_in_tail(progress) == 3.0
    assert time_fraction(progress, 12.0) == 0.25

    stats = tmp_path / "remux.log"
    stats.write_bytes(b"size= 1024kB time=00:00:10.00 bitrate=1\rsize= 2048kB time=00:01:00.50 bitrate=1\r")
    assert media_seconds_in_tail(stats) == pytest.approx(60.5)

    crop = tmp_path / "crop.log"
    crop.write_text("[Parsed_cropdetect_0] x1:0 t:41.708 crop=3840:1636:0:262\n" * 3)
    assert media_seconds_in_tail(crop) == pytest.approx(41.708)

    index = tmp_path / "index.log"
    index.write_text("Creating lwi index file 12%Creating lwi index file 57%")
    assert percent_in_tail(index) == 0.57
    assert time_fraction(tmp_path / "missing.log", 10) is None
    assert time_fraction(progress, None) is None


def test_the_api_serves_the_live_step_of_a_job(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    settings = Settings(data_root=tmp_path / "data", source_roots=(source,)).validate()
    settings.create_directories()
    database = Database(tmp_path / "state.sqlite3")
    client = TestClient(create_app(database, settings=settings))
    job = database.create_job(JobCreate(source_path=str(source / "Disc"), name="Disc"))

    empty = client.get(f"/api/v1/jobs/{job.id}/live").json()
    assert empty["step"] is None and empty["timeline"] == []
    assert isinstance(empty["now"], float)

    live = LiveProgress(settings.job_root(job.id) / ".live", min_interval=0)
    live.start("remux", "Referencia-remux")
    live.update(0.5)
    body = client.get(f"/api/v1/jobs/{job.id}/live").json()
    assert body["step"]["key"] == "remux" and body["step"]["fraction"] == 0.5
    assert body["now"] >= body["step"]["started_at"]
    assert client.get("/api/v1/jobs/unknown-job/live").status_code == 404
