"""The worker is started again after a passing ExecCondition failure (a full disk)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_the_timer_starts_an_enabled_worker_that_is_not_running() -> None:
    service = (ROOT / "deploy/systemd/bdencode-worker-ensure.service").read_text(encoding="utf-8")
    timer = (ROOT / "deploy/systemd/bdencode-worker-ensure.timer").read_text(encoding="utf-8")
    worker = (ROOT / "deploy/systemd/bdencode-worker.service.in").read_text(encoding="utf-8")
    recovery = (ROOT / "deploy/systemd/bdencode-runtime-recovery.conf.in").read_text(encoding="utf-8")

    assert "Type=oneshot" in service and "User=root" in service
    command = next(line for line in service.splitlines() if line.startswith("ExecStart="))
    # Only an enabled worker that does not run is touched, and a failed state is cleared first.
    assert "systemctl is-enabled --quiet bdencode-worker.service" in command
    assert "! systemctl is-active --quiet bdencode-worker.service" in command
    assert "reset-failed bdencode-worker.service" in command
    assert "systemctl start --no-block bdencode-worker.service" in command
    assert "OnUnitActiveSec=2min" in timer and "OnBootSec=2min" in timer
    assert "Unit=bdencode-worker-ensure.service" in timer
    # The worker's own ExecCondition keeps it down during an update or a recovery.
    assert "ExecCondition=/usr/local/libexec/bdencode-recovery-check --runtime" in recovery
    assert "Restart=on-failure" in worker


def test_the_installer_and_uninstaller_manage_the_timer() -> None:
    installer = (ROOT / "install/install.sh").read_text(encoding="utf-8")
    uninstaller = (ROOT / "install/uninstall.sh").read_text(encoding="utf-8")

    for name in ("bdencode-worker-ensure.service", "bdencode-worker-ensure.timer"):
        assert f"/etc/systemd/system/{name}" in installer
        assert f"/etc/systemd/system/{name}" in uninstaller
        assert name in uninstaller.split("managed_units=(", 1)[1].split(")", 1)[0]
    assert "bdencode-credentials.path bdencode-worker-ensure.timer" in installer
    assert "timers.target.wants/bdencode-worker-ensure.timer" in uninstaller
