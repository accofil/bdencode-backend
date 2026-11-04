"""The two trackers Accofil BDEncode uploads to, and what they have in common.

Nothing here decides to upload: the release service calls ``upload`` only after
the operator approved one exact release.  A request is sent at most once; an
unclear answer is reported as uncertain and never retried.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .. import __version__

USER_AGENT = f"Accofil-BDEncode/{__version__}"


class TrackerError(RuntimeError):
    """The tracker could not be reached or answered something unusable.

    Messages never carry a credential or a download link.
    """


class SessionExpired(TrackerError):
    """The stored login no longer works."""


@dataclass(frozen=True)
class TrackerMatch:
    """A release already on the tracker that may be a duplicate."""

    name: str
    url: str = ""
    size: int | None = None
    exact: bool = False
    trumpable: bool = False


@dataclass(frozen=True)
class UploadResult:
    """``accepted`` and ``rejected`` are certain; otherwise the answer was unclear."""

    accepted: bool = False
    rejected: bool = False
    torrent_id: int | None = None
    url: str = ""
    errors: tuple[str, ...] = field(default_factory=tuple)
    note: str = ""
