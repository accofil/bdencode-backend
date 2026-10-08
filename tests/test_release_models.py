from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from bdencode.release.models import (
    PackageFile,
    PackageFileRole,
    ReleaseMetadata,
    ReleasePackageManifest,
    ReleasePreparationState,
    TrackerProfile,
)


def _profile(**overrides: object) -> TrackerProfile:
    values: dict[str, object] = {
        "profile_id": "test-tracker",
        "display_name": "Test Tracker",
        "torrent_source": "TEST",
        "announce_urls": ("https://tracker.invalid/announce",),
        "credential_name": "tracker-api-token",
    }
    values.update(overrides)
    return TrackerProfile(**values)


def _metadata(**overrides: object) -> ReleaseMetadata:
    values: dict[str, object] = {
        "release_name": "Example.2026.1080p.BluRay.x264-GROUP",
        "title": "Example",
        "year": 2026,
        "category": "Movie",
        "source_media": "BluRay",
        "resolution": "1080p",
        "video_codec": "x264",
        "audio_codecs": ("FLAC",),
        "languages": ("en", "hu"),
    }
    values.update(overrides)
    return ReleaseMetadata(**values)


def _required_files(release_name: str, *, schema: int = 2) -> tuple[PackageFile, ...]:
    definitions = [
        ("mediainfo.txt", PackageFileRole.MEDIAINFO, "text/plain"),
        (f"{release_name}.nfo", PackageFileRole.NFO, "text/plain"),
        ("description.bbcode", PackageFileRole.DESCRIPTION, "text/plain"),
        ("SHA256SUMS", PackageFileRole.CHECKSUMS, "text/plain"),
    ]
    if schema == 1:
        # Kits built before 3.0 also carried the private torrent and upload request.
        definitions += [
            (f"{release_name}.torrent", PackageFileRole.TORRENT, "application/x-bittorrent"),
            ("upload-request.json", PackageFileRole.UPLOAD_REQUEST, "application/json"),
        ]
    return tuple(
        PackageFile(path=path, size=1, sha256="a" * 64, role=role, media_type=media_type)
        for path, role, media_type in definitions
    )


def test_tracker_profile_is_strict_and_versioned() -> None:
    profile = _profile()

    assert profile.screenshot_minimum >= 1
    assert "tracker.invalid" not in repr(profile)
    with pytest.raises(ValidationError):
        _profile(schema_version=2)
    with pytest.raises(ValidationError):
        _profile(unknown=True)
    with pytest.raises(ValidationError):
        _profile(target_piece_count_min="1000")


def test_tracker_profile_needs_no_torrent_fields_since_3_0() -> None:
    profile = TrackerProfile(profile_id="aither", display_name="Aither")

    assert profile.announce_urls == ()
    assert profile.torrent_source is None
    # The credential is only needed for a dupe check (checked by the profile file).
    assert profile.credential_name is None
    # Profiles written before 3.0 keep their (now unused) torrent fields.
    assert _profile().announce_urls == ("https://tracker.invalid/announce",)


@pytest.mark.parametrize(
    "overrides",
    [
        {"announce_urls": ("http://tracker.invalid/announce",)},
        {"announce_urls": ("https://user:secret@tracker.invalid/announce",)},
        {"piece_size_min": 300_000},
        {"piece_size_min": 2 * 1024 * 1024, "piece_size_default": 1024 * 1024},
        {"target_piece_count_min": 3000, "target_piece_count_max": 2000},
        {"screenshot_minimum": 9, "screenshot_maximum": 8},
        {"credential_name": "../secret"},
    ],
)
def test_tracker_profile_rejects_unsafe_or_incoherent_policy(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        _profile(**overrides)


@pytest.mark.parametrize(
    "name",
    [
        "../movie",
        "movie/movie",
        "movie\\movie",
        "movie.mkv ",
        "NUL",
        "COM1",
        "CON.Title.2026",
        "Movie.💿.2026",
        "bad\x00name",
        "Cafe\u0301.2026-GROUP",
    ],
)
def test_release_metadata_rejects_noncanonical_or_path_unsafe_names(name: str) -> None:
    with pytest.raises(ValidationError):
        _metadata(release_name=name)


def test_release_metadata_digest_is_stable_and_sensitive_to_content() -> None:
    first = _metadata()
    same = ReleaseMetadata.model_validate_json(first.model_dump_json())
    changed = _metadata(title="Different")

    assert first.canonical_digest() == same.canonical_digest()
    assert first.canonical_digest() != changed.canonical_digest()


def test_release_metadata_accepts_json_array_containers_without_scalar_coercion() -> None:
    values = _metadata().model_dump(mode="json")

    parsed = ReleaseMetadata.model_validate(values)

    assert parsed.audio_codecs == ("FLAC",)
    assert parsed.languages == ("en", "hu")
    values["year"] = "2026"
    with pytest.raises(ValidationError):
        ReleaseMetadata.model_validate(values)


def test_manifest_rejects_casefold_collision_and_invalid_payload_shape() -> None:
    metadata = _metadata()
    files = _required_files(metadata.release_name) + (
        PackageFile(
            path="screenshots/A.png",
            size=1,
            sha256="a" * 64,
            role=PackageFileRole.SCREENSHOT,
            media_type="image/png",
        ),
        PackageFile(
            path="screenshots/a.PNG",
            size=1,
            sha256="b" * 64,
            role=PackageFileRole.SCREENSHOT,
            media_type="image/png",
        ),
    )
    base = {
        "release_name": metadata.release_name,
        "profile_id": "test-tracker",
        "metadata_sha256": metadata.canonical_digest(),
        "payload_path": f"{metadata.release_name}/{metadata.release_name}.mkv",
        "payload_size": 1,
        "payload_sha256": "d" * 64,
        "files": files,
        "created_at": datetime.now(UTC),
    }

    with pytest.raises(ValidationError, match="casefold"):
        ReleasePackageManifest(**base)
    with pytest.raises(ValidationError, match="payload"):
        ReleasePackageManifest(
            **{
                **base,
                "files": _required_files(metadata.release_name),
                "payload_path": "wrong/movie.mkv",
            }
        )


def _manifest_values(*, schema: int = 2) -> dict[str, object]:
    metadata = _metadata()
    values: dict[str, object] = {
        "schema_version": schema,
        "release_name": metadata.release_name,
        "profile_id": "test-tracker",
        "metadata_sha256": metadata.canonical_digest(),
        "payload_path": f"{metadata.release_name}/{metadata.release_name}.mkv",
        "payload_size": 4,
        "payload_sha256": "c" * 64,
        "files": _required_files(metadata.release_name, schema=schema),
        "created_at": datetime(2026, 8, 16, 12, 0, tzinfo=UTC),
    }
    if schema == 1:
        values["torrent_infohash"] = "b" * 40
    return values


@pytest.mark.parametrize("schema", [1, 2])
def test_manifest_canonical_bytes_round_trip(schema: int) -> None:
    manifest = ReleasePackageManifest(**_manifest_values(schema=schema))

    parsed = ReleasePackageManifest.model_validate_json(manifest.canonical_bytes())
    parsed_from_persisted_dict = ReleasePackageManifest.model_validate(
        manifest.model_dump(mode="json")
    )

    assert parsed == manifest
    assert parsed_from_persisted_dict == manifest
    assert parsed.canonical_bytes() == manifest.canonical_bytes()
    assert len(manifest.canonical_digest()) == 64


def test_manifest_schema_versions_bind_their_own_files() -> None:
    schema_2 = ReleasePackageManifest(**_manifest_values())
    assert schema_2.schema_version == 2
    assert schema_2.torrent_infohash is None

    # A schema 2 kit never names or carries a torrent.
    with pytest.raises(ValidationError, match="schema 2 manifest has no torrent"):
        ReleasePackageManifest(**{**_manifest_values(), "torrent_infohash": "b" * 40})
    old_files = _manifest_values(schema=1)["files"]
    with pytest.raises(ValidationError, match="schema 2 has no TORRENT"):
        ReleasePackageManifest(**{**_manifest_values(), "files": old_files})
    # A schema 1 kit (before 3.0) still needs its infohash, torrent and request.
    with pytest.raises(ValidationError, match="torrent infohash"):
        ReleasePackageManifest(**{**_manifest_values(schema=1), "torrent_infohash": None})
    with pytest.raises(ValidationError, match="TORRENT"):
        ReleasePackageManifest(
            **{**_manifest_values(schema=1), "files": _required_files(_metadata().release_name)}
        )


def test_release_preparation_state_contains_ambiguous_terminal_state() -> None:
    assert ReleasePreparationState.READY_TO_PUBLISH.value == "READY_TO_PUBLISH"
    assert ReleasePreparationState.UNKNOWN.value == "UNKNOWN"
