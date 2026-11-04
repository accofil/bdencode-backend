"""Aither's UNIT3D API.

Written from the API's behaviour, as Audionut's Upload-Assistant uses it; none
of that project's code is copied, because its licence does not allow it here.
Live behaviour is checked by ``check_connection`` once a key is set.
"""

from __future__ import annotations

import json
import re
from typing import Any, Mapping

import httpx

from . import SessionExpired, TrackerError, TrackerMatch, UploadResult, USER_AGENT
from ..torrent_file import TorrentError, info_hash

BASE_URL = "https://aither.cc"
ANNOUNCE = "https://aither.cc/announce"
SOURCE_TAG = "Aither"
CREDENTIAL = "tracker-aither-api-token"
CATEGORY_IDS = {"movie": 1, "tv": 2}
TYPE_REMUX = 2
TYPE_ENCODE = 3
RESOLUTION_IDS = {
    "2160p": 2,
    "1080p": 3,
    "1080i": 4,
    "720p": 5,
    "576p": 6,
    "576i": 7,
    "480p": 8,
    "480i": 9,
}
_SD_RESOLUTIONS = {"576p", "576i", "480p", "480i"}
REQUEST_TIMEOUT = 40.0
UPLOAD_TIMEOUT = 300.0
_DOWNLOAD_ID = re.compile(r"/(\d+)\.")
_DIGITS = re.compile(r"\d+")
# Channel layouts and the codec names keep their dot; the year's dots do not.
_KEPT_DOT = re.compile(r"(?<!\d)\d\.\d(?!\d)|\bH\.26[45]\b")


def display_name(release_name: str) -> str:
    """Aither's titles have spaces where the file has dots: ``DTS-HD MA 5.1``, not ``DTS-HD.MA.5.1``."""

    kept = _KEPT_DOT.sub(lambda found: found.group(0).replace(".", "\0"), release_name)
    return kept.replace(".", " ").replace("\0", ".")


def imdb_digits(imdb_id: str | None) -> str:
    """UNIT3D wants the bare, zero padded number; ``0`` says there is none."""

    digits = (imdb_id or "").lower().removeprefix("tt")
    return digits.zfill(7) if digits.isdigit() and int(digits) else "0"


def upload_fields(
    *,
    name: str,
    description: str,
    mediainfo: str,
    category: str,
    remux: bool,
    resolution: str,
    tmdb_id: int,
    imdb_id: str | None,
    dynamic_range: tuple[str, ...] = (),
    anonymous: bool = False,
    personal_release: bool = False,
    mod_queue: bool = False,
) -> dict[str, str]:
    """The form fields of an upload; refuses what the tracker could not file correctly."""

    category_id = CATEGORY_IDS.get(category.casefold())
    if category_id is None:
        raise TrackerError(f"Aither has no category for {category!r}")
    resolution_id = RESOLUTION_IDS.get(resolution)
    if resolution_id is None:
        raise TrackerError(f"Aither has no resolution for {resolution!r}")
    fields = {
        "name": name,
        "description": description,
        "mediainfo": mediainfo,
        "bdinfo": "",
        "category_id": str(category_id),
        "type_id": str(TYPE_REMUX if remux else TYPE_ENCODE),
        "resolution_id": str(resolution_id),
        "tmdb": str(tmdb_id),
        "imdb": imdb_digits(imdb_id),
        "tvdb": "0",
        "mal": "0",
        "igdb": "0",
        "anonymous": "1" if anonymous else "0",
        "stream": "0",
        "sd": "1" if resolution in _SD_RESOLUTIONS else "0",
        "personal_release": "1" if personal_release else "0",
        "internal": "0",
        "featured": "0",
        "free": "0",
        "doubleup": "0",
        "sticky": "0",
        "mod_queue_opt_in": "1" if mod_queue else "0",
    }
    if "DV" in dynamic_range:
        fields["dv"] = "1"
    if "HDR10+" in dynamic_range:
        fields["hdr10p"] = "1"
    elif "HDR" in dynamic_range or "HLG" in dynamic_range:
        fields["hdr"] = "1"
    return fields


class AitherClient:
    def __init__(self, token: str, *, client: httpx.Client | None = None) -> None:
        self._token = token
        self._client = client or httpx.Client(follow_redirects=True)

    def close(self) -> None:
        self._client.close()

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "authorization": f"Bearer {self._token}",
            "accept": "application/json",
            "User-Agent": USER_AGENT,
        }

    def _get_json(self, path: str, params: Mapping[str, Any] | None = None) -> Any:
        try:
            response = self._client.get(
                f"{BASE_URL}{path}",
                params=dict(params or {}),
                headers=self._headers,
                timeout=REQUEST_TIMEOUT,
            )
        except httpx.HTTPError as exc:
            raise TrackerError(f"Aither cannot be reached ({type(exc).__name__})") from None
        if response.status_code in (401, 403):
            raise SessionExpired("Aither refused the API key")
        if response.status_code != 200:
            raise TrackerError(f"Aither answered HTTP {response.status_code} on {path}")
        try:
            return response.json()
        except json.JSONDecodeError:
            # An expired key can get a login page with status 200.
            raise TrackerError(f"Aither's answer on {path} is not JSON") from None

    def check_connection(self) -> str:
        document = self._get_json("/api/torrents/filter", {"perPage": 1})
        if not isinstance(document, Mapping) or "data" not in document:
            raise TrackerError("Aither's search answer has an unknown form")
        return "Aither API OK"

    def banned_groups(self) -> frozenset[str]:
        """The release groups Aither does not accept, lower case."""

        names: set[str] = set()
        params: dict[str, Any] = {"per_page": 100}
        for _page in range(100):
            document = self._get_json("/api/blacklists/releasegroups", params)
            items = document if isinstance(document, list) else document.get("data", [])
            for item in items:
                if isinstance(item, Mapping):
                    attributes = item.get("attributes")
                    named = attributes if isinstance(attributes, Mapping) else item
                    name = named.get("name")
                    if isinstance(name, str) and name:
                        names.add(name.casefold())
            following = (
                document.get("meta", {}).get("next_cursor")
                if isinstance(document, Mapping)
                else None
            )
            if not following:
                return frozenset(names)
            params["cursor"] = following
        raise TrackerError("Aither's list of banned groups does not end")

    def search(
        self,
        *,
        tmdb_id: int,
        category: str,
        resolution: str,
        release_name: str,
    ) -> tuple[TrackerMatch, ...]:
        """What is on the tracker for this film at this resolution, whatever its type:
        an encode next to a remux is for the operator to judge."""

        params: dict[str, Any] = {
            "tmdbId": tmdb_id,
            "categories[]": CATEGORY_IDS.get(category.casefold(), 1),
            "perPage": 100,
        }
        if resolution in RESOLUTION_IDS:
            params["resolutions[]"] = RESOLUTION_IDS[resolution]
        document = self._get_json("/api/torrents/filter", params)
        items = document.get("data") if isinstance(document, Mapping) else None
        if not isinstance(items, list):
            raise TrackerError("Aither's search answer has an unknown form")
        wanted = display_name(release_name).casefold()
        matches: list[TrackerMatch] = []
        for item in items:
            attributes = item.get("attributes") if isinstance(item, Mapping) else None
            if not isinstance(attributes, Mapping):
                continue
            name = str(attributes.get("name") or "")
            size = attributes.get("size")
            matches.append(
                TrackerMatch(
                    name=name,
                    # Never the download link: it carries the account's key.
                    url=str(attributes.get("details_link") or ""),
                    size=size if isinstance(size, int) else None,
                    exact=name.casefold() == wanted,
                    trumpable=bool(attributes.get("trumpable")),
                )
            )
        return tuple(matches)

    def upload(
        self,
        fields: Mapping[str, str],
        torrent: bytes,
    ) -> tuple[UploadResult, str]:
        """(the result, the download link).  The link is private: use it, do not store it."""

        try:
            response = self._client.post(
                f"{BASE_URL}/api/torrents/upload",
                data=dict(fields),
                files={"torrent": ("torrent.torrent", torrent, "application/x-bittorrent")},
                headers=self._headers,
                timeout=UPLOAD_TIMEOUT,
            )
        except httpx.HTTPError as exc:
            return (
                UploadResult(
                    errors=(f"the upload request broke off ({type(exc).__name__})",),
                ),
                "",
            )
        if response.status_code in (401, 403):
            raise SessionExpired("Aither refused the API key")
        try:
            document = response.json()
        except json.JSONDecodeError:
            return (
                UploadResult(errors=(f"an answer without JSON, HTTP {response.status_code}",)),
                "",
            )
        if not isinstance(document, Mapping):
            return UploadResult(errors=("an answer of unknown form",)), ""
        if response.is_success and document.get("success"):
            link = str(document.get("data") or "")
            found = _DOWNLOAD_ID.search(link)
            torrent_id = int(found.group(1)) if found else None
            return (
                UploadResult(
                    accepted=True,
                    torrent_id=torrent_id,
                    url=f"{BASE_URL}/torrents/{torrent_id}" if torrent_id else "",
                ),
                link,
            )
        if response.status_code in (400, 404, 409, 422) or document.get("success") is False:
            return UploadResult(rejected=True, errors=_validation_errors(document)), ""
        return UploadResult(errors=(f"an unclear answer, HTTP {response.status_code}",)), ""

    def download_torrent(self, link: str) -> bytes:
        if not link.startswith(f"{BASE_URL}/"):
            raise TrackerError("Aither's download link is not on Aither")
        try:
            response = self._client.get(link, headers=self._headers, timeout=REQUEST_TIMEOUT)
        except httpx.HTTPError as exc:
            # The exception text can hold the private link.
            raise TrackerError(f"the torrent cannot be downloaded ({type(exc).__name__})") from None
        if response.status_code != 200:
            raise TrackerError(f"the torrent download answered HTTP {response.status_code}")
        try:
            info_hash(response.content)
        except TorrentError:
            raise TrackerError("the downloaded file is not a torrent") from None
        return response.content


def _validation_errors(document: Mapping[str, Any]) -> tuple[str, ...]:
    """UNIT3D's reasons: ``message`` and often a field to messages mapping in ``data``."""

    reasons: list[str] = []
    message = document.get("message")
    if isinstance(message, str) and message:
        reasons.append(message)
    details = document.get("data")
    if isinstance(details, Mapping):
        for field_name, value in details.items():
            for text in value if isinstance(value, list) else [value]:
                reasons.append(f"{field_name}: {text}")
    elif isinstance(details, str) and details and _DIGITS.search(details) is None:
        reasons.append(details)
    return tuple(reasons) or ("Aither refused the upload without a reason",)
