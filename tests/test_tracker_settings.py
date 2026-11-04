from __future__ import annotations

from pathlib import Path
import re

from fastapi.testclient import TestClient
import pytest

from bdencode.api import create_app
from bdencode.config import Settings
from bdencode.db import Database
from bdencode.tracker_settings import (
    SECRET_CREDENTIALS,
    TrackerSettings,
    load_settings,
    save_settings,
    settings_path,
    tracker_status,
    validate_secret,
)

ROOT = Path(__file__).resolve().parents[1]


def test_the_helper_and_the_installer_know_the_new_credentials() -> None:
    helper = (ROOT / "install" / "credentials_helper.py").read_text(encoding="utf-8")
    installer = (ROOT / "install" / "install.sh").read_text(encoding="utf-8")
    names = re.search(r"api_credential_names=\((.*?)\)", installer, re.S)
    assert names is not None
    for credential in SECRET_CREDENTIALS.values():
        assert f'"{credential}"' in helper
        assert credential in names.group(1).split()


def test_the_api_service_may_write_the_seeding_folder() -> None:
    unit = (ROOT / "deploy" / "systemd" / "bdencode-api.service.in").read_text(encoding="utf-8")
    installer = (ROOT / "install" / "install.sh").read_text(encoding="utf-8")
    assert "@DATA_ROOT@/seeding" in unit
    assert '"$data_root/seeding"' in installer


def test_secret_validation_never_repeats_the_value() -> None:
    assert validate_secret("aither", "a" * 40) == "a" * 40
    assert validate_secret("ncore", "nick=a; pass=b") == "nick=a; pass=b"
    assert validate_secret("qbittorrent", "pa ss") == "pa ss"
    for kind, value in (("aither", "short-secret"), ("ncore", "no-cookies-secret"), ("qbittorrent", "bad\nsecret")):
        with pytest.raises(ValueError) as caught:
            validate_secret(kind, value)
        assert "secret" not in str(caught.value)


def test_settings_round_trip_and_status_without_secrets(tmp_path: Path) -> None:
    path = settings_path(tmp_path)
    assert load_settings(path) == TrackerSettings()
    save_settings(path, TrackerSettings(qbittorrent_url="http://127.0.0.1:8080/", qbittorrent_username="user"))
    (tmp_path / "creds").mkdir()
    (tmp_path / "creds" / "tracker-aither-api-token.cred").write_text("encrypted", encoding="utf-8")

    status = tracker_status(tmp_path, {"BDENCODE_CREDENTIAL_DIR": str(tmp_path / "creds")})

    assert status["aither"] == {"configured": True}
    assert status["ncore"] == {"configured": False}
    assert status["qbittorrent"] == {
        "url": "http://127.0.0.1:8080",
        "username": "user",
        "password_set": False,
        "configured": True,
    }
    assert "encrypted" not in str(status)


def test_a_broken_settings_file_counts_as_empty(tmp_path: Path) -> None:
    path = settings_path(tmp_path)
    path.write_text("{not json", encoding="utf-8")

    assert load_settings(path) == TrackerSettings()


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    source = tmp_path / "source"
    source.mkdir()
    settings = Settings(data_root=tmp_path / "data", source_roots=(source,)).validate()
    settings.create_directories()
    database = Database(settings.resolved_database_path)
    database.initialize()
    return TestClient(create_app(database, settings=settings))


def test_the_api_reports_uploads_and_saves_the_address(client: TestClient) -> None:
    capabilities = client.get("/api/v1/capabilities").json()
    assert capabilities["constraints"]["tracker_upload"] == {"trackers": ["aither", "ncore"]}

    saved = client.put(
        "/api/v1/system/tracker-settings",
        json={"schema_version": 1, "qbittorrent_url": "http://127.0.0.1:9000", "qbittorrent_username": "user"},
    )
    assert saved.status_code == 200
    assert saved.json()["qbittorrent"]["url"] == "http://127.0.0.1:9000"
    assert client.get("/api/v1/system/trackers").json()["qbittorrent"]["username"] == "user"

    refused = client.put(
        "/api/v1/system/tracker-settings",
        json={"schema_version": 1, "qbittorrent_url": "http://user:hunter2@host", "qbittorrent_username": ""},
    )
    assert refused.status_code == 422


def test_a_bad_secret_is_refused_without_echoing_it(client: TestClient) -> None:
    response = client.put("/api/v1/system/tracker-credentials/aither", json={"value": "hunter2"})

    assert response.status_code >= 400
    assert "hunter2" not in response.text


def test_unknown_secret_kinds_are_refused(client: TestClient) -> None:
    assert client.put("/api/v1/system/tracker-credentials/other", json={"value": "x"}).status_code == 422
    assert client.post("/api/v1/system/trackers/other/check").status_code == 422


def test_the_connection_check_says_when_no_login_is_set(client: TestClient) -> None:
    response = client.post("/api/v1/system/trackers/aither/check")

    assert response.status_code == 409
    assert "System page" in response.json()["detail"]


def test_builtin_profiles_offer_the_upload(client: TestClient) -> None:
    response = client.get("/api/v1/release-profiles")
    assert response.status_code == 200
    document = response.json()
    profiles = document if isinstance(document, list) else document.get("items") or document.get("profiles")
    by_id = {item["profile_id"]: item for item in profiles}
    assert by_id["aither"]["supports_upload"] is True
    assert by_id["ncore"]["supports_dupe_check"] is True
