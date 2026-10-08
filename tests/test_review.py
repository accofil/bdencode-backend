"""Resolving reviews from the web UI: track languages, image upload resets and
video metric acceptance."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bdencode.api import create_app
from bdencode.config import Settings
from bdencode.db import Database
from bdencode.models import JobCreate, JobState
from bdencode.review import (
    LANGUAGE_REVIEW_MESSAGE,
    STAGES_DIR,
    VIDEO_METRICS_REVIEW_MESSAGE,
    ReviewError,
    accept_video_metrics,
    apply_track_languages,
    language_review,
    read_upload_override,
    reset_upload,
    video_metrics_accepted,
)
from bdencode.worker import JobPaths

SELECTION = {
    "playlist_id": "00800",
    "tracks": [
        {"stream_id": "video:4113", "action": "copy"},
        {"stream_id": "audio:4352", "action": "copy"},
        {"stream_id": "audio:4353", "action": "flac"},
        {"stream_id": "audio:4354", "action": "omit"},
        {"stream_id": "subtitle:4608", "action": "copy", "subtitle_kind": "full"},
    ],
}
SCAN_RESULT = {
    "playlists": [
        {
            "playlist_id": "00800",
            "streams": [
                {"id": "video:4113", "kind": "video", "codec": "hevc"},
                {
                    "id": "audio:4352",
                    "kind": "audio",
                    "codec": "truehd",
                    "channels": 8,
                    "title": "English Atmos",
                    "language": {"iso639_2t": "eng"},
                },
                {
                    "id": "audio:4353",
                    "kind": "audio",
                    "codec": "dts",
                    "channels": 6,
                    "title": None,
                    "language": {"iso639_2t": "eng"},
                },
                {"id": "audio:4354", "kind": "audio", "codec": "ac3"},
                {"id": "subtitle:4608", "kind": "subtitle", "codec": "pgs", "language": None},
            ],
        }
    ]
}
REPORT = {
    "status": "needs_review",
    "resolved_languages": {"audio:4352": "eng"},
    "evidence": [
        {"stream_id": "audio:4352", "inference": {"consensus": {"iso639_2t": "eng", "confidence": 0.98}}},
        {"stream_id": "audio:4353", "inference": {"consensus": {"iso639_2t": "hun", "confidence": 0.91}}},
    ],
    "unresolved": [
        {"stream_id": "audio:4353", "kind": "audio", "reason": "language_conflict_or_low_confidence"},
        {"stream_id": "subtitle:4608", "kind": "subtitle", "reason": "subtitle_ocr_or_manual_override_required"},
    ],
}


def test_the_language_review_lists_every_retained_track_with_its_clues() -> None:
    review = language_review(SELECTION, SCAN_RESULT, REPORT, {})
    tracks = {track["stream_id"]: track for track in review["tracks"]}

    # Video and omitted tracks need no language.
    assert list(tracks) == ["audio:4352", "audio:4353", "subtitle:4608"]
    assert tracks["audio:4352"]["needs_confirmation"] is False
    assert tracks["audio:4352"]["suggested"] == "eng"
    # The disc says English, the detection is sure it is Hungarian.
    conflict = tracks["audio:4353"]
    assert conflict["needs_confirmation"] is True
    assert (conflict["declared"], conflict["detected"], conflict["suggested"]) == ("eng", "hun", "hun")
    assert conflict["detected_confidence"] == pytest.approx(0.91)
    assert tracks["subtitle:4608"]["suggested"] is None
    assert {"code": "hun", "bcp47": "hu"} in review["languages"]


def test_confirmed_languages_are_written_into_the_selection() -> None:
    revised = apply_track_languages(SELECTION, {"audio:4353": "hun", "subtitle:4608": "ger"})

    by_id = {track["stream_id"]: track for track in revised["tracks"]}
    assert by_id["audio:4353"]["language"] == "hun"
    # Bibliographic codes become the terminological form Matroska receives.
    assert by_id["subtitle:4608"]["language"] == "deu"
    assert "language" not in SELECTION["tracks"][2]

    with pytest.raises(ReviewError, match="unknown ISO 639-2"):
        apply_track_languages(SELECTION, {"audio:4353": "xx"})
    with pytest.raises(ReviewError, match="not a retained track"):
        apply_track_languages(SELECTION, {"audio:4354": "eng"})


def test_an_upload_reset_keeps_the_old_checkpoint_and_records_the_choice(tmp_path: Path) -> None:
    root = tmp_path / "job"
    (root / "comparison").mkdir(parents=True)
    (root / STAGES_DIR).mkdir()
    (root / "comparison" / "uploads.json").write_text(
        json.dumps({"schema_version": 2, "provider": "imgbb", "images": {"a.png": {}, "b.png": {}}})
    )
    (root / STAGES_DIR / "upload.json").write_text("{}")

    first = reset_upload(root, provider="catbox", image_set="sdr", upload_images=True, clock=lambda: 0)
    second = reset_upload(root, provider=None, image_set=None, upload_images=False, clock=lambda: 0)

    assert first["previous_provider"] == "imgbb" and first["previous_uploaded_images"] == 2
    assert (root / "logs" / "upload-resets" / first["backup"]).is_file()
    assert second["backup"] is None  # nothing left to keep
    assert not (root / "comparison" / "uploads.json").exists()
    assert not (root / STAGES_DIR / "upload.json").exists()
    assert read_upload_override(root / STAGES_DIR) == {"upload_images": False}
    with pytest.raises(ReviewError):
        reset_upload(root, provider="dropbox", image_set=None, upload_images=True)


def test_the_stage_directory_matches_the_worker_layout(tmp_path: Path) -> None:
    (tmp_path / "source").mkdir()
    settings = Settings(data_root=tmp_path / "data", source_roots=(tmp_path / "source",)).validate()
    settings.create_directories()
    assert JobPaths.create(settings, "job-1").stages.name == STAGES_DIR


@pytest.fixture
def api(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    settings = Settings(data_root=tmp_path / "data", source_roots=(source,)).validate()
    settings.create_directories()
    database = Database(tmp_path / "state.sqlite3")
    client = TestClient(create_app(database, settings=settings))
    job = database.create_job(JobCreate(source_path=str(source / "Disc"), name="Disc"))
    return client, database, settings, job


def _walk(database: Database, job_id: str, *states: JobState, **last) -> None:
    for state in states[:-1]:
        database.transition_job(job_id, state)
    database.transition_job(job_id, states[-1], **last)


def test_the_page_confirms_languages_and_the_job_returns_to_the_queue(api) -> None:
    client, database, settings, job = api
    _walk(database, job.id, JobState.SCANNING, JobState.AWAITING_SELECTION)
    database.set_selection(job.id, SELECTION)
    _walk(
        database,
        job.id,
        JobState.ENCODING,
        JobState.NEEDS_REVIEW,
        message=LANGUAGE_REVIEW_MESSAGE,
        details={"tracks": REPORT["unresolved"]},
    )
    analysis = settings.job_root(job.id) / "analysis"
    analysis.mkdir(parents=True, exist_ok=True)
    (analysis / "language-inference.json").write_text(json.dumps(REPORT), encoding="utf-8")

    review = client.get(f"/api/v1/jobs/{job.id}/review").json()
    assert review["kind"] == "language"
    assert [track["stream_id"] for track in review["language"]["tracks"] if track["needs_confirmation"]] == [
        "audio:4353",
        "subtitle:4608",
    ]

    rejected = client.post(f"/api/v1/jobs/{job.id}/review/languages", json={"languages": {"audio:4353": "zz"}})
    assert rejected.status_code == 422

    current = database.get_job(job.id)
    response = client.post(
        f"/api/v1/jobs/{job.id}/review/languages",
        json={
            "languages": {"audio:4352": "eng", "audio:4353": "hun", "subtitle:4608": "hun"},
            "expected_version": current.version,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["state"] == "READY"
    languages = {track["stream_id"]: track.get("language") for track in body["selection"]["tracks"]}
    assert languages["audio:4353"] == "hun" and languages["subtitle:4608"] == "hun"

    again = client.post(f"/api/v1/jobs/{job.id}/review/languages", json={"languages": {"audio:4353": "hun"}})
    assert again.status_code == 409


def test_the_page_resets_a_failed_upload_with_another_host(api) -> None:
    client, database, settings, job = api
    _walk(database, job.id, JobState.SCANNING, JobState.AWAITING_SELECTION)
    database.set_selection(job.id, SELECTION)
    _walk(
        database,
        job.id,
        JobState.ENCODING,
        JobState.MUXING,
        JobState.QC,
        JobState.COMPARISON,
        JobState.UPLOADING,
        JobState.UPLOAD_FAILED,
        message="image upload failed; retry is safe",
        details={"provider": "imgbb"},
    )
    comparison = settings.job_root(job.id) / "comparison"
    comparison.mkdir(parents=True, exist_ok=True)
    (comparison / "uploads.json").write_text(
        json.dumps({"schema_version": 2, "provider": "imgbb", "images": {"a.png": {}}}), encoding="utf-8"
    )
    (comparison / "01-I-f000000000-encode.png").write_bytes(b"\0" * 2048)

    review = client.get(f"/api/v1/jobs/{job.id}/review").json()
    assert review["kind"] == "upload_failed"
    assert review["upload"]["provider"] == "imgbb"
    assert review["upload"]["uploaded_images"] == 1
    assert review["upload"]["largest_image_bytes"] == 2048
    assert {"provider": "catbox", "max_upload_bytes": 200_000_000} in review["upload"]["hosts"]

    current = database.get_job(job.id)
    response = client.post(
        f"/api/v1/jobs/{job.id}/reset-upload",
        json={"provider": "catbox", "image_set": "sdr", "expected_version": current.version},
    )
    assert response.status_code == 200, response.text
    assert response.json()["state"] == "UPLOADING"
    assert read_upload_override(settings.job_root(job.id) / STAGES_DIR) == {
        "image_upload_provider": "catbox",
        "upload_image_set": "sdr",
        "upload_images": True,
    }
    reset_events = [event for event in database.list_events(job_id=job.id, limit=1000) if event.kind == "job.upload-reset"]
    assert reset_events and reset_events[-1].payload["previous_provider"] == "imgbb"

    # Not an upload problem any more.
    assert client.post(f"/api/v1/jobs/{job.id}/reset-upload", json={}).status_code == 409


def test_other_reviews_cannot_reset_the_upload(api) -> None:
    client, database, _settings, job = api
    _walk(database, job.id, JobState.SCANNING, JobState.AWAITING_SELECTION)
    database.set_selection(job.id, SELECTION)
    _walk(
        database,
        job.id,
        JobState.ENCODING,
        JobState.NEEDS_REVIEW,
        message="video compatibility policy rejected the selection: test",
    )

    assert client.get(f"/api/v1/jobs/{job.id}/review").json()["kind"] == "other"
    assert client.post(f"/api/v1/jobs/{job.id}/reset-upload", json={}).status_code == 409


def _metrics_report(errors: list[str]) -> dict:
    return {
        "aggregate": {"ssim_all_mean": 0.82, "psnr_average_db_mean": 31.5},
        "samples": [
            {"category": "I", "presentation_index": 0, "ssim_all": 0.97, "psnr_average_db": 44.0,
             "reference_measurement_sha256": "r1", "encode_measurement_sha256": "e1"},
            {"category": "B", "presentation_index": 52920, "ssim_all": 0.71, "psnr_average_db": 27.0,
             "reference_measurement_sha256": "r2", "encode_measurement_sha256": "e2"},
        ],
        "quality_gate": {"status": "needs_review", "errors": errors, "warnings": []},
    }


def test_the_page_accepts_a_video_metrics_review_for_these_frames_only(api) -> None:
    client, database, settings, job = api
    errors = ["sample 2 SSIM is below 0.80 (0.710000)", "sample 2 PSNR is below 28 dB (27.000 dB)"]
    _walk(database, job.id, JobState.SCANNING, JobState.AWAITING_SELECTION)
    database.set_selection(job.id, SELECTION)
    _walk(
        database,
        job.id,
        JobState.ENCODING,
        JobState.MUXING,
        JobState.QC,
        JobState.COMPARISON,
        JobState.NEEDS_REVIEW,
        message=VIDEO_METRICS_REVIEW_MESSAGE,
        details={"errors": errors, "report": "video-metrics.json"},
    )
    comparison = settings.job_root(job.id) / "comparison"
    comparison.mkdir(parents=True, exist_ok=True)
    report = _metrics_report(errors)
    (comparison / "video-metrics.json").write_text(json.dumps(report), encoding="utf-8")

    review = client.get(f"/api/v1/jobs/{job.id}/review").json()
    assert review["kind"] == "video_metrics"
    assert review["video_metrics"]["errors"] == errors
    assert review["video_metrics"]["samples"][1] == {
        "index": 2, "category": "B", "presentation_index": 52920, "ssim_all": 0.71, "psnr_average_db": 27.0,
    }

    current = database.get_job(job.id)
    stale = client.post(f"/api/v1/jobs/{job.id}/review/video-metrics", json={"expected_version": current.version - 1})
    assert stale.status_code == 409
    response = client.post(f"/api/v1/jobs/{job.id}/review/video-metrics", json={"expected_version": current.version})
    assert response.status_code == 200, response.text
    assert response.json()["state"] == "COMPARISON"

    # The acceptance binds the findings and the measured frames.
    assert video_metrics_accepted(comparison, errors, report["samples"]) is not None
    assert video_metrics_accepted(comparison, errors[:1], report["samples"]) is None
    other_encode = [dict(sample, encode_measurement_sha256="x") for sample in report["samples"]]
    assert video_metrics_accepted(comparison, errors, other_encode) is None
    # Not a metrics review any more.
    assert client.post(f"/api/v1/jobs/{job.id}/review/video-metrics", json={}).status_code == 409


def test_a_metrics_report_without_an_open_review_cannot_be_accepted(tmp_path: Path) -> None:
    comparison = tmp_path / "comparison"
    comparison.mkdir()
    report = _metrics_report([])
    report["quality_gate"]["status"] = "passed_with_warnings"
    (comparison / "video-metrics.json").write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(ReviewError):
        accept_video_metrics(tmp_path)
