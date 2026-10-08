"""Operator choices for the AI adviser: provider, models and API-key requests.

The provider choice and the model names are plain preferences in
``<state>/ai-settings.json``; the API writes them directly.  API keys are
secrets: the API never stores them itself.  It drops a one-shot request into
its own runtime directory (``/run/bdencode-api``, tmpfs, mode 0700), a root
helper started by a systemd path unit encrypts the key with ``systemd-creds``
into the operator's credential directory, binds it to the API unit and
restarts the API.  The helper's outcome (never the key) is readable from
``/var/lib/bdencode/credentials/status.json``.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, field_validator

AIProvider = Literal["openai", "anthropic"]
AI_PROVIDERS: tuple[AIProvider, ...] = ("openai", "anthropic")
PROVIDER_LABELS: dict[str, str] = {"openai": "OpenAI", "anthropic": "Claude (Anthropic)"}
PROVIDER_CREDENTIALS: dict[str, str] = {
    "openai": "openai-api-key",
    "anthropic": "anthropic-api-key",
}
DEFAULT_ANTHROPIC_MODEL = "claude-opus-5-5"
SETTINGS_NAME = "ai-settings.json"
REQUEST_PREFIX = "credential-request-"
CREDENTIAL_STATUS_PATH = Path("/var/lib/bdencode/credentials/status.json")
MAX_SETTINGS_BYTES = 4096
MAX_STATUS_BYTES = 65536
MODEL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]*")
API_KEY_RE = re.compile(r"[A-Za-z0-9_\-]{20,400}")


class CredentialRequestUnavailable(RuntimeError):
    """This API process cannot hand keys to the root helper."""


class AIPreferences(BaseModel):
    """The adviser's provider and models chosen on the System page."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    # ``None``: the first provider with a key, OpenAI first.
    default_provider: AIProvider | None = None
    openai_model: str | None = None
    anthropic_model: str | None = None

    @field_validator("openai_model", "anthropic_model")
    @classmethod
    def _model_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            return None
        if len(value) > 100 or MODEL_RE.fullmatch(value) is None:
            raise ValueError("a modellnév csak betűt, számot és ._:- jelet tartalmazhat")
        return value


def settings_path(state_root: Path) -> Path:
    return state_root / SETTINGS_NAME


def load_preferences(path: Path | None) -> AIPreferences:
    """The saved preferences; defaults when the file is absent or unusable."""

    if path is None:
        return AIPreferences()
    try:
        raw = path.read_bytes()[: MAX_SETTINGS_BYTES + 1]
    except OSError:
        return AIPreferences()
    if len(raw) > MAX_SETTINGS_BYTES:
        return AIPreferences()
    try:
        return AIPreferences.model_validate(json.loads(raw.decode("utf-8")))
    except (UnicodeError, ValueError):
        return AIPreferences()


def save_preferences(path: Path, preferences: AIPreferences) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(preferences.model_dump(), indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)


def validate_api_key(provider: AIProvider, value: str) -> str:
    """A plausible key for ``provider``; the provider checks it on first use."""

    key = value.strip()
    if API_KEY_RE.fullmatch(key) is None:
        raise ValueError(
            "Az API-kulcs 20–400 karakter hosszú lehet, és csak betűt, számot, "
            "kötőjelet és aláhúzást tartalmazhat."
        )
    if provider == "anthropic" and not key.startswith("sk-ant-"):
        raise ValueError("Ez nem Claude-kulcsnak tűnik: az Anthropic API-kulcsa sk-ant- előtaggal kezdődik.")
    if provider == "openai" and (not key.startswith("sk-") or key.startswith("sk-ant-")):
        raise ValueError("Ez nem OpenAI-kulcsnak tűnik: az OpenAI API-kulcsa sk- előtaggal kezdődik.")
    return key


def credential_request_directory(
    environment: Mapping[str, str] | None = None,
) -> Path | None:
    """The API's runtime directory that the root helper watches, if any."""

    env = os.environ if environment is None else environment
    configured = env.get("BDENCODE_CREDENTIAL_REQUEST_DIR") or env.get("RUNTIME_DIRECTORY")
    if not configured:
        return None
    # systemd joins several runtime directories with ":"; the API has one.
    directory = Path(configured.split(os.pathsep)[0])
    return directory if directory.is_absolute() and directory.is_dir() else None


def submit_credential_request(
    directory: Path,
    provider: AIProvider,
    action: Literal["set", "delete"],
    value: str | None = None,
) -> str:
    """Hand one key change to the root helper; returns the request id."""

    request_id = uuid.uuid4().hex
    document: dict[str, Any] = {
        "schema_version": 1,
        "request_id": request_id,
        "credential": PROVIDER_CREDENTIALS[provider],
        "action": action,
    }
    if action == "set":
        if value is None:
            raise ValueError("a set request needs a value")
        document["value"] = value
    payload = json.dumps(document).encode("utf-8")
    # The helper's glob only matches the final name, so it never sees a
    # partially written file.
    temporary = directory / f".{REQUEST_PREFIX}{request_id}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(temporary, flags, 0o600)
    except OSError as exc:
        raise CredentialRequestUnavailable(
            f"the key request cannot be written: {exc.strerror}"
        ) from exc
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, directory / f"{REQUEST_PREFIX}{request_id}.json")
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise CredentialRequestUnavailable(
            f"the key request cannot be written: {exc.strerror}"
        ) from exc
    return request_id


def credential_status_path(environment: Mapping[str, str] | None = None) -> Path:
    env = os.environ if environment is None else environment
    configured = env.get("BDENCODE_CREDENTIAL_STATUS_PATH")
    return Path(configured) if configured else CREDENTIAL_STATUS_PATH


def read_helper_results(path: Path) -> list[dict[str, Any]]:
    """The helper's recent outcomes, newest last; never contains a key."""

    try:
        raw = path.read_bytes()[: MAX_STATUS_BYTES + 1]
        document = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, ValueError):
        return []
    results = document.get("results") if isinstance(document, Mapping) else None
    if not isinstance(results, list):
        return []
    keys = ("request_id", "credential", "action", "state", "message", "finished_at")
    return [
        {key: item.get(key) for key in keys if isinstance(item.get(key), str)}
        for item in results[-20:]
        if isinstance(item, Mapping)
    ]


def key_management_view(environment: Mapping[str, str] | None = None) -> dict[str, Any]:
    directory = credential_request_directory(environment)
    return {
        "available": directory is not None,
        "results": read_helper_results(credential_status_path(environment)),
    }
