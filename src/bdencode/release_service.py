"""Application service for release kits: NFO, description, MediaInfo, screenshots.

Since 3.0 BDEncode creates no torrent, seeds nothing and uploads nothing; the
tracker's duplicate check is the only network call left.
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import stat
import threading
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict

from .config import ConfigurationError, Settings
from .db import Database, StateConflictError
from .maintenance import (
    MaintenanceDomainGuard,
    MaintenanceJournal,
    MaintenanceSafetyError,
    MaintenanceTargetSpec,
)
from .models import ArtifactKind, JobState
from .process import CommandRunner
from .release import (
    DupeCheckOutcome,
    HttpDupeChecker,
    ReleaseMetadata,
    ReleasePreparationState,
    build_upload_kit,
    sanitize_release_text,
    verify_upload_kit,
)
from .release_profiles import ConfiguredReleaseProfile, load_release_profiles
from .release_store import ReleasePreparation, ReleaseStore
from .utils import sha256_file


_STARTUP_RECOVERY_LOCK = threading.Lock()
_STARTUP_RECOVERED_DATABASES: set[str] = set()


class ReleaseServiceError(RuntimeError):
    pass


class ReleasePreparationView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    job_id: str
    state: ReleasePreparationState
    profile_id: str
    profile_digest: str
    metadata: ReleaseMetadata
    payload_path: str
    payload_size: int
    payload_sha256: str
    kit_ready: bool
    manifest_sha256: str | None
    torrent_infohash: str | None
    torrent_sha256: str | None
    dupe_receipt: dict[str, Any] | None
    qbittorrent_receipt: dict[str, Any] | None
    publication_receipt: dict[str, Any] | None
    error: str | None
    version: int
    created_at: datetime
    updated_at: datetime


def _is_link_or_reparse(path: Path) -> bool:
    try:
        information = path.lstat()
    except FileNotFoundError:
        return False
    flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return path.is_symlink() or bool(
        getattr(information, "st_file_attributes", 0) & flag
    )


def _safe_message(exc: BaseException) -> str:
    # External tool and network exceptions may contain local paths or remote
    # response bodies.  The precise exception remains available to the caller's
    # private traceback; only this bounded classification is persisted/API-visible.
    return f"{type(exc).__name__}: release operation did not complete"


def _comparison_png(root: Path, item: dict[str, Any], key: str) -> Path | None:
    """One hash-checked PNG of a comparison pair, directly inside ``root``."""

    name = item.get(key)
    if not isinstance(name, str) or Path(name).name != name:
        return None
    candidate = root / name
    if (
        candidate.suffix.casefold() != ".png"
        or _is_link_or_reparse(candidate)
        or not candidate.is_file()
        or candidate.resolve(strict=True).parent != root
    ):
        return None
    expected_hash = item.get(key.replace("png", "sha256"))
    if isinstance(expected_hash, str) and sha256_file(candidate) != expected_hash:
        return None
    return candidate


def _file_identity(details: os.stat_result) -> tuple[int, int, int, int]:
    return (
        details.st_dev,
        details.st_ino,
        details.st_size,
        details.st_mtime_ns,
    )


def _read_stable_bounded_file(path: Path, *, root: Path, maximum_bytes: int) -> bytes:
    """Read one direct-child file without following a replace/link race."""

    if maximum_bytes < 1:
        raise ValueError("maximum_bytes must be positive")
    path = Path(path)
    root = Path(root)
    try:
        if _is_link_or_reparse(root) or not root.is_dir():
            raise ReleaseServiceError("release file directory is unsafe")
        resolved_root = root.resolve(strict=True)
        before = path.lstat()
        reparse = getattr(before, "st_file_attributes", 0) & getattr(
            stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400
        )
        if stat.S_ISLNK(before.st_mode) or reparse or not stat.S_ISREG(before.st_mode):
            raise ReleaseServiceError("release file is not a regular file")
        resolved = path.resolve(strict=True)
        if resolved.parent != resolved_root:
            raise ReleaseServiceError("release file escaped its directory")
        if before.st_size > maximum_bytes:
            raise ReleaseServiceError("release file exceeds the size limit")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        try:
            opened = os.fstat(descriptor)
            if _file_identity(opened) != _file_identity(before) or not stat.S_ISREG(
                opened.st_mode
            ):
                raise ReleaseServiceError("release file changed while it was opened")
            chunks: list[bytes] = []
            remaining = maximum_bytes + 1
            while remaining:
                chunk = os.read(descriptor, min(1024 * 1024, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            after_open = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        after = path.lstat()
        data = b"".join(chunks)
        if (
            _file_identity(after_open) != _file_identity(before)
            or _file_identity(after) != _file_identity(before)
            or len(data) != before.st_size
        ):
            raise ReleaseServiceError("release file changed while it was read")
        if len(data) > maximum_bytes:
            raise ReleaseServiceError("release file exceeds the size limit")
        return data
    except ReleaseServiceError:
        raise
    except OSError:
        raise ReleaseServiceError(
            "release file changed or disappeared while it was read"
        ) from None


def _stable_file_sha256(path: Path, *, root: Path) -> tuple[int, str]:
    """Hash one direct-child regular file through a pinned descriptor."""

    path = Path(path)
    root = Path(root)
    try:
        if _is_link_or_reparse(root) or not root.is_dir():
            raise ReleaseServiceError("release directory is unsafe")
        resolved_root = root.resolve(strict=True)
        before = path.lstat()
        reparse = getattr(before, "st_file_attributes", 0) & getattr(
            stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400
        )
        if stat.S_ISLNK(before.st_mode) or reparse or not stat.S_ISREG(before.st_mode):
            raise ReleaseServiceError("release payload is not a regular file")
        if path.resolve(strict=True).parent != resolved_root:
            raise ReleaseServiceError("release payload escaped its owned directory")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        try:
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode) or _file_identity(
                opened
            ) != _file_identity(before):
                raise ReleaseServiceError("release payload changed before hashing")
            digest = hashlib.sha256()
            while chunk := os.read(descriptor, 1024 * 1024):
                digest.update(chunk)
            after_open = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        after = path.lstat()
        if not (
            _file_identity(before)
            == _file_identity(opened)
            == _file_identity(after_open)
            == _file_identity(after)
        ):
            raise ReleaseServiceError("release payload changed while hashing")
        return opened.st_size, digest.hexdigest()
    except ReleaseServiceError:
        raise
    except OSError:
        raise ReleaseServiceError(
            "release payload changed or disappeared while it was hashed"
        ) from None


class ReleaseService:
    def __init__(
        self,
        database: Database,
        settings: Settings,
        *,
        store: ReleaseStore | None = None,
        maintenance_journal: MaintenanceJournal | None = None,
        runner: CommandRunner | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.database = database
        self.settings = settings
        self.store = store or ReleaseStore(database)
        self.maintenance = maintenance_journal or MaintenanceJournal(database, settings)
        self.runner = runner or CommandRunner()
        self._now = now or (lambda: datetime.now(UTC))
        self.maintenance.recover()
        self._recover_once_at_startup()

    def _startup_recovery_key(self) -> str:
        path = self.database.display_path
        if path == ":memory:":
            return f":memory:{id(self.database)}"
        return os.path.normcase(os.path.abspath(os.path.expanduser(path)))

    def _recover_once_at_startup(self) -> None:
        """Recover crash leases exactly once during a process singleton's life."""

        key = self._startup_recovery_key()
        with _STARTUP_RECOVERY_LOCK:
            if key in _STARTUP_RECOVERED_DATABASES:
                return
            self._recover_interrupted_operations()
            _STARTUP_RECOVERED_DATABASES.add(key)

    def _recover_interrupted_operations(self) -> None:
        root = self.settings.release_kits_root
        interrupted = self.store.list_interrupted()
        preparing_ids = {
            record.id
            for record in interrupted
            if record.state is ReleasePreparationState.PREPARING
        }
        if _is_link_or_reparse(root) or not root.is_dir():
            raise ReleaseServiceError("release-kit root is unsafe")
        resolved_root = root.resolve(strict=True)
        candidates = [
            child
            for child in resolved_root.iterdir()
            if child.name.startswith(".release-build-")
            or any(
                child.name == identifier or child.name.startswith(f".{identifier}.tmp-")
                for identifier in preparing_ids
            )
        ]
        operation = (
            self.maintenance.begin(
                "interrupted-release-cleanup",
                "startup",
                [
                    MaintenanceTargetSpec(
                        candidate,
                        resolved_root,
                        "orphan release build",
                    )
                    for candidate in candidates
                ],
            )
            if candidates
            else None
        )
        try:
            if operation is not None:
                self.maintenance.stage(operation.id)
            if interrupted:
                self.store.recover_interrupted(
                    maintenance_operation_id=(
                        operation.id if operation is not None else None
                    )
                )
            elif operation is not None:
                with self.database._write() as connection:
                    self.database._mark_maintenance_committed(
                        connection,
                        operation.id,
                        kind="interrupted-release-cleanup",
                        subject_id="startup",
                    )
        except BaseException:
            if operation is not None:
                self.maintenance.rollback(operation.id)
            raise
        if operation is not None:
            try:
                self.maintenance.finalize(operation.id)
            except (MaintenanceSafetyError, OSError):
                # The committed journal remains for a later fail-closed retry.
                pass

    def profiles(self) -> tuple[dict[str, object], ...]:
        document = load_release_profiles(self.settings.resolved_release_profiles_path)
        return tuple(item.public_dict() for item in document.profiles)

    def _profile(self, profile_id: str) -> ConfiguredReleaseProfile:
        return load_release_profiles(self.settings.resolved_release_profiles_path).get(
            profile_id
        )

    def _bound_profile(self, record: ReleasePreparation) -> ConfiguredReleaseProfile:
        profile = self._profile(record.profile_id)
        if profile.canonical_digest() != record.profile_digest:
            raise StateConflictError(
                "tracker profile changed after release preparation creation"
            )
        return profile

    @staticmethod
    def view(record: ReleasePreparation) -> ReleasePreparationView:
        return ReleasePreparationView(
            id=record.id,
            job_id=record.job_id,
            state=record.state,
            profile_id=record.profile_id,
            profile_digest=record.profile_digest,
            metadata=record.metadata,
            payload_path=f"{record.metadata.release_name}/{record.payload_name}",
            payload_size=record.payload_size,
            payload_sha256=record.payload_sha256,
            kit_ready=record.kit_path is not None,
            manifest_sha256=record.manifest_sha256,
            torrent_infohash=record.torrent_infohash,
            torrent_sha256=record.torrent_sha256,
            dupe_receipt=record.dupe_receipt,
            qbittorrent_receipt=record.qbittorrent_receipt,
            publication_receipt=record.publication_receipt,
            error=record.error,
            version=record.version,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    def list_for_job(self, job_id: str) -> tuple[ReleasePreparationView, ...]:
        self.database.get_job(job_id)
        return tuple(self.view(item) for item in self.store.list_for_job(job_id))

    def get(self, preparation_id: str) -> ReleasePreparationView:
        return self.view(self.store.get(preparation_id))

    def _payload_artifact(self, job_id: str) -> tuple[Path, int, str]:
        job = self.database.get_job(job_id)
        if job.state is not JobState.COMPLETED:
            raise StateConflictError(
                "release preparation requires a completed encode", current=job.state
            )
        outputs = tuple(
            item
            for item in self.database.list_artifacts(job_id=job_id, limit=1000)
            if item.kind is ArtifactKind.OUTPUT
        )
        if len(outputs) != 1:
            raise ReleaseServiceError(
                "completed job must have exactly one registered output"
            )
        artifact = outputs[0]
        path = Path(artifact.path)
        completed_root = self.settings.completed_root.resolve(strict=True)
        if _is_link_or_reparse(path) or not path.is_file():
            raise ReleaseServiceError("registered output is not a regular media file")
        resolved = path.resolve(strict=True)
        if (
            resolved.suffix.casefold() != ".mkv"
            or resolved.parent.parent != completed_root
            or resolved.parent.name != resolved.stem
        ):
            raise ReleaseServiceError(
                "registered output escaped the completed release tree"
            )
        owner = resolved.parent / ".bdencode-owner.json"
        if _is_link_or_reparse(owner) or not owner.is_file():
            raise ReleaseServiceError("completed release has no safe owner record")
        try:
            owner_bytes = _read_stable_bounded_file(
                owner,
                root=resolved.parent,
                maximum_bytes=64 * 1024,
            )
            ownership = json.loads(owner_bytes.decode("utf-8"))
        except (OSError, UnicodeError, ValueError) as exc:
            raise ReleaseServiceError(
                "completed release owner record is invalid"
            ) from exc
        if set(ownership) != {"schema_version", "output_name", "mux_sha256"}:
            raise ReleaseServiceError(
                "completed release owner record has unknown fields"
            )
        size, digest = _stable_file_sha256(resolved, root=resolved.parent)
        if (
            ownership.get("schema_version") != 2
            or ownership.get("output_name") != resolved.stem
            or ownership.get("mux_sha256") != digest
            or artifact.sha256 is None
            or artifact.sha256.casefold() != digest
            or (artifact.size_bytes is not None and artifact.size_bytes != size)
        ):
            raise ReleaseServiceError(
                "completed output no longer matches its owner/artifact"
            )
        return resolved, size, digest

    def _bound_payload(self, record: ReleasePreparation) -> Path:
        payload, size, digest = self._payload_artifact(record.job_id)
        if (
            str(payload) != record.payload_path
            or payload.name != record.payload_name
            or size != record.payload_size
            or digest != record.payload_sha256
        ):
            raise StateConflictError(
                "completed output changed after release preparation creation"
            )
        return payload

    def create(
        self,
        job_id: str,
        *,
        profile_id: str,
        metadata: ReleaseMetadata,
    ) -> ReleasePreparationView:
        profile = self._profile(profile_id)
        payload, size, digest = self._payload_artifact(job_id)
        if metadata.release_name != payload.stem:
            raise ReleaseServiceError(
                "release_name must exactly match the completed MKV name"
            )
        record = self.store.create(
            job_id=job_id,
            profile_id=profile_id,
            profile_digest=profile.canonical_digest(),
            metadata=metadata,
            payload_name=payload.name,
            payload_path=str(payload),
            payload_size=size,
            payload_sha256=digest,
        )
        return self.view(record)

    def validate(self, preparation_id: str) -> dict[str, object]:
        record = self.store.get(preparation_id)
        profile = self._profile(record.profile_id)
        failures: list[str] = []
        try:
            payload, size, digest = self._payload_artifact(record.job_id)
        except ReleaseServiceError:
            payload = Path(record.payload_path)
            size = record.payload_size
            digest = record.payload_sha256
            failures.append("completed MKV changed after preparation creation")
        if profile.canonical_digest() != record.profile_digest:
            failures.append("tracker profile changed after preparation creation")
        if (
            str(payload) != record.payload_path
            or size != record.payload_size
            or digest != record.payload_sha256
        ):
            failures.append("completed MKV changed after preparation creation")
        screenshots: tuple[Path, ...] = ()
        try:
            screenshots = self._screenshots(payload, profile)
        except ReleaseServiceError as exc:
            failures.append(str(exc))
        if record.kit_path and record.manifest_sha256:
            try:
                verify_upload_kit(
                    Path(record.kit_path),
                    expected_manifest_sha256=record.manifest_sha256,
                )
            except (OSError, ValueError, RuntimeError):
                failures.append("upload kit no longer matches its approved manifest")
        return {
            "valid": not failures,
            "failures": failures,
            "payload": {
                "path": f"{record.metadata.release_name}/{record.payload_name}",
                "size": record.payload_size,
                "sha256": record.payload_sha256,
            },
            "screenshots": len(screenshots),
            "profile_digest": record.profile_digest,
            "manifest_sha256": record.manifest_sha256,
        }

    def _screenshots(
        self,
        payload: Path,
        profile: ConfiguredReleaseProfile,
    ) -> tuple[Path, ...]:
        root = payload.parent / "comparison"
        if _is_link_or_reparse(root) or not root.is_dir():
            raise ReleaseServiceError("completed comparison evidence is unavailable")
        resolved_root = root.resolve(strict=True)
        if resolved_root.parent != payload.parent:
            raise ReleaseServiceError(
                "comparison evidence escaped the completed release"
            )
        manifest_path = resolved_root / "video-comparison.json"
        if _is_link_or_reparse(manifest_path) or not manifest_path.is_file():
            raise ReleaseServiceError("video comparison manifest is unavailable")
        if manifest_path.stat().st_size > 4 * 1024 * 1024:
            raise ReleaseServiceError("video comparison manifest is too large")
        try:
            document = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ReleaseServiceError("video comparison manifest is invalid") from exc
        pairs = document.get("pairs") if isinstance(document, dict) else None
        if not isinstance(pairs, list):
            raise ReleaseServiceError("video comparison has no screenshot pairs")
        labelled: list[Path] = []
        clean: list[Path] = []
        for item in pairs:
            if not isinstance(item, dict):
                continue
            key = (
                "encode_sdr_png"
                if isinstance(item.get("encode_sdr_png"), str)
                else "encode_png"
            )
            if (candidate := _comparison_png(resolved_root, item, key)) is not None:
                labelled.append(candidate)
            # Tracker jobs also keep clean, unlabelled frames for screenshots.
            if (
                screenshot := _comparison_png(resolved_root, item, "screenshot_png")
            ) is not None:
                clean.append(screenshot)
        maximum = profile.tracker.screenshot_maximum
        minimum = profile.tracker.screenshot_minimum
        candidates = clean if clean and len(clean) >= minimum else labelled
        if len(candidates) < minimum:
            raise ReleaseServiceError(
                "completed release has too few validated encode-only screenshots"
            )
        if len(candidates) <= maximum:
            return tuple(candidates)
        # Evenly spread the chosen images across the title-wide comparison set.
        if maximum == 1:
            return (candidates[len(candidates) // 2],)
        indexes = {
            round(index * (len(candidates) - 1) / (maximum - 1))
            for index in range(maximum)
        }
        return tuple(candidates[index] for index in sorted(indexes))

    def _release_text(self, record: ReleasePreparation) -> tuple[str, str, str]:
        payload = Path(record.payload_path)
        completed = self.runner.capture(
            ["mediainfo", str(payload)], timeout=120, check=True
        )
        mediainfo = sanitize_release_text(
            completed.stdout,
            payload_filename=record.payload_name,
        )
        metadata = record.metadata
        identifiers = "\n".join(
            value
            for value in (
                f"IMDb: {metadata.imdb_id}" if metadata.imdb_id else "",
                f"TMDb: {metadata.tmdb_id}" if metadata.tmdb_id else "",
            )
            if value
        )
        nfo = (
            f"{metadata.release_name}\n\n"
            f"Title: {metadata.title}\nYear: {metadata.year}\n"
            f"Source: {metadata.source_media}\nResolution: {metadata.resolution}\n"
            f"Video: {metadata.video_codec}\n"
            f"Audio: {', '.join(metadata.audio_codecs)}\n"
            f"Languages: {', '.join(metadata.languages)}\n"
            f"Size: {record.payload_size} bytes\n"
            f"SHA-256: {record.payload_sha256}\n{identifiers}\n"
        )
        description = (
            f"[b]{metadata.title} ({metadata.year})[/b]\n\n"
            f"[b]Release[/b]: {metadata.release_name}\n"
            f"[b]Source[/b]: {metadata.source_media}\n"
            f"[b]Video[/b]: {metadata.video_codec} / {metadata.resolution}\n"
            f"[b]Audio[/b]: {', '.join(metadata.audio_codecs)}\n"
            f"[b]Languages[/b]: {', '.join(metadata.languages)}\n"
            f"\n[spoiler=MediaInfo]\n{mediainfo}\n[/spoiler]\n"
        )
        return mediainfo, nfo, description

    def build(
        self, preparation_id: str, *, expected_version: int
    ) -> ReleasePreparationView:
        record = self.store.get(preparation_id)
        profile = self._bound_profile(record)
        preflight = self.validate(preparation_id)
        if not preflight["valid"]:
            raise ReleaseServiceError("release preflight failed")
        preparing = self.store.transition(
            preparation_id,
            ReleasePreparationState.PREPARING,
            expected_version=expected_version,
            values={"error": None},
        )
        release_root = self.settings.release_kits_root
        try:
            release_root.mkdir(mode=0o750, parents=True, exist_ok=True)
            if _is_link_or_reparse(release_root) or not release_root.is_dir():
                raise ReleaseServiceError("release-kit root is unsafe")
            # Re-hash the completed MKV now: the kit records what it describes.
            payload = self._bound_payload(preparing)
            screenshots = self._screenshots(payload, profile)
            mediainfo, nfo, description = self._release_text(preparing)
            kit = build_upload_kit(
                release_root / preparing.id,
                profile=profile.tracker,
                metadata=preparing.metadata,
                payload_path=payload,
                payload_size=preparing.payload_size,
                payload_sha256=preparing.payload_sha256,
                mediainfo=mediainfo,
                nfo=nfo,
                description_bbcode=description,
                screenshots=screenshots,
                screenshot_roots=(payload.parent / "comparison",),
                created_at=self._now(),
            )
            ready = self.store.transition(
                preparing.id,
                ReleasePreparationState.READY,
                expected_version=preparing.version,
                values={
                    "kit_path": str(kit.directory),
                    "manifest_sha256": kit.manifest_sha256,
                    "error": None,
                },
            )
            return self.view(ready)
        except Exception as exc:
            current = self.store.get(preparation_id)
            if current.state is ReleasePreparationState.PREPARING:
                final_kit = release_root / current.id
                operation = None
                try:
                    if os.path.lexists(final_kit):
                        operation = self.maintenance.begin(
                            "failed-release-build-cleanup",
                            current.id,
                            [
                                MaintenanceTargetSpec(
                                    final_kit,
                                    release_root,
                                    "failed private release kit",
                                )
                            ],
                            guard=MaintenanceDomainGuard(
                                job_id=current.job_id,
                                preparation_id=current.id,
                                expected_preparation_version=current.version,
                                allowed_preparation_states=(
                                    ReleasePreparationState.PREPARING.value,
                                ),
                            ),
                        )
                        self.maintenance.stage(operation.id)
                    self.store.fail_build(
                        preparation_id,
                        expected_version=current.version,
                        error=_safe_message(exc),
                        maintenance_operation_id=(
                            operation.id if operation is not None else None
                        ),
                    )
                except BaseException:
                    if operation is not None:
                        self.maintenance.rollback(operation.id)
                    raise ReleaseServiceError(
                        "release build failed and requires startup recovery"
                    ) from None
                if operation is not None:
                    try:
                        self.maintenance.finalize(operation.id)
                    except (MaintenanceSafetyError, OSError):
                        # The FAILED transition committed the durable detach.
                        pass
            raise ReleaseServiceError("release build failed safely") from None

    def dupe_check(
        self, preparation_id: str, *, expected_version: int
    ) -> ReleasePreparationView:
        record = self.store.get(preparation_id)
        if record.state is not ReleasePreparationState.READY:
            raise StateConflictError("dupe check requires a READY release kit")
        profile = self._bound_profile(record)
        self._bound_payload(record)
        network = profile.network
        credential_name = profile.tracker.credential_name
        if (
            not network
            or not network.dupe_check_endpoint
            or not credential_name
            or not record.manifest_sha256
        ):
            raise ConfigurationError("tracker profile has no duplicate-check endpoint")
        checker = HttpDupeChecker(
            network.dupe_check_endpoint,
            allowed_hosts=network.allowed_hosts,
            credential_name=credential_name,
        )
        checking = self.store.transition(
            preparation_id,
            ReleasePreparationState.SEEDING_CHECK,
            expected_version=expected_version,
        )
        try:
            receipt = checker.check(
                checking.metadata,
                profile_id=checking.profile_id,
                manifest_sha256=checking.manifest_sha256 or "",
            )
        except Exception as exc:
            self.store.transition(
                preparation_id,
                ReleasePreparationState.UNKNOWN,
                expected_version=checking.version,
                values={"error": _safe_message(exc)},
            )
            raise ReleaseServiceError("duplicate check did not complete") from None
        if receipt.outcome is DupeCheckOutcome.CLEAR:
            target = ReleasePreparationState.READY_TO_PUBLISH
        elif receipt.outcome is DupeCheckOutcome.DUPLICATE:
            target = ReleasePreparationState.NEEDS_REVIEW
        else:
            target = ReleasePreparationState.UNKNOWN
        updated = self.store.transition(
            preparation_id,
            target,
            expected_version=checking.version,
            values={"dupe_receipt_json": receipt.model_dump(mode="json")},
        )
        return self.view(updated)

    def _verified_maintenance_kit(self, record: ReleasePreparation) -> Path | None:
        if record.kit_path is None:
            return None
        root = self.settings.release_kits_root
        try:
            resolved_root = root.resolve(strict=True)
            kit = Path(record.kit_path)
            resolved = kit.resolve(strict=True)
            if (
                _is_link_or_reparse(kit)
                or not kit.is_dir()
                or resolved != resolved_root / record.id
                or resolved.parent != resolved_root
                or kit.name != record.id
            ):
                raise ReleaseServiceError("release kit cannot be safely deleted")
            if not record.manifest_sha256:
                raise ReleaseServiceError("release kit has no manifest binding")
            verify_upload_kit(
                resolved,
                expected_manifest_sha256=record.manifest_sha256,
            )
            return resolved
        except ReleaseServiceError:
            raise
        except (OSError, ValueError, RuntimeError):
            raise ReleaseServiceError(
                "release kit failed maintenance verification"
            ) from None

    def delete(self, preparation_id: str, *, expected_version: int) -> None:
        record = self.store.get(preparation_id)
        if record.version != expected_version:
            raise StateConflictError(
                f"release preparation version is {record.version}, "
                f"expected {expected_version}"
            )
        deletable_states = {
            ReleasePreparationState.NOT_PREPARED,
            ReleasePreparationState.READY,
            ReleasePreparationState.READY_TO_PUBLISH,
            ReleasePreparationState.NEEDS_REVIEW,
            ReleasePreparationState.FAILED,
        }
        if (
            record.state
            in {
                ReleasePreparationState.UNKNOWN,
                ReleasePreparationState.PUBLISHED,
            }
            or (
                record.qbittorrent_receipt is not None
                and record.qbittorrent_receipt.get("outcome") != "REJECTED"
            )
            or (
                record.publication_receipt is not None
                and record.publication_receipt.get("outcome") != "REJECTED"
            )
        ):
            raise StateConflictError(
                "release preparation has an external outcome and must remain "
                "available for reconciliation or completed-release deletion"
            )
        if record.state not in deletable_states:
            raise StateConflictError("active release preparation cannot be deleted")
        root = self.settings.release_kits_root
        kit = self._verified_maintenance_kit(record)
        operation = (
            self.maintenance.begin(
                "release-preparation-delete",
                preparation_id,
                [
                    MaintenanceTargetSpec(
                        kit,
                        root,
                        "private release kit",
                    )
                ],
                guard=MaintenanceDomainGuard(
                    job_id=record.job_id,
                    preparation_id=record.id,
                    expected_preparation_version=expected_version,
                    allowed_preparation_states=tuple(
                        state.value for state in deletable_states
                    ),
                ),
            )
            if kit is not None
            else None
        )

        try:
            if operation is not None:
                self.maintenance.stage(operation.id)
            self.store.delete(
                preparation_id,
                expected_version=expected_version,
                maintenance_operation_id=(
                    operation.id if operation is not None else None
                ),
            )
        except BaseException:
            if operation is not None:
                self.maintenance.rollback(operation.id)
            raise
        if operation is not None:
            try:
                self.maintenance.finalize(operation.id)
            except (MaintenanceSafetyError, OSError):
                pass


__all__ = [
    "ReleasePreparationView",
    "ReleaseService",
    "ReleaseServiceError",
]
