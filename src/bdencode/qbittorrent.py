"""Seed an uploaded release through qBittorrent's Web API.

The torrent goes into its own category, ``bdencode``: the operator's other
qBittorrent automations act on other categories and tags (qbit-aither-relay on
``aither``, qbit-upload-prep on ``other``) and must not move or delete it.  The
client only adds torrents and reads their state: it deletes and moves nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any, Callable, Mapping
from urllib.parse import urlsplit

import httpx

from . import __version__

CATEGORY = "bdencode"
TAG = "accofil-bdencode"
REQUEST_TIMEOUT = 30.0
# Hashing an 80 GB remux takes a while; nCore wants the seed within 30 minutes.
DEFAULT_WAIT_SECONDS = 1500.0
POLL_SECONDS = 5.0
_SEEDING_STATES = {"uploading", "stalledUP", "forcedUP", "queuedUP", "pausedUP", "stoppedUP"}
_CHECKING_STATES = {"checkingUP", "checkingDL", "checkingResumeData", "allocating", "metaDL", "moving"}
_FAILED_STATES = {"error", "missingFiles"}
_QUEUED_STATES = {"queuedUP", "pausedUP", "stoppedUP"}


class QbittorrentError(RuntimeError):
    """Messages never carry the password."""


def validate_url(value: str) -> str:
    """A plain http(s) address without a login, path or query."""

    parts = urlsplit(value.strip())
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ValueError("the qBittorrent address must look like http://127.0.0.1:8080")
    if parts.username or parts.password or parts.query or parts.fragment or parts.path not in {"", "/"}:
        raise ValueError("the qBittorrent address must not hold a login, path or query")
    return f"{parts.scheme}://{parts.netloc}"


@dataclass(frozen=True)
class SeedResult:
    info_hash: str
    state: str
    progress: float


class QbittorrentClient:
    def __init__(
        self,
        url: str,
        *,
        username: str = "",
        password: str = "",
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._url = validate_url(url)
        self._username = username
        self._password = password
        self._client = client or httpx.Client(follow_redirects=False)
        self._sleep = sleep
        self._monotonic = monotonic
        self._logged_in = False

    def close(self) -> None:
        self._client.close()

    @property
    def _headers(self) -> dict[str, str]:
        # qBittorrent's CSRF protection compares these with its own address.
        return {
            "Referer": self._url,
            "Origin": self._url,
            "User-Agent": f"Accofil-BDEncode/{__version__}",
        }

    def _request(self, method: str, path: str, **options: Any) -> httpx.Response:
        try:
            return self._client.request(
                method,
                f"{self._url}/api/v2/{path}",
                headers=self._headers,
                timeout=REQUEST_TIMEOUT,
                **options,
            )
        except httpx.HTTPError as exc:
            raise QbittorrentError(f"qBittorrent cannot be reached ({type(exc).__name__})") from None

    def _login(self) -> None:
        if self._logged_in:
            return
        # With "bypass authentication for localhost" no login is needed.
        probe = self._request("GET", "app/version")
        if probe.status_code == 200:
            self._logged_in = True
            return
        if not self._username:
            raise QbittorrentError("qBittorrent asks for a login, but none is set")
        response = self._request(
            "POST", "auth/login", data={"username": self._username, "password": self._password}
        )
        if response.status_code != 200 or response.text.strip() != "Ok.":
            raise QbittorrentError(f"qBittorrent refused the login (HTTP {response.status_code})")
        self._logged_in = True

    def check_connection(self) -> str:
        self._login()
        response = self._request("GET", "app/version")
        if response.status_code != 200:
            raise QbittorrentError(f"qBittorrent answered HTTP {response.status_code}")
        return f"qBittorrent {response.text.strip()}"

    def _info(self, info_hash: str) -> Mapping[str, Any] | None:
        response = self._request("GET", "torrents/info", params={"hashes": info_hash})
        if response.status_code != 200:
            raise QbittorrentError(f"qBittorrent answered HTTP {response.status_code} on the torrent list")
        try:
            items = response.json()
        except ValueError:
            raise QbittorrentError("qBittorrent's torrent list is broken") from None
        return items[0] if isinstance(items, list) and items else None

    def _ensure_category(self) -> None:
        response = self._request("POST", "torrents/createCategory", data={"category": CATEGORY})
        # 409: it exists already.
        if response.status_code not in (200, 409):
            raise QbittorrentError(f"the category cannot be created (HTTP {response.status_code})")

    def add(self, torrent: bytes, *, info_hash: str, save_path: str) -> None:
        """Add the torrent and let qBittorrent check the data; adding twice is harmless."""

        self._login()
        if self._info(info_hash) is not None:
            return
        self._ensure_category()
        response = self._request(
            "POST",
            "torrents/add",
            files={"torrents": (f"{info_hash}.torrent", torrent, "application/x-bittorrent")},
            data={
                "savepath": save_path,
                "category": CATEGORY,
                "tags": TAG,
                "autoTMM": "false",
                "contentLayout": "Original",
                "skip_checking": "false",
                "paused": "false",
                "stopped": "false",
            },
        )
        if response.status_code != 200 or response.text.strip().casefold().startswith("fails"):
            raise QbittorrentError(f"qBittorrent did not take the torrent (HTTP {response.status_code})")

    def wait_until_seeding(
        self,
        info_hash: str,
        *,
        wait_seconds: float = DEFAULT_WAIT_SECONDS,
        report: Callable[[str, float], None] | None = None,
    ) -> SeedResult:
        """Until the check found all data and the torrent seeds; anything less is an error."""

        self._login()
        deadline = self._monotonic() + wait_seconds
        forced = False
        while True:
            info = self._info(info_hash)
            if info is None:
                # qBittorrent adds asynchronously: give it until the deadline.
                state, progress = "absent", 0.0
            else:
                state, progress = str(info.get("state") or ""), float(info.get("progress") or 0.0)
            if report is not None:
                report(state, progress)
            if state in _FAILED_STATES:
                raise QbittorrentError(f"qBittorrent reports {state}: the data is not where the torrent says")
            if state in _SEEDING_STATES and progress >= 1.0:
                if state in _QUEUED_STATES and not forced:
                    # A queue limit must not make the release miss its seed deadline.
                    self._request(
                        "POST", "torrents/setForceStart", data={"hashes": info_hash, "value": "true"}
                    )
                    forced = True
                else:
                    return SeedResult(info_hash=info_hash, state=state, progress=progress)
            elif info is not None and state not in _CHECKING_STATES and progress < 1.0:
                # A finished check with missing pieces starts to download: never seed that.
                if state in {"downloading", "stalledDL", "forcedDL", "queuedDL", "pausedDL", "stoppedDL"}:
                    raise QbittorrentError(
                        f"qBittorrent found only {progress:.1%} of the data; the torrent does not match it"
                    )
            if self._monotonic() >= deadline:
                raise QbittorrentError(f"qBittorrent did not start seeding in time (state: {state})")
            self._sleep(POLL_SECONDS)
