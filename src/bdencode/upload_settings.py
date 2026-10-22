"""Operator choices for the comparison image hosts: host order and key requests.

The host order is a plain preference in ``<state>/image-upload-settings.json``;
the API writes it and the worker reads it at every upload step, so a change
applies to the next upload without a restart.

The host keys are secrets and travel exactly like the AI adviser's keys: the
API drops a one-shot request into its runtime directory, the root helper
(``install/credentials_helper.py``) encrypts the key with ``systemd-creds``
into the operator's credential directory and binds it to the worker unit.
Because a worker may be in the middle of an encode, the helper does not
restart it: it also publishes the change into the running worker's private
runtime directory, which :func:`bdencode.secrets.read_secret` prefers.  The
API never reads a key back; it only reports whether the encrypted file
exists.
"""

from __future__ import annotations

import json
import os
import re
import stat
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, field_validator

from .ai_settings import key_management_view
from .i18n import t

UploadHost = Literal["imgbb", "catbox", "freeimage"]
#: The historical automatic order; the default while the operator chose none.
DEFAULT_HOST_ORDER: tuple[UploadHost, ...] = ("imgbb", "catbox", "freeimage")
HOST_LABELS: dict[str, str] = {"imgbb": "ImgBB", "catbox": "Catbox", "freeimage": "Freeimage"}
#: The credential each host reads (``bdencode.qc.*``); must match
#: ``WORKER_CREDENTIALS`` in install/credentials_helper.py.
HOST_CREDENTIALS: dict[str, str] = {
    "imgbb": "imgbb-api-key",
    "catbox": "catbox-userhash",
    "freeimage": "freeimage-api-key",
}
#: Catbox uploads anonymously without its user hash; the others need a key.
HOST_KEY_REQUIRED: dict[str, bool] = {"imgbb": True, "catbox": False, "freeimage": True}
SETTINGS_NAME = "image-upload-settings.json"
MAX_SETTINGS_BYTES = 4096
# Both API keys are 32 characters (hexadecimal in practice); the Catbox user
# hash is a shorter alphanumeric token.  Must match the helper's patterns.
HOST_KEY_PATTERNS: dict[str, re.Pattern[str]] = {
    "imgbb": re.compile(r"[A-Za-z0-9]{32}"),
    "freeimage": re.compile(r"[A-Za-z0-9]{32}"),
    "catbox": re.compile(r"[A-Za-z0-9]{16,64}"),
}
_HOST_KEY_RULES: dict[str, tuple[str, str]] = {
    "imgbb": (
        "Az ImgBB API-kulcsa pontosan 32 karakter, csak betű és szám.",
        "The ImgBB API key is exactly 32 characters, letters and digits only.",
    ),
    "freeimage": (
        "A Freeimage API-kulcsa pontosan 32 karakter, csak betű és szám.",
        "The Freeimage API key is exactly 32 characters, letters and digits only.",
    ),
    "catbox": (
        "A Catbox userhash 16–64 karakter, csak betű és szám.",
        "The Catbox user hash is 16–64 characters, letters and digits only.",
    ),
}


class UploadPreferences(BaseModel):
    """The host order chosen on the System page."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    # ``None``: the built-in order ImgBB, Catbox, Freeimage.
    provider_order: list[UploadHost] | None = None

    @field_validator("provider_order")
    @classmethod
    def _complete_order(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        if sorted(value) != sorted(DEFAULT_HOST_ORDER):
            raise ValueError(
                t(
                    "a sorrendben minden képtárhely pontosan egyszer szerepeljen",
                    "the order must name every image host exactly once",
                )
            )
        return list(value)


def settings_path(state_root: Path) -> Path:
    return state_root / SETTINGS_NAME


def load_preferences(path: Path | None) -> UploadPreferences:
    """The saved preferences; defaults when the file is absent or unusable."""

    if path is None:
        return UploadPreferences()
    try:
        raw = path.read_bytes()[: MAX_SETTINGS_BYTES + 1]
    except OSError:
        return UploadPreferences()
    if len(raw) > MAX_SETTINGS_BYTES:
        return UploadPreferences()
    try:
        return UploadPreferences.model_validate(json.loads(raw.decode("utf-8")))
    except (UnicodeError, ValueError):
        return UploadPreferences()


def save_preferences(path: Path, preferences: UploadPreferences) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(
        (json.dumps(preferences.model_dump(), indent=2) + "\n").encode("utf-8")
    )
    os.replace(temporary, path)


def host_order(preferences: UploadPreferences) -> list[str]:
    return list(preferences.provider_order or DEFAULT_HOST_ORDER)


def order_by_preference(names: Sequence[str], order: Sequence[str]) -> list[int]:
    """Indexes of ``names`` sorted by ``order``; unknown names keep their place after."""

    rank = {name: position for position, name in enumerate(order)}
    return sorted(
        range(len(names)),
        key=lambda index: (rank.get(names[index], len(rank)), index),
    )


def validate_upload_key(host: UploadHost, value: str) -> str:
    """A plausible key for ``host``; the host itself checks it on first use."""

    key = value.strip()
    pattern = HOST_KEY_PATTERNS[host]
    if pattern.fullmatch(key) is None:
        hungarian, english = _HOST_KEY_RULES[host]
        raise ValueError(t(hungarian, english))
    return key


def credential_directory(environment: Mapping[str, str] | None = None) -> Path:
    """Where the installer and the helper keep the encrypted credentials."""

    env = os.environ if environment is None else environment
    configured = env.get("BDENCODE_CREDENTIAL_DIR")
    return Path(configured) if configured else Path.home() / ".config" / "bdencode"


def encrypted_credential_present(name: str, directory: Path) -> bool:
    """Whether ``<directory>/<name>.cred`` is a non-empty regular file."""

    try:
        details = (directory / f"{name}.cred").lstat()
    except OSError:
        return False
    return stat.S_ISREG(details.st_mode) and details.st_size > 0


def upload_status(
    state_root: Path | None,
    environment: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """The System page view: hosts in order, key presence, never a key."""

    preferences = load_preferences(settings_path(state_root) if state_root else None)
    order = host_order(preferences)
    directory = credential_directory(environment)
    hosts = [
        {
            "id": host,
            "label": HOST_LABELS[host],
            "credential": HOST_CREDENTIALS[host],
            "key_required": HOST_KEY_REQUIRED[host],
            "configured": encrypted_credential_present(HOST_CREDENTIALS[host], directory),
        }
        for host in order
    ]
    return {
        "provider_order": order,
        "default_order": list(DEFAULT_HOST_ORDER),
        "custom_order": preferences.provider_order is not None,
        "hosts": hosts,
        "key_management": key_management_view(environment),
    }
