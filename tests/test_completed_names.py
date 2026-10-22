"""A taken output name is refused when the plan is validated and approved,
not after the encode (3.11.2)."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from bdencode.api import create_app
from bdencode.completed_names import OUTPUT_NAME_TAKEN, output_name_taken
from bdencode.config import Settings
from bdencode.db import Database
from test_api import scan_result, valid_selection

NAME = "Film.1080p.BluRay.x264"


def release(root: Path, name: str, owner: dict | None) -> Path:
    directory = root / name
    directory.mkdir(parents=True)
    (directory / f"{name}.mkv").write_bytes(b"mkv")
    if owner is not None:
        (directory / ".bdencode-owner.json").write_bytes(json.dumps(owner).encode())
    return directory


def test_an_existing_release_takes_the_name(tmp_path: Path) -> None:
    release(tmp_path, NAME, {"schema_version": 2, "output_name": NAME, "mux_sha256": "0" * 64})

    assert output_name_taken(tmp_path, NAME, "job-1")
    assert not output_name_taken(tmp_path, f"{NAME}-TAG", "job-1")


def test_an_empty_folder_or_the_job_s_own_legacy_release_is_free(tmp_path: Path) -> None:
    (tmp_path / NAME).mkdir()
    assert not output_name_taken(tmp_path, NAME, "job-1")

    release(tmp_path, "Old.1080p.BluRay.x264", {"schema_version": 1, "job_id": "job-1"})
    assert not output_name_taken(tmp_path, "Old.1080p.BluRay.x264", "job-1")
    assert output_name_taken(tmp_path, "Old.1080p.BluRay.x264", "job-2")


def test_a_folder_without_an_owner_record_is_taken(tmp_path: Path) -> None:
    release(tmp_path, NAME, None)
    assert output_name_taken(tmp_path, NAME, "job-1")


def test_validation_and_approval_refuse_a_taken_name(tmp_path: Path) -> None:
    source = tmp_path / "source"
    (source / "Film").mkdir(parents=True)
    settings = Settings(data_root=tmp_path / "data", source_roots=(source,)).validate()
    settings.create_directories()
    release(settings.completed_root, NAME, {"schema_version": 2, "output_name": NAME, "mux_sha256": "0" * 64})
    with TestClient(create_app(Database(tmp_path / "api.sqlite3"), settings=settings)) as client:
        job = client.post("/api/v1/jobs", json={"source_path": str(source / "Film"), "name": "Film"}).json()
        client.post("/api/v1/jobs/claim-next")
        scan = client.post("/api/v1/scans", json={"job_id": job["id"]}).json()
        client.patch(f"/api/v1/scans/{scan['id']}", json={"status": "AWAITING_SELECTION", "result": scan_result()})
        job = client.get(f"/api/v1/jobs/{job['id']}").json()

        body = {"selection": valid_selection(), "expected_version": job["version"]}
        validated = client.post(f"/api/v1/jobs/{job['id']}/selection/validate", json=body)
        approved = client.post(f"/api/v1/jobs/{job['id']}/selection", json=body)

        for response in (validated, approved):
            assert response.status_code == 422
            assert response.json()["code"] == OUTPUT_NAME_TAKEN
            assert response.json()["context"] == {"output_name": NAME}
        assert client.get(f"/api/v1/jobs/{job['id']}").json()["selection"] is None

        renamed = {**valid_selection(), "output_name": f"{NAME}-TAG.mkv"}
        ok = client.post(
            f"/api/v1/jobs/{job['id']}/selection/validate",
            json={"selection": renamed, "expected_version": job["version"]},
        )
        assert ok.status_code == 200, ok.text
