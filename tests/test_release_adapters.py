from __future__ import annotations

import httpx
import pytest

from bdencode.release.adapters import (
    AdapterConfigurationError,
    AdapterError,
    DupeCheckOutcome,
    DupeCheckReceipt,
    HttpDupeChecker,
)
from bdencode.release.models import ReleaseMetadata


def _metadata() -> ReleaseMetadata:
    return ReleaseMetadata(
        release_name="Example.2026.1080p.BluRay.x264-GROUP",
        title="Example",
        year=2026,
        category="Movie",
        source_media="BluRay",
        resolution="1080p",
        video_codec="x264",
        audio_codecs=("FLAC",),
        languages=("en",),
    )


@pytest.mark.parametrize(
    ("url", "hosts"),
    [
        ("http://tracker.invalid/api", ("tracker.invalid",)),
        ("https://attacker.invalid/api", ("tracker.invalid",)),
        ("https://user:secret@tracker.invalid/api", ("tracker.invalid",)),
        ("https://tracker.invalid/api?next=https://attacker.invalid", ("tracker.invalid",)),
    ],
)
def test_network_adapters_reject_unsafe_endpoints(
    url: str, hosts: tuple[str, ...]
) -> None:
    with pytest.raises(AdapterConfigurationError):
        HttpDupeChecker(
            url,
            allowed_hosts=hosts,
            credential_name="tracker-token",
        )


def test_dupe_checker_returns_strict_clear_receipt() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["authorization"] == "Bearer top-secret"
        return httpx.Response(
            200,
            json={"status": "clear", "matches": [], "request_id": "req-1"},
        )

    checker = HttpDupeChecker(
        "https://tracker.invalid/api/dupe",
        allowed_hosts=("tracker.invalid",),
        credential_name="tracker-token",
        credential_loader=lambda _name: "top-secret",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    receipt = checker.check(
        _metadata(),
        profile_id="tracker",
        manifest_sha256="a" * 64,
    )

    assert receipt.outcome is DupeCheckOutcome.CLEAR
    assert receipt.remote_request_id == "req-1"
    assert DupeCheckReceipt.model_validate(receipt.model_dump(mode="json")) == receipt
    assert len(requests) == 1
    assert "top-secret" not in repr(checker.__dict__)


def test_dupe_timeout_is_unknown_and_never_retried() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ReadTimeout("ambiguous", request=request)

    checker = HttpDupeChecker(
        "https://tracker.invalid/api/dupe",
        allowed_hosts=("tracker.invalid",),
        credential_name="tracker-token",
        credential_loader=lambda _name: "secret",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    receipt = checker.check(
        _metadata(),
        profile_id="tracker",
        manifest_sha256="a" * 64,
    )

    assert receipt.outcome is DupeCheckOutcome.UNKNOWN
    assert attempts == 1


def test_dupe_checker_treats_unrecognized_success_as_unknown() -> None:
    checker = HttpDupeChecker(
        "https://tracker.invalid/api/dupe",
        allowed_hosts=("tracker.invalid",),
        credential_name="tracker-token",
        credential_loader=lambda _name: "secret",
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(200, json={"status": "maybe"})
            )
        ),
    )

    receipt = checker.check(
        _metadata(), profile_id="tracker", manifest_sha256="a" * 64
    )

    assert receipt.outcome is DupeCheckOutcome.UNKNOWN


def test_dupe_checker_does_not_surface_credential_loader_detail() -> None:
    def credential_loader(_name: str) -> str:
        raise RuntimeError("do-not-leak-this-secret")

    checker = HttpDupeChecker(
        "https://tracker.invalid/api/dupe",
        allowed_hosts=("tracker.invalid",),
        credential_name="tracker-token",
        credential_loader=credential_loader,
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda _request: pytest.fail("network must not be reached")
            )
        ),
    )

    with pytest.raises(AdapterError) as captured:
        checker.check(
            _metadata(), profile_id="tracker", manifest_sha256="a" * 64
        )
    assert "do-not-leak" not in str(captured.value)
    assert captured.value.__suppress_context__ is True


def test_dupe_checker_rejects_control_characters_in_remote_evidence() -> None:
    checker = HttpDupeChecker(
        "https://tracker.invalid/api/dupe",
        allowed_hosts=("tracker.invalid",),
        credential_name="tracker-token",
        credential_loader=lambda _name: "secret",
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(
                    200,
                    json={"status": "duplicate", "matches": ["bad\nlog-entry"]},
                )
            )
        ),
    )

    receipt = checker.check(
        _metadata(), profile_id="tracker", manifest_sha256="a" * 64
    )

    assert receipt.outcome is DupeCheckOutcome.UNKNOWN
    assert receipt.matches == ()


