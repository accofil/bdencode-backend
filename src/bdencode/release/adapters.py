"""The network boundary for tracker duplicate checks.

Since 3.0 BDEncode neither seeds nor publishes: the duplicate check is the
only tracker request left.  It performs at most one request.  A timeout after
that request is represented as ``UNKNOWN`` and is never retried automatically.
Credentials are loaded immediately before use and are never included in a
receipt, exception message, URL or log record.
"""

from __future__ import annotations

import ipaddress
import re
import unicodedata
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal, Protocol, Sequence
from urllib.parse import urlsplit, urlunsplit

import httpx
from pydantic import Field, field_validator, model_validator

from bdencode.secrets import read_secret

from .models import ReleaseMetadata, ReleaseModel


_HEX_64 = "0123456789abcdef"
_CREDENTIAL_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_PROFILE_ID = re.compile(r"^[a-z0-9](?:[a-z0-9._-]{0,62}[a-z0-9])?$")
_HOSTNAME = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)(?:\."
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*$"
)


class AdapterConfigurationError(ValueError):
    pass


class AdapterError(RuntimeError):
    pass


class CredentialLoader(Protocol):
    def __call__(self, name: str) -> str: ...


class DupeCheckOutcome(StrEnum):
    CLEAR = "CLEAR"
    DUPLICATE = "DUPLICATE"
    UNKNOWN = "UNKNOWN"


class DupeCheckReceipt(ReleaseModel):
    schema_version: Literal[1] = 1
    profile_id: str
    manifest_sha256: str
    metadata_sha256: str
    outcome: DupeCheckOutcome
    matches: tuple[str, ...] = Field(default=(), max_length=100)
    checked_at: datetime
    remote_request_id: str | None = Field(default=None, max_length=256)

    @field_validator("outcome", mode="before")
    @classmethod
    def accept_serialized_outcome(cls, value: Any) -> Any:
        return _serialized_enum(value, DupeCheckOutcome)

    @field_validator("checked_at", mode="before")
    @classmethod
    def accept_serialized_checked_at(cls, value: Any) -> Any:
        return _serialized_datetime(value)

    @field_validator("matches", mode="before")
    @classmethod
    def accept_json_match_array(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @field_validator("profile_id")
    @classmethod
    def validate_profile_id(cls, value: str) -> str:
        return _validate_profile_id(value)

    @field_validator("matches", "remote_request_id")
    @classmethod
    def validate_remote_text(
        cls, value: tuple[str, ...] | str | None
    ) -> tuple[str, ...] | str | None:
        if isinstance(value, tuple):
            for item in value:
                _validate_remote_text(item)
        elif value is not None:
            _validate_remote_text(value)
        return value

    @field_validator("manifest_sha256", "metadata_sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if len(value) != 64 or any(char not in _HEX_64 for char in value):
            raise ValueError("invalid SHA-256 digest")
        return value

    @model_validator(mode="after")
    def validate_receipt(self) -> DupeCheckReceipt:
        if self.checked_at.tzinfo is None or self.checked_at.utcoffset() is None:
            raise ValueError("checked_at must be timezone-aware")
        if self.outcome is DupeCheckOutcome.CLEAR and self.matches:
            raise ValueError("a CLEAR dupe receipt cannot contain matches")
        if self.outcome is DupeCheckOutcome.DUPLICATE and not self.matches:
            raise ValueError("a DUPLICATE receipt must contain at least one match")
        return self


class DupeChecker(Protocol):
    def check(
        self,
        metadata: ReleaseMetadata,
        *,
        profile_id: str,
        manifest_sha256: str,
    ) -> DupeCheckReceipt: ...


def _serialized_datetime(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value


def _serialized_enum(value: Any, enum_type: type[StrEnum]) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return enum_type(value)
    except ValueError:
        return value


def _normalized_endpoint(
    value: str,
    *,
    allowed_hosts: Sequence[str],
    allow_loopback_http: bool,
) -> str:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise AdapterConfigurationError("endpoint URL is malformed") from exc
    hostname = _normalize_host(parsed.hostname or "")
    allowlist = {_normalize_host(item) for item in allowed_hosts}
    if not hostname or hostname not in allowlist or not allowlist:
        raise AdapterConfigurationError("endpoint host is not explicitly allowlisted")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise AdapterConfigurationError("endpoint may not contain userinfo, query or fragment")
    loopback = hostname == "localhost"
    try:
        loopback = loopback or ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        pass
    if parsed.scheme != "https" and not (
        allow_loopback_http and parsed.scheme == "http" and loopback
    ):
        raise AdapterConfigurationError("endpoint must use HTTPS (HTTP only for loopback)")
    if port is not None and not 1 <= port <= 65535:
        raise AdapterConfigurationError("endpoint port is invalid")
    if parsed.path and not parsed.path.startswith("/"):
        raise AdapterConfigurationError("endpoint path is invalid")
    netloc = f"[{hostname}]" if ":" in hostname else hostname
    if port is not None:
        netloc += f":{port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path.rstrip("/"), "", ""))


def _join_endpoint(base: str, suffix: str) -> str:
    if not suffix.startswith("/") or "?" in suffix or "#" in suffix or "\\" in suffix:
        raise AdapterConfigurationError("API path must be an absolute URL path")
    return base.rstrip("/") + suffix


def _validate_credential_name(value: str) -> str:
    if not _CREDENTIAL_NAME.fullmatch(value):
        raise AdapterConfigurationError("credential name is invalid")
    return value


def _validate_profile_id(value: str) -> str:
    if not _PROFILE_ID.fullmatch(value):
        raise ValueError("profile_id must be a lowercase stable identifier")
    return value


def _validate_remote_text(value: str) -> str:
    if not value or value != unicodedata.normalize("NFC", value):
        raise ValueError("remote text must be non-empty canonical Unicode")
    if any(unicodedata.category(char).startswith("C") for char in value):
        raise ValueError("remote text contains unsafe control or format characters")
    return value


def _is_safe_remote_text(value: object, *, maximum: int) -> bool:
    if not isinstance(value, str) or not 0 < len(value) <= maximum:
        return False
    try:
        _validate_remote_text(value)
    except ValueError:
        return False
    return True


def _normalize_host(value: str) -> str:
    normalized = value.rstrip(".").casefold()
    try:
        return ipaddress.ip_address(normalized).compressed
    except ValueError:
        pass
    if not normalized.isascii() or not _HOSTNAME.fullmatch(normalized):
        raise AdapterConfigurationError("host allowlist contains an invalid host")
    return normalized


def _load_credential(loader: CredentialLoader, name: str, *, label: str) -> str:
    try:
        value = loader(name)
    except Exception:
        # A third-party loader exception may contain the credential value.
        raise AdapterError(f"{label} credential loading failed") from None
    if not value:
        raise AdapterError(f"{label} credential is unavailable")
    return value


def _close_owned_client(client: httpx.Client, *, owned: bool) -> None:
    if not owned:
        return
    try:
        client.close()
    except Exception:
        # Transport cleanup cannot change an already observed remote outcome.
        pass


class HttpDupeChecker:
    """Strict one-shot JSON duplicate check against an operator-set endpoint."""

    def __init__(
        self,
        endpoint: str,
        *,
        allowed_hosts: Sequence[str],
        credential_name: str,
        credential_loader: CredentialLoader = read_secret,
        client: httpx.Client | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._endpoint = _normalized_endpoint(
            endpoint,
            allowed_hosts=allowed_hosts,
            allow_loopback_http=False,
        )
        self._credential_name = _validate_credential_name(credential_name)
        self._credential_loader = credential_loader
        self._client = client
        self._timeout = timeout

    def check(
        self,
        metadata: ReleaseMetadata,
        *,
        profile_id: str,
        manifest_sha256: str,
    ) -> DupeCheckReceipt:
        profile_id = _validate_profile_id(profile_id)
        if len(manifest_sha256) != 64 or any(char not in _HEX_64 for char in manifest_sha256):
            raise ValueError("manifest_sha256 is invalid")
        token = _load_credential(
            self._credential_loader, self._credential_name, label="tracker"
        )
        now = datetime.now(UTC)
        owned = self._client is None
        client = self._client or httpx.Client(timeout=self._timeout, follow_redirects=False)
        try:
            try:
                response = client.post(
                    self._endpoint,
                    headers={"Authorization": f"Bearer {token}"},
                    json={
                        "schema_version": 1,
                        "profile_id": profile_id,
                        "manifest_sha256": manifest_sha256,
                        "metadata": metadata.model_dump(mode="json"),
                    },
                    follow_redirects=False,
                )
            except (httpx.TimeoutException, httpx.TransportError):
                return DupeCheckReceipt(
                    profile_id=profile_id,
                    manifest_sha256=manifest_sha256,
                    metadata_sha256=metadata.canonical_digest(),
                    outcome=DupeCheckOutcome.UNKNOWN,
                    checked_at=now,
                )
            if response.is_redirect or response.status_code != 200:
                return DupeCheckReceipt(
                    profile_id=profile_id,
                    manifest_sha256=manifest_sha256,
                    metadata_sha256=metadata.canonical_digest(),
                    outcome=DupeCheckOutcome.UNKNOWN,
                    checked_at=now,
                )
            try:
                document = response.json()
            except ValueError:
                document = None
            if not isinstance(document, dict) or set(document) - {
                "status",
                "matches",
                "request_id",
            }:
                document = None
            status = document.get("status") if document else None
            matches = document.get("matches", []) if document else []
            request_id = document.get("request_id") if document else None
            valid_matches = (
                isinstance(matches, list)
                and len(matches) <= 100
                and all(
                    _is_safe_remote_text(item, maximum=512) and token not in item
                    for item in matches
                )
            )
            valid_request = request_id is None or (
                _is_safe_remote_text(request_id, maximum=256)
                and token not in request_id
            )
            if status == "clear" and valid_matches and not matches and valid_request:
                outcome = DupeCheckOutcome.CLEAR
            elif status == "duplicate" and valid_matches and bool(matches) and valid_request:
                outcome = DupeCheckOutcome.DUPLICATE
            else:
                outcome = DupeCheckOutcome.UNKNOWN
                matches = []
                request_id = None
            return DupeCheckReceipt(
                profile_id=profile_id,
                manifest_sha256=manifest_sha256,
                metadata_sha256=metadata.canonical_digest(),
                outcome=outcome,
                matches=tuple(matches),
                checked_at=now,
                remote_request_id=request_id,
            )
        finally:
            token = ""
            _close_owned_client(client, owned=owned)


__all__ = [
    "AdapterConfigurationError",
    "AdapterError",
    "CredentialLoader",
    "DupeCheckOutcome",
    "DupeCheckReceipt",
    "DupeChecker",
    "HttpDupeChecker",
]
