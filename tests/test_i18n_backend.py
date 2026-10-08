"""Texts the backend sends to the web UI follow the request's interface language."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from bdencode.api import create_app
from bdencode.config import Settings
from bdencode.db import Database
from bdencode.i18n import use_language
from bdencode.live_progress import LiveProgress, read_live
from bdencode.models import JobCreate
from bdencode.progress import EncodeProgress, encode_status_message
from bdencode.tracker_policy import TrackerProfile, tracker_findings
from test_api import awaiting_selection_job, make_client, valid_selection
from test_tracker_policy import PLAYLIST, pick

ENGLISH = {"Accept-Language": "en"}


def test_tracker_findings_of_the_validation_follow_the_language(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        job = awaiting_selection_job(client, warnings=[])
        selection = valid_selection()
        selection["tracker_profile"] = "ncore"
        selection["video"]["settings"] = {**selection["video"]["settings"], "bframes": 3}
        body = {"selection": selection, "expected_version": job["version"]}
        url = f"/api/v1/jobs/{job['id']}/selection/validate"

        hungarian = client.post(url, json=body)
        english = client.post(url, json=body, headers=ENGLISH)

    assert hungarian.status_code == 200 and english.status_code == 200
    hu_findings = {item["code"]: item["message"] for item in hungarian.json()["tracker_findings"]}
    en_findings = {item["code"]: item["message"] for item in english.json()["tracker_findings"]}
    assert hu_findings.keys() == en_findings.keys()
    assert hu_findings["ncore_bframes"] == "x264: legalább 5 egymás utáni B-frame kell (bframes ≥ 5)."
    assert en_findings["ncore_bframes"] == (
        "x264: at least 5 consecutive B-frames are required (bframes ≥ 5)."
    )


def test_track_plan_findings_follow_the_language() -> None:
    tracks = [pick("en-truehd", "copy", 1, "eng"), pick("hu-ac3", "copy", 2, "hun")]

    def messages() -> dict[str, str]:
        return {
            item.code: item.message
            for item in tracker_findings(
                TrackerProfile.AITHER, encoder="x265", playlist=PLAYLIST, tracks=tracks
            )
        }

    hungarian = messages()
    with use_language("en"):
        english = messages()
    assert hungarian["aither_language"] == (
        "Aitheren csak az eredeti nyelvű és az angol hang mehet (plusz kommentár); "
        "a(z) magyar sávot ki kell hagyni."
    )
    assert english["aither_language"] == (
        "Aither only allows original-language and English audio (plus commentary); "
        "omit the Hungarian track."
    )
    assert english["aither_compat_missing"] == (
        "TrueHD (English) needs a separate DD or DD+ compatibility track."
    )


def test_noise_profiles_and_aither_presets_follow_the_language(tmp_path: Path) -> None:
    with TestClient(create_app(Database(tmp_path / "api.sqlite3"))) as client:
        hungarian = client.get("/api/v1/profiles/x265/noise-profiles").json()
        english = client.get("/api/v1/profiles/x265/noise-profiles", headers=ENGLISH).json()
        hu_presets = client.get("/api/v1/profiles/x264/aither-presets").json()
        en_presets = client.get("/api/v1/profiles/x264/aither-presets", headers=ENGLISH).json()

    def by_id(items: list[dict[str, object]], key: str) -> dict[str, object]:
        return next(item for item in items if item["id"] == key)

    assert by_id(hungarian["profiles"], "light_denoise")["label"] == "Enyhe zajszűrés"
    light = by_id(english["profiles"], "light_denoise")
    assert light["label"] == "Light denoise"
    assert str(light["description"]).startswith("Encoder-built-in noise reduction")
    # The settings themselves do not depend on the language.
    assert light["settings"] == by_id(hungarian["profiles"], "light_denoise")["settings"]

    grain_hu = by_id(hu_presets["presets"], "aither_bd_quality_grain")
    grain_en = by_id(en_presets["presets"], "aither_bd_quality_grain")
    assert grain_hu["label"] == "Aither 1080p Quality – szemcsés film"
    assert grain_en["label"] == "Aither 1080p Quality – grainy film"
    assert grain_en["crf_hint"] == "CRF 15–17; typically 45–60% of the remux."
    assert "zárt GOP" in str(grain_hu["description"])
    assert "closed GOP" in str(grain_en["description"])


def test_live_step_labels_are_stored_in_both_languages_and_served_in_one(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    settings = Settings(data_root=tmp_path / "data", source_roots=(source,)).validate()
    settings.create_directories()
    database = Database(tmp_path / "state.sqlite3")
    job = database.create_job(JobCreate(source_path=str(source / "Disc"), name="Disc"))
    root = settings.job_root(job.id) / ".live"

    live = LiveProgress(root, min_interval=0)
    live.start("scan", ("Lemez beolvasása", "Reading the disc"))
    live.finish()
    live.start("crop-scan", ("Crop-keresés (GPU)", "Crop scan (GPU)"))
    live.update(0.5, detail=("3 / 6 kép feltöltve", "3 / 6 images uploaded"))
    live.side("index", ("Forrásindex", "Source index"), 0.25)

    with TestClient(create_app(database, settings=settings)) as client:
        hungarian = client.get(f"/api/v1/jobs/{job.id}/live").json()
        english = client.get(f"/api/v1/jobs/{job.id}/live", headers=ENGLISH).json()

    assert hungarian["step"]["label"] == "Crop-keresés (GPU)"
    assert hungarian["step"]["detail"] == "3 / 6 kép feltöltve"
    assert hungarian["step"]["side"]["index"]["label"] == "Forrásindex"
    assert hungarian["timeline"][0]["label"] == "Lemez beolvasása"
    assert english["step"]["label"] == "Crop scan (GPU)"
    assert english["step"]["detail"] == "3 / 6 images uploaded"
    assert english["step"]["side"]["index"] == {
        "label": "Source index",
        "fraction": 0.25,
        "done": False,
    }
    assert english["timeline"][0]["label"] == "Reading the disc"
    assert english["step"]["fraction"] == 0.5


def test_live_files_written_before_both_languages_are_served_unchanged(tmp_path: Path) -> None:
    live = LiveProgress(tmp_path / ".live", min_interval=0)
    live.start("encode", "Videókódolás", detail="régi részlet")
    with use_language("en"):
        view = read_live(tmp_path / ".live")
    assert view["step"]["label"] == "Videókódolás"
    assert view["step"]["detail"] == "régi részlet"


def test_the_encode_status_message_is_english() -> None:
    message = encode_status_message(
        EncodeProgress(
            stage_fraction=0.123,
            out_time_seconds=738.0,
            duration_seconds=6000.0,
            frame=17_700,
            fps=1.7,
            speed=0.07,
            eta_seconds=3723,
            protocol_status="continue",
            output_bytes=2_361_600_000,  # projected: 19.2 GB
        )
    )
    assert message == (
        "Encoding video: 12.3% · 1.7 fps · 0.07x · ETA 01:02:03 · projected video size ~19.2 GB"
    )


def test_the_ai_adviser_answers_in_the_interface_language() -> None:
    from bdencode.ai_recommendation import _instructions

    assert _instructions().endswith("Answer summary, rationale, and warnings in Hungarian.")
    with use_language("en"):
        assert _instructions().endswith("Answer summary, rationale, and warnings in English.")
