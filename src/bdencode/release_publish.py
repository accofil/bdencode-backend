"""From a built release kit to a seeded upload: torrent, duplicate check, upload, seed.

Every step is started by the operator; the upload itself needs them to confirm
the exact release, and the same request is never sent twice by itself.  An
unclear answer ends in UNKNOWN, where only a new look at the tracker can continue.

The long steps run in a background thread of the API and report through the
preparation's state.  A restart ends them; the store's startup recovery resolves
the state, and no step resumes by itself.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import shutil
import threading
from typing import Any, Callable, Mapping

from pydantic import BaseModel, ConfigDict, Field

from .config import ConfigurationError
from .db import StateConflictError
from .qbittorrent import CATEGORY, QbittorrentClient, QbittorrentError
from .release.models import ReleasePreparationState
from .release_service import ReleaseServiceError
from .release_store import ReleasePreparation
from .secrets import SecretUnavailable, read_secret
from .torrent_file import TorrentError, build_torrent, file_names, info_hash, same_content
from .tracker_settings import QBITTORRENT_PASSWORD, load_settings, settings_path
from .trackers import SessionExpired, TrackerError, TrackerMatch, UploadResult, aither, ncore

LOG = logging.getLogger(__name__)
TRACKERS = ("aither", "ncore")
TORRENTS_DIRECTORY = ".torrents"
MIN_ACKNOWLEDGEMENT_CHARS = 12
PICTURE_TIMEOUT = 180
STREAM_PROBE_TIMEOUT = 300
_RELEASE_TAG = re.compile(r"-([A-Za-z0-9][A-Za-z0-9_.]*)$")
_IMDB_ID = re.compile(r"tt\d{7,10}")


class ReleasePublishError(ReleaseServiceError):
    """Safe to show: never a credential or a private link."""


class UploadApproval(BaseModel):
    """What the operator saw and approved; the rest of the request is tracker specific."""

    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    confirm_release_name: str = Field(min_length=1, max_length=240)
    torrent_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class AitherUploadRequest(UploadApproval):
    name: str = Field(min_length=6, max_length=255)
    description: str = Field(min_length=1, max_length=1_000_000)
    anonymous: bool = False
    personal_release: bool = True
    mod_queue: bool = False


class NcoreUploadRequest(UploadApproval):
    name: str = Field(min_length=6, max_length=255)
    description: str = Field(min_length=1, max_length=100_000)
    title_hu: str = Field(default="", max_length=300)
    title_en: str = Field(default="", max_length=300)
    title_other: str = Field(default="", max_length=300)
    country: str = Field(default="", max_length=300)
    runtime: str = Field(default="", max_length=32)
    directors: str = Field(default="", max_length=2000)
    cast: str = Field(default="", max_length=4000)
    subtitles: str = Field(default="nincs", max_length=2000)
    audio: str = Field(default="nincs", max_length=2000)
    extras: str = Field(default="nincs", max_length=2000)
    menu: bool = False


@dataclass(frozen=True)
class _Stage:
    """The torrent's content where qBittorrent will find it."""

    root: Path
    content: Path


def dynamic_range_of(release_name: str) -> tuple[str, ...]:
    tokens = set(release_name.split("."))
    return tuple(token for token in ("DV", "HDR10+", "HDR", "HLG") if token in tokens)


def _film_name(title: str, release_name: str, *, remux: bool) -> str:
    """nCore's name of an own film: ``Tomb Raider 2160p UHD BluRay REMUX DV HDR``."""

    tokens = release_name.split(".")
    resolution = next((token for token in tokens if re.fullmatch(r"\d{3,4}[pi]", token)), "")
    parts = [re.sub(r"\s*:\s*", " - ", title).strip(), resolution]
    if resolution == "2160p" and remux:
        parts.append("UHD BluRay")
    if remux:
        parts.append("REMUX")
    if "DV" in tokens:
        parts.append("DV")
    if "HDR10+" in tokens:
        parts.append("HDR10+")
    elif "HDR" in tokens:
        parts.append("HDR")
    return " ".join(part for part in parts if part)


class ReleasePublisher:
    def __init__(
        self,
        service: Any,
        *,
        aither_factory: Callable[[str], aither.AitherClient] = aither.AitherClient,
        ncore_factory: Callable[[str], ncore.NcoreClient] = ncore.NcoreClient,
        qbittorrent_factory: Callable[..., QbittorrentClient] = QbittorrentClient,
        secret: Callable[[str], str] = read_secret,
        background: Callable[[Callable[[], None]], None] | None = None,
    ) -> None:
        self.service = service
        self._aither_factory = aither_factory
        self._ncore_factory = ncore_factory
        self._qbittorrent_factory = qbittorrent_factory
        self._secret = secret
        self._background = background or self._start_thread

    @staticmethod
    def _start_thread(work: Callable[[], None]) -> None:
        threading.Thread(target=work, name="release-publish", daemon=True).start()

    @property
    def _store(self) -> Any:
        return self.service.store

    @property
    def _root(self) -> Path:
        return self.service.settings.seeding_root

    def _stage_root(self, record: ReleasePreparation) -> Path:
        return self._root / record.id

    def _torrent_path(self, record: ReleasePreparation, *, site: bool = False) -> Path:
        return self._root / TORRENTS_DIRECTORY / f"{record.id}{'.site' if site else ''}.torrent"

    def _is_remux(self, record: ReleasePreparation) -> bool:
        job = self.service.database.get_job(record.job_id)
        return isinstance(job.selection, Mapping) and job.selection.get("mode") == "remux"

    def _record(self, preparation_id: str, expected_version: int) -> ReleasePreparation:
        record = self._store.get(preparation_id)
        if record.version != expected_version:
            raise StateConflictError(
                f"release preparation version is {record.version}, expected {expected_version}"
            )
        if record.profile_id not in TRACKERS:
            raise ConfigurationError("uploads exist only for the Aither and nCore profiles")
        return record

    def _login(self, credential: str, label: str) -> str:
        try:
            value = self._secret(credential)
        except SecretUnavailable:
            raise ReleasePublishError(f"{label}: the login is not set on the System page") from None
        if not value:
            raise ReleasePublishError(f"{label}: the login is not set on the System page")
        return value

    def _aither(self) -> aither.AitherClient:
        return self._aither_factory(self._login(aither.CREDENTIAL, "Aither"))

    def _ncore(self) -> ncore.NcoreClient:
        return self._ncore_factory(self._login(ncore.CREDENTIAL, "nCore"))

    def _qbittorrent(self) -> QbittorrentClient | None:
        settings = load_settings(settings_path(self.service.settings.state_root))
        if not settings.qbittorrent_url:
            return None
        try:
            password = self._secret(QBITTORRENT_PASSWORD)
        except SecretUnavailable:
            password = ""
        return self._qbittorrent_factory(
            settings.qbittorrent_url,
            username=settings.qbittorrent_username,
            password=password,
        )

    def check_connection(self, kind: str) -> str:
        """A read-only look: is the stored login good?"""

        try:
            if kind == "aither":
                client: Any = self._aither()
            elif kind == "ncore":
                client = self._ncore()
            elif kind == "qbittorrent":
                client = self._qbittorrent()
                if client is None:
                    raise ReleasePublishError("qBittorrent: no address is set")
            else:
                raise ReleasePublishError("unknown connection")
            try:
                return client.check_connection()
            finally:
                client.close()
        except (TrackerError, QbittorrentError) as exc:
            raise ReleasePublishError(str(exc)) from None

    # The torrent.

    def start_torrent(self, preparation_id: str, *, expected_version: int) -> ReleasePreparation:
        record = self._record(preparation_id, expected_version)
        if record.state is not ReleasePreparationState.READY or record.kit_path is None:
            raise StateConflictError("a torrent needs a READY release kit")
        if record.torrent_infohash is not None:
            raise StateConflictError("this release already has its torrent")
        building = self._store.transition(
            preparation_id,
            ReleasePreparationState.BUILDING_TORRENT,
            expected_version=expected_version,
            values={"error": None},
        )
        self._background(lambda: self._build_torrent(building))
        return building

    def _build_torrent(self, record: ReleasePreparation) -> None:
        try:
            stage = self._make_stage(record)
            source, announce = (
                (aither.SOURCE_TAG, aither.ANNOUNCE)
                if record.profile_id == "aither"
                else (ncore.SOURCE_TAG, ncore.ANNOUNCE)
            )
            built = build_torrent(stage.content, source=source, announce=announce)
            path = self._torrent_path(record)
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            self._write_private(path, built.data)
            values: dict[str, Any] = {
                "torrent_infohash": built.info_hash,
                "torrent_sha256": hashlib.sha256(built.data).hexdigest(),
                "error": None,
            }
        except Exception as exc:  # noqa: BLE001 - the state must leave BUILDING_TORRENT
            LOG.warning("torrent of %s failed: %s", record.id, type(exc).__name__)
            values = {"error": f"the torrent could not be made: {_safe_reason(exc)}"}
        self._store.transition(
            record.id,
            ReleasePreparationState.READY,
            expected_version=record.version,
            values=values,
        )

    @staticmethod
    def _write_private(path: Path, data: bytes) -> None:
        temporary = path.with_name(f".{path.name}.new")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)

    def _make_stage(self, record: ReleasePreparation) -> _Stage:
        """Hard links beside the release: no copy, and the completed folder's evidence stays out."""

        payload = self.service._bound_payload(record)
        root = self._stage_root(record)
        if root.exists():
            shutil.rmtree(root)
        root.mkdir(mode=0o750, parents=True)
        name = record.metadata.release_name
        if record.profile_id == "ncore" and record.payload_size > ncore.SAMPLE_OVER_BYTES:
            # Over 2 GiB nCore wants a sample in the torrent.
            folder = root / name
            folder.mkdir()
            os.link(payload, folder / payload.name)
            self._link_sample(record, payload, folder / "sample.mkv")
            return _Stage(root, folder)
        target = root / payload.name
        os.link(payload, target)
        return _Stage(root, target)

    def _link_sample(self, record: ReleasePreparation, payload: Path, target: Path) -> None:
        existing = payload.parent / "Sample" / f"{payload.stem}.sample.mkv"
        if existing.is_file() and not existing.is_symlink():
            os.link(existing, target)
            return
        # Lazily: the worker module is large and imports this package's relatives.
        from .worker import sample_window

        duration = self._duration(payload)
        window = sample_window(
            duration_seconds=duration,
            size_bytes=record.payload_size,
            uhd=record.metadata.resolution == "2160p",
        )
        if window is None:
            raise ReleasePublishError("the film is too short for nCore's sample")
        start, length = window
        scratch = target.parent.parent / ".sample"
        scratch.mkdir()
        self.service.runner.capture(
            [
                "mkvmerge",
                "--output",
                str(scratch / "sample.mkv"),
                "--split",
                f"parts:{_clock(start)}-{_clock(start + length)}",
                str(payload),
            ],
            timeout=1800,
            check=False,
        )
        produced = sorted(scratch.glob("*.mkv"))
        if len(produced) != 1 or produced[0].stat().st_size == 0:
            raise ReleasePublishError("the sample could not be cut")
        os.replace(produced[0], target)
        shutil.rmtree(scratch)
        if (
            record.metadata.resolution == "2160p"
            and target.stat().st_size < ncore.UHD_SAMPLE_MIN_BYTES
        ):
            raise ReleasePublishError("the UHD sample is below nCore's 200 MB")

    def _duration(self, payload: Path) -> float:
        completed = self.service.runner.capture(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(payload)],
            timeout=STREAM_PROBE_TIMEOUT,
            check=True,
        )
        try:
            return float(json.loads(completed.stdout)["format"]["duration"])
        except (KeyError, TypeError, ValueError):
            raise ReleasePublishError("the film's length cannot be read") from None

    def _streams(self, payload: Path) -> dict[str, list[dict[str, Any]]]:
        completed = self.service.runner.capture(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "stream=codec_type,channels:stream_tags=language,title:stream_disposition=forced",
                "-of",
                "json",
                str(payload),
            ],
            timeout=STREAM_PROBE_TIMEOUT,
            check=True,
        )
        try:
            streams = json.loads(completed.stdout).get("streams") or []
        except ValueError:
            raise ReleasePublishError("the film's tracks cannot be read") from None
        found: dict[str, list[dict[str, Any]]] = {"audio": [], "subtitle": []}
        for stream in streams:
            kind = stream.get("codec_type")
            if kind in found:
                tags = stream.get("tags") or {}
                found[kind].append(
                    {
                        "language": tags.get("language", ""),
                        "title": tags.get("title", ""),
                        "channels": stream.get("channels"),
                        "forced": bool((stream.get("disposition") or {}).get("forced")),
                    }
                )
        return found

    # The duplicate check.

    def dupe_check(self, preparation_id: str, *, expected_version: int) -> ReleasePreparation:
        record = self._record(preparation_id, expected_version)
        if record.state not in {
            ReleasePreparationState.READY,
            ReleasePreparationState.NEEDS_REVIEW,
            ReleasePreparationState.UNKNOWN,
        }:
            raise StateConflictError("a duplicate check needs a release that is not being uploaded")
        if record.torrent_infohash is None:
            raise StateConflictError("make the torrent before the duplicate check")
        # Looked up before any state change: an unreachable tracker changes nothing.
        try:
            matches, blocked = self._look_up(record)
        except (TrackerError, ReleasePublishError) as exc:
            raise ReleasePublishError(str(exc)) from None
        checking = self._store.transition(
            preparation_id,
            ReleasePreparationState.SEEDING_CHECK,
            expected_version=expected_version,
            values={"error": None},
        )
        outcome = "BLOCKED" if blocked else "DUPLICATE" if matches else "CLEAR"
        receipt = {
            "outcome": outcome,
            "tracker": record.profile_id,
            "checked_at": self.service._now().isoformat(),
            "blocked_reason": blocked,
            "matches": [_match_view(item) for item in matches],
        }
        return self._store.transition(
            preparation_id,
            ReleasePreparationState.READY_TO_PUBLISH
            if outcome == "CLEAR"
            else ReleasePreparationState.NEEDS_REVIEW,
            expected_version=checking.version,
            values={"dupe_receipt_json": receipt},
        )

    def _look_up(self, record: ReleasePreparation) -> tuple[tuple[TrackerMatch, ...], str | None]:
        """(what is on the tracker, why it may not go up at all)."""

        metadata = record.metadata
        name = metadata.release_name
        if record.profile_id == "aither":
            if metadata.tmdb_id is None:
                raise ReleasePublishError("Aither needs the film's TMDB id in the release plan")
            client = self._aither()
            try:
                tag = _RELEASE_TAG.search(name)
                if tag and tag.group(1).casefold() in client.banned_groups():
                    return (), f"Aither does not accept the group {tag.group(1)}"
                return (
                    client.search(
                        tmdb_id=metadata.tmdb_id,
                        category=metadata.category,
                        resolution=metadata.resolution,
                        release_name=name,
                    ),
                    None,
                )
            finally:
                client.close()
        if not metadata.imdb_id:
            raise ReleasePublishError("nCore needs the film's IMDb id in the release plan")
        client = self._ncore()
        try:
            token = client.upload_token()
            category = ncore.category_for(metadata.languages)
            notice = client.banned_notice(
                token,
                {
                    "tipus": category,
                    "torrent_nev": _film_name(metadata.title, name, remux=self._is_remux(record)),
                    "eredeti": "nem",
                },
            )
            return client.search(imdb_id=metadata.imdb_id, release_name=name), notice or None
        finally:
            client.close()

    def acknowledge_duplicates(
        self, preparation_id: str, *, expected_version: int, reason: str
    ) -> ReleasePreparation:
        """The operator judged the hits: this release may stand next to them."""

        record = self._record(preparation_id, expected_version)
        receipt = record.dupe_receipt or {}
        if record.state is not ReleasePreparationState.NEEDS_REVIEW or receipt.get("outcome") != "DUPLICATE":
            raise StateConflictError("there are no duplicate hits to judge")
        if any(item.get("exact") for item in receipt.get("matches") or []):
            raise StateConflictError("this exact release name is already on the tracker")
        if len(reason.strip()) < MIN_ACKNOWLEDGEMENT_CHARS:
            raise ReleasePublishError(
                f"give a reason of at least {MIN_ACKNOWLEDGEMENT_CHARS} characters"
            )
        return self._store.transition(
            preparation_id,
            ReleasePreparationState.READY_TO_PUBLISH,
            expected_version=expected_version,
            values={"dupe_receipt_json": {**receipt, "acknowledged_reason": reason.strip()}, "error": None},
        )

    # The plan the operator approves.

    def _release_bbcode(self, payload: Path, *, aither_format: bool) -> str:
        comparison = payload.parent / "comparison"
        parts: list[str] = []
        names = ("comparison.bbcode", "comparison-aither.bbcode") if aither_format else ("comparison.bbcode",)
        for name in names:
            path = comparison / name
            if path.is_file() and not path.is_symlink():
                text = path.read_text(encoding="utf-8").strip()
                if text:
                    parts.append(text)
        return "\n\n".join(parts)

    def upload_plan(self, preparation_id: str) -> dict[str, Any]:
        """Exactly what would go up, for the operator to read and correct."""

        record = self._store.get(preparation_id)
        if record.profile_id not in TRACKERS:
            raise ConfigurationError("uploads exist only for the Aither and nCore profiles")
        if record.torrent_infohash is None:
            raise StateConflictError("make the torrent first")
        payload = Path(record.payload_path)
        streams = self._streams(payload)
        torrent = self._torrent_path(record).read_bytes()
        base: dict[str, Any] = {
            "tracker": record.profile_id,
            "release_name": record.metadata.release_name,
            "torrent_sha256": record.torrent_sha256,
            "info_hash": record.torrent_infohash,
            "files": list(file_names(torrent)),
            "seeding": self._seeding_view(),
        }
        if record.profile_id == "aither":
            return {**base, **self._aither_plan(record, payload, streams)}
        return {**base, **self._ncore_plan(record, payload, streams)}

    def _seeding_view(self) -> dict[str, Any]:
        settings = load_settings(settings_path(self.service.settings.state_root))
        return {"automatic": bool(settings.qbittorrent_url), "category": CATEGORY}

    def _aither_plan(
        self, record: ReleasePreparation, payload: Path, streams: Mapping[str, list[dict[str, Any]]]
    ) -> dict[str, Any]:
        metadata = record.metadata
        mediainfo = self.service._release_text(record)[0]
        description = self._release_bbcode(payload, aither_format=True)
        languages = [str(item["language"]).casefold() for key in streams for item in streams[key]]
        problems: list[str] = []
        if metadata.tmdb_id is None:
            problems.append("Aither needs the film's TMDB id")
        if not re.search(r"(?im)^Unique ID\s*:", mediainfo):
            problems.append("the MediaInfo has no Unique ID, Aither refuses that")
        if "[img" not in description:
            problems.append("the description has no pictures: upload the screenshots first")
        if not any(language in {"en", "eng"} for language in languages):
            problems.append("Aither needs English audio or subtitles")
        if metadata.resolution not in aither.RESOLUTION_IDS:
            problems.append(f"Aither has no resolution {metadata.resolution}")
        return {
            "fields": {
                "name": aither.display_name(metadata.release_name),
                "description": description,
                "anonymous": False,
                "personal_release": True,
                "mod_queue": False,
            },
            "facts": {
                "type": "REMUX" if self._is_remux(record) else "ENCODE",
                "category": metadata.category,
                "resolution": metadata.resolution,
                "tmdb": metadata.tmdb_id,
                "imdb": aither.imdb_digits(metadata.imdb_id),
                "dynamic_range": list(dynamic_range_of(metadata.release_name)),
                "mediainfo_characters": len(mediainfo),
            },
            "problems": problems,
        }

    def _ncore_plan(
        self, record: ReleasePreparation, payload: Path, streams: Mapping[str, list[dict[str, Any]]]
    ) -> dict[str, Any]:
        metadata = record.metadata
        problems: list[str] = []
        if metadata.category.casefold() != "movie":
            problems.append("only films can go to nCore from here")
        movie: dict[str, str] = {}
        if not metadata.imdb_id or not _IMDB_ID.fullmatch(metadata.imdb_id):
            problems.append("nCore needs the film's IMDb id, like tt1234567")
        else:
            client = self._ncore()
            try:
                movie = client.imdb_movie(metadata.imdb_id)
            except SessionExpired as exc:
                raise ReleasePublishError(str(exc)) from None
            except TrackerError as exc:
                # The form can be filled in by hand.
                problems.append(f"the film's data could not be fetched: {exc}")
            finally:
                client.close()
        title_hu = movie.get("movie_magyar_cim", "")
        title_en = movie.get("movie_angol_cim", "") or metadata.title
        audio = streams["audio"]
        category = ncore.category_for([str(item["language"]) for item in audio] or metadata.languages)
        name_title = title_hu or title_en
        description = f"Forrás: {metadata.source_media}\n"
        problems.extend(ncore.description_problems(description))
        return {
            "fields": {
                "name": _film_name(name_title, metadata.release_name, remux=self._is_remux(record)),
                "description": description,
                "title_hu": title_hu,
                "title_en": title_en,
                "title_other": "",
                "country": movie.get("movie_orszag", ""),
                "runtime": movie.get("movie_hossz", ""),
                "directors": movie.get("movie_rendezo", ""),
                "cast": movie.get("movie_szereplok", ""),
                "subtitles": ncore.subtitle_line(streams["subtitle"]),
                "audio": ncore.audio_line(audio),
                "extras": "nincs",
                "menu": False,
            },
            "facts": {
                "category": category,
                "imdb": metadata.imdb_id,
                "year": metadata.year,
                "sample": record.payload_size > ncore.SAMPLE_OVER_BYTES,
            },
            "problems": problems,
        }

    # The upload.

    def _approve(self, preparation_id: str, request: UploadApproval) -> ReleasePreparation:
        record = self._record(preparation_id, request.expected_version)
        if record.state is not ReleasePreparationState.READY_TO_PUBLISH:
            raise StateConflictError("this release is not ready to upload")
        if request.confirm_release_name != record.metadata.release_name:
            raise StateConflictError("the confirmed name is not this release's name")
        if request.torrent_sha256 != record.torrent_sha256:
            raise StateConflictError("the torrent changed after it was shown")
        path = self._torrent_path(record)
        if hashlib.sha256(path.read_bytes()).hexdigest() != record.torrent_sha256:
            raise StateConflictError("the torrent file changed on disk")
        self._assert_stage(record, path.read_bytes())
        return record

    def _assert_stage(self, record: ReleasePreparation, torrent: bytes) -> None:
        """The stage still holds the very file the kit describes; no 80 GB hash for that."""

        root = self._stage_root(record)
        for name in file_names(torrent):
            if not (root / name).is_file():
                raise StateConflictError(f"the seeding folder lost {name}")
        stage_payload = next(
            (root / name for name in file_names(torrent) if name.endswith(record.payload_name)), None
        )
        if stage_payload is None or not os.path.samefile(stage_payload, record.payload_path):
            raise StateConflictError("the seeding folder no longer holds the completed MKV")

    def upload(
        self, preparation_id: str, request: AitherUploadRequest | NcoreUploadRequest
    ) -> ReleasePreparation:
        record = self._approve(preparation_id, request)
        if record.profile_id == "aither" and not isinstance(request, AitherUploadRequest):
            raise ConfigurationError("this request is not an Aither upload")
        if record.profile_id == "ncore" and not isinstance(request, NcoreUploadRequest):
            raise ConfigurationError("this request is not an nCore upload")
        # Everything that can be refused here is refused before anything is sent.
        prepared = (
            self._prepare_aither(record, request)
            if isinstance(request, AitherUploadRequest)
            else self._prepare_ncore(record, request)
        )
        publishing = self._store.transition(
            preparation_id,
            ReleasePreparationState.PUBLISHING,
            expected_version=request.expected_version,
            values={"error": None},
        )
        self._background(lambda: self._publish(publishing, prepared))
        return publishing

    def _prepare_aither(
        self, record: ReleasePreparation, request: AitherUploadRequest
    ) -> Callable[[], tuple[UploadResult, bytes | None]]:
        metadata = record.metadata
        mediainfo = self.service._release_text(record)[0]
        if metadata.tmdb_id is None:
            raise ReleasePublishError("Aither needs the film's TMDB id")
        if "[img" not in request.description:
            raise ReleasePublishError("the description has no pictures")
        fields = aither.upload_fields(
            name=request.name,
            description=request.description,
            mediainfo=mediainfo,
            category=metadata.category,
            remux=self._is_remux(record),
            resolution=metadata.resolution,
            tmdb_id=metadata.tmdb_id,
            imdb_id=metadata.imdb_id,
            dynamic_range=dynamic_range_of(metadata.release_name),
            anonymous=request.anonymous,
            personal_release=request.personal_release,
            mod_queue=request.mod_queue,
        )
        client = self._aither()
        torrent = self._torrent_path(record).read_bytes()

        def send() -> tuple[UploadResult, bytes | None]:
            try:
                wanted = client.search(
                    tmdb_id=metadata.tmdb_id or 0,
                    category=metadata.category,
                    resolution=metadata.resolution,
                    release_name=metadata.release_name,
                )
                if any(item.exact for item in wanted):
                    return UploadResult(rejected=True, errors=("this exact name appeared on Aither meanwhile",)), None
                result, link = client.upload(fields, torrent)
                site: bytes | None = None
                if result.accepted and link:
                    site = _try_download(lambda: client.download_torrent(link))
                return result, site
            finally:
                client.close()

        return send

    def _prepare_ncore(
        self, record: ReleasePreparation, request: NcoreUploadRequest
    ) -> Callable[[], tuple[UploadResult, bytes | None]]:
        metadata = record.metadata
        if metadata.category.casefold() != "movie":
            raise ReleasePublishError("only films can go to nCore from here")
        payload = Path(record.payload_path)
        root = self._stage_root(record)
        torrent = self._torrent_path(record).read_bytes()
        names = file_names(torrent)
        techinfo = self._techinfo(root, names)
        pictures = self._pictures(record, payload, root)
        streams = self._streams(payload)
        category = ncore.category_for([str(item["language"]) for item in streams["audio"]] or metadata.languages)
        film = ncore.FilmForm(
            name=request.name,
            category=category,
            description=request.description,
            imdb_id=metadata.imdb_id or "",
            year=str(metadata.year),
            title_hu=request.title_hu,
            title_en=request.title_en,
            title_other=request.title_other,
            country=request.country,
            runtime=request.runtime,
            directors=request.directors,
            cast=request.cast,
            subtitles=request.subtitles,
            audio=request.audio,
            extras=request.extras,
            menu=request.menu,
        )
        files: dict[str, tuple[str, bytes, str]] = {
            "torrent_fajl": (f"{metadata.release_name}.torrent", torrent, "application/x-bittorrent"),
            "techinfo_fajl": ("techinfo.txt", techinfo.encode("utf-8"), "text/plain"),
        }
        for number, picture in enumerate(pictures, start=1):
            kind = "image/png" if picture.suffix.casefold() == ".png" else "image/jpeg"
            files[f"kep{number}"] = (picture.name, picture.read_bytes(), kind)
        problems = ncore.form_problems(ncore.form_fields("0" * 16, film), files)
        if problems:
            raise ReleasePublishError("; ".join(problems))
        client = self._ncore()

        def send() -> tuple[UploadResult, bytes | None]:
            try:
                token = client.upload_token()
                fields = ncore.form_fields(token, film)
                notice = client.banned_notice(token, fields)
                if notice:
                    return UploadResult(rejected=True, errors=(f"nCore's ban list: {notice}",)), None
                wanted = client.search(imdb_id=None, release_name=metadata.release_name)
                if any(item.exact for item in wanted):
                    return UploadResult(rejected=True, errors=("this exact name appeared on nCore meanwhile",)), None
                result = client.upload(fields, files)
                site: bytes | None = None
                if result.accepted and result.torrent_id:
                    identifier = result.torrent_id
                    site = _try_download(lambda: client.download_torrent(identifier))
                return result, site
            finally:
                client.close()

        return send

    def _techinfo(self, root: Path, names: tuple[str, ...]) -> str:
        """MediaInfo of every file of the torrent, with relative names only."""

        reports: list[str] = []
        for name in names:
            completed = self.service.runner.capture(
                ["mediainfo", str(root / name)], timeout=STREAM_PROBE_TIMEOUT, check=True
            )
            reports.append(
                re.sub(
                    r"(?m)^(Complete name\s*:\s*).*$",
                    lambda found: found.group(1) + name,
                    completed.stdout,
                ).rstrip()
            )
        return "\n\n\n".join(reports) + "\n"

    def _pictures(self, record: ReleasePreparation, payload: Path, root: Path) -> list[Path]:
        """Three pictures at the film's resolution; nCore takes at most 5 MB each."""

        profile = self.service._bound_profile(record)
        pictures: list[Path] = []
        folder = self._root / TORRENTS_DIRECTORY / f"{record.id}.pictures"
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        for number, source in enumerate(self.service._screenshots(payload, profile), start=1):
            if source.stat().st_size <= ncore.MAX_PICTURE_BYTES:
                pictures.append(source)
                continue
            target = folder / f"screen{number}.jpg"
            self.service.runner.capture(
                ["ffmpeg", "-hide_banner", "-v", "error", "-y", "-i", str(source), "-frames:v", "1", "-q:v", "2", str(target)],
                timeout=PICTURE_TIMEOUT,
                check=True,
            )
            if not target.is_file() or target.stat().st_size > ncore.MAX_PICTURE_BYTES:
                raise ReleasePublishError(f"picture {number} stays over nCore's 5 MB")
            pictures.append(target)
        return pictures

    def _publish(
        self,
        record: ReleasePreparation,
        send: Callable[[], tuple[UploadResult, bytes | None]],
    ) -> None:
        tracker = record.profile_id
        try:
            result, site = send()
        except SessionExpired as exc:
            # The tracker refused the login: nothing was filed.
            self._store.transition(
                record.id,
                ReleasePreparationState.READY_TO_PUBLISH,
                expected_version=record.version,
                values={"error": str(exc)},
            )
            return
        except Exception as exc:  # noqa: BLE001 - it may or may not have reached the tracker
            LOG.warning("upload of %s ended with %s", record.id, type(exc).__name__)
            self._store.transition(
                record.id,
                ReleasePreparationState.UNKNOWN,
                expected_version=record.version,
                values={
                    "error": f"the upload ended unclearly: {_safe_reason(exc)}. Look at {tracker} before trying again.",
                    "publication_receipt_json": {"outcome": "UNKNOWN", "tracker": tracker},
                },
            )
            return
        if result.rejected:
            self._store.transition(
                record.id,
                ReleasePreparationState.READY_TO_PUBLISH,
                expected_version=record.version,
                values={
                    "error": "; ".join(result.errors),
                    "publication_receipt_json": {
                        "outcome": "REJECTED",
                        "tracker": tracker,
                        "errors": list(result.errors),
                    },
                },
            )
            return
        if not result.accepted:
            self._store.transition(
                record.id,
                ReleasePreparationState.UNKNOWN,
                expected_version=record.version,
                values={
                    "error": f"{'; '.join(result.errors)}. Look at {tracker} before trying again.",
                    "publication_receipt_json": {"outcome": "UNKNOWN", "tracker": tracker},
                },
            )
            return
        published = self._store.transition(
            record.id,
            ReleasePreparationState.PUBLISHED,
            expected_version=record.version,
            values={
                "publication_receipt_json": {
                    "outcome": "PUBLISHED",
                    "tracker": tracker,
                    "torrent_id": result.torrent_id,
                    "url": result.url,
                    "note": result.note,
                    "published_at": self.service._now().isoformat(),
                },
            },
        )
        if site is not None:
            self._write_private(self._torrent_path(record, site=True), site)
        self._seed(published)

    # Seeding.

    def start_seed(self, preparation_id: str, *, expected_version: int) -> ReleasePreparation:
        """Again, after qBittorrent was down or the data was missing."""

        record = self._record(preparation_id, expected_version)
        if record.state is not ReleasePreparationState.PUBLISHED:
            raise StateConflictError("only a published release can be seeded")
        seeding = self._store.transition(
            preparation_id,
            ReleasePreparationState.SEEDING,
            expected_version=expected_version,
            values={"error": None},
        )

        def work() -> None:
            self._seed_from(seeding)

        self._background(work)
        return seeding

    def _seed(self, published: ReleasePreparation) -> None:
        seeding = self._store.transition(
            published.id,
            ReleasePreparationState.SEEDING,
            expected_version=published.version,
            values={"error": None},
        )
        self._seed_from(seeding)

    def _site_torrent(self, record: ReleasePreparation) -> bytes:
        path = self._torrent_path(record, site=True)
        if path.is_file():
            return path.read_bytes()
        receipt = record.publication_receipt or {}
        identifier = receipt.get("torrent_id")
        if not isinstance(identifier, int) or record.profile_id != "ncore":
            raise ReleasePublishError(
                "the tracker's torrent could not be fetched: download it from the tracker's page"
            )
        client = self._ncore()
        try:
            data = client.download_torrent(identifier)
        finally:
            client.close()
        self._write_private(path, data)
        return data

    def _seed_from(self, seeding: ReleasePreparation) -> None:
        try:
            receipt = self._run_seed(seeding)
            error = None
        except (ReleasePublishError, TrackerError, QbittorrentError, TorrentError, OSError) as exc:
            receipt = {"outcome": "FAILED", "reason": _safe_reason(exc)}
            error = f"The upload is done, but it does not seed yet: {_safe_reason(exc)}"
        except Exception as exc:  # noqa: BLE001 - the state must leave SEEDING
            LOG.warning("seeding %s ended with %s", seeding.id, type(exc).__name__)
            receipt = {"outcome": "FAILED", "reason": type(exc).__name__}
            error = "The upload is done, but seeding failed unexpectedly."
        self._store.transition(
            seeding.id,
            ReleasePreparationState.PUBLISHED,
            expected_version=seeding.version,
            values={"qbittorrent_receipt_json": receipt, "error": error},
        )

    def _run_seed(self, record: ReleasePreparation) -> dict[str, Any]:
        site = self._site_torrent(record)
        local = self._torrent_path(record).read_bytes()
        if not same_content(site, local):
            raise ReleasePublishError("the tracker's torrent describes other data than the one uploaded")
        self._assert_stage(record, local)
        client = self._qbittorrent()
        if client is None:
            raise ReleasePublishError(
                "no qBittorrent address is set on the System page: add the tracker's torrent by hand"
            )
        identifier = info_hash(site)
        try:
            client.add(site, info_hash=identifier, save_path=str(self._stage_root(record)))
            seeded = client.wait_until_seeding(identifier)
        finally:
            client.close()
        return {
            "outcome": "SEEDING",
            "info_hash": identifier,
            "state": seeded.state,
            "category": CATEGORY,
            "seeding_since": self.service._now().isoformat(),
        }

    def site_torrent(self, preparation_id: str) -> tuple[str, bytes]:
        """The file for seeding by hand.  It holds the account's passkey."""

        record = self._store.get(preparation_id)
        if record.state is not ReleasePreparationState.PUBLISHED:
            raise StateConflictError("only a published release has the tracker's torrent")
        return f"{record.metadata.release_name}.torrent", self._site_torrent(record)

    def discard(self, record: ReleasePreparation) -> None:
        """Remove a deleted preparation's links; the completed MKV keeps its own."""

        root = self._stage_root(record)
        if root.is_dir() and not root.is_symlink():
            shutil.rmtree(root, ignore_errors=True)
        for path in (self._torrent_path(record), self._torrent_path(record, site=True)):
            path.unlink(missing_ok=True)
        shutil.rmtree(self._root / TORRENTS_DIRECTORY / f"{record.id}.pictures", ignore_errors=True)


def _match_view(item: TrackerMatch) -> dict[str, Any]:
    return {
        "name": item.name,
        "url": item.url,
        "size": item.size,
        "exact": item.exact,
        "trumpable": item.trumpable,
    }


def _try_download(download: Callable[[], bytes]) -> bytes | None:
    """A failed download must not hide that the upload succeeded."""

    try:
        return download()
    except TrackerError as exc:
        LOG.warning("the tracker's torrent could not be fetched: %s", exc)
        return None


def _safe_reason(exc: BaseException) -> str:
    if isinstance(exc, (ReleasePublishError, TrackerError, QbittorrentError, TorrentError, StateConflictError)):
        return str(exc)
    return type(exc).__name__


def _clock(seconds: float) -> str:
    whole = int(seconds)
    return f"{whole // 3600:02d}:{whole % 3600 // 60:02d}:{whole % 60:02d}"


__all__ = [
    "AitherUploadRequest",
    "NcoreUploadRequest",
    "ReleasePublishError",
    "ReleasePublisher",
    "TRACKERS",
    "UploadApproval",
    "dynamic_range_of",
]
