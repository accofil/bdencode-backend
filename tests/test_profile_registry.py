from __future__ import annotations

import json
from pathlib import Path

import pytest

from bdencode.config import ConfigurationError
from bdencode.release_profiles import (
    BUILTIN_RELEASE_PROFILES,
    RELEASE_PROFILE_VALIDATION_ERROR,
    load_release_profiles,
)


def _profile() -> dict[str, object]:
    return {
        "tracker": {
            "schema_version": 1,
            "profile_id": "example",
            "display_name": "Example",
            "torrent_source": "EXAMPLE",
            "announce_urls": ["https://tracker.example/announce"],
            "credential_name": "tracker-example-api-token",
        },
        "network": {
            "allowed_hosts": ["tracker.example"],
            "dupe_check_endpoint": "https://tracker.example/api/dupe",
            "publish_endpoint": "https://tracker.example/api/upload",
        },
        "qbittorrent": {
            "base_url": "http://127.0.0.1:8080",
            "allowed_hosts": ["127.0.0.1"],
            "username_credential": "qbittorrent-username",
            "password_credential": "qbittorrent-password",
        },
    }


def test_missing_profile_document_still_offers_the_builtin_profiles(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing.json"

    builtin = load_release_profiles(missing).profiles

    assert [item.tracker.profile_id for item in builtin] == ["aither", "ncore"]
    assert load_release_profiles(missing, include_builtins=False).profiles == ()


def test_builtin_profiles_follow_the_tracker_screenshot_rules() -> None:
    by_id = {item.tracker.profile_id: item for item in BUILTIN_RELEASE_PROFILES}

    aither = by_id["aither"].public_dict()
    ncore = by_id["ncore"].public_dict()

    assert aither["display_name"] == "Aither"
    assert (aither["screenshot_minimum"], aither["screenshot_maximum"]) == (3, 9)
    assert ncore["display_name"] == "nCore"
    assert (ncore["screenshot_minimum"], ncore["screenshot_maximum"]) == (3, 3)
    assert aither["supports_dupe_check"] is False
    assert ncore["supports_dupe_check"] is False
    # A preparation is bound to its profile's digest: a changed built-in would
    # make every preparation made with it fail validation after an update.
    assert aither["profile_digest"] == (
        "8581a5df59b3a90e9aa1ee936e36644ee34c68e075770a80e741e0203d194b63"
    )
    assert ncore["profile_digest"] == (
        "81dc722145e3cb073238adf2e20a117d2ba791acf6afb2c5bad087b80664bb94"
    )


def test_file_profile_replaces_the_builtin_with_the_same_id(tmp_path: Path) -> None:
    own_aither = _profile()
    own_aither["tracker"]["profile_id"] = "aither"  # type: ignore[index]
    own_aither["tracker"]["display_name"] = "Aither (dupe check)"  # type: ignore[index]
    path = tmp_path / "profiles.json"
    path.write_text(
        json.dumps({"schema_version": 1, "profiles": [_profile(), own_aither]}),
        encoding="utf-8",
    )

    document = load_release_profiles(path)

    assert [item.tracker.profile_id for item in document.profiles] == [
        "aither",
        "ncore",
        "example",
    ]
    aither = document.get("aither").public_dict()
    assert aither["display_name"] == "Aither (dupe check)"
    assert aither["supports_dupe_check"] is True
    assert document.get("ncore").tracker.display_name == "nCore"


def test_dupe_check_endpoint_requires_a_credential_name(tmp_path: Path) -> None:
    document = _profile()
    del document["tracker"]["credential_name"]  # type: ignore[attr-defined]
    path = tmp_path / "profiles.json"
    path.write_text(
        json.dumps({"schema_version": 1, "profiles": [document]}),
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError) as captured:
        load_release_profiles(path)

    assert captured.value.code == RELEASE_PROFILE_VALIDATION_ERROR


def test_profile_public_view_never_exposes_endpoints_or_credentials(
    tmp_path: Path,
) -> None:
    path = tmp_path / "profiles.json"
    path.write_text(
        json.dumps({"schema_version": 1, "profiles": [_profile()]}),
        encoding="utf-8",
    )

    profile = load_release_profiles(path).get("example")
    public = profile.public_dict()

    assert public["supports_dupe_check"] is True
    # Since 3.0 BDEncode neither uploads nor seeds, so the view offers neither.
    assert "supports_publish" not in public
    assert "supports_qbittorrent" not in public
    serialized = json.dumps(public)
    assert "api/upload" not in serialized
    assert "credential" not in serialized
    assert "announce" not in serialized


def test_endpoint_host_must_be_explicitly_allowlisted(tmp_path: Path) -> None:
    document = _profile()
    document["network"]["publish_endpoint"] = "https://evil.example/api/upload"  # type: ignore[index]
    path = tmp_path / "profiles.json"
    path.write_text(
        json.dumps({"schema_version": 1, "profiles": [document]}),
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError) as captured:
        load_release_profiles(path)

    assert captured.value.code == RELEASE_PROFILE_VALIDATION_ERROR
    assert "evil.example" not in str(captured.value)


def test_duplicate_profile_ids_are_rejected(tmp_path: Path) -> None:
    profile = _profile()
    path = tmp_path / "profiles.json"
    path.write_text(
        json.dumps({"schema_version": 1, "profiles": [profile, profile]}),
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError) as captured:
        load_release_profiles(path)

    assert captured.value.code == RELEASE_PROFILE_VALIDATION_ERROR


def test_invalid_announce_value_stays_only_in_private_validation_diagnostic(
    tmp_path: Path,
) -> None:
    profile = _profile()
    rejected_url = "http://tracker.example/sekrit"
    profile["tracker"]["announce_urls"] = [rejected_url]  # type: ignore[index]
    path = tmp_path / "profiles.json"
    path.write_text(
        json.dumps({"schema_version": 1, "profiles": [profile]}),
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError) as captured:
        load_release_profiles(path)

    assert captured.value.code == RELEASE_PROFILE_VALIDATION_ERROR
    assert "sekrit" not in str(captured.value)
    assert captured.value.__cause__ is not None
    assert "sekrit" in str(captured.value.__cause__)
