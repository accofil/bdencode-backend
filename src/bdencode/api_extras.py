"""Operator-facing extras: statistics, profile library, player, DB backups.

These routes live outside :mod:`bdencode.api` to keep that module focused on the
queue/pipeline contract.  They use the same ``/api/v1`` prefix, the same
same-origin mutation guard and the same error envelope.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import Body, FastAPI, Query, Request, status
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from .config import ConfigurationError, Settings
from .cpu_policy import CpuPolicy, policy_view, save_policy
from .db import Database, NotFoundError, PersistenceError, StateConflictError
from .db_backup import BackupError, list_backups
from .external import source as external_source
from .external import spec as external_spec
from .job_statistics import compute_job_statistics, completed_statistics
from .models import ArtifactKind, JobState
from .previews import PreviewError, PreviewRequest, PreviewService
from .profile_library import (
    ProfileExists,
    ProfileLibrary,
    ProfileLibraryError,
    ProfileNotFound,
)

#: Written by the root-owned daily release check; world-readable, no secrets.
RELEASE_UPDATE_STATUS_PATH = Path("/var/lib/bdencode/release-update/status.json")

_PREVIEW_STATUS = {
    "invalid": 422,
    "no_output": 409,
    "not_found": 404,
    "unavailable": 503,
    "timeout": 504,
    "probe_failed": 502,
    "transcode_failed": 502,
}
_LIBRARY_STATUS = {
    "not_found": 404,
    "exists": 409,
    "unsupported_version": 422,
    "too_large": 413,
    "limit": 409,
}


class PreviewBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_seconds: int = Field(default=0, ge=0, le=86_400)
    duration_seconds: int = Field(default=20, ge=5, le=30)
    height: Literal[360, 480, 720] = 720


class ExternalApprovalBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    map_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ExternalPitchBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stream: str = Field(min_length=1, max_length=16)
    pitch: Literal["restore", "keep"]


class ExternalExcerptBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    track: int = Field(default=0, ge=0, le=64)
    subtitle: int | None = Field(default=None, ge=0, le=64)
    audio: Literal["fitted", "original", "both"] = "fitted"
    start_seconds: int = Field(default=0, ge=0, le=86_400)
    duration_seconds: int = Field(default=20, ge=5, le=30)
    height: Literal[360, 480, 720] = 480


def register_extra_routes(
    application: FastAPI,
    *,
    db: Database,
    settings: Settings | None,
    prefix: str,
) -> None:
    in_memory = db.path == ":memory:"
    base = Path(db.path).expanduser().parent if not in_memory else None

    def library() -> ProfileLibrary:
        directory = (
            settings.state_root / "profile-library"
            if settings is not None
            else (base / "profile-library" if base else None)
        )
        if directory is None:
            raise ConfigurationError("the profile library is not configured")
        return ProfileLibrary(directory)

    def backup_directory() -> Path:
        return settings.state_root / "backups" if settings is not None else db.backup_directory

    def preview_service() -> PreviewService:
        service = getattr(application.state, "preview_service", None)
        if service is not None:
            return service
        root = (
            settings.cache_root
            if settings is not None
            else (base / "cache" if base else None)
        )
        if root is None:
            raise PreviewError("unavailable", "previews need a configured cache")
        application.state.preview_service = PreviewService(root)
        return application.state.preview_service

    def job_root(job_id: str) -> Path | None:
        return settings.job_root(job_id) if settings is not None else None

    # -- error envelope ---------------------------------------------------------------------
    @application.exception_handler(ProfileLibraryError)
    async def library_error(_request: Request, exc: ProfileLibraryError) -> JSONResponse:
        return JSONResponse(
            status_code=_LIBRARY_STATUS.get(exc.code, 422),
            content={"detail": str(exc), "code": exc.code},
        )

    @application.exception_handler(PreviewError)
    async def preview_error(_request: Request, exc: PreviewError) -> JSONResponse:
        return JSONResponse(
            status_code=_PREVIEW_STATUS.get(exc.code, 500),
            content={"detail": str(exc), "code": exc.code},
        )

    @application.exception_handler(BackupError)
    async def backup_error(_request: Request, exc: BackupError) -> JSONResponse:
        return JSONResponse(
            status_code=500, content={"detail": str(exc), "code": "backup_failed"}
        )

    # -- statistics ----------------------------------------------------------------------------
    @application.get(f"{prefix}/statistics")
    def statistics(
        limit: Annotated[int, Query(ge=1, le=1000)] = 200,
    ) -> dict[str, Any]:
        # ``list_jobs`` orders by queue priority and *oldest first*; take every
        # completed job, then keep the ``limit`` most recently finished.
        jobs = db.list_jobs(states=[JobState.COMPLETED], limit=5000)
        jobs.sort(key=lambda item: item.finished_at or item.updated_at, reverse=True)
        jobs = jobs[:limit]
        return completed_statistics(
            jobs,
            lambda job_id: db.list_events(job_id=job_id, limit=5000),
            lambda job_id: db.list_artifacts(job_id=job_id, limit=1000),
            job_root,
        )

    @application.get(f"{prefix}/jobs/{{job_id}}/statistics")
    def job_statistics(job_id: str) -> dict[str, Any]:
        job = db.get_job(job_id)
        return compute_job_statistics(
            job,
            db.list_events(job_id=job_id, limit=5000),
            db.list_artifacts(job_id=job_id, limit=1000),
            job_root(job_id),
        )

    # -- profile library ----------------------------------------------------------------------------
    @application.get(f"{prefix}/profile-library")
    def list_profiles() -> dict[str, Any]:
        items = library().list()
        return {
            "items": [
                {**item.to_dict(), "selection": item.selection_fragment()} for item in items
            ],
            "count": len(items),
        }

    @application.get(f"{prefix}/profile-library/export")
    def export_library() -> JSONResponse:
        return JSONResponse(
            library().export_bundle(),
            headers={
                "Content-Disposition": 'attachment; filename="bdencode-profiles.json"',
                "X-Content-Type-Options": "nosniff",
            },
        )

    @application.post(f"{prefix}/profile-library/import")
    def import_profiles(
        document: Annotated[dict[str, Any], Body()],
        on_conflict: Literal["rename", "skip", "overwrite"] = "rename",
    ) -> dict[str, Any]:
        return library().import_document(document, on_conflict=on_conflict)

    @application.post(f"{prefix}/profile-library", status_code=status.HTTP_201_CREATED)
    def save_profile(
        document: Annotated[dict[str, Any], Body()], overwrite: bool = False
    ) -> dict[str, Any]:
        saved = library().save(document, overwrite=overwrite)
        return {**saved.to_dict(), "selection": saved.selection_fragment()}

    @application.get(f"{prefix}/profile-library/{{profile_id}}")
    def get_profile(profile_id: str) -> dict[str, Any]:
        item = library().get(profile_id)
        return {**item.to_dict(), "selection": item.selection_fragment()}

    @application.get(f"{prefix}/profile-library/{{profile_id}}/export")
    def export_profile(profile_id: str) -> JSONResponse:
        document = library().export(profile_id)
        return JSONResponse(
            document,
            headers={
                "Content-Disposition": (
                    f'attachment; filename="{profile_id}.bdencode-profile.json"'
                ),
                "X-Content-Type-Options": "nosniff",
            },
        )

    @application.delete(
        f"{prefix}/profile-library/{{profile_id}}",
        status_code=status.HTTP_204_NO_CONTENT,
        response_class=Response,
    )
    def delete_profile(profile_id: str) -> Response:
        library().delete(profile_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    # -- built-in player -------------------------------------------------------------------------------
    def output_file(job_id: str) -> Path:
        job = db.get_job(job_id)
        artifact = next(
            (
                item
                for item in db.list_artifacts(job_id=job_id, limit=1000)
                if item.kind is ArtifactKind.OUTPUT
            ),
            None,
        )
        if artifact is None:
            raise StateConflictError(
                "the job has no finished MKV yet", current=job.state
            )
        path = Path(artifact.path)
        try:
            resolved = path.resolve(strict=True)
        except OSError as exc:
            raise NotFoundError("the finished MKV is missing") from exc
        if settings is not None and not (
            resolved.is_relative_to(settings.completed_root)
            or resolved.is_relative_to(settings.jobs_root)
        ):
            raise ConfigurationError("output path is outside the completed/job roots")
        return resolved

    @application.get(f"{prefix}/jobs/{{job_id}}/player")
    def player_info(job_id: str) -> dict[str, Any]:
        source = output_file(job_id)
        service = preview_service()
        return {
            **service.media_info(source),
            "previews": service.list(job_id),
            "limits": {
                "min_duration_seconds": 5,
                "max_duration_seconds": 30,
                "heights": [360, 480, 720],
            },
        }

    @application.get(f"{prefix}/jobs/{{job_id}}/previews")
    def list_previews(job_id: str) -> dict[str, Any]:
        db.get_job(job_id)
        return {"items": preview_service().list(job_id)}

    @application.post(
        f"{prefix}/jobs/{{job_id}}/previews", status_code=status.HTTP_201_CREATED
    )
    def create_preview(
        job_id: str, body: PreviewBody, response: Response
    ) -> dict[str, Any]:
        source = output_file(job_id)
        record, created = preview_service().ensure(
            job_id,
            source,
            PreviewRequest(body.start_seconds, body.duration_seconds, body.height),
        )
        if not created:
            response.status_code = status.HTTP_200_OK
        return {**record, "created": created}

    @application.get(
        f"{prefix}/jobs/{{job_id}}/previews/{{name}}", response_class=FileResponse
    )
    def preview_content(job_id: str, name: str) -> FileResponse:
        db.get_job(job_id)
        path = preview_service().path_for(job_id, name)
        return FileResponse(
            path,
            media_type="video/mp4",
            content_disposition_type="inline",
            headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=3600"},
        )

    @application.delete(
        f"{prefix}/jobs/{{job_id}}/previews/{{name}}",
        status_code=status.HTTP_204_NO_CONTENT,
        response_class=Response,
    )
    def delete_preview(job_id: str, name: str) -> Response:
        db.get_job(job_id)
        preview_service().delete(job_id, name)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    # -- external sources -------------------------------------------------------------------------------------
    @application.get(f"{prefix}/external-sources/probe")
    def probe_external_source(path: str) -> dict[str, Any]:
        if settings is None:
            raise ConfigurationError("source browsing is not configured")
        resolved = settings.authorize_source(path)
        try:
            info = external_source.probe_source(resolved)
        except (external_source.ExternalSourceError, OSError, ValueError) as exc:
            raise ConfigurationError(f"external source cannot be read: {exc}") from exc
        return {**info.to_dict(), "support": external_source.external_support()}

    def external_directory(job_id: str, source_id: str) -> Path:
        if settings is None:
            raise ConfigurationError("job storage is not configured")
        if not external_spec.valid_id(source_id):
            raise NotFoundError("no such external source")
        return settings.job_root(job_id) / "work" / "external" / source_id

    def external_selection(job_id: str, source_id: str) -> tuple[Any, dict[str, Any], dict[str, Any]]:
        job = db.get_job(job_id)
        if job.state is not JobState.NEEDS_REVIEW:
            raise StateConflictError(
                "an external source is reviewed only while the job awaits review",
                current=job.state,
            )
        selection = json.loads(json.dumps(job.selection))
        sources = selection.get("external_sources") if isinstance(selection, dict) else None
        entry = next(
            (item for item in sources or [] if isinstance(item, dict) and item.get("id") == source_id),
            None,
        )
        if entry is None:
            raise NotFoundError("no such external source")
        return job, selection, entry

    def read_review(job_id: str, source_id: str) -> dict[str, Any]:
        path = external_directory(job_id, source_id) / "review.json"
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise NotFoundError("the external source has not been fitted yet") from exc

    @application.get(f"{prefix}/jobs/{{job_id}}/external-review")
    def external_review(job_id: str) -> dict[str, Any]:
        job = db.get_job(job_id)
        selection = job.selection if isinstance(job.selection, dict) else {}
        items = []
        for entry in selection.get("external_sources") or []:
            if not isinstance(entry, dict):
                continue
            try:
                review = read_review(job_id, str(entry.get("id")))
            except NotFoundError:
                continue
            items.append({"selection": entry, "review": review})
        return {"items": items}

    @application.post(f"{prefix}/jobs/{{job_id}}/external-review/{{source_id}}/approve")
    def approve_external_source(job_id: str, source_id: str, body: ExternalApprovalBody) -> Any:
        job, selection, entry = external_selection(job_id, source_id)
        if read_review(job_id, source_id).get("map_sha256") != body.map_sha256:
            raise StateConflictError(
                "the fit changed since it was shown; check it again", current=job.state
            )
        entry["approved_map_sha256"] = body.map_sha256
        return db.set_selection(
            job_id, selection, message="external source fit approved by operator", expected_version=job.version
        )

    @application.post(f"{prefix}/jobs/{{job_id}}/external-review/{{source_id}}/pitch")
    def set_external_pitch(job_id: str, source_id: str, body: ExternalPitchBody) -> Any:
        job, selection, entry = external_selection(job_id, source_id)
        track = next(
            (item for item in entry.get("tracks") or [] if item.get("stream") == body.stream), None
        )
        if track is None:
            raise NotFoundError("no such external track")
        track["pitch"] = body.pitch
        entry["approved_map_sha256"] = None
        return db.set_selection(
            job_id, selection, message="external track pitch changed by operator", expected_version=job.version
        )

    @application.post(f"{prefix}/jobs/{{job_id}}/external-review/{{source_id}}/discard")
    def discard_external_source(job_id: str, source_id: str) -> Any:
        job, selection, _entry = external_selection(job_id, source_id)
        remaining = [
            item for item in selection["external_sources"] if item.get("id") != source_id
        ]
        if remaining:
            selection["external_sources"] = remaining
        else:
            del selection["external_sources"]
        return db.set_selection(
            job_id, selection, message="external source left out by operator", expected_version=job.version
        )

    @application.post(
        f"{prefix}/jobs/{{job_id}}/external-review/{{source_id}}/excerpts",
        status_code=status.HTTP_201_CREATED,
    )
    def create_external_excerpt(
        job_id: str, source_id: str, body: ExternalExcerptBody, response: Response
    ) -> dict[str, Any]:
        db.get_job(job_id)
        directory = external_directory(job_id, source_id)
        review = read_review(job_id, source_id)
        tracks = review.get("tracks") or []
        subtitles = review.get("subtitles") or []
        if not tracks:
            raise NotFoundError("the external source holds no fitted track")
        if body.track >= len(tracks) or (body.subtitle is not None and body.subtitle >= len(subtitles)):
            raise NotFoundError("no such external track")
        report = tracks[body.track]
        record, created = preview_service().ensure_fit(
            job_id,
            settings.job_root(job_id) / "work" / "reference.mkv",
            directory / report["file"],
            PreviewRequest(body.start_seconds, body.duration_seconds, body.height),
            audio=body.audio,
            video_start_seconds=external_video_start(job_id),
            fitted_shift_seconds=float(report.get("sync_ms") or 0) / 1000,
            subtitle=(
                directory / subtitles[body.subtitle]["file"] if body.subtitle is not None else None
            ),
        )
        if not created:
            response.status_code = status.HTTP_200_OK
        return {**record, "created": created}

    def external_video_start(job_id: str) -> float:
        import subprocess

        completed = subprocess.run(
            external_source.first_time_command(
                ["-i", str(settings.job_root(job_id) / "work" / "reference.mkv")], "v:0"
            ),
            capture_output=True, text=True, timeout=60, check=False,
        )
        return external_source.parse_first_time(completed.stdout) or 0.0

    # -- database status and backups ---------------------------------------------------------------------------
    @application.get(f"{prefix}/system/database")
    def database_status() -> dict[str, Any]:
        path = Path(db.path).expanduser()
        listing = list_backups(backup_directory())
        return {
            "path": db.display_path,
            "schema_version": db.schema_version(),
            "size_bytes": path.stat().st_size if path.is_file() else None,
            "integrity": db.integrity_check(),
            "migrations": db.migration_history(),
            "backup_count": len(listing),
            "latest_backup": listing[0].to_dict() if listing else None,
        }

    @application.get(f"{prefix}/system/backups")
    def backups() -> dict[str, Any]:
        directory = backup_directory()
        return {
            "directory": str(directory),
            "items": [item.to_dict() for item in list_backups(directory)],
        }

    @application.get(f"{prefix}/system/release-update")
    def release_update_status() -> dict[str, Any]:
        """The daily release check's last outcome (written by bdencode-release-update)."""

        path = Path(os.environ.get("BDENCODE_RELEASE_STATUS_PATH") or RELEASE_UPDATE_STATUS_PATH)
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"available": False, "status": None}
        if not isinstance(document, dict):
            return {"available": False, "status": None}
        keys = (
            "state", "message", "checked_at", "last_successful_check_at", "installed_version",
            "latest_version", "latest_tag", "installed_at", "installed_commit", "media_updates",
        )
        return {"available": True, "status": {key: document.get(key) for key in keys if key in document}}

    # -- CPU policy ---------------------------------------------------------------------------------------------
    def cpu_settings() -> Settings:
        if settings is None:
            raise ConfigurationError("the CPU policy needs the service configuration")
        return settings

    @application.get(f"{prefix}/system/cpu-policy")
    def cpu_policy() -> dict[str, Any]:
        """The worker's day share and night window, and what is in force now."""

        return policy_view(cpu_settings())

    @application.put(f"{prefix}/system/cpu-policy")
    def update_cpu_policy(policy: CpuPolicy) -> dict[str, Any]:
        """Save the policy; the root helper applies it within seconds."""

        current = cpu_settings()
        save_policy(current, policy)
        return policy_view(current)

    @application.post(f"{prefix}/system/backups", status_code=status.HTTP_201_CREATED)
    def create_backup_now() -> dict[str, Any]:
        try:
            info = db.backup("manual", backup_directory())
        except PersistenceError as exc:
            raise ConfigurationError(str(exc)) from exc
        return info.to_dict()
