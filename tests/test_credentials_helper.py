"""The root helper that stores API keys submitted on the System page."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "bdencode_credentials_helper", ROOT / "install" / "credentials_helper.py"
)
assert SPEC is not None and SPEC.loader is not None
helper = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = helper
SPEC.loader.exec_module(helper)

KEY = "sk-ant-api03-" + "k" * 40
REQUEST_ID = "0123456789abcdef0123456789abcdef"
posix_only = pytest.mark.skipif(os.name != "posix", reason="uid, chown and 0700 modes")


def test_requests_are_validated_strictly() -> None:
    good = {
        "schema_version": 1,
        "request_id": REQUEST_ID,
        "credential": "anthropic-api-key",
        "action": "set",
        "value": KEY,
    }
    assert helper.validate(good) == (REQUEST_ID, "anthropic-api-key", "set", KEY)
    assert helper.validate({**{k: v for k, v in good.items() if k != "value"}, "action": "delete"})[2] == "delete"
    for bad in (
        {**good, "credential": "imgbb-api-key"},
        {**good, "credential": "../../etc/shadow"},
        {**good, "value": "sk-proj-" + "x" * 40},  # an OpenAI key for Claude
        {**good, "credential": "openai-api-key", "value": KEY},
        {**good, "value": KEY + "\nExecStart=/bin/sh"},
        {**good, "request_id": "../x"},
        {**good, "extra": 1},
        {**good, "action": "run"},
        {**good, "schema_version": 2},
    ):
        with pytest.raises(helper.RequestError):
            helper.validate(bad)


class FakeSystem:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.inputs: list[str | None] = []

    def __call__(self, argv, input=None):  # noqa: A002 - mirrors subprocess.run
        self.calls.append(list(argv))
        self.inputs.append(input)
        if argv[:2] == ["systemd-creds", "encrypt"]:
            Path(argv[-1]).write_text("encrypted:" + argv[2], encoding="utf-8")


def _setup(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    run_dir = tmp_path / "run"
    credentials = tmp_path / "credentials"
    run_dir.mkdir()
    credentials.mkdir(mode=0o700)
    os.chmod(credentials, 0o700)
    return run_dir, credentials, tmp_path / "credential.conf", tmp_path / "status.json"


def _request(run_dir: Path, document: dict) -> Path:
    path = run_dir / f"credential-request-{document.get('request_id', 'x')}.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    os.chmod(path, 0o600)
    return path


@posix_only
def test_a_key_is_encrypted_from_stdin_bound_and_the_api_restarted(tmp_path: Path) -> None:
    run_dir, credentials, dropin, status = _setup(tmp_path)
    request = _request(
        run_dir,
        {"schema_version": 1, "request_id": REQUEST_ID, "credential": "anthropic-api-key", "action": "set", "value": KEY},
    )
    system = FakeSystem()
    ids = (os.getuid(), os.getgid())
    # The real unit runs with UMask=0077 and the status directory is new.
    status = tmp_path / "lib" / "credentials" / "status.json"
    previous_umask = os.umask(0o077)
    try:
        results = helper.process(
            request_directory=run_dir,
            credential_directory=credentials,
            user="ignored",
            dropin=dropin,
            status_path=status,
            run=system,
            ids=ids,
        )
    finally:
        os.umask(previous_umask)

    # The API (not root) reads the outcome.
    assert status.parent.stat().st_mode & 0o777 == 0o755
    assert status.stat().st_mode & 0o777 == 0o644
    assert not request.exists()
    assert results[0]["state"] == "applied"
    encrypt = system.calls[0]
    assert encrypt[:4] == ["systemd-creds", "encrypt", "--name=anthropic-api-key", "-"]
    assert all(KEY not in part for call in system.calls for part in call)
    assert system.inputs[0] == KEY
    stored = credentials / "anthropic-api-key.cred"
    assert stored.stat().st_mode & 0o777 == 0o600
    assert dropin.read_text(encoding="utf-8") == (
        f"[Service]\nLoadCredentialEncrypted=anthropic-api-key:{stored}\n"
    )
    assert ["systemctl", "daemon-reload"] in system.calls
    assert ["systemctl", "try-restart", "bdencode-api.service"] in system.calls
    report = status.read_text(encoding="utf-8")
    assert KEY not in report
    assert json.loads(report)["results"][0]["request_id"] == REQUEST_ID
    assert json.loads(report)["bound"] == ["anthropic-api-key"]


@posix_only
def test_delete_unbinds_and_bad_requests_change_nothing(tmp_path: Path) -> None:
    run_dir, credentials, dropin, status = _setup(tmp_path)
    (credentials / "openai-api-key.cred").write_text("old", encoding="utf-8")
    os.chmod(credentials / "openai-api-key.cred", 0o600)
    dropin.write_text("[Service]\nLoadCredentialEncrypted=openai-api-key:x\n", encoding="utf-8")
    _request(run_dir, {"schema_version": 1, "request_id": REQUEST_ID, "credential": "openai-api-key", "action": "delete"})
    _request(run_dir, {"schema_version": 1, "request_id": "f" * 32, "credential": "imgbb-api-key", "action": "delete"})
    (run_dir / "unrelated.json").write_text("{}", encoding="utf-8")
    system = FakeSystem()

    results = helper.process(
        request_directory=run_dir,
        credential_directory=credentials,
        user="ignored",
        dropin=dropin,
        status_path=status,
        run=system,
        ids=(os.getuid(), os.getgid()),
    )

    assert sorted(item["state"] for item in results) == ["applied", "rejected"]
    assert not (credentials / "openai-api-key.cred").exists()
    assert not dropin.exists()  # nothing left to bind
    assert [p.name for p in run_dir.iterdir()] == ["unrelated.json"]


@posix_only
def test_a_foreign_owner_or_open_directory_is_refused(tmp_path: Path) -> None:
    run_dir, credentials, dropin, status = _setup(tmp_path)
    os.chmod(credentials, 0o755)
    _request(
        run_dir,
        {"schema_version": 1, "request_id": REQUEST_ID, "credential": "anthropic-api-key", "action": "set", "value": KEY},
    )
    system = FakeSystem()
    results = helper.process(
        request_directory=run_dir,
        credential_directory=credentials,
        user="ignored",
        dropin=dropin,
        status_path=status,
        run=system,
        ids=(os.getuid(), os.getgid()),
    )
    assert results[0]["state"] == "rejected"
    assert system.calls == []

    _request(
        run_dir,
        {"schema_version": 1, "request_id": REQUEST_ID, "credential": "anthropic-api-key", "action": "set", "value": KEY},
    )
    results = helper.process(
        request_directory=run_dir,
        credential_directory=credentials,
        user="ignored",
        dropin=dropin,
        status_path=status,
        run=system,
        ids=(os.getuid() + 1, os.getgid()),
    )
    assert results[0]["state"] == "rejected"
    assert not list(run_dir.iterdir())


def test_units_installer_and_uninstaller_wire_the_helper() -> None:
    service = (ROOT / "deploy/systemd/bdencode-credentials.service.in").read_text(encoding="utf-8")
    path_unit = (ROOT / "deploy/systemd/bdencode-credentials.path.in").read_text(encoding="utf-8")
    api_unit = (ROOT / "deploy/systemd/bdencode-api.service.in").read_text(encoding="utf-8")
    installer = (ROOT / "install/install.sh").read_text(encoding="utf-8")
    uninstaller = (ROOT / "install/uninstall.sh").read_text(encoding="utf-8")

    assert "ExecStart=/usr/local/libexec/bdencode-credentials process" in service
    assert "Environment=BDENCODE_CREDENTIAL_DIR=@CREDENTIAL_DIR@" in service
    assert "PrivateNetwork=true" in service
    assert "PathExistsGlob=/run/bdencode-api/credential-request-*.json" in path_unit
    assert "RuntimeDirectory=bdencode-api" in api_unit
    assert "RuntimeDirectoryMode=0700" in api_unit
    assert '"$repo_root/install/credentials_helper.py"' in installer
    assert "/usr/local/libexec/bdencode-credentials 0755" in installer
    assert 's|@CREDENTIAL_DIR@|$credential_directory|g' in installer
    assert "bdencode-credentials.path" in installer
    names = installer.split("api_credential_names=(", 1)[1].split(")", 1)[0].split()
    assert tuple(names) == helper.API_CREDENTIALS
    for name in (
        "bdencode-credentials.service",
        "bdencode-credentials.path",
        "/usr/local/libexec/bdencode-credentials",
        "anthropic-api-key.cred",
    ):
        assert name in uninstaller
