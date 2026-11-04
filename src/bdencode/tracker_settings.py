"""The tracker logins and the qBittorrent address on the System page.

Secrets go through the root helper into the encrypted credential store, like the
other keys; only the address and the user name of qBittorrent are plain settings.
Nothing here returns a secret: the view says whether one is set.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .ai_settings import key_management_view
from .i18n import t
from .qbittorrent import validate_url
from .trackers import aither, ncore
from .upload_settings import credential_directory, encrypted_credential_present
from .utils import atomic_write_json

SETTINGS_NAME = "tracker-settings.json"
MAX_SETTINGS_BYTES = 4096
QBITTORRENT_PASSWORD = "qbittorrent-password"
TrackerSecret = Literal["aither", "ncore", "qbittorrent"]
#: Must match ``SETTABLE`` and ``API_CREDENTIALS`` in install/credentials_helper.py.
SECRET_CREDENTIALS: dict[str, str] = {
    "aither": aither.CREDENTIAL,
    "ncore": ncore.CREDENTIAL,
    "qbittorrent": QBITTORRENT_PASSWORD,
}
_AITHER_TOKEN = re.compile(r"[A-Za-z0-9_\-]{20,400}")
_PLAIN_LINE = re.compile(r"[ -~]{1,200}")


class TrackerSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    qbittorrent_url: str = Field(default="", max_length=200)
    qbittorrent_username: str = Field(default="", max_length=120)

    @field_validator("qbittorrent_url")
    @classmethod
    def _valid_url(cls, value: str) -> str:
        return validate_url(value) if value.strip() else ""

    @field_validator("qbittorrent_username")
    @classmethod
    def _valid_username(cls, value: str) -> str:
        value = value.strip()
        if value and not _PLAIN_LINE.fullmatch(value):
            raise ValueError("the qBittorrent user name has an unexpected character")
        return value


def settings_path(state_root: Path) -> Path:
    return state_root / SETTINGS_NAME


def load_settings(path: Path | None) -> TrackerSettings:
    if path is None:
        return TrackerSettings()
    try:
        raw = path.read_bytes()[: MAX_SETTINGS_BYTES + 1]
    except OSError:
        return TrackerSettings()
    if len(raw) > MAX_SETTINGS_BYTES:
        return TrackerSettings()
    try:
        return TrackerSettings.model_validate(json.loads(raw))
    except ValueError:
        return TrackerSettings()


def save_settings(path: Path, settings: TrackerSettings) -> None:
    atomic_write_json(path, settings.model_dump(mode="json"))


def validate_secret(kind: str, value: str) -> str:
    """The value the helper may store.  Errors never repeat the value."""

    text = value.strip()
    if kind == "aither":
        if not _AITHER_TOKEN.fullmatch(text):
            raise ValueError(
                t(
                    "Az Aither API-kulcsa 20–400 karakter: betű, szám, kötőjel, aláhúzás.",
                    "The Aither API key is 20–400 characters: letters, digits, dash, underscore.",
                )
            )
        return text
    if kind == "ncore":
        try:
            return ncore.parse_cookie_export(value)
        except ValueError:
            raise ValueError(
                t(
                    "Az nCore-sütik nem olvashatók: illeszd be a böngészőből exportált cookies.txt tartalmát.",
                    "The nCore cookies cannot be read: paste the cookies.txt exported from the browser.",
                )
            ) from None
    if kind == "qbittorrent":
        if not _PLAIN_LINE.fullmatch(value):
            raise ValueError(
                t(
                    "A qBittorrent jelszava 1–200 sima karakter lehet.",
                    "The qBittorrent password can be 1–200 plain characters.",
                )
            )
        return value
    raise ValueError("unknown secret")


def tracker_status(
    state_root: Path | None,
    environment: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """The System page view; never a secret."""

    settings = load_settings(settings_path(state_root) if state_root else None)
    directory = credential_directory(environment)
    configured = {
        kind: encrypted_credential_present(name, directory)
        for kind, name in SECRET_CREDENTIALS.items()
    }
    return {
        "aither": {"configured": configured["aither"]},
        "ncore": {"configured": configured["ncore"]},
        "qbittorrent": {
            "url": settings.qbittorrent_url,
            "username": settings.qbittorrent_username,
            "password_set": configured["qbittorrent"],
            "configured": bool(settings.qbittorrent_url),
        },
        "key_management": key_management_view(environment),
    }
