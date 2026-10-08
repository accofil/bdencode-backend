from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import sqlite3
import subprocess
from types import SimpleNamespace

import pytest

from bdencode.config import Settings
from bdencode.db import Database, StateConflictError
from bdencode.models import ArtifactCreate, ArtifactKind, JobCreate
from bdencode.release import (
    DupeCheckOutcome,
    DupeCheckReceipt,
    PackageFileRole,
    ReleaseMetadata,
    ReleasePreparationState,
    load_verified_upload_kit,
)
from bdencode.release_service import (
    ReleaseService,
    ReleaseServiceError,
    _read_stable_bounded_file,
)
import bdencode.release_service as release_service_module
from bdencode.utils import sha256_file


class _Runner:
    def capture(
        self,
        argv: list[str],
        *,
        timeout: float = 30,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        assert argv[0] == "mediainfo"
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout=(
                "General\n"
                f"Complete name : {argv[-1]}\n"
                "Format : Matroska\n"
                "Video\nFormat : AVC\n"
            ),
            stderr="",
        )


def _fixture(tmp_path: Path) -> tuple[ReleaseService, str, Path]:
    source = tmp_path / "source"
    source.mkdir()
    settings = Settings(
        data_root=tmp_path / "data",
        source_roots=(source,),
        release_profiles_path=tmp_path / "profiles.json",
    ).validate()
    settings.create_directories()
    settings.resolved_release_profiles_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "profiles": [
                    {
                        "tracker": {
                            "schema_version": 1,
                            "profile_id": "example",
                            "display_name": "Example",
                            "torrent_source": "EXAMPLE",
                            "announce_urls": ["https://tracker.example/announce"],
                            "piece_size_min": 16_384,
                            "piece_size_max": 65_536,
                            "piece_size_default": 16_384,
                            "target_piece_count_min": 1,
                            "target_piece_count_max": 100,
                            "screenshot_minimum": 1,
                            "screenshot_maximum": 2,
                            "credential_name": "tracker-example-token",
                        },
                        "network": {
                            "allowed_hosts": ["tracker.example"],
                            "dupe_check_endpoint": "https://tracker.example/dupe",
                            "publish_endpoint": "https://tracker.example/publish",
                        },
                        "qbittorrent": {
                            "base_url": "http://127.0.0.1:8080",
                            "allowed_hosts": ["127.0.0.1"],
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    database = Database(settings.resolved_database_path)
    job = database.create_job(JobCreate(source_path=str(source)))
    with database._write() as connection:
        connection.execute(
            "UPDATE jobs SET state = 'COMPLETED' WHERE id = ?", (job.id,)
        )

    name = "Example.Movie.2026.1080p.BluRay.x264-GROUP"
    completed = settings.completed_root / name
    comparison = completed / "comparison"
    comparison.mkdir(parents=True)
    payload = completed / f"{name}.mkv"
    payload.write_bytes((b"matroska-test-payload\x00" * 2000) + b"end")
    digest = sha256_file(payload)
    (completed / ".bdencode-owner.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "output_name": name,
                "mux_sha256": digest,
            }
        ),
        encoding="utf-8",
    )
    png = comparison / "pair-01-encode.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\nfixture")
    (comparison / "video-comparison.json").write_text(
        json.dumps(
            {
                "pairs": [
                    {
                        "encode_png": png.name,
                        "encode_sha256": sha256_file(png),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    database.create_artifact(
        ArtifactCreate(
            job_id=job.id,
            kind=ArtifactKind.OUTPUT,
            name=payload.name,
            path=str(payload.resolve()),
            mime_type="video/x-matroska",
            sha256=digest,
            size_bytes=payload.stat().st_size,
        )
    )
    return ReleaseService(database, settings, runner=_Runner()), job.id, payload


def _metadata(payload: Path) -> ReleaseMetadata:
    return ReleaseMetadata(
        release_name=payload.stem,
        title="Example Movie",
        year=2026,
        category="Movie",
        source_media="BluRay",
        resolution="1080p",
        video_codec="x264",
        audio_codecs=("FLAC",),
        languages=("en",),
    )


def test_release_build_is_private_single_mkv_payload_and_safe_public_view(
    tmp_path: Path,
) -> None:
    service, job_id, payload = _fixture(tmp_path)
    created = service.create(
        job_id,
        profile_id="example",
        metadata=_metadata(payload),
    )

    ready = service.build(created.id, expected_version=created.version)
    kit = service.settings.release_kits_root / ready.id
    manifest, _artifacts = load_verified_upload_kit(
        kit, expected_manifest_sha256=ready.manifest_sha256
    )

    assert ready.state.value == "READY"
    assert ready.payload_path == f"{payload.stem}/{payload.name}"
    assert str(tmp_path) not in ready.model_dump_json()
    assert ready.manifest_sha256
    # Since 3.0 the kit is text, screenshots and checksums: no torrent, no upload request.
    assert manifest.schema_version == 2
    assert manifest.torrent_infohash is None
    assert manifest.payload_path == f"{payload.stem}/{payload.name}"
    assert manifest.payload_sha256 == sha256_file(payload)
    assert {item.role for item in manifest.files} == {
        PackageFileRole.MEDIAINFO,
        PackageFileRole.NFO,
        PackageFileRole.DESCRIPTION,
        PackageFileRole.SCREENSHOT,
        PackageFileRole.CHECKSUMS,
    }
    assert not list(kit.glob("*.torrent"))
    assert not (kit / "upload-request.json").exists()


def _comparison_pairs(payload: Path, *, labelled: int, clean: int) -> dict[str, str]:
    """Rewrite the comparison with ``labelled`` pairs, the first ``clean`` with screenshots.

    Returns the SHA-256 of every PNG by its role and pair number.
    """

    comparison = payload.parent / "comparison"
    digests: dict[str, str] = {}
    pairs = []
    for number in range(1, labelled + 1):
        encode = comparison / f"pair-{number:02d}-encode.png"
        encode.write_bytes(b"\x89PNG\r\n\x1a\n" + f"labelled {number}".encode())
        pair = {"encode_png": encode.name, "encode_sha256": sha256_file(encode)}
        digests[f"labelled-{number}"] = pair["encode_sha256"]
        if number <= clean:
            screenshot = comparison / f"pair-{number:02d}-screenshot.png"
            screenshot.write_bytes(b"\x89PNG\r\n\x1a\n" + f"clean {number}".encode())
            pair["screenshot_png"] = screenshot.name
            pair["screenshot_sha256"] = sha256_file(screenshot)
            digests[f"clean-{number}"] = pair["screenshot_sha256"]
        pairs.append(pair)
    (comparison / "video-comparison.json").write_text(
        json.dumps({"pairs": pairs}), encoding="utf-8"
    )
    return digests


def _kit_screenshot_digests(service: ReleaseService, ready) -> set[str]:
    manifest, _artifacts = load_verified_upload_kit(
        service.settings.release_kits_root / ready.id,
        expected_manifest_sha256=ready.manifest_sha256,
    )
    return {
        item.sha256 for item in manifest.files if item.role is PackageFileRole.SCREENSHOT
    }


@pytest.mark.parametrize(
    ("profile_id", "expected"),
    [("aither", 6), ("ncore", 3)],
)
def test_builtin_tracker_profiles_build_kits_from_the_clean_screenshots(
    tmp_path: Path, profile_id: str, expected: int
) -> None:
    service, job_id, payload = _fixture(tmp_path)
    digests = _comparison_pairs(payload, labelled=24, clean=6)
    created = service.create(job_id, profile_id=profile_id, metadata=_metadata(payload))

    ready = service.build(created.id, expected_version=created.version)

    chosen = _kit_screenshot_digests(service, ready)
    clean = {value for key, value in digests.items() if key.startswith("clean-")}
    assert len(chosen) == expected
    assert chosen <= clean


def test_release_kit_uses_labelled_frames_when_clean_ones_are_too_few(
    tmp_path: Path,
) -> None:
    service, job_id, payload = _fixture(tmp_path)
    digests = _comparison_pairs(payload, labelled=4, clean=2)
    created = service.create(job_id, profile_id="ncore", metadata=_metadata(payload))

    ready = service.build(created.id, expected_version=created.version)

    chosen = _kit_screenshot_digests(service, ready)
    labelled = {value for key, value in digests.items() if key.startswith("labelled-")}
    assert len(chosen) == 3
    assert chosen <= labelled


def test_release_preflight_detects_completed_payload_change(tmp_path: Path) -> None:
    service, job_id, payload = _fixture(tmp_path)
    created = service.create(
        job_id,
        profile_id="example",
        metadata=_metadata(payload),
    )
    payload.write_bytes(b"changed")

    result = service.validate(created.id)

    assert result["valid"] is False
    assert "completed MKV changed" in " ".join(result["failures"])


def test_ready_release_cannot_be_rebuilt_or_damage_its_existing_kit(
    tmp_path: Path,
) -> None:
    service, job_id, payload = _fixture(tmp_path)
    created = service.create(job_id, profile_id="example", metadata=_metadata(payload))
    ready = service.build(created.id, expected_version=created.version)
    manifest = service.settings.release_kits_root / ready.id / "package-manifest.json"
    manifest_digest = sha256_file(manifest)
    original = service.store.get(ready.id)

    with pytest.raises(StateConflictError, match="cannot transition"):
        service.build(ready.id, expected_version=ready.version)

    assert service.store.get(ready.id) == original
    assert sha256_file(manifest) == manifest_digest


def test_profile_list_does_not_return_announce_or_credential(tmp_path: Path) -> None:
    service, _job_id, _payload = _fixture(tmp_path)

    serialized = json.dumps(service.profiles())

    assert "announce" not in serialized
    assert "credential" not in serialized
    assert "tracker.example" not in serialized


def test_release_delete_stale_version_never_touches_kit(tmp_path: Path) -> None:
    service, job_id, payload = _fixture(tmp_path)
    created = service.create(job_id, profile_id="example", metadata=_metadata(payload))
    ready = service.build(created.id, expected_version=created.version)
    kit = service.settings.release_kits_root / ready.id

    with pytest.raises(StateConflictError, match="version is"):
        service.delete(ready.id, expected_version=created.version)

    assert kit.is_dir()
    assert service.store.get(ready.id).version == ready.version


def test_release_delete_restores_quarantine_when_database_delete_fails(
    tmp_path: Path,
) -> None:
    service, job_id, payload = _fixture(tmp_path)
    created = service.create(job_id, profile_id="example", metadata=_metadata(payload))
    ready = service.build(created.id, expected_version=created.version)
    kit = service.settings.release_kits_root / ready.id
    with service.database._write() as connection:
        connection.execute(
            """
            CREATE TRIGGER fail_release_delete BEFORE DELETE ON release_preparations
            BEGIN SELECT RAISE(ABORT, 'injected delete failure'); END
            """
        )

    with pytest.raises(sqlite3.DatabaseError, match="injected delete failure"):
        service.delete(ready.id, expected_version=ready.version)

    assert kit.is_dir()


def test_active_preparation_delete_creates_no_intent_or_filesystem_disruption(
    tmp_path: Path,
) -> None:
    service, job_id, payload = _fixture(tmp_path)
    created = service.create(job_id, profile_id="example", metadata=_metadata(payload))
    preparing = service.store.transition(
        created.id,
        ReleasePreparationState.PREPARING,
        expected_version=created.version,
    )
    orphan = service.settings.release_kits_root / preparing.id
    orphan.mkdir()
    sentinel = orphan / "partial"
    sentinel.write_bytes(b"active-build")

    with pytest.raises(StateConflictError, match="active release preparation"):
        service.delete(preparing.id, expected_version=preparing.version)

    with service.database._read() as connection:
        count = connection.execute(
            "SELECT COUNT(*) AS count FROM maintenance_operations WHERE subject_id = ?",
            (preparing.id,),
        ).fetchone()["count"]
    assert count == 0
    assert sentinel.read_bytes() == b"active-build"


def test_cross_linked_kit_record_blocks_multitarget_maintenance(
    tmp_path: Path,
) -> None:
    service, job_id, payload = _fixture(tmp_path)
    created = [
        service.create(job_id, profile_id="example", metadata=_metadata(payload))
        for _ in range(2)
    ]
    ready = [service.build(item.id, expected_version=item.version) for item in created]
    kit_paths = [service.settings.release_kits_root / item.id for item in ready]
    with service.database._write() as connection:
        connection.execute(
            "UPDATE release_preparations SET kit_path = ? WHERE id = ?",
            (str(kit_paths[1]), ready[0].id),
        )
    corrupted = service.store.get(ready[0].id)

    with pytest.raises(ReleaseServiceError, match="safely deleted"):
        service._verified_maintenance_kit(corrupted)

    assert all(path.is_dir() for path in kit_paths)
    with service.database._read() as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) AS count FROM maintenance_operations"
            ).fetchone()["count"]
            == 0
        )


def test_ready_persistence_failure_removes_the_unbound_final_kit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, job_id, payload = _fixture(tmp_path)
    created = service.create(job_id, profile_id="example", metadata=_metadata(payload))
    real_transition = service.store.transition
    failed_ready_write = False

    def fail_first_ready_transition(preparation_id, target, **kwargs):
        nonlocal failed_ready_write
        if target is ReleasePreparationState.READY and not failed_ready_write:
            failed_ready_write = True
            raise sqlite3.OperationalError("injected READY persistence failure")
        return real_transition(preparation_id, target, **kwargs)

    monkeypatch.setattr(
        service.store,
        "transition",
        fail_first_ready_transition,
    )

    with pytest.raises(ReleaseServiceError, match="failed safely"):
        service.build(created.id, expected_version=created.version)

    failed = service.store.get(created.id)
    kit = service.settings.release_kits_root / created.id
    assert failed.state is ReleasePreparationState.FAILED
    assert failed.kit_path is None
    assert not kit.exists()
    trash = service.settings.release_kits_root / ".trash"
    assert not trash.exists() or tuple(trash.iterdir()) == ()


def _install_dupe_checker(
    monkeypatch: pytest.MonkeyPatch,
    outcome: DupeCheckOutcome | Exception,
    calls: list[str] | None = None,
) -> None:
    class FakeChecker:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def check(self, metadata, *, profile_id, manifest_sha256):
            if calls is not None:
                calls.append(manifest_sha256)
            if isinstance(outcome, Exception):
                raise outcome
            return DupeCheckReceipt(
                profile_id=profile_id,
                manifest_sha256=manifest_sha256,
                metadata_sha256=metadata.canonical_digest(),
                outcome=outcome,
                matches=(
                    ("Example.Movie.2026.1080p.BluRay.x264-OTHER",)
                    if outcome is DupeCheckOutcome.DUPLICATE
                    else ()
                ),
                checked_at=datetime.now(UTC),
            )

    monkeypatch.setattr(release_service_module, "HttpDupeChecker", FakeChecker)


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [
        (DupeCheckOutcome.CLEAR, ReleasePreparationState.READY_TO_PUBLISH),
        (DupeCheckOutcome.DUPLICATE, ReleasePreparationState.NEEDS_REVIEW),
        (DupeCheckOutcome.UNKNOWN, ReleasePreparationState.UNKNOWN),
    ],
)
def test_dupe_check_records_the_tracker_answer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    outcome: DupeCheckOutcome,
    expected: ReleasePreparationState,
) -> None:
    service, job_id, payload = _fixture(tmp_path)
    created = service.create(job_id, profile_id="example", metadata=_metadata(payload))
    ready = service.build(created.id, expected_version=created.version)
    calls: list[str] = []
    _install_dupe_checker(monkeypatch, outcome, calls)

    checked = service.dupe_check(ready.id, expected_version=ready.version)

    assert calls == [ready.manifest_sha256]
    assert checked.state is expected
    receipt = service.store.get(ready.id).dupe_receipt
    assert receipt is not None
    assert receipt["outcome"] == outcome.value
    assert receipt["manifest_sha256"] == ready.manifest_sha256


def test_dupe_check_failure_is_recorded_as_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, job_id, payload = _fixture(tmp_path)
    created = service.create(job_id, profile_id="example", metadata=_metadata(payload))
    ready = service.build(created.id, expected_version=created.version)
    _install_dupe_checker(monkeypatch, OSError("tracker unreachable"))

    with pytest.raises(ReleaseServiceError, match="did not complete"):
        service.dupe_check(ready.id, expected_version=ready.version)

    failed = service.store.get(ready.id)
    assert failed.state is ReleasePreparationState.UNKNOWN
    assert failed.error


def test_dupe_check_requires_the_canonical_profile_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, job_id, payload = _fixture(tmp_path)
    created = service.create(job_id, profile_id="example", metadata=_metadata(payload))
    ready = service.build(created.id, expected_version=created.version)
    calls: list[str] = []
    _install_dupe_checker(monkeypatch, DupeCheckOutcome.CLEAR, calls)
    document = json.loads(
        service.settings.resolved_release_profiles_path.read_text(encoding="utf-8")
    )
    document["profiles"][0]["tracker"]["display_name"] = "Changed profile"
    service.settings.resolved_release_profiles_path.write_text(
        json.dumps(document), encoding="utf-8"
    )

    with pytest.raises(StateConflictError, match="profile changed"):
        service.dupe_check(ready.id, expected_version=ready.version)

    assert calls == []
    assert service.store.get(ready.id).state is ReleasePreparationState.READY


def test_dupe_check_revalidates_the_completed_payload_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, job_id, payload = _fixture(tmp_path)
    created = service.create(job_id, profile_id="example", metadata=_metadata(payload))
    ready = service.build(created.id, expected_version=created.version)
    calls: list[str] = []
    _install_dupe_checker(monkeypatch, DupeCheckOutcome.CLEAR, calls)
    payload.write_bytes(b"tampered after release preparation")

    with pytest.raises(ReleaseServiceError, match="owner/artifact"):
        service.dupe_check(ready.id, expected_version=ready.version)

    assert calls == []
    assert service.store.get(ready.id).state is ReleasePreparationState.READY


def test_crash_recovery_fails_build_and_quarantines_orphan_kit(
    tmp_path: Path,
) -> None:
    service, job_id, payload = _fixture(tmp_path)
    created = service.create(job_id, profile_id="example", metadata=_metadata(payload))
    preparing = service.store.transition(
        created.id,
        ReleasePreparationState.PREPARING,
        expected_version=created.version,
    )
    orphan = service.settings.release_kits_root / preparing.id
    orphan.mkdir()
    (orphan / "partial").write_bytes(b"partial")
    generic = service.settings.release_kits_root / ".release-build-crashed"
    generic.mkdir()
    (generic / "partial").write_bytes(b"partial")

    service._recover_interrupted_operations()

    assert service.store.get(preparing.id).state is ReleasePreparationState.FAILED
    assert not orphan.exists()
    assert not generic.exists()


def test_second_service_in_same_singleton_lifecycle_does_not_recover_live_work(
    tmp_path: Path,
) -> None:
    service, job_id, payload = _fixture(tmp_path)
    created = service.create(job_id, profile_id="example", metadata=_metadata(payload))
    preparing = service.store.transition(
        created.id,
        ReleasePreparationState.PREPARING,
        expected_version=created.version,
    )

    ReleaseService(service.database, service.settings, runner=_Runner())

    assert service.store.get(preparing.id).state is ReleasePreparationState.PREPARING


def test_stable_bounded_read_rejects_an_in_read_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "completed"
    root.mkdir()
    owner = root / ".bdencode-owner.json"
    owner.write_bytes(b"owner record")
    real_fstat = release_service_module.os.fstat
    calls = 0

    def changing_fstat(descriptor: int):
        nonlocal calls
        details = real_fstat(descriptor)
        calls += 1
        if calls != 2:
            return details
        return SimpleNamespace(
            st_dev=details.st_dev,
            st_ino=details.st_ino,
            st_size=details.st_size,
            st_mtime_ns=details.st_mtime_ns + 1,
            st_mode=details.st_mode,
        )

    monkeypatch.setattr(release_service_module.os, "fstat", changing_fstat)
    with pytest.raises(ReleaseServiceError, match="changed while it was read"):
        _read_stable_bounded_file(owner, root=root, maximum_bytes=1024)


def test_stable_bounded_read_rejects_a_link(tmp_path: Path) -> None:
    root = tmp_path / "completed"
    root.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_bytes(b"outside")
    link = root / ".bdencode-owner.json"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symbolic links are unavailable on this Windows host")

    with pytest.raises(ReleaseServiceError, match="not a regular file"):
        _read_stable_bounded_file(link, root=root, maximum_bytes=1024)


def test_stable_bounded_read_rejects_a_delete_race(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "completed"
    root.mkdir()
    owner = root / ".bdencode-owner.json"
    owner.write_bytes(b"owner record")
    real_lstat = Path.lstat
    target_calls = 0

    def disappearing_lstat(path: Path, *args, **kwargs):
        nonlocal target_calls
        if path == owner:
            target_calls += 1
            if target_calls == 2:
                raise FileNotFoundError(owner)
        return real_lstat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", disappearing_lstat)
    with pytest.raises(ReleaseServiceError, match="disappeared"):
        _read_stable_bounded_file(owner, root=root, maximum_bytes=1024)
