"""Evaluating a finished encode: fixed rules, an AI answer, and the API."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bdencode.ai_recommendation import AIRecommendationError
from bdencode.api import create_app
from bdencode.comparison_evaluation import (
    collect_facts,
    deterministic_evaluation,
    evaluation_from_ai,
    validate_suggestion,
)
from bdencode.config import Settings
from bdencode.db import Database
from bdencode.models import ArtifactCreate, ArtifactKind, JobCreate, JobState


def write_measurements(root: Path, *, vmaf_mean: float, vmaf_low: float, saving: float, crf: float = 17.5) -> None:
    (root / "comparison").mkdir(parents=True, exist_ok=True)
    (root / "analysis").mkdir(parents=True, exist_ok=True)
    (root / "logs").mkdir(parents=True, exist_ok=True)
    samples = [
        {"category": kind, "presentation_index": index * 1000, "ssim_all": ssim, "psnr_average_db": psnr}
        for index, (kind, ssim, psnr) in enumerate(
            [("I", 1.0, "inf"), ("P", 0.982, 47.2), ("B", 0.978, 45.8), ("I", 0.993, 51.1), ("P", 0.984, 46.0), ("B", 0.981, 46.7)]
        )
    ]
    (root / "comparison/video-metrics.json").write_text(json.dumps({
        "samples": samples,
        "aggregate": {"ssim_all_mean": 0.9875, "psnr_average_db_mean": 48.4},
        "quality_gate": {"status": "passed", "warnings": []},
    }), encoding="utf-8")
    (root / "comparison/video-vmaf.json").write_text(json.dumps({
        "status": "measured", "model": "vmaf_v0.6.1", "mean": vmaf_mean, "harmonic_mean": vmaf_mean - 0.05,
        "percentile_1": vmaf_low, "minimum": vmaf_low - 4,
        "windows": [{"start_seconds": 400.0, "mean": vmaf_mean + 0.5}, {"start_seconds": 4048.0, "mean": vmaf_mean - 2}],
    }), encoding="utf-8")
    source = 17_446_016_571
    (root / "analysis/video-efficiency.json").write_text(json.dumps({
        "verdict": {"source_bytes": source, "encoded_bytes": round(source * (1 - saving))},
    }), encoding="utf-8")
    (root / "comparison/video-comparison.json").write_text(json.dumps({
        "frame_completeness": {"verdict": {"final_video_duration_seconds": "5819.063", "fps_numerator": 24000, "fps_denominator": 1001}},
    }), encoding="utf-8")
    (root / "encode-plan.json").write_text(json.dumps({
        "output_encoder": "x264",
        "decisions": {
            "content_kind": "film",
            "crop": {"left": 68, "right": 68, "top": 0, "bottom": 0},
            "source_video": {"video": {"width": 1920, "height": 1080, "codec": "avc", "hdr10": False}},
            "encoder": {"crf": crf, "preset": "slow", "psy_rd": 1.0, "bframes": 8},
        },
    }), encoding="utf-8")
    (root / "logs/video-encode.log").write_text(
        "[libx264 @ 0x1] frame I:822   Avg QP:14.68  size:297126\n"
        "[libx264 @ 0x1] frame B:113545 Avg QP:18.81  size: 98629\n"
        "[libx264 @ 0x1] kb/s:20466.49\n",
        encoding="utf-8",
    )


def test_a_transparent_but_generous_encode_suggests_a_higher_crf(tmp_path: Path) -> None:
    # The Late Fame numbers (nvme, 2026-10-10).
    write_measurements(tmp_path, vmaf_mean=95.267, vmaf_low=91.943, saving=0.147)
    facts = collect_facts(tmp_path)

    evaluation = deterministic_evaluation(facts)

    assert facts["encoded_picture"]["width"] == 1784
    assert evaluation["verdict"] == "transparent"
    (crf,) = [item for item in evaluation["suggestions"] if item["field"] == "crf"]
    assert (crf["current"], crf["value"]) == (17.5, 18.5)
    assert crf["estimated_size_change_percent"] == -13
    assert any("Bőkezű bitráta" in item["hu"] for item in evaluation["findings"])


def test_a_weak_spot_suggests_a_lower_crf(tmp_path: Path) -> None:
    write_measurements(tmp_path, vmaf_mean=91.0, vmaf_low=82.0, saving=0.5, crf=21)

    evaluation = deterministic_evaluation(collect_facts(tmp_path))

    assert evaluation["verdict"] == "weak"
    assert evaluation["suggestions"][0]["value"] == 20.0


def test_without_measurements_there_is_nothing_to_evaluate(tmp_path: Path) -> None:
    assert collect_facts(tmp_path) is None


def test_ai_suggestions_stay_inside_their_bounds(tmp_path: Path) -> None:
    write_measurements(tmp_path, vmaf_mean=95.3, vmaf_low=91.9, saving=0.15)
    facts = collect_facts(tmp_path)
    answer = {
        "verdict": "transparent",
        "summary": {"hu": "Átlátszó.", "en": "Transparent."},
        "findings": [{"hu": "Bőkezű.", "en": "Generous."}],
        "suggestions": [
            {"field": "crf", "value": "18.5", "reason": {"hu": "Kisebb fájl.", "en": "Smaller file."}},
            {"field": "crf", "value": "45", "reason": {"hu": "x", "en": "x"}},
            {"field": "bframes", "value": "7.5", "reason": {"hu": "x", "en": "x"}},
        ],
        "confidence": 0.8,
    }

    evaluation = evaluation_from_ai(answer, facts, source="openai", model="gpt-test")

    assert [(item["field"], item["value"]) for item in evaluation["suggestions"]] == [("crf", 18.5)]
    assert evaluation["suggestions"][0]["estimated_size_change_percent"] == -13
    with pytest.raises(ValueError):
        evaluation_from_ai({**answer, "verdict": "great"}, facts, source="openai", model=None)
    assert validate_suggestion("deblock_alpha", "-2") == -2
    assert validate_suggestion("noise", "1") is None


class _FakeAI:
    def __init__(self, *, available: bool, fail: bool = False) -> None:
        self.available, self.fail, self.calls = available, fail, 0

    def evaluation_available(self) -> bool:
        return self.available

    def evaluate_comparison(self, facts, baseline):
        self.calls += 1
        if self.fail:
            raise AIRecommendationError("the AI gave no usable answer")
        return {**baseline, "source": "openai", "model": "gpt-test", "confidence": 0.9,
                "summary": {"hu": "AI szerint átlátszó.", "en": "Transparent per AI."}}

    def status(self):
        return {"provider": "openai", "configured": self.available, "providers": []}


@pytest.fixture
def completed_job(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    settings = Settings(data_root=tmp_path / "data", source_roots=(source,)).validate()
    settings.create_directories()
    database = Database(tmp_path / "state.sqlite3")
    job = database.create_job(JobCreate(source_path=str(source / "Disc"), name="Disc"))
    for state in (JobState.SCANNING, JobState.AWAITING_SELECTION):
        database.transition_job(job.id, state)
    database.set_selection(job.id, {"playlist_id": "00800", "tracks": []})
    for state in (JobState.ENCODING, JobState.MUXING, JobState.QC, JobState.COMPARISON, JobState.UPLOADING, JobState.COMPLETED):
        database.transition_job(job.id, state)
    root = settings.job_root(job.id)
    write_measurements(root, vmaf_mean=95.267, vmaf_low=91.943, saving=0.147)
    output = settings.completed_root / "Disc" / "Disc.mkv"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"mkv")
    database.create_artifact(ArtifactCreate(job_id=job.id, kind=ArtifactKind.OUTPUT, name="Disc.mkv", path=str(output)))
    return database, settings, job


def test_the_page_gets_the_fixed_rules_first_and_the_ai_on_request(completed_job) -> None:
    database, settings, job = completed_job
    ai = _FakeAI(available=True)
    client = TestClient(create_app(database, settings=settings, ai_recommender=ai))

    first = client.get(f"/api/v1/jobs/{job.id}/evaluation").json()
    assert first["source"] == "deterministic" and first["ai_available"] is True
    assert first["ai_attempted"] is False and ai.calls == 0

    evaluated = client.post(f"/api/v1/jobs/{job.id}/evaluation", json={}).json()
    assert evaluated["source"] == "openai" and ai.calls == 1
    # Cached: the next page load does not call the AI again.
    assert client.get(f"/api/v1/jobs/{job.id}/evaluation").json()["source"] == "openai"
    assert ai.calls == 1


def test_an_ai_failure_keeps_the_fixed_rule_evaluation(completed_job) -> None:
    database, settings, job = completed_job
    client = TestClient(create_app(database, settings=settings, ai_recommender=_FakeAI(available=True, fail=True)))

    evaluated = client.post(f"/api/v1/jobs/{job.id}/evaluation", json={}).json()

    assert evaluated["source"] == "deterministic"
    assert evaluated["ai_error"] == "the AI gave no usable answer"
    assert evaluated["suggestions"][0]["value"] == 18.5
