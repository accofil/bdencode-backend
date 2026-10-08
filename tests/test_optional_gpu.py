"""A GPU is optional: bound only where it exists, reported on the System page."""

from __future__ import annotations

from pathlib import Path

from bdencode.config import Settings
from bdencode.doctor import worker_gpu_status

ROOT = Path(__file__).resolve().parents[1]


def _settings(tmp_path: Path, crop_hwaccel: str = "auto") -> Settings:
    source = tmp_path / "source"
    source.mkdir(exist_ok=True)
    return Settings(
        data_root=tmp_path / "data", source_roots=(source,), crop_hwaccel=crop_hwaccel
    ).validate()


def test_the_installer_binds_only_present_gpu_nodes_in_a_dropin() -> None:
    installer = (ROOT / "install" / "install.sh").read_text(encoding="utf-8")
    uninstaller = (ROOT / "install" / "uninstall.sh").read_text(encoding="utf-8")

    definition = installer.index("render_gpu_dropin() {")
    worker_unit = installer.index('"$repo_root/deploy/systemd/bdencode-worker.service.in"')
    call = installer.index("\nrender_gpu_dropin\n")
    # Defined before use, called right after the worker unit is rendered.
    assert definition < worker_unit < call
    body = installer[definition:installer.index("\n}\n", definition)]
    for device in ("/dev/dxg", "/dev/nvidiactl", "/dev/nvidia-uvm", "/dev/nvidia[0-9]*"):
        assert device in body
    assert '[[ -c "$device" && ! -L "$device" ]]' in body
    assert 'sudo rm -f "$target"' in body  # no GPU: no drop-in
    assert "BindPaths=%s" in body and "DeviceAllow=%s rw" in body
    assert "/etc/systemd/system/bdencode-worker.service.d/gpu.conf" in uninstaller


def test_the_report_reads_the_bound_devices(tmp_path: Path) -> None:
    dropin = tmp_path / "gpu.conf"
    dropin.write_text(
        "[Service]\n# comment\nBindPaths=/dev/dxg\nDeviceAllow=/dev/dxg rw\n"
        "BindPaths=/dev/nvidiactl\nDeviceAllow=/dev/nvidiactl rw\n",
        encoding="utf-8",
    )

    status = worker_gpu_status(_settings(tmp_path), dropin)

    assert status == {
        "devices": ["/dev/dxg", "/dev/nvidiactl"],
        "crop_hwaccel": "auto",
        "crop_decode": "gpu_if_available",
    }


def test_without_a_dropin_or_with_the_gpu_off_the_crop_scan_uses_the_cpu(tmp_path: Path) -> None:
    missing = tmp_path / "missing.conf"
    assert worker_gpu_status(_settings(tmp_path), missing)["crop_decode"] == "cpu"
    assert worker_gpu_status(_settings(tmp_path), missing)["devices"] == []

    dropin = tmp_path / "gpu.conf"
    dropin.write_text("[Service]\nDeviceAllow=/dev/dxg rw\n", encoding="utf-8")
    assert worker_gpu_status(_settings(tmp_path, "none"), dropin)["crop_decode"] == "cpu"
    assert worker_gpu_status(_settings(tmp_path, "cuda"), missing)["crop_decode"] == "gpu"
