"""The worker's CPU budget as the operator sets it in the web UI.

The API writes the policy to ``<data_root>/state/cpu-policy.json``.  A
root-owned helper (``/usr/local/libexec/bdencode-cpu-policy``, started by a
systemd path unit on every save and by a timer every few minutes) validates
the file, picks the day or night share for the current time and applies it as
the worker unit's runtime ``CPUQuota``.  It reports what it applied in
``/var/lib/bdencode/cpu-policy/status.json``.

A running encode keeps its threads; the kernel simply grants the new share.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .config import Settings
from .utils import atomic_write_json

CPU_POLICY_FILE = "cpu-policy.json"
#: Written by the root helper; world-readable, no secrets.
CPU_POLICY_STATUS_PATH = Path("/var/lib/bdencode/cpu-policy/status.json")
MIN_PERCENT = 10
MAX_PERCENT = 100
_CLOCK = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
_TIMEZONE = re.compile(r"^[A-Za-z0-9_+\-]+(?:/[A-Za-z0-9_+\-]+){0,2}$")


class NightWindow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    percent: int = Field(default=MAX_PERCENT, ge=MIN_PERCENT, le=MAX_PERCENT)
    start: str = "23:00"
    end: str = "07:00"

    @field_validator("start", "end")
    @classmethod
    def clock_time(cls, value: str) -> str:
        if not _CLOCK.fullmatch(value):
            raise ValueError("times are HH:MM on a 24-hour clock")
        return value


class CpuPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    day_percent: int = Field(ge=MIN_PERCENT, le=MAX_PERCENT)
    night: NightWindow = Field(default_factory=NightWindow)
    #: IANA zone of the operator's browser; the WSL clock may run on UTC.
    timezone: str | None = Field(default=None, max_length=64)

    @field_validator("timezone")
    @classmethod
    def zone_name(cls, value: str | None) -> str | None:
        if value is not None and not _TIMEZONE.fullmatch(value):
            raise ValueError("timezone must be an IANA zone name such as Europe/Budapest")
        return value


def policy_path(settings: Settings) -> Path:
    return settings.state_root / CPU_POLICY_FILE


def default_policy(settings: Settings) -> CpuPolicy:
    percent = min(MAX_PERCENT, max(MIN_PERCENT, settings.cpu_limit_percent))
    return CpuPolicy(day_percent=percent)


def load_policy(settings: Settings) -> tuple[CpuPolicy, bool]:
    """The saved policy (and ``True``), or the installed default (``False``)."""

    try:
        document = json.loads(policy_path(settings).read_text(encoding="utf-8"))
        return CpuPolicy.model_validate(document), True
    except (OSError, ValueError):
        return default_policy(settings), False


def save_policy(settings: Settings, policy: CpuPolicy) -> None:
    path = policy_path(settings)
    path.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
    atomic_write_json(path, policy.model_dump(mode="json"))


def _minutes(clock: str) -> int:
    hours, minutes = clock.split(":")
    return int(hours) * 60 + int(minutes)


def _local(policy: CpuPolicy, now: datetime) -> datetime:
    if policy.timezone:
        try:
            from zoneinfo import ZoneInfo

            return now.astimezone(ZoneInfo(policy.timezone))
        except Exception:  # unknown zone or no tzdata: the host's clock
            pass
    return now.astimezone()


def effective_share(policy: CpuPolicy, now: datetime | None = None) -> tuple[int, str]:
    """The percentage that applies at ``now`` and whether it is day or night."""

    night = policy.night
    if not night.enabled or night.start == night.end:
        return policy.day_percent, "day"
    local = _local(policy, now or datetime.now(timezone.utc))
    minute = local.hour * 60 + local.minute
    start, end = _minutes(night.start), _minutes(night.end)
    in_night = start <= minute < end if start < end else (minute >= start or minute < end)
    return (night.percent, "night") if in_night else (policy.day_percent, "day")


def read_status() -> dict[str, Any] | None:
    """What the root helper applied last, or ``None`` before its first run."""

    path = Path(os.environ.get("BDENCODE_CPU_POLICY_STATUS_PATH") or CPU_POLICY_STATUS_PATH)
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(document, dict):
        return None
    keys = ("mode", "percent", "quota_percent", "logical_cpus", "applied_at", "state", "message")
    return {key: document.get(key) for key in keys if key in document}


def policy_view(settings: Settings, now: datetime | None = None) -> dict[str, Any]:
    policy, saved = load_policy(settings)
    percent, mode = effective_share(policy, now)
    return {
        "policy": policy.model_dump(mode="json"),
        "saved": saved,
        "expected": {"percent": percent, "mode": mode},
        "applied": read_status(),
        "install_default_percent": settings.cpu_limit_percent,
        "logical_cpus": os.cpu_count(),
        "limits": {"min_percent": MIN_PERCENT, "max_percent": MAX_PERCENT},
    }


def current_cpu_percent(settings: Settings) -> int:
    """The share in force: what the helper applied, else what the policy asks."""

    applied = read_status()
    if applied and applied.get("state") == "applied" and isinstance(applied.get("percent"), int):
        return int(applied["percent"])
    policy, _saved = load_policy(settings)
    return effective_share(policy)[0]
