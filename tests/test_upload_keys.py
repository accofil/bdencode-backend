"""Image host keys and host order set on the System page (3.11)."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from bdencode import upload_settings
from bdencode.api import create_app
from bdencode.config import Settings
from bdencode.db import Database
from bdencode.qc.catbox import CatboxClient
from bdencode.qc.image_upload import ImageUploadError
from bdencode.qc.imgbb import ImgBBClient
from bdencode.secrets import LIVE_CREDENTIAL_DIR_ENV, SecretUnavailable, read_secret
from bdencode.upload_settings import (
    UploadPreferences,
    load_preferences,
    save_preferences,
    settings_path,
    validate_upload_key,
)
from bdencode.worker import PipelineWorker

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "bdencode_credentials_helper_upload", ROOT / "install" / "credentials_helper.py"
)
assert SPEC is not None and SPEC.loader is not None
helper = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = helper
SPEC.loader.exec_module(helper)

# Distinct from REQUEST_ID: the status file legitimately names the request.
IMGBB_KEY = "9f8e7d6c5b4a39281706f5e4d3c2b1a0"
NEW_IMGBB_KEY = "fedcba9876543210fedcba9876543210"
FREEIMAGE_KEY = "6d207e02198a847aa98d0a2a901485a5"
USERHASH = "a1b2c3d4e5f6a7b8c9d0e1f2a"
PNG = b"\x89PNG\r\n\x1a\nmock-png-body"
REQUEST_ID = "0123456789abcdef0123456789abcdef"
posix_only = pytest.mark.skipif(os.name != "posix", reason="uid, chown and dir_fd")


# -- format validation --------------------------------------------------------
def test_keys_are_checked_per_host_before_saving() -> None:
    assert validate_upload_key("imgbb", IMGBB_KEY) == IMGBB_KEY
    assert validate_upload_key("freeimage", FREEIMAGE_KEY) == FREEIMAGE_KEY
    assert validate_upload_key("catbox", USERHASH) == USERHASH
    # A pasted key often carries the line end; it is not part of the key.
    assert validate_upload_key("imgbb", f"  {IMGBB_KEY}\n") == IMGBB_KEY
    for host, key in (
        ("imgbb", IMGBB_KEY[:-1]),  # too short
        ("imgbb", IMGBB_KEY + "0"),  # too long
        ("imgbb", IMGBB_KEY[:16] + " " + IMGBB_KEY[17:]),  # whitespace inside
        ("imgbb", IMGBB_KEY[:16] + "\n" + IMGBB_KEY[17:]),  # a line break inside
        ("imgbb", IMGBB_KEY[:31] + "-"),
        ("freeimage", "sk-proj-" + "x" * 24),
        ("freeimage", ""),
        ("catbox", "short"),
        ("catbox", USERHASH + "\nExecStart=/bin/sh"),
        ("catbox", "x" * 65),
    ):
        with pytest.raises(ValueError):
            validate_upload_key(host, key)  # type: ignore[arg-type]


def test_the_helper_accepts_exactly_the_formats_the_api_accepts() -> None:
    for host, credential in upload_settings.HOST_CREDENTIALS.items():
        assert helper.SETTABLE[credential].pattern == upload_settings.HOST_KEY_PATTERNS[host].pattern
    assert tuple(upload_settings.HOST_CREDENTIALS.values()) == helper.WORKER_CREDENTIALS
    good = {
        "schema_version": 1,
        "request_id": REQUEST_ID,
        "credential": "imgbb-api-key",
        "action": "set",
        "value": IMGBB_KEY,
    }
    assert helper.validate(good) == (REQUEST_ID, "imgbb-api-key", "set", IMGBB_KEY)
    assert helper.validate({**good, "credential": "catbox-userhash", "value": USERHASH})[1] == "catbox-userhash"
    for bad in (
        {**good, "value": IMGBB_KEY + "\n"},
        {**good, "value": "sk-ant-api03-" + "k" * 40},
        {**good, "credential": "catbox-userhash", "value": "x"},
        {**good, "credential": "tracker-aither-api-token"},
    ):
        with pytest.raises(helper.RequestError):
            helper.validate(bad)


def test_installer_binds_the_names_the_helper_changes() -> None:
    installer = (ROOT / "install/install.sh").read_text(encoding="utf-8")
    names = installer.split("worker_credential_names=(", 1)[1].split(")", 1)[0].split()
    assert tuple(names) == helper.WORKER_CREDENTIALS
    uninstaller = (ROOT / "install/uninstall.sh").read_text(encoding="utf-8")
    for name in helper.WORKER_CREDENTIALS:
        assert f"{name}.cred" in uninstaller
    service = (ROOT / "deploy/systemd/bdencode-credentials.service.in").read_text(encoding="utf-8")
    assert "/etc/systemd/system/bdencode-worker.service.d" in service
    worker = (ROOT / "deploy/systemd/bdencode-worker.service.in").read_text(encoding="utf-8")
    assert "RuntimeDirectory=bdencode-worker\n" in worker
    assert "RuntimeDirectoryMode=0700\n" in worker
    live = f"{helper.WORKER_RUNTIME_DIRECTORY.as_posix()}/{helper.LIVE_SUBDIRECTORY}"
    assert f"Environment={LIVE_CREDENTIAL_DIR_ENV}={live}\n" in worker


# -- host order ---------------------------------------------------------------
def test_host_order_must_name_every_host_once_and_survives_a_broken_file(tmp_path: Path) -> None:
    path = settings_path(tmp_path)
    assert load_preferences(path).provider_order is None
    assert upload_settings.host_order(load_preferences(path)) == ["imgbb", "catbox", "freeimage"]
    save_preferences(path, UploadPreferences(provider_order=["freeimage", "imgbb", "catbox"]))
    assert b"\r" not in path.read_bytes()
    assert load_preferences(path).provider_order == ["freeimage", "imgbb", "catbox"]
    for bad in (["imgbb", "imgbb", "catbox"], ["imgbb", "catbox"], ["imgbb", "catbox", "freeimage", "x"]):
        with pytest.raises(ValueError):
            UploadPreferences(provider_order=bad)  # type: ignore[arg-type]
    path.write_bytes(b"{not json")
    assert load_preferences(path).provider_order is None


class _Host:
    def __init__(self, name: str) -> None:
        self.provider_name = name


def test_the_worker_uses_the_saved_order_from_its_next_upload_step(tmp_path: Path) -> None:
    state = tmp_path / "state"
    worker = SimpleNamespace(
        settings=SimpleNamespace(state_root=state),
        upload_client_factory=None,
        upload_client_factories=tuple(
            (lambda name=name: _Host(name)) for name in ("imgbb", "catbox", "freeimage")
        ),
    )

    def chain() -> list[str]:
        return [client.provider_name for client in PipelineWorker._image_upload_clients(worker)]  # type: ignore[arg-type]

    assert chain() == ["imgbb", "catbox", "freeimage"]
    save_preferences(settings_path(state), UploadPreferences(provider_order=["freeimage", "catbox", "imgbb"]))
    assert chain() == ["freeimage", "catbox", "imgbb"]
    save_preferences(settings_path(state), UploadPreferences(provider_order=None))
    assert chain() == ["imgbb", "catbox", "freeimage"]


# -- a running worker picks up a changed key ----------------------------------
def _credentials(tmp_path: Path) -> tuple[Path, Path]:
    started = tmp_path / "systemd-credentials"
    live = tmp_path / "live"
    started.mkdir()
    live.mkdir()
    (started / "imgbb-api-key").write_bytes(IMGBB_KEY.encode())
    return started, live


def test_the_changed_copy_wins_over_the_credential_loaded_at_start(tmp_path: Path) -> None:
    started, live = _credentials(tmp_path)
    env = {"CREDENTIALS_DIRECTORY": str(started), LIVE_CREDENTIAL_DIR_ENV: str(live)}
    assert read_secret("imgbb-api-key", environment=env) == IMGBB_KEY
    (live / "imgbb-api-key").write_bytes(NEW_IMGBB_KEY.encode() + b"\n")
    assert read_secret("imgbb-api-key", environment=env) == NEW_IMGBB_KEY
    # Deleted on the System page: the copy loaded at start is stale.
    (live / "imgbb-api-key").write_bytes(b"")
    with pytest.raises(SecretUnavailable):
        read_secret("imgbb-api-key", environment=env)
    # A key that was never bound at start but was set later.
    (live / "freeimage-api-key").write_bytes(FREEIMAGE_KEY.encode())
    assert read_secret("freeimage-api-key", environment=env) == FREEIMAGE_KEY
    (live / "odd").mkdir()
    with pytest.raises(SecretUnavailable):
        read_secret("odd", environment=env)
    with pytest.raises(SecretUnavailable):
        read_secret("../imgbb-api-key", environment=env)
    # Without the variable (the API, older units) nothing changes.
    assert read_secret("imgbb-api-key", environment={"CREDENTIALS_DIRECTORY": str(started)}) == IMGBB_KEY


def _imgbb_transport(seen: list[bytes]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            seen.append(request.content)
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "data": {"url": "https://i.ibb.co/proof.png", "url_viewer": "https://ibb.co/proof"},
                },
            )
        return httpx.Response(200, content=PNG, headers={"content-type": "image/png"})

    return httpx.MockTransport(handler)


def test_a_running_uploader_uses_the_new_key_on_its_next_upload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    started, live = _credentials(tmp_path)
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(started))
    monkeypatch.setenv(LIVE_CREDENTIAL_DIR_ENV, str(live))
    image = tmp_path / "proof.png"
    image.write_bytes(PNG)
    seen: list[bytes] = []
    # One client for the whole worker life, built before the key changes.
    uploader = ImgBBClient(client=httpx.Client(transport=_imgbb_transport(seen)))

    uploader.upload_png(image)
    (live / "imgbb-api-key").write_bytes(NEW_IMGBB_KEY.encode())
    uploader.upload_png(image)
    assert IMGBB_KEY.encode() in seen[0] and NEW_IMGBB_KEY.encode() not in seen[0]
    assert NEW_IMGBB_KEY.encode() in seen[1] and IMGBB_KEY.encode() not in seen[1]

    (live / "imgbb-api-key").write_bytes(b"")
    with pytest.raises(ImageUploadError) as deleted:
        uploader.upload_png(image)
    assert deleted.value.allow_fallback is True  # the next host may take over
    assert len(seen) == 2

    # Catbox without its user hash uploads anonymously.
    (live / "catbox-userhash").write_bytes(b"")
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(started))
    (started / "catbox-userhash").write_bytes(USERHASH.encode())
    bodies: list[bytes] = []

    def catbox(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            bodies.append(request.content)
            return httpx.Response(200, text="https://files.catbox.moe/abc123.png")
        return httpx.Response(200, content=PNG, headers={"content-type": "image/png"})

    CatboxClient(client=httpx.Client(transport=httpx.MockTransport(catbox))).upload_png(image)
    assert USERHASH.encode() not in bodies[0]


# -- the System page endpoints -------------------------------------------------
def _app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, Path, Path]:
    runtime = tmp_path / "run"
    runtime.mkdir()
    credentials = tmp_path / "credentials"
    credentials.mkdir()
    monkeypatch.setenv("BDENCODE_CREDENTIAL_REQUEST_DIR", str(runtime))
    monkeypatch.setenv("BDENCODE_CREDENTIAL_STATUS_PATH", str(tmp_path / "status.json"))
    monkeypatch.setenv("BDENCODE_CREDENTIAL_DIR", str(credentials))
    source = tmp_path / "source"
    source.mkdir()
    settings = Settings(data_root=tmp_path / "data", source_roots=(source,)).validate()
    settings.create_directories()
    client = TestClient(create_app(Database(tmp_path / "keys.sqlite3"), settings=settings))
    return client, runtime, credentials


def test_system_page_sets_replaces_and_deletes_keys_without_echoing_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, runtime, credentials = _app(tmp_path, monkeypatch)
    with client:
        status = client.get("/api/v1/system/image-upload")
        assert status.status_code == 200
        document = status.json()
        assert document["provider_order"] == ["imgbb", "catbox", "freeimage"]
        assert document["custom_order"] is False
        assert document["key_management"]["available"] is True
        assert [(item["id"], item["configured"]) for item in document["hosts"]] == [
            ("imgbb", False),
            ("catbox", False),
            ("freeimage", False),
        ]
        assert [item["key_required"] for item in document["hosts"]] == [True, False, True]

        for bad in (IMGBB_KEY[:-1], IMGBB_KEY[:10] + " " + IMGBB_KEY[11:], IMGBB_KEY * 20):
            rejected = client.put("/api/v1/system/image-upload-credentials/imgbb", json={"api_key": bad})
            assert rejected.status_code == 422
            assert rejected.json()["code"] == "upload_key_invalid"
            assert bad not in rejected.text and bad.strip()[:20] not in rejected.text
        assert list(runtime.iterdir()) == []

        accepted = client.put("/api/v1/system/image-upload-credentials/imgbb", json={"api_key": IMGBB_KEY})
        assert accepted.status_code == 202
        assert IMGBB_KEY not in accepted.text
        request_id = accepted.json()["request_id"]
        assert accepted.json() == {"request_id": request_id, "host": "imgbb", "action": "set"}
        request = json.loads((runtime / f"credential-request-{request_id}.json").read_bytes())
        assert request["credential"] == "imgbb-api-key" and request["value"] == IMGBB_KEY

        # The helper stored it: the page sees "configured", never the key.
        (credentials / "imgbb-api-key.cred").write_bytes(b"encrypted:" + IMGBB_KEY.encode())
        (tmp_path / "status.json").write_bytes(
            json.dumps(
                {"results": [{"request_id": request_id, "credential": "imgbb-api-key", "state": "applied", "value": IMGBB_KEY}]}
            ).encode()
        )
        after = client.get("/api/v1/system/image-upload")
        assert after.json()["hosts"][0]["configured"] is True
        assert after.json()["key_management"]["results"][0]["state"] == "applied"
        assert IMGBB_KEY not in after.text
        runtime_report = client.get("/api/v1/ai-recommendation/status")
        assert IMGBB_KEY not in runtime_report.text

        userhash = client.put("/api/v1/system/image-upload-credentials/catbox", json={"api_key": USERHASH})
        assert userhash.status_code == 202
        deleted = client.delete("/api/v1/system/image-upload-credentials/freeimage")
        assert deleted.status_code == 202
        assert deleted.json()["action"] == "delete"
        assert client.put("/api/v1/system/image-upload-credentials/postimg", json={"api_key": IMGBB_KEY}).status_code == 422
        assert len(list(runtime.iterdir())) == 3

        monkeypatch.delenv("BDENCODE_CREDENTIAL_REQUEST_DIR")
        monkeypatch.delenv("RUNTIME_DIRECTORY", raising=False)
        unavailable = client.delete("/api/v1/system/image-upload-credentials/imgbb")
        assert unavailable.status_code == 422
        assert unavailable.json()["code"] == "upload_key_management_unavailable"
        assert client.get("/api/v1/system/image-upload").json()["key_management"]["available"] is False


def test_system_page_saves_the_host_order(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _runtime, _credentials = _app(tmp_path, monkeypatch)
    with client:
        saved = client.put(
            "/api/v1/system/image-upload-settings",
            json={"provider_order": ["catbox", "freeimage", "imgbb"]},
        )
        assert saved.status_code == 200
        assert saved.json()["provider_order"] == ["catbox", "freeimage", "imgbb"]
        assert saved.json()["custom_order"] is True
        assert [item["id"] for item in saved.json()["hosts"]] == ["catbox", "freeimage", "imgbb"]
        assert client.put(
            "/api/v1/system/image-upload-settings", json={"provider_order": ["catbox", "catbox", "imgbb"]}
        ).status_code == 422
        reset = client.put("/api/v1/system/image-upload-settings", json={"provider_order": None})
        assert reset.json()["provider_order"] == ["imgbb", "catbox", "freeimage"]
        assert reset.json()["custom_order"] is False


# -- the root helper ----------------------------------------------------------
class FakeSystem:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.inputs: list[str | None] = []

    def __call__(self, argv, input=None):  # noqa: A002 - mirrors subprocess.run
        self.calls.append(list(argv))
        self.inputs.append(input)
        if argv[:2] == ["systemd-creds", "encrypt"]:
            Path(argv[-1]).write_bytes(b"encrypted:" + argv[2].encode())


def _helper_dirs(tmp_path: Path) -> tuple[Path, Path, Path]:
    run_dir = tmp_path / "run"
    credentials = tmp_path / "credentials"
    worker_runtime = tmp_path / "bdencode-worker"
    run_dir.mkdir()
    credentials.mkdir(mode=0o700)
    os.chmod(credentials, 0o700)
    worker_runtime.mkdir(mode=0o700)
    return run_dir, credentials, worker_runtime


def _request(run_dir: Path, document: dict) -> None:
    path = run_dir / f"credential-request-{document['request_id']}.json"
    path.write_bytes(json.dumps(document).encode())
    os.chmod(path, 0o600)


def _process(tmp_path: Path, run_dir: Path, credentials: Path, worker_runtime: Path, system: FakeSystem):
    return helper.process(
        request_directory=run_dir,
        credential_directory=credentials,
        user="ignored",
        dropin=tmp_path / "api-credential.conf",
        worker_dropin=tmp_path / "worker-credential.conf",
        worker_runtime_directory=worker_runtime,
        status_path=tmp_path / "status.json",
        run=system,
        ids=(os.getuid(), os.getgid()),
    )


@posix_only
def test_an_image_host_key_reaches_the_running_worker_without_any_restart(tmp_path: Path) -> None:
    run_dir, credentials, worker_runtime = _helper_dirs(tmp_path)
    _request(
        run_dir,
        {"schema_version": 1, "request_id": REQUEST_ID, "credential": "imgbb-api-key", "action": "set", "value": IMGBB_KEY},
    )
    system = FakeSystem()
    results = _process(tmp_path, run_dir, credentials, worker_runtime, system)

    assert results[0]["state"] == "applied"
    assert "next upload" in results[0]["message"]
    assert system.inputs[0] == IMGBB_KEY
    assert all(IMGBB_KEY not in part for call in system.calls for part in call)
    stored = credentials / "imgbb-api-key.cred"
    assert (tmp_path / "worker-credential.conf").read_bytes() == (
        f"[Service]\nLoadCredentialEncrypted=imgbb-api-key:{stored}\n".encode()
    )
    assert not (tmp_path / "api-credential.conf").exists()
    assert ["systemctl", "daemon-reload"] in system.calls
    assert not any(call[:2] == ["systemctl", "try-restart"] for call in system.calls)
    assert not any("bdencode-worker.service" in part for call in system.calls for part in call)
    live = worker_runtime / "credentials"
    assert live.stat().st_mode & 0o777 == 0o700
    assert (live / "imgbb-api-key").read_bytes() == IMGBB_KEY.encode()
    assert (live / "imgbb-api-key").stat().st_mode & 0o777 == 0o600
    env = {LIVE_CREDENTIAL_DIR_ENV: str(live)}
    assert read_secret("imgbb-api-key", environment=env) == IMGBB_KEY
    report = (tmp_path / "status.json").read_text(encoding="utf-8")
    assert IMGBB_KEY not in report
    assert json.loads(report)["worker_bound"] == ["imgbb-api-key"]

    # Delete: the running worker must stop using the key it loaded at start.
    _request(run_dir, {"schema_version": 1, "request_id": "e" * 32, "credential": "imgbb-api-key", "action": "delete"})
    results = _process(tmp_path, run_dir, credentials, worker_runtime, system)
    assert results[0]["state"] == "applied"
    assert not stored.exists()
    assert not (tmp_path / "worker-credential.conf").exists()
    assert (live / "imgbb-api-key").read_bytes() == b""
    with pytest.raises(SecretUnavailable):
        read_secret("imgbb-api-key", environment=env)


@posix_only
def test_a_stopped_worker_loads_the_key_at_start_and_planted_links_are_not_followed(tmp_path: Path) -> None:
    run_dir, credentials, worker_runtime = _helper_dirs(tmp_path)
    worker_runtime.rmdir()  # the worker is not running
    _request(
        run_dir,
        {"schema_version": 1, "request_id": REQUEST_ID, "credential": "freeimage-api-key", "action": "set", "value": FREEIMAGE_KEY},
    )
    results = _process(tmp_path, run_dir, credentials, worker_runtime, FakeSystem())
    assert results[0]["state"] == "applied"
    assert "when it starts" in results[0]["message"]
    assert (credentials / "freeimage-api-key.cred").exists()

    worker_runtime.mkdir(mode=0o700)
    victim = tmp_path / "victim"
    victim.write_bytes(b"keep")
    (worker_runtime / "credentials").mkdir(mode=0o700)
    (worker_runtime / "credentials" / "freeimage-api-key").symlink_to(victim)
    (worker_runtime / "credentials" / ".freeimage-api-key.new").symlink_to(victim)
    _request(
        run_dir,
        {"schema_version": 1, "request_id": "d" * 32, "credential": "freeimage-api-key", "action": "set", "value": FREEIMAGE_KEY},
    )
    results = _process(tmp_path, run_dir, credentials, worker_runtime, FakeSystem())
    assert results[0]["state"] == "applied"
    assert victim.read_bytes() == b"keep"
    published = worker_runtime / "credentials" / "freeimage-api-key"
    assert not published.is_symlink() and published.read_bytes() == FREEIMAGE_KEY.encode()

    # A planted link in place of the key directory is refused.
    target = tmp_path / "elsewhere"
    target.mkdir()
    for child in (worker_runtime / "credentials").iterdir():
        child.unlink()
    (worker_runtime / "credentials").rmdir()
    (worker_runtime / "credentials").symlink_to(target)
    _request(
        run_dir,
        {"schema_version": 1, "request_id": "c" * 32, "credential": "freeimage-api-key", "action": "set", "value": FREEIMAGE_KEY},
    )
    results = _process(tmp_path, run_dir, credentials, worker_runtime, FakeSystem())
    assert results[0]["state"] == "failed"
    assert FREEIMAGE_KEY not in results[0]["message"]
    assert list(target.iterdir()) == []


@posix_only
def test_ai_and_upload_keys_in_one_batch_restart_only_the_api(tmp_path: Path) -> None:
    run_dir, credentials, worker_runtime = _helper_dirs(tmp_path)
    _request(
        run_dir,
        {"schema_version": 1, "request_id": "a" * 32, "credential": "anthropic-api-key", "action": "set", "value": "sk-ant-api03-" + "k" * 40},
    )
    _request(
        run_dir,
        {"schema_version": 1, "request_id": "b" * 32, "credential": "catbox-userhash", "action": "set", "value": USERHASH},
    )
    system = FakeSystem()
    results = _process(tmp_path, run_dir, credentials, worker_runtime, system)
    assert [item["state"] for item in results] == ["applied", "applied"]
    assert ["systemctl", "try-restart", "bdencode-api.service"] in system.calls
    assert system.calls.count(["systemctl", "daemon-reload"]) == 1
    assert "anthropic-api-key" in (tmp_path / "api-credential.conf").read_text(encoding="utf-8")
    worker_dropin = (tmp_path / "worker-credential.conf").read_text(encoding="utf-8")
    assert "catbox-userhash" in worker_dropin and "anthropic" not in worker_dropin
    assert (worker_runtime / "credentials" / "catbox-userhash").read_bytes() == USERHASH.encode()
    assert not (worker_runtime / "credentials" / "anthropic-api-key").exists()
    assert re.search(r"sk-ant", (tmp_path / "status.json").read_text(encoding="utf-8")) is None
