"""The way from a built kit to a seeded upload, with fake trackers and a fake qBittorrent."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
from typing import Any

import pytest

from bdencode.config import Settings
from bdencode.db import Database, StateConflictError
from bdencode.models import ArtifactCreate, ArtifactKind, JobCreate
from bdencode.qbittorrent import QbittorrentError, SeedResult
from bdencode.release import ReleaseMetadata, ReleasePreparationState
from bdencode.release_publish import (
    AitherUploadRequest,
    NcoreUploadRequest,
    ReleasePublishError,
    ReleasePublisher,
    dynamic_range_of,
)
from bdencode.release_service import ReleaseService
from bdencode.torrent_file import bdecode, bencode, info_hash
from bdencode.tracker_settings import TrackerSettings, save_settings, settings_path
from bdencode.trackers import SessionExpired, TrackerError, TrackerMatch, UploadResult
from bdencode.utils import sha256_file

pytestmark = pytest.mark.skipif(not hasattr(os, "link"), reason="needs hard links")

AITHER_NAME = "Example.Movie.2026.2160p.UHD.BluRay.REMUX.DV.HDR.HEVC.TrueHD.7.1.Atmos-GROUP"
MEDIAINFO = "General\nUnique ID : 123\nComplete name : {path}\nFormat : Matroska\n"
STREAMS = {
    "streams": [
        {"codec_type": "video"},
        {"codec_type": "audio", "channels": 8, "tags": {"language": "eng"}},
        {"codec_type": "subtitle", "tags": {"language": "hun"}, "disposition": {"forced": 0}},
    ]
}


class _Runner:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    def capture(self, argv: list[str], *, timeout: float = 30, check: bool = True) -> subprocess.CompletedProcess[str]:
        self.commands.append(list(argv))
        if argv[0] == "mediainfo":
            return subprocess.CompletedProcess(argv, 0, stdout=MEDIAINFO.format(path=argv[-1]), stderr="")
        if argv[0] == "ffprobe":
            return subprocess.CompletedProcess(
                argv, 0, stdout=json.dumps({**STREAMS, "format": {"duration": "7000"}}), stderr=""
            )
        if argv[0] == "ffmpeg":
            Path(argv[-1]).write_bytes(b"\xff\xd8jpeg")
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
        if argv[0] == "mkvmerge":
            with Path(argv[argv.index("--output") + 1]).open("wb") as handle:
                handle.truncate(200 * 1024**2)
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
        raise AssertionError(argv)


class _FakeAither:
    def __init__(self) -> None:
        self.banned: frozenset[str] = frozenset()
        self.matches: tuple[TrackerMatch, ...] = ()
        self.uploads: list[dict[str, str]] = []
        self.result = UploadResult(accepted=True, torrent_id=7, url="https://aither.cc/torrents/7")
        self.link = "https://aither.cc/torrent/download/7.private"
        self.raises: Exception | None = None
        self.site_source = b"[aither.cc]"
        self.download_fails = False
        self.torrent: bytes = b""

    def banned_groups(self) -> frozenset[str]:
        return self.banned

    def search(self, **_kwargs: Any) -> tuple[TrackerMatch, ...]:
        return self.matches

    def upload(self, fields: dict[str, str], torrent: bytes) -> tuple[UploadResult, str]:
        if self.raises is not None:
            raise self.raises
        self.uploads.append(dict(fields))
        self.torrent = torrent
        return self.result, self.link

    def download_torrent(self, _link: str) -> bytes:
        if self.download_fails:
            raise TrackerError("no download")
        document = bdecode(self.torrent)
        document[b"info"][b"source"] = self.site_source
        return bencode(document)

    def check_connection(self) -> str:
        return "Aither API OK"

    def close(self) -> None:
        pass


class _FakeNcore:
    def __init__(self) -> None:
        self.matches: tuple[TrackerMatch, ...] = ()
        self.notice = ""
        self.uploads: list[tuple[dict[str, str], dict[str, Any]]] = []
        self.result = UploadResult(accepted=True, torrent_id=9, url="https://ncore.pro/torrents.php?action=details&id=9")

    def upload_token(self) -> str:
        return "t" * 20

    def banned_notice(self, _token: str, _fields: dict[str, str]) -> str:
        return self.notice

    def search(self, **_kwargs: Any) -> tuple[TrackerMatch, ...]:
        return self.matches

    def imdb_movie(self, _imdb_id: str) -> dict[str, str]:
        return {
            "movie_magyar_cim": "Példa film",
            "movie_angol_cim": "Example Movie",
            "movie_hossz": "120",
            "movie_orszag": "United States",
            "movie_rendezo": "Valaki",
        }

    def upload(self, fields: dict[str, str], files: dict[str, Any]) -> UploadResult:
        self.uploads.append((dict(fields), dict(files)))
        return self.result

    def download_torrent(self, _identifier: int) -> bytes:
        return self.uploads[-1][1]["torrent_fajl"][1]

    def close(self) -> None:
        pass


class _FakeQbit:
    def __init__(self) -> None:
        self.added: list[tuple[str, str]] = []
        self.fail: Exception | None = None
        self.url = ""

    def add(self, _torrent: bytes, *, info_hash: str, save_path: str) -> None:
        if self.fail is not None:
            raise self.fail
        self.added.append((info_hash, save_path))

    def wait_until_seeding(self, identifier: str) -> SeedResult:
        return SeedResult(info_hash=identifier, state="stalledUP", progress=1.0)

    def close(self) -> None:
        pass


class _Context:
    def __init__(self, tmp_path: Path, profile_id: str, *, size: int = 40_000, name: str = AITHER_NAME) -> None:
        source = tmp_path / "source"
        source.mkdir()
        self.settings = Settings(data_root=tmp_path / "data", source_roots=(source,)).validate()
        self.settings.create_directories()
        self.database = Database(self.settings.resolved_database_path)
        job = self.database.create_job(JobCreate(source_path=str(source)))
        with self.database._write() as connection:
            connection.execute(
                "UPDATE jobs SET state = 'COMPLETED', selection_json = ? WHERE id = ?",
                (json.dumps({"mode": "remux"}), job.id),
            )
        self.job_id = job.id
        completed = self.settings.completed_root / name
        comparison = completed / "comparison"
        comparison.mkdir(parents=True)
        self.payload = completed / f"{name}.mkv"
        with self.payload.open("wb") as handle:
            handle.truncate(size)
            handle.write(b"matroska")
        digest = sha256_file(self.payload)
        (completed / ".bdencode-owner.json").write_text(
            json.dumps({"schema_version": 2, "output_name": name, "mux_sha256": digest}), encoding="utf-8"
        )
        images = []
        for number in range(1, 4):
            png = comparison / f"{number:02d}-screenshot.png"
            png.write_bytes(b"\x89PNG\r\n\x1a\n" + bytes([number]) * 5000)
            images.append({"png": png.name, "sha256": sha256_file(png), "timestamp": "00:10:00.000", "frame": number})
        (comparison / "remux-screenshots.json").write_text(json.dumps({"images": images}), encoding="utf-8")
        (comparison / "comparison.bbcode").write_text("[img]https://x/1.png[/img]", encoding="utf-8")
        self.database.create_artifact(
            ArtifactCreate(
                job_id=job.id,
                kind=ArtifactKind.OUTPUT,
                name=self.payload.name,
                path=str(self.payload.resolve()),
                mime_type="video/x-matroska",
                sha256=digest,
                size_bytes=self.payload.stat().st_size,
            )
        )
        self.runner = _Runner()
        self.service = ReleaseService(self.database, self.settings, runner=self.runner)
        self.aither = _FakeAither()
        self.ncore = _FakeNcore()
        self.qbit = _FakeQbit()
        self.secrets = {
            "tracker-aither-api-token": "token",
            "tracker-ncore-cookies": "nick=a",
            "qbittorrent-password": "pw",
        }
        self.service.publisher = ReleasePublisher(
            self.service,
            aither_factory=lambda _token: self.aither,  # type: ignore[arg-type,return-value]
            ncore_factory=lambda _cookies: self.ncore,  # type: ignore[arg-type,return-value]
            qbittorrent_factory=lambda url, **_kw: self.qbit,  # type: ignore[arg-type,return-value]
            secret=self.secrets.__getitem__,
            background=lambda work: work(),
        )
        save_settings(
            settings_path(self.settings.state_root),
            TrackerSettings(qbittorrent_url="http://127.0.0.1:8080", qbittorrent_username="user"),
        )
        self.profile_id = profile_id
        self.name = name

    @property
    def publisher(self) -> ReleasePublisher:
        return self.service.publisher

    def built(self) -> Any:
        view = self.service.create(
            self.job_id,
            profile_id=self.profile_id,
            metadata=ReleaseMetadata(
                release_name=self.name,
                title="Example Movie",
                year=2026,
                imdb_id="tt0123456",
                tmdb_id=42,
                category="Movie",
                source_media="UHD Blu-ray",
                resolution="2160p",
                video_codec="H.265",
                audio_codecs=("TrueHD",),
                languages=("eng",),
            ),
        )
        return self.service.build(view.id, expected_version=view.version)

    def with_torrent(self) -> Any:
        ready = self.built()
        return self.publisher.start_torrent(ready.id, expected_version=ready.version), ready.id

    def ready_to_publish(self) -> Any:
        _record, identifier = self.with_torrent()
        current = self.service.store.get(identifier)
        return self.publisher.dupe_check(identifier, expected_version=current.version)

    def aither_request(self, record: Any, **changes: Any) -> AitherUploadRequest:
        return AitherUploadRequest(
            **{
                "expected_version": record.version,
                "confirm_release_name": self.name,
                "torrent_sha256": record.torrent_sha256,
                "name": "Example Movie 2026 2160p",
                "description": "[img]https://x/1.png[/img]",
                **changes,
            }
        )

    def ncore_request(self, record: Any, **changes: Any) -> NcoreUploadRequest:
        return NcoreUploadRequest(
            **{
                "expected_version": record.version,
                "confirm_release_name": self.name,
                "torrent_sha256": record.torrent_sha256,
                "name": "Példa film 2160p UHD BluRay REMUX",
                "description": "Egy részletes és hosszú leírás a filmről.\n\nForrás: UHD Blu-ray\n",
                "title_hu": "Példa film",
                "title_en": "Example Movie",
                "audio": "angol 7.1",
                "subtitles": "magyar",
                **changes,
            }
        )


@pytest.fixture
def aither_context(tmp_path: Path) -> _Context:
    return _Context(tmp_path, "aither")


@pytest.fixture
def ncore_context(tmp_path: Path) -> _Context:
    return _Context(tmp_path, "ncore")


def test_dynamic_range_comes_from_the_name() -> None:
    assert dynamic_range_of(AITHER_NAME) == ("DV", "HDR")
    assert dynamic_range_of("Film.2020.1080p.BluRay.x264-X") == ()


def test_the_torrent_is_a_hard_link_of_the_payload(aither_context: _Context) -> None:
    record, identifier = aither_context.with_torrent()

    assert record.state is ReleasePreparationState.BUILDING_TORRENT
    current = aither_context.service.store.get(identifier)
    assert current.state is ReleasePreparationState.READY
    assert current.error is None
    stage = aither_context.settings.seeding_root / identifier / aither_context.payload.name
    assert os.path.samefile(stage, aither_context.payload)
    torrent = (aither_context.settings.seeding_root / ".torrents" / f"{identifier}.torrent").read_bytes()
    assert info_hash(torrent) == current.torrent_infohash
    info = bdecode(torrent)[b"info"]
    assert info[b"private"] == 1
    assert info[b"source"] == b"Aither"
    assert info[b"name"] == aither_context.payload.name.encode()


def test_a_torrent_cannot_be_made_twice_or_with_a_stale_version(aither_context: _Context) -> None:
    ready = aither_context.built()
    with pytest.raises(StateConflictError):
        aither_context.publisher.start_torrent(ready.id, expected_version=ready.version + 5)
    aither_context.publisher.start_torrent(ready.id, expected_version=ready.version)
    current = aither_context.service.store.get(ready.id)
    with pytest.raises(StateConflictError):
        aither_context.publisher.start_torrent(ready.id, expected_version=current.version)


def test_the_duplicate_check_needs_the_torrent(aither_context: _Context) -> None:
    ready = aither_context.built()
    with pytest.raises(StateConflictError, match="torrent"):
        aither_context.publisher.dupe_check(ready.id, expected_version=ready.version)


def test_clear_check_then_upload_then_seed(aither_context: _Context) -> None:
    clear = aither_context.ready_to_publish()
    assert clear.state is ReleasePreparationState.READY_TO_PUBLISH
    assert clear.dupe_receipt["outcome"] == "CLEAR"

    aither_context.publisher.upload(clear.id, aither_context.aither_request(clear))

    done = aither_context.service.store.get(clear.id)
    assert done.state is ReleasePreparationState.PUBLISHED
    assert done.publication_receipt["torrent_id"] == 7
    assert "private" not in json.dumps(done.publication_receipt)
    assert done.qbittorrent_receipt["outcome"] == "SEEDING"
    assert done.error is None
    sent = aither_context.aither.uploads[0]
    assert sent["type_id"] == "2"
    assert sent["dv"] == "1"
    assert sent["mediainfo"].startswith("General")
    assert str(aither_context.settings.data_root) not in sent["mediainfo"]
    (identifier, save_path) = aither_context.qbit.added[0]
    assert save_path == str(aither_context.settings.seeding_root / clear.id)
    # What seeds is the tracker's own torrent.
    site = (aither_context.settings.seeding_root / ".torrents" / f"{clear.id}.site.torrent").read_bytes()
    assert identifier == info_hash(site) != done.torrent_infohash


def test_the_upload_needs_the_exact_approval(aither_context: _Context) -> None:
    clear = aither_context.ready_to_publish()
    wrong = (
        aither_context.aither_request(clear, confirm_release_name="Other"),
        aither_context.aither_request(clear, torrent_sha256="0" * 64),
        aither_context.aither_request(clear, expected_version=clear.version + 1),
    )
    for request in wrong:
        with pytest.raises(StateConflictError):
            aither_context.publisher.upload(clear.id, request)
    assert aither_context.aither.uploads == []
    assert aither_context.service.store.get(clear.id).state is ReleasePreparationState.READY_TO_PUBLISH


def test_an_upload_without_pictures_is_refused_before_sending(aither_context: _Context) -> None:
    clear = aither_context.ready_to_publish()

    with pytest.raises(ReleasePublishError, match="pictures"):
        aither_context.publisher.upload(clear.id, aither_context.aither_request(clear, description="no images"))

    assert aither_context.aither.uploads == []


def test_a_refused_upload_can_be_corrected(aither_context: _Context) -> None:
    clear = aither_context.ready_to_publish()
    aither_context.aither.result = UploadResult(rejected=True, errors=("name: taken",))

    aither_context.publisher.upload(clear.id, aither_context.aither_request(clear))

    current = aither_context.service.store.get(clear.id)
    assert current.state is ReleasePreparationState.READY_TO_PUBLISH
    assert current.error == "name: taken"
    assert current.publication_receipt["outcome"] == "REJECTED"
    assert aither_context.qbit.added == []


def test_an_unclear_upload_stops_and_is_never_repeated(aither_context: _Context) -> None:
    clear = aither_context.ready_to_publish()
    aither_context.aither.result = UploadResult(errors=("an unclear answer, HTTP 500",))

    aither_context.publisher.upload(clear.id, aither_context.aither_request(clear))

    current = aither_context.service.store.get(clear.id)
    assert current.state is ReleasePreparationState.UNKNOWN
    assert "Look at aither" in (current.error or "")
    assert len(aither_context.aither.uploads) == 1
    with pytest.raises(StateConflictError):
        aither_context.publisher.upload(clear.id, aither_context.aither_request(current))
    assert len(aither_context.aither.uploads) == 1


def test_an_unclear_upload_found_on_the_tracker_cannot_go_up_again(aither_context: _Context) -> None:
    clear = aither_context.ready_to_publish()
    aither_context.aither.result = UploadResult(errors=("timeout",))
    aither_context.publisher.upload(clear.id, aither_context.aither_request(clear))
    current = aither_context.service.store.get(clear.id)
    aither_context.aither.matches = (TrackerMatch(name="x", exact=True),)

    review = aither_context.publisher.dupe_check(clear.id, expected_version=current.version)

    assert review.state is ReleasePreparationState.NEEDS_REVIEW
    with pytest.raises(StateConflictError, match="exact"):
        aither_context.publisher.acknowledge_duplicates(
            clear.id, expected_version=review.version, reason="valami hosszabb indok"
        )


def test_a_refused_key_leaves_the_release_ready(aither_context: _Context) -> None:
    clear = aither_context.ready_to_publish()
    aither_context.aither.raises = SessionExpired("Aither refused the API key")

    aither_context.publisher.upload(clear.id, aither_context.aither_request(clear))

    current = aither_context.service.store.get(clear.id)
    assert current.state is ReleasePreparationState.READY_TO_PUBLISH
    assert current.error == "Aither refused the API key"


def test_a_crash_during_the_upload_is_unclear(aither_context: _Context) -> None:
    clear = aither_context.ready_to_publish()
    aither_context.aither.raises = RuntimeError("secret detail")

    aither_context.publisher.upload(clear.id, aither_context.aither_request(clear))

    current = aither_context.service.store.get(clear.id)
    assert current.state is ReleasePreparationState.UNKNOWN
    assert "secret detail" not in (current.error or "")


def test_duplicate_hits_need_a_reason_and_an_exact_name_blocks(aither_context: _Context) -> None:
    _record, identifier = aither_context.with_torrent()
    current = aither_context.service.store.get(identifier)
    aither_context.aither.matches = (TrackerMatch(name="Example Movie 2026 1080p x264-OTHER"),)

    review = aither_context.publisher.dupe_check(identifier, expected_version=current.version)

    assert review.state is ReleasePreparationState.NEEDS_REVIEW
    assert review.dupe_receipt["outcome"] == "DUPLICATE"
    with pytest.raises(ReleasePublishError, match="reason"):
        aither_context.publisher.acknowledge_duplicates(identifier, expected_version=review.version, reason="rövid")
    accepted = aither_context.publisher.acknowledge_duplicates(
        identifier, expected_version=review.version, reason="Remux az encode mellett, más típus."
    )
    assert accepted.state is ReleasePreparationState.READY_TO_PUBLISH
    assert accepted.dupe_receipt["acknowledged_reason"].startswith("Remux")


def test_a_banned_group_cannot_be_acknowledged(aither_context: _Context) -> None:
    _record, identifier = aither_context.with_torrent()
    current = aither_context.service.store.get(identifier)
    aither_context.aither.banned = frozenset({"group"})

    review = aither_context.publisher.dupe_check(identifier, expected_version=current.version)

    assert review.dupe_receipt["outcome"] == "BLOCKED"
    assert "GROUP" in review.dupe_receipt["blocked_reason"]
    with pytest.raises(StateConflictError):
        aither_context.publisher.acknowledge_duplicates(
            identifier, expected_version=review.version, reason="valami hosszabb indok"
        )


def test_an_unreachable_tracker_changes_nothing(aither_context: _Context) -> None:
    _record, identifier = aither_context.with_torrent()
    current = aither_context.service.store.get(identifier)

    def broken(**_kwargs: Any) -> Any:
        raise TrackerError("Aither cannot be reached (ConnectError)")

    aither_context.aither.search = broken  # type: ignore[method-assign]

    with pytest.raises(ReleasePublishError, match="cannot be reached"):
        aither_context.publisher.dupe_check(identifier, expected_version=current.version)
    assert aither_context.service.store.get(identifier).state is ReleasePreparationState.READY


def test_a_missing_login_is_reported_plainly(aither_context: _Context) -> None:
    _record, identifier = aither_context.with_torrent()
    current = aither_context.service.store.get(identifier)
    aither_context.secrets.pop("tracker-aither-api-token")
    from bdencode.secrets import SecretUnavailable

    def missing(name: str) -> str:
        raise SecretUnavailable(name)

    aither_context.publisher._secret = missing

    with pytest.raises(ReleasePublishError, match="System page"):
        aither_context.publisher.dupe_check(identifier, expected_version=current.version)


def test_the_plan_shows_what_goes_up_and_what_is_wrong(aither_context: _Context) -> None:
    clear = aither_context.ready_to_publish()

    plan = aither_context.publisher.upload_plan(clear.id)

    assert plan["tracker"] == "aither"
    assert plan["fields"]["name"].endswith("TrueHD 7.1 Atmos-GROUP")
    assert plan["facts"]["type"] == "REMUX"
    assert plan["facts"]["tmdb"] == 42
    assert plan["facts"]["dynamic_range"] == ["DV", "HDR"]
    assert plan["problems"] == []
    assert plan["seeding"] == {"automatic": True, "category": "bdencode"}
    assert plan["files"] == [aither_context.payload.name]


def test_failed_seed_keeps_the_upload_and_can_be_retried(aither_context: _Context) -> None:
    clear = aither_context.ready_to_publish()
    aither_context.qbit.fail = QbittorrentError("qBittorrent cannot be reached (ConnectError)")

    aither_context.publisher.upload(clear.id, aither_context.aither_request(clear))

    current = aither_context.service.store.get(clear.id)
    assert current.state is ReleasePreparationState.PUBLISHED
    assert current.qbittorrent_receipt["outcome"] == "FAILED"
    assert "does not seed yet" in (current.error or "")

    aither_context.qbit.fail = None
    aither_context.publisher.start_seed(clear.id, expected_version=current.version)

    current = aither_context.service.store.get(clear.id)
    assert current.state is ReleasePreparationState.PUBLISHED
    assert current.qbittorrent_receipt["outcome"] == "SEEDING"
    assert current.error is None
    assert len(aither_context.aither.uploads) == 1


def test_without_a_qbittorrent_address_the_torrent_is_there_for_manual_seeding(aither_context: _Context) -> None:
    save_settings(settings_path(aither_context.settings.state_root), TrackerSettings())
    clear = aither_context.ready_to_publish()

    aither_context.publisher.upload(clear.id, aither_context.aither_request(clear))

    current = aither_context.service.store.get(clear.id)
    assert current.state is ReleasePreparationState.PUBLISHED
    assert current.qbittorrent_receipt["outcome"] == "FAILED"
    assert "by hand" in (current.error or "")
    name, data = aither_context.publisher.site_torrent(clear.id)
    assert name.endswith(".torrent")
    assert info_hash(data)


def test_other_content_from_the_tracker_is_not_seeded(aither_context: _Context) -> None:
    clear = aither_context.ready_to_publish()

    def other(_link: str) -> bytes:
        return bencode({"info": {"name": "Other.mkv", "length": 1, "piece length": 16384, "pieces": b"\1" * 20}})

    aither_context.aither.download_torrent = other  # type: ignore[method-assign]

    aither_context.publisher.upload(clear.id, aither_context.aither_request(clear))

    current = aither_context.service.store.get(clear.id)
    assert current.qbittorrent_receipt["outcome"] == "FAILED"
    assert aither_context.qbit.added == []


def test_startup_recovery_keeps_a_published_upload_published(aither_context: _Context) -> None:
    clear = aither_context.ready_to_publish()
    aither_context.publisher.upload(clear.id, aither_context.aither_request(clear))
    current = aither_context.service.store.get(clear.id)
    seeding = aither_context.service.store.transition(
        clear.id, ReleasePreparationState.SEEDING, expected_version=current.version
    )

    aither_context.service.store.recover_interrupted()

    recovered = aither_context.service.store.get(seeding.id)
    assert recovered.state is ReleasePreparationState.PUBLISHED
    assert recovered.error


def test_startup_recovery_returns_a_torrent_build_to_ready(aither_context: _Context) -> None:
    ready = aither_context.built()
    aither_context.service.store.transition(
        ready.id, ReleasePreparationState.BUILDING_TORRENT, expected_version=ready.version
    )

    aither_context.service.store.recover_interrupted()

    assert aither_context.service.store.get(ready.id).state is ReleasePreparationState.READY


def test_ncore_small_release_is_one_file_and_big_one_gets_a_sample(tmp_path: Path) -> None:
    (tmp_path / "small").mkdir()
    (tmp_path / "big").mkdir()
    small = _Context(tmp_path / "small", "ncore")
    _record, identifier = small.with_torrent()
    current = small.service.store.get(identifier)
    assert current.error is None
    assert (small.settings.seeding_root / identifier / small.payload.name).is_file()

    big = _Context(tmp_path / "big", "ncore", size=2 * 1024**3 + 1)
    _record, identifier = big.with_torrent()
    current = big.service.store.get(identifier)
    assert current.error is None
    folder = big.settings.seeding_root / identifier / big.name
    assert os.path.samefile(folder / big.payload.name, big.payload)
    assert (folder / "sample.mkv").is_file()
    assert any(command[0] == "mkvmerge" for command in big.runner.commands)


def test_ncore_plan_fetches_the_film_and_asks_for_a_description(ncore_context: _Context) -> None:
    clear = ncore_context.ready_to_publish()

    plan = ncore_context.publisher.upload_plan(clear.id)

    assert plan["tracker"] == "ncore"
    assert plan["fields"]["title_hu"] == "Példa film"
    assert plan["fields"]["name"] == "Példa film 2160p UHD BluRay REMUX DV HDR"
    assert plan["fields"]["audio"] == "angol 7.1"
    assert plan["fields"]["subtitles"] == "magyar"
    assert plan["fields"]["runtime"] == "120"
    assert plan["facts"]["category"] == "hd"
    assert any("30 characters" in item for item in plan["problems"])


def test_ncore_upload_sends_the_form_techinfo_and_pictures(ncore_context: _Context) -> None:
    clear = ncore_context.ready_to_publish()

    ncore_context.publisher.upload(clear.id, ncore_context.ncore_request(clear))

    current = ncore_context.service.store.get(clear.id)
    assert current.state is ReleasePreparationState.PUBLISHED
    assert current.qbittorrent_receipt["outcome"] == "SEEDING"
    fields, files = ncore_context.ncore.uploads[0]
    assert fields["tipus"] == "hd"
    assert fields["eredeti"] == "nem"
    assert fields["imdb_id"] == "tt0123456"
    assert set(files) == {"torrent_fajl", "techinfo_fajl", "kep1", "kep2", "kep3"}
    techinfo = files["techinfo_fajl"][1].decode()
    assert f"Complete name : {ncore_context.payload.name}" in techinfo
    assert str(ncore_context.settings.data_root) not in techinfo


def test_ncore_big_pictures_become_jpeg_and_a_ban_notice_stops(ncore_context: _Context) -> None:
    for png in (ncore_context.payload.parent / "comparison").glob("*.png"):
        png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * (6 * 1024 * 1024))
    document = []
    for png in sorted((ncore_context.payload.parent / "comparison").glob("*.png")):
        document.append({"png": png.name, "sha256": sha256_file(png), "timestamp": "00:10:00.000", "frame": 1})
    (ncore_context.payload.parent / "comparison" / "remux-screenshots.json").write_text(
        json.dumps({"images": document}), encoding="utf-8"
    )
    clear = ncore_context.ready_to_publish()
    ncore_context.ncore.notice = "Tiltott anyag"

    ncore_context.publisher.upload(clear.id, ncore_context.ncore_request(clear))

    current = ncore_context.service.store.get(clear.id)
    assert current.state is ReleasePreparationState.READY_TO_PUBLISH
    assert "ban list" in (current.error or "")
    assert ncore_context.ncore.uploads == []
    assert any(command[0] == "ffmpeg" for command in ncore_context.runner.commands)


def test_ncore_refuses_an_incomplete_form_before_sending(ncore_context: _Context) -> None:
    clear = ncore_context.ready_to_publish()

    with pytest.raises(ReleasePublishError, match="30 characters"):
        ncore_context.publisher.upload(clear.id, ncore_context.ncore_request(clear, description="Rövid"))

    assert ncore_context.ncore.uploads == []


def test_deleting_a_preparation_removes_its_links_but_not_the_mkv(aither_context: _Context) -> None:
    clear = aither_context.ready_to_publish()
    stage = aither_context.settings.seeding_root / clear.id

    aither_context.service.delete(clear.id, expected_version=clear.version)

    assert not stage.exists()
    assert aither_context.payload.is_file()
