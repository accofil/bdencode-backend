#!/usr/bin/env python3
"""Apply the operator's CPU policy to the BDEncode worker unit.

The web UI saves a day share and an optional night window to
``<data_root>/state/cpu-policy.json``.  This helper runs as root (a systemd
path unit starts it on every save, a timer every few minutes so the night
window switches on time), validates that user-writable file strictly, and sets
the worker's runtime ``CPUQuota``.  It never runs anything taken from the file:
the unit name is fixed and the quota is computed from validated integers.

What it applied is written to ``/var/lib/bdencode/cpu-policy/status.json``.
A missing policy leaves the installed quota alone.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

WORKER_UNIT = "bdencode-worker.service"
STATUS_PATH = Path("/var/lib/bdencode/cpu-policy/status.json")
POLICY_NAME = "cpu-policy.json"
MAX_POLICY_BYTES = 4096
MIN_PERCENT = 10
MAX_PERCENT = 100
CLOCK_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
TIMEZONE_RE = re.compile(r"^[A-Za-z0-9_+\-]+(?:/[A-Za-z0-9_+\-]+){0,2}$")


class PolicyError(ValueError):
    """The policy file is unusable; nothing is applied."""


def _percent(value: Any, field: str) -> int:
    if type(value) is not int or not MIN_PERCENT <= value <= MAX_PERCENT:
        raise PolicyError(f"{field} must be an integer between {MIN_PERCENT} and {MAX_PERCENT}")
    return value


def _clock(value: Any, field: str) -> int:
    if not isinstance(value, str) or not CLOCK_RE.fullmatch(value):
        raise PolicyError(f"{field} must be HH:MM")
    hours, minutes = value.split(":")
    return int(hours) * 60 + int(minutes)


def validate(document: Any) -> dict[str, Any]:
    """The policy as plain validated values."""

    if not isinstance(document, dict) or document.get("schema_version") != 1:
        raise PolicyError("unsupported policy document")
    if set(document) - {"schema_version", "day_percent", "night", "timezone"}:
        raise PolicyError("unknown policy fields")
    night = document.get("night", {})
    if not isinstance(night, dict) or set(night) - {"enabled", "percent", "start", "end"}:
        raise PolicyError("invalid night window")
    enabled = night.get("enabled", False)
    if type(enabled) is not bool:
        raise PolicyError("night.enabled must be true or false")
    zone = document.get("timezone")
    if zone is not None and (not isinstance(zone, str) or len(zone) > 64 or not TIMEZONE_RE.fullmatch(zone)):
        raise PolicyError("timezone must be an IANA zone name")
    return {
        "day_percent": _percent(document.get("day_percent"), "day_percent"),
        "night_enabled": enabled,
        "night_percent": _percent(night.get("percent", MAX_PERCENT), "night.percent"),
        "night_start": _clock(night.get("start", "23:00"), "night.start"),
        "night_end": _clock(night.get("end", "07:00"), "night.end"),
        "timezone": zone,
    }


def read_policy(path: Path) -> dict[str, Any] | None:
    """Read the user-writable policy without following links; ``None`` if absent."""

    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise PolicyError(f"policy cannot be opened: {exc.strerror}") from exc
    with os.fdopen(descriptor, "rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_POLICY_BYTES:
            raise PolicyError("policy must be a small regular file")
        raw = handle.read(MAX_POLICY_BYTES + 1)
    try:
        return validate(json.loads(raw.decode("utf-8")))
    except (UnicodeError, ValueError) as exc:
        if isinstance(exc, PolicyError):
            raise
        raise PolicyError("policy is not valid JSON") from exc


def local_minute(now: datetime, zone: str | None) -> int:
    local = now.astimezone()
    if zone:
        try:
            from zoneinfo import ZoneInfo

            local = now.astimezone(ZoneInfo(zone))
        except Exception:  # unknown zone or no tzdata: the host's clock
            pass
    return local.hour * 60 + local.minute


def effective(policy: Mapping[str, Any], now: datetime) -> tuple[int, str]:
    start, end = policy["night_start"], policy["night_end"]
    if not policy["night_enabled"] or start == end:
        return policy["day_percent"], "day"
    minute = local_minute(now, policy["timezone"])
    in_night = start <= minute < end if start < end else (minute >= start or minute < end)
    return (policy["night_percent"], "night") if in_night else (policy["day_percent"], "day")


def write_status(path: Path, document: Mapping[str, Any]) -> None:
    path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(dict(document), indent=2) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o644)
    os.replace(temporary, path)


def apply(
    data_root: Path,
    *,
    status_path: Path = STATUS_PATH,
    now: datetime | None = None,
    cpus: int | None = None,
    run: Callable[[Sequence[str]], Any] | None = None,
) -> dict[str, Any]:
    moment = now or datetime.now(UTC)
    logical = cpus or os.cpu_count() or 1
    stamp = moment.astimezone(UTC).isoformat().replace("+00:00", "Z")
    try:
        policy = read_policy(data_root / "state" / POLICY_NAME)
    except PolicyError as exc:
        status = {"schema_version": 1, "state": "invalid", "message": str(exc), "applied_at": stamp}
        write_status(status_path, status)
        return status
    if policy is None:
        status = {
            "schema_version": 1,
            "state": "default",
            "message": "no saved policy; the installed quota stays in force",
            "applied_at": stamp,
        }
        write_status(status_path, status)
        return status
    percent, mode = effective(policy, moment)
    quota = logical * percent
    command = [
        "systemctl",
        "set-property",
        "--runtime",
        WORKER_UNIT,
        f"CPUQuota={quota}%",
    ]
    runner = run or (lambda argv: subprocess.run(argv, check=True, capture_output=True, text=True, timeout=30))
    try:
        runner(command)
    except (OSError, subprocess.SubprocessError) as exc:
        status = {
            "schema_version": 1,
            "state": "failed",
            "message": f"systemctl set-property failed: {exc}"[:400],
            "mode": mode,
            "percent": percent,
            "applied_at": stamp,
        }
        write_status(status_path, status)
        return status
    status = {
        "schema_version": 1,
        "state": "applied",
        "mode": mode,
        "percent": percent,
        "quota_percent": quota,
        "logical_cpus": logical,
        "applied_at": stamp,
    }
    write_status(status_path, status)
    return status


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("command", choices=("apply",))
    parser.add_argument("--data-root", default=os.environ.get("BDENCODE_DATA_ROOT"))
    arguments = parser.parse_args(argv)
    if not arguments.data_root:
        print("BDENCODE_DATA_ROOT is not set", file=sys.stderr)
        return 2
    status = apply(Path(arguments.data_root))
    print(json.dumps(status))
    return 0 if status["state"] in {"applied", "default"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
