"""Operator reviews the web UI resolves without hand-made API calls.

Two kinds are resolved here:

* a language review: retained tracks whose language neither the disc's
  declarations nor the audio language detection could settle.  The operator
  confirms a language for the retained audio and subtitle tracks; the stored
  selection receives them and the job returns to the encode queue.  Tracks the
  detection already resolved are confirmed in the same step, so the next run
  does not have to detect them again.
* an image upload problem (``UPLOAD_FAILED`` or an upload review): the upload
  checkpoint is reset, optionally with another image host or image set, or the
  job finishes without uploading images.  That choice lives in a stage file
  and not in the selection, because the preparation reports (crop policy,
  automatic CRF) are pinned to the selection's hash.
"""

from __future__ import annotations

import copy
import json
import time
from pathlib import Path
from typing import Any, Mapping

from .media.language import iso639_2_to_bcp47, normalize_iso639_2, supported_iso639_2
from .models import Job, JobState
from .qc.catbox import CatboxClient
from .qc.freeimage import FreeimageClient
from .qc.imgbb import ImgBBClient
from .qc.image_upload import IMAGE_UPLOAD_PROVIDERS
from .utils import atomic_write_json

LANGUAGE_REVIEW_MESSAGE = (
    "one or more retained tracks need a confirmed language before encoding"
)
UPLOAD_REVIEW_CODES = frozenset({"image_upload_rejected", "image_too_large_for_host"})
# Reviews raised by the upload stage that a fresh checkpoint resolves.
_UPLOAD_REVIEW_PREFIXES = (
    "the image host rejected the upload",
    "comparison image ",
    "upload checkpoint",
    "selected image provider conflicts with upload checkpoint",
    "skipped upload checkpoint conflicts",
)
UPLOAD_IMAGE_SETS = ("all", "sdr", "native")
UPLOAD_OVERRIDE_NAME = "upload-override.json"
# The job's stage checkpoint directory (``JobPaths.stages``).
STAGES_DIR = ".stages"
UPLOAD_HOST_LIMITS: dict[str, int] = {
    client.provider_name: client.max_upload_bytes
    for client in (ImgBBClient, CatboxClient, FreeimageClient)
}
# A detection this sure becomes the suggested language over the disc's tag.
_DETECTION_SUGGESTION_CONFIDENCE = 0.6
_LANGUAGE_KINDS = ("audio", "subtitle")


class ReviewError(ValueError):
    """The request cannot resolve this review."""


# -- classification ---------------------------------------------------------
def review_kind(job: Job, details: Mapping[str, Any]) -> str | None:
    """What the operator has to decide, for the page to offer the right form."""

    if job.state is JobState.UPLOAD_FAILED:
        return "upload_failed"
    if job.state is not JobState.NEEDS_REVIEW:
        return None
    message = job.status_message or ""
    if message == LANGUAGE_REVIEW_MESSAGE:
        return "language"
    if job.resume_state is JobState.UPLOADING and (
        details.get("code") in UPLOAD_REVIEW_CODES
        or message.startswith(_UPLOAD_REVIEW_PREFIXES)
    ):
        return "upload"
    if message.startswith("fast comparison exceeded"):
        return "comparison_timeout"
    return "other"


# -- language review --------------------------------------------------------
def _playlist(scan_result: Mapping[str, Any] | None, playlist_id: Any) -> Mapping[str, Any] | None:
    if not isinstance(scan_result, Mapping) or playlist_id is None:
        return None
    wanted = str(playlist_id).lower().removesuffix(".mpls").zfill(5)
    for playlist in scan_result.get("playlists") or ():
        if isinstance(playlist, Mapping) and str(playlist.get("playlist_id", "")).zfill(5) == wanted:
            return playlist
    return None


def _detection(evidence: Mapping[str, Any] | None) -> tuple[str | None, float | None]:
    if not isinstance(evidence, Mapping):
        return None, None
    inference = evidence.get("inference")
    consensus = inference.get("consensus") if isinstance(inference, Mapping) else None
    if not isinstance(consensus, Mapping):
        return None, None
    code = normalize_iso639_2(consensus.get("iso639_2t"))
    confidence = consensus.get("confidence")
    return code, float(confidence) if isinstance(confidence, (int, float)) else None


def language_review(
    selection: Mapping[str, Any] | None,
    scan_result: Mapping[str, Any] | None,
    report: Mapping[str, Any] | None,
    details: Mapping[str, Any],
) -> dict[str, Any]:
    """The retained audio and subtitle tracks with every language clue."""

    selection = selection if isinstance(selection, Mapping) else {}
    playlist = _playlist(scan_result, selection.get("playlist_id"))
    streams = {
        str(stream.get("id")): stream
        for stream in (playlist or {}).get("streams") or ()
        if isinstance(stream, Mapping)
    }
    report = report if isinstance(report, Mapping) else {}
    unresolved: dict[str, Mapping[str, Any]] = {}
    for source in (report.get("unresolved"), details.get("tracks")):
        for item in source or ():
            if isinstance(item, Mapping) and item.get("stream_id"):
                unresolved.setdefault(str(item["stream_id"]), item)
    evidence = {
        str(item.get("stream_id")): item
        for item in report.get("evidence") or ()
        if isinstance(item, Mapping)
    }
    resolved = report.get("resolved_languages")
    resolved = resolved if isinstance(resolved, Mapping) else {}

    tracks: list[dict[str, Any]] = []
    for track in selection.get("tracks") or ():
        if not isinstance(track, Mapping) or str(track.get("action", "")).lower() == "omit":
            continue
        stream_id = str(track.get("stream_id"))
        stream = streams.get(stream_id, {})
        kind = stream.get("kind") or stream_id.split(":", 1)[0]
        if kind not in _LANGUAGE_KINDS:
            continue
        declared_raw = stream.get("language")
        declared = normalize_iso639_2(
            declared_raw.get("iso639_2t") if isinstance(declared_raw, Mapping) else None
        )
        detected, confidence = _detection(evidence.get(stream_id))
        current = normalize_iso639_2(track.get("language"))
        automatic = normalize_iso639_2(resolved.get(stream_id))
        confident_detection = (
            detected
            if detected and (confidence or 0.0) >= _DETECTION_SUGGESTION_CONFIDENCE
            else None
        )
        review = unresolved.get(stream_id)
        tracks.append(
            {
                "stream_id": stream_id,
                "kind": kind,
                "codec": stream.get("codec"),
                "channels": stream.get("channels"),
                "title": stream.get("title"),
                "declared": declared,
                "detected": detected,
                "detected_confidence": confidence,
                "resolved": automatic,
                "current": current,
                "needs_confirmation": review is not None,
                "reason": review.get("reason") if review is not None else None,
                "suggested": current or automatic or confident_detection or declared,
            }
        )
    return {"tracks": tracks, "languages": language_options()}


def language_options() -> list[dict[str, str | None]]:
    """The ISO 639-2 codes a track may carry, with their BCP 47 form."""

    return [
        {"code": code, "bcp47": iso639_2_to_bcp47(code)} for code in supported_iso639_2()
    ]


def apply_track_languages(
    selection: Mapping[str, Any], languages: Mapping[str, str]
) -> dict[str, Any]:
    """A copy of ``selection`` whose retained tracks carry the given languages."""

    revised = copy.deepcopy(dict(selection))
    tracks = revised.get("tracks")
    if not isinstance(tracks, list):
        raise ReviewError("the stored selection has no track list")
    by_id = {
        str(track.get("stream_id")): track for track in tracks if isinstance(track, dict)
    }
    for stream_id, value in languages.items():
        code = normalize_iso639_2(value) if isinstance(value, str) else None
        if code is None:
            raise ReviewError(f"{stream_id}: unknown ISO 639-2 language code {value!r}")
        track = by_id.get(stream_id)
        if track is None or str(track.get("action", "")).lower() == "omit":
            raise ReviewError(f"{stream_id} is not a retained track of the selection")
        track["language"] = code
    return revised


# -- image upload -----------------------------------------------------------
def read_upload_override(stages: Path) -> dict[str, Any]:
    """The operator's upload choice made after the selection (may be empty)."""

    try:
        document = json.loads((stages / UPLOAD_OVERRIDE_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(document, dict) or document.get("schema_version") != 1:
        return {}
    override: dict[str, Any] = {}
    provider = document.get("provider")
    if provider == "auto" or provider in IMAGE_UPLOAD_PROVIDERS:
        override["image_upload_provider"] = provider
    if document.get("image_set") in UPLOAD_IMAGE_SETS:
        override["upload_image_set"] = document["image_set"]
    if isinstance(document.get("upload_images"), bool):
        override["upload_images"] = document["upload_images"]
    return override


def upload_overview(job_root: Path) -> dict[str, Any]:
    """Where the upload stands: the locked host, images done, the largest image."""

    checkpoint = job_root / "comparison" / "uploads.json"
    provider: str | None = None
    uploaded = 0
    try:
        document = json.loads(checkpoint.read_text(encoding="utf-8"))
        if isinstance(document, Mapping):
            raw_provider = document.get("provider")
            provider = raw_provider if isinstance(raw_provider, str) else None
            images = document.get("images")
            uploaded = len(images) if isinstance(images, Mapping) else 0
    except (OSError, ValueError):
        pass
    largest = 0
    for folder in (job_root / "comparison", job_root / "analysis"):
        try:
            for png in folder.glob("*.png"):
                largest = max(largest, png.stat().st_size)
        except OSError:
            continue
    override = read_upload_override(job_root / STAGES_DIR)
    return {
        "provider": provider,
        "uploaded_images": uploaded,
        "largest_image_bytes": largest or None,
        "override": {
            "provider": override.get("image_upload_provider"),
            "image_set": override.get("upload_image_set"),
            "upload_images": override.get("upload_images"),
        },
        "hosts": [
            {"provider": name, "max_upload_bytes": limit}
            for name, limit in UPLOAD_HOST_LIMITS.items()
        ],
    }


def reset_upload(
    job_root: Path,
    *,
    provider: str | None,
    image_set: str | None,
    upload_images: bool,
    clock: Any = time.time,
) -> dict[str, Any]:
    """Set the upload choice aside the selection and start the upload over.

    The old checkpoint moves to the job's private ``logs/upload-resets``: the
    images stay on their old host and the job no longer refers to them.
    """

    if provider is not None and provider != "auto" and provider not in IMAGE_UPLOAD_PROVIDERS:
        raise ReviewError(f"unknown image host: {provider!r}")
    if image_set is not None and image_set not in UPLOAD_IMAGE_SETS:
        raise ReviewError(f"image_set must be one of {', '.join(UPLOAD_IMAGE_SETS)}")
    before = upload_overview(job_root)
    stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime(clock()))
    checkpoint = job_root / "comparison" / "uploads.json"
    backup: Path | None = None
    if checkpoint.is_file():
        backups = job_root / "logs" / "upload-resets"
        backups.mkdir(mode=0o750, parents=True, exist_ok=True)
        backup = backups / f"uploads-{stamp}.json"
        number = 1
        while backup.exists():
            number += 1
            backup = backups / f"uploads-{stamp}-{number}.json"
        checkpoint.replace(backup)
    stages = job_root / STAGES_DIR
    stages.mkdir(mode=0o750, parents=True, exist_ok=True)
    (stages / "upload.json").unlink(missing_ok=True)
    document: dict[str, Any] = {"schema_version": 1, "upload_images": upload_images}
    if provider is not None:
        document["provider"] = provider
    if image_set is not None:
        document["image_set"] = image_set
    atomic_write_json(stages / UPLOAD_OVERRIDE_NAME, document)
    return {
        "previous_provider": before["provider"],
        "previous_uploaded_images": before["uploaded_images"],
        "backup": None if backup is None else backup.name,
        "provider": provider,
        "image_set": image_set,
        "upload_images": upload_images,
    }
