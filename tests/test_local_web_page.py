"""A server without Swizzin gets a loopback-only page reached through SSH."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = (ROOT / "install" / "install.sh").read_text(encoding="utf-8")
BRANCH_START = "    # A server without Swizzin:"

needs_bash = pytest.mark.skipif(
    os.name != "posix" or shutil.which("bash") is None, reason="runs the installer branch in bash"
)


def _branch() -> str:
    start = INSTALLER.index(BRANCH_START)
    end = INSTALLER.index("\nfi\n", start)
    return INSTALLER[start:end]


def test_the_branch_order_keeps_swizzin_and_wsl_unchanged() -> None:
    swizzin = INSTALLER.index("if [[ -d /etc/nginx/apps && -f /etc/htpasswd ]]; then")
    wsl = INSTALLER.index("elif grep -qi microsoft /proc/sys/kernel/osrelease 2>/dev/null; then")
    local = INSTALLER.index(BRANCH_START)
    assert swizzin < wsl < local
    body = _branch()
    assert '"$repo_root/deploy/nginx/bdencode-standalone.conf.in"' in body
    assert "local_nginx_target=/etc/nginx/conf.d/bdencode-local.conf" in body
    uninstaller = (ROOT / "install" / "uninstall.sh").read_text(encoding="utf-8")
    assert "local_nginx_target=/etc/nginx/conf.d/bdencode-local.conf" in uninstaller
    assert 'sudo rm -f -- "$local_nginx_target"' in uninstaller
    template = (ROOT / "deploy" / "nginx" / "bdencode-standalone.conf.in").read_text(encoding="utf-8")
    # Loopback only: nothing listens on a public address.
    assert all("127.0.0.1:" in line for line in template.splitlines() if line.strip().startswith("listen"))


def _run(tmp_path: Path, *, port: str | None = None, reload_fails: bool = False) -> subprocess.CompletedProcess[str]:
    etc = tmp_path / "etc"
    (etc / "conf.d").mkdir(parents=True, exist_ok=True)
    (etc / "sites-enabled").mkdir(exist_ok=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    (bin_dir / "nginx").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (bin_dir / "systemctl").write_text(
        "#!/bin/sh\n"
        'case "$1" in reload-or-restart) [ -n "$RELOAD_FAILS" ] && exit 1;; esac\n'
        "exit 0\n",
        encoding="utf-8",
    )
    (bin_dir / "apt-get").write_text("#!/bin/sh\necho apt-get called >&2\nexit 1\n", encoding="utf-8")
    for tool in ("nginx", "systemctl", "apt-get"):
        (bin_dir / tool).chmod(0o755)
    body = (
        _branch()
        .replace("/etc/nginx/conf.d/bdencode-local.conf", str(etc / "conf.d" / "bdencode-local.conf"))
        .replace("/etc/nginx/sites-enabled/default", str(etc / "sites-enabled" / "default"))
    )
    script = (
        "set -Eeuo pipefail\n"
        'sudo() { "$@"; }\n'
        f"repo_root={ROOT.as_posix()!r}\n"
        "frontend_root=/var/www/bdencode\n"
        "release_id=test\n"
        "task_user=encoder\n"
        "{\n" + body + "\n}\n"
    )
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"}
    env.pop("BDENCODE_LOCAL_WEB_PORT", None)
    if port is not None:
        env["BDENCODE_LOCAL_WEB_PORT"] = port
    if reload_fails:
        env["RELOAD_FAILS"] = "1"
    return subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True, check=False)


@needs_bash
def test_a_fresh_server_gets_the_page_on_the_default_port(tmp_path: Path) -> None:
    result = _run(tmp_path)

    assert result.returncode == 0, result.stderr
    conf = (tmp_path / "etc" / "conf.d" / "bdencode-local.conf").read_text(encoding="utf-8")
    assert "listen 127.0.0.1:8787" in conf
    assert "proxy_pass http://127.0.0.1:8796/api/;" in conf
    assert "@" not in conf.replace("$", "")
    assert "ssh -L 8787:127.0.0.1:8787 encoder@<server>" in result.stdout


@needs_bash
def test_an_update_keeps_the_chosen_port(tmp_path: Path) -> None:
    assert _run(tmp_path, port="9123").returncode == 0
    # The unattended updater does not pass BDENCODE_LOCAL_WEB_PORT.
    result = _run(tmp_path)

    assert result.returncode == 0, result.stderr
    conf = (tmp_path / "etc" / "conf.d" / "bdencode-local.conf").read_text(encoding="utf-8")
    assert "listen 127.0.0.1:9123" in conf


@needs_bash
def test_a_busy_port_rolls_back_without_failing_the_install(tmp_path: Path) -> None:
    assert _run(tmp_path, port="9123").returncode == 0
    result = _run(tmp_path, port="9200", reload_fails=True)

    assert result.returncode == 0
    assert "could not be installed" in result.stderr
    conf = (tmp_path / "etc" / "conf.d" / "bdencode-local.conf").read_text(encoding="utf-8")
    assert "listen 127.0.0.1:9123" in conf  # the previous working page stays


@needs_bash
def test_an_invalid_port_stops_the_installer(tmp_path: Path) -> None:
    for port in ("80", "8796", "abc"):
        result = _run(tmp_path, port=port)
        assert result.returncode == 2
        assert "BDENCODE_LOCAL_WEB_PORT" in result.stderr
