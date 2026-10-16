"""The worker is started again after a passing ExecCondition failure (a full disk)."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "install/worker_ensure.sh"

posix_only = pytest.mark.skipif(os.name == "nt", reason="needs a POSIX shell")


def test_the_timer_and_service_run_the_helper_without_firing_at_once() -> None:
    service = (ROOT / "deploy/systemd/bdencode-worker-ensure.service").read_text(encoding="utf-8")
    timer = (ROOT / "deploy/systemd/bdencode-worker-ensure.timer").read_text(encoding="utf-8")
    worker = (ROOT / "deploy/systemd/bdencode-worker.service.in").read_text(encoding="utf-8")
    recovery = (ROOT / "deploy/systemd/bdencode-runtime-recovery.conf.in").read_text(encoding="utf-8")

    assert "Type=oneshot" in service and "User=root" in service
    assert "ExecStart=/usr/local/libexec/bdencode-worker-ensure" in service
    # 3.8.2 used OnBootSec: an installer that restarted the timer mid-update made it
    # fire at once and broke the update.  It must first fire two minutes after it starts.
    assert "OnActiveSec=2min" in timer and "OnUnitActiveSec=2min" in timer
    assert "OnBootSec" not in timer
    assert "Unit=bdencode-worker-ensure.service" in timer
    # The worker's own ExecCondition keeps it down during an update or a recovery.
    assert "ExecCondition=/usr/local/libexec/bdencode-recovery-check --runtime" in recovery
    assert "Restart=on-failure" in worker


def test_the_installer_and_uninstaller_manage_the_timer_and_helper() -> None:
    installer = (ROOT / "install/install.sh").read_text(encoding="utf-8")
    uninstaller = (ROOT / "install/uninstall.sh").read_text(encoding="utf-8")

    for name in ("bdencode-worker-ensure.service", "bdencode-worker-ensure.timer"):
        assert f"/etc/systemd/system/{name}" in installer
        assert f"/etc/systemd/system/{name}" in uninstaller
        assert name in uninstaller.split("managed_units=(", 1)[1].split(")", 1)[0]
    assert '"$repo_root/install/worker_ensure.sh"' in installer
    assert "/usr/local/libexec/bdencode-worker-ensure 0755" in installer
    assert "/usr/local/libexec/bdencode-worker-ensure" in uninstaller
    assert "bdencode-credentials.path bdencode-worker-ensure.timer" in installer
    assert "timers.target.wants/bdencode-worker-ensure.timer" in uninstaller


class Host:
    """A fake systemd: states come from files, every call is logged."""

    def __init__(self, tmp_path: Path) -> None:
        self.dir = tmp_path / "stub"
        self.state = tmp_path / "state"
        self.dir.mkdir()
        self.state.mkdir()
        self.log = tmp_path / "calls.log"
        self.log.write_text("", encoding="utf-8")
        script = self.dir / "systemctl"
        script.write_text(
            "#!/bin/sh\n"
            'echo "$*" >> "$STUB_LOG"\n'
            'case "$1" in\n'
            '  is-enabled) [ -e "$STUB_DIR/enabled" ] ;;\n'
            '  show) cat "$STUB_DIR/state-$5" 2>/dev/null || echo inactive ;;\n'
            "  *) exit 0 ;;\n"
            "esac\n",
            encoding="utf-8",
        )
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
        (self.dir / "enabled").write_text("", encoding="utf-8")

    def set_state(self, unit: str, value: str) -> None:
        (self.dir / f"state-{unit}").write_text(value + "\n", encoding="utf-8")

    def run(self) -> list[str]:
        env = {
            **os.environ,
            "PATH": f"{self.dir}{os.pathsep}{os.environ['PATH']}",
            "STUB_DIR": str(self.dir),
            "STUB_LOG": str(self.log),
            "BDENCODE_STATE_DIR": str(self.state),
        }
        subprocess.run(["sh", str(HELPER)], env=env, check=True, timeout=20)
        return [
            line
            for line in self.log.read_text(encoding="utf-8").splitlines()
            if line.split()[0] in {"start", "reset-failed"}
        ]


@posix_only
@pytest.mark.parametrize("state", ["inactive", "failed"])
def test_a_plainly_stopped_enabled_worker_is_started(tmp_path: Path, state: str) -> None:
    host = Host(tmp_path)
    host.set_state("bdencode-worker.service", state)

    assert host.run() == [
        "reset-failed bdencode-worker.service",
        "start --no-block bdencode-worker.service",
    ]


@posix_only
@pytest.mark.parametrize("state", ["active", "activating", "deactivating", "reloading"])
def test_a_worker_that_runs_or_is_changing_state_is_left_alone(tmp_path: Path, state: str) -> None:
    """3.8.2 queued a start while the installer was stopping the worker and broke the update."""

    host = Host(tmp_path)
    host.set_state("bdencode-worker.service", state)

    assert host.run() == []


@posix_only
def test_a_disabled_worker_stays_stopped(tmp_path: Path) -> None:
    host = Host(tmp_path)
    (host.dir / "enabled").unlink()  # systemctl disable --now: a deliberate stop

    assert host.run() == []


@posix_only
@pytest.mark.parametrize(
    "marker",
    [
        "install-transactions/active",
        "install-transactions/services-pending",
        "update-runtime/active.json",
        "apt-transactions/active",
    ],
)
def test_an_installer_transaction_keeps_the_helper_away(tmp_path: Path, marker: str) -> None:
    host = Host(tmp_path)
    path = host.state / marker
    path.parent.mkdir(parents=True)
    path.write_text("{}", encoding="utf-8")

    assert host.run() == []


@posix_only
@pytest.mark.parametrize("state", ["activating", "active", "deactivating"])
def test_a_running_update_keeps_the_helper_away(tmp_path: Path, state: str) -> None:
    host = Host(tmp_path)
    host.set_state("bdencode-update.service", state)

    assert host.run() == []


@posix_only
def test_a_finished_update_does_not_block_the_helper(tmp_path: Path) -> None:
    host = Host(tmp_path)
    host.set_state("bdencode-update.service", "inactive")

    assert host.run()[-1] == "start --no-block bdencode-worker.service"
