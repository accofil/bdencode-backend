"""The web UI's CPU policy: the API side, the root helper and their units."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bdencode.api import create_app
from bdencode.config import Settings
from bdencode.cpu_policy import CpuPolicy, NightWindow, effective_share, load_policy
from bdencode.db import Database

ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location("bdencode_cpu_policy_helper", ROOT / "install" / "cpu_policy.py")
assert SPEC is not None and SPEC.loader is not None
helper = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = helper
SPEC.loader.exec_module(helper)

NIGHT = {"enabled": True, "percent": 100, "start": "23:00", "end": "07:00"}


def utc(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, 4, hour, minute, tzinfo=timezone.utc)


def write_policy(data_root: Path, document: object) -> Path:
    state = data_root / "state"
    state.mkdir(parents=True, exist_ok=True)
    path = state / "cpu-policy.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


class Systemctl:
    def __init__(self, fail: bool = False) -> None:
        self.calls: list[list[str]] = []
        self.fail = fail

    def __call__(self, argv):
        self.calls.append(list(argv))
        if self.fail:
            raise OSError("systemd is not reachable")


def _zone_database_available() -> bool:
    try:
        from zoneinfo import ZoneInfo

        ZoneInfo("Europe/Budapest")
        return True
    except Exception:  # Windows without the tzdata package
        return False


@pytest.mark.skipif(not _zone_database_available(), reason="needs the IANA time zone database")
def test_the_night_window_wraps_past_midnight_in_the_operator_s_zone() -> None:
    policy = CpuPolicy(day_percent=80, night=NightWindow(**NIGHT), timezone="Europe/Budapest")
    # 21:30 UTC is 23:30 in Budapest (CEST): night.
    assert effective_share(policy, utc(21, 30)) == (100, "night")
    # 05:30 UTC is 07:30 in Budapest: day again.
    assert effective_share(policy, utc(5, 30)) == (80, "day")
    assert effective_share(policy.model_copy(update={"night": NightWindow(enabled=False)}), utc(21, 30)) == (80, "day")
    same_day = policy.model_copy(update={"night": NightWindow(enabled=True, percent=40, start="09:00", end="17:00"), "timezone": "UTC"})
    assert effective_share(same_day, utc(12)) == (40, "night")
    assert effective_share(same_day, utc(17)) == (80, "day")


def test_the_helper_and_the_api_pick_the_same_share() -> None:
    document = {"schema_version": 1, "day_percent": 60, "night": NIGHT, "timezone": "Europe/Budapest"}
    policy = CpuPolicy.model_validate(document)
    validated = helper.validate(document)
    for hour in range(24):
        assert helper.effective(validated, utc(hour, 15)) == effective_share(policy, utc(hour, 15))


@pytest.mark.parametrize(
    "document",
    [
        {"schema_version": 1, "day_percent": 5},
        {"schema_version": 1, "day_percent": 80.5},
        {"schema_version": 1, "day_percent": 80, "night": {"enabled": "yes"}},
        {"schema_version": 1, "day_percent": 80, "night": {"enabled": True, "start": "24:00"}},
        {"schema_version": 1, "day_percent": 80, "timezone": "../../etc/passwd"},
        {"schema_version": 1, "day_percent": 80, "command": "rm -rf /"},
        {"schema_version": 2, "day_percent": 80},
    ],
)
def test_the_helper_rejects_anything_but_a_strict_policy(document: dict) -> None:
    with pytest.raises(helper.PolicyError):
        helper.validate(document)


def test_the_helper_applies_the_share_as_the_worker_s_runtime_quota(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    status_path = tmp_path / "status" / "status.json"
    write_policy(data_root, {"schema_version": 1, "day_percent": 60, "night": NIGHT, "timezone": "UTC"})
    systemctl = Systemctl()

    status = helper.apply(data_root, status_path=status_path, now=utc(12), cpus=24, run=systemctl)

    assert systemctl.calls == [
        ["systemctl", "set-property", "--runtime", "bdencode-worker.service", "CPUQuota=1440%"]
    ]
    assert status["state"] == "applied" and status["mode"] == "day" and status["percent"] == 60
    assert json.loads(status_path.read_text(encoding="utf-8"))["quota_percent"] == 1440

    night = helper.apply(data_root, status_path=status_path, now=utc(23, 30), cpus=24, run=systemctl)
    assert night["mode"] == "night" and systemctl.calls[-1][-1] == "CPUQuota=2400%"


def test_the_helper_leaves_the_quota_alone_without_a_valid_policy(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    status_path = tmp_path / "status.json"
    systemctl = Systemctl()

    assert helper.apply(data_root, status_path=status_path, run=systemctl)["state"] == "default"
    write_policy(data_root, {"schema_version": 1, "day_percent": 300})
    assert helper.apply(data_root, status_path=status_path, run=systemctl)["state"] == "invalid"
    (data_root / "state" / "cpu-policy.json").write_bytes(b"{" * 5000)
    assert helper.apply(data_root, status_path=status_path, run=systemctl)["state"] == "invalid"
    assert systemctl.calls == []

    write_policy(data_root, {"schema_version": 1, "day_percent": 50})
    failed = helper.apply(data_root, status_path=status_path, run=Systemctl(fail=True))
    assert failed["state"] == "failed" and "systemd is not reachable" in failed["message"]


@pytest.mark.skipif(os.name != "posix", reason="symbolic links need POSIX permissions")
def test_the_helper_never_follows_a_link_planted_as_the_policy(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    target = tmp_path / "elsewhere.json"
    target.write_text(json.dumps({"schema_version": 1, "day_percent": 50}), encoding="utf-8")
    (data_root / "state").mkdir(parents=True)
    (data_root / "state" / "cpu-policy.json").symlink_to(target)
    systemctl = Systemctl()

    status = helper.apply(data_root, status_path=tmp_path / "status.json", run=systemctl)

    assert status["state"] == "invalid" and systemctl.calls == []


@pytest.fixture
def api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = tmp_path / "source"
    source.mkdir()
    settings = Settings(data_root=tmp_path / "data", source_roots=(source,), cpu_limit_percent=70).validate()
    settings.create_directories()
    monkeypatch.setenv("BDENCODE_CPU_POLICY_STATUS_PATH", str(tmp_path / "missing-status.json"))
    return TestClient(create_app(Database(tmp_path / "state.sqlite3"), settings=settings)), settings, tmp_path


def test_the_api_saves_the_policy_for_the_helper_and_reports_what_applies(api, monkeypatch: pytest.MonkeyPatch) -> None:
    client, settings, tmp_path = api

    initial = client.get("/api/v1/system/cpu-policy").json()
    assert initial["saved"] is False
    assert initial["policy"]["day_percent"] == 70
    assert initial["applied"] is None
    assert client.get("/api/v1/capabilities").json()["constraints"]["cpu_budget_fraction"] == 0.7

    body = {
        "schema_version": 1,
        "day_percent": 50,
        "night": {"enabled": True, "percent": 90, "start": "22:30", "end": "06:00"},
        "timezone": "Europe/Budapest",
    }
    saved = client.put("/api/v1/system/cpu-policy", json=body)
    assert saved.status_code == 200, saved.text
    assert saved.json()["saved"] is True
    policy, from_file = load_policy(settings)
    assert from_file and policy.night.percent == 90
    # The helper reads exactly what the API wrote.
    assert helper.validate(json.loads((settings.state_root / "cpu-policy.json").read_text(encoding="utf-8")))["night_start"] == 22 * 60 + 30

    assert client.put("/api/v1/system/cpu-policy", json={**body, "day_percent": 5}).status_code == 422
    assert client.put("/api/v1/system/cpu-policy", json={**body, "timezone": "../x"}).status_code == 422

    status = tmp_path / "status.json"
    status.write_text(json.dumps({"state": "applied", "mode": "night", "percent": 90, "quota_percent": 2160}), encoding="utf-8")
    monkeypatch.setenv("BDENCODE_CPU_POLICY_STATUS_PATH", str(status))
    view = client.get("/api/v1/system/cpu-policy").json()
    assert view["applied"]["percent"] == 90 and view["applied"]["mode"] == "night"
    assert client.get("/api/v1/capabilities").json()["constraints"]["cpu_budget_fraction"] == 0.9


def test_the_units_and_the_installer_wire_the_helper() -> None:
    service = (ROOT / "deploy" / "systemd" / "bdencode-cpu-policy.service.in").read_text(encoding="utf-8")
    path_unit = (ROOT / "deploy" / "systemd" / "bdencode-cpu-policy.path.in").read_text(encoding="utf-8")
    timer = (ROOT / "deploy" / "systemd" / "bdencode-cpu-policy.timer").read_text(encoding="utf-8")
    installer = (ROOT / "install" / "install.sh").read_text(encoding="utf-8")
    uninstaller = (ROOT / "install" / "uninstall.sh").read_text(encoding="utf-8")

    assert "ExecStart=/usr/local/libexec/bdencode-cpu-policy apply" in service
    assert "Environment=BDENCODE_DATA_ROOT=@DATA_ROOT@" in service
    assert "PathChanged=@DATA_ROOT@/state/cpu-policy.json" in path_unit
    assert "OnCalendar=*:0/5" in timer
    assert '"$repo_root/install/cpu_policy.py"' in installer
    assert "/usr/local/libexec/bdencode-cpu-policy 0755" in installer
    assert "bdencode-cpu-policy.path bdencode-cpu-policy.timer" in installer
    for name in (
        "bdencode-cpu-policy.service",
        "bdencode-cpu-policy.path",
        "bdencode-cpu-policy.timer",
        "/usr/local/libexec/bdencode-cpu-policy",
    ):
        assert name in uninstaller
