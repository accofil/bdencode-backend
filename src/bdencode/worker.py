"""Durable worker with concurrent scan and strictly serial encode lanes.

The database owns scheduling and the job state is the recovery cursor.  Every
expensive filesystem stage also has a content-addressed marker, so a service
restart never treats the mere presence of a partial output as success.
"""

from __future__ import annotations

import contextlib
import errno
import functools
import hashlib
import json
import logging
import math
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, replace
from datetime import timedelta
from decimal import ROUND_HALF_EVEN, Decimal
from fractions import Fraction
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Literal, Mapping, Protocol, Sequence

from .audio import (
    AUDIO_DECODE_POLICY_SCHEMA_VERSION,
    AUDIO_TRANSCODE_PRESETS,
    audio_decode_input_args,
    effective_audio_policy,
    expected_audio_codec,
    normalize_audio_codec_name,
)
from .chapters import render_matroska_chapters
from .config import ConfigurationError, Settings
from .capabilities import capability_snapshot, dynamic_hdr_support, remux_support
from .crf_search import (
    STATUS_BEST_EFFORT,
    STATUS_MAX_CRF,
    AutoCrfConfig,
    CrfProbe,
    CrfSearch,
    CrfSearchError,
    CrfSearchOutcome,
    STATUS_MIN_CRF,
    STATUS_UNREACHABLE,
    SampleWindow,
    SizeSearch,
    plan_sample_windows,
    project_title_bytes,
    summarize_sampled_vmaf,
    vmaf_model_for_height,
    vmaf_score,
)
from .db import Database, StateConflictError
from .dolby_vision_scan import detect_dolby_vision_layers
from .object_audio_scan import detect_object_audio
from .hdr_dynamic import (
    DISCARD_PLAN,
    DOLBY_VISION_VBV_KBPS,
    DynamicHdrError,
    DynamicHdrMode,
    DynamicHdrPlan,
    allowed_forbidden_tokens,
    dovi_base_stream_command,
    dovi_duration_command,
    dovi_extract_commands,
    dovi_inject_command,
    dovi_rebuild_command,
    dovi_summary_command,
    dovi_verify_commands,
    hdr10plus_extract_commands,
    hdr10plus_inject_command,
    parse_dovi_summary,
    parse_hdr10plus_json,
    parse_mode,
    parse_video_track_properties,
    require_dolby_vision_profile,
    require_frame_alignment,
    resolve_dynamic_hdr,
    video_timestamps_command,
    video_track_command,
    x265_dynamic_params,
)
from .encode import (
    PcmBlurayAudio,
    ReferenceRemuxPlan,
    audio_track_command,
    encode_pipeline_commands,
    reference_remux_command,
    subtitle_track_command,
)
from .media.bluray import (
    BluRayScanner,
    ContentKind,
    DiscKind,
    DiscScan,
    HdrStaticMetadata,
    LIBBLURAY_UNAVAILABLE_WARNING,
    MediaStream,
    PlaylistCandidate,
    PlaylistSegment,
    SOURCE_KIND_DISC,
    SOURCE_KIND_MKV,
    StreamKind,
    ToolCapabilities,
    TrackRole,
    VideoCodec,
    VideoProperties,
)
from .media.mkv_source import MkvScanner, is_mkv_source, mkv_fingerprint
from .media.language import (
    LanguageDecision,
    LanguageEvidence,
    LanguageResolver,
    LanguageSettlement,
    LanguageSource,
    LanguageStatus,
    normalize_iso639_2,
    settle_track_language,
)
from .media.language_runtime import AudioLanguageRuntime, LanguageInferenceUnavailable
from .media.track_analysis import (
    ANALYSIS_SCHEMA_VERSION as TRACK_ANALYSIS_SCHEMA_VERSION,
    analyse_playlist,
    playlists_to_analyse,
)
from .media.planner import (
    Crop as PlannerCrop,
    EncodePlanner,
    EncodeRequest,
    FieldHandling,
    TrackAction,
    TrackSelection,
    resolve_audio_defaults,
    resolved_track_name,
)
from .media.profiles import (
    ColorMetadata,
    DetailLevel,
    EncoderSettings,
    Hdr10Metadata,
    VbvSettings,
    VideoEncoder,
    format_frame_rate,
    parse_frame_rate,
    recommended_profile,
    source_adapted_settings,
)
from .maintenance import (
    MaintenanceDomainGuard,
    MaintenanceJournal,
    MaintenancePhase,
    MaintenanceTargetSpec,
    safe_tree_usage,
)
from .logs import assert_public_metadata_absent, sanitize_text
from .models import (
    ArtifactCreate,
    ArtifactKind as DatabaseArtifactKind,
    EventCreate,
    Job,
    JobControlState,
    JobState,
    Scan,
    ScanCreate,
    ScanState,
    ScanUpdate,
    TERMINAL_STATES,
)
from .mux import (
    FinalTrackPolicy,
    FinalVideoPolicy,
    MuxTrack,
    MkvmergeWarning,
    classify_mkvmerge_warnings,
    inspection_commands,
    mkvmerge_command,
    mkvmerge_warning_lines,
    encoder_priming_seconds,
    first_packet_probe_command,
    parse_first_packet_time,
    parse_stream_start_times,
    parse_stream_start_times_by_type,
    plan_common_zero_timeline,
    stream_start_probe_command,
    validate_dynamic_hdr_output,
    assess_ffprobe_stream_policy,
    validate_hdr10_side_data,
    validate_mkvmerge_identification,
    validate_stream_start_times,
)
from .process import (
    CommandRunner,
    DiagnosticCategory,
    MediaDiagnostic,
    ProcessFailure,
    ProcessInterrupted,
    classify_media_diagnostics,
    redact_argv,
)
from .progress import EncodeProgressReporter, FFmpegProgressParser
from . import dovi_layers, remux
from .external import render as external_render
from .external import source as external_source
from .external import spec as external_spec
from .external import subtitles as external_subtitles
from .external.frame_map import FrameMapError
from .qc import av_sync, multi_clip
from .qc.artifacts import inspect_png
from .qc.audio import (
    AUDIO_FRAME_CONTINUITY_SCHEMA_VERSION,
    analysis_command,
    audio_frame_continuity_probe_command,
    audio_probe_command,
    compare_audio_frame_continuity,
    compare_audio_probes,
    parse_audio_frame_continuity,
    parse_audio_probe,
    parse_audio_analysis,
    pcm_hash_command,
    plan_spectrum_windows,
    spectrum_command,
    spectrum_stitch_command,
    verify_audio_output,
    verify_audio_signal,
)
from .qc.catbox import CatboxClient
from .qc.crop import (
    automatic_crop,
    count_crop_observations,
    CropPolicyError,
    DEFAULT_MINIMUM_OBSERVATIONS as CROP_MINIMUM_OBSERVATIONS,
    full_title_cropdetect_command,
    keyframe_cropdetect_commands,
    parse_aspect_profile,
    parse_stable_cropdetect,
    tightened_edges,
    validate_operator_crop,
    variable_aspect_evidence,
    verify_crop_against_full_decode,
)
from .qc.freeimage import FreeimageClient
from .qc.image_upload import (
    IMAGE_UPLOAD_PROVIDERS,
    ImageUploadClient,
    ImageUploadError,
    parse_uploaded_image_checkpoint,
    upload_size_limit,
)
from .qc.imgbb import ImgBBClient
from .upload_settings import (
    host_order as upload_host_order,
    load_preferences as load_upload_preferences,
    order_by_preference,
    settings_path as upload_settings_path,
)
from .qc.video import (
    CropMargins as ActiveCropMargins,
    FrameRecord,
    FrameSelectionError,
    annotate_comparison_png_command,
    comparison_manifest,
    extract_png_at_timestamp_command,
    extract_y4m_at_timestamp_command,
    ffprobe_frame_origin_command,
    ffprobe_sampled_frame_command,
    parse_ffprobe_frame_origin,
    MAXIMUM_MEAN_PLANE_BIAS,
    parse_ffmpeg_metric_stats,
    parse_sampled_ffprobe_frames,
    plane_bias,
    parse_vspipe_info,
    plan_sample_intervals,
    png_filter_chain,
    native_yuv_metric_command,
    select_frame_pairs,
    select_frame_pairs_reducing_i,
    tracker_type_counts,
    vspipe_info_command,
)
from .qc.subtitle import (
    SubtitleDecodeError,
    parse_subtitle_probe,
    assess_final_subtitle_decode,
    require_subtitle_decode,
    subtitle_decode_probe_command,
    subtitle_probe_command,
    validate_subtitle_classification,
)
from .qc.integrity import (
    classify_final_decode_log,
    clip_join_decode_command,
    compare_packet_timelines,
    packet_timeline_probe_command,
    parse_packet_timeline,
    parse_video_packet_sizes,
    parse_stream_payload_hash,
    parse_video_stream_hash,
    require_video_cadence,
    require_video_completeness,
    evaluate_video_efficiency,
    source_video_integrity_command,
    split_clip_join_lines,
    stream_payload_hash_command,
    video_packet_size_command,
    video_stream_hash_command,
)
from .queue import JobQueue
from .i18n import t
from .live_progress import (
    LiveProgress,
    LiveText,
    media_seconds_in_tail,
    percent_in_tail,
    time_fraction,
)
from .review import read_upload_override, video_metrics_accepted
from .tracker_bbcode import (
    remux_bbcode,
    aither_comparison_bbcode,
    encoder_summary,
    gallery_bbcode,
    published_pairs,
    screenshot_pair_numbers,
    tracker_bbcode,
)
from .tracker_policy import TrackerProfile
from .release_naming import (
    RELEASE_NAME_PATTERNS,
    AudioOutput,
    ReleaseFacts,
    audio_codec_family,
    release_name_problems,
)
from .media.hwaccel import cuda_decode_available
from .source_stage import (
    StagingInterrupted,
    StagingUnavailable,
    needs_staging,
    plan_files,
    remove_stage,
    remove_stale_stages,
    stage_disc,
    stage_root_for,
)
from .utils import (
    atomic_write_json,
    atomic_write_text,
    sha256_file as _uncached_sha256_file,
)
from .vapoursynth import (
    LSMAS_FIRST_SEEK_PREROLL_FRAMES,
    Crop as VapourSynthCrop,
    ReferenceScriptPlan,
    SourceFilter,
    TemporalFilter,
    reference_frame_preroll,
    render_reference_script,
    script_record,
)
from .vmaf_runner import streamed_vmaf_command


LOG = logging.getLogger(__name__)

# Free space that must remain beside a staged disc copy on top of the reference
# remux, which is about as large as the copied clips.
STAGE_RESERVE_BYTES = 10 * 1024**3
# An MKV source is copied to the reference in these blocks; the copy must leave
# at least this much space free.
MKV_COPY_BLOCK_BYTES = 8 * 1024 * 1024
MKV_REFERENCE_RESERVE_BYTES = 2 * 1024**3

# Sampled VMAF of the finished file: 12 windows of 2 s (576 frames at 24p).
FINAL_VMAF_SAMPLES = 12
FINAL_VMAF_SAMPLE_SECONDS = 2.0

# Independent QC/comparison commands (probes, hashes, analyses of different
# files) run this many at a time.
INDEPENDENT_COMMAND_WORKERS = 4

# Frame threads of the full source decode.  On a 4K HEVC reference sixteen
# threads decode about a fifth faster than FFmpeg's default; more do not help.
INTEGRITY_DECODE_THREADS = max(1, min(16, os.cpu_count() or 1))
# A keyframe-only decode is single-threaded: the CPU crop scan runs this many
# time ranges side by side.
CROP_SCAN_SEGMENTS = max(1, min(16, os.cpu_count() or 1))


def _images_to_upload(
    pngs: Sequence[Path],
    image_set: str,
    pairs: Sequence[Mapping[str, Any]] | None = None,
) -> list[Path]:
    """The published subset of the comparison images.

    With the comparison ``pairs``, only the pictures of the published pairs
    (:func:`published_pairs`, ten) are kept; the other measured pairs stay
    local.  ``sdr`` leaves out the native picture of every pair that also has
    a tone-mapped ``-sdr`` view (an SDR title keeps its native pictures);
    ``native`` leaves out the ``-sdr`` views.  Audio spectrograms and tracker
    screenshots always stay.
    """

    if pairs:
        kept = {id(item) for item in published_pairs(pairs)}
        held_back = {
            str(item.get(key))
            for item in pairs
            if isinstance(item, Mapping) and id(item) not in kept
            for key in ("reference_png", "encode_png", "reference_sdr_png", "encode_sdr_png")
            if item.get(key)
        }
        pngs = [png for png in pngs if png.name not in held_back]
    if image_set == "all":
        return list(pngs)
    names = {png.name for png in pngs}
    selected: list[Path] = []
    for png in pngs:
        is_sdr_view = png.name.endswith("-sdr.png")
        has_sdr_view = png.name.removesuffix(".png") + "-sdr.png" in names
        if image_set == "sdr" and has_sdr_view:
            continue
        if image_set == "native" and is_sdr_view:
            continue
        selected.append(png)
    return selected


class _BackgroundRun:
    """Run ``function(cancelled)`` on a thread beside the caller's own work."""

    def __init__(
        self, function: Callable[[Callable[[], bool]], object], *, name: str
    ) -> None:
        self._cancelled = threading.Event()
        self._error: BaseException | None = None
        self._thread = threading.Thread(
            target=self._main, args=(function,), name=name, daemon=True
        )
        self._thread.start()

    def _main(self, function: Callable[[Callable[[], bool]], object]) -> None:
        try:
            function(self._cancelled.is_set)
        except BaseException as exc:  # handed to the waiting thread
            self._error = exc

    def failed(self) -> bool:
        return self._error is not None

    def wait(self) -> None:
        """Wait for the work and re-raise its error."""

        self._thread.join()
        if self._error is not None:
            raise self._error

    def cancel(self) -> BaseException | None:
        """Stop the work, wait for it and return its error (if it had failed)."""

        self._cancelled.set()
        self._thread.join()
        return self._error


# Twenty-five distributed probes decode roughly six minutes once the open-GOP
# preroll is included.  Real H.264/HEVC titles can need more than 90 seconds on
# otherwise healthy hardware, while the enclosing comparison still enforces a
# strict thirty-minute wall-clock deadline.
COMPARISON_FRAME_PROBE_TIMEOUT_SECONDS = 300
COMPARISON_DEADLINE_SECONDS = 1800
_REFERENCE_PIXELS = 1920 * 1080
MAX_COMPARISON_BUDGET_SCALE = 4
# A comparison that runs out of time is retried with these multiples of its
# budgets before the job asks for review: a slow disk or a busy host is far
# more common than a hung decoder, and finished pairs are kept between runs.
COMPARISON_RETRY_TIME_SCALES: tuple[int, ...] = (1, 2, 4)


def comparison_budget_scale(width: int | None, height: int | None) -> int:
    """How many times the 1080p comparison budgets a picture of this size needs.

    The sampled frame probes decode twenty-four overlapping windows, each with a whole GOP of
    preroll. The 300 s / 30 min budgets were set for 1080p; a UHD title has four times the pixels
    to decode, and a measured UHD run hit the per-probe limit while the same work at 1080p fits.
    """

    if not width or not height or width <= 0 or height <= 0:
        return 1
    return max(1, min(MAX_COMPARISON_BUDGET_SCALE, round(width * height / _REFERENCE_PIXELS)))

# libvmaf frame-level threads for the CRF probes.  Measured on 720p: one thread
# 114 s, four 25 s, eight 14.5 s, sixteen 10.5 s for the same bit-identical
# score; eight keeps the per-frame float buffers of a UHD title modest.
VMAF_PROBE_MAX_THREADS = 8


def _vmaf_thread_count() -> int:
    return max(1, min(VMAF_PROBE_MAX_THREADS, os.cpu_count() or 1))


_FFPROBE_PROFILE_NAMES = {
    "high": "High",
    "high10": "High 10",
    "main": "Main",
    "main10": "Main 10",
    # FFmpeg 5.x reports libx265's 12-bit Main profile under the HEVC
    # Range-Extensions profile family.
    "main12": "Rext",
}


def _ffprobe_level_idc(encoder: VideoEncoder, level: str | None) -> int | None:
    """Translate the configured codec level to FFprobe's integer notation."""

    if level is None:
        return None
    multiplier = 10 if encoder is VideoEncoder.X264 else 30
    return int(Decimal(level) * multiplier)


_SAFE_OUTPUT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ ()'&+\-]{0,199}$")
_X264_RELEASE_RE = RELEASE_NAME_PATTERNS["x264"]
_X265_RELEASE_RE = RELEASE_NAME_PATTERNS["x265"]
_SELECTION_KEYS = {
    "schema_version",
    "playlist_id",
    "angle",
    "video",
    "crop",
    "temporal_filter",
    "tracks",
    "output_name",
    "upload_images",
    "image_upload_provider",
    "upload_image_set",
    "dual_type_match",
    "tracker_profile",
    # "encode" (the default) or "remux": an untouched Aither-style remux.
    "mode",
    "remux",
    # Tracks and subtitles fitted from another source (bdencode.external).
    "external_sources",
}
# A remux selection carries no video settings, crop or filter.
_REMUX_SELECTION_KEYS = _SELECTION_KEYS - {"video", "crop", "temporal_filter", "dual_type_match"}
# A fit keeps a finished MKV as it is and only adds tracks to it.
_FIT_SELECTION_KEYS = _REMUX_SELECTION_KEYS - {"remux"}
_REMUX_OPTION_KEYS = {"imdb", "tmdb"}
# Which comparison images are published: all of them, only the tone-mapped
# SDR views of an HDR title (half the upload), or only the native pictures.
UPLOAD_IMAGE_SETS = frozenset({"all", "sdr", "native"})
# Images uploaded at the same time once the first one has locked the host.
UPLOAD_PARALLELISM = 3
# An UHD remux's raw video in the job's work/remux folder.
REMUX_UHD_VIDEO = "video.hevc"
# Screenshots of a remux per tracker profile (Aither asks for 3 or more).
REMUX_SCREENSHOT_COUNT = {"aither": 6, "ncore": 3, "none": 6}
_HASH_CACHE: dict[tuple[str, int, int, int, int, int], str] = {}
_MAINTENANCE_MARKERS = (
    Path("/var/lib/bdencode/install-transactions/active"),
    Path("/var/lib/bdencode/update-runtime/active.json"),
    Path("/var/lib/bdencode/apt-transactions/active"),
)


def _maintenance_active() -> bool:
    """Return true while an installer or toolchain transaction is published."""

    return any(os.path.lexists(marker) for marker in _MAINTENANCE_MARKERS)


def _sd_notify(message: str) -> bool:
    """Send one systemd notification without requiring libsystemd bindings.

    ``NOTIFY_SOCKET`` is absent during ordinary CLI and Windows execution, in
    which case notification is intentionally a no-op.  Removing it before the
    send also prevents media-tool child processes from inheriting the service
    manager's notification endpoint.
    """

    address = os.environ.pop("NOTIFY_SOCKET", None)
    if not address:
        return False
    if address.startswith("@"):
        # systemd exposes Linux abstract namespace sockets with a leading '@',
        # while Python's AF_UNIX API represents the leading NUL explicitly.
        address = "\0" + address[1:]
    elif not address.startswith("/"):
        raise RuntimeError("NOTIFY_SOCKET must be an absolute or abstract path")

    payload = message.encode("utf-8")
    unix_family = getattr(socket, "AF_UNIX", None)
    if unix_family is None:
        raise RuntimeError("systemd notification requires Unix-domain sockets")
    notifier = socket.socket(unix_family, socket.SOCK_DGRAM)
    try:
        notifier.connect(address)
        sent = notifier.send(payload)
        if sent != len(payload):
            raise OSError("short write to systemd notification socket")
    finally:
        notifier.close()
    return True


def sha256_file(path: Path) -> str:
    """Hash immutable stage inputs once per observed filesystem generation.

    A BD reference can be tens of gigabytes.  Re-reading it for every audio-QC
    sub-command would turn marker validation into more I/O than the analysis.
    Size, inode, modification and change times invalidate the process cache.
    """
    resolved = path.resolve(strict=True)
    stat = resolved.stat()
    key = (
        str(resolved),
        stat.st_dev,
        stat.st_ino,
        stat.st_size,
        stat.st_mtime_ns,
        stat.st_ctime_ns,
    )
    value = _HASH_CACHE.get(key)
    if value is None:
        value = _uncached_sha256_file(resolved)
        _HASH_CACHE[key] = value
    return value


def _quick_source_fingerprint(path: Path) -> dict[str, Any]:
    """Detect source clip replacement without a second full-disc read.

    The durable reference remux itself receives a full SHA-256.  For marker
    invalidation we combine file identity/timestamps with hashes of the first
    and last MiB, which catches ordinary replacement/corruption while avoiding
    another complete read of every multi-gigabyte M2TS before remuxing.
    """

    resolved = path.resolve(strict=True)
    details = resolved.stat()
    digest = hashlib.sha256()
    with resolved.open("rb") as handle:
        digest.update(handle.read(1024 * 1024))
        if details.st_size > 1024 * 1024:
            handle.seek(max(0, details.st_size - 1024 * 1024))
            digest.update(handle.read(1024 * 1024))
    return {
        "path": str(resolved),
        "size_bytes": details.st_size,
        "mtime_ns": details.st_mtime_ns,
        "edge_sha256": digest.hexdigest(),
    }


def _remember_sha256(path: Path, digest: str) -> None:
    """Record a digest computed while the file was written (see ``sha256_file``)."""

    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("a SHA-256 digest is 64 lowercase hex digits")
    resolved = path.resolve(strict=True)
    stat = resolved.stat()
    _HASH_CACHE[
        (
            str(resolved),
            stat.st_dev,
            stat.st_ino,
            stat.st_size,
            stat.st_mtime_ns,
            stat.st_ctime_ns,
        )
    ] = digest


def _mkv_reference_inputs(scan: DiscScan, playlist_id: str) -> dict[str, Any]:
    """The reference-copy marker inputs of an MKV source.

    The quick fingerprint (size, modification time, first and last MiB) makes
    a replaced or modified source invalidate the copy.
    """

    try:
        source = _quick_source_fingerprint(scan.source)
    except OSError as exc:
        raise ReviewRequired(
            f"the MKV source cannot be read: {exc}",
            details={"code": "mkv_source_unreadable"},
        ) from exc
    return {
        "source_kind": SOURCE_KIND_MKV,
        "scan_fingerprint": scan.fingerprint,
        "playlist_id": playlist_id,
        "source_file": source,
    }


def _first_packet_seconds(timeline_path: Path) -> Decimal | None:
    """The first packet time of a packet-timeline probe (None: no packets)."""

    document = json.loads(timeline_path.read_text(encoding="utf-8"))
    packets = document.get("packets") if isinstance(document, dict) else None
    if not isinstance(packets, list):
        raise ValueError(f"{timeline_path.name} has no packets array")
    for packet in packets:
        if not isinstance(packet, dict):
            continue
        for field in ("pts_time", "dts_time"):
            value = packet.get(field)
            if value not in (None, "", "N/A"):
                return Decimal(str(value))
    return None


def _subtitle_shift_ms(
    reference_timeline: Path, final_timeline: Path, origin_seconds: Decimal
) -> Decimal | None:
    """How far the final MKV moved a copied subtitle against the reference.

    The final timeline is the reference's rebased onto the common zero, so the
    first event must land at ``reference first - origin``.  None when either
    side has no packets (the packet-count check covers that).
    """

    reference_first = _first_packet_seconds(reference_timeline)
    final_first = _first_packet_seconds(final_timeline)
    if reference_first is None or final_first is None:
        return None
    return (final_first - (reference_first - origin_seconds)) * Decimal(1000)


def _track_timestamp_tolerance_ms(scan: DiscScan) -> int:
    """How far a copied track's PTS/DTS may move between sidecar and final MKV.

    A sync-shifted remux compares two independently quantized Matroska
    timelines; normalizing both origins can differ by up to two 1 ms ticks.
    An MKV remux source carries the timeline of a foreign muxer, which may
    truncate rather than round (The Florist 2026 remux: DTS 10.67 ms packets,
    mkvmerge re-timed 18 of 552 502 by 3 ms, payload identical): one more
    tick.  Packet counts, sizes, payloads and durations stay exact, so a
    dropped or moved packet is still caught.
    """

    return 3 if scan.is_mkv else 2


def _playlist_source_snapshot(scan: DiscScan, playlist_id: str) -> list[dict[str, Any]]:
    if scan.is_mkv:
        # The remux file is the title's only source file.
        scan.playlist(playlist_id)
        return [_quick_source_fingerprint(scan.source)]
    playlist = scan.playlist(playlist_id)
    clip_ids = tuple(dict.fromkeys(segment.clip_id for segment in playlist.segments))
    result: list[dict[str, Any]] = []
    for clip_id in clip_ids:
        candidate = scan.source / "BDMV" / "STREAM" / f"{clip_id}.m2ts"
        if not candidate.is_file():
            candidate = scan.source / "BDMV" / "STREAM" / f"{clip_id}.M2TS"
        if not candidate.is_file():
            raise ReviewRequired(
                f"selected playlist clip is missing: {clip_id}",
                details={"playlist_id": playlist.playlist_id, "clip_id": clip_id},
            )
        result.append(_quick_source_fingerprint(candidate))
    return result


class Runner(Protocol):
    def run(
        self,
        argv: Sequence[str | os.PathLike[str]],
        *,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
        stdout_path: Path | None = None,
        stderr_path: Path | None = None,
        check: bool = True,
        ok_returncodes: Sequence[int] = (0,),
        timeout: float | None = None,
    ) -> Any: ...

    def run_pipeline(
        self,
        commands: Sequence[Sequence[str | os.PathLike[str]]],
        *,
        cwd: Path | None = None,
        stderr_paths: Sequence[Path] | None = None,
        timeout: float | None = None,
        check: bool = True,
        stderr_line_callback: Callable[[str], None] | None = None,
        interrupt_requested: Callable[[], bool] | None = None,
        poll_interval: float = 0.2,
    ) -> Any: ...


FIT_LOG_NAME = "external-fit.txt"


def fit_base_mux_command(
    output: Path,
    reference: Path,
    file_tracks: Sequence[Mapping[str, Any]],
    playlist: PlaylistCandidate,
    tracks: Sequence[TrackSelection],
    *,
    title: str,
) -> tuple[list[str], list[str], list[str]]:
    """Copy the finished file, leaving out the omitted tracks.

    The scan and mkvmerge list a kind's tracks in the same file order, so the
    ordinal joins them.  Also returns the FFmpeg maps of the kept streams in the
    original and in the new file, to prove them unchanged.
    """

    selections = {item.stream_id: item for item in tracks}
    command = ["mkvmerge", "--output", str(output), "--title", title]
    reference_maps = ["0:v:0"]
    kept_maps = ["0:v:0"]
    for kind, flag, none, letter, streams in (
        ("audio", "--audio-tracks", "--no-audio", "a", playlist.audio_streams),
        ("subtitles", "--subtitle-tracks", "--no-subtitles", "s", playlist.subtitle_streams),
    ):
        identified = [item for item in file_tracks if item.get("type") == kind]
        if len(identified) != len(streams):
            raise ReviewRequired(
                "the MKV's tracks changed since it was read", details={"code": "fit_tracks_changed"}
            )
        kept = []
        for ordinal, (item, stream) in enumerate(zip(identified, streams)):
            chosen = selections.get(stream.id)
            if chosen is not None and chosen.action is TrackAction.OMIT:
                continue
            reference_maps.append(f"0:{letter}:{ordinal}")
            kept_maps.append(f"0:{letter}:{len(kept)}")
            kept.append(str(item["id"]))
            if chosen is not None and chosen.default is not None:
                command.extend(("--default-track-flag", f"{item['id']}:{'yes' if chosen.default else 'no'}"))
            if chosen is not None and chosen.language:
                command.extend(("--language", f"{item['id']}:{chosen.language}"))
        command.extend((flag, ",".join(kept)) if kept else (none,))
    command.append(str(reference))
    return command, reference_maps, kept_maps


def external_final_audio_order(
    base_tracks: Sequence[Mapping[str, Any]], audio: Sequence[Mapping[str, Any]]
) -> list[int | tuple[str, int]]:
    """Final audio order: base ordinals, and ``("external", index)`` at their positions."""

    order: list[int | tuple[str, int]] = list(
        range(sum(1 for item in base_tracks if item.get("type") == "audio"))
    )
    indexed = sorted(enumerate(audio), key=lambda pair: (pair[1]["track"].position, pair[0]))
    for index, item in indexed:
        order.insert(min(item["track"].position, len(order)), ("external", index))
    return order


def external_merge_command(
    output: Path,
    base: Path,
    base_tracks: Sequence[Mapping[str, Any]],
    audio: Sequence[Mapping[str, Any]],
    subtitles: Sequence[Mapping[str, Any]],
    *,
    title: str,
    video_start_seconds: float,
) -> list[str]:
    """Base file first (input 0), then one input per fitted track, in the release's order."""

    sync_ms = int(round(video_start_seconds * 1000))
    command = ["mkvmerge", "--output", str(output), "--title", title]
    takes_default = any(item["track"].default for item in audio)
    base_audio = [item for item in base_tracks if item.get("type") == "audio"]
    if takes_default:
        for item in base_audio:
            command.extend(("--default-track-flag", f"{item['id']}:no"))
    command.append(str(base))
    for item in audio:
        track = item["track"]
        report = item["report"]
        command.extend(("--language", f"0:{track.language}"))
        command.extend(("--default-track-flag", f"0:{'yes' if track.default else 'no'}"))
        command.extend(("--track-name", f"0:{track.name or external_track_name(track, report)}"))
        command.extend(("--sync", f"0:{sync_ms + int(report.get('sync_ms') or 0)}"))
        command.extend(("--no-video", "--no-subtitles", "--no-chapters", str(item["path"])))
    for item in subtitles:
        subtitle = item["subtitle"]
        command.extend(("--language", f"0:{subtitle.language}"))
        command.extend(("--default-track-flag", f"0:{'yes' if subtitle.default else 'no'}"))
        command.extend(("--forced-display-flag", f"0:{'yes' if subtitle.forced else 'no'}"))
        command.extend(("--sub-charset", "0:UTF-8"))
        if subtitle.name:
            command.extend(("--track-name", f"0:{subtitle.name}"))
        command.extend(("--sync", f"0:{sync_ms}"))
        command.append(str(item["path"]))
    entries: list[str] = []
    video = [item for item in base_tracks if item.get("type") == "video"]
    entries.extend(f"0:{item['id']}" for item in video)
    for entry in external_final_audio_order(base_tracks, audio):
        if isinstance(entry, int):
            entries.append(f"0:{base_audio[entry]['id']}")
        else:
            entries.append(f"{entry[1] + 1}:0")
    entries.extend(f"0:{item['id']}" for item in base_tracks if item.get("type") == "subtitles")
    entries.extend(f"{len(audio) + 1 + index}:0" for index in range(len(subtitles)))
    command.extend(("--track-order", ",".join(entries)))
    return command


def external_track_name(track: external_spec.ExternalTrack, report: Mapping[str, Any]) -> str:
    encoding = report.get("encoding") or {}
    codec = str(encoding.get("codec") or report.get("codec") or "").upper().replace("AC3", "DD")
    channels = {1: "1.0", 2: "2.0", 6: "5.1"}.get(int(report.get("channels") or 0), "")
    language = {
        "hu": "Hungarian", "hun": "Hungarian", "en": "English", "eng": "English",
        "de": "German", "deu": "German", "ger": "German",
    }.get(track.language, track.language)
    return " ".join(part for part in (language, codec, channels) if part)


class ReviewRequired(RuntimeError):
    """The worker cannot safely infer a material operator decision."""

    def __init__(
        self, message: str, *, details: Mapping[str, Any] | None = None
    ) -> None:
        super().__init__(message)
        self.details = dict(details or {})


@dataclass(frozen=True, slots=True)
class ParsedSelection:
    playlist_id: str
    angle: int
    settings: EncoderSettings
    crop: VapourSynthCrop
    temporal_filter: TemporalFilter
    tracks: tuple[TrackSelection, ...]
    output_name: str
    upload_images: bool
    image_upload_provider: str
    dual_type_match: bool = False
    upload_image_set: str = "all"
    schema_version: int = 2
    auto_crf: AutoCrfConfig = AutoCrfConfig()
    dynamic_hdr: DynamicHdrMode = DynamicHdrMode.DISCARD
    # Whose rules the job follows: none, aither or ncore (see tracker_policy).
    tracker_profile: TrackerProfile = TrackerProfile.NONE
    # "remux": no video encode; settings, crop and filter are then unused
    # placeholders and ``remux`` holds the remux options.
    mode: str = "encode"
    remux: RemuxOptions | None = None
    external_sources: tuple[external_spec.ExternalSource, ...] = ()
    # Where the name strays from the release-name rules: shown as advice,
    # never a stop (4.2.1); the operator may name a release their own way.
    name_warnings: tuple[str, ...] = ()

    @property
    def dub_may_be_default(self) -> bool:
        return self.tracker_profile is TrackerProfile.NCORE

    @property
    def is_remux(self) -> bool:
        return self.mode == "remux"

    @property
    def is_fit(self) -> bool:
        """Tracks fitted to a finished MKV: nothing is encoded or demuxed."""

        return self.mode == "fit"


@dataclass(frozen=True, slots=True)
class RemuxOptions:
    """What a remux selection adds: the guide's global tags."""

    imdb: str | None = None
    tmdb: str | None = None


def _is_remux_job(job: Job) -> bool:
    return isinstance(job.selection, Mapping) and job.selection.get("mode") == "remux"


def _is_fit_job(job: Job) -> bool:
    return isinstance(job.selection, Mapping) and job.selection.get("mode") == "fit"


# The states a remux runs through its own stages; UPLOADING is shared.
_REMUX_STAGES = frozenset(
    {JobState.READY, JobState.ENCODING, JobState.MUXING, JobState.QC, JobState.COMPARISON}
)


@dataclass(frozen=True, slots=True)
class JobPaths:
    root: Path
    work: Path
    logs: Path
    analysis: Path
    comparison: Path
    stages: Path
    scan_json: Path
    plan_json: Path
    manifest_json: Path
    language_json: Path
    timeline_json: Path
    reference: Path
    script: Path
    encoded_video: Path
    muxed_output: Path
    live: Path

    @classmethod
    def create(cls, settings: Settings, job_id: str) -> "JobPaths":
        jobs_root = settings.jobs_root
        if os.path.lexists(jobs_root) and _unsafe_directory_link(jobs_root):
            raise ReviewRequired("jobs root cannot be a symbolic link or junction")
        jobs_root.mkdir(mode=0o750, parents=True, exist_ok=True)
        resolved_jobs_root = jobs_root.resolve(strict=True)
        resolved_data_root = settings.data_root.resolve(strict=True)
        if resolved_jobs_root.parent != resolved_data_root:
            raise ReviewRequired("jobs root escaped the configured data root")

        root = settings.job_root(job_id)
        if os.path.lexists(root) and _unsafe_directory_link(root):
            raise ReviewRequired("job root cannot be a symbolic link or junction")
        root.mkdir(mode=0o750, parents=False, exist_ok=True)
        resolved_root = root.resolve(strict=True)
        if resolved_root.parent != resolved_jobs_root or resolved_root.name != job_id:
            raise ReviewRequired("job root escaped the configured jobs root")
        value = cls(
            root=root,
            work=root / "work",
            logs=root / "logs",
            analysis=root / "analysis",
            comparison=root / "comparison",
            stages=root / ".stages",
            scan_json=root / "scan.json",
            plan_json=root / "encode-plan.json",
            manifest_json=root / "manifest.json",
            language_json=root / "analysis" / "language-inference.json",
            timeline_json=root / "analysis" / "timeline-plan.json",
            reference=root / "work" / "reference.mkv",
            script=root / "work" / "reference.vpy",
            encoded_video=root / "work" / "video-encoded.mkv",
            muxed_output=root / "work" / "output.mkv",
            live=root / ".live",
        )
        for path in (
            value.work,
            value.logs,
            value.analysis,
            value.comparison,
            value.stages,
            value.live,
        ):
            if os.path.lexists(path) and _unsafe_directory_link(path):
                raise ReviewRequired(
                    f"job workspace member cannot be a link: {path.name}"
                )
            path.mkdir(mode=0o750, parents=True, exist_ok=True)
            if path.resolve(strict=True).parent != resolved_root:
                raise ReviewRequired(
                    f"job workspace member escaped its job root: {path.name}"
                )
        resolved_work = value.work.resolve(strict=True)
        for path in (value.work / "tracks", value.work / "cache"):
            if os.path.lexists(path) and _unsafe_directory_link(path):
                raise ReviewRequired(f"job work member cannot be a link: {path.name}")
            path.mkdir(mode=0o750, parents=False, exist_ok=True)
            if path.resolve(strict=True).parent != resolved_work:
                raise ReviewRequired(
                    f"job work member escaped its work root: {path.name}"
                )
        return value


def _current_comparison_pngs(paths: JobPaths, *, prune: bool = False) -> list[Path]:
    try:
        resolved_job_root = paths.root.resolve(strict=True)
    except OSError as exc:
        raise RuntimeError("comparison job root cannot be resolved safely") from exc
    for evidence_root in (paths.comparison, paths.analysis):
        try:
            resolved_evidence_root = evidence_root.resolve(strict=True)
        except OSError as exc:
            raise RuntimeError("comparison evidence root cannot be resolved") from exc
        if (
            _unsafe_directory_link(evidence_root)
            or resolved_evidence_root.parent != resolved_job_root
        ):
            raise RuntimeError(
                "comparison evidence root cannot be a link or escape its job root"
            )
    video_manifest = paths.comparison / "video-comparison.json"
    audio_manifest = paths.analysis / "audio-comparison.json"
    try:
        video_document = json.loads(video_manifest.read_text(encoding="utf-8"))
        audio_document = json.loads(audio_manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("comparison manifests are missing or invalid") from exc

    selected: dict[Path, None] = {}

    def include(root: Path, name: object, expected_sha256: object) -> None:
        if not isinstance(name, str) or Path(name).name != name:
            raise RuntimeError("comparison manifest contains an unsafe image name")
        path = root / name
        if path.suffix.casefold() != ".png" or not path.is_file():
            raise RuntimeError(f"comparison image is missing or invalid: {name}")
        try:
            resolved_root = root.resolve(strict=True)
            resolved_path = path.resolve(strict=True)
        except OSError as exc:
            raise RuntimeError(
                f"comparison image cannot be resolved safely: {name}"
            ) from exc
        if _unsafe_directory_link(path) or resolved_path.parent != resolved_root:
            raise RuntimeError(
                f"comparison image cannot be a link or escape its evidence root: {name}"
            )
        if (
            not isinstance(expected_sha256, str)
            or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256)
            or sha256_file(path) != expected_sha256
        ):
            raise RuntimeError(f"comparison image hash differs from manifest: {name}")
        selected[path] = None

    pairs = video_document.get("pairs", [])
    if not isinstance(pairs, list):
        raise RuntimeError("video comparison manifest has no pairs array")
    for pair in pairs:
        if not isinstance(pair, Mapping):
            raise RuntimeError("video comparison pair is invalid")
        for key, hash_key in (
            ("reference_png", "reference_sha256"),
            ("encode_png", "encode_sha256"),
            ("reference_sdr_png", "reference_sdr_sha256"),
            ("encode_sdr_png", "encode_sdr_sha256"),
            ("screenshot_png", "screenshot_sha256"),
        ):
            if key in pair:
                include(paths.comparison, pair[key], pair.get(hash_key))

    tracks = audio_document.get("tracks", [])
    if not isinstance(tracks, list):
        raise RuntimeError("audio comparison manifest has no tracks array")
    for track in tracks:
        if not isinstance(track, Mapping):
            raise RuntimeError("audio comparison track is invalid")
        include(
            paths.analysis,
            track.get("source_spectrum"),
            track.get("source_spectrum_sha256"),
        )
        include(
            paths.analysis,
            track.get("encode_spectrum"),
            track.get("encode_spectrum_sha256"),
        )

    if prune:
        for candidate in (
            *paths.comparison.glob("*.png"),
            *paths.analysis.glob("*-spectrum.png"),
        ):
            if candidate not in selected:
                candidate.unlink()
    return sorted(selected, key=lambda item: (str(item.parent), item.name))


def _current_video_metric_sidecars(paths: JobPaths) -> list[Path]:
    """Resolve only hash-pinned metric evidence named by the v2 manifests."""

    manifest_path = paths.comparison / "video-comparison.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("video comparison manifest is missing or invalid") from exc
    if not isinstance(manifest, Mapping):
        raise RuntimeError("video comparison manifest must be a JSON object")

    root = paths.comparison.resolve(strict=True)
    selected: dict[Path, None] = {}

    def include(
        record: object,
        *,
        description: str,
        allowed_suffix: str,
    ) -> Path:
        if not isinstance(record, Mapping):
            raise RuntimeError(f"{description} record is missing or invalid")
        name = record.get("path")
        expected_sha256 = record.get("sha256")
        if (
            not isinstance(name, str)
            or Path(name).name != name
            or not name.casefold().endswith(allowed_suffix)
        ):
            raise RuntimeError(f"{description} has an unsafe path")
        if not isinstance(expected_sha256, str) or not re.fullmatch(
            r"[0-9a-f]{64}", expected_sha256
        ):
            raise RuntimeError(f"{description} has an invalid SHA-256")
        path = paths.comparison / name
        if not path.is_file() or _unsafe_directory_link(path):
            raise RuntimeError(f"{description} is missing or is a link")
        try:
            resolved = path.resolve(strict=True)
        except OSError as exc:
            raise RuntimeError(f"{description} cannot be resolved safely") from exc
        if resolved.parent != root or sha256_file(resolved) != expected_sha256:
            raise RuntimeError(f"{description} differs from its manifest")
        selected[resolved] = None
        return resolved

    metrics_path = include(
        manifest.get("metrics"),
        description="video metrics manifest",
        allowed_suffix=".json",
    )
    try:
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("video metrics document is invalid") from exc
    if not isinstance(metrics, Mapping) or not isinstance(metrics.get("samples"), list):
        raise RuntimeError("video metrics document has no samples array")
    for index, sample in enumerate(metrics["samples"], start=1):
        if not isinstance(sample, Mapping):
            raise RuntimeError(f"video metric sample {index} is invalid")
        include(
            sample.get("ssim_stats"),
            description=f"video metric sample {index} SSIM stats",
            allowed_suffix=".ssim.log",
        )
        include(
            sample.get("psnr_stats"),
            description=f"video metric sample {index} PSNR stats",
            allowed_suffix=".psnr.log",
        )
    if manifest.get("vmaf") is not None:
        # Comparisons from 2.9 on also carry the sampled VMAF of the final file.
        include(
            manifest.get("vmaf"),
            description="sampled VMAF report",
            allowed_suffix=".json",
        )
    return sorted(selected, key=lambda item: item.name)


_FORBIDDEN_PUBLIC_JSON_KEYS = {
    "api_key",
    "argv",
    "authorization",
    "command",
    "cpu",
    "credential",
    "delete_url",
    "encoder_settings",
    "job_id",
    "job_uuid",
    "host",
    "hostname",
    "local_path",
    "password",
    "platform",
    "machine",
    "secret",
    "settings",
    "settings_json",
    "source_path",
    "source_fingerprint",
    "scan_fingerprint",
    "stderr_path",
    "stdout_path",
    "token",
    "tools",
    "capabilities",
    "binary_versions",
    "os",
    "user_name",
    "userhash",
    "username",
}


def _assert_public_sidecar_safe(path: Path, *, wine_drives: bool = False) -> None:
    """Reject private fields/values before any public upload or package copy.

    ``wine_drives``: the eac3to log (and a BBCode quoting it) may name the
    Wine drives bdencode-eac3to maps (eac3to on C:, the disc on S:).
    """

    try:
        assert_public_metadata_absent(path, wine_drives=wine_drives)
        if path.suffix.casefold() != ".json":
            return
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ReviewRequired(
            f"public sidecar contains unsafe metadata: {path.name}",
            details={"sidecar": path.name},
        ) from exc

    def visit(value: object) -> None:
        if isinstance(value, Mapping):
            for key, nested in value.items():
                normalized = str(key).strip().casefold().replace("-", "_")
                if normalized in _FORBIDDEN_PUBLIC_JSON_KEYS:
                    raise ReviewRequired(
                        f"public sidecar contains a private field: {path.name}",
                        details={"sidecar": path.name, "field": normalized},
                    )
                visit(nested)
        elif isinstance(value, list):
            for nested in value:
                visit(nested)
        elif isinstance(value, str) and sanitize_text(value, public=True) != value:
            raise ReviewRequired(
                f"public sidecar contains private host metadata: {path.name}",
                details={"sidecar": path.name},
            )

    visit(document)


def _has_current_visual_annotations(document: Mapping[str, Any]) -> bool:
    annotation = document.get("visual_annotation")
    pairs = document.get("pairs")
    schema_version = document.get("schema_version")
    if (
        not isinstance(schema_version, int)
        or schema_version < 4
        or not isinstance(annotation, Mapping)
        or annotation.get("schema_version") != 1
        or annotation.get("metrics_use_unannotated_pixels") is not True
        or annotation.get("metrics_use_native_yuv_planes") is not True
        or not isinstance(pairs, list)
        or not pairs
    ):
        return False
    for pair in pairs:
        if not isinstance(pair, Mapping):
            return False
        visual_label = pair.get("visual_label")
        if (
            not isinstance(visual_label, Mapping)
            or visual_label.get("reference_role") != "SOURCE"
            or visual_label.get("encode_role") != "ENCODE"
            or visual_label.get("frame_index") != pair.get("presentation_index")
            or visual_label.get("frame_index_base") != 0
            or visual_label.get("frame_type") != pair.get("category")
        ):
            return False
    return True


def _json_hash(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _selection_hash(selection: Any) -> str:
    """What the title's own stages depend on.  External sources are left out, so
    approving a fit or changing its pitch does not repeat the language check."""

    if isinstance(selection, Mapping):
        return _json_hash({k: v for k, v in selection.items() if k != "external_sources"})
    return _json_hash(selection)


def _parse_external_sources(raw: Mapping[str, Any]) -> tuple[external_spec.ExternalSource, ...]:
    try:
        return external_spec.parse_external_sources(raw.get("external_sources"))
    except external_spec.ExternalSpecError as exc:
        raise ReviewRequired(str(exc), details={"code": "external_source_invalid"}) from exc


def _remove_owned_completed_child(completed: Path, child: Path) -> None:
    """Remove one exact BDEncode-owned package child without following links."""

    if child.parent != completed:
        raise RuntimeError("completed-package cleanup target is not a direct child")
    if not os.path.lexists(child):
        return
    if child.is_symlink():
        raise ReviewRequired(
            f"completed package contains an unsafe symbolic link: {child.name}"
        )
    completed_root = completed.resolve(strict=True)
    resolved = child.resolve(strict=True)
    if resolved.parent != completed_root:
        raise ReviewRequired(
            f"completed-package cleanup target escaped its release directory: {child.name}"
        )
    if resolved.is_dir():
        safe_tree_usage(resolved)
        shutil.rmtree(resolved)
    else:
        resolved.unlink()


def _replace_public_sidecars(
    *,
    completed: Path,
    comparison_source: Path,
    analysis_source: Path,
    comparison_files: Sequence[Path],
    analysis_files: Sequence[Path],
    expected_files: Mapping[Path, tuple[int, str]],
) -> None:
    """Atomically refresh the v2 public evidence trees from explicit allowlists."""

    comparison_stage = completed / ".comparison.partial"
    analysis_stage = completed / ".analysis.partial"
    for stage in (comparison_stage, analysis_stage):
        _remove_owned_completed_child(completed, stage)
        _ensure_contained_directory(
            stage,
            root=completed,
            description="public evidence staging directory",
        )
    comparison_root = comparison_source.resolve(strict=True)
    analysis_root = analysis_source.resolve(strict=True)
    copied: set[Path] = set()

    def copy_pinned(
        source: Path,
        *,
        source_root: Path,
        stage_root: Path,
        evidence_kind: str,
    ) -> None:
        if _unsafe_directory_link(source):
            raise ReviewRequired(
                f"public {evidence_kind} sidecar cannot be a symbolic link"
            )
        resolved = source.resolve(strict=True)
        if not resolved.is_file() or resolved.parent != source_root:
            raise ReviewRequired(
                f"public {evidence_kind} sidecar escaped its source directory"
            )
        if resolved in copied:
            raise ReviewRequired(f"public {evidence_kind} sidecar is duplicated")
        pin = expected_files.get(resolved)
        if pin is None:
            raise ReviewRequired(f"public {evidence_kind} sidecar is not hash-pinned")
        expected_size, expected_sha256 = pin
        if (
            resolved.stat().st_size != expected_size
            or sha256_file(resolved) != expected_sha256
        ):
            raise ReviewRequired(
                f"public {evidence_kind} sidecar changed after validation"
            )
        staged = stage_root / resolved.name
        shutil.copy2(resolved, staged)
        if (
            _unsafe_directory_link(staged)
            or not staged.is_file()
            or staged.stat().st_size != expected_size
            or sha256_file(staged) != expected_sha256
        ):
            raise ReviewRequired(
                f"public {evidence_kind} sidecar changed during package staging"
            )
        copied.add(resolved)

    try:
        for source in comparison_files:
            copy_pinned(
                source,
                source_root=comparison_root,
                stage_root=comparison_stage,
                evidence_kind="comparison",
            )
        for source in analysis_files:
            copy_pinned(
                source,
                source_root=analysis_root,
                stage_root=analysis_stage,
                evidence_kind="analysis",
            )
        if copied != set(expected_files):
            raise ReviewRequired(
                "public evidence allowlist omitted or added a hash-pinned sidecar"
            )
    except Exception:
        for stage in (comparison_stage, analysis_stage):
            _remove_owned_completed_child(completed, stage)
        raise

    for legacy in (
        completed / "logs",
        completed / "manifest.json",
        completed / "comparison",
        completed / "analysis",
    ):
        _remove_owned_completed_child(completed, legacy)
    os.replace(comparison_stage, completed / "comparison")
    os.replace(analysis_stage, completed / "analysis")


def _unsafe_directory_link(path: Path) -> bool:
    is_junction = getattr(path, "is_junction", None)
    return path.is_symlink() or bool(is_junction and is_junction())


def _ensure_contained_directory(
    path: Path,
    *,
    root: Path,
    description: str,
) -> Path:
    """Create one workspace directory without following links outside ``root``."""

    try:
        if _unsafe_directory_link(root):
            raise ValueError("containment root is a link")
        resolved_root = root.resolve(strict=True)
        if not resolved_root.is_dir():
            raise ValueError("containment root is not a directory")
        relative = path.relative_to(root)
        if not relative.parts or any(
            part in {"", ".", ".."} for part in relative.parts
        ):
            raise ValueError("unsafe relative directory path")

        current = root
        resolved_parent = resolved_root
        for part in relative.parts:
            current = current / part
            if os.path.lexists(current) and _unsafe_directory_link(current):
                raise ValueError("directory component is a link")
            current.mkdir(mode=0o750, parents=False, exist_ok=True)
            if _unsafe_directory_link(current) or not current.is_dir():
                raise ValueError("directory component is not a real directory")
            resolved_current = current.resolve(strict=True)
            if resolved_current.parent != resolved_parent:
                raise ValueError("directory component escaped its parent")
            resolved_parent = resolved_current
    except (OSError, ValueError) as exc:
        raise ReviewRequired(
            f"{description} cannot be created safely inside its workspace"
        ) from exc
    return path


SAMPLE_DIRECTORY = "Sample"
# nCore: a sample is mandatory above 2 GB; at least a minute, UHD at least 200 MB.
NCORE_SAMPLE_THRESHOLD_BYTES = 2 * 1024**3
NCORE_UHD_SAMPLE_BYTES = 200 * 1024**2


def sample_window(
    *, duration_seconds: float, size_bytes: int, uhd: bool
) -> tuple[float, float] | None:
    """``(start, length)`` of an nCore sample in seconds, or ``None`` if not needed.

    A minute (UHD: enough for 200 MB, at most four minutes) from about five
    minutes in, clear of the opening logos and the end credits.
    """

    if size_bytes <= NCORE_SAMPLE_THRESHOLD_BYTES or duration_seconds < 240:
        return None
    length = 60.0
    if uhd:
        bytes_per_second = size_bytes / duration_seconds
        length = min(240.0, max(length, math.ceil(NCORE_UHD_SAMPLE_BYTES / bytes_per_second) + 5.0))
    start = 300.0 if duration_seconds > 1200 else round(duration_seconds * 0.25)
    start = max(0.0, min(start, duration_seconds - length - 60.0))
    return start, length


def _clock(seconds: float) -> str:
    whole = int(seconds)
    return f"{whole // 3600:02d}:{whole % 3600 // 60:02d}:{whole % 60:02d}"


def _validate_completed_members(
    completed: Path, output_name: str, *, allow_legacy: bool
) -> None:
    allowed = {
        ".bdencode-owner.json",
        f"{output_name}.mkv",
        "comparison",
        "analysis",
        SAMPLE_DIRECTORY,
    }
    if allow_legacy:
        allowed.update(
            {
                "logs",
                "manifest.json",
                f".{output_name}.mkv.partial",
                ".comparison.partial",
                ".analysis.partial",
            }
        )
    unexpected = sorted(
        item.name for item in completed.iterdir() if item.name not in allowed
    )
    if unexpected:
        raise ReviewRequired(
            "completed directory contains files outside the v2 public allowlist",
            details={"unexpected": unexpected},
        )
    for item in completed.iterdir():
        if _unsafe_directory_link(item):
            raise ReviewRequired(
                f"completed package member cannot be a link: {item.name}"
            )
        if item.name in {"comparison", "analysis", "logs", SAMPLE_DIRECTORY}:
            if not item.is_dir():
                raise ReviewRequired(
                    f"completed package member must be a directory: {item.name}"
                )
            if item.name == SAMPLE_DIRECTORY:
                members = sorted(child.name for child in item.iterdir())
                if members != [f"{output_name}.sample.mkv"] or _unsafe_directory_link(
                    item / members[0]
                ):
                    raise ReviewRequired(
                        "the Sample directory may hold only the release's own sample",
                        details={"members": members},
                    )
        elif not item.is_file():
            raise ReviewRequired(
                f"completed package member must be a regular file: {item.name}"
            )


def _output_records(outputs: Iterable[Path]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for output in outputs:
        resolved = output.resolve(strict=True)
        if not resolved.is_file():
            raise RuntimeError(f"stage output is not a regular file: {output}")
        records.append(
            {
                "path": str(resolved),
                "size_bytes": resolved.stat().st_size,
                "sha256": sha256_file(resolved),
            }
        )
    return records


def _recorded_output_sha256(marker: Path, output: Path) -> str | None:
    """Reuse a durable upstream stage digest without re-reading a huge MKV.

    The producer stage wrote this digest after creating the immutable output.
    A size/path check prevents accidentally borrowing a digest for another
    file; callers fall back to a fresh SHA-256 when the record is unavailable.
    """

    try:
        document = json.loads(marker.read_text(encoding="utf-8"))
        if document.get("schema_version") != 1 or not output.is_file():
            return None
        expected_path = str(output.resolve(strict=True))
        output_stat = output.stat()
        expected_size = output_stat.st_size
        completed_at = float(document["completed_at_epoch"])
        # A normal producer writes its checkpoint only after the output digest
        # has been calculated.  A later mtime therefore means the file changed
        # in place and the recorded SHA-256 can no longer describe it, even if
        # its path and byte size remained identical.
        if output_stat.st_mtime > completed_at:
            return None
        for item in document.get("outputs", []):
            if (
                item.get("path") == expected_path
                and item.get("size_bytes") == expected_size
                and isinstance(item.get("sha256"), str)
                and re.fullmatch(r"[0-9a-f]{64}", item["sha256"])
            ):
                return item["sha256"]
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None
    return None


def _assert_stage_outputs_current(
    marker: Path,
    outputs: Sequence[Path],
    *,
    stage_name: str,
) -> dict[Path, tuple[int, str]]:
    """Freshly hash outputs and return immutable size/SHA pins from the marker."""

    verified: dict[Path, tuple[int, str]] = {}
    try:
        document = json.loads(marker.read_text(encoding="utf-8"))
        if document.get("schema_version") != 1:
            raise ValueError("unsupported marker schema")
        raw_records = document.get("outputs")
        if not isinstance(raw_records, list):
            raise ValueError("marker has no output records")
        records = {
            str(record.get("path")): record
            for record in raw_records
            if isinstance(record, Mapping)
        }
        for output in outputs:
            resolved = output.resolve(strict=True)
            if _unsafe_directory_link(output) or not resolved.is_file():
                raise ValueError(f"unsafe output: {output.name}")
            record = records.get(str(resolved))
            if not isinstance(record, Mapping):
                raise ValueError(f"unrecorded output: {output.name}")
            expected_sha256 = record.get("sha256")
            expected_size = record.get("size_bytes")
            if (
                not isinstance(expected_sha256, str)
                or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256)
                or isinstance(expected_size, bool)
                or not isinstance(expected_size, int)
                or expected_size < 0
                or resolved.stat().st_size != expected_size
                or sha256_file(resolved) != expected_sha256
            ):
                raise ValueError(f"changed output: {output.name}")
            verified[resolved] = (expected_size, expected_sha256)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ReviewRequired(
            f"{stage_name} evidence changed after its validated checkpoint",
            details={"stage": stage_name, "action": "rerun_qc"},
        ) from exc
    return verified


def _valid_stage(
    marker: Path, inputs: Mapping[str, Any], outputs: Sequence[Path]
) -> bool:
    if not marker.is_file():
        return False
    try:
        document = json.loads(marker.read_text(encoding="utf-8"))
        if document.get("schema_version") != 1:
            return False
        if document.get("input_sha256") != _json_hash(inputs):
            return False
        expected = {str(path.resolve(strict=False)): path for path in outputs}
        recorded = {item["path"]: item for item in document.get("outputs", [])}
        if set(expected) != set(recorded):
            return False
        for name, path in expected.items():
            item = recorded[name]
            if not path.is_file() or path.stat().st_size != item["size_bytes"]:
                return False
            if sha256_file(path) != item["sha256"]:
                return False
        return True
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return False


def _outcome_from_report(
    document: Mapping[str, Any], config: AutoCrfConfig
) -> CrfSearchOutcome:
    """Rebuild the search outcome from a hash-pinned automatic CRF report."""

    probes = tuple(
        CrfProbe(crf=float(item["crf"]), score=float(item["score"]))
        for item in document["probes"]
    )
    chosen = document["chosen_crf"]
    return CrfSearchOutcome(
        status=str(document["status"]),
        chosen_crf=None if chosen is None else float(chosen),
        chosen_score=(
            None
            if document.get("chosen_score") is None
            else float(document["chosen_score"])
        ),
        probes=probes,
        monotonic=bool(document.get("monotonic", True)),
        target_vmaf=config.target_vmaf,
        mode=str(document.get("mode", "vmaf")),
        target_size_gb=config.target_size_gb,
    )


def _write_stage(
    marker: Path, inputs: Mapping[str, Any], outputs: Sequence[Path]
) -> None:
    atomic_write_json(
        marker,
        {
            "schema_version": 1,
            "input_sha256": _json_hash(inputs),
            "outputs": _output_records(outputs),
            "completed_at_epoch": time.time(),
        },
    )


def _activate_source_log_generation(
    *,
    logs_root: Path,
    generation_record: Path,
    remux_marker: Path,
    generation: str,
) -> None:
    """Keep sticky source diagnostics scoped to one remux input generation."""

    if not re.fullmatch(r"[0-9a-f]{64}", generation):
        raise ValueError("source log generation must be a SHA-256 digest")
    previous: str | None = None
    if generation_record.is_file():
        document = json.loads(generation_record.read_text(encoding="utf-8"))
        candidate = document.get("generation")
        if not isinstance(candidate, str) or not re.fullmatch(
            r"[0-9a-f]{64}", candidate
        ):
            raise ValueError("source log generation record is invalid")
        previous = candidate
    elif remux_marker.is_file():
        try:
            marker_document = json.loads(remux_marker.read_text(encoding="utf-8"))
            candidate = marker_document.get("input_sha256")
            if isinstance(candidate, str) and re.fullmatch(r"[0-9a-f]{64}", candidate):
                previous = candidate
        except json.JSONDecodeError:
            # The normal stage validator will reject a malformed marker. With
            # no trustworthy generation, retaining current logs is fail-closed.
            previous = None

    if previous is not None and previous != generation:
        history_root = _ensure_contained_directory(
            logs_root / "source-history" / previous,
            root=logs_root,
            description="source diagnostic history directory",
        )
        current_logs = sorted(
            {
                *logs_root.glob("reference-remux*.log"),
                *logs_root.glob("source-video-integrity*.log"),
            },
            key=lambda item: item.name,
        )
        for source in current_logs:
            destination = history_root / source.name
            suffix = 1
            while destination.exists():
                destination = history_root / (
                    f"{source.stem}.generation-{suffix:02d}{source.suffix}"
                )
                suffix += 1
            source.replace(destination)

    atomic_write_json(
        generation_record,
        {"schema_version": 1, "generation": generation},
    )


def _read_text_or_empty(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _mkvmerge_identify_warnings(report: Path) -> list[str]:
    """The warnings of ``mkvmerge --identify`` (JSON) and its stderr."""

    messages: list[str] = []
    try:
        document = json.loads(report.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        document = None
    if isinstance(document, dict):
        for key in ("warnings", "errors"):
            values = document.get(key)
            if isinstance(values, list):
                messages.extend(str(item) for item in values if str(item).strip())
    messages.extend(
        mkvmerge_warning_lines(
            _read_text_or_empty(report.with_suffix(report.suffix + ".stderr"))
        )
    )
    return messages


def _public_diagnostic_summary(
    diagnostics: Iterable[MediaDiagnostic],
) -> list[dict[str, object]]:
    """Return event-safe diagnostic counts without raw paths or log lines."""

    return [
        {
            "code": item.code,
            "category": item.category.value,
            "severity": item.severity.value,
            "count": item.count,
            "requires_review": item.requires_review,
        }
        for item in diagnostics
    ]


def _sticky_source_diagnostics(
    diagnostics: Iterable[MediaDiagnostic],
) -> tuple[MediaDiagnostic, ...]:
    """Retain only corruption/decode failures across same-input retries."""

    return tuple(
        item
        for item in diagnostics
        if item.requires_review
        and item.category
        in {
            DiagnosticCategory.SOURCE_CORRUPTION,
            DiagnosticCategory.DECODE_INTEGRITY,
        }
    )


def _clip_join_moments(report: Mapping[str, Any]) -> list[float]:
    """The join times of a verified ``clip-joins.json``, and the title end
    when the strict decode there was clean too."""

    moments = [float(item) for item in report.get("joins") or []]
    title_end = report.get("title_end")
    if (
        report.get("title_end_verified") is True
        and isinstance(title_end, (int, float))
        and not isinstance(title_end, bool)
    ):
        moments.append(float(title_end))
    return moments


def _content_kind(job: Job) -> ContentKind:
    return ContentKind(job.content_type.value.lower())


def _language_from_dict(value: Mapping[str, Any] | None) -> LanguageDecision | None:
    if not value:
        return None
    evidence = tuple(
        LanguageEvidence(
            source=LanguageSource(item["source"]),
            raw_code=item.get("raw_code"),
            normalized_code=item.get("normalized_code"),
            confidence=float(item.get("confidence", 1.0)),
            detail=item.get("detail"),
        )
        for item in value.get("evidence", [])
    )
    return LanguageDecision(
        iso639_2t=value.get("iso639_2t"),
        bcp47=value.get("bcp47"),
        status=LanguageStatus(value.get("status", "unknown")),
        confidence=float(value.get("confidence", 0.0)),
        evidence=evidence,
        needs_review=bool(value.get("needs_review", False)),
        overridden_by=value.get("overridden_by"),
    )


def _scan_from_dict(value: Mapping[str, Any]) -> DiscScan:
    playlists: list[PlaylistCandidate] = []
    for raw_playlist in value.get("playlists", []):
        streams: list[MediaStream] = []
        for raw_stream in raw_playlist.get("streams", []):
            raw_video = raw_stream.get("video")
            video = None
            if raw_video:
                raw_static = raw_video.get("hdr10_static") or {}
                video = VideoProperties(
                    codec=VideoCodec(raw_video.get("codec", "unknown")),
                    width=raw_video.get("width"),
                    height=raw_video.get("height"),
                    frame_rate=raw_video.get("frame_rate"),
                    field_order=raw_video.get("field_order"),
                    bit_depth=raw_video.get("bit_depth"),
                    pixel_format=raw_video.get("pixel_format"),
                    color_primaries=raw_video.get("color_primaries"),
                    color_transfer=raw_video.get("color_transfer"),
                    color_matrix=raw_video.get("color_matrix"),
                    color_range=raw_video.get("color_range"),
                    chroma_location=raw_video.get("chroma_location"),
                    hdr10=bool(raw_video.get("hdr10", False)),
                    hdr10_static=HdrStaticMetadata(
                        mastering_display=raw_static.get("mastering_display"),
                        max_cll=raw_static.get("max_cll"),
                        max_fall=raw_static.get("max_fall"),
                    ),
                    dolby_vision=bool(raw_video.get("dolby_vision", False)),
                    dolby_vision_profile=raw_video.get("dolby_vision_profile"),
                    dolby_vision_el_stream_id=raw_video.get("dolby_vision_el_stream_id"),
                    dolby_vision_el_type=raw_video.get("dolby_vision_el_type"),
                    hdr10_base_layer=bool(raw_video.get("hdr10_base_layer", False)),
                    hdr10_plus=bool(raw_video.get("hdr10_plus", False)),
                    three_d=bool(raw_video.get("three_d", False)),
                )
            streams.append(
                MediaStream(
                    id=str(raw_stream["id"]),
                    index=int(raw_stream["index"]),
                    pid=raw_stream.get("pid"),
                    kind=StreamKind(raw_stream["kind"]),
                    codec=str(raw_stream.get("codec", "unknown")),
                    codec_profile=raw_stream.get("codec_profile"),
                    language=_language_from_dict(raw_stream.get("language")),
                    title=raw_stream.get("title"),
                    channels=raw_stream.get("channels"),
                    channel_layout=raw_stream.get("channel_layout"),
                    sample_rate=raw_stream.get("sample_rate"),
                    bit_depth=raw_stream.get("bit_depth"),
                    default=bool(raw_stream.get("default", False)),
                    forced=bool(raw_stream.get("forced", False)),
                    roles=tuple(
                        TrackRole(item) for item in raw_stream.get("roles", [])
                    ),
                    object_audio=bool(raw_stream.get("object_audio", False)),
                    video=video,
                    text_subtitle=bool(raw_stream.get("text_subtitle", False)),
                )
            )
        segments = tuple(
            PlaylistSegment(
                clip_id=str(item["clip_id"]),
                in_time_seconds=float(item["in_time_seconds"]),
                out_time_seconds=float(item["out_time_seconds"]),
                relative_start_seconds=float(item.get("relative_start_seconds", 0.0)),
                seamless=bool(item.get("seamless", True)),
                angle=int(item.get("angle", 1)),
            )
            for item in raw_playlist.get("segments", [])
        )
        playlists.append(
            PlaylistCandidate(
                playlist_id=str(raw_playlist["playlist_id"]).zfill(5),
                duration_seconds=float(raw_playlist.get("duration_seconds", 0.0)),
                chapters=tuple(
                    float(item) for item in raw_playlist.get("chapters", [])
                ),
                segments=segments,
                streams=tuple(streams),
                angle_count=int(raw_playlist.get("angle_count", 1)),
                seamless_branching=bool(raw_playlist.get("seamless_branching", False)),
                edition_group=raw_playlist.get("edition_group"),
                edition_label=raw_playlist.get("edition_label"),
                episode_number=raw_playlist.get("episode_number"),
                recommended=bool(raw_playlist.get("recommended", False)),
            )
        )
    raw_capabilities = value.get("capabilities", {})
    return DiscScan(
        source=Path(str(value["source"])),
        disc_kind=DiscKind(value["disc_kind"]),
        content_kind=ContentKind(value["content_kind"]),
        playlists=tuple(playlists),
        capabilities=ToolCapabilities(
            ffprobe=raw_capabilities.get("ffprobe"),
            mediainfo=raw_capabilities.get("mediainfo"),
            mkvmerge=raw_capabilities.get("mkvmerge"),
            libbluray_json=raw_capabilities.get("libbluray_json"),
            ffprobe_bluray=bool(raw_capabilities.get("ffprobe_bluray", False)),
        ),
        fingerprint=str(value["fingerprint"]),
        warnings=tuple(str(item) for item in value.get("warnings", [])),
        source_kind=str(value.get("source_kind", SOURCE_KIND_DISC)),
    )


def _nested_encoder_overrides(raw: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(raw)
    if "color" in result and isinstance(result["color"], Mapping):
        result["color"] = ColorMetadata(**result["color"])
    if "vbv" in result and isinstance(result["vbv"], Mapping):
        result["vbv"] = VbvSettings(**result["vbv"])
    if "hdr10" in result and isinstance(result["hdr10"], Mapping):
        result["hdr10"] = Hdr10Metadata(**result["hdr10"])
    return result


def _resolve_hdr10(
    scan: DiscScan,
    playlist_id: str,
    manual: Hdr10Metadata | None,
) -> Hdr10Metadata:
    playlist = scan.playlist(playlist_id)
    if not playlist.video_streams:
        raise ReviewRequired("the selected playlist has no video stream")
    video = playlist.video_streams[0].video
    assert video is not None
    source_hdr10 = video.hdr10 or str(video.color_transfer or "").casefold() == (
        "smpte2084"
    )
    if not source_hdr10:
        return manual or Hdr10Metadata()
    static = video.hdr10_static
    if manual is None:
        if not static.complete:
            raise ReviewRequired(
                "HDR10 static mastering metadata is incomplete; enter verified values",
                details={
                    "code": "source_hdr10_metadata_incomplete",
                    "playlist_id": playlist.playlist_id,
                    "confirmation_field": "selection.video.settings.hdr10",
                },
            )
        try:
            return Hdr10Metadata(
                enabled=True,
                mastering_display=static.mastering_display,
                max_cll=static.max_cll,
                max_fall=static.max_fall,
            )
        except (TypeError, ValueError) as exc:
            raise ReviewRequired(
                f"scanned HDR10 static metadata is invalid: {exc}",
                details={
                    "code": "invalid_source_hdr10_metadata",
                    "playlist_id": playlist.playlist_id,
                },
            ) from exc

    conflicts: dict[str, dict[str, object]] = {}
    if not manual.enabled:
        conflicts["enabled"] = {"required": True, "selected": manual.enabled}
    if not manual.hdr10_opt:
        conflicts["hdr10_opt"] = {
            "required": True,
            "selected": manual.hdr10_opt,
        }
    for field_name in ("mastering_display", "max_cll", "max_fall"):
        scanned_value = getattr(static, field_name)
        selected_value = getattr(manual, field_name)
        if scanned_value is not None and selected_value != scanned_value:
            conflicts[field_name] = {
                "scanned": scanned_value,
                "selected": selected_value,
            }
    if conflicts:
        raise ReviewRequired(
            "manual HDR10 metadata conflicts with the selected source",
            details={
                "code": "source_hdr10_metadata_conflict",
                "playlist_id": playlist.playlist_id,
                "confirmation_field": "selection.video.settings.hdr10",
                "scan_complete": static.complete,
                "conflicts": conflicts,
            },
        )
    return manual


def _derive_color(
    scan: DiscScan,
    playlist_id: str,
    confirmation: Mapping[str, Any] | None = None,
) -> ColorMetadata:
    playlist = scan.playlist(playlist_id)
    if not playlist.video_streams:
        raise ReviewRequired("the selected playlist has no video stream")
    video = playlist.video_streams[0].video
    assert video is not None
    scanned = {
        "primaries": video.color_primaries,
        "transfer": video.color_transfer,
        "matrix": video.color_matrix,
        "range": video.color_range,
        "chroma_location": video.chroma_location,
    }
    range_aliases = {
        "tv": "limited",
        "mpeg": "limited",
        "limited": "limited",
        "pc": "full",
        "jpeg": "full",
        "full": "full",
    }
    matrix_aliases = {"bt2020ncl": "bt2020nc", "bt2020cl": "bt2020c"}
    normalized_scanned = {
        "primaries": (
            str(video.color_primaries).casefold() if video.color_primaries else None
        ),
        "transfer": (
            str(video.color_transfer).casefold() if video.color_transfer else None
        ),
        "matrix": (
            matrix_aliases.get(
                str(video.color_matrix).casefold(),
                str(video.color_matrix).casefold(),
            )
            if video.color_matrix
            else None
        ),
        "range": (
            range_aliases.get(str(video.color_range).casefold())
            if video.color_range
            else None
        ),
        "chroma_location": (
            str(video.chroma_location).casefold() if video.chroma_location else None
        ),
    }
    blocking_fields = [
        name for name in ("primaries", "transfer", "matrix") if not scanned[name]
    ]
    if video.color_range and normalized_scanned["range"] is None:
        raise ReviewRequired(
            "source color range is unsupported",
            details={
                "code": "unsupported_source_color_metadata",
                "playlist_id": playlist.playlist_id,
                "field": "range",
                "value": video.color_range,
            },
        )
    if blocking_fields and confirmation is None:
        missing_source_fields = [name for name, value in scanned.items() if not value]
        suggested = None
        suggestion_reason = None
        if (
            scan.disc_kind is DiscKind.BD
            and video.codec in {VideoCodec.AVC, VideoCodec.VC1, VideoCodec.MPEG2}
            and (video.width or 0) >= 1280
            and (video.height or 0) >= 720
            and video.bit_depth == 8
            and not video.hdr10
        ):
            suggested = {
                "primaries": normalized_scanned["primaries"] or "bt709",
                "transfer": normalized_scanned["transfer"] or "bt709",
                "matrix": normalized_scanned["matrix"] or "bt709",
                "range": normalized_scanned["range"] or "limited",
                "chroma_location": normalized_scanned["chroma_location"] or "left",
            }
            suggestion_reason = "HD SDR Blu-ray source profile"
        raise ReviewRequired(
            t(
                "A forr\u00e1s sz\u00ednmetaadata hi\u00e1nyos. Ellen\u0151rizd \u00e9s er\u0151s\u00edtsd meg "
                "a sz\u00ednteret a vide\u00f3be\u00e1ll\u00edt\u00e1sokn\u00e1l.",
                "The source colour metadata is incomplete. Check and confirm "
                "the colour space in the video settings.",
            ),
            details={
                "code": "source_color_confirmation_required",
                "playlist_id": playlist.playlist_id,
                "missing_fields": missing_source_fields,
                "blocking_fields": blocking_fields,
                "detected": normalized_scanned,
                "safe_defaults": {
                    name: value
                    for name, value in {
                        "range": "limited",
                        "chroma_location": "left",
                    }.items()
                    if not scanned[name]
                },
                "confirmation_field": "selection.video.settings.color",
                "suggested": suggested,
                "suggestion_reason": suggestion_reason,
            },
        )

    if confirmation is not None:
        expected_fields = {
            "primaries",
            "transfer",
            "matrix",
            "range",
            "chroma_location",
        }
        if set(confirmation) != expected_fields:
            missing_confirmation = sorted(expected_fields - set(confirmation))
            unknown_confirmation = sorted(set(confirmation) - expected_fields)
            raise ReviewRequired(
                t(
                    "A sz\u00ednmetaadat meger\u0151s\u00edt\u00e9se nem teljes.",
                    "The colour metadata confirmation is incomplete.",
                ),
                details={
                    "code": "invalid_source_color_confirmation",
                    "playlist_id": playlist.playlist_id,
                    "confirmation_field": "selection.video.settings.color",
                    "missing_fields": missing_confirmation,
                    "unknown_fields": unknown_confirmation,
                },
            )
        try:
            confirmed = ColorMetadata(
                primaries=str(confirmation["primaries"]).casefold(),
                transfer=str(confirmation["transfer"]).casefold(),
                matrix=matrix_aliases.get(
                    str(confirmation["matrix"]).casefold(),
                    str(confirmation["matrix"]).casefold(),
                ),
                range=range_aliases.get(
                    str(confirmation["range"]).casefold(),
                    str(confirmation["range"]).casefold(),
                ),
                chroma_location=str(confirmation["chroma_location"]).casefold(),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ReviewRequired(
                t(
                    f"A sz\u00ednmetaadat meger\u0151s\u00edt\u00e9se \u00e9rv\u00e9nytelen: {exc}",
                    f"The colour metadata confirmation is invalid: {exc}",
                ),
                details={
                    "code": "invalid_source_color_confirmation",
                    "playlist_id": playlist.playlist_id,
                    "confirmation_field": "selection.video.settings.color",
                },
            ) from exc
        conflicts = {
            name: {"scanned": value, "confirmed": getattr(confirmed, name)}
            for name, value in normalized_scanned.items()
            if value is not None and value != getattr(confirmed, name)
        }
        if conflicts:
            raise ReviewRequired(
                "changing color metadata without an explicit color conversion is not allowed",
                details={
                    "code": "source_color_confirmation_conflict",
                    "playlist_id": playlist.playlist_id,
                    "confirmation_field": "selection.video.settings.color",
                    "conflicts": conflicts,
                },
            )
        return confirmed

    # Blu-ray 4:2:0 video is studio/limited range with left chroma siting when
    # those VUI fields are omitted. Primaries/transfer/matrix are never guessed.
    color_range = range_aliases.get(str(video.color_range or "limited").casefold())
    if color_range is None:
        raise ReviewRequired(
            "source color range is unsupported",
            details={"value": video.color_range},
        )
    try:
        return ColorMetadata(
            primaries=str(video.color_primaries).casefold(),
            transfer=str(video.color_transfer).casefold(),
            matrix=matrix_aliases.get(
                str(video.color_matrix).casefold(),
                str(video.color_matrix).casefold(),
            ),
            range=color_range,
            chroma_location=str(video.chroma_location or "left").casefold(),
        )
    except ValueError as exc:
        raise ReviewRequired(f"source color metadata is unsupported: {exc}") from exc


def parse_selection(
    job: Job,
    scan: DiscScan,
    *,
    crop_override: VapourSynthCrop | None = None,
) -> ParsedSelection:
    raw = job.selection
    if not isinstance(raw, Mapping):
        raise ReviewRequired("selection JSON is missing")
    mode = raw.get("mode", "encode")
    if mode == "remux":
        return parse_remux_selection(job, scan)
    if mode == "fit":
        return parse_fit_selection(job, scan)
    if mode != "encode":
        raise ReviewRequired("selection mode must be encode, remux or fit")
    unknown = set(raw) - _SELECTION_KEYS - {"mode"}
    if "remux" in raw:
        raise ReviewRequired("remux options belong to a remux selection")
    if unknown:
        raise ReviewRequired(
            "unknown selection field(s): " + ", ".join(sorted(unknown))
        )
    schema_version = raw.get("schema_version", 1)
    if isinstance(schema_version, bool) or schema_version not in {1, 2}:
        raise ReviewRequired("selection schema_version must be 1 or 2")
    try:
        tracker_profile = TrackerProfile(raw.get("tracker_profile", "none"))
    except ValueError as exc:
        raise ReviewRequired("tracker_profile must be none, aither or ncore") from exc
    # ``video`` is the canonical home of crop/filter/settings in docs/API.md.
    # Top-level crop/filter and ``overrides`` remain accepted for queued jobs
    # created by the first backend prototype.
    required = {
        "playlist_id",
        "angle",
        "video",
        "tracks",
        "output_name",
        "upload_images",
    }
    missing = required - set(raw)
    if missing:
        raise ReviewRequired(
            "missing selection field(s): " + ", ".join(sorted(missing))
        )

    playlist_text = str(raw["playlist_id"]).lower().removesuffix(".mpls")
    if not playlist_text.isdigit():
        raise ReviewRequired("playlist_id must be numeric")
    playlist_id = playlist_text.zfill(5)
    try:
        playlist = scan.playlist(playlist_id)
    except KeyError as exc:
        raise ReviewRequired(str(exc)) from exc
    angle = raw["angle"]
    if (
        isinstance(angle, bool)
        or not isinstance(angle, int)
        or not 1 <= angle <= playlist.angle_count
    ):
        raise ReviewRequired(f"angle must be between 1 and {playlist.angle_count}")

    video_raw = raw["video"]
    allowed_video = {
        "detail_level",
        "settings",
        "overrides",
        "crop",
        "temporal_filter",
        "auto_crf",
        "dynamic_hdr",
    }
    if not isinstance(video_raw, Mapping) or set(video_raw) - allowed_video:
        raise ReviewRequired(
            "video may contain detail_level, settings, crop, temporal_filter, "
            "auto_crf and dynamic_hdr"
        )
    try:
        auto_crf = AutoCrfConfig.from_mapping(video_raw.get("auto_crf"))
    except CrfSearchError as exc:
        raise ReviewRequired(f"invalid automatic CRF configuration: {exc}") from exc
    try:
        dynamic_hdr = parse_mode(video_raw.get("dynamic_hdr"))
    except DynamicHdrError as exc:
        raise ReviewRequired(
            f"invalid dynamic HDR policy: {exc}",
            details={"code": f"dynamic_hdr_{exc.code}"},
        ) from exc
    try:
        detail_level = DetailLevel(video_raw.get("detail_level", "beginner"))
    except ValueError as exc:
        raise ReviewRequired("invalid video detail_level") from exc
    if "settings" in video_raw and "overrides" in video_raw:
        if video_raw["settings"] != video_raw["overrides"]:
            raise ReviewRequired("video.settings and legacy video.overrides conflict")
    overrides_raw = video_raw.get("settings", video_raw.get("overrides", {}))
    if not isinstance(overrides_raw, Mapping):
        raise ReviewRequired("video.settings must be an object")
    # V1 stored the value sent to x264.  x264's Psy-RD path then applied -2
    # internally, so an authored 0 described an effective -2.  V2 stores the
    # effective value and compensates only when building the encoder command.
    overrides_raw = dict(overrides_raw)
    if (
        schema_version == 1
        and overrides_raw.get("chroma_qp_offset") == 0
        and scan.disc_kind is DiscKind.BD
    ):
        overrides_raw["chroma_qp_offset"] = -2
    encoder = VideoEncoder.X265 if scan.disc_kind is DiscKind.UHD else VideoEncoder.X264
    if "encoder" in overrides_raw:
        try:
            selected_encoder = VideoEncoder(overrides_raw["encoder"])
        except (TypeError, ValueError) as exc:
            raise ReviewRequired("invalid video encoder") from exc
        if selected_encoder is not encoder:
            raise ReviewRequired(
                f"{scan.disc_kind.value.upper()} output must use {encoder.value}"
            )
    manual_color = overrides_raw.get("color")
    if manual_color is not None and not isinstance(manual_color, Mapping):
        raise ReviewRequired(
            "video.settings.color must be an object",
            details={
                "code": "invalid_source_color_confirmation",
                "playlist_id": playlist_id,
                "confirmation_field": "selection.video.settings.color",
            },
        )
    source_color = _derive_color(scan, playlist_id, manual_color)
    hdr10 = None
    if encoder is VideoEncoder.X265:
        manual_hdr = overrides_raw.get("hdr10")
        if manual_hdr is not None:
            if not isinstance(manual_hdr, Mapping):
                raise ReviewRequired("video.settings.hdr10 must be an object")
            try:
                hdr10 = Hdr10Metadata(**manual_hdr)
            except (TypeError, ValueError) as exc:
                raise ReviewRequired(f"invalid manual HDR10 metadata: {exc}") from exc
        hdr10 = _resolve_hdr10(scan, playlist_id, hdr10)
    try:
        encoder_overrides = _nested_encoder_overrides(overrides_raw)
        selected_color = encoder_overrides.get("color")
        if selected_color is not None and selected_color != source_color:
            raise ReviewRequired(
                "changing color metadata without an explicit color conversion is not allowed"
            )
        settings = recommended_profile(
            encoder,
            detail_level=detail_level,
            content_type=job.content_type.value.lower(),
            hdr10=hdr10,
            color=source_color,
            overrides=encoder_overrides,
        )
    except ReviewRequired:
        raise
    except (TypeError, ValueError) as exc:
        raise ReviewRequired(f"invalid video settings: {exc}") from exc
    if settings.bframes < 1:
        raise ReviewRequired(
            "B-frames must remain enabled for mandatory I/P/B comparison"
        )

    if "crop" in raw and "crop" in video_raw and raw["crop"] != video_raw["crop"]:
        raise ReviewRequired("top-level crop and video.crop conflict")
    crop_raw = video_raw.get("crop", raw.get("crop"))
    if not isinstance(crop_raw, Mapping) or set(crop_raw) != {
        "left",
        "top",
        "right",
        "bottom",
    }:
        raise ReviewRequired("video.crop must contain left, top, right and bottom")
    if any(type(value) is not int for value in crop_raw.values()):
        raise ReviewRequired("video.crop values must be non-boolean integers")
    try:
        requested_crop = VapourSynthCrop(**dict(crop_raw))
    except (TypeError, ValueError) as exc:
        raise ReviewRequired(f"invalid crop: {exc}") from exc
    crop = requested_crop if crop_override is None else crop_override
    if (
        "temporal_filter" in raw
        and "temporal_filter" in video_raw
        and raw["temporal_filter"] != video_raw["temporal_filter"]
    ):
        raise ReviewRequired(
            "top-level temporal_filter and video.temporal_filter conflict"
        )
    temporal_raw = video_raw.get("temporal_filter", raw.get("temporal_filter"))
    try:
        temporal_filter = TemporalFilter(temporal_raw)
    except (TypeError, ValueError) as exc:
        raise ReviewRequired("invalid temporal_filter") from exc

    source_video_streams = playlist.video_streams
    if not source_video_streams or source_video_streams[0].video is None:
        raise ReviewRequired("the selected playlist has no video stream")
    source_video = source_video_streams[0].video
    missing_geometry = [
        name
        for name, value in {
            "width": source_video.width,
            "height": source_video.height,
            "frame_rate": source_video.frame_rate,
        }.items()
        if value is None
    ]
    if missing_geometry:
        raise ReviewRequired(
            "source video geometry/timing is incomplete: " + ", ".join(missing_geometry)
        )
    output_width = (
        source_video.width - crop.left - crop.right
        if source_video.width is not None
        else None
    )
    output_height = (
        source_video.height - crop.top - crop.bottom
        if source_video.height is not None
        else None
    )
    try:
        settings, _video_policy = source_adapted_settings(
            settings,
            width=output_width,
            height=output_height,
            frame_rate=_vapoursynth_output_frame_rate(
                source_video.frame_rate, temporal_filter
            ),
            tracker=tracker_profile.value,
        )
    except ValueError as exc:
        raise ReviewRequired(
            f"video compatibility policy rejected the selection: {exc}"
        ) from exc

    tracks_raw = raw["tracks"]
    if not isinstance(tracks_raw, list):
        raise ReviewRequired("tracks must be an array")
    tracks: list[TrackSelection] = []
    allowed_track = {
        "stream_id",
        "action",
        "language",
        "name",
        "default",
        "forced",
        "subtitle_kind",
        "order",
    }
    for number, item in enumerate(tracks_raw):
        if not isinstance(item, Mapping) or set(item) - allowed_track:
            raise ReviewRequired(f"tracks[{number}] contains unknown fields")
        if "stream_id" not in item or "action" not in item:
            raise ReviewRequired(f"tracks[{number}] needs stream_id and action")
        action_value = str(item["action"]).lower()
        order_value = item.get("order", number)
        if type(order_value) is not int or order_value < 0:
            raise ReviewRequired(
                f"invalid tracks[{number}]: order must be a non-negative integer"
            )
        try:
            tracks.append(
                TrackSelection(
                    stream_id=str(item["stream_id"]),
                    action=TrackAction(action_value),
                    language=item.get("language"),
                    name=item.get("name"),
                    default=item.get("default"),
                    forced=item.get("forced"),
                    subtitle_kind=item.get("subtitle_kind"),
                    order=order_value,
                )
            )
        except (TypeError, ValueError) as exc:
            raise ReviewRequired(f"invalid tracks[{number}]: {exc}") from exc

    stream_by_id = {stream.id: stream for stream in playlist.streams}
    if len({item.stream_id for item in tracks}) != len(tracks):
        raise ReviewRequired("each playlist track may be selected only once")
    for number, item in enumerate(tracks):
        stream = stream_by_id.get(item.stream_id)
        if stream is None:
            raise ReviewRequired(f"tracks[{number}] references an unknown stream")
        if stream.kind is StreamKind.AUDIO:
            if item.forced:
                raise ReviewRequired(f"tracks[{number}] audio cannot be forced")
            if item.subtitle_kind is not None:
                raise ReviewRequired(
                    f"tracks[{number}] audio cannot declare subtitle_kind"
                )
        elif stream.kind is StreamKind.SUBTITLE and item.action is not TrackAction.OMIT:
            if item.subtitle_kind not in {"full", "forced"}:
                raise ReviewRequired(
                    f"tracks[{number}] retained subtitle needs an explicit full/forced classification"
                )
            expected_forced = item.subtitle_kind == "forced"
            if item.forced is not None and item.forced is not expected_forced:
                raise ReviewRequired(
                    f"tracks[{number}] subtitle forced flag conflicts with subtitle_kind"
                )

    output_name = str(raw["output_name"]).removesuffix(".mkv")
    if not _SAFE_OUTPUT_RE.fullmatch(output_name) or output_name in {".", ".."}:
        raise ReviewRequired("output_name contains unsafe characters")
    if not isinstance(raw["upload_images"], bool):
        raise ReviewRequired("upload_images must be boolean")
    image_upload_provider = str(raw.get("image_upload_provider", "auto")).lower()
    if image_upload_provider not in {"auto", "imgbb", "catbox", "freeimage"}:
        raise ReviewRequired(
            "image_upload_provider must be auto, imgbb, catbox or freeimage"
        )
    upload_image_set = str(raw.get("upload_image_set", "all")).lower()
    if upload_image_set not in UPLOAD_IMAGE_SETS:
        raise ReviewRequired("upload_image_set must be all, sdr or native")
    dual_type = raw.get("dual_type_match", True)
    if not isinstance(dual_type, bool):
        raise ReviewRequired("dual_type_match must be boolean")
    parsed = ParsedSelection(
        external_sources=_parse_external_sources(raw),
        playlist_id=playlist_id,
        angle=angle,
        settings=settings,
        crop=crop,
        temporal_filter=temporal_filter,
        tracks=tuple(tracks),
        output_name=output_name,
        upload_images=raw["upload_images"],
        image_upload_provider=image_upload_provider,
        upload_image_set=upload_image_set,
        dual_type_match=dual_type,
        schema_version=2,
        auto_crf=auto_crf,
        dynamic_hdr=dynamic_hdr,
        tracker_profile=tracker_profile,
    )
    try:
        dynamic_plan = resolve_selection_dynamic_hdr(scan, parsed)
    except DynamicHdrError as exc:
        raise ReviewRequired(
            f"dynamic HDR retention is not possible: {exc}",
            details={"code": f"dynamic_hdr_{exc.code}"},
        ) from exc
    return replace(
        parsed,
        name_warnings=_release_name_warnings(
            output_name,
            facts=release_facts(
                encoder=encoder,
                playlist=playlist,
                tracks=tracks,
                settings=settings,
                dynamic_plan=dynamic_plan,
            ),
        ),
    )


def parse_fit_selection(job: Job, scan: DiscScan) -> ParsedSelection:
    """Tracks from other sources added to a finished encode or remux.

    The file's own streams stay byte for byte; a track can only be kept or left
    out.  A disc cannot take new tracks: fitting to one is a remux with external
    sources.
    """

    raw = job.selection
    assert isinstance(raw, Mapping)
    unknown = set(raw) - _FIT_SELECTION_KEYS
    if unknown:
        raise ReviewRequired("unknown selection field(s): " + ", ".join(sorted(unknown)))
    missing = {"playlist_id", "tracks", "output_name", "upload_images"} - set(raw)
    if missing:
        raise ReviewRequired("missing selection field(s): " + ", ".join(sorted(missing)))
    if not scan.is_mkv:
        raise ReviewRequired(
            "tracks are fitted to a finished MKV; for a disc choose a remux with external sources",
            details={"code": "fit_needs_mkv"},
        )
    external = _parse_external_sources(raw)
    if not external:
        raise ReviewRequired(
            "choose at least one external track or subtitle to fit",
            details={"code": "fit_needs_external"},
        )
    try:
        tracker_profile = TrackerProfile(raw.get("tracker_profile", "none"))
        playlist = scan.playlist(str(raw["playlist_id"]))
    except (KeyError, ValueError) as exc:
        raise ReviewRequired(str(exc)) from exc
    videos = playlist.video_streams
    if not videos or videos[0].video is None or videos[0].video.frame_rate is None:
        raise ReviewRequired(
            "the MKV's video has no known frame rate", details={"code": "fit_video"}
        )
    if not isinstance(raw["tracks"], list):
        raise ReviewRequired("tracks must be an array")
    allowed_track = {"stream_id", "action", "language", "name", "default", "forced", "subtitle_kind", "order"}
    streams = {stream.id: stream for stream in playlist.streams}
    tracks: list[TrackSelection] = []
    for number, item in enumerate(raw["tracks"]):
        if not isinstance(item, Mapping) or set(item) - allowed_track or "stream_id" not in item:
            raise ReviewRequired(f"tracks[{number}] is not valid")
        try:
            selected = TrackSelection(
                stream_id=str(item["stream_id"]),
                action=TrackAction(str(item.get("action", "copy")).lower()),
                language=item.get("language"),
                name=item.get("name"),
                default=item.get("default"),
                forced=item.get("forced"),
                subtitle_kind=item.get("subtitle_kind"),
                order=item.get("order", number),
            )
        except (TypeError, ValueError) as exc:
            raise ReviewRequired(f"invalid tracks[{number}]: {exc}") from exc
        stream = streams.get(selected.stream_id)
        if stream is None or stream.kind is StreamKind.VIDEO:
            raise ReviewRequired(f"tracks[{number}] does not name an audio or subtitle track")
        if selected.action not in {TrackAction.COPY, TrackAction.OMIT}:
            raise ReviewRequired(
                f"tracks[{number}]: a finished file's tracks are kept or left out, not converted",
                details={"code": "fit_track_action"},
            )
        tracks.append(selected)
    output_name = str(raw["output_name"]).removesuffix(".mkv")
    if not _SAFE_OUTPUT_RE.fullmatch(output_name) or output_name in {".", ".."}:
        raise ReviewRequired("output_name contains unsafe characters")
    if not isinstance(raw["upload_images"], bool):
        raise ReviewRequired("upload_images must be boolean")
    image_upload_provider = str(raw.get("image_upload_provider", "auto")).lower()
    if image_upload_provider not in {"auto", "imgbb", "catbox", "freeimage"}:
        raise ReviewRequired("image_upload_provider must be auto, imgbb, catbox or freeimage")
    return ParsedSelection(
        external_sources=external,
        playlist_id=playlist.playlist_id,
        angle=1,
        settings=recommended_profile(VideoEncoder.X264, content_type=job.content_type.value.lower()),
        crop=VapourSynthCrop(left=0, top=0, right=0, bottom=0),
        temporal_filter=TemporalFilter.PROGRESSIVE,
        tracks=tuple(tracks),
        output_name=output_name,
        upload_images=raw["upload_images"],
        image_upload_provider=image_upload_provider,
        upload_image_set="all",
        dual_type_match=False,
        schema_version=2,
        tracker_profile=tracker_profile,
        mode="fit",
    )


def parse_remux_selection(job: Job, scan: DiscScan) -> ParsedSelection:
    """An Aither-style remux: the disc's own streams, nothing re-encoded.

    The video is always kept; audio is copied untouched except Blu-ray LPCM,
    which becomes FLAC as the guide demands; PGS subtitles are copied or
    left out.  Everything an encode needs (settings, crop, filter) is a
    placeholder the remux stages never read.
    """

    raw = job.selection
    assert isinstance(raw, Mapping)
    unknown = set(raw) - _REMUX_SELECTION_KEYS
    if unknown:
        raise ReviewRequired(
            "unknown remux selection field(s): " + ", ".join(sorted(unknown))
        )
    if raw.get("schema_version", 2) != 2 or isinstance(raw.get("schema_version"), bool):
        raise ReviewRequired("remux selection schema_version must be 2")
    missing = {"playlist_id", "angle", "tracks", "output_name", "upload_images"} - set(raw)
    if missing:
        raise ReviewRequired("missing selection field(s): " + ", ".join(sorted(missing)))
    try:
        tracker_profile = TrackerProfile(raw.get("tracker_profile", "none"))
    except ValueError as exc:
        raise ReviewRequired("tracker_profile must be none, aither or ncore") from exc
    if scan.is_mkv:
        raise ReviewRequired(
            "a remux is made from the disc itself, not from an existing MKV remux",
            details={"code": "remux_needs_disc"},
        )
    playlist_text = str(raw["playlist_id"]).lower().removesuffix(".mpls")
    if not playlist_text.isdigit():
        raise ReviewRequired("playlist_id must be numeric")
    playlist_id = playlist_text.zfill(5)
    try:
        playlist = scan.playlist(playlist_id)
    except KeyError as exc:
        raise ReviewRequired(str(exc)) from exc
    if raw["angle"] != 1 or isinstance(raw["angle"], bool):
        raise ReviewRequired(
            "a remux keeps the playlist's first angle; angle must be 1",
            details={"code": "remux_angle"},
        )
    videos = playlist.video_streams
    if not videos or videos[0].video is None:
        raise ReviewRequired(
            "the selected playlist has no video stream",
            details={"code": "remux_video_streams"},
        )
    # A second video stream is only acceptable as the Dolby Vision enhancement
    # layer the scan identified; anything else would silently lose a picture.
    if len(videos) > 1 and not (
        len(videos) == 2
        and scan.disc_kind is DiscKind.UHD
        and videos[0].video.dolby_vision_el_stream_id == videos[1].id
    ):
        raise ReviewRequired(
            "the playlist has a second video stream that is not a recognized "
            "Dolby Vision enhancement layer",
            details={"code": "remux_video_streams"},
        )
    video_family = remux.stream_family(videos[0])
    if video_family not in remux.VIDEO_FAMILIES or videos[0].video.three_d:
        raise ReviewRequired(
            f"the playlist's {videos[0].codec} video cannot be remuxed",
            details={"code": "remux_video_codec"},
        )
    video = videos[0].video
    if video.frame_rate is None or video.height is None:
        raise ReviewRequired("source video geometry/timing is incomplete")

    tracks_raw = raw["tracks"]
    if not isinstance(tracks_raw, list):
        raise ReviewRequired("tracks must be an array")
    allowed_track = {
        "stream_id",
        "action",
        "language",
        "name",
        "default",
        "forced",
        "subtitle_kind",
        "order",
    }
    stream_by_id = {stream.id: stream for stream in playlist.streams}
    tracks: list[TrackSelection] = []
    for number, item in enumerate(tracks_raw):
        if not isinstance(item, Mapping) or set(item) - allowed_track:
            raise ReviewRequired(f"tracks[{number}] contains unknown fields")
        if "stream_id" not in item or "action" not in item:
            raise ReviewRequired(f"tracks[{number}] needs stream_id and action")
        order_value = item.get("order", number)
        if type(order_value) is not int or order_value < 0:
            raise ReviewRequired(
                f"invalid tracks[{number}]: order must be a non-negative integer"
            )
        try:
            selected = TrackSelection(
                stream_id=str(item["stream_id"]),
                action=TrackAction(str(item["action"]).lower()),
                language=item.get("language"),
                name=item.get("name"),
                default=item.get("default"),
                forced=item.get("forced"),
                subtitle_kind=item.get("subtitle_kind"),
                order=order_value,
            )
        except (TypeError, ValueError) as exc:
            raise ReviewRequired(f"invalid tracks[{number}]: {exc}") from exc
        stream = stream_by_id.get(selected.stream_id)
        if stream is None:
            raise ReviewRequired(f"tracks[{number}] references an unknown stream")
        if stream.kind is StreamKind.VIDEO:
            raise ReviewRequired(f"tracks[{number}]: a remux always keeps its video")
        family = remux.stream_family(stream)
        action = selected.action
        if stream.kind is StreamKind.AUDIO:
            if selected.forced or selected.subtitle_kind is not None:
                raise ReviewRequired(f"tracks[{number}] audio cannot be forced")
            if family not in remux.AUDIO_FAMILIES:
                raise ReviewRequired(
                    f"tracks[{number}]: {stream.codec} audio cannot be remuxed",
                    details={"code": "remux_audio_codec"},
                )
            expected = TrackAction.FLAC if family == "LPCM" else TrackAction.COPY
            if action not in {expected, TrackAction.OMIT}:
                raise ReviewRequired(
                    f"tracks[{number}]: a remux keeps {stream.codec} audio as "
                    f"{expected.value} (the guide converts only LPCM, to FLAC)",
                    details={"code": "remux_audio_action"},
                )
        else:
            if action not in {TrackAction.COPY, TrackAction.OMIT}:
                raise ReviewRequired(f"tracks[{number}]: subtitles are copied or omitted")
            if action is TrackAction.COPY:
                if family != "PGS":
                    raise ReviewRequired(
                        f"tracks[{number}]: only PGS subtitles can be remuxed",
                        details={"code": "remux_subtitle_codec"},
                    )
                if selected.subtitle_kind not in {"full", "forced"}:
                    raise ReviewRequired(
                        f"tracks[{number}] retained subtitle needs an explicit full/forced classification"
                    )
                if selected.forced is not None and selected.forced is not (
                    selected.subtitle_kind == "forced"
                ):
                    raise ReviewRequired(
                        f"tracks[{number}] subtitle forced flag conflicts with subtitle_kind"
                    )
        tracks.append(selected)
    if len({item.stream_id for item in tracks}) != len(tracks):
        raise ReviewRequired("each playlist track may be selected only once")
    retained_audio = [
        item
        for item in tracks
        if item.action is not TrackAction.OMIT
        and stream_by_id[item.stream_id].kind is StreamKind.AUDIO
    ]
    if not retained_audio:
        raise ReviewRequired("a remux needs at least one audio track")

    options_raw = raw.get("remux", {})
    if not isinstance(options_raw, Mapping) or set(options_raw) - _REMUX_OPTION_KEYS:
        raise ReviewRequired("remux options may contain imdb and tmdb")
    imdb = options_raw.get("imdb") or None
    tmdb = options_raw.get("tmdb") or None
    if imdb is not None and not (isinstance(imdb, str) and remux.IMDB_ID.fullmatch(imdb)):
        raise ReviewRequired("remux.imdb must look like tt0123456")
    if tmdb is not None and not (isinstance(tmdb, str) and remux.TMDB_ID.fullmatch(tmdb)):
        raise ReviewRequired("remux.tmdb must look like movie/123 or tv/123")

    output_name = str(raw["output_name"]).removesuffix(".mkv")
    if not _SAFE_OUTPUT_RE.fullmatch(output_name) or output_name in {".", ".."}:
        raise ReviewRequired("output_name contains unsafe characters")
    if not isinstance(raw["upload_images"], bool):
        raise ReviewRequired("upload_images must be boolean")
    image_upload_provider = str(raw.get("image_upload_provider", "auto")).lower()
    if image_upload_provider not in {"auto", "imgbb", "catbox", "freeimage"}:
        raise ReviewRequired(
            "image_upload_provider must be auto, imgbb, catbox or freeimage"
        )
    upload_image_set = str(raw.get("upload_image_set", "all")).lower()
    if upload_image_set not in UPLOAD_IMAGE_SETS:
        raise ReviewRequired("upload_image_set must be all, sdr or native")
    name_warnings = _release_name_warnings(
        output_name,
        facts=remux_release_facts(scan=scan, playlist=playlist, tracks=tracks),
    )
    return ParsedSelection(
        name_warnings=name_warnings,
        external_sources=_parse_external_sources(raw),
        playlist_id=playlist_id,
        angle=1,
        settings=recommended_profile(
            VideoEncoder.X264, content_type=job.content_type.value.lower()
        ),
        crop=VapourSynthCrop(left=0, top=0, right=0, bottom=0),
        temporal_filter=TemporalFilter.PROGRESSIVE,
        tracks=tuple(tracks),
        output_name=output_name,
        upload_images=raw["upload_images"],
        image_upload_provider=image_upload_provider,
        upload_image_set=upload_image_set,
        dual_type_match=False,
        schema_version=2,
        tracker_profile=tracker_profile,
        mode="remux",
        remux=RemuxOptions(imdb=imdb, tmdb=tmdb),
    )


def remux_output_order(
    playlist: PlaylistCandidate, tracks: Sequence[TrackSelection]
) -> list[tuple[TrackSelection, MediaStream]]:
    """Retained audio, then subtitles, each in the operator's order."""

    streams = {item.id: item for item in playlist.streams}
    retained = [
        (item, streams[item.stream_id])
        for item in sorted(tracks, key=lambda value: value.order)
        if item.action is not TrackAction.OMIT
    ]
    # A kept TrueHD brings its embedded AC-3 itself, whatever its row says.
    kept = {stream.id for _item, stream in retained}
    retained = [
        pair
        for pair in retained
        if (parent := remux.embedded_core_parent(pair[1], playlist.audio_streams)) is None
        or parent.id not in kept
    ]
    return [pair for pair in retained if pair[1].kind is StreamKind.AUDIO] + [
        pair for pair in retained if pair[1].kind is StreamKind.SUBTITLE
    ]


def remux_release_facts(
    *,
    scan: DiscScan,
    playlist: PlaylistCandidate,
    tracks: Sequence[TrackSelection],
    atmos: Mapping[str, bool] | None = None,
) -> ReleaseFacts:
    """What a remux name may say: the untouched video and the kept audio.

    A TrueHD track brings its embedded AC-3 along as the next track.
    ``atmos`` overrides the scan's object-audio guess per stream with what
    eac3to read from the bitstream (FFmpeg 5 does not see TrueHD Atmos).
    """

    audio: list[AudioOutput] = []
    for item, stream in remux_output_order(playlist, tracks):
        if stream.kind is not StreamKind.AUDIO:
            continue
        family = remux.stream_family(stream)
        language = item.bcp47(stream).split("-")[0].casefold()
        commentary = TrackRole.COMMENTARY in stream.roles
        audio.append(
            AudioOutput(
                codec="FLAC" if family == "LPCM" else family,
                channels=stream.channels,
                atmos=(atmos or {}).get(stream.id, stream.object_audio),
                language=language,
                commentary=commentary,
            )
        )
        if family == "TRUEHD":
            audio.append(
                AudioOutput(
                    codec="DD",
                    channels=min(stream.channels or 6, 6),
                    language=language,
                    commentary=commentary,
                )
            )
    video_stream = playlist.video_streams[0]
    video = video_stream.video
    assert video is not None
    return ReleaseFacts(
        encoder="remux",
        audio=tuple(audio),
        dynamic_range=remux.dynamic_range(video),
        video_codec=remux.VIDEO_NAME_CODECS[remux.stream_family(video_stream)],
        resolution=remux.resolution_text(video.height, video.field_order, video.frame_rate),
        uhd=scan.disc_kind is DiscKind.UHD,
    )


def chapter_keyframe_seconds(playlist: PlaylistCandidate) -> tuple[float, ...]:
    """Chapter starts that need an IDR frame: not the first frame, not the last second."""

    end = playlist.duration_seconds - 1.0
    return tuple(
        sorted({round(value, 3) for value in playlist.chapters if 0.5 < value < end})
    )


def release_facts(
    *,
    encoder: VideoEncoder,
    playlist: PlaylistCandidate,
    tracks: Sequence[TrackSelection],
    settings: EncoderSettings,
    dynamic_plan: DynamicHdrPlan,
) -> ReleaseFacts:
    """What a release name may truthfully say about this plan."""

    streams = {item.id: item for item in playlist.streams}
    audio: list[AudioOutput] = []
    for item in tracks:
        stream = streams.get(item.stream_id)
        if (
            item.action is TrackAction.OMIT
            or stream is None
            or stream.kind is not StreamKind.AUDIO
        ):
            continue
        if item.action is TrackAction.COPY:
            codec = audio_codec_family(stream.codec, stream.codec_profile)
            channels = stream.channels
            atmos = stream.object_audio
        else:
            codec = {
                TrackAction.FLAC: "FLAC",
                TrackAction.FLAC16: "FLAC",
                TrackAction.AC3: "DD",
                TrackAction.EAC3: "DDP",
                TrackAction.DTS: "DTS",
            }[item.action]
            preset = AUDIO_TRANSCODE_PRESETS.get(item.action.value)
            channels = (
                min(stream.channels, preset.max_channels)
                if preset is not None and stream.channels
                else stream.channels
            )
            atmos = False
        audio.append(
            AudioOutput(
                codec=codec,
                channels=channels,
                atmos=atmos,
                language=item.bcp47(stream).split("-")[0].casefold(),
                commentary=TrackRole.COMMENTARY in stream.roles,
            )
        )
    if encoder is VideoEncoder.X264:
        dynamic = {"SDR"}
    else:
        video = playlist.video_streams[0].video if playlist.video_streams else None
        transfer = ((video.color_transfer if video else None) or "").casefold()
        if settings.hdr10.enabled:
            dynamic = {"HDR"}
        elif transfer in {"arib-std-b67", "hlg"}:
            dynamic = {"HLG"}
        else:
            dynamic = {"SDR"}
        if dynamic_plan.mode is DynamicHdrMode.HDR10PLUS:
            dynamic.add("HDR10+")
        if dynamic_plan.mode is DynamicHdrMode.DOLBY_VISION:
            dynamic.add("DV")
    return ReleaseFacts(
        encoder=encoder.value, audio=tuple(audio), dynamic_range=frozenset(dynamic)
    )


def resolve_selection_dynamic_hdr(
    scan: DiscScan, selection: ParsedSelection
) -> DynamicHdrPlan:
    """Resolve the requested retention against the scanned source (pure)."""

    if selection.dynamic_hdr is DynamicHdrMode.DISCARD:
        return DISCARD_PLAN
    playlist = scan.playlist(selection.playlist_id)
    video = playlist.video_streams[0].video if playlist.video_streams else None
    if video is None:
        raise DynamicHdrError("no_video", "the playlist has no video stream")
    el_ordinal = next(
        (
            ordinal
            for ordinal, stream in enumerate(playlist.video_streams)
            if video.dolby_vision_el_stream_id and stream.id == video.dolby_vision_el_stream_id
        ),
        None,
    )
    return resolve_dynamic_hdr(
        selection.dynamic_hdr,
        encoder=selection.settings.encoder.value,
        hdr10_enabled=selection.settings.hdr10.enabled,
        progressive=selection.temporal_filter is TemporalFilter.PROGRESSIVE,
        crop_enabled=selection.crop.enabled,
        dolby_vision=video.dolby_vision,
        dolby_vision_profile=video.dolby_vision_profile,
        hdr10_base_layer=video.hdr10_base_layer,
        hdr10_plus=video.hdr10_plus,
        dolby_vision_el_ordinal=el_ordinal,
        dolby_vision_el_type=video.dolby_vision_el_type,
    )


def _settings_for_dynamic_hdr(
    settings: EncoderSettings, plan: DynamicHdrPlan
) -> EncoderSettings:
    """Dolby Vision 8.1 needs a bounded VBV that x265 does not impose itself."""

    if plan.mode is DynamicHdrMode.DOLBY_VISION and settings.vbv is None:
        return replace(
            settings,
            vbv=VbvSettings(
                maxrate_kbps=DOLBY_VISION_VBV_KBPS,
                bufsize_kbps=DOLBY_VISION_VBV_KBPS,
            ),
        )
    return settings


def _field_handling(value: TemporalFilter) -> FieldHandling:
    if value is TemporalFilter.PROGRESSIVE:
        return FieldHandling.PROGRESSIVE
    if value in {TemporalFilter.IVTC_TFF, TemporalFilter.IVTC_BFF}:
        return FieldHandling.IVTC
    if value in {TemporalFilter.BWDIF_TFF, TemporalFilter.BWDIF_BFF}:
        return FieldHandling.DEINTERLACE
    return FieldHandling.HYBRID


def _vapoursynth_output_frame_rate(
    frame_rate: str | None, temporal_filter: TemporalFilter
) -> str | None:
    """Return the actual frame rate emitted by the reviewed VapourSynth graph."""

    if frame_rate is None:
        return None
    rate = parse_frame_rate(frame_rate)
    if temporal_filter in {TemporalFilter.IVTC_TFF, TemporalFilter.IVTC_BFF}:
        rate *= Fraction(4, 5)
    elif temporal_filter in {
        TemporalFilter.HYBRID_SAFE_BOB_TFF,
        TemporalFilter.HYBRID_SAFE_BOB_BFF,
    }:
        rate *= 2
    return format_frame_rate(rate)


def _planner_crop(value: VapourSynthCrop) -> PlannerCrop:
    return PlannerCrop(value.left, value.top, value.right, value.bottom)


def _release_name_warnings(output_name: str, *, facts: ReleaseFacts) -> tuple[str, ...]:
    """Where the name strays from the release-name rules: inherited source
    metadata, or a claim the plan does not back.  Advice only: the name's
    safety as a file name is checked separately (``_SAFE_OUTPUT_RE``)."""

    return tuple(release_name_problems(output_name, facts))


def _track_name(item: TrackSelection, stream: MediaStream) -> str:
    return resolved_track_name(item, stream)


def _effective_audio_defaults(
    retained: Sequence[tuple[int, TrackSelection, MediaStream]],
    *,
    allow_dub_default: bool = False,
) -> dict[str, bool]:
    try:
        return resolve_audio_defaults(
            [(item, stream) for _, item, stream in retained],
            allow_dub_default=allow_dub_default,
        )
    except ValueError as exc:
        raise ReviewRequired(str(exc)) from exc


def _mean_plane_bias(
    samples: Sequence[Mapping[str, Any]],
) -> dict[str, float] | None:
    """Per-plane mean of the samples' signed bias, or None when none was measured."""

    totals: dict[str, list[float]] = {}
    for sample in samples:
        bias = sample.get("plane_bias_8bit")
        if isinstance(bias, Mapping):
            for name, value in bias.items():
                if isinstance(value, (int, float)):
                    totals.setdefault(str(name), []).append(float(value))
    if not totals:
        return None
    return {name: round(sum(values) / len(values), 4) for name, values in totals.items()}


def _playlist_join_seconds(playlist: PlaylistCandidate) -> list[float]:
    """The clip-join times of a multi-clip playlist, from its start."""

    return sorted(
        {
            segment.relative_start_seconds
            for segment in playlist.segments
            if segment.relative_start_seconds > 0
        }
    )


# Below these the encode is broken (wrong frames, corruption, a failed
# filter), not merely soft: the job stops for review.  The stricter quality
# policy of ``_sampled_video_metric_errors`` only warns, because grainy film
# can dip one sample under it while it looks identical to the source.
BROKEN_SAMPLE_SSIM = 0.80
BROKEN_SAMPLE_PSNR_DB = 28.0
BROKEN_MEAN_SSIM = 0.90
BROKEN_MEAN_PSNR_DB = 33.0


def _title_duration_is_estimate(scan: DiscScan, playlist: PlaylistCandidate) -> bool:
    """Whether the playlist duration is ffprobe's container estimate.

    The libbluray playlist reader provides both the exact playlist duration
    and its clip segments.  When it failed or timed out during the scan the
    playlist has no segments and its duration is ffprobe's ``format.duration``
    estimate, which can be off by more than a frame or two.  A scan without
    any playlist backend (the largest-clip fallback) is an estimate as well.
    """

    return not playlist.segments or any(
        warning == LIBBLURAY_UNAVAILABLE_WARNING
        or warning.startswith("No libbluray playlist backend")
        for warning in scan.warnings
    )


def _sampled_video_metric_blockers(
    samples: Sequence[Mapping[str, Any]],
) -> tuple[str, ...]:
    """Sampled measurements that show a broken encode or a broken measurement."""

    errors: list[str] = []
    finite_ssim: list[float] = []
    finite_psnr: list[float] = []
    for index, sample in enumerate(samples, start=1):
        ssim = sample.get("ssim_all")
        psnr = sample.get("psnr_average_db")
        if not isinstance(ssim, float) or not 0 <= ssim <= 1:
            errors.append(f"sample {index} has no finite SSIM value")
        else:
            finite_ssim.append(ssim)
            if ssim < BROKEN_SAMPLE_SSIM:
                errors.append(
                    f"sample {index} SSIM is below {BROKEN_SAMPLE_SSIM:.2f} ({ssim:.6f})"
                )
        if isinstance(psnr, float):
            finite_psnr.append(psnr)
            if psnr < BROKEN_SAMPLE_PSNR_DB:
                errors.append(
                    f"sample {index} PSNR is below {BROKEN_SAMPLE_PSNR_DB:g} dB ({psnr:.3f} dB)"
                )
        elif str(psnr).casefold() not in {"inf", "+inf"}:
            errors.append(f"sample {index} has no valid PSNR value")
    if finite_ssim and sum(finite_ssim) / len(finite_ssim) < BROKEN_MEAN_SSIM:
        errors.append(f"mean sampled SSIM is below {BROKEN_MEAN_SSIM:.2f}")
    if finite_psnr and sum(finite_psnr) / len(finite_psnr) < BROKEN_MEAN_PSNR_DB:
        errors.append(f"mean sampled PSNR is below {BROKEN_MEAN_PSNR_DB:g} dB")
    for name, value in (_mean_plane_bias(samples) or {}).items():
        if abs(value) > MAXIMUM_MEAN_PLANE_BIAS:
            errors.append(
                f"mean sampled {name.upper()} plane is shifted by {value:+.2f} "
                f"(8-bit code values, limit {MAXIMUM_MEAN_PLANE_BIAS}); "
                "a systematic colour or levels error in the encode"
            )
    return tuple(errors)


def _sampled_video_metric_errors(
    samples: Sequence[Mapping[str, Any]],
) -> tuple[str, ...]:
    """The sampled quality policy: every finding is reported as a warning.

    The ones that also show a broken encode come from
    :func:`_sampled_video_metric_blockers`.
    """

    errors: list[str] = []
    ssim_by_type: dict[str, list[float]] = {"I": [], "P": [], "B": []}
    finite_ssim: list[float] = []
    finite_psnr: list[float] = []
    for index, sample in enumerate(samples, start=1):
        category = str(sample.get("category", ""))
        ssim = sample.get("ssim_all")
        psnr = sample.get("psnr_average_db")
        if not isinstance(ssim, float) or not 0 <= ssim <= 1:
            errors.append(f"sample {index} has no finite SSIM value")
        else:
            finite_ssim.append(ssim)
            if category in ssim_by_type:
                ssim_by_type[category].append(ssim)
            if ssim < 0.93:
                errors.append(f"sample {index} SSIM is below 0.93 ({ssim:.6f})")
        if isinstance(psnr, float):
            finite_psnr.append(psnr)
            if psnr < 35:
                errors.append(f"sample {index} PSNR is below 35 dB ({psnr:.3f} dB)")
        elif str(psnr).casefold() not in {"inf", "+inf"}:
            errors.append(f"sample {index} has no valid PSNR value")
    if finite_ssim and sum(finite_ssim) / len(finite_ssim) < 0.95:
        errors.append("mean sampled SSIM is below 0.95")
    if finite_psnr and sum(finite_psnr) / len(finite_psnr) < 38:
        errors.append("mean sampled PSNR is below 38 dB")
    for name, value in (_mean_plane_bias(samples) or {}).items():
        if abs(value) > MAXIMUM_MEAN_PLANE_BIAS:
            errors.append(
                f"mean sampled {name.upper()} plane is shifted by {value:+.2f} "
                f"(8-bit code values, limit {MAXIMUM_MEAN_PLANE_BIAS}); "
                "a systematic colour or levels error in the encode"
            )
    if ssim_by_type["B"] and ssim_by_type["P"]:
        b_mean = sum(ssim_by_type["B"]) / len(ssim_by_type["B"])
        p_mean = sum(ssim_by_type["P"]) / len(ssim_by_type["P"])
        if p_mean - b_mean > 0.03:
            errors.append("B-frame sampled SSIM trails P-frames by more than 0.03")
    return tuple(errors)


# Waits between automatic upload attempts while an image host is unreachable
# or answers with a passing error: about 33 minutes in all, then the job
# stops in UPLOAD_FAILED for the operator.
UPLOAD_RETRY_DELAYS: tuple[float, ...] = (30, 60, 120, 300, 600, 900)


# Waits before a stage is run again after a passing storage or network error
# (a NAS or SMB share that drops for a moment); finished checkpoints are kept.
IO_RETRY_DELAYS: tuple[float, ...] = (60, 300, 900)
_TRANSIENT_ERRNOS = frozenset(
    getattr(errno, name)
    for name in (
        "EIO", "ESTALE", "ETIMEDOUT", "EAGAIN", "EBUSY", "EINTR", "ENOTCONN",
        "ECONNRESET", "ECONNABORTED", "EHOSTDOWN", "EHOSTUNREACH", "ENETDOWN",
        "ENETUNREACH", "ENETRESET", "EREMOTEIO",
    )
    if hasattr(errno, name)
)


def _transient_os_error(exc: OSError) -> bool:
    return exc.errno in _TRANSIENT_ERRNOS


def _transient_upload_error(exc: ImageUploadError) -> bool:
    """Whether the same upload may succeed a little later.

    Errors raised by a host client name their provider; a permanent rejection
    (file too big, invalid key) and local set-up errors (no provider, a failed
    client initialisation) are not retried.
    """

    if exc.permanent:
        return False
    return exc.provider is not None or str(exc).startswith(
        "all image upload providers are temporarily unavailable"
    )


class PipelineWorker:
    """One durable worker.  Running a second instance remains database-safe."""

    def __init__(
        self,
        database: Database,
        settings: Settings,
        *,
        scanner_factory: Callable[[Settings], BluRayScanner] | None = None,
        runner_factory: Callable[[JobPaths], Runner] | None = None,
        upload_client_factory: Callable[[], ImageUploadClient] | None = None,
        upload_client_factories: Sequence[Callable[[], ImageUploadClient]]
        | None = None,
        language_runtime: AudioLanguageRuntime | None = None,
        stop_requested: Callable[[], bool] | None = None,
    ) -> None:
        self.database = database
        self.settings = settings.validate()
        self.maintenance = MaintenanceJournal(database, self.settings)
        self.maintenance.recover()
        self.queue = JobQueue(database)
        self.scanner_factory = scanner_factory
        self.runner_factory = runner_factory or (
            lambda paths: CommandRunner(paths.logs / "commands.jsonl")
        )
        if upload_client_factory is not None and upload_client_factories is not None:
            raise ValueError(
                "use either upload_client_factory or upload_client_factories"
            )
        # Keep the historical single-factory attribute mutable for tests and
        # integrations.  Production uses the ordered provider chain.
        self.upload_client_factory = upload_client_factory
        self.upload_client_factories = tuple(
            upload_client_factories or (ImgBBClient, CatboxClient, FreeimageClient)
        )
        self.language_runtime = language_runtime or AudioLanguageRuntime(
            settings.data_root
        )
        self.stop_requested = stop_requested or (lambda: False)
        # Mutable for tests, like ``upload_client_factory``.
        self.upload_retry_delays: tuple[float, ...] = UPLOAD_RETRY_DELAYS
        self._comparison_time_scale = 1
        self.io_retry_delays: tuple[float, ...] = IO_RETRY_DELAYS
        self._sleep: Callable[[float], None] = time.sleep
        self._runners: dict[str, Runner] = {}
        self._lives: dict[str, LiveProgress] = {}

    def _live(self, paths: JobPaths) -> LiveProgress:
        """The job's live step reporter (``<job>/.live``), one per job root."""

        key = str(paths.root)
        live = self._lives.get(key)
        if live is None:
            live = LiveProgress(paths.live)
            live.discard_stale()
            self._lives[key] = live
        return live

    @contextlib.contextmanager
    def _step(
        self,
        paths: JobPaths,
        key: str,
        label: LiveText,
        *,
        detail: LiveText | None = None,
    ) -> Iterator[LiveProgress]:
        """Report one step of the pipeline to the UI while its body runs.

        ``label`` and ``detail`` are ``(hungarian, english)`` pairs: the API
        serves them in the interface language of the request.
        """

        live = self._live(paths)
        live.start(key, label, detail=detail)
        try:
            yield live
        except ProcessInterrupted:
            live.finish("interrupted")
            raise
        except ReviewRequired:
            live.finish("review")
            raise
        except BaseException:
            live.finish("failed")
            raise
        live.finish("done")

    def _run_reported(
        self,
        paths: JobPaths,
        argv: Sequence[str | os.PathLike[str]],
        *,
        probe: Callable[[], None],
        **kwargs: Any,
    ) -> Any:
        """``runner.run`` that polls ``probe`` for progress on a real runner."""

        runner = self._runner(paths)
        if isinstance(runner, CommandRunner):
            return runner.run(argv, progress_probe=probe, **kwargs)
        return runner.run(argv, **kwargs)

    def _runner(self, paths: JobPaths) -> Runner:
        key = str(paths.root)
        runner = self._runners.get(key)
        if runner is None:
            runner = self.runner_factory(paths)
            if isinstance(runner, CommandRunner):
                runner.set_interrupt_requested(
                    lambda: self._process_interrupt_requested(paths.root.name)
                )
            self._runners[key] = runner
        return runner

    def _process_interrupt_requested(self, job_id: str) -> bool:
        if self.stop_requested():
            return True
        try:
            control, _revision = self.database.get_control(job_id)
        except Exception:
            LOG.exception("job %s control polling failed; process continues", job_id)
            return False
        return control in {
            JobControlState.PAUSE_REQUESTED,
            JobControlState.CANCEL_REQUESTED,
        }

    def _acknowledge_operator_control(self, job_id: str) -> Job | None:
        """Acknowledge the latest request at a worker-safe boundary."""

        while True:
            control, revision = self.database.get_control(job_id)
            try:
                if control is JobControlState.PAUSE_REQUESTED:
                    return self.queue.acknowledge_pause(
                        job_id, expected_control_revision=revision
                    )
                if control is JobControlState.CANCEL_REQUESTED:
                    return self.queue.acknowledge_cancel(
                        job_id, expected_control_revision=revision
                    )
                if control is JobControlState.PAUSED:
                    return self.database.get_job(job_id)
                return None
            except StateConflictError:
                # Pause may be escalated to cancel between observation and ack.
                # Re-read instead of acknowledging the superseded revision.
                continue

    def _stop_at_operator_boundary(self, job_id: str) -> None:
        if self._acknowledge_operator_control(job_id) is not None:
            raise ProcessInterrupted("operator control acknowledged at safe boundary")

    @staticmethod
    def _remove_interrupted_partials(paths: JobPaths) -> None:
        """Remove exact owned temporary outputs without traversing workspace links."""

        # A recursive suffix search is unsafe here: an operator-controlled local
        # workspace could acquire a directory symlink or Windows junction while a
        # command is running, making cleanup walk outside the job root. Keep this
        # list aligned with the explicit temporary paths created by the pipeline.
        candidates = (paths.work / "video-encoded.partial.mkv",)
        for candidate in candidates:
            if not os.path.lexists(candidate) or candidate.is_symlink():
                continue
            try:
                resolved_parent = candidate.parent.resolve(strict=True)
                resolved_work = paths.work.resolve(strict=True)
                if (
                    resolved_parent != resolved_work
                    or _unsafe_directory_link(paths.work)
                    or _unsafe_directory_link(candidate)
                    or not candidate.is_file()
                ):
                    LOG.warning(
                        "refusing to remove unsafe interrupted partial %s", candidate
                    )
                    continue
                candidate.unlink()
            except OSError:
                LOG.warning("could not remove interrupted partial %s", candidate)

    def _image_upload_clients(self) -> list[ImageUploadClient]:
        factories = (
            (self.upload_client_factory,)
            if self.upload_client_factory is not None
            else self.upload_client_factories
        )
        clients: list[ImageUploadClient] = []
        names: set[str] = set()
        for factory in factories:
            client = factory()
            name = str(getattr(client, "provider_name", "imgbb")).strip().lower()
            if not name or name in names:
                raise ImageUploadError("image upload provider names must be unique")
            names.add(name)
            clients.append(client)
        if not clients:
            raise ImageUploadError("no image upload provider is configured")
        # The operator's host order from the System page, read at every upload
        # step so a change needs no worker restart.  Without a saved order the
        # chain stays as built (ImgBB, Catbox, Freeimage in production).
        preferences = load_upload_preferences(
            upload_settings_path(self.settings.state_root)
        )
        if preferences.provider_order is None:
            return clients
        order = upload_host_order(preferences)
        names_in_chain = [
            str(getattr(client, "provider_name", "imgbb")).strip().lower()
            for client in clients
        ]
        return [clients[index] for index in order_by_preference(names_in_chain, order)]

    def process_one_stage(self, job: Job) -> Job:
        """Run exactly the current durable stage and return refreshed state."""
        paths = JobPaths.create(self.settings, job.id)
        controlled = self._acknowledge_operator_control(job.id)
        if controlled is not None:
            return controlled
        if job.state is JobState.SCANNING:
            with self._step(paths, "scan", ("Lemez beolvasása", "Reading the disc")):
                self._scan(job, paths)
        elif _is_fit_job(job) and job.state in _REMUX_STAGES:
            self._process_fit_stage(job, paths)
        elif _is_remux_job(job) and job.state in _REMUX_STAGES:
            self._process_remux_stage(job, paths)
        elif job.state is JobState.READY:
            self._prepare(job, paths)
        elif job.state is JobState.ENCODING:
            if not self._preparation_is_current(job, paths):
                self._prepare(job, paths, advance=False)
            self._encode(job, paths)
        elif job.state is JobState.MUXING:
            with self._step(paths, "mux", ("Muxolás", "Muxing")):
                self._mux(job, paths)
        elif job.state is JobState.QC:
            with self._step(paths, "qc", ("Minőségellenőrzés (QC)", "Quality check (QC)")):
                self._qc(job, paths)
        elif job.state is JobState.COMPARISON:
            with self._step(paths, "comparison", ("Összehasonlítás", "Comparison")):
                self._comparison_with_retries(job, paths)
        elif job.state is JobState.UPLOADING:
            with self._step(paths, "upload", ("Képfeltöltés és lezárás", "Image upload and finalization")):
                self._upload_with_retries(job, paths)
        return self.database.get_job(job.id)

    def _process_stage_with_io_retries(self, job: Job) -> Job:
        """One stage; a passing storage or network error runs it again.

        Stages resume from their checkpoints, so a retry repeats only the
        unfinished part.  Other errors, and the last failed attempt, reach the
        usual failure handling.
        """

        delays = tuple(self.io_retry_delays)
        for attempt in range(1, len(delays) + 2):
            try:
                return self.process_one_stage(job)
            except OSError as exc:
                if attempt > len(delays) or not _transient_os_error(exc):
                    raise
                delay = delays[attempt - 1]
                detail = sanitize_text(str(exc)).strip()[:400] or type(exc).__name__
                LOG.warning(
                    "job %s stage %s hit a passing I/O error (%s); retrying in %g s",
                    job.id,
                    job.state.value,
                    detail,
                    delay,
                )
                self.database.add_event(
                    EventCreate(
                        job_id=job.id,
                        kind="worker.io-retry",
                        message=(
                            f"a storage or network error interrupted the {job.state.value} "
                            f"stage; retrying automatically in {delay:g} s"
                        ),
                        payload={"attempt": attempt, "delay_seconds": delay, "detail": detail},
                    )
                )
                self._wait_before_upload_retry(job.id, delay)
                job = self.database.get_job(job.id)
        raise AssertionError("unreachable")

    def _comparison_with_retries(self, job: Job, paths: JobPaths) -> None:
        """Run the comparison; a timeout is retried with longer budgets."""

        scales = tuple(COMPARISON_RETRY_TIME_SCALES) or (1,)
        try:
            for attempt, scale in enumerate(scales, start=1):
                self._comparison_time_scale = scale
                try:
                    self._comparison(job, paths)
                    return
                except subprocess.TimeoutExpired as exc:
                    if attempt == len(scales):
                        raise
                    self._stop_at_operator_boundary(job.id)
                    if self.stop_requested():
                        raise ProcessInterrupted("worker shutdown before a comparison retry") from exc
                    LOG.warning(
                        "job %s comparison ran out of time (%s); retrying with %dx budgets",
                        job.id,
                        exc.timeout,
                        scales[attempt],
                    )
                    self.database.add_event(
                        EventCreate(
                            job_id=job.id,
                            kind="worker.comparison-retry",
                            message=(
                                "comparison ran out of time; retrying automatically "
                                f"with {scales[attempt]}x time budgets"
                            ),
                            payload={
                                "attempt": attempt,
                                "time_scale": scales[attempt],
                                "timeout_seconds": exc.timeout,
                            },
                        )
                    )
        finally:
            self._comparison_time_scale = 1

    def _upload_with_retries(self, job: Job, paths: JobPaths) -> None:
        """Upload and finalise; a passing host error is retried automatically.

        Each attempt resumes from the upload checkpoint, so images already on
        the host are not sent again and a provider lock is kept.  The waits
        stop at an operator pause or cancel and at a worker shutdown.
        """

        delays = tuple(self.upload_retry_delays)
        for attempt in range(1, len(delays) + 2):
            try:
                self._upload_and_finalize(job, paths)
                return
            except ImageUploadError as exc:
                if attempt > len(delays) or not _transient_upload_error(exc):
                    raise
                delay = delays[attempt - 1]
                detail = sanitize_text(str(exc)).strip()[:400] or type(exc).__name__
                LOG.warning(
                    "job %s image upload attempt %d failed (%s); retrying in %g s",
                    job.id,
                    attempt,
                    detail,
                    delay,
                )
                self.database.add_event(
                    EventCreate(
                        job_id=job.id,
                        kind="worker.image-upload-retry",
                        message=(
                            f"image upload attempt {attempt} failed; "
                            f"retrying automatically in {delay:g} s"
                        ),
                        payload={
                            "attempt": attempt,
                            "delay_seconds": delay,
                            "provider": exc.provider,
                            "detail": detail,
                        },
                    )
                )
                self._live(paths).update(
                    0.0,
                    detail=(
                        f"A képtárhely nem elérhető; újrapróbálás {delay:g} mp múlva ({attempt}. kísérlet után)",
                        f"The image host is unavailable; retrying in {delay:g} s (after attempt {attempt})",
                    ),
                )
                self._wait_before_upload_retry(job.id, delay)

    def _wait_before_upload_retry(self, job_id: str, seconds: float) -> None:
        waited = 0.0
        while waited < seconds:
            self._stop_at_operator_boundary(job_id)
            if self.stop_requested():
                raise ProcessInterrupted("worker shutdown during an upload retry wait")
            step = min(1.0, seconds - waited)
            self._sleep(step)
            waited += step
        self._stop_at_operator_boundary(job_id)

    def process_job(self, job: Job) -> Job:
        """Continue one job until completion or an operator-controlled pause."""
        while job.state not in TERMINAL_STATES:
            if self.stop_requested():
                LOG.info(
                    "job %s paused at %s for worker shutdown",
                    job.id,
                    job.state.value,
                )
                return self.database.get_job(job.id)
            controlled = self._acknowledge_operator_control(job.id)
            if controlled is not None:
                return controlled
            if job.state in {
                JobState.AWAITING_SELECTION,
                JobState.NEEDS_REVIEW,
                JobState.UPLOAD_FAILED,
            }:
                return job
            try:
                before = job.state
                job = self._process_stage_with_io_retries(job)
                if job.control_state is JobControlState.PAUSED:
                    return job
                if job.state is before:
                    raise RuntimeError(
                        f"worker stage {before.value} made no durable progress"
                    )
            except ReviewRequired as exc:
                current = self.database.get_job(job.id)
                if (
                    current.state not in TERMINAL_STATES
                    and current.state is not JobState.NEEDS_REVIEW
                ):
                    job = self.queue.needs_review(
                        job.id, message=str(exc), details=exc.details
                    )
                else:
                    job = current
                return job
            except ProcessInterrupted:
                paths = JobPaths.create(self.settings, job.id)
                self._remove_interrupted_partials(paths)
                controlled = self._acknowledge_operator_control(job.id)
                current = controlled or self.database.get_job(job.id)
                if current.state is JobState.CANCELLED:
                    LOG.info(
                        "job %s encode stopped after operator cancellation", job.id
                    )
                elif current.control_state is JobControlState.PAUSED:
                    LOG.info(
                        "job %s paused at durable %s boundary",
                        job.id,
                        current.state.value,
                    )
                elif self.stop_requested():
                    LOG.info("job %s encode stopped for worker shutdown", job.id)
                else:
                    LOG.warning(
                        "job %s process was interrupted; durable state remains %s",
                        job.id,
                        current.state.value,
                    )
                # Keeping the pipeline stage lets a resumed invocation reuse
                # completed checkpoints and replay only the interrupted unit.
                return current
            except subprocess.TimeoutExpired as exc:
                current = self.database.get_job(job.id)
                controlled = self._acknowledge_operator_control(job.id)
                if controlled is not None:
                    self._remove_interrupted_partials(
                        JobPaths.create(self.settings, job.id)
                    )
                    return controlled
                if self.stop_requested():
                    LOG.info(
                        "job %s stopped during %s without a failure transition",
                        job.id,
                        current.state.value,
                    )
                    return current
                if current.state is JobState.COMPARISON:
                    return self.queue.needs_review(
                        job.id,
                        message=(
                            "fast comparison exceeded its bounded command/time budget"
                        ),
                        details={
                            "timeout_seconds": exc.timeout,
                            "command": redact_argv(exc.cmd or ()),
                        },
                    )
                self._fail(current, exc)
                return self.database.get_job(job.id)
            except (ImageUploadError, OSError) as exc:
                current = self.database.get_job(job.id)
                controlled = self._acknowledge_operator_control(job.id)
                if controlled is not None:
                    return controlled
                if self.stop_requested():
                    LOG.info(
                        "job %s stopped during %s without a failure transition",
                        job.id,
                        current.state.value,
                    )
                    return current
                if current.state is JobState.UPLOADING:
                    detail = sanitize_text(str(exc)).strip()[:800]
                    if not detail:
                        detail = type(exc).__name__
                    provider = (
                        exc.provider
                        if isinstance(exc, ImageUploadError) and exc.provider
                        else None
                    )
                    LOG.warning(
                        "job %s image upload failed via %s: %s",
                        job.id,
                        provider or "unselected provider",
                        detail,
                    )
                    return self.queue.advance(
                        job.id,
                        JobState.UPLOAD_FAILED,
                        message="image upload failed; retry is safe",
                        details={
                            "error_type": type(exc).__name__,
                            "provider": provider,
                            "detail": detail,
                        },
                    )
                self._fail(current, exc)
                return self.database.get_job(job.id)
            except Exception as exc:
                current = self.database.get_job(job.id)
                controlled = self._acknowledge_operator_control(job.id)
                if controlled is not None:
                    self._remove_interrupted_partials(
                        JobPaths.create(self.settings, job.id)
                    )
                    return controlled
                if self.stop_requested():
                    LOG.info(
                        "job %s stopped during %s without a failure transition",
                        job.id,
                        current.state.value,
                    )
                    return current
                self._fail(current, exc)
                return self.database.get_job(job.id)
        return job

    def _fail(self, job: Job, exc: Exception) -> None:
        LOG.exception("job %s failed in %s", job.id, job.state.value)
        if job.state in TERMINAL_STATES:
            return
        if job.state is JobState.SCANNING:
            scans = self.database.list_scans(job_id=job.id, limit=1)
            if scans and scans[0].status in {ScanState.PENDING, ScanState.RUNNING}:
                self.database.update_scan(
                    scans[0].id,
                    ScanUpdate(
                        status=ScanState.FAILED,
                        error=f"{type(exc).__name__}: {exc}",
                        message="disc scan failed",
                    ),
                )
                # update_scan atomically transitions the owning SCANNING job
                # to FAILED in the same transaction.
                return
        self.queue.fail(
            job.id,
            message=f"{type(exc).__name__}: {exc}",
            details={"stage": job.state.value, "error_type": type(exc).__name__},
        )

    def _scan(self, job: Job, paths: JobPaths) -> None:
        scans = self.database.list_scans(job_id=job.id, limit=1)
        scan_row: Scan
        if scans and scans[0].status in {ScanState.PENDING, ScanState.RUNNING}:
            scan_row = scans[0]
        else:
            scan_row = self.database.create_scan(ScanCreate(job_id=job.id))
        inputs = {
            "source": job.source_path,
            "content_kind": _content_kind(job).value,
            "source_roots": [str(item) for item in self.settings.source_roots],
        }
        marker = paths.stages / "scan.json"
        if not _valid_stage(marker, inputs, [paths.scan_json]):
            source = self.settings.authorize_source(job.source_path)
            mkv_source = source.is_file() and is_mkv_source(source)
            scanner: BluRayScanner | MkvScanner
            if self.scanner_factory is not None:
                scanner = self.scanner_factory(self.settings)
            else:
                source_root = next(
                    root
                    for root in self.settings.source_roots
                    if source == root or source.is_relative_to(root)
                )
                if mkv_source:
                    scanner = MkvScanner(
                        source_root=source_root,
                        runner=self._runner(paths),
                    )
                else:
                    scanner = BluRayScanner(
                        source_root=source_root,
                        runner=self._runner(paths),
                    )
            result = scanner.scan(source, content_kind=_content_kind(job))
            if not result.is_mkv:
                # A remux has one video track: there is no separate Dolby
                # Vision enhancement-layer stream to look for.
                result = self._detect_dolby_vision_layers(paths, source, result)
                result = self._detect_object_audio(paths, source, result)
            atomic_write_json(paths.scan_json, result.to_dict())
            _write_stage(marker, inputs, [paths.scan_json])
        result_json = json.loads(paths.scan_json.read_text(encoding="utf-8"))
        result_json = self._attach_track_analysis(job, paths, result_json)
        self._register_artifact(
            job.id,
            paths.scan_json,
            DatabaseArtifactKind.MANIFEST,
            "disc-scan.json",
            scan_id=scan_row.id,
            mime_type="application/json",
        )
        self.database.update_scan(
            scan_row.id,
            ScanUpdate(
                status=ScanState.AWAITING_SELECTION,
                result=result_json,
                message="scan complete; playlist, processing and tracks require confirmation",
            ),
        )

    def _attach_track_analysis(
        self, job: Job, paths: JobPaths, result_json: dict[str, Any]
    ) -> dict[str, Any]:
        """Add the selection-time track analysis to the recommended playlists.

        Advisory only: any failure leaves the scan as it was.  The result is
        kept under ``analysis/track-analysis.json``, keyed by the scan.
        """

        report = paths.analysis / "track-analysis.json"
        inputs = {
            "scan_sha256": sha256_file(paths.scan_json),
            "schema_version": TRACK_ANALYSIS_SCHEMA_VERSION,
        }
        marker = paths.stages / "track-analysis.json"
        analyses: dict[str, Any] = {}
        if _valid_stage(marker, inputs, [report]):
            try:
                analyses = json.loads(report.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                analyses = {}
        else:
            # A disc is read through libbluray by PID; a remux MKV file by its
            # own stream indexes (track_analysis.source_input_args).
            if self.scanner_factory is not None:
                # Test and alternative scanners have no real disc to read.
                return result_json
            try:
                source = self.settings.authorize_source(job.source_path)
            except Exception:  # noqa: BLE001 - advisory step
                return result_json
            playlists = [p for p in result_json.get("playlists") or [] if isinstance(p, dict)]
            runner = self._runner(paths)

            def run(argv: list[str], cwd: Path) -> str:
                stdout = cwd / "stdout.txt"
                runner.run(argv, cwd=cwd, stdout_path=stdout, stderr_path=cwd / "stderr.log", timeout=900)
                return stdout.read_text(encoding="utf-8", errors="replace")

            def detect(samples: Any) -> Any:
                return self.language_runtime.detect_samples(samples)

            chosen = playlists_to_analyse(playlists)
            with self._step(paths, "track-analysis", ("Sávok elemzése", "Analysing tracks")) as step:
                for number, playlist in enumerate(chosen):
                    work = paths.analysis / "track-analysis" / str(playlist.get("playlist_id"))
                    work.mkdir(parents=True, exist_ok=True)
                    try:
                        analyses[str(playlist["playlist_id"])] = analyse_playlist(
                            source,
                            playlist,
                            work,
                            run=run,
                            detect_language=detect,
                            on_window=lambda done, total, number=number: step.update(
                                (number + done / total) / max(len(chosen), 1)
                            ),
                        )
                    except Exception as exc:  # noqa: BLE001 - advisory only
                        LOG.warning("track analysis of playlist %s failed: %s", playlist.get("playlist_id"), exc)
                        analyses[str(playlist["playlist_id"])] = {
                            "schema_version": TRACK_ANALYSIS_SCHEMA_VERSION,
                            "status": "failed",
                            "reason": type(exc).__name__,
                        }
            atomic_write_json(report, analyses)
            _write_stage(marker, inputs, [report])
        for playlist in result_json.get("playlists") or []:
            if isinstance(playlist, dict) and str(playlist.get("playlist_id")) in analyses:
                playlist["track_analysis"] = analyses[str(playlist.get("playlist_id"))]
        return result_json

    def _detect_dolby_vision_layers(
        self, paths: JobPaths, source: Path, scan: DiscScan
    ) -> DiscScan:
        """Recognise a dual-layer (profile 7) Dolby Vision UHD disc, which no scanner flags."""

        runner = self._runner(paths)
        try:
            return detect_dolby_vision_layers(
                scan,
                source,
                run_pipeline=runner.run_pipeline,
                run=runner.run,
                read_text=lambda path: path.read_text(encoding="utf-8", errors="replace"),
                work=paths.analysis / "dolby-vision-probe",
                logs=paths.logs,
                tool_available=bool(dynamic_hdr_support().get("dolby_vision", {}).get("tool_available")),
            )
        except Exception:  # a failed probe must never fail the scan
            LOG.exception("job %s: the Dolby Vision layer probe failed; the scan is kept as it was", paths.root.name)
            return scan

    def _detect_object_audio(
        self, paths: JobPaths, source: Path, scan: DiscScan
    ) -> DiscScan:
        """Recognise Atmos and DTS:X, which FFmpeg 5 does not report."""

        try:
            return detect_object_audio(
                scan,
                source,
                run=self._runner(paths).run,
                read_text=lambda path: path.read_text(encoding="utf-8", errors="replace"),
                work=paths.analysis / "object-audio-probe",
                logs=paths.logs,
            )
        except Exception:  # a failed probe must never fail the scan
            LOG.exception("job %s: the object-audio probe failed; the scan is kept as it was", paths.root.name)
            return scan

    @staticmethod
    def _crop_policy_inputs(
        scan: DiscScan,
        selection: ParsedSelection,
        *,
        reference_sha256: str,
    ) -> dict[str, Any]:
        playlist = scan.playlist(selection.playlist_id)
        source_video = playlist.video_streams[0].video
        assert source_video is not None
        return {
            "policy_schema_version": 3,
            "strategy": "full-title-sequential-1fps",
            "selection_mode": "automatic-when-zero",
            "reference_sha256": reference_sha256,
            "duration_seconds": playlist.duration_seconds,
            "source_width": source_video.width,
            "source_height": source_video.height,
            "requested": asdict(selection.crop),
        }

    def _load_scan_and_selection(
        self, job: Job, paths: JobPaths
    ) -> tuple[DiscScan, ParsedSelection]:
        if not paths.scan_json.is_file():
            raise RuntimeError("durable scan.json is missing")
        scan = _scan_from_dict(json.loads(paths.scan_json.read_text(encoding="utf-8")))
        selection = parse_selection(job, scan)
        if paths.language_json.is_file():
            try:
                report = json.loads(paths.language_json.read_text(encoding="utf-8"))
                if (
                    report.get("selection_sha256") == _selection_hash(job.selection)
                    and report.get("scan_fingerprint") == scan.fingerprint
                    and report.get("status") == "completed"
                ):
                    resolved = report.get("resolved_languages", {})
                    selection = replace(
                        selection,
                        tracks=tuple(
                            replace(item, language=resolved[item.stream_id])
                            if item.language is None and item.stream_id in resolved
                            else item
                            for item in selection.tracks
                        ),
                    )
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                pass
        return scan, selection

    def _load_prepared_scan_and_selection(
        self, job: Job, paths: JobPaths
    ) -> tuple[DiscScan, ParsedSelection]:
        """Load the durable post-prepare selection contract.

        An all-zero operator crop is an automatic-selection sentinel, not the
        crop that was necessarily encoded.  Preparation records the validated
        effective crop in a hash-pinned policy report.  Every later stage must
        replay that decision and re-run source adaptation with its dimensions
        instead of silently falling back to the original zero margins.
        """

        if _is_remux_job(job) or _is_fit_job(job):
            # A remux has no crop, CRF or dynamic-HDR decision to replay.
            return self._load_scan_and_selection(job, paths)
        scan, selection = self._load_prepared_crop_selection(job, paths)
        selection = self._apply_auto_crf(job, paths, selection)
        if selection.dynamic_hdr is not DynamicHdrMode.DISCARD:
            plan, _metadata, _digest = self._load_dynamic_hdr(job, paths, selection)
            selection = replace(
                selection, settings=_settings_for_dynamic_hdr(selection.settings, plan)
            )
        return scan, selection

    def _apply_auto_crf(
        self, job: Job, paths: JobPaths, selection: ParsedSelection
    ) -> ParsedSelection:
        """Replace the nominal CRF with the durable automatic-search result."""

        if not selection.auto_crf.enabled:
            return selection
        report = paths.analysis / "crf-search.json"
        try:
            document = json.loads(report.read_text(encoding="utf-8"))
            chosen = document["chosen_crf"]
            if (
                document.get("schema_version") != 1
                or document.get("selection_sha256") != _selection_hash(job.selection)
                or type(chosen) not in {int, float}
            ):
                raise ValueError("report does not describe this selection")
            return replace(selection, settings=replace(selection.settings, crf=chosen))
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ReviewRequired(
                f"automatic CRF report is missing or stale: {exc}",
                details={"code": "crf_search_missing", "report": report.name},
            ) from exc

    def _load_prepared_crop_selection(
        self, job: Job, paths: JobPaths
    ) -> tuple[DiscScan, ParsedSelection]:
        scan, selection = self._load_scan_and_selection(job, paths)
        if selection.crop.enabled:
            return scan, selection

        reference_sha256 = _recorded_output_sha256(
            paths.stages / "reference-remux.json", paths.reference
        )
        if reference_sha256 is None:
            raise ReviewRequired(
                "automatic crop source checkpoint is missing or stale"
            )
        crop_inputs = self._crop_policy_inputs(
            scan,
            selection,
            reference_sha256=reference_sha256,
        )
        crop_report = paths.analysis / "crop-policy.json"
        if not _valid_stage(
            paths.stages / "crop-policy.json", crop_inputs, [crop_report]
        ):
            raise ReviewRequired("automatic crop checkpoint is missing or stale")
        try:
            crop_document = json.loads(crop_report.read_text(encoding="utf-8"))
            if (
                crop_document.get("schema_version") != 1
                or crop_document.get("status") != "passed"
                or crop_document.get("selection_mode") != "automatic"
            ):
                raise ValueError("automatic crop decision was not passed")
            effective_crop_raw = crop_document["decision"]["requested"]
            effective_crop = VapourSynthCrop(**effective_crop_raw)
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ReviewRequired(
                f"automatic crop report is invalid: {exc}"
            ) from exc

        effective_selection = parse_selection(
            job,
            scan,
            crop_override=effective_crop,
        )
        # Preserve any language inference already restored by the regular
        # loader; crop adaptation cannot change track decisions.
        return scan, replace(effective_selection, tracks=selection.tracks)

    @staticmethod
    def _declared_language_evidence(
        decision: LanguageDecision | None,
    ) -> dict[str, str | None]:
        result: dict[str, str | None] = {"mpls": None, "clpi": None, "pmt": None}
        if decision is not None and any(
            item.source is LanguageSource.MATROSKA for item in decision.evidence
        ):
            # Only an MKV source declares this; a disc keeps its three labels.
            result["matroska"] = None
        if decision is None:
            return result
        for item in decision.evidence:
            if item.source.value in result:
                result[item.source.value] = item.raw_code
        return result

    @staticmethod
    def _declared_language_codes(
        decision: LanguageDecision | None,
    ) -> dict[str, str | None]:
        raw = PipelineWorker._declared_language_evidence(decision)
        return {source: normalize_iso639_2(code) for source, code in raw.items()}

    @staticmethod
    def _settle_language(
        stream: MediaStream,
        settlement: LanguageSettlement,
        resolved: dict[str, str],
        unresolved: list[dict[str, Any]],
        warnings: list[dict[str, Any]],
        *,
        decision: LanguageDecision | None = None,
    ) -> None:
        if settlement.stop:
            entry: dict[str, Any] = {
                "stream_id": stream.id,
                "kind": stream.kind.value,
                "reason": "language_conflict_or_low_confidence",
            }
            if decision is not None:
                entry["decision"] = decision.to_dict()
            unresolved.append(entry)
            return
        if settlement.language is not None:
            resolved[stream.id] = settlement.language
        if settlement.warning:
            warnings.append(
                {
                    "stream_id": stream.id,
                    "kind": stream.kind.value,
                    "language": settlement.language,
                    "warning": settlement.warning,
                }
            )

    @staticmethod
    def _subtitle_detection(
        paths: JobPaths, playlist_id: str, stream_id: str
    ) -> tuple[str | None, float]:
        """The caption-text language of a subtitle from the track analysis."""

        try:
            analyses = json.loads((paths.analysis / "track-analysis.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None, 0.0
        wanted = str(playlist_id).lower().removesuffix(".mpls").zfill(5)
        analysis = next(
            (value for key, value in analyses.items() if str(key).zfill(5) == wanted),
            None,
        ) if isinstance(analyses, dict) else None
        record = (((analysis or {}).get("subtitles") or {}).get(stream_id) or {}).get("language") or {}
        code = normalize_iso639_2(record.get("iso639_2t")) if record.get("status") == "detected" else None
        confidence = record.get("confidence")
        return code, float(confidence) if isinstance(confidence, (int, float)) else 0.0

    def _resolve_selected_languages(
        self,
        job: Job,
        scan: DiscScan,
        selection: ParsedSelection,
        paths: JobPaths,
    ) -> ParsedSelection:
        playlist = scan.playlist(selection.playlist_id)
        streams = {item.id: item for item in playlist.streams}
        selected_ids = {item.stream_id for item in selection.tracks}
        resolved: dict[str, str] = {}
        evidence_records: list[dict[str, Any]] = []
        # A READY-stage restart may load previously inferred languages into the
        # in-memory selection. Preserve that durable evidence instead of
        # replacing the completed report with an empty map when inference is
        # consequently skipped on the replay.
        if paths.language_json.is_file():
            try:
                prior_report = json.loads(
                    paths.language_json.read_text(encoding="utf-8")
                )
                if (
                    prior_report.get("selection_sha256") == _selection_hash(job.selection)
                    and prior_report.get("scan_fingerprint") == scan.fingerprint
                    and prior_report.get("status") == "completed"
                ):
                    prior_resolved = prior_report.get("resolved_languages", {})
                    if isinstance(prior_resolved, dict):
                        resolved.update(
                            {
                                str(stream_id): str(language)
                                for stream_id, language in prior_resolved.items()
                                if stream_id in selected_ids and language
                            }
                        )
                    prior_evidence = prior_report.get("evidence", [])
                    if isinstance(prior_evidence, list):
                        evidence_records.extend(
                            item for item in prior_evidence if isinstance(item, dict)
                        )
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                pass
        unresolved: list[dict[str, Any]] = []
        language_warnings: list[dict[str, Any]] = []
        reference_digest = sha256_file(paths.reference)
        resolver = LanguageResolver()
        audio_ordinals = {
            stream.id: ordinal for ordinal, stream in enumerate(playlist.audio_streams)
        }

        for track in selection.tracks:
            if track.action is TrackAction.OMIT or track.language is not None:
                continue
            stream = streams.get(track.stream_id)
            if stream is None:
                continue
            declared = stream.language
            labels = self._declared_language_codes(declared)
            if stream.kind is StreamKind.SUBTITLE:
                # The selection-time analysis read the captions themselves
                # (OCR for PGS, text for SubRip): that reading is the detection
                # of a subtitle, as speech detection is for audio.
                detected, detected_confidence = self._subtitle_detection(
                    paths, selection.playlist_id, stream.id
                )
                if detected is None and (
                    declared is not None
                    and declared.iso639_2t is not None
                    and not declared.needs_review
                ):
                    # Agreeing authored metadata and nothing read: usable as is.
                    continue
                evidence_records.append(
                    {
                        "stream_id": stream.id,
                        "decision": declared.to_dict() if declared else None,
                        "inference": {
                            "status": "detected" if detected else "unavailable",
                            "method": "caption_text",
                            "consensus": {"iso639_2t": detected, "confidence": detected_confidence},
                        },
                    }
                )
                self._settle_language(
                    stream,
                    settle_track_language(labels, detected, detected_confidence),
                    resolved,
                    unresolved,
                    language_warnings,
                )
                continue
            if stream.kind is not StreamKind.AUDIO:
                continue
            try:
                inference = self.language_runtime.infer(
                    paths.reference,
                    audio_ordinals[stream.id],
                    playlist.duration_seconds,
                    paths.work,
                    self._runner(paths),
                    source_sha256=reference_digest,
                )
            except LanguageInferenceUnavailable as exc:
                evidence_records.append(
                    {
                        "stream_id": stream.id,
                        "decision": declared.to_dict() if declared else None,
                        "inference": {
                            "status": "unavailable",
                            "reason": exc.reason_code,
                        },
                    }
                )
                settlement = settle_track_language(labels)
                if settlement.language is not None and settlement.warning is None:
                    settlement = replace(
                        settlement,
                        warning=(
                            f"the language detection is unavailable ({exc.reason_code}); "
                            f"the disc label {settlement.language} is used"
                        ),
                    )
                self._settle_language(stream, settlement, resolved, unresolved, language_warnings)
                continue
            consensus = inference.get("consensus", {})
            raw = self._declared_language_evidence(declared)
            decision = resolver.resolve(
                mpls=raw["mpls"],
                clpi=raw["clpi"],
                pmt=raw["pmt"],
                matroska=raw.get("matroska"),
                audio_lid=consensus.get("iso639_2t"),
                audio_confidence=float(consensus.get("confidence", 0.0)),
            )
            evidence_records.append(
                {
                    "stream_id": stream.id,
                    "decision": decision.to_dict(),
                    "inference": inference,
                }
            )
            if decision.iso639_2t and not decision.needs_review:
                resolved[stream.id] = decision.iso639_2t
            else:
                self._settle_language(
                    stream,
                    settle_track_language(
                        labels,
                        normalize_iso639_2(consensus.get("iso639_2t")),
                        float(consensus.get("confidence", 0.0)),
                    ),
                    resolved,
                    unresolved,
                    language_warnings,
                    decision=decision,
                )

        report = {
            "schema_version": 1,
            "selection_sha256": _selection_hash(job.selection),
            "scan_fingerprint": scan.fingerprint,
            "playlist_id": selection.playlist_id,
            "status": "needs_review" if unresolved else "completed",
            "resolved_languages": resolved,
            "evidence": evidence_records,
            "unresolved": unresolved,
            "warnings": language_warnings,
        }
        atomic_write_json(paths.language_json, report)
        self._register_artifact(
            job.id,
            paths.language_json,
            DatabaseArtifactKind.REPORT,
            paths.language_json.name,
            mime_type="application/json",
        )
        if unresolved:
            raise ReviewRequired(
                "one or more retained tracks need a confirmed language before encoding",
                details={"tracks": unresolved},
            )
        if language_warnings:
            self.database.add_event(
                EventCreate(
                    job_id=job.id,
                    kind="worker.language-warning",
                    message=(
                        "track languages were chosen with warnings; check them in "
                        "language-inference.json"
                    ),
                    payload={"tracks": language_warnings},
                )
            )
        if not resolved:
            return selection
        return replace(
            selection,
            tracks=tuple(
                replace(item, language=resolved[item.stream_id])
                if item.language is None and item.stream_id in resolved
                else item
                for item in selection.tracks
            ),
        )

    def _preparation_inputs(self, job: Job, scan: DiscScan) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "scan_fingerprint": scan.fingerprint,
            "selection": (
                {k: v for k, v in job.selection.items() if k != "external_sources"}
                if isinstance(job.selection, Mapping)
                else job.selection
            ),
        }

    def _external_fit_is_current(self, paths: JobPaths, selection: ParsedSelection) -> bool:
        """Whether every external source is fitted as selected and approved."""

        for source in selection.external_sources:
            try:
                review = json.loads(
                    (paths.work / "external" / source.id / "review.json").read_text(encoding="utf-8")
                )
            except (OSError, ValueError):
                return False
            if review.get("map_sha256") != source.approved_map_sha256:
                return False
            done = [
                (item.get("stream"), item.get("pitch"), item.get("fill_from"))
                for item in review.get("tracks") or []
            ]
            if done != [(track.stream, track.pitch, track.fill_from) for track in source.tracks]:
                return False
            if len(review.get("subtitles") or []) != len(source.subtitles):
                return False
        return True

    def _remux_preparation_is_current(self, job: Job, paths: JobPaths) -> bool:
        try:
            scan, selection = self._load_scan_and_selection(job, paths)
        except (OSError, TypeError, ValueError, KeyError):
            return False
        return self._external_fit_is_current(paths, selection) and _valid_stage(
            paths.stages / "pipeline-prepare.json",
            self._preparation_inputs(job, scan),
            [paths.reference, self._remux_plan_path(paths), paths.analysis / "eac3to-listing.txt"],
        )

    def _preparation_is_current(self, job: Job, paths: JobPaths) -> bool:
        try:
            scan, _selection = self._load_scan_and_selection(job, paths)
        except (OSError, TypeError, ValueError, KeyError):
            return False
        if not self._external_fit_is_current(paths, _selection):
            return False
        outputs = [paths.reference, paths.script, paths.plan_json]
        if _selection.dynamic_hdr is not DynamicHdrMode.DISCARD:
            outputs.append(paths.analysis / "dynamic-hdr.json")
        if _selection.auto_crf.enabled:
            outputs.append(paths.analysis / "crf-search.json")
        return _valid_stage(
            paths.stages / "pipeline-prepare.json",
            self._preparation_inputs(job, scan),
            outputs,
        )

    def _stage_source(
        self, job: Job, paths: JobPaths, scan: DiscScan, playlist: PlaylistCandidate
    ) -> Path | None:
        """Copy the selected title's disc files to local disk when the disc is on a slow mount.

        Returns the local disc root, or ``None`` when the remux reads the disc in place.
        """

        if not needs_staging(scan.source, mode=self.settings.source_staging):
            return None
        cache_root = self.settings.cache_root
        clips = tuple(dict.fromkeys(segment.clip_id for segment in playlist.segments))
        remove_stale_stages(cache_root, keep=stage_root_for(cache_root, scan.source))
        started = time.monotonic()
        try:
            planned = sum(item.size for item in plan_files(scan.source, clips))
            with self._step(paths, "staging", ("Lemezfájlok helyi másolata", "Local copy of the disc files")) as step:
                staged = stage_disc(
                    scan.source,
                    cache_root,
                    clips=clips,
                    reserve_bytes=planned + STAGE_RESERVE_BYTES,
                    should_stop=lambda: self._process_interrupt_requested(job.id),
                    report=lambda done, total: step.update(
                        done / total if total else None,
                        detail=f"{done / 1e9:.1f} / {total / 1e9:.1f} GB",
                    ),
                )
        except StagingInterrupted as exc:
            raise ProcessInterrupted() from exc
        except (OSError, StagingUnavailable) as exc:
            LOG.warning("job %s: the disc is read in place: %s", job.id, exc)
            self.database.add_event(
                EventCreate(
                    job_id=job.id,
                    kind="worker.source-staging-skipped",
                    message=f"the disc is read in place (no local copy): {exc}",
                    payload={},
                )
            )
            return None
        seconds = time.monotonic() - started
        self.database.add_event(
            EventCreate(
                job_id=job.id,
                kind="worker.source-staged",
                message=(
                    f"title files copied to local disk ({planned / 1e9:.1f} GB "
                    f"in {seconds / 60:.1f} min)"
                ),
                payload={"bytes": planned, "seconds": round(seconds, 1)},
            )
        )
        return staged

    def _materialise_mkv_reference(
        self, job: Job, paths: JobPaths, scan: DiscScan
    ) -> None:
        """Copy an MKV source byte for byte to ``paths.reference``.

        A remux already is the title's reference, so it is copied instead of
        remuxed: a real copy, never a link (the workspace accounting refuses
        links and other devices), hashed while it is written so the stage
        marker needs no second read.  Pause and cancel stop the copy; the
        partial file is removed.
        """

        source = self.settings.authorize_source(job.source_path)
        # The scan's stream list (and every ``-map 0:<index>`` built from it)
        # describes the file it fingerprinted; a replaced or modified file
        # needs a new scan, not a silent copy.
        if (
            source != scan.source
            or not source.is_file()
            or mkv_fingerprint(source) != scan.fingerprint
        ):
            raise ReviewRequired(
                "the MKV source changed since the scan; create the job again "
                "to rescan it",
                details={"code": "mkv_source_changed"},
            )
        before = source.stat()
        total = before.st_size
        paths.work.mkdir(parents=True, exist_ok=True)
        free = shutil.disk_usage(paths.work).free
        if free < total + MKV_REFERENCE_RESERVE_BYTES:
            raise ReviewRequired(
                f"not enough space for the reference copy of the MKV source "
                f"({total / 1e9:.1f} GB needed plus "
                f"{MKV_REFERENCE_RESERVE_BYTES / 1e9:.1f} GB reserve, "
                f"{free / 1e9:.1f} GB free)",
                details={"code": "mkv_reference_space"},
            )
        partial = paths.work / f"{paths.reference.name}.partial"
        digest = hashlib.sha256()
        done = 0
        started = time.monotonic()
        # Operator control is checked at the first block and then every second.
        last_check = started - 1.0
        last_report = started
        label = ("Referencia-másolat (MKV)", "Reference copy (MKV)")
        try:
            with self._step(paths, "remux", label) as step:
                with (
                    ThreadPoolExecutor(max_workers=1) as pool,
                    source.open("rb", buffering=0) as reader,
                    partial.open("wb") as writer,
                ):
                    # The next block is read while this one is hashed and written.
                    pending = pool.submit(reader.read, MKV_COPY_BLOCK_BYTES)
                    while True:
                        chunk = pending.result()
                        if not chunk:
                            break
                        pending = pool.submit(reader.read, MKV_COPY_BLOCK_BYTES)
                        digest.update(chunk)
                        writer.write(chunk)
                        done += len(chunk)
                        now = time.monotonic()
                        if now - last_check >= 1.0:
                            last_check = now
                            if self._process_interrupt_requested(job.id):
                                pending.result()
                                raise ProcessInterrupted(
                                    "operator control stopped the MKV reference copy"
                                )
                        if now - last_report >= 2.0:
                            last_report = now
                            shown = f"{done / 1e9:.1f} / {total / 1e9:.1f} GB"
                            step.update(
                                done / total if total else None,
                                detail=(shown, shown),
                            )
                    writer.flush()
                    os.fsync(writer.fileno())
                after = source.stat()
                if (
                    done != total
                    or after.st_size != before.st_size
                    or after.st_mtime_ns != before.st_mtime_ns
                ):
                    raise ReviewRequired(
                        "the MKV source changed while it was copied",
                        details={"code": "mkv_source_changed"},
                    )
                os.replace(partial, paths.reference)
        finally:
            partial.unlink(missing_ok=True)
        # The digest was taken from the bytes written; the marker reuses it.
        _remember_sha256(paths.reference, digest.hexdigest())
        seconds = time.monotonic() - started
        self.database.add_event(
            EventCreate(
                job_id=job.id,
                kind="worker.mkv-reference-copied",
                message=(
                    f"MKV source copied as the reference ({total / 1e9:.1f} GB "
                    f"in {seconds / 60:.1f} min)"
                ),
                payload={"bytes": total, "seconds": round(seconds, 1)},
            )
        )

    def _crop_decode_acceleration(self, runner: Runner) -> str | None:
        mode = self.settings.crop_hwaccel
        if mode == "cuda":
            return "cuda"
        if (
            mode == "auto"
            and isinstance(runner, CommandRunner)
            and cuda_decode_available()
        ):
            return "cuda"
        return None

    def _source_plan(self, paths: JobPaths, **options: Any) -> ReferenceScriptPlan:
        """A reference script plan with the configured source filter and its index cache."""

        source_filter = SourceFilter(self.settings.source_filter)
        return ReferenceScriptPlan(
            source=paths.reference,
            cache_path=paths.work / "cache" / source_filter.value,
            source_filter=source_filter,
            **options,
        )

    def _source_index_plan(self, paths: JobPaths) -> ReferenceScriptPlan:
        """A script with exactly the reference script's source call, nothing after it.

        The source filters key their index by source file and cache path, so
        the index this script builds is the one every later reference script
        reads.
        """

        return self._source_plan(paths, script_path=paths.work / "source-index.vpy")

    def _start_source_index(self, job: Job, paths: JobPaths) -> _BackgroundRun | None:
        runner = self._runner(paths)
        if not isinstance(runner, CommandRunner):
            return None
        plan = self._source_index_plan(paths)
        content = render_reference_script(plan)
        info = paths.work / "source-index-info.txt"
        inputs = {
            "reference_sha256": sha256_file(paths.reference),
            "script": script_record(plan, content),
        }
        marker = paths.stages / "source-index.json"
        if _valid_stage(marker, inputs, [info]):
            return None
        atomic_write_text(plan.script_path, content)
        live = self._live(paths)
        index_log = paths.logs / "source-index.log"
        label = ("Forrásindex", "Source index")

        def build(cancelled: Callable[[], bool]) -> None:
            runner.run(
                vspipe_info_command(plan.script_path),
                cwd=paths.work,
                stdout_path=info,
                stderr_path=index_log,
                interrupt_requested=cancelled,
                progress_probe=lambda: live.side("index", label, percent_in_tail(index_log)),
            )
            live.side("index", label, 1.0, done=True)
            _write_stage(marker, inputs, [info])

        return _BackgroundRun(build, name=f"source-index-{job.id}")

    @staticmethod
    def _finish_source_index(paths: JobPaths, index_build: _BackgroundRun) -> None:
        """Wait for the index; a failed early build is redone by the next vspipe."""

        try:
            index_build.wait()
        except (ProcessInterrupted, KeyboardInterrupt):
            raise
        except Exception:
            LOG.warning(
                "job %s: building the BestSource index beside the crop scan failed; "
                "the reference script builds it instead",
                paths.root.name,
                exc_info=True,
            )

    def _run_crop_scan(
        self,
        paths: JobPaths,
        *,
        duration_seconds: float,
        full: bool = False,
    ) -> tuple[Path, str]:
        """Find the title's active picture; return the cropdetect log and the scan mode.

        Normally only the keyframes are decoded (about one a second): on the
        GPU when one is available, else in parallel time ranges on the CPU.
        The full decode beside the encode then verifies the crop on every
        frame.  ``full`` (after a failed verification) or too few keyframes
        for a decision decode every frame instead.
        """

        if not full:
            log_path = paths.logs / "crop-detect-keyframes.log"
            self._run_keyframe_crop_scan(paths, log_path, duration_seconds)
            observations = count_crop_observations(
                log_path.read_text(encoding="utf-8", errors="replace")
            )
            if observations >= CROP_MINIMUM_OBSERVATIONS:
                return log_path, "keyframes"
            LOG.info(
                "job %s: only %d keyframe crop observations; scanning every frame",
                paths.root.name,
                observations,
            )
        log_path = paths.logs / "crop-detect-full-title.log"
        self._run_full_crop_scan(paths, log_path, duration_seconds)
        return log_path, "full"

    def _run_keyframe_crop_scan(
        self, paths: JobPaths, log_path: Path, duration_seconds: float
    ) -> None:
        runner = self._runner(paths)
        hwaccel = self._crop_decode_acceleration(runner)
        if hwaccel is not None:
            ((_interval, command),) = keyframe_cropdetect_commands(
                paths.reference, duration_seconds, hwaccel=hwaccel
            )
            try:
                with self._step(paths, "crop-scan", ("Crop-keresés (GPU)", "Crop scan (GPU)")) as step:
                    self._run_reported(
                        paths,
                        command,
                        probe=lambda: step.update(time_fraction(log_path, duration_seconds)),
                        cwd=paths.work,
                        stderr_path=log_path,
                    )
                return
            except ProcessFailure:
                LOG.warning(
                    "job %s: the %s crop scan failed; repeating it on the CPU",
                    paths.root.name,
                    hwaccel,
                )
        # Real runs split the title, at least a minute per range (a shorter one
        # gains nothing); test runners record one command.
        segments = (
            max(1, min(CROP_SCAN_SEGMENTS, int(duration_seconds // 60)))
            if isinstance(runner, CommandRunner)
            else 1
        )
        plan = keyframe_cropdetect_commands(
            paths.reference, duration_seconds, segments=segments
        )
        segment_logs = [
            paths.logs / f"crop-detect-keyframes-{index:02d}.log"
            for index in range(len(plan))
        ]
        label = (
            ("Crop-keresés (CPU)", "Crop scan (CPU)")
            if segments == 1
            else (f"Crop-keresés (CPU, {segments} szál)", f"Crop scan (CPU, {segments} threads)")
        )
        with self._step(paths, "crop-scan", label) as step:

            def probe() -> None:
                covered = 0.0
                for (interval, _command), segment_log in zip(plan, segment_logs):
                    seconds = media_seconds_in_tail(segment_log)
                    if seconds is not None:
                        start = float(interval.start_seconds)
                        covered += min(
                            float(interval.duration_seconds), max(0.0, seconds - start)
                        )
                step.update(covered / duration_seconds)

            def scan(command: list[str], segment_log: Path) -> Callable[[], None]:
                return lambda: self._run_reported(
                    paths,
                    command,
                    probe=probe,
                    cwd=paths.work,
                    stderr_path=segment_log,
                )

            self._run_independent(
                paths,
                [scan(command, log) for (_interval, command), log in zip(plan, segment_logs)],
                max_workers=segments,
            )
        # One log in title order, as the decision and its evidence expect.
        log_path.write_text(
            "".join(
                item.read_text(encoding="utf-8", errors="replace")
                for item in segment_logs
            ),
            encoding="utf-8",
        )
        for item in segment_logs:
            item.unlink(missing_ok=True)

    def _run_full_crop_scan(
        self, paths: JobPaths, log_path: Path, duration_seconds: float
    ) -> None:
        """Decode every frame, on the GPU when available (CPU on failure)."""

        runner = self._runner(paths)
        hwaccel = self._crop_decode_acceleration(runner)
        if hwaccel is not None:
            try:
                with self._step(
                    paths, "crop-scan", ("Teljes crop-keresés (GPU)", "Full crop scan (GPU)")
                ) as step:
                    self._run_reported(
                        paths,
                        full_title_cropdetect_command(paths.reference, hwaccel=hwaccel),
                        probe=lambda: step.update(time_fraction(log_path, duration_seconds)),
                        cwd=paths.work,
                        stderr_path=log_path,
                    )
                return
            except ProcessFailure:
                LOG.warning(
                    "job %s: the %s crop scan failed; repeating it on the CPU",
                    paths.root.name,
                    hwaccel,
                )
        with self._step(paths, "crop-scan", ("Teljes crop-keresés (CPU)", "Full crop scan (CPU)")) as step:
            self._run_reported(
                paths,
                full_title_cropdetect_command(paths.reference),
                probe=lambda: step.update(time_fraction(log_path, duration_seconds)),
                cwd=paths.work,
                stderr_path=log_path,
            )

    @staticmethod
    def _crop_verification_failed(paths: JobPaths, reference_sha256: str) -> bool:
        """Whether the full decode found that the keyframe crop cuts picture."""

        try:
            report = json.loads(
                (paths.analysis / "crop-verification.json").read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            return False
        return (
            isinstance(report, dict)
            and report.get("status") == "needs_review"
            and report.get("reference_sha256") == reference_sha256
        )

    @staticmethod
    def _upload_concurrently(
        client: ImageUploadClient,
        upload_one: Callable[[Path], None],
        pngs: Sequence[Path],
    ) -> None:
        """Upload a few images at a time when the host client allows it.

        After a failure no further upload starts; the ones in flight finish
        (their results reach the checkpoint) before the first error is raised.
        """

        if not getattr(client, "supports_parallel_upload", False) or len(pngs) < 2:
            for png in pngs:
                upload_one(png)
            return
        stop = threading.Event()

        def guarded(png: Path) -> None:
            if stop.is_set():
                return
            try:
                upload_one(png)
            except BaseException:
                stop.set()
                raise

        with ThreadPoolExecutor(
            max_workers=UPLOAD_PARALLELISM, thread_name_prefix="image-upload"
        ) as pool:
            futures = [pool.submit(guarded, png) for png in pngs]
        for future in futures:
            future.result()

    def _run_independent(
        self,
        paths: JobPaths,
        tasks: Sequence[Callable[[], object]],
        *,
        max_workers: int = INDEPENDENT_COMMAND_WORKERS,
    ) -> None:
        """Run tasks that share no inputs or outputs, concurrently on a real runner.

        Every task is waited for before the first error (in task order) is
        raised, so no command keeps running unattended.  Test runners keep the
        sequential order their recorded command lists rely on.
        """

        if len(tasks) < 2 or not isinstance(self._runner(paths), CommandRunner):
            for task in tasks:
                task()
            return
        with ThreadPoolExecutor(
            max_workers=min(max_workers, len(tasks)),
            thread_name_prefix=f"independent-{paths.root.name}",
        ) as pool:
            futures = [pool.submit(task) for task in tasks]
        for future in futures:
            future.result()

    @staticmethod
    def _source_integrity_stage(
        paths: JobPaths, reference_sha256: str
    ) -> tuple[Path, dict[str, Any], list[Path]]:
        """The checkpoint marker, inputs and outputs of the full source decode."""

        inputs = {
            "policy_schema_version": 4,
            "reference_sha256": reference_sha256,
            "context": "source",
            "decode_mode": "full-pixel-decode",
            "crop_verification": "cropdetect-per-frame",
        }
        outputs = [
            paths.analysis / "source-video-integrity.json",
            paths.analysis / "source-video-integrity-progress.txt",
            paths.analysis / "crop-verification.json",
        ]
        return paths.stages / "source-video-integrity.json", inputs, outputs

    def _source_integrity_current(self, paths: JobPaths, reference_sha256: str) -> bool:
        """Whether the full source decode already ran for this reference.

        A decode finished before 3.7.3 logged a cumulative crop maximum, which
        judged the crop at least as strictly as the per-frame log does: its
        verdict stands and the hour-long decode is never repeated for it.
        """

        marker, inputs, outputs = self._source_integrity_stage(paths, reference_sha256)
        return _valid_stage(marker, inputs, outputs) or _valid_stage(
            marker, {**inputs, "crop_verification": "cropdetect-reset0"}, outputs
        )

    def _check_source_integrity(
        self,
        paths: JobPaths,
        reference_sha256: str,
        *,
        cancelled: Callable[[], bool] | None = None,
        low_priority: bool = False,
        duration_seconds: float | None = None,
    ) -> None:
        """Fully decode the reference video and enforce the source diagnostics history.

        Runs beside the video encode (``cancelled`` stops it, ``low_priority``
        leaves the CPU to the encoder); a failure raises ``ReviewRequired``.
        Its progress is shown as a side task of the running step.
        """

        integrity_marker, integrity_inputs, outputs = self._source_integrity_stage(
            paths, reference_sha256
        )
        integrity_report, integrity_progress, _crop_verification = outputs
        integrity_log = paths.logs / "source-video-integrity.log"
        if not self._source_integrity_current(paths, reference_sha256):
            command = source_video_integrity_command(
                paths.reference, threads=INTEGRITY_DECODE_THREADS, cropdetect=True
            )
            if low_priority and os.name == "posix" and shutil.which("nice"):
                command = ["nice", "-n", "10", *command]
            options: dict[str, Any] = (
                {} if cancelled is None else {"interrupt_requested": cancelled}
            )
            live = self._live(paths)
            label = ("Forrás-integritás ellenőrzése", "Source integrity check")
            failure: ProcessFailure | None = None
            try:
                self._run_reported(
                    paths,
                    command,
                    probe=lambda: live.side(
                        "integrity",
                        label,
                        time_fraction(integrity_progress, duration_seconds),
                    ),
                    cwd=paths.work,
                    stdout_path=integrity_progress,
                    stderr_path=integrity_log,
                    **options,
                )
            except ProcessFailure as exc:
                failure = exc
            live.side("integrity", label, 1.0, done=True)
            source_log_paths = sorted(
                {
                    *paths.logs.glob("reference-remux*.log"),
                    *paths.logs.glob("source-video-integrity*.log"),
                },
                key=lambda item: item.name,
            )
            source_text = "\n".join(
                self._source_log_text(paths, path)
                for path in source_log_paths
                if path.is_file()
            )
            diagnostics = classify_media_diagnostics(source_text, context="source")
            current_log_paths = (
                paths.logs / "reference-remux.log",
                integrity_log,
            )
            current_diagnostics = classify_media_diagnostics(
                "\n".join(
                    self._source_log_text(paths, path)
                    for path in current_log_paths
                    if path.is_file()
                ),
                context="source",
            )
            sticky_diagnostics = _sticky_source_diagnostics(diagnostics)
            current_requires_review = any(
                item.requires_review for item in current_diagnostics
            )
            needs_review = (
                failure is not None
                or current_requires_review
                or bool(sticky_diagnostics)
            )
            atomic_write_json(
                integrity_report,
                {
                    "schema_version": 2,
                    "status": "needs_review" if needs_review else "passed",
                    "command_failed": failure is not None,
                    "sticky_history": [path.name for path in source_log_paths],
                    "diagnostics": [item.to_dict() for item in diagnostics],
                },
            )
            if needs_review:
                public_diagnostics = (
                    *current_diagnostics,
                    *sticky_diagnostics,
                )
                raise ReviewRequired(
                    "source video integrity diagnostics require review",
                    details={
                        "report": integrity_report.name,
                        "diagnostics": _public_diagnostic_summary(public_diagnostics),
                    },
                )
            self._verify_crop(paths, reference_sha256, integrity_log)
            _write_stage(integrity_marker, integrity_inputs, outputs)
        self._enforce_source_history(paths)

    def _verify_crop(
        self, paths: JobPaths, reference_sha256: str, log_path: Path
    ) -> None:
        """Check the crop against every frame the integrity decode saw.

        Preparation chooses the crop from the keyframes.  A shot shorter than a
        keyframe interval that shows more picture (a full-frame insert in a
        scope film) appears only here; a crop that would cut into it for at
        least half a second stops the job for review and drops the crop
        checkpoint, so a restart scans every frame and encodes with the crop
        that keeps the whole picture.  A shorter flash in the bar is recorded
        as a ``worker.crop-verification-warning`` and the job continues.

        An automatic crop that follows the detected border instead of the widest
        canvas is checked against that canvas too.  Too many frames past it stop
        the job the same way, and the restart keeps the canvas; a few are recorded
        as a ``worker.crop-tight-reach``.
        """

        report = paths.analysis / "crop-verification.json"
        try:
            crop_document = json.loads(
                (paths.analysis / "crop-policy.json").read_text(encoding="utf-8")
            )
            used = ActiveCropMargins(**crop_document["decision"]["requested"])
            source_width = int(crop_document["evidence"]["source_width"])
            source_height = int(crop_document["evidence"]["source_height"])
            release_safe = (
                ActiveCropMargins(**crop_document["decision"]["release_safe"])
                if crop_document.get("selection_mode") == "automatic"
                else None
            )
        except (OSError, KeyError, TypeError, ValueError) as exc:
            raise ReviewRequired(f"crop verification needs the crop report: {exc}") from exc
        try:
            verification = verify_crop_against_full_decode(
                log_path.read_text(encoding="utf-8", errors="replace"),
                used,
                source_width=source_width,
                source_height=source_height,
                release_safe=release_safe,
            )
        except CropPolicyError as exc:
            atomic_write_json(
                report,
                {
                    "schema_version": 1,
                    "status": "needs_review",
                    "reference_sha256": reference_sha256,
                    "code": exc.code,
                    "message": str(exc),
                },
            )
            raise ReviewRequired(
                f"crop verification requires review: {exc}",
                details={"code": exc.code, "report": report.name},
            ) from exc
        flashes = verification.passed and verification.flash_runs > 0
        atomic_write_json(
            report,
            {
                "schema_version": 2,
                "status": (
                    "needs_review"
                    if not verification.passed
                    else "passed_with_warnings" if flashes else "passed"
                ),
                "reference_sha256": reference_sha256,
                **verification.to_dict(),
            },
        )
        if flashes:
            # A bright frame in the bar (a flash, a logo, dust, grain in an HDR
            # bar) is no lost picture: the crop stays and the job continues.
            self.database.add_event(
                EventCreate(
                    job_id=paths.root.name,
                    kind="worker.crop-verification-warning",
                    message=verification.summary(),
                    payload={
                        "report": report.name,
                        "flash_runs": verification.flash_runs,
                        "cut_frames": verification.cut_frames,
                        "minimum_persistent_seconds": (
                            verification.minimum_persistent_seconds
                        ),
                        "runs": [run.to_dict() for run in verification.flashes[:5]],
                    },
                )
            )
        if verification.passed and any(
            item.frames_past for item in verification.tight_edges
        ):
            self.database.add_event(
                EventCreate(
                    job_id=paths.root.name,
                    kind="worker.crop-tight-reach",
                    message=(
                        "crop verification: the automatic crop follows the detected "
                        f"border; {verification.tight_summary()}"
                    ),
                    payload={
                        "report": report.name,
                        "edges": [item.to_dict() for item in verification.tight_edges],
                    },
                )
            )
        if not verification.passed:
            (paths.stages / "crop-policy.json").unlink(missing_ok=True)
            raise ReviewRequired(
                f"crop verification: {verification.summary()}; cancel and restart "
                "the job: preparation then scans every frame and the encode keeps "
                "the whole picture",
                details={"code": "crop_cuts_picture", "report": report.name},
            )

    @staticmethod
    def _clip_join_report(paths: JobPaths) -> dict[str, Any] | None:
        """The clip-join verification of the current reference, when it passed."""

        reference_sha256 = _recorded_output_sha256(
            paths.stages / "reference-remux.json", paths.reference
        )
        try:
            report = json.loads(
                (paths.analysis / "clip-joins.json").read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            return None
        if (
            isinstance(report, dict)
            and report.get("verified") is True
            and reference_sha256 is not None
            and report.get("reference_sha256") == reference_sha256
            and isinstance(report.get("joins"), list)
        ):
            return report
        return None

    def _source_log_text(self, paths: JobPaths, log_path: Path) -> str:
        """A source log for diagnosis; a remux log without its verified join messages."""

        text = log_path.read_text(encoding="utf-8", errors="replace")
        if not log_path.name.startswith("reference-remux"):
            return text
        report = self._clip_join_report(paths)
        if report is None:
            return text
        split = split_clip_join_lines(
            text, len(report["joins"]), moments=_clip_join_moments(report)
        )
        return text if split is None else split[0]

    def _verify_clip_joins(
        self, paths: JobPaths, playlist: PlaylistCandidate, reference_sha256: str
    ) -> None:
        """Decode the reference strictly across the clip joins the remux logged.

        libbluray plays a multi-clip playlist as one stream: at every join the
        remux logs timestamp jumps, and it may report the earlier clip's cut
        last packet ("Packet corrupt", a TrueHD parity error).  When the
        picture and every sound stream decode cleanly across each join, those
        join messages are not source damage, and the source checks leave them
        out (``analysis/clip-joins.json``).  Every other message is judged as
        before.
        """

        joins = _playlist_join_seconds(playlist)
        # The title's last packet is cut like a clip's at a join.
        title_end = (
            float(playlist.duration_seconds) if playlist.duration_seconds > 0 else None
        )
        moments = [*joins, *([title_end] if title_end is not None else [])]
        if not moments:
            return
        current = self._clip_join_report(paths)
        if (
            current is not None
            and current.get("joins") == joins
            # A report from before 3.7.3 covers the joins only; its strict
            # decode is not repeated for the title end.
            and (current.get("title_end") == title_end or "title_end" not in current)
        ):
            return
        report_path = paths.analysis / "clip-joins.json"
        join_messages: list[str] = []
        end_messages: list[str] = []
        for log_path in sorted(paths.logs.glob("reference-remux*.log")):
            text = log_path.read_text(encoding="utf-8", errors="replace")
            split = split_clip_join_lines(text, len(joins), moments=joins)
            with_end = split_clip_join_lines(text, len(joins), moments=moments)
            if split is None or with_end is None:
                atomic_write_json(
                    report_path,
                    {
                        "schema_version": 2,
                        "reference_sha256": reference_sha256,
                        "joins": joins,
                        "title_end": title_end,
                        "verified": False,
                        "reason": f"{log_path.name} has more timestamp jumps than the playlist has clip joins",
                    },
                )
                return
            join_messages.extend(split[1])
            # The messages only the end of the title explains.
            end_messages.extend((Counter(with_end[1]) - Counter(split[1])).elements())
        if not join_messages and not end_messages:
            return
        # The joins and the title end are decoded only when they logged
        # something; a failed end decode leaves the joins' verdict alone.
        checks = [
            *((moment, False) for moment in (joins if join_messages else [])),
            *([(title_end, True)] if end_messages and title_end is not None else []),
        ]
        failed: list[float] = []
        end_failed = False
        runner = self._runner(paths)
        with self._step(paths, "clip-joins", ("Klipillesztések ellenőrzése", "Checking clip joins")) as step:
            for number, (moment, is_end) in enumerate(checks, start=1):
                try:
                    runner.run(
                        clip_join_decode_command(paths.reference, moment),
                        cwd=paths.work,
                        stderr_path=paths.logs / f"clip-join-{number:02d}.log",
                    )
                except ProcessFailure:
                    if is_end:
                        end_failed = True
                    else:
                        failed.append(moment)
                step.update(number / len(checks))
        title_end_verified = bool(end_messages) and not end_failed
        atomic_write_json(
            report_path,
            {
                "schema_version": 2,
                "reference_sha256": reference_sha256,
                "joins": joins,
                "title_end": title_end,
                "verified": not failed,
                "failed_joins": failed,
                "title_end_verified": title_end_verified,
                "join_messages": [*join_messages, *(end_messages if title_end_verified else [])][:100],
            },
        )
        excused = len(join_messages) if not failed else 0
        if title_end_verified:
            excused += len(end_messages)
        if excused:
            self.database.add_event(
                EventCreate(
                    job_id=paths.root.name,
                    kind="worker.clip-joins-verified",
                    message=(
                        f"{excused} remux message(s) at {len(joins)} clip join(s) "
                        "and the end of the title; the strict decode there is clean"
                        if title_end_verified
                        else f"{excused} remux message(s) at {len(joins)} clip "
                        "join(s); the strict decode across the joins is clean"
                    ),
                    payload={"joins": joins, "title_end": title_end},
                )
            )

    def _enforce_source_history(self, paths: JobPaths) -> None:
        """Stop on corruption that any remux or source decode attempt has reported.

        Corruption reported by an earlier remux/decode attempt remains material
        even after a later retry succeeds.  CommandRunner preserves those stderr
        files as attempt-NN logs, so the history is enforced on every resume
        instead of trusting only the latest base log/marker.  Reading the logs
        is cheap, so preparation checks the remux before the encode starts.
        """

        integrity_report = paths.analysis / "source-video-integrity.json"
        historical_source_logs = sorted(
            {
                *paths.logs.glob("reference-remux*.log"),
                *paths.logs.glob("source-video-integrity*.log"),
            },
            key=lambda item: item.name,
        )
        historical_diagnostics = classify_media_diagnostics(
            "\n".join(
                self._source_log_text(paths, path)
                for path in historical_source_logs
                if path.is_file()
            ),
            context="source",
        )
        sticky_failures = _sticky_source_diagnostics(historical_diagnostics)
        if sticky_failures:
            atomic_write_json(
                integrity_report,
                {
                    "schema_version": 2,
                    "status": "needs_review",
                    "command_failed": False,
                    "sticky_history": [path.name for path in historical_source_logs],
                    "diagnostics": [item.to_dict() for item in historical_diagnostics],
                },
            )
            raise ReviewRequired(
                "source corruption appeared in the retained command history",
                details={
                    "report": integrity_report.name,
                    "diagnostics": _public_diagnostic_summary(sticky_failures),
                },
            )

    def _prepare_reference(
        self,
        job: Job,
        paths: JobPaths,
        scan: DiscScan,
        selection: ParsedSelection,
        playlist: PlaylistCandidate,
    ) -> str:
        """The lossless reference remux of the playlist, checked; its SHA-256.

        Shared by encodes and remuxes: a remux's QC compares its output with
        this independent FFmpeg demux of the same playlist.
        """

        pcm_bluray_audio: list[PcmBlurayAudio] = []
        for ordinal, stream in enumerate(playlist.audio_streams):
            if stream.codec.casefold() != "pcm_bluray":
                continue
            if stream.bit_depth is None:
                raise ReviewRequired(
                    f"Blu-ray PCM stream {stream.id} has no verified bit depth"
                )
            try:
                pcm_bluray_audio.append(PcmBlurayAudio(ordinal, stream.bit_depth))
            except ValueError as exc:
                raise ReviewRequired(
                    f"Blu-ray PCM stream {stream.id} has an unsupported bit depth: "
                    f"{stream.bit_depth}"
                ) from exc
        if scan.is_mkv:
            remux_inputs = _mkv_reference_inputs(scan, selection.playlist_id)
        else:
            remux_inputs = {
                "scan_fingerprint": scan.fingerprint,
                "playlist_id": selection.playlist_id,
                "angle": selection.angle,
                "pcm_bluray_audio": [asdict(item) for item in pcm_bluray_audio],
                "source_clips": _playlist_source_snapshot(scan, selection.playlist_id),
            }
        remux_marker = paths.stages / "reference-remux.json"
        try:
            _activate_source_log_generation(
                logs_root=paths.logs,
                generation_record=(paths.analysis / "source-integrity-generation.json"),
                remux_marker=remux_marker,
                generation=_json_hash(remux_inputs),
            )
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ReviewRequired(
                f"source integrity generation record is invalid: {exc}"
            ) from exc
        if scan.is_mkv:
            if not _valid_stage(remux_marker, remux_inputs, [paths.reference]):
                self._materialise_mkv_reference(job, paths, scan)
                _write_stage(remux_marker, remux_inputs, [paths.reference])
        elif not _valid_stage(remux_marker, remux_inputs, [paths.reference]):
            disc_root = self._stage_source(job, paths, scan, playlist) or scan.source
            command = reference_remux_command(
                ReferenceRemuxPlan(
                    disc_root=disc_root,
                    playlist_id=selection.playlist_id,
                    output_path=paths.reference,
                    angle=selection.angle,
                    pcm_bluray_audio=tuple(pcm_bluray_audio),
                )
            )
            remux_log = paths.logs / "reference-remux.log"
            with self._step(paths, "remux", ("Referencia-remux", "Reference remux")) as step:
                self._run_reported(
                    paths,
                    command,
                    probe=lambda: step.update(
                        time_fraction(remux_log, playlist.duration_seconds)
                    ),
                    cwd=paths.work,
                    stderr_path=remux_log,
                )
            _write_stage(remux_marker, remux_inputs, [paths.reference])
            if disc_root != scan.source:
                remove_stage(self.settings.cache_root, scan.source)

        with self._step(paths, "reference-hash", ("Referencia ellenőrzőösszege", "Reference checksum")):
            reference_sha256 = sha256_file(paths.reference)
        # The full decode of the reference (source integrity) runs beside the
        # video encode; preparation only enforces what the remux reported,
        # after checking the playlist's clip joins.
        self._verify_clip_joins(paths, playlist, reference_sha256)
        self._enforce_source_history(paths)
        return reference_sha256

    def _prepare(self, job: Job, paths: JobPaths, *, advance: bool = True) -> None:
        scan, selection = self._load_scan_and_selection(job, paths)
        playlist = scan.playlist(selection.playlist_id)
        reference_sha256 = self._prepare_reference(job, paths, scan, selection, playlist)
        self._prepare_external_sources(paths, selection, playlist, reference_sha256)
        source_video = playlist.video_streams[0].video
        assert source_video is not None
        crop_report = paths.analysis / "crop-policy.json"
        crop_marker = paths.stages / "crop-policy.json"

        if playlist.duration_seconds <= 0:
            raise ReviewRequired(
                "title duration must be positive for distributed crop and QC sampling"
            )
        if source_video.width is None or source_video.height is None:
            raise ReviewRequired(
                "source dimensions are required for distributed crop validation"
            )
        crop_inputs = self._crop_policy_inputs(
            scan,
            selection,
            reference_sha256=reference_sha256,
        )
        # BestSource's frame index needs a full CPU decode of the reference;
        # it is built while the crop scan decodes on the GPU.
        index_build = self._start_source_index(job, paths)
        try:
            if not _valid_stage(crop_marker, crop_inputs, [crop_report]):
                verification_failed = self._crop_verification_failed(
                    paths, reference_sha256
                )
                crop_log_path, crop_scan_mode = self._run_crop_scan(
                    paths,
                    duration_seconds=float(playlist.duration_seconds),
                    full=verification_failed,
                )
                crop_log = crop_log_path.read_text(encoding="utf-8", errors="replace")
                try:
                    try:
                        crop_evidence = parse_stable_cropdetect(
                            crop_log,
                            source_width=source_video.width,
                            source_height=source_video.height,
                        )
                    except CropPolicyError as unstable:
                        # A title that changes aspect ratio has no dominant border;
                        # accept it only when the log is a clean few-step envelope.
                        explained = (
                            variable_aspect_evidence(
                                crop_log,
                                source_width=source_video.width,
                                source_height=source_video.height,
                                duration_seconds=float(playlist.duration_seconds),
                            )
                            if unstable.code == "unstable_detection"
                            else None
                        )
                        if explained is None:
                            raise
                        crop_evidence = explained
                    requested_crop = ActiveCropMargins(
                        left=selection.crop.left,
                        top=selection.crop.top,
                        right=selection.crop.right,
                        bottom=selection.crop.bottom,
                    )
                    automatic = not any(asdict(requested_crop).values())
                    aspect_profile = parse_aspect_profile(
                        crop_log,
                        source_width=source_video.width,
                        source_height=source_video.height,
                        duration_seconds=float(playlist.duration_seconds),
                    )
                    effective_crop = (
                        automatic_crop(
                            crop_evidence,
                            widest_only=verification_failed
                            or (aspect_profile is not None and aspect_profile.variable),
                        )
                        if automatic
                        else requested_crop
                    )
                    crop_decision = validate_operator_crop(effective_crop, crop_evidence)
                except CropPolicyError as exc:
                    atomic_write_json(
                        crop_report,
                        {
                            "schema_version": 1,
                            "status": "needs_review",
                            "code": exc.code,
                            "message": str(exc),
                        },
                    )
                    raise ReviewRequired(
                        f"crop policy requires review: {exc}",
                        details={"code": exc.code, "report": crop_report.name},
                    ) from exc
                atomic_write_json(
                    crop_report,
                    {
                        "schema_version": 1,
                        "status": "passed",
                        "selection_mode": "automatic" if automatic else "manual",
                        "tightened_edges": list(
                            tightened_edges(effective_crop, crop_decision.release_safe)
                        ),
                        "scan": crop_scan_mode,
                        "evidence": crop_evidence.to_dict(),
                        "decision": crop_decision.to_dict(),
                        "aspect_profile": (
                            aspect_profile.to_dict() if aspect_profile else None
                        ),
                    },
                )
                _write_stage(crop_marker, crop_inputs, [crop_report])
                if aspect_profile is not None and aspect_profile.variable:
                    self.database.add_event(
                        EventCreate(
                            job_id=job.id,
                            kind="worker.variable-aspect",
                            message=aspect_profile.summary(),
                            payload=aspect_profile.to_dict(),
                        )
                    )

            try:
                crop_document = json.loads(crop_report.read_text(encoding="utf-8"))
                effective_crop_raw = crop_document["decision"]["requested"]
                effective_crop = VapourSynthCrop(**effective_crop_raw)
            except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                raise ReviewRequired(f"automatic crop report is invalid: {exc}") from exc
            if effective_crop != selection.crop:
                effective_selection = parse_selection(
                    job,
                    scan,
                    crop_override=effective_crop,
                )
                selection = replace(effective_selection, tracks=selection.tracks)
                self.database.add_event(
                    EventCreate(
                        job_id=job.id,
                        kind="worker.auto-crop",
                        message="automatic crop applied from full-title evidence",
                        payload={"crop": asdict(effective_crop)},
                    )
                )

            # Resolve uncertain retained audio tracks now: this avoids discovering
            # a language problem only after a multi-hour video encode. Manual track
            # language choices remain authoritative and skip content inference.
            with self._step(paths, "language", ("Hangsávok nyelvének ellenőrzése", "Checking audio track languages")):
                selection = self._resolve_selected_languages(job, scan, selection, paths)
        except BaseException:
            if index_build is not None:
                index_build.cancel()
            raise
        if index_build is not None:
            with self._step(paths, "source-index", ("Forrásindex befejezése", "Finishing the source index")):
                self._finish_source_index(paths, index_build)
        try:
            dynamic_plan = resolve_selection_dynamic_hdr(scan, selection)
        except DynamicHdrError as exc:
            raise ReviewRequired(
                f"dynamic HDR retention is not possible: {exc}",
                details={"code": f"dynamic_hdr_{exc.code}"},
            ) from exc
        plan_request = EncodeRequest(
            scan=scan,
            playlist_id=selection.playlist_id,
            settings=selection.settings,
            work_dir=paths.work,
            output_path=paths.muxed_output,
            track_selections=selection.tracks,
            field_handling=_field_handling(selection.temporal_filter),
            crop=_planner_crop(selection.crop),
            angle=selection.angle,
            overwrite=True,
            dynamic_hdr=dynamic_plan.mode.value,
            allow_dub_default=selection.dub_may_be_default,
            tracker_profile=selection.tracker_profile.value,
        )
        try:
            encode_plan = EncodePlanner(work_root=self.settings.data_root).build(
                plan_request
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ReviewRequired(f"selection cannot be planned safely: {exc}") from exc
        # This plan is produced only after an explicit operator selection.  Its
        # advisory warnings remain durable evidence, but do not create an
        # unresumable review loop (for example an intentional Atmos -> FLAC
        # choice). Missing or contradictory data has already raised above.
        if encode_plan.warnings:
            self.database.add_event(
                EventCreate(
                    job_id=job.id,
                    kind="worker.plan-warning",
                    message="encode plan contains advisory warnings",
                    payload={"warnings": list(encode_plan.warnings)},
                )
            )
        atomic_write_json(paths.plan_json, encode_plan.to_dict())

        script_plan = self._source_plan(
            paths,
            script_path=paths.script,
            temporal_filter=selection.temporal_filter,
            crop=selection.crop,
        )
        content = render_reference_script(script_plan)
        script_inputs = {
            "reference_sha256": sha256_file(paths.reference),
            "plan": script_record(script_plan, content),
        }
        script_marker = paths.stages / "reference-script.json"
        script_record_path = paths.work / "reference-script.json"
        if not _valid_stage(
            script_marker, script_inputs, [paths.script, script_record_path]
        ):
            atomic_write_text(paths.script, content)
            atomic_write_json(script_record_path, script_record(script_plan, content))
            _write_stage(
                script_marker, script_inputs, [paths.script, script_record_path]
            )
        prepared_outputs = [paths.reference, paths.script, paths.plan_json]
        final_dynamic = dynamic_plan
        if selection.dynamic_hdr is not DynamicHdrMode.DISCARD:
            with self._step(paths, "dynamic-hdr", ("Dinamikus HDR-metaadat kinyerése", "Extracting dynamic HDR metadata")):
                final_dynamic = self._dynamic_hdr(job, paths, scan, selection, dynamic_plan)
            selection = replace(
                selection,
                settings=_settings_for_dynamic_hdr(selection.settings, final_dynamic),
            )
            prepared_outputs.append(paths.analysis / "dynamic-hdr.json")
        if selection.auto_crf.enabled:
            with self._step(paths, "auto-crf", ("Automatikus CRF-keresés", "Automatic CRF search")):
                outcome = self._auto_crf(job, paths, scan, selection)
            if outcome.chosen_crf is not None:
                selection = replace(
                    selection,
                    settings=replace(selection.settings, crf=outcome.chosen_crf),
                )
            prepared_outputs.append(paths.analysis / "crf-search.json")
        if (
            selection.settings != plan_request.settings
            or final_dynamic.mode is not dynamic_plan.mode
        ):
            try:
                final_plan = EncodePlanner(work_root=self.settings.data_root).build(
                    replace(
                        plan_request,
                        settings=selection.settings,
                        dynamic_hdr=final_dynamic.mode.value,
                    )
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise ReviewRequired(
                    f"the tuned encode settings cannot be planned safely: {exc}"
                ) from exc
            atomic_write_json(paths.plan_json, final_plan.to_dict())
        self._register_artifact(
            job.id,
            paths.plan_json,
            DatabaseArtifactKind.MANIFEST,
            "encode-plan.json",
            mime_type="application/json",
        )
        _write_stage(
            paths.stages / "pipeline-prepare.json",
            self._preparation_inputs(job, scan),
            prepared_outputs,
        )
        if advance:
            self.queue.advance(
                job.id, JobState.ENCODING, message="reference timeline prepared"
            )

    def _reference_info(self, paths: JobPaths) -> Any:
        """Frame count and rate of the reviewed reference graph (checkpointed)."""

        info_path = paths.work / "reference-info.txt"
        inputs = {
            "script_sha256": sha256_file(paths.script),
            "reference_sha256": sha256_file(paths.reference),
        }
        marker = paths.stages / "reference-info.json"
        if not _valid_stage(marker, inputs, [info_path]):
            self._runner(paths).run(
                vspipe_info_command(paths.script),
                cwd=paths.work,
                stdout_path=info_path,
                stderr_path=paths.logs / "reference-info.log",
            )
            _write_stage(marker, inputs, [info_path])
        return parse_vspipe_info(info_path.read_text(encoding="utf-8", errors="replace"))

    def _dynamic_hdr(
        self,
        job: Job,
        paths: JobPaths,
        scan: DiscScan,
        selection: ParsedSelection,
        plan: DynamicHdrPlan,
    ) -> DynamicHdrPlan:
        """Extract and verify HDR10+/Dolby Vision metadata for retention.

        The stage only runs when the operator asked for retention.  Extraction
        output is proven frame-aligned with the reviewed reference timeline
        before it may reach the encoder; anything else is a review, never a
        silent downgrade (except for the explicit ``auto`` mode).
        """

        report = paths.analysis / "dynamic-hdr.json"
        selection_sha256 = _selection_hash(job.selection)
        work = paths.work / "dynamic-hdr"
        work.mkdir(mode=0o750, parents=True, exist_ok=True)
        runner = self._runner(paths)

        state: Mapping[str, Any] = {}
        if plan.retained:
            key = "hdr10plus" if plan.mode is DynamicHdrMode.HDR10PLUS else "dolby_vision"
            state = dynamic_hdr_support().get(key, {})
            if not state.get("available"):
                problem = (
                    f"{plan.mode.value} retention needs {plan.required_tool}"
                    + (
                        " and an x265 build that accepts the Dolby Vision parameters"
                        if plan.mode is DynamicHdrMode.DOLBY_VISION
                        else ""
                    )
                    + f" (tool: {state.get('tool_available')}, "
                    f"x265: {state.get('x265_supported')})"
                )
                if selection.dynamic_hdr is DynamicHdrMode.AUTO:
                    plan = DynamicHdrPlan(
                        plan.requested, DynamicHdrMode.DISCARD, problem
                    )
                else:
                    raise ReviewRequired(
                        problem,
                        details={
                            "code": "dynamic_hdr_tool_missing",
                            "support": dict(state),
                        },
                    )

        if not plan.retained:
            atomic_write_json(
                report,
                {
                    "schema_version": 1,
                    "status": "discarded",
                    "selection_sha256": selection_sha256,
                    "plan": plan.to_dict(),
                },
            )
            self.database.add_event(
                EventCreate(
                    job_id=job.id,
                    kind="worker.dynamic-hdr",
                    message=f"dynamic HDR is discarded: {plan.reason}",
                    payload=plan.to_dict(),
                )
            )
            return plan

        plus = plan.mode is DynamicHdrMode.HDR10PLUS
        metadata = work / ("hdr10plus.json" if plus else "rpu.bin")
        summary_path = work / "dovi-summary.txt"
        outputs = [metadata] if plus else [metadata, summary_path]
        try:
            info = self._reference_info(paths)
        except FrameSelectionError as exc:
            raise ReviewRequired(
                f"dynamic HDR cannot read the reference timeline: {exc}"
            ) from exc
        inputs = {
            "policy_schema_version": 1,
            "reference_sha256": sha256_file(paths.reference),
            "plan": plan.to_dict(),
            "tool_version": state.get("tool_version"),
            "output_frames": info.frames,
        }
        marker = paths.stages / "dynamic-hdr.json"
        if not _valid_stage(marker, inputs, outputs):
            metadata.unlink(missing_ok=True)
            commands = (
                hdr10plus_extract_commands(paths.reference, metadata)
                if plus
                else dovi_extract_commands(paths.reference, metadata, plan)
            )
            runner.run_pipeline(
                commands,
                cwd=paths.work,
                stderr_paths=[
                    paths.logs / "dynamic-hdr-source.log",
                    paths.logs / "dynamic-hdr-extract.log",
                ],
            )
            try:
                if plus:
                    counted = parse_hdr10plus_json(
                        metadata.read_text(encoding="utf-8")
                    )
                    require_frame_alignment(
                        counted.frames, info.frames, what="the HDR10+ metadata"
                    )
                else:
                    runner.run(
                        dovi_summary_command(metadata),
                        cwd=paths.work,
                        stdout_path=summary_path,
                        stderr_path=paths.logs / "dynamic-hdr-summary.log",
                    )
                    counted = parse_dovi_summary(
                        summary_path.read_text(encoding="utf-8", errors="replace")
                    )
                    require_dolby_vision_profile(counted)
                    require_frame_alignment(
                        counted.frames, info.frames, what="the Dolby Vision RPU"
                    )
            except (DynamicHdrError, OSError, UnicodeError) as exc:
                code = getattr(exc, "code", "unreadable")
                raise ReviewRequired(
                    f"extracted dynamic HDR metadata was rejected: {exc}",
                    details={"code": f"dynamic_hdr_{code}"},
                ) from exc
            _write_stage(marker, inputs, outputs)

        if plus:
            counted = parse_hdr10plus_json(metadata.read_text(encoding="utf-8"))
        else:
            counted = parse_dovi_summary(
                summary_path.read_text(encoding="utf-8", errors="replace")
            )
        atomic_write_json(
            report,
            {
                "schema_version": 1,
                "status": "retained",
                "selection_sha256": selection_sha256,
                "plan": plan.to_dict(),
                "tool": plan.required_tool,
                "tool_version": state.get("tool_version"),
                "output_frames": info.frames,
                "summary": counted.to_dict(),
                "metadata": {
                    "name": metadata.name,
                    "sha256": sha256_file(metadata),
                    "size_bytes": metadata.stat().st_size,
                },
            },
        )
        self._register_artifact(
            job.id,
            report,
            DatabaseArtifactKind.MANIFEST,
            "dynamic-hdr.json",
            mime_type="application/json",
        )
        self.database.add_event(
            EventCreate(
                job_id=job.id,
                kind="worker.dynamic-hdr",
                message=f"{plan.mode.value} metadata verified for {info.frames} frames",
                payload={**plan.to_dict(), "summary": counted.to_dict()},
            )
        )
        return plan

    def _load_dynamic_hdr(
        self, job: Job, paths: JobPaths, selection: ParsedSelection
    ) -> tuple[DynamicHdrPlan, Path | None, str | None]:
        """Reload the verified plan and its hash-pinned metadata file."""

        report = paths.analysis / "dynamic-hdr.json"
        try:
            document = json.loads(report.read_text(encoding="utf-8"))
            if (
                document.get("schema_version") != 1
                or document.get("selection_sha256") != _selection_hash(job.selection)
            ):
                raise ValueError("report does not describe this selection")
            plan = DynamicHdrPlan.from_dict(document["plan"])
            if not plan.retained:
                return plan, None, None
            metadata = paths.work / "dynamic-hdr" / str(document["metadata"]["name"])
            expected = str(document["metadata"]["sha256"])
            if sha256_file(metadata) != expected:
                raise ValueError("extracted metadata changed after verification")
            return plan, metadata, expected
        except (
            OSError,
            KeyError,
            TypeError,
            ValueError,
            DynamicHdrError,
            json.JSONDecodeError,
        ) as exc:
            raise ReviewRequired(
                f"dynamic HDR report is missing or stale: {exc}",
                details={"code": "dynamic_hdr_report", "report": report.name},
            ) from exc

    def _auto_crf(
        self,
        job: Job,
        paths: JobPaths,
        scan: DiscScan,
        selection: ParsedSelection,
    ) -> CrfSearchOutcome:
        """Choose the release CRF from short VMAF-scored sample encodes.

        Every probe is an independent checkpoint, so a pause, cancellation or
        restart resumes after the last completed probe instead of repeating it.
        The final report is hash-pinned by the ``pipeline-prepare`` marker.
        """

        config = selection.auto_crf
        work = paths.work / "crf-search"
        work.mkdir(mode=0o750, parents=True, exist_ok=True)
        report = paths.analysis / "crf-search.json"
        runner = self._runner(paths)
        selection_sha256 = _selection_hash(job.selection)

        reference_sha256 = sha256_file(paths.reference)
        try:
            info = self._reference_info(paths)
            windows = plan_sample_windows(
                info.frames,
                Fraction(info.fps_numerator, info.fps_denominator),
                samples=config.samples,
                sample_seconds=config.sample_seconds,
            )
        except (FrameSelectionError, CrfSearchError) as exc:
            raise ReviewRequired(
                f"automatic CRF search cannot sample this title: {exc}",
                details={"code": "crf_search_unplannable"},
            ) from exc

        sample_script = work / "sample.vpy"
        sample_plan = self._source_plan(
            paths,
            script_path=sample_script,
            temporal_filter=selection.temporal_filter,
            crop=selection.crop,
            sample_windows=tuple((w.start_frame, w.frame_count) for w in windows),
        )
        sample_content = render_reference_script(sample_plan)
        atomic_write_text(sample_script, sample_content)
        base_settings = (
            selection.settings
            if config.probe_preset is None
            else replace(selection.settings, preset=config.probe_preset)
        )
        playlist = scan.playlist(selection.playlist_id)
        video = playlist.video_streams[0].video if playlist.video_streams else None
        picture_height = None if video is None else video.height
        if picture_height is not None:
            picture_height -= selection.crop.top + selection.crop.bottom
        model_4k = vmaf_model_for_height(picture_height)
        hdr10 = selection.settings.hdr10.enabled
        common_inputs: dict[str, Any] = {
            "policy_schema_version": 1,
            "reference_sha256": reference_sha256,
            "sample_script_sha256": hashlib.sha256(
                sample_content.encode("utf-8")
            ).hexdigest(),
            "windows": [window.to_dict() for window in windows],
            "settings": {**base_settings.to_dict(), "crf": None},
            "config": config.to_dict(),
            "model_4k": model_4k,
            "hdr10": hdr10,
        }

        report_inputs = {**common_inputs, "selection_sha256": selection_sha256}
        report_marker = paths.stages / "crf-search.json"
        if _valid_stage(report_marker, report_inputs, [report]):
            document = json.loads(report.read_text(encoding="utf-8"))
            return _outcome_from_report(document, config)

        size_mode = config.mode == "size"
        sampled_frames = sum(window.frame_count for window in windows)
        search: CrfSearch | SizeSearch = (
            SizeSearch(config, selection.settings.crf)
            if size_mode
            else CrfSearch(config, selection.settings.crf)
        )
        live = self._live(paths)
        sample_seconds = sampled_frames * info.fps_denominator / info.fps_numerator
        while (crf := search.next_crf()) is not None:
            token = f"{crf:.2f}".replace(".", "_")
            vmaf_json = work / f"probe-{token}.vmaf.json"
            size_json = work / f"probe-{token}.size.json"
            evidence = size_json if size_mode else vmaf_json
            probe_marker = paths.stages / f"crf-probe-{token}.json"
            probe_inputs = {**common_inputs, "crf": crf}
            done_probes = len(search.probes)
            live.update(
                done_probes / config.max_iterations,
                detail=(
                    f"{done_probes + 1}. próba: CRF {crf:g}",
                    f"Probe {done_probes + 1}: CRF {crf:g}",
                ),
                force=True,
            )
            if not _valid_stage(probe_marker, probe_inputs, [evidence]):
                probe_video = work / f"probe-{token}.mkv"
                probe_video.unlink(missing_ok=True)
                probe_progress = FFmpegProgressParser(max(sample_seconds, 0.001))

                def report_probe(line: str, done: int = done_probes) -> None:
                    snapshot = probe_progress.feed_line(line)
                    if snapshot is not None:
                        live.update(
                            (done + snapshot.stage_fraction) / config.max_iterations
                        )

                try:
                    runner.run_pipeline(
                        encode_pipeline_commands(
                            sample_script, probe_video, replace(base_settings, crf=crf)
                        ),
                        cwd=paths.work,
                        stderr_paths=[
                            paths.logs / f"crf-probe-{token}-vapoursynth.log",
                            paths.logs / f"crf-probe-{token}-encode.log",
                        ],
                        stderr_line_callback=report_probe,
                    )
                    if size_mode:
                        # The exact release settings on spread windows: the
                        # sample's size projects the title's size.
                        sample_bytes = probe_video.stat().st_size
                        atomic_write_json(
                            size_json,
                            {
                                "crf": crf,
                                "sample_bytes": sample_bytes,
                                "sample_frames": sampled_frames,
                                "title_frames": info.frames,
                                "projected_bytes": project_title_bytes(
                                    sample_bytes, sampled_frames, info.frames
                                ),
                            },
                        )
                    else:
                        runner.run(
                            streamed_vmaf_command(
                                sample_script,
                                probe_video,
                                vmaf_json,
                                hdr10=hdr10,
                                model_4k=model_4k,
                                # Only the VMAF score steers the search: skip
                                # the slow PSNR/SSIM features, use a thread
                                # pool (the score is identical), and keep the
                                # named pipes out of the job tree, where they
                                # would make the storage accounting refuse
                                # the whole job.
                                threads=_vmaf_thread_count(),
                                vmaf_only=True,
                                fifo_root=self.settings.cache_root / "vmaf",
                            ),
                            cwd=paths.work,
                            stderr_path=paths.logs / f"crf-probe-{token}-vmaf.log",
                        )
                finally:
                    # Sample encodes are disposable; only the score is evidence.
                    probe_video.unlink(missing_ok=True)
                _write_stage(probe_marker, probe_inputs, [evidence])
            if size_mode:
                try:
                    projected_bytes = int(
                        json.loads(size_json.read_text(encoding="utf-8"))["projected_bytes"]
                    )
                    search.record(crf, projected_bytes / 1e9)
                except (OSError, KeyError, TypeError, ValueError, CrfSearchError) as exc:
                    raise ReviewRequired(
                        f"CRF probe {crf} produced no usable size: {exc}",
                        details={"code": "crf_probe_invalid", "crf": crf},
                    ) from exc
                self.database.add_event(
                    EventCreate(
                        job_id=job.id,
                        kind="worker.auto-crf-probe",
                        message=(
                            f"CRF {crf:g} projects {projected_bytes / 1e9:.1f} GB "
                            f"(target {config.target_size_gb:g} GB)"
                        ),
                        payload={
                            "crf": crf,
                            "projected_bytes": projected_bytes,
                            "target_size_gb": config.target_size_gb,
                        },
                    )
                )
                continue
            try:
                score = vmaf_score(
                    json.loads(vmaf_json.read_text(encoding="utf-8")), config.metric
                )
                search.record(crf, score)
            except (OSError, CrfSearchError, json.JSONDecodeError) as exc:
                raise ReviewRequired(
                    f"CRF probe {crf} produced no usable VMAF score: {exc}",
                    details={"code": "crf_probe_invalid", "crf": crf},
                ) from exc
            self.database.add_event(
                EventCreate(
                    job_id=job.id,
                    kind="worker.auto-crf-probe",
                    message=f"CRF {crf:g} scored VMAF {score:.2f}",
                    payload={
                        "crf": crf,
                        "vmaf": round(score, 4),
                        "target": config.target_vmaf,
                        "metric": config.metric,
                    },
                )
            )

        outcome = search.outcome()
        if not outcome.usable and outcome.probes:
            # The target is out of reach within the allowed range: encode at
            # the end of the range nearest to it (the best measured quality,
            # or the smallest measured size) instead of stopping the queue.
            nearest = (
                max(outcome.probes, key=lambda item: item.crf)
                if size_mode
                else max(outcome.probes, key=lambda item: (item.score, -item.crf))
            )
            outcome = replace(
                outcome, chosen_crf=nearest.crf, chosen_score=nearest.score
            )
        atomic_write_json(
            report,
            {
                "schema_version": 1,
                "selection_sha256": selection_sha256,
                "nominal_crf": selection.settings.crf,
                "config": config.to_dict(),
                "windows": [window.to_dict() for window in windows],
                "sampled_frames": sum(window.frame_count for window in windows),
                **(
                    {"title_frames": info.frames}
                    if size_mode
                    else {
                        "model": "vmaf_4k_v0.6.1" if model_4k else "vmaf_v0.6.1",
                        "hdr10_proof_transform": hdr10,
                    }
                ),
                **outcome.to_dict(),
            },
        )
        if not outcome.usable:
            target_text = (
                f"the size target of {config.target_size_gb:g} GB"
                if size_mode
                else f"the VMAF target {config.target_vmaf:g}"
            )
            raise ReviewRequired(
                f"automatic CRF search could not reach {target_text} within CRF "
                f"{config.min_crf:g}-{config.max_crf:g}; change the target, widen "
                "the range or choose a fixed CRF",
                details={"code": "crf_target_unreachable", "report": report.name},
            )
        _write_stage(report_marker, report_inputs, [report])
        self._register_artifact(
            job.id,
            report,
            DatabaseArtifactKind.MANIFEST,
            "crf-search.json",
            mime_type="application/json",
        )
        message = f"automatic CRF search selected CRF {outcome.chosen_crf:g}"
        if size_mode:
            message += (
                f" (projected {outcome.chosen_score:.1f} GB, target "
                f"{config.target_size_gb:g} GB)"
            )
            if outcome.status == STATUS_MIN_CRF:
                message += (
                    "; even the lowest allowed CRF stays well under the target, so "
                    "a lower min_crf would use the size for more quality"
                )
            elif outcome.status == STATUS_BEST_EFFORT:
                message += (
                    "; the search ended before a CRF closer to the target was found"
                )
        if outcome.status == STATUS_UNREACHABLE:
            message += (
                f"; the {'size' if size_mode else 'VMAF'} target is out of reach within "
                f"CRF {config.min_crf:g}-{config.max_crf:g}, so the nearest measured "
                "CRF is used"
            )
        elif size_mode:
            pass
        elif outcome.status == STATUS_MAX_CRF:
            message += (
                f"; the VMAF target {config.target_vmaf:g} is met even at the "
                f"highest allowed CRF (VMAF {outcome.chosen_score:.2f}), so a "
                "higher max_crf would give a smaller file"
            )
        elif outcome.status == STATUS_BEST_EFFORT:
            message += (
                f"; VMAF {outcome.chosen_score:.2f} is more than "
                f"{config.tolerance:g} above the target {config.target_vmaf:g} "
                "because the search ended before a closer CRF was found"
            )
        self.database.add_event(
            EventCreate(
                job_id=job.id,
                kind="worker.auto-crf",
                message=message,
                payload={
                    "status": outcome.status,
                    "chosen_crf": outcome.chosen_crf,
                    "mode": outcome.mode,
                    **(
                        {
                            "projected_gb": outcome.chosen_score,
                            "target_size_gb": config.target_size_gb,
                        }
                        if size_mode
                        else {"vmaf": outcome.chosen_score, "target": config.target_vmaf}
                    ),
                },
            )
        )
        return outcome

    def _encode(self, job: Job, paths: JobPaths) -> None:
        scan, selection = self._load_prepared_scan_and_selection(job, paths)
        if not paths.script.is_file() or not paths.reference.is_file():
            raise RuntimeError("prepared reference or VapourSynth script is missing")
        reference_sha256 = _recorded_output_sha256(
            paths.stages / "reference-remux.json", paths.reference
        )
        if reference_sha256 is None:
            raise RuntimeError("reference remux checkpoint digest is missing")
        temporary_video = paths.work / "video-encoded.partial.mkv"
        extra_video_params: dict[str, str | int] | None = None
        dynamic_inputs: dict[str, Any] | None = None
        to_inject: tuple[DynamicHdrPlan, Path] | None = None
        if selection.dynamic_hdr is not DynamicHdrMode.DISCARD:
            dynamic_plan, metadata_path, metadata_sha256 = self._load_dynamic_hdr(
                job, paths, selection
            )
            if dynamic_plan.retained and metadata_path is not None:
                try:
                    extra_video_params = (
                        x265_dynamic_params(dynamic_plan, metadata_path) or None
                    )
                except DynamicHdrError as exc:
                    raise ReviewRequired(
                        f"dynamic HDR metadata cannot be passed to x265: {exc}",
                        details={"code": f"dynamic_hdr_{exc.code}"},
                    ) from exc
                dynamic_inputs = {
                    "plan": dynamic_plan.to_dict(),
                    "metadata_sha256": metadata_sha256,
                    # The metadata is injected into the finished stream: an encode checkpoint made
                    # before that step carries none.
                    "injection": 2,
                }
                to_inject = (dynamic_plan, metadata_path)
        commands = encode_pipeline_commands(
            paths.script,
            temporary_video,
            selection.settings,
            extra_video_params=extra_video_params,
            # Tracker jobs only, so the encode checkpoint of older jobs stays valid.
            keyframe_seconds=(
                chapter_keyframe_seconds(scan.playlist(selection.playlist_id))
                if selection.tracker_profile is not TrackerProfile.NONE
                else ()
            ),
        )
        inputs = {
            "policy_schema_version": 3,
            "scan_fingerprint": scan.fingerprint,
            "playlist_id": selection.playlist_id,
            "angle": selection.angle,
            "reference_sha256": reference_sha256,
            "script_sha256": sha256_file(paths.script),
            "settings": selection.settings.to_dict(),
            "argv": commands,
        }
        if dynamic_inputs is not None:
            inputs["dynamic_hdr"] = dynamic_inputs

        check: _BackgroundRun | None = None

        def interrupted() -> bool:
            if check is not None and check.failed():
                return True
            return self._process_interrupt_requested(job.id)

        marker = paths.stages / "video-encode.json"
        encode_needed = not _valid_stage(marker, inputs, [paths.encoded_video])
        if (
            encode_needed
            and isinstance(self._runner(paths), CommandRunner)
            and not self._source_integrity_current(paths, reference_sha256)
        ):
            # The full decode of the reference takes most of an hour on a UHD
            # title.  It runs at low priority beside the encode instead of
            # before it; a corrupt source stops the encode.
            title_seconds = float(scan.playlist(selection.playlist_id).duration_seconds)
            check = _BackgroundRun(
                lambda cancelled: self._check_source_integrity(
                    paths,
                    reference_sha256,
                    cancelled=cancelled,
                    low_priority=True,
                    duration_seconds=title_seconds,
                ),
                name=f"source-integrity-{job.id}",
            )
        try:
            if encode_needed:
                temporary_video.unlink(missing_ok=True)
                playlist = scan.playlist(selection.playlist_id)

                live = self._live(paths)
                target_size_gb = selection.auto_crf.target_size_gb
                encode_metrics_base: dict[str, Any] = {
                    "target_bytes": (
                        None if target_size_gb is None else int(target_size_gb * 1e9)
                    ),
                }

                def persist_progress(
                    progress: float, message: str, details: dict[str, object]
                ) -> None:
                    fraction = details.get("stage_fraction")
                    live.update(
                        float(fraction) if isinstance(fraction, (int, float)) else None,
                        metrics={
                            **encode_metrics_base,
                            **{
                                key: details.get(key)
                                for key in (
                                    "fps",
                                    "speed",
                                    "eta_seconds",
                                    "frame",
                                    "output_bytes",
                                    "projected_bytes",
                                )
                            },
                        },
                        force=True,
                    )
                    self.database.record_progress(
                        job.id,
                        progress,
                        message=message,
                        details=details,
                        expected_state=JobState.ENCODING,
                        emit_event="milestone_percent" in details,
                    )

                reporter: EncodeProgressReporter | None = None
                live.start("encode", ("Videókódolás", "Video encoding"))
                try:
                    reporter = EncodeProgressReporter(
                        playlist.duration_seconds,
                        paths.logs / "video-progress.jsonl",
                        persist_progress,
                    )
                    reporter.start()
                except Exception:
                    # Invalid legacy duration metadata must not turn optional
                    # progress observation into an encode failure.
                    LOG.exception(
                        "job %s video progress reporter is unavailable; encode continues",
                        job.id,
                    )

                try:
                    try:
                        self._runner(paths).run_pipeline(
                            commands,
                            cwd=paths.work,
                            stderr_paths=[
                                paths.logs / "vapoursynth.log",
                                paths.logs / "video-encode.log",
                            ],
                            stderr_line_callback=reporter.handle_line if reporter else None,
                            interrupt_requested=interrupted,
                        )
                    except ProcessInterrupted:
                        live.finish("interrupted")
                        raise
                    except BaseException:
                        live.finish("failed")
                        raise
                    live.finish("done")
                    # Close the tiny race in which cancellation commits after the
                    # final poll but before a successful temporary output is
                    # promoted to the durable checkpoint path.
                    if interrupted():
                        raise ProcessInterrupted()
                    if to_inject is not None:
                        with self._step(
                            paths, "dynamic-hdr-inject", ("HDR-metaadat beillesztése", "Injecting HDR metadata")
                        ):
                            self._inject_dynamic_hdr(
                                paths, *to_inject, temporary_video, interrupted
                            )
                    os.replace(temporary_video, paths.encoded_video)
                    if reporter is not None:
                        reporter.complete()
                except BaseException:
                    temporary_video.unlink(missing_ok=True)
                    raise
                _write_stage(marker, inputs, [paths.encoded_video])
        except BaseException:
            if check is not None:
                error = check.cancel()
                if isinstance(error, ReviewRequired):
                    raise error from None
            raise
        with self._step(paths, "integrity", ("Forrás-integritás ellenőrzése", "Source integrity check")):
            if check is not None:
                check.wait()
            else:
                self._check_source_integrity(
                    paths,
                    reference_sha256,
                    duration_seconds=float(
                        scan.playlist(selection.playlist_id).duration_seconds
                    ),
                )
        # Hashing and writing a multi-gigabyte checkpoint creates a real race
        # window after FFmpeg exits. Stop cleanly at the durable boundary rather
        # than entering mux/QC after shutdown or operator cancellation.
        if interrupted():
            raise ProcessInterrupted()
        self.queue.advance(job.id, JobState.MUXING, message="video encode complete")

    def _inject_dynamic_hdr(
        self,
        paths: JobPaths,
        plan: DynamicHdrPlan,
        metadata: Path,
        video: Path,
        interrupted: Callable[[], bool],
    ) -> None:
        """Attach the verified HDR10+ / Dolby Vision metadata to the finished encode.

        FFmpeg's libx265 cannot do it itself (no RPU files; Debian's build has no HDR10+). The
        metadata is injected into the HEVC stream and the Matroska track is rebuilt from it with the
        original timestamps, frame duration and colour description; the result replaces the encode
        only after the metadata read back from it matches the reference timeline frame for frame.
        """

        dolby = plan.mode is DynamicHdrMode.DOLBY_VISION
        label = "Dolby Vision RPU" if dolby else "HDR10+ metadata"
        work = paths.work / "dynamic-hdr"
        work.mkdir(mode=0o750, parents=True, exist_ok=True)
        base, injected = work / "encoded.hevc", work / "encoded-injected.hevc"
        timestamps, rebuilt = work / "encoded-timestamps.txt", work / "encoded-injected.mkv"
        check = work / ("encoded-rpu.bin" if dolby else "encoded-hdr10plus.json")
        summary_path, track_report = work / "encoded-rpu-summary.txt", work / "encoded-track.json"
        scratch = (base, injected, timestamps, rebuilt, check, summary_path, track_report)
        runner = self._runner(paths)
        try:
            for item in scratch:
                item.unlink(missing_ok=True)
            runner.run(
                video_track_command(video),
                cwd=paths.work,
                stdout_path=track_report,
                stderr_path=paths.logs / "dynamic-hdr-track.log",
            )
            try:
                properties = parse_video_track_properties(
                    track_report.read_text(encoding="utf-8")
                )
            except (DynamicHdrError, OSError, UnicodeError) as exc:
                raise ReviewRequired(
                    f"the {label} could not be attached to the encode: {exc}",
                    details={"code": "dynamic_hdr_invalid_track"},
                ) from exc
            inject = (
                dovi_inject_command(base, metadata, injected)
                if dolby
                else hdr10plus_inject_command(base, metadata, injected)
            )
            steps = (
                ("base", dovi_base_stream_command(video, base)),
                ("inject", inject),
                ("timestamps", video_timestamps_command(video, timestamps)),
                ("rebuild", dovi_rebuild_command(injected, timestamps, rebuilt, properties)),
                ("duration", dovi_duration_command(rebuilt, properties["default_duration"])),
            )
            for name, command in steps:
                if interrupted():
                    raise ProcessInterrupted()
                runner.run(
                    command,
                    cwd=paths.work,
                    stderr_path=paths.logs / f"dynamic-hdr-{name}.log",
                )
            runner.run_pipeline(
                dovi_verify_commands(rebuilt, check)
                if dolby
                else hdr10plus_extract_commands(rebuilt, check),
                cwd=paths.work,
                stderr_paths=[
                    paths.logs / "dynamic-hdr-verify-source.log",
                    paths.logs / "dynamic-hdr-verify.log",
                ],
                interrupt_requested=interrupted,
            )
            if dolby:
                runner.run(
                    dovi_summary_command(check),
                    cwd=paths.work,
                    stdout_path=summary_path,
                    stderr_path=paths.logs / "dynamic-hdr-verify-summary.log",
                )
            try:
                if dolby:
                    counted = parse_dovi_summary(
                        summary_path.read_text(encoding="utf-8", errors="replace")
                    )
                    require_dolby_vision_profile(counted)
                else:
                    counted = parse_hdr10plus_json(check.read_text(encoding="utf-8"))
                require_frame_alignment(
                    counted.frames,
                    self._reference_info(paths).frames,
                    what=f"the {label} stream of the encode",
                )
            except (DynamicHdrError, FrameSelectionError, OSError, UnicodeError) as exc:
                code = getattr(exc, "code", "unreadable")
                raise ReviewRequired(
                    f"the {label} could not be attached to the encode: {exc}",
                    details={"code": f"dynamic_hdr_{code}"},
                ) from exc
            os.replace(rebuilt, video)
        finally:
            for item in scratch:
                item.unlink(missing_ok=True)

    @staticmethod
    def _selected_streams(
        scan: DiscScan, selection: ParsedSelection
    ) -> list[tuple[int, TrackSelection, MediaStream]]:
        playlist = scan.playlist(selection.playlist_id)
        streams = {item.id: item for item in playlist.streams}
        result: list[tuple[int, TrackSelection, MediaStream]] = []
        ordered = sorted(
            selection.tracks, key=lambda item: (item.order, item.stream_id)
        )
        for number, item in enumerate(ordered, start=1):
            if item.stream_id not in streams:
                raise ReviewRequired(
                    f"selected stream disappeared from scan: {item.stream_id}"
                )
            result.append((number, item, streams[item.stream_id]))
        return result

    @staticmethod
    def _track_path(
        paths: JobPaths, number: int, item: TrackSelection, stream: MediaStream
    ) -> Path:
        if stream.kind is StreamKind.SUBTITLE:
            suffix = ".mks"
        elif item.action is TrackAction.FLAC:
            # Matroska retains the source PTS/delay while carrying FLAC audio;
            # a raw .flac intermediate cannot represent that timeline.
            suffix = ".mka"
        else:
            suffix = ".mka"
        return paths.work / "tracks" / f"track-{number:02d}-{stream.kind.value}{suffix}"

    def _probe_stream_starts(
        self,
        paths: JobPaths,
        media_path: Path,
        *,
        label: str,
    ) -> dict[int, Decimal]:
        if not re.fullmatch(r"[a-z0-9-]+", label):
            raise ValueError("unsafe stream-start probe label")
        report = paths.analysis / f"{label}-stream-starts.json"
        command = stream_start_probe_command(media_path)
        inputs = {"media_sha256": sha256_file(media_path), "argv": command}
        marker = paths.stages / f"stream-start-{label}.json"
        if not _valid_stage(marker, inputs, [report]):
            self._runner(paths).run(
                command,
                cwd=paths.work,
                stdout_path=report,
                stderr_path=paths.logs / f"{label}-stream-starts.log",
            )
            try:
                parse_stream_start_times(json.loads(report.read_text(encoding="utf-8")))
            except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
                raise ReviewRequired(
                    f"{label} has no trustworthy presentation start time"
                ) from exc
            _write_stage(marker, inputs, [report])
        try:
            return parse_stream_start_times(
                json.loads(report.read_text(encoding="utf-8"))
            )
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise ReviewRequired(
                f"{label} stream-start report is missing or invalid"
            ) from exc

    def _probe_first_packet(
        self,
        paths: JobPaths,
        media_path: Path,
        stream_spec: str,
        *,
        label: str,
    ) -> Decimal | None:
        """The first packet time of one stream; None when it has no packets."""

        if not re.fullmatch(r"[a-z0-9-]+", label):
            raise ValueError("unsafe first-packet probe label")
        report = paths.analysis / f"{label}-first-packet.json"
        command = first_packet_probe_command(media_path, stream_spec)
        inputs = {"media_sha256": sha256_file(media_path), "argv": command}
        marker = paths.stages / f"first-packet-{label}.json"
        if not _valid_stage(marker, inputs, [report]):
            self._runner(paths).run(
                command,
                cwd=paths.work,
                stdout_path=report,
                stderr_path=paths.logs / f"{label}-first-packet.log",
            )
            _write_stage(marker, inputs, [report])
        try:
            return parse_first_packet_time(json.loads(report.read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise ReviewRequired(f"{label} first packet time is missing or invalid") from exc

    def _audio_first_packet(
        self, paths: JobPaths, media_path: Path, ordinal: int, *, side: str
    ) -> Decimal:
        """Where an audio stream of a multi-stream MKV really starts.

        Audio frames are not reordered, so the first packet is the earliest
        presentation time.  A selected audio stream without packets cannot
        be timed and stops the job.
        """

        first = self._probe_first_packet(
            paths, media_path, f"a:{ordinal}", label=f"{side}-audio-{ordinal:02d}"
        )
        if first is None:
            raise ReviewRequired(
                f"{side} audio stream {ordinal} has no packets to time",
                details={"audio_ordinal": ordinal},
            )
        return first

    def _mux(self, job: Job, paths: JobPaths) -> None:
        self._restore_base_mux(paths)
        scan, selection = self._load_prepared_scan_and_selection(job, paths)
        if not paths.encoded_video.is_file() or not paths.reference.is_file():
            raise RuntimeError("encoded video or reference remux is missing")
        playlist = scan.playlist(selection.playlist_id)
        retained = [
            entry
            for entry in self._selected_streams(scan, selection)
            if entry[1].action is not TrackAction.OMIT
        ]
        default_audio = _effective_audio_defaults(
            retained, allow_dub_default=selection.dub_may_be_default
        )
        audio_ordinals = {
            stream.id: ordinal for ordinal, stream in enumerate(playlist.audio_streams)
        }
        subtitle_ordinals = {
            stream.id: ordinal
            for ordinal, stream in enumerate(playlist.subtitle_streams)
        }
        extracted_audio: list[tuple[int, TrackSelection, MediaStream, Path]] = []
        extracted_subtitles: list[tuple[int, TrackSelection, MediaStream, Path]] = []
        untagged = [stream.id for _number, item, stream in retained if item.bcp47(stream) == "und"]
        if untagged:
            # Nothing names these languages; they are muxed as ``und`` and the
            # tag can be fixed later without touching the encode.
            self.database.add_event(
                EventCreate(
                    job_id=job.id,
                    kind="worker.language-warning",
                    message="some retained tracks have no known language and are tagged und",
                    payload={"tracks": untagged},
                )
            )
        for number, item, stream in retained:
            output = self._track_path(paths, number, item, stream)
            inputs = {
                "reference_sha256": sha256_file(paths.reference),
                "stream_id": stream.id,
                "source_stream_index": stream.index,
                "reference_type_ordinal": (
                    audio_ordinals[stream.id]
                    if stream.kind is StreamKind.AUDIO
                    else subtitle_ordinals[stream.id]
                ),
                "action": item.action.value,
            }
            if stream.kind is StreamKind.AUDIO:
                audio_policy = effective_audio_policy(
                    item.action.value,
                    source_codec=stream.codec,
                    source_profile=stream.codec_profile,
                    source_channels=stream.channels,
                    source_sample_rate=stream.sample_rate,
                    source_bit_depth=stream.bit_depth,
                )
                inputs["effective_audio_policy"] = audio_policy.to_dict()
            marker = paths.stages / f"track-{number:02d}.json"
            if not _valid_stage(marker, inputs, [output]):
                if stream.kind is StreamKind.AUDIO:
                    command = audio_track_command(
                        paths.reference,
                        audio_ordinals[stream.id],
                        output,
                        action=item.action.value,
                        source_codec=stream.codec,
                        source_profile=stream.codec_profile,
                        source_channels=stream.channels,
                        source_sample_rate=stream.sample_rate,
                        source_bit_depth=stream.bit_depth,
                    )
                elif stream.kind is StreamKind.SUBTITLE:
                    command = subtitle_track_command(
                        paths.reference, subtitle_ordinals[stream.id], output
                    )
                else:
                    raise ReviewRequired(
                        f"unsupported selected track kind: {stream.kind.value}"
                    )
                self._runner(paths).run(
                    command,
                    cwd=paths.work,
                    stderr_path=paths.logs / f"track-{number:02d}.log",
                )
                _write_stage(marker, inputs, [output])
            if stream.kind is StreamKind.SUBTITLE:
                subtitle_report = paths.analysis / f"subtitle-{number:02d}-probe.json"
                subtitle_inputs = {
                    "sidecar_sha256": sha256_file(output),
                    "subtitle_kind": item.subtitle_kind,
                    "title_duration_seconds": playlist.duration_seconds,
                }
                subtitle_marker = paths.stages / f"subtitle-{number:02d}-qc.json"
                if not _valid_stage(
                    subtitle_marker, subtitle_inputs, [subtitle_report]
                ):
                    self._runner(paths).run(
                        subtitle_probe_command(output),
                        cwd=paths.work,
                        stdout_path=subtitle_report,
                        stderr_path=paths.logs / f"subtitle-{number:02d}-probe.log",
                    )
                    try:
                        subtitle_probe = parse_subtitle_probe(
                            subtitle_report.read_text(encoding="utf-8")
                        )
                    except (OSError, ValueError) as exc:
                        raise ReviewRequired(
                            f"subtitle {stream.id} could not be classified safely"
                        ) from exc
                    subtitle_errors = validate_subtitle_classification(
                        subtitle_probe,
                        subtitle_kind=item.subtitle_kind or "unknown",
                        title_duration_seconds=playlist.duration_seconds,
                    )
                    if subtitle_errors:
                        raise ReviewRequired(
                            f"subtitle {stream.id} classification requires review",
                            details={"errors": list(subtitle_errors)},
                        )
                    _write_stage(subtitle_marker, subtitle_inputs, [subtitle_report])
                extracted_subtitles.append((number, item, stream, output))
            elif stream.kind is StreamKind.AUDIO:
                if item.forced:
                    raise ReviewRequired("audio tracks cannot be forced")
                extracted_audio.append((number, item, stream, output))
            else:
                raise ReviewRequired(
                    f"unsupported selected track kind: {stream.kind.value}"
                )

        ordered_sidecars = [*extracted_audio, *extracted_subtitles]
        self._probe_stream_starts(paths, paths.reference, label="reference")
        try:
            reference_start_document = json.loads(
                (paths.analysis / "reference-stream-starts.json").read_text(
                    encoding="utf-8"
                )
            )
            reference_starts_by_type = parse_stream_start_times_by_type(
                reference_start_document
            )
            reference_video_start = reference_starts_by_type[("video", 0)]
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ReviewRequired(
                "reference video start time is missing or ambiguous"
            ) from exc
        # Audio is planned from where its first packet sits in the reference,
        # and the sidecar side from the sidecar's own start time (codec
        # priming and container rounding live there).  ffprobe's start_time of
        # a stream in a multi-stream MKV is only right when the stream's first
        # packet falls inside the probe window; otherwise it is the
        # container's start.  Taffin 1988 opens with an 11 s clip without
        # audio: the reference said 0.042 s for an audio stream whose first
        # packet is at 11.053 s, and the plan moved the sound 11 s early
        # (4.0.3 and older).  Subtitles are planned on their first packets
        # below for the same reason (3.11.2 and older began them at 0:00).
        retained_reference_starts: list[Decimal] = []
        for _number, _item, stream, _output in extracted_audio:
            key = ("audio", audio_ordinals[stream.id])
            if key not in reference_starts_by_type:
                raise ReviewRequired(f"reference start time is missing for {stream.id}")
            retained_reference_starts.append(
                self._audio_first_packet(
                    paths, paths.reference, audio_ordinals[stream.id], side="reference"
                )
            )
        encoded_starts = self._probe_stream_starts(
            paths, paths.encoded_video, label="encoded-video"
        )
        if len(encoded_starts) != 1:
            raise ReviewRequired(
                "encoded-video sidecar must contain exactly one stream"
            )
        sidecar_starts: list[Decimal] = []
        for number, _item, _stream, output in extracted_audio:
            starts = self._probe_stream_starts(
                paths, output, label=f"track-{number:02d}"
            )
            if len(starts) != 1:
                raise ReviewRequired(
                    f"track-{number:02d} sidecar must contain exactly one stream"
                )
            sidecar_starts.append(next(iter(starts.values())))
        sidecar_priming: list[Decimal] = []
        for _number, item, stream, _output in extracted_audio:
            policy = effective_audio_policy(
                item.action.value,
                source_codec=stream.codec,
                source_profile=stream.codec_profile,
                source_channels=stream.channels,
                source_sample_rate=stream.sample_rate,
                source_bit_depth=stream.bit_depth,
            )
            sidecar_priming.append(
                Decimal(0)
                if item.action is TrackAction.COPY
                else encoder_priming_seconds(
                    policy.codec_name, policy.sample_rate or stream.sample_rate
                )
            )
        audio_timeline = plan_common_zero_timeline(
            reference_video_start,
            retained_reference_starts,
            encoded_video_start=next(iter(encoded_starts.values())),
            sidecar_start_times=sidecar_starts,
            sidecar_priming_seconds=sidecar_priming,
        )
        # A subtitle sidecar is a stream copy with -copyts: its packets keep
        # the reference's absolute times, which mkvmerge keeps too.  The
        # offset only rebases them onto the common zero, corrected by any
        # difference between the two first packets (normally none).
        # ``expected_start_seconds`` stays what ffprobe reports for a subtitle
        # of a multi-stream MKV (the container's start); the first-event
        # times are kept apart for the track QC's absolute check.
        subtitle_expected: list[Decimal] = []
        subtitle_first_events: list[str | None] = []
        subtitle_offsets: list[Decimal] = []
        for number, _item, stream, output in extracted_subtitles:
            container_key = ("subtitle", subtitle_ordinals[stream.id])
            if container_key not in reference_starts_by_type:
                raise ReviewRequired(f"reference start time is missing for {stream.id}")
            reference_first = self._probe_first_packet(
                paths,
                paths.reference,
                f"s:{subtitle_ordinals[stream.id]}",
                label=f"reference-subtitle-{subtitle_ordinals[stream.id]:02d}",
            )
            sidecar_first = self._probe_first_packet(
                paths, output, "s:0", label=f"track-{number:02d}"
            )
            if (reference_first is None) != (sidecar_first is None):
                raise ReviewRequired(
                    f"track-{number:02d} sidecar lost or gained subtitle packets",
                    details={"stream_id": stream.id},
                )
            drift = (
                Decimal(0)
                if reference_first is None or sidecar_first is None
                else reference_first - sidecar_first
            )
            subtitle_expected.append(
                reference_starts_by_type[container_key] - audio_timeline.origin_seconds
            )
            subtitle_first_events.append(
                None
                if reference_first is None
                else str(reference_first - audio_timeline.origin_seconds)
            )
            subtitle_offsets.append(
                ((drift - audio_timeline.origin_seconds) * Decimal(1000)).quantize(
                    Decimal(1), rounding=ROUND_HALF_EVEN
                )
            )
        timeline = replace(
            audio_timeline,
            expected_start_seconds=(
                *audio_timeline.expected_start_seconds,
                *subtitle_expected,
            ),
            track_sync_offsets_ms=(
                *audio_timeline.track_sync_offsets_ms,
                *subtitle_offsets,
            ),
        )
        atomic_write_json(
            paths.timeline_json,
            {
                "schema_version": 2,
                "origin_seconds": str(timeline.origin_seconds),
                "expected_start_seconds": [
                    str(value) for value in timeline.expected_start_seconds
                ],
                "video_sync_offset_ms": str(timeline.video_sync_offset_ms),
                "track_sync_offsets_ms": [
                    str(value) for value in timeline.track_sync_offsets_ms
                ],
                # Per retained subtitle, in order: where its first event must
                # land in the final MKV (None: the stream has no packets).
                "subtitle_first_event_seconds": subtitle_first_events,
            },
        )
        audio: list[MuxTrack] = []
        subtitles: list[MuxTrack] = []
        for (number, item, stream, output), sync_offset in zip(
            ordered_sidecars, timeline.track_sync_offsets_ms, strict=True
        ):
            is_subtitle = stream.kind is StreamKind.SUBTITLE
            track = MuxTrack(
                path=output,
                language=item.bcp47(stream),
                name=_track_name(item, stream),
                default=(
                    (stream.default if item.default is None else item.default)
                    if is_subtitle
                    else default_audio[stream.id]
                ),
                forced=is_subtitle and item.subtitle_kind == "forced",
                sync_offset_ms=sync_offset,
                subtitle_kind=(item.subtitle_kind or "unknown")
                if is_subtitle
                else None,
            )
            (subtitles if is_subtitle else audio).append(track)

        chapters = paths.work / "chapters.xml"
        chapters_path: Path | None = None
        if playlist.chapters:
            # Chapter starts count from the title's first picture, as do the
            # encode's forced chapter IDR frames; in the final MKV that
            # picture sits at the video's expected start (0, or a few ms when
            # a primed AC-3/E-AC-3 track moved the common zero earlier).
            video_start = timeline.expected_start_seconds[0]
            final_chapters = tuple(
                float(Decimal(str(start)) + video_start) for start in playlist.chapters
            )
            chapter_inputs = {
                "format": "matroska-chapters-v1",
                "scan_fingerprint": scan.fingerprint,
                "playlist_id": playlist.playlist_id,
                "chapter_starts": list(playlist.chapters),
                "video_start_seconds": str(video_start),
            }
            chapter_marker = paths.stages / "chapters.json"
            if not _valid_stage(chapter_marker, chapter_inputs, [chapters]):
                atomic_write_text(chapters, render_matroska_chapters(final_chapters))
                _write_stage(chapter_marker, chapter_inputs, [chapters])
            chapters_path = chapters

        mux_inputs = {
            "video_sha256": sha256_file(paths.encoded_video),
            "tracks": [
                {"path": str(item.path), "sha256": sha256_file(item.path)}
                for item in (*audio, *subtitles)
            ],
            "chapters_sha256": (
                sha256_file(chapters_path) if chapters_path is not None else None
            ),
            "timeline_sha256": sha256_file(paths.timeline_json),
        }
        try:
            command = mkvmerge_command(
                paths.muxed_output,
                paths.encoded_video,
                audio_tracks=audio,
                subtitle_tracks=subtitles,
                chapters_path=chapters_path,
                title=selection.output_name,
                video_sync_offset_ms=timeline.video_sync_offset_ms,
            )
        except ValueError as exc:
            raise ReviewRequired(
                f"mux track policy rejected the release: {exc}"
            ) from exc
        # Track names/languages/default/forced flags and title are material mux
        # inputs even when the elementary stream hashes are unchanged.
        mux_inputs["argv"] = command
        marker = paths.stages / "mux.json"
        if not _valid_stage(marker, mux_inputs, [paths.muxed_output]):
            # mkvmerge prints its warnings on stdout.
            mux_output_log = paths.logs / "mkvmerge-output.log"
            mux_result = self._runner(paths).run(
                command,
                cwd=paths.work,
                stdout_path=mux_output_log,
                stderr_path=paths.logs / "mkvmerge.log",
                ok_returncodes=(0, 1),
            )
            if getattr(mux_result, "returncode", 0) == 1:
                self._judge_mkvmerge_warnings(
                    job.id,
                    paths,
                    mkvmerge_warning_lines(
                        "\n".join(
                            _read_text_or_empty(path)
                            for path in (mux_output_log, paths.logs / "mkvmerge.log")
                        )
                    ),
                    stage="mux",
                )
            _write_stage(marker, mux_inputs, [paths.muxed_output])
        self.queue.advance(job.id, JobState.QC, message="final Matroska mux complete")

    def _judge_mkvmerge_warnings(
        self,
        job_id: str,
        paths: JobPaths,
        messages: Sequence[str],
        *,
        stage: Literal["mux", "identify"],
    ) -> None:
        """Record mkvmerge's warnings; stop only on one that reports data loss.

        See ``MKVMERGE_DATA_LOSS_WARNING`` in :mod:`bdencode.mux`.  A warning
        exit without a readable warning is recorded as an unknown warning.
        """

        warnings = classify_mkvmerge_warnings(messages) or (
            MkvmergeWarning(
                "unknown", "mkvmerge exited with warnings but printed none", False
            ),
        )
        blocking = [item for item in warnings if item.blocking]
        report = paths.analysis / f"mkvmerge-{stage}-warnings.json"
        atomic_write_json(
            report,
            {
                "schema_version": 1,
                "stage": stage,
                "status": "needs_review" if blocking else "passed_with_warnings",
                "warnings": [item.to_dict() for item in warnings],
            },
        )
        if blocking:
            raise ReviewRequired(
                "mkvmerge reported lost or damaged data during the mux; inspect mkvmerge-output.log before resuming"
                if stage == "mux"
                else "mkvmerge identify reported lost or damaged data in the final file",
                details={
                    "warnings": [item.message for item in blocking[:20]],
                    "report": report.name,
                },
            )
        self.database.add_event(
            EventCreate(
                job_id=job_id,
                kind="worker.mkvmerge-warning",
                message=(
                    "mkvmerge finished the mux with warnings that do not affect the media; the job continues"
                    if stage == "mux"
                    else "mkvmerge identify reported warnings that do not affect the media; the job continues"
                ),
                payload={
                    "stage": stage,
                    "warnings": [item.to_dict() for item in warnings[:20]],
                    "report": report.name,
                },
            )
        )

    def _judge_full_decode(self, job: Job, paths: JobPaths, log: Path) -> Path | None:
        """Judge the final file's full-decode log; stop only on a real defect.

        Returns the diagnostics report when the log held any message.
        """

        text = log.read_text(encoding="utf-8", errors="replace")
        if not text.strip():
            return None
        join_report = self._clip_join_report(paths)
        join_messages = (
            [str(item) for item in join_report.get("join_messages") or []]
            if join_report is not None
            else []
        )
        verdict = classify_final_decode_log(text, join_messages=join_messages)
        report = log.with_name("full-decode-diagnostics.json")
        public = verdict.to_dict()
        for key in ("blocking", "warnings", "excused_join_messages"):
            public[key] = [sanitize_text(line) for line in public[key][:100]]
        atomic_write_json(report, {"schema_version": 1, **public})
        if verdict.blocking:
            raise ReviewRequired(
                "full decode emitted an error-level diagnostic; final media is not accepted",
                details={"report": report.name, "blocking": public["blocking"][:20]},
            )
        self.database.add_event(
            EventCreate(
                job_id=job.id,
                kind="worker.full-decode-warning",
                message=(
                    "the full decode of the final file logged messages that are not "
                    "decode errors; the job continues"
                ),
                payload={
                    "warnings": public["warnings"][:20],
                    "excused_join_messages": public["excused_join_messages"][:20],
                    "report": report.name,
                },
            )
        )
        return report

    def _qc(self, job: Job, paths: JobPaths) -> None:
        self._restore_base_mux(paths)
        scan, selection = self._load_prepared_scan_and_selection(job, paths)
        output = paths.muxed_output
        if not output.is_file():
            raise RuntimeError("mux output is missing")
        efficiency_report = paths.analysis / "video-efficiency.json"
        source_packets = paths.analysis / "source-video-packet-sizes.csv"
        encoded_packets = paths.analysis / "encoded-video-packet-sizes.csv"
        final_packets = paths.analysis / "final-video-packet-sizes.csv"
        efficiency_inputs = {
            "policy_schema_version": 2,
            "reference_sha256": sha256_file(paths.reference),
            "encoded_video_sha256": sha256_file(paths.encoded_video),
            "final_mkv_sha256": sha256_file(output),
            "minimum_savings_ratio": "0.001",
            "encoded_is_lossy": True,
        }
        efficiency_marker = paths.stages / "video-efficiency.json"
        if not _valid_stage(
            efficiency_marker,
            efficiency_inputs,
            [efficiency_report, source_packets, encoded_packets, final_packets],
        ):
            for media_path, packet_report, label in (
                (paths.reference, source_packets, "source"),
                (paths.encoded_video, encoded_packets, "encoded"),
                (output, final_packets, "final"),
            ):
                self._runner(paths).run(
                    video_packet_size_command(media_path),
                    cwd=paths.work,
                    stdout_path=packet_report,
                    stderr_path=paths.logs / f"{label}-video-packet-sizes.log",
                )
            try:
                source_summary = parse_video_packet_sizes(
                    source_packets.read_text(encoding="utf-8")
                )
                encoded_summary = parse_video_packet_sizes(
                    encoded_packets.read_text(encoding="utf-8")
                )
                # A low-bitrate or animated disc at a low CRF can legitimately
                # come out larger than its source: that is a warning, not a
                # defect.  Unreadable packet evidence still stops the job.
                verdict = evaluate_video_efficiency(
                    source_summary.total_bytes,
                    encoded_summary.total_bytes,
                    encoded_is_lossy=True,
                )
            except (OSError, ValueError) as exc:
                failure = f"video packet-size evidence is invalid: {exc}"
                atomic_write_json(
                    efficiency_report,
                    {
                        "schema_version": 1,
                        "status": "needs_review",
                        "error": failure,
                    },
                )
                raise ReviewRequired(
                    "lossy video efficiency policy requires review",
                    details={"error": failure, "report": efficiency_report.name},
                ) from exc
            atomic_write_json(
                efficiency_report,
                {
                    "schema_version": 1,
                    "status": "passed" if verdict.passed else "passed_with_warnings",
                    "source": source_summary.to_dict(),
                    "encoded": encoded_summary.to_dict(),
                    "verdict": verdict.to_dict(),
                    "warnings": [] if verdict.passed else [verdict.reason],
                },
            )
            if not verdict.passed:
                self.database.add_event(
                    EventCreate(
                        job_id=job.id,
                        kind="worker.video-efficiency-warning",
                        message=(
                            "the encoded video is not smaller than the source; "
                            "the job continues"
                        ),
                        payload={
                            "source_bytes": verdict.source_bytes,
                            "encoded_bytes": verdict.encoded_bytes,
                            "encoded_to_source_ratio": str(
                                verdict.encoded_to_source_ratio
                            ),
                            "report": efficiency_report.name,
                        },
                    )
                )
            _write_stage(
                efficiency_marker,
                efficiency_inputs,
                [efficiency_report, source_packets, encoded_packets, final_packets],
            )

        # Muxing must be a bit-for-bit packet-payload copy, not merely produce
        # the same number of decodable access units.  Hash the compressed video
        # stream on both sides of mkvmerge and fail closed on any mutation.
        mux_integrity_report = paths.analysis / "video-mux-integrity.json"
        mux_integrity_root = _ensure_contained_directory(
            paths.work / "video-mux-integrity",
            root=paths.work,
            description="video mux-integrity directory",
        )
        encoded_streamhash = mux_integrity_root / "encoded-video.streamhash"
        final_streamhash = mux_integrity_root / "final-video.streamhash"
        encoded_timeline_path = mux_integrity_root / "encoded-video-timeline.json"
        final_timeline_path = mux_integrity_root / "final-video-timeline.json"
        encoded_hash_command = video_stream_hash_command(paths.encoded_video)
        final_hash_command = video_stream_hash_command(output)
        encoded_timeline_command = packet_timeline_probe_command(
            paths.encoded_video, stream_type="v"
        )
        final_timeline_command = packet_timeline_probe_command(output, stream_type="v")
        mux_integrity_inputs = {
            "policy_schema_version": 3,
            "encoded_video_sha256": sha256_file(paths.encoded_video),
            "final_mkv_sha256": sha256_file(output),
            "commands": [
                encoded_hash_command,
                final_hash_command,
                encoded_timeline_command,
                final_timeline_command,
            ],
        }
        mux_integrity_marker = paths.stages / "video-mux-integrity.json"
        if not _valid_stage(
            mux_integrity_marker,
            mux_integrity_inputs,
            [
                mux_integrity_report,
                encoded_streamhash,
                final_streamhash,
                encoded_timeline_path,
                final_timeline_path,
            ],
        ):
            for command, streamhash, label in (
                (encoded_hash_command, encoded_streamhash, "encoded"),
                (final_hash_command, final_streamhash, "final"),
            ):
                self._runner(paths).run(
                    command,
                    cwd=paths.work,
                    stdout_path=streamhash,
                    stderr_path=paths.logs / f"{label}-video-streamhash.log",
                )
            for command, timeline_path, label in (
                (encoded_timeline_command, encoded_timeline_path, "encoded"),
                (final_timeline_command, final_timeline_path, "final"),
            ):
                self._runner(paths).run(
                    command,
                    cwd=paths.work,
                    stdout_path=timeline_path,
                    stderr_path=paths.logs / f"{label}-video-timeline.log",
                )
            try:
                encoded_payload_sha256 = parse_video_stream_hash(
                    encoded_streamhash.read_text(encoding="utf-8")
                )
                final_payload_sha256 = parse_video_stream_hash(
                    final_streamhash.read_text(encoding="utf-8")
                )
                encoded_timeline = parse_packet_timeline(
                    encoded_timeline_path.read_text(encoding="utf-8")
                )
                final_timeline = parse_packet_timeline(
                    final_timeline_path.read_text(encoding="utf-8")
                )
                timeline_verdict = compare_packet_timelines(
                    encoded_timeline, final_timeline
                )
            except (OSError, UnicodeError, ValueError) as exc:
                atomic_write_json(
                    mux_integrity_report,
                    {
                        "schema_version": 1,
                        "status": "needs_review",
                        "error": f"compressed video hash evidence is invalid: {exc}",
                    },
                )
                raise ReviewRequired(
                    "final video mux integrity evidence is invalid",
                    details={"report": mux_integrity_report.name},
                ) from exc
            payloads_match = encoded_payload_sha256 == final_payload_sha256
            passed = payloads_match and timeline_verdict.passed
            atomic_write_json(
                mux_integrity_report,
                {
                    "schema_version": 1,
                    "status": "passed" if passed else "needs_review",
                    "algorithm": "sha256",
                    "encoded_video_payload_sha256": encoded_payload_sha256,
                    "final_video_payload_sha256": final_payload_sha256,
                    "payloads_match": payloads_match,
                    "encoded_timeline": encoded_timeline.to_dict(),
                    "final_timeline": final_timeline.to_dict(),
                    "timeline_verdict": timeline_verdict.to_dict(),
                },
            )
            if not payloads_match:
                raise ReviewRequired(
                    "final mux changed the compressed video packet payload",
                    details={"report": mux_integrity_report.name},
                )
            if not timeline_verdict.passed:
                raise ReviewRequired(
                    "final mux changed the compressed video packet timeline",
                    details={"report": mux_integrity_report.name},
                )
            _write_stage(
                mux_integrity_marker,
                mux_integrity_inputs,
                [
                    mux_integrity_report,
                    encoded_streamhash,
                    final_streamhash,
                    encoded_timeline_path,
                    final_timeline_path,
                ],
            )
        report_root = _ensure_contained_directory(
            paths.analysis / "container",
            root=paths.analysis,
            description="container QC directory",
        )
        reports: list[Path] = [mux_integrity_report]
        inspections = inspection_commands(output, report_root)
        identify_warned: list[tuple[Path, dict[str, Any], Path]] = []
        # Hash the final file once, before the concurrent inspections.
        output_sha256 = sha256_file(output)
        live = self._live(paths)
        title_seconds = float(scan.playlist(selection.playlist_id).duration_seconds)

        def inspect(command: Sequence[str], report: Path) -> None:
            effective_command = list(command)
            inputs = {"output_sha256": output_sha256, "argv": effective_command}
            marker = paths.stages / f"qc-{report.stem}.json"
            if _valid_stage(marker, inputs, [report]):
                return
            inspection_result = None
            if report.name == "full-decode.log":
                decode_progress = paths.work / "qc-full-decode-progress.txt"
                inspection_result = self._run_reported(
                    paths,
                    effective_command,
                    probe=lambda: live.update(
                        time_fraction(decode_progress, title_seconds),
                        detail=("a kész fájl teljes dekódolása", "full decode of the finished file"),
                    ),
                    cwd=paths.work,
                    stdout_path=decode_progress,
                    stderr_path=report,
                )
            else:
                inspection_result = self._runner(paths).run(
                    effective_command,
                    cwd=paths.work,
                    stdout_path=report,
                    stderr_path=report.with_suffix(report.suffix + ".stderr"),
                    ok_returncodes=(0, 1) if command[0] == "mkvmerge" else (0,),
                )
            if (
                report.name == "mkvmerge-identify.json"
                and getattr(inspection_result, "returncode", 0) == 1
            ):
                # Judged after the inspections; the marker follows the verdict.
                identify_warned.append((marker, inputs, report))
                return
            _write_stage(marker, inputs, [report])

        # The full decode (UHD: 20 min) and the side-data scan read the file
        # independently of the quick identification probes.
        self._run_independent(
            paths,
            [functools.partial(inspect, command, report) for command, report in inspections],
        )
        for identify_marker, identify_inputs, identify_report in identify_warned:
            self._judge_mkvmerge_warnings(
                job.id,
                paths,
                _mkvmerge_identify_warnings(identify_report),
                stage="identify",
            )
            _write_stage(identify_marker, identify_inputs, [identify_report])
        for _command, report in inspections:
            if report.name == "full-decode.log":
                diagnostics_report = self._judge_full_decode(job, paths, report)
                if diagnostics_report is not None:
                    reports.append(diagnostics_report)
            reports.append(report)

        playlist = scan.playlist(selection.playlist_id)
        retained_streams = [
            entry
            for entry in self._selected_streams(scan, selection)
            if entry[1].action is not TrackAction.OMIT
        ]
        default_audio = _effective_audio_defaults(
            retained_streams, allow_dub_default=selection.dub_may_be_default
        )

        track_mux_integrity_report = paths.analysis / "track-mux-integrity.json"
        track_mux_integrity_root = _ensure_contained_directory(
            paths.work / "track-mux-integrity",
            root=paths.work,
            description="track mux-integrity directory",
        )
        track_mux_records: list[dict[str, Any]] = []
        track_mux_raw_outputs: list[Path] = []
        reference_audio_ordinals = {
            stream.id: ordinal for ordinal, stream in enumerate(playlist.audio_streams)
        }
        reference_subtitle_ordinals = {
            stream.id: ordinal
            for ordinal, stream in enumerate(playlist.subtitle_streams)
        }
        audio_ordinal = 0
        subtitle_ordinal = 0
        for number, item, stream in retained_streams:
            if stream.kind is StreamKind.AUDIO:
                stream_type: Literal["a", "s"] = "a"
                final_ordinal = audio_ordinal
                audio_ordinal += 1
            elif stream.kind is StreamKind.SUBTITLE:
                stream_type = "s"
                final_ordinal = subtitle_ordinal
                subtitle_ordinal += 1
            else:
                continue
            reference_ordinal = (
                reference_audio_ordinals[stream.id]
                if stream_type == "a"
                else reference_subtitle_ordinals[stream.id]
            )
            intermediate = self._track_path(paths, number, item, stream)
            sidecar_hash_path = (
                track_mux_integrity_root
                / f"track-{number:02d}-{stream_type}-sidecar.streamhash"
            )
            final_hash_path = (
                track_mux_integrity_root
                / f"track-{number:02d}-{stream_type}-final.streamhash"
            )
            sidecar_timeline_path = (
                track_mux_integrity_root
                / f"track-{number:02d}-{stream_type}-sidecar-timeline.json"
            )
            final_timeline_path = (
                track_mux_integrity_root
                / f"track-{number:02d}-{stream_type}-final-timeline.json"
            )
            sidecar_command = stream_payload_hash_command(
                intermediate,
                stream_type=stream_type,
            )
            final_command = stream_payload_hash_command(
                output,
                stream_type=stream_type,
                stream=final_ordinal,
            )
            sidecar_timeline_command = packet_timeline_probe_command(
                intermediate,
                stream_type=stream_type,
            )
            final_timeline_command = packet_timeline_probe_command(
                output,
                stream_type=stream_type,
                stream=final_ordinal,
            )
            track_mux_raw_outputs.extend(
                (
                    sidecar_hash_path,
                    final_hash_path,
                    sidecar_timeline_path,
                    final_timeline_path,
                )
            )
            track_mux_records.append(
                {
                    "track_number": number,
                    "stream_id": stream.id,
                    "stream_type": stream_type,
                    "final_type_ordinal": final_ordinal,
                    "reference_type_ordinal": reference_ordinal,
                    "copy_from_reference": item.action is TrackAction.COPY,
                    "intermediate": intermediate,
                    "intermediate_sha256": sha256_file(intermediate),
                    "sidecar_hash_path": sidecar_hash_path,
                    "final_hash_path": final_hash_path,
                    "sidecar_timeline_path": sidecar_timeline_path,
                    "final_timeline_path": final_timeline_path,
                    "sidecar_command": sidecar_command,
                    "final_command": final_command,
                    "sidecar_timeline_command": sidecar_timeline_command,
                    "final_timeline_command": final_timeline_command,
                }
            )
            if item.action is TrackAction.COPY:
                record = track_mux_records[-1]
                reference_hash_path = (
                    track_mux_integrity_root
                    / f"track-{number:02d}-{stream_type}-reference.streamhash"
                )
                reference_timeline_path = (
                    track_mux_integrity_root
                    / f"track-{number:02d}-{stream_type}-reference-timeline.json"
                )
                record.update(
                    {
                        "reference_hash_path": reference_hash_path,
                        "reference_timeline_path": reference_timeline_path,
                        "reference_command": stream_payload_hash_command(
                            paths.reference,
                            stream_type=stream_type,
                            stream=reference_ordinal,
                        ),
                        "reference_timeline_command": packet_timeline_probe_command(
                            paths.reference,
                            stream_type=stream_type,
                            stream=reference_ordinal,
                        ),
                    }
                )
                track_mux_raw_outputs.extend(
                    (reference_hash_path, reference_timeline_path)
                )
        track_mux_inputs = {
            # 3: subtitle tracks are also checked at their absolute place.
            "policy_schema_version": 3,
            "reference_sha256": sha256_file(paths.reference),
            "final_mkv_sha256": sha256_file(output),
            "tracks": [
                {
                    key: str(value) if isinstance(value, Path) else value
                    for key, value in record.items()
                    if key
                    not in {
                        "sidecar_hash_path",
                        "final_hash_path",
                        "sidecar_timeline_path",
                        "final_timeline_path",
                        "reference_hash_path",
                        "reference_timeline_path",
                    }
                }
                for record in track_mux_records
            ],
        }
        track_mux_marker = paths.stages / "track-mux-integrity.json"
        track_mux_outputs = [track_mux_integrity_report, *track_mux_raw_outputs]
        if not _valid_stage(
            track_mux_marker,
            track_mux_inputs,
            track_mux_outputs,
        ):
            track_results: list[dict[str, Any]] = []
            try:
                timeline_origin = Decimal(
                    str(
                        json.loads(paths.timeline_json.read_text(encoding="utf-8"))[
                            "origin_seconds"
                        ]
                    )
                )
            except (OSError, KeyError, TypeError, ValueError, ArithmeticError) as exc:
                raise ReviewRequired("timeline plan is missing or invalid") from exc
            for record in track_mux_records:
                for command_key, output_key, label in (
                    ("sidecar_command", "sidecar_hash_path", "sidecar"),
                    ("final_command", "final_hash_path", "final"),
                ):
                    self._runner(paths).run(
                        record[command_key],
                        cwd=paths.work,
                        stdout_path=record[output_key],
                        stderr_path=(
                            paths.logs
                            / f"track-{record['track_number']:02d}-{label}-streamhash.log"
                        ),
                    )
                for command_key, output_key, label in (
                    (
                        "sidecar_timeline_command",
                        "sidecar_timeline_path",
                        "sidecar",
                    ),
                    (
                        "final_timeline_command",
                        "final_timeline_path",
                        "final",
                    ),
                ):
                    self._runner(paths).run(
                        record[command_key],
                        cwd=paths.work,
                        stdout_path=record[output_key],
                        stderr_path=(
                            paths.logs
                            / f"track-{record['track_number']:02d}-{label}-timeline.log"
                        ),
                    )
                if record["copy_from_reference"]:
                    for command_key, output_key, suffix in (
                        (
                            "reference_command",
                            "reference_hash_path",
                            "streamhash",
                        ),
                        (
                            "reference_timeline_command",
                            "reference_timeline_path",
                            "timeline",
                        ),
                    ):
                        self._runner(paths).run(
                            record[command_key],
                            cwd=paths.work,
                            stdout_path=record[output_key],
                            stderr_path=(
                                paths.logs
                                / f"track-{record['track_number']:02d}-reference-{suffix}.log"
                            ),
                        )
                try:
                    sidecar_payload_sha256 = parse_stream_payload_hash(
                        record["sidecar_hash_path"].read_text(encoding="utf-8"),
                        expected_stream_type=record["stream_type"],
                    )
                    final_payload_sha256 = parse_stream_payload_hash(
                        record["final_hash_path"].read_text(encoding="utf-8"),
                        expected_stream_type=record["stream_type"],
                    )
                    sidecar_timeline = parse_packet_timeline(
                        record["sidecar_timeline_path"].read_text(encoding="utf-8")
                    )
                    final_timeline = parse_packet_timeline(
                        record["final_timeline_path"].read_text(encoding="utf-8")
                    )
                    timeline_verdict = compare_packet_timelines(
                        sidecar_timeline,
                        final_timeline,
                        timestamp_tolerance_ms=_track_timestamp_tolerance_ms(scan),
                    )
                    reference_payload_sha256 = None
                    reference_timeline = None
                    extraction_payloads_match = None
                    extraction_timeline_verdict = None
                    if record["copy_from_reference"]:
                        reference_payload_sha256 = parse_stream_payload_hash(
                            record["reference_hash_path"].read_text(encoding="utf-8"),
                            expected_stream_type=record["stream_type"],
                        )
                        reference_timeline = parse_packet_timeline(
                            record["reference_timeline_path"].read_text(
                                encoding="utf-8"
                            )
                        )
                        extraction_payloads_match = (
                            reference_payload_sha256 == sidecar_payload_sha256
                        )
                        extraction_timeline_verdict = compare_packet_timelines(
                            reference_timeline, sidecar_timeline
                        )
                except (OSError, UnicodeError, ValueError) as exc:
                    atomic_write_json(
                        track_mux_integrity_report,
                        {
                            "schema_version": 1,
                            "status": "needs_review",
                            "tracks": track_results,
                            "error": (
                                "track payload hash evidence is invalid for "
                                f"{record['stream_id']}: {exc}"
                            ),
                        },
                    )
                    raise ReviewRequired(
                        "final track mux integrity evidence is invalid",
                        details={
                            "stream_id": record["stream_id"],
                            "report": track_mux_integrity_report.name,
                        },
                    ) from exc
                payloads_match = sidecar_payload_sha256 == final_payload_sha256
                track_results.append(
                    {
                        "track_number": record["track_number"],
                        "stream_id": record["stream_id"],
                        "stream_type": record["stream_type"],
                        "final_type_ordinal": record["final_type_ordinal"],
                        "sidecar_payload_sha256": sidecar_payload_sha256,
                        "final_payload_sha256": final_payload_sha256,
                        "payloads_match": payloads_match,
                        "sidecar_timeline": sidecar_timeline.to_dict(),
                        "final_timeline": final_timeline.to_dict(),
                        "timeline_verdict": timeline_verdict.to_dict(),
                        "reference_payload_sha256": reference_payload_sha256,
                        "reference_timeline": (
                            reference_timeline.to_dict()
                            if reference_timeline is not None
                            else None
                        ),
                        "extraction_payloads_match": extraction_payloads_match,
                        "extraction_timeline_verdict": (
                            extraction_timeline_verdict.to_dict()
                            if extraction_timeline_verdict is not None
                            else None
                        ),
                    }
                )
                if extraction_payloads_match is False:
                    atomic_write_json(
                        track_mux_integrity_report,
                        {
                            "schema_version": 1,
                            "status": "needs_review",
                            "tracks": track_results,
                        },
                    )
                    raise ReviewRequired(
                        "copy extraction changed an audio/subtitle packet payload",
                        details={
                            "stream_id": record["stream_id"],
                            "report": track_mux_integrity_report.name,
                        },
                    )
                if (
                    extraction_timeline_verdict is not None
                    and not extraction_timeline_verdict.passed
                ):
                    atomic_write_json(
                        track_mux_integrity_report,
                        {
                            "schema_version": 1,
                            "status": "needs_review",
                            "tracks": track_results,
                        },
                    )
                    raise ReviewRequired(
                        "copy extraction changed an audio/subtitle packet timeline",
                        details={
                            "stream_id": record["stream_id"],
                            "report": track_mux_integrity_report.name,
                        },
                    )
                if not payloads_match:
                    atomic_write_json(
                        track_mux_integrity_report,
                        {
                            "schema_version": 1,
                            "status": "needs_review",
                            "tracks": track_results,
                        },
                    )
                    raise ReviewRequired(
                        "final mux changed a retained audio/subtitle packet payload",
                        details={
                            "stream_id": record["stream_id"],
                            "report": track_mux_integrity_report.name,
                        },
                    )
                if not timeline_verdict.passed:
                    atomic_write_json(
                        track_mux_integrity_report,
                        {
                            "schema_version": 1,
                            "status": "needs_review",
                            "tracks": track_results,
                        },
                    )
                    raise ReviewRequired(
                        "final mux changed a retained audio/subtitle packet timeline",
                        details={
                            "stream_id": record["stream_id"],
                            "report": track_mux_integrity_report.name,
                        },
                    )
                # The packet comparison above is relative to each timeline's
                # first packet, so a whole subtitle track moved in time passes
                # it.  Its absolute place is checked against the reference.
                if record["stream_type"] == "s" and record["copy_from_reference"]:
                    shift_ms = _subtitle_shift_ms(
                        record["reference_timeline_path"],
                        record["final_timeline_path"],
                        timeline_origin,
                    )
                    track_results[-1]["absolute_shift_ms"] = (
                        None if shift_ms is None else str(shift_ms)
                    )
                    if shift_ms is not None and abs(shift_ms) > _track_timestamp_tolerance_ms(scan):
                        atomic_write_json(
                            track_mux_integrity_report,
                            {
                                "schema_version": 1,
                                "status": "needs_review",
                                "tracks": track_results,
                            },
                        )
                        raise ReviewRequired(
                            f"final mux moved a subtitle track by {shift_ms} ms",
                            details={
                                "stream_id": record["stream_id"],
                                "report": track_mux_integrity_report.name,
                            },
                        )
            atomic_write_json(
                track_mux_integrity_report,
                {
                    "schema_version": 1,
                    "status": "passed",
                    "tracks": track_results,
                },
            )
            _write_stage(
                track_mux_marker,
                track_mux_inputs,
                track_mux_outputs,
            )
        reports.append(track_mux_integrity_report)
        expected_audio: list[MuxTrack] = []
        expected_subtitles: list[MuxTrack] = []
        for _number, item, stream in retained_streams:
            is_subtitle = stream.kind is StreamKind.SUBTITLE
            expected = MuxTrack(
                path=Path("unused"),
                language=item.bcp47(stream),
                name=_track_name(item, stream),
                default=(
                    (stream.default if item.default is None else item.default)
                    if is_subtitle
                    else default_audio[stream.id]
                ),
                forced=is_subtitle and item.subtitle_kind == "forced",
                subtitle_kind=(item.subtitle_kind or "unknown")
                if is_subtitle
                else None,
            )
            (
                expected_audio
                if stream.kind is StreamKind.AUDIO
                else expected_subtitles
            ).append(expected)
        identify_document = json.loads(
            (report_root / "mkvmerge-identify.json").read_text(encoding="utf-8")
        )
        topology_errors = validate_mkvmerge_identification(
            identify_document,
            audio_tracks=expected_audio,
            subtitle_tracks=expected_subtitles,
            title=selection.output_name,
        )
        if topology_errors:
            raise ReviewRequired(
                "final Matroska topology differs from the reviewed mux plan",
                details={"errors": list(topology_errors)},
            )

        source_video = playlist.video_streams[0].video
        assert source_video is not None
        if source_video.width is None or source_video.height is None:
            raise ReviewRequired("source dimensions are missing from the reviewed scan")
        video_policy = FinalVideoPolicy(
            codec_name=(
                "h264" if selection.settings.encoder is VideoEncoder.X264 else "hevc"
            ),
            profile=_FFPROBE_PROFILE_NAMES[selection.settings.profile],
            width=source_video.width - selection.crop.left - selection.crop.right,
            height=source_video.height - selection.crop.top - selection.crop.bottom,
            pixel_format=selection.settings.pixel_format,
            color_range="pc" if selection.settings.color.range == "full" else "tv",
            color_space=selection.settings.color.matrix,
            color_transfer=selection.settings.color.transfer,
            color_primaries=selection.settings.color.primaries,
            chroma_location=selection.settings.color.chroma_location,
            level=_ffprobe_level_idc(
                selection.settings.encoder, selection.settings.level
            ),
        )
        audio_policies = [
            FinalTrackPolicy(
                "audio", expected_audio_codec(item.action.value, stream.codec)
            )
            for _number, item, stream in retained_streams
            if stream.kind is StreamKind.AUDIO
        ]
        subtitle_policies = [
            FinalTrackPolicy("subtitle", stream.codec)
            for _number, _item, stream in retained_streams
            if stream.kind is StreamKind.SUBTITLE
        ]
        ffprobe_document = json.loads(
            (report_root / "ffprobe-streams.json").read_text(encoding="utf-8")
        )
        stream_errors, stream_warnings = assess_ffprobe_stream_policy(
            ffprobe_document,
            video=video_policy,
            media_tracks=[*audio_policies, *subtitle_policies],
        )
        try:
            timeline_document = json.loads(
                paths.timeline_json.read_text(encoding="utf-8")
            )
            expected_start_times = timeline_document["expected_start_seconds"]
            if not isinstance(expected_start_times, list):
                raise TypeError("expected_start_seconds is not an array")
            timeline_expected_starts = tuple(
                Decimal(str(value)) for value in expected_start_times
            )
            # A subtitle's start_time in a multi-stream MKV is the container's
            # start, not its first event: subtitles are checked at their first
            # packet by the track QC instead (absolute_shift_ms).  An audio
            # stream's start_time has the same flaw when its first packet lies
            # past the probe window, so audio is checked at its first packet.
            timed_count = 1 + len(audio_policies)
            timed_streams: list[Any] = []
            audio_ordinal = 0
            for stream in ffprobe_document.get("streams") or []:
                if isinstance(stream, Mapping) and stream.get("codec_type") == "subtitle":
                    continue
                if isinstance(stream, Mapping) and stream.get("codec_type") == "audio":
                    stream = {
                        **stream,
                        "start_time": str(
                            self._audio_first_packet(
                                paths, output, audio_ordinal, side="final"
                            )
                        ),
                    }
                    audio_ordinal += 1
                timed_streams.append(stream)
            start_errors = validate_stream_start_times(
                {**ffprobe_document, "streams": timed_streams},
                expected_start_times=timeline_expected_starts[:timed_count],
            )
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ReviewRequired("timeline plan is missing or invalid") from exc
        hdr = selection.settings.hdr10
        side_data_document = json.loads(
            (report_root / "ffprobe-video-side-data.json").read_text(encoding="utf-8")
        )
        dynamic_plan = DISCARD_PLAN
        if selection.dynamic_hdr is not DynamicHdrMode.DISCARD:
            dynamic_plan, _metadata, _digest = self._load_dynamic_hdr(
                job, paths, selection
            )
        hdr_errors = validate_hdr10_side_data(
            ffprobe_document,
            side_data_document,
            enabled=hdr.enabled,
            mastering_display=hdr.mastering_display,
            max_cll=hdr.max_cll,
            max_fall=hdr.max_fall,
            allowed_dynamic=allowed_forbidden_tokens(dynamic_plan),
        )
        retained_errors = validate_dynamic_hdr_output(
            ffprobe_document, side_data_document, dynamic_plan
        )
        policy_errors = (*stream_errors, *start_errors, *hdr_errors, *retained_errors)
        if policy_errors:
            raise ReviewRequired(
                "final media streams differ from the reviewed codec/color/HDR policy",
                details={"errors": list(policy_errors)},
            )
        if stream_warnings:
            # FFmpeg builds name a profile or default the chroma location
            # differently; the picture itself matches the reviewed policy.
            self.database.add_event(
                EventCreate(
                    job_id=job.id,
                    kind="worker.stream-policy-warning",
                    message=(
                        "the final video stream is described differently by this "
                        "FFmpeg build; the job continues"
                    ),
                    payload={"warnings": list(stream_warnings)},
                )
            )

        # The general full-decode pass maps video/audio only.  Send every final
        # subtitle event through FFmpeg's actual decoder; packet-copy/remux
        # evidence cannot prove that a PGS/text payload is parseable.
        subtitle_integrity_results: list[dict[str, Any]] = []
        subtitle_decode_reports: list[Path] = []
        subtitle_warnings: list[dict[str, Any]] = []
        retained_subtitle_entries = [
            entry for entry in retained_streams if entry[2].kind is StreamKind.SUBTITLE
        ]
        for subtitle_ordinal, (number, _item, stream) in enumerate(
            retained_subtitle_entries
        ):
            subtitle_decode_report = (
                report_root / f"subtitle-{subtitle_ordinal + 1:02d}-decode.json"
            )
            subtitle_decode_log = (
                paths.logs / f"subtitle-{subtitle_ordinal + 1:02d}-decode.log"
            )
            integrity_command = subtitle_decode_probe_command(output, subtitle_ordinal)
            sidecar_probe_path = paths.analysis / f"subtitle-{number:02d}-probe.json"
            integrity_inputs = {
                "policy_schema_version": 5,
                "output_sha256": sha256_file(output),
                "subtitle_ordinal": subtitle_ordinal,
                "sidecar_probe_sha256": sha256_file(sidecar_probe_path),
                "title_duration_seconds": playlist.duration_seconds,
                "argv": integrity_command,
            }
            integrity_marker = (
                paths.stages / f"qc-subtitle-{subtitle_ordinal + 1:02d}-integrity.json"
            )
            try:
                if not _valid_stage(
                    integrity_marker,
                    integrity_inputs,
                    [subtitle_decode_report, subtitle_decode_log],
                ):
                    self._runner(paths).run(
                        integrity_command,
                        cwd=paths.work,
                        stdout_path=subtitle_decode_report,
                        stderr_path=subtitle_decode_log,
                    )
                decode_stderr = subtitle_decode_log.read_text(
                    encoding="utf-8", errors="replace"
                )
                verdict = require_subtitle_decode(
                    subtitle_decode_report.read_text(encoding="utf-8")
                )
                sidecar_probe = parse_subtitle_probe(
                    sidecar_probe_path.read_text(encoding="utf-8")
                )
                # Real defects stop the job; known PGS quirks, FFmpeg-build
                # differences in the event count and a trailing clear set
                # just past the title end are recorded as warnings.
                decode_errors, decode_warnings = assess_final_subtitle_decode(
                    verdict,
                    stderr_text=decode_stderr,
                    packet_count=sidecar_probe.packet_count,
                    title_duration_seconds=Decimal(str(playlist.duration_seconds)),
                )
                if decode_errors:
                    raise SubtitleDecodeError("; ".join(decode_errors))
            except (OSError, UnicodeError, ProcessFailure, SubtitleDecodeError) as exc:
                subtitle_integrity_results.append(
                    {
                        "subtitle_ordinal": subtitle_ordinal,
                        "status": "needs_review",
                        "error": str(exc),
                    }
                )
                subtitle_integrity_report = report_root / "subtitle-integrity.json"
                atomic_write_json(
                    subtitle_integrity_report,
                    {
                        "schema_version": 2,
                        "status": "needs_review",
                        "tracks": subtitle_integrity_results,
                    },
                )
                raise ReviewRequired(
                    "final subtitle payload decode requires review",
                    details={
                        "subtitle_ordinal": subtitle_ordinal,
                        "report": subtitle_integrity_report.name,
                    },
                ) from exc
            if not _valid_stage(
                integrity_marker,
                integrity_inputs,
                [subtitle_decode_report, subtitle_decode_log],
            ):
                _write_stage(
                    integrity_marker,
                    integrity_inputs,
                    [subtitle_decode_report, subtitle_decode_log],
                )
            subtitle_integrity_results.append(
                {
                    "subtitle_ordinal": subtitle_ordinal,
                    "status": "passed_with_warnings" if decode_warnings else "passed",
                    "decode": verdict.to_dict(),
                    "sidecar_packet_count": sidecar_probe.packet_count,
                    "warnings": list(decode_warnings),
                    "evidence_sha256": sha256_file(subtitle_decode_report),
                }
            )
            if decode_warnings:
                subtitle_warnings.append(
                    {
                        "subtitle_ordinal": subtitle_ordinal,
                        "warnings": list(decode_warnings),
                    }
                )
            subtitle_decode_reports.append(subtitle_decode_report)
        subtitle_integrity_report = report_root / "subtitle-integrity.json"
        atomic_write_json(
            subtitle_integrity_report,
            {
                "schema_version": 2,
                "status": "passed_with_warnings" if subtitle_warnings else "passed",
                "tracks": subtitle_integrity_results,
            },
        )
        if subtitle_warnings:
            self.database.add_event(
                EventCreate(
                    job_id=job.id,
                    kind="worker.subtitle-decode-warning",
                    message=(
                        "the final subtitle decode shows known harmless differences; "
                        "the job continues"
                    ),
                    payload={
                        "tracks": subtitle_warnings,
                        "report": subtitle_integrity_report.name,
                    },
                )
            )
        reports.extend(subtitle_decode_reports)
        reports.append(subtitle_integrity_report)

        audio_manifest_path = paths.analysis / "audio-comparison.json"
        audio_outputs: list[Path] = [audio_manifest_path]
        audio_results: list[dict[str, Any]] = []
        spectrograms: list[Path] = []
        audio_ordinals = {
            item.id: index for index, item in enumerate(playlist.audio_streams)
        }
        # Gaps and overlaps of the sound at these clip joins are a property of
        # the disc, not of the encode.
        audio_join_seconds = tuple(
            Decimal(str(moment)) for moment in _playlist_join_seconds(playlist)
        )
        # The joins count from the title's first picture.  A discontinuity is
        # placed on that timeline by where its file's video starts: the
        # reference (and the sidecars, which keep its timestamps) and the
        # final MKV each have their own.
        try:
            reference_title_start = parse_stream_start_times_by_type(
                json.loads(
                    (paths.analysis / "reference-stream-starts.json").read_text(
                        encoding="utf-8"
                    )
                )
            )[("video", 0)]
            final_title_start = Decimal(
                str(
                    json.loads(paths.timeline_json.read_text(encoding="utf-8"))[
                        "expected_start_seconds"
                    ][0]
                )
            )
        except (OSError, KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ReviewRequired(
                "the video start of the reference or the final MKV is unknown"
            ) from exc
        audio_inputs: dict[str, Any] = {
            "manifest_schema_version": 4,
            "audio_decode_policy_schema_version": AUDIO_DECODE_POLICY_SCHEMA_VERSION,
            "audio_frame_continuity_schema_version": (
                AUDIO_FRAME_CONTINUITY_SCHEMA_VERSION
            ),
            "reference_sha256": sha256_file(paths.reference),
            "output_sha256": sha256_file(output),
            "tracks": [],
        }
        retained = [
            entry for entry in retained_streams if entry[2].kind is StreamKind.AUDIO
        ]
        for final_audio_ordinal, (number, item, stream) in enumerate(retained):
            self._live(paths).update(
                final_audio_ordinal / max(1, len(retained)),
                detail=(
                    f"hangsáv {final_audio_ordinal + 1} / {len(retained)} ellenőrzése",
                    f"checking audio track {final_audio_ordinal + 1} / {len(retained)}",
                ),
                force=True,
            )
            audio_policy = effective_audio_policy(
                item.action.value,
                source_codec=stream.codec,
                source_profile=stream.codec_profile,
                source_channels=stream.channels,
                source_sample_rate=stream.sample_rate,
                source_bit_depth=stream.bit_depth,
            )
            intermediate = self._track_path(paths, number, item, stream)
            source_audio_ordinal = audio_ordinals[stream.id]
            source_input_codec = normalize_audio_codec_name(stream.codec)
            final_input_codec = normalize_audio_codec_name(
                expected_audio_codec(item.action.value, stream.codec)
            )
            decode_policy = {
                "schema_version": AUDIO_DECODE_POLICY_SCHEMA_VERSION,
                "source_input_codec": source_input_codec,
                "source_input_args": audio_decode_input_args(source_input_codec),
                "final_input_codec": final_input_codec,
                "final_input_args": audio_decode_input_args(final_input_codec),
            }
            continuity_required = item.action is not TrackAction.COPY
            prefix = paths.analysis / f"audio-{number:02d}"
            source_probe = prefix.with_name(prefix.name + "-source-probe.json")
            encode_probe = prefix.with_name(prefix.name + "-encode-probe.json")
            frame_evidence_root = (
                paths.work / "audio-frame-continuity" / (f"audio-{number:02d}")
            )
            if continuity_required:
                frame_evidence_root = _ensure_contained_directory(
                    frame_evidence_root,
                    root=paths.work,
                    description="audio frame-continuity evidence directory",
                )
            source_frames = frame_evidence_root / "source-frames.json"
            sidecar_frames = frame_evidence_root / "sidecar-frames.json"
            final_frames = frame_evidence_root / "final-frames.json"
            source_pcm = prefix.with_name(prefix.name + "-source-pcm.sha256")
            encode_pcm = prefix.with_name(prefix.name + "-encode-pcm.sha256")
            source_analysis = prefix.with_name(prefix.name + "-source-analysis.log")
            encode_analysis = prefix.with_name(prefix.name + "-encode-analysis.log")
            source_spectrum = prefix.with_name(prefix.name + "-source-spectrum.png")
            encode_spectrum = prefix.with_name(prefix.name + "-encode-spectrum.png")
            spectrograms.extend((source_spectrum, encode_spectrum))
            intermediate_sha256 = sha256_file(intermediate)
            track_command_inputs = {
                "reference": audio_inputs["reference_sha256"],
                "final_output": audio_inputs["output_sha256"],
                "intermediate": intermediate_sha256,
                "effective_audio_policy": audio_policy.to_dict(),
                "audio_decode_policy": decode_policy,
                "audio_frame_continuity_schema_version": (
                    AUDIO_FRAME_CONTINUITY_SCHEMA_VERSION
                ),
            }
            commands: list[tuple[list[str], Path, Literal["stdout", "stderr"]]] = [
                (
                    audio_probe_command(paths.reference, source_audio_ordinal),
                    source_probe,
                    "stdout",
                ),
                (
                    audio_probe_command(output, final_audio_ordinal),
                    encode_probe,
                    "stdout",
                ),
                (
                    analysis_command(
                        paths.reference,
                        source_audio_ordinal,
                        source_analysis,
                        input_codec=source_input_codec,
                    ),
                    source_analysis,
                    "stderr",
                ),
                (
                    analysis_command(
                        output,
                        final_audio_ordinal,
                        encode_analysis,
                        input_codec=final_input_codec,
                    ),
                    encode_analysis,
                    "stderr",
                ),
            ]
            if continuity_required:
                commands[2:2] = [
                    (
                        audio_frame_continuity_probe_command(
                            paths.reference,
                            source_audio_ordinal,
                            input_codec=source_input_codec,
                        ),
                        source_frames,
                        "stdout",
                    ),
                    (
                        audio_frame_continuity_probe_command(
                            intermediate,
                            input_codec=final_input_codec,
                        ),
                        sidecar_frames,
                        "stdout",
                    ),
                    (
                        audio_frame_continuity_probe_command(
                            output,
                            final_audio_ordinal,
                            input_codec=final_input_codec,
                        ),
                        final_frames,
                        "stdout",
                    ),
                ]
            if audio_policy.pcm_match_required:
                commands[2:2] = [
                    (
                        pcm_hash_command(
                            paths.reference,
                            source_audio_ordinal,
                            input_codec=source_input_codec,
                        ),
                        source_pcm,
                        "stdout",
                    ),
                    (
                        pcm_hash_command(
                            output,
                            final_audio_ordinal,
                            input_codec=final_input_codec,
                        ),
                        encode_pcm,
                        "stdout",
                    ),
                ]
            def run_audio_command(
                command: list[str],
                result_path: Path,
                result_mode: Literal["stdout", "stderr"],
            ) -> None:
                command_inputs = {
                    "argv": command,
                    **track_command_inputs,
                }
                marker = paths.stages / f"qc-{result_path.stem}.json"
                if _valid_stage(marker, command_inputs, [result_path]):
                    return
                if result_mode == "stdout":
                    self._runner(paths).run(
                        command,
                        cwd=paths.work,
                        stdout_path=result_path,
                        stderr_path=paths.logs / f"{result_path.stem}.stderr",
                    )
                elif result_mode == "stderr":
                    self._runner(paths).run(
                        command,
                        cwd=paths.work,
                        stderr_path=result_path,
                    )
                else:
                    raise AssertionError(f"unsupported QC result mode: {result_mode}")
                _write_stage(marker, command_inputs, [result_path])

            # Each probe, hash and loudness analysis reads its own file and
            # writes its own result: on a UHD title they took 19 minutes one
            # after the other.
            self._run_independent(
                paths,
                [
                    functools.partial(run_audio_command, *command)
                    for command in commands
                ],
            )
            try:
                source_value = parse_audio_probe(
                    source_probe.read_text(encoding="utf-8")
                )
                encode_value = parse_audio_probe(
                    encode_probe.read_text(encoding="utf-8")
                )
            except (OSError, ValueError) as exc:
                raise ReviewRequired(
                    f"audio duration evidence is incomplete for {stream.id}"
                ) from exc
            source_frame_value = None
            sidecar_frame_value = None
            final_frame_value = None
            sidecar_continuity = None
            final_continuity = None
            if continuity_required:
                try:
                    source_frame_value = parse_audio_frame_continuity(
                        source_frames.read_text(encoding="utf-8")
                    )
                    sidecar_frame_value = parse_audio_frame_continuity(
                        sidecar_frames.read_text(encoding="utf-8")
                    )
                    final_frame_value = parse_audio_frame_continuity(
                        final_frames.read_text(encoding="utf-8")
                    )
                except (OSError, ValueError) as exc:
                    raise ReviewRequired(
                        f"decoded audio frame evidence is incomplete for {stream.id}"
                    ) from exc
                source_offset = (
                    source_frame_value.first_pts_seconds - reference_title_start
                )
                sidecar_continuity = compare_audio_frame_continuity(
                    source_frame_value,
                    sidecar_frame_value,
                    audio_policy,
                    join_seconds=audio_join_seconds,
                    source_title_offset_seconds=source_offset,
                    encoded_title_offset_seconds=(
                        sidecar_frame_value.first_pts_seconds - reference_title_start
                    ),
                )
                final_continuity = compare_audio_frame_continuity(
                    source_frame_value,
                    final_frame_value,
                    audio_policy,
                    join_seconds=audio_join_seconds,
                    source_title_offset_seconds=source_offset,
                    encoded_title_offset_seconds=(
                        final_frame_value.first_pts_seconds - final_title_start
                    ),
                )
                if not sidecar_continuity.passed or not final_continuity.passed:
                    raise ReviewRequired(
                        "decoded audio sample-cursor continuity failed for "
                        f"{stream.id}",
                        details={
                            "action": item.action.value,
                            "source": source_frame_value.to_dict(),
                            "sidecar": sidecar_frame_value.to_dict(),
                            "final": final_frame_value.to_dict(),
                            "source_to_sidecar": sidecar_continuity.to_dict(),
                            "source_to_final": final_continuity.to_dict(),
                        },
                    )
                if final_continuity.excused_join_discontinuities:
                    self.database.add_event(
                        EventCreate(
                            job_id=job.id,
                            kind="worker.audio-continuity-warning",
                            message=(
                                f"audio track {stream.id} has small gaps or "
                                "overlaps at the playlist's clip joins; the "
                                "sample count matches and the job continues"
                            ),
                            payload={
                                "stream_id": stream.id,
                                "join_seconds": [
                                    str(item) for item in audio_join_seconds
                                ],
                                "source_to_final": final_continuity.to_dict(),
                                "report": audio_manifest_path.name,
                            },
                        )
                    )
            # Compare timing on the same rebased timeline used by the mux.  A
            # source track that legitimately started at +40 ms and was moved to
            # zero must not be mistaken for a -40 ms encode delay.
            source_timeline_value = replace(
                source_value,
                start_time=timeline_expected_starts[1 + final_audio_ordinal],
            )
            if source_value.duration is None or encode_value.duration is None:
                raise ReviewRequired(
                    f"audio duration evidence is incomplete for {stream.id}"
                )
            measured_durations = (source_value.duration, encode_value.duration)
            spectrum_duration = max(measured_durations)
            spectrum_windows = plan_spectrum_windows(spectrum_duration)
            spectrum_work = _ensure_contained_directory(
                paths.work / "spectrum" / f"audio-{number:02d}",
                root=paths.work,
                description="audio spectrum workspace directory",
            )

            for media_path, ordinal, input_codec, final_spectrum in (
                (
                    paths.reference,
                    source_audio_ordinal,
                    source_input_codec,
                    source_spectrum,
                ),
                (output, final_audio_ordinal, final_input_codec, encode_spectrum),
            ):
                window_outputs: list[Path] = []
                for window in spectrum_windows:
                    window_output = spectrum_work / (
                        f"{final_spectrum.stem}-window-{window.index + 1:03d}.png"
                    )
                    window_outputs.append(window_output)
                    command = spectrum_command(
                        media_path,
                        ordinal,
                        window_output,
                        start_seconds=window.start_seconds,
                        duration_seconds=window.duration_seconds,
                        height=window.height,
                        input_codec=input_codec,
                    )
                    command_inputs = {"argv": command, **track_command_inputs}
                    marker = paths.stages / f"qc-{window_output.stem}.json"
                    if not _valid_stage(marker, command_inputs, [window_output]):
                        self._runner(paths).run(
                            command,
                            cwd=paths.work,
                            stderr_path=paths.logs / f"{window_output.stem}.stderr",
                        )
                        inspect_png(window_output, require_high_bit_depth=True)
                        _write_stage(marker, command_inputs, [window_output])
                    else:
                        inspect_png(window_output, require_high_bit_depth=True)

                stitch_command = spectrum_stitch_command(
                    tuple(window_outputs), final_spectrum
                )
                stitch_inputs = {
                    "argv": stitch_command,
                    **track_command_inputs,
                    "window_sha256": [sha256_file(path) for path in window_outputs],
                }
                marker = paths.stages / f"qc-{final_spectrum.stem}.json"
                if not _valid_stage(marker, stitch_inputs, [final_spectrum]):
                    self._runner(paths).run(
                        stitch_command,
                        cwd=paths.work,
                        stderr_path=paths.logs / f"{final_spectrum.stem}.stderr",
                    )
                    inspect_png(final_spectrum, require_high_bit_depth=True)
                    _write_stage(marker, stitch_inputs, [final_spectrum])
                else:
                    inspect_png(final_spectrum, require_high_bit_depth=True)

            comparison = compare_audio_probes(source_timeline_value, encode_value)
            pcm_match = (
                sha256_file(source_pcm) == sha256_file(encode_pcm)
                if audio_policy.pcm_match_required
                else None
            )
            verification = verify_audio_output(
                source_timeline_value,
                encode_value,
                audio_policy,
                decoded_pcm_sha256_match=pcm_match,
                join_slack_seconds=(
                    final_continuity.join_slack_seconds
                    if final_continuity is not None
                    else Decimal(0)
                ),
            )
            try:
                source_signal = parse_audio_analysis(
                    source_analysis.read_text(encoding="utf-8", errors="replace")
                )
                encode_signal = parse_audio_analysis(
                    encode_analysis.read_text(encoding="utf-8", errors="replace")
                )
            except (OSError, ValueError) as exc:
                raise ReviewRequired(
                    f"audio signal evidence is incomplete for {stream.id}"
                ) from exc
            signal_verification = verify_audio_signal(
                source_signal,
                encode_signal,
                audio_policy,
                decoded_pcm_sha256_match=pcm_match,
            )
            one_sample_tolerance = Decimal(1) / Decimal(source_value.sample_rate)
            delay_within_one_sample = (
                abs(comparison.delay_seconds) <= one_sample_tolerance
            )
            if not verification.passed:
                raise ReviewRequired(
                    f"final audio verification failed for {stream.id}",
                    details={
                        "action": item.action.value,
                        "comparison": comparison.to_dict(),
                        "effective_target": audio_policy.to_dict(),
                        "verification": verification.to_dict(),
                    },
                )
            if not signal_verification.passed:
                raise ReviewRequired(
                    f"audio signal safety verification failed for {stream.id}",
                    details={
                        "action": item.action.value,
                        "source_signal": source_signal.to_dict(),
                        "encode_signal": encode_signal.to_dict(),
                        "signal_verification": signal_verification.to_dict(),
                        "decoded_pcm_sha256_match": pcm_match,
                        "decoded_pcm_sha256_required": (
                            audio_policy.pcm_match_required
                        ),
                    },
                )
            if verification.warnings or signal_verification.warnings:
                self.database.add_event(
                    EventCreate(
                        job_id=job.id,
                        kind="worker.audio-qc-warning",
                        message=(
                            f"audio track {stream.id} has level or bitrate "
                            "findings that do not show a broken encode; the "
                            "job continues"
                        ),
                        payload={
                            "stream_id": stream.id,
                            "action": item.action.value,
                            "warnings": [
                                *verification.warnings,
                                *signal_verification.warnings,
                            ],
                            "report": audio_manifest_path.name,
                        },
                    )
                )
            source_probe_value = asdict(source_value)
            source_timeline_probe_value = asdict(source_timeline_value)
            encode_probe_value = asdict(encode_value)
            for value in (
                source_probe_value,
                source_timeline_probe_value,
                encode_probe_value,
            ):
                value["start_time"] = str(value["start_time"])
                if value["duration"] is not None:
                    value["duration"] = str(value["duration"])
            audio_results.append(
                {
                    "stream_id": stream.id,
                    "action": item.action.value,
                    "source_probe": source_probe_value,
                    "source_timeline_probe": source_timeline_probe_value,
                    "encode_probe": encode_probe_value,
                    "comparison": comparison.to_dict(),
                    "verification_mode": audio_policy.verification_mode,
                    "effective_target": audio_policy.to_dict(),
                    "verification": verification.to_dict(),
                    "source_signal": source_signal.to_dict(),
                    "encode_signal": encode_signal.to_dict(),
                    "signal_verification": signal_verification.to_dict(),
                    "decoded_pcm_sha256_match": pcm_match,
                    "decoded_pcm_sha256_required": audio_policy.pcm_match_required,
                    "decoded_frame_continuity_required": continuity_required,
                    "source_frame_continuity": (
                        source_frame_value.to_dict()
                        if source_frame_value is not None
                        else None
                    ),
                    "sidecar_frame_continuity": (
                        sidecar_frame_value.to_dict()
                        if sidecar_frame_value is not None
                        else None
                    ),
                    "final_frame_continuity": (
                        final_frame_value.to_dict()
                        if final_frame_value is not None
                        else None
                    ),
                    "source_to_sidecar_continuity": (
                        sidecar_continuity.to_dict()
                        if sidecar_continuity is not None
                        else None
                    ),
                    "source_to_final_continuity": (
                        final_continuity.to_dict()
                        if final_continuity is not None
                        else None
                    ),
                    "delay_within_one_sample": delay_within_one_sample,
                    "timing_within_tolerance": verification.timing_within_tolerance,
                    "duration_within_tolerance": verification.duration_within_tolerance,
                    "delay_tolerance_seconds": str(
                        verification.timing_tolerance_seconds
                    ),
                    "source_pcm_sha256": (
                        sha256_file(source_pcm)
                        if audio_policy.pcm_match_required
                        else None
                    ),
                    "encode_pcm_sha256": (
                        sha256_file(encode_pcm)
                        if audio_policy.pcm_match_required
                        else None
                    ),
                    "source_spectrum": source_spectrum.name,
                    "encode_spectrum": encode_spectrum.name,
                    "source_spectrum_sha256": sha256_file(source_spectrum),
                    "encode_spectrum_sha256": sha256_file(encode_spectrum),
                    "spectrum_coverage_seconds": str(spectrum_duration),
                    "spectrum_window_count": len(spectrum_windows),
                    "spectrum_max_window_seconds": "300",
                }
            )
            track_outputs = [
                source_probe,
                encode_probe,
                source_analysis,
                encode_analysis,
                source_spectrum,
                encode_spectrum,
            ]
            if audio_policy.pcm_match_required:
                track_outputs.extend((source_pcm, encode_pcm))
            if continuity_required:
                track_outputs.extend((source_frames, sidecar_frames, final_frames))
            audio_outputs.extend(track_outputs)
            audio_inputs["tracks"].append(
                {
                    "stream": stream.id,
                    "action": item.action.value,
                    "sha256": intermediate_sha256,
                    "effective_audio_policy": audio_policy.to_dict(),
                    "audio_decode_policy": decode_policy,
                }
            )
        audio_marker = paths.stages / "qc-audio.json"
        if not _valid_stage(audio_marker, audio_inputs, audio_outputs):
            atomic_write_json(
                audio_manifest_path, {"schema_version": 4, "tracks": audio_results}
            )
            _write_stage(audio_marker, audio_inputs, audio_outputs)
        av_sync_report = self._verify_av_sync(
            job, paths, playlist, retained, output, audio_ordinals
        )
        reports.append(av_sync_report)

        for report in reports:
            kind = (
                DatabaseArtifactKind.MEDIAINFO
                if report.name == "mediainfo.txt"
                else DatabaseArtifactKind.MKVINFO
                if report.name in {"mkvinfo.txt", "mkvmerge-identify.json"}
                else DatabaseArtifactKind.REPORT
            )
            self._register_artifact(
                job.id,
                report,
                kind,
                report.name,
                mime_type=(
                    "application/json" if report.suffix == ".json" else "text/plain"
                ),
            )
        self._register_artifact(
            job.id,
            audio_manifest_path,
            DatabaseArtifactKind.AUDIO_COMPARISON,
            audio_manifest_path.name,
            mime_type="application/json",
        )
        for spectrum in spectrograms:
            self._register_artifact(
                job.id,
                spectrum,
                DatabaseArtifactKind.SPECTROGRAM,
                spectrum.name,
                mime_type="image/png",
            )
        self._merge_external_tracks(job, paths, selection)
        self.queue.advance(
            job.id, JobState.COMPARISON, message="container and audio QC passed"
        )

    def _verify_av_sync(
        self,
        job: Job,
        paths: JobPaths,
        playlist: PlaylistCandidate,
        retained: Sequence[tuple[int, TrackSelection, MediaStream]],
        output: Path,
        audio_ordinals: Mapping[str, int],
    ) -> Path:
        """Measure each final audio track's sound against the source (qc.av_sync)."""

        report = paths.analysis / "av-sync.json"
        try:
            origin = Decimal(
                str(json.loads(paths.timeline_json.read_text(encoding="utf-8"))["origin_seconds"])
            )
        except (OSError, KeyError, TypeError, ValueError, ArithmeticError) as exc:
            raise ReviewRequired("timeline plan is missing or invalid") from exc
        duration = Decimal(str(playlist.duration_seconds))
        inputs = {
            # 2: windows are sought by absolute timestamp (-seek_timestamp 1).
            "schema_version": 2,
            "reference_sha256": sha256_file(paths.reference),
            "output_sha256": sha256_file(output),
            "origin_seconds": str(origin),
            "window_seconds": str(av_sync.WINDOW_SECONDS),
            "tolerance_ms": str(av_sync.TOLERANCE_MS),
            "tracks": [stream.id for _number, _item, stream in retained],
        }
        marker = paths.stages / "qc-av-sync.json"
        if not _valid_stage(marker, inputs, [report]):
            root = _ensure_contained_directory(
                paths.work / "av-sync", root=paths.work, description="A/V sync windows"
            )
            tracks: list[dict[str, Any]] = []
            for final_ordinal, (number, item, stream) in enumerate(retained):
                source_args = audio_decode_input_args(normalize_audio_codec_name(stream.codec))
                final_args = audio_decode_input_args(
                    normalize_audio_codec_name(expected_audio_codec(item.action.value, stream.codec))
                )
                windows: list[av_sync.SyncWindow] = []
                for index, start in enumerate(av_sync.window_starts(duration)):
                    reference_start = start + origin
                    if reference_start < 0:
                        continue
                    reference_raw = root / f"audio-{number:02d}-reference-{index}.f32"
                    final_raw = root / f"audio-{number:02d}-final-{index}.f32"
                    for command, raw in (
                        (
                            av_sync.sync_window_command(
                                paths.reference,
                                audio_ordinals[stream.id],
                                reference_start,
                                reference_raw,
                                input_args=source_args,
                            ),
                            reference_raw,
                        ),
                        (
                            av_sync.sync_window_command(
                                output, final_ordinal, start, final_raw, input_args=final_args
                            ),
                            final_raw,
                        ),
                    ):
                        self._runner(paths).run(
                            command,
                            cwd=paths.work,
                            stderr_path=paths.logs / f"{raw.stem}.log",
                        )
                    try:
                        windows.append(
                            av_sync.window_result(
                                start,
                                reference_start,
                                av_sync.read_samples(reference_raw),
                                av_sync.read_samples(final_raw),
                            )
                        )
                    except ImportError:
                        windows.append(
                            av_sync.SyncWindow(
                                str(start), str(reference_start), None, None, False, "numpy_missing"
                            )
                        )
                    finally:
                        reference_raw.unlink(missing_ok=True)
                        final_raw.unlink(missing_ok=True)
                verdict = av_sync.judge(windows)
                tracks.append(
                    {
                        "track_number": number,
                        "stream_id": stream.id,
                        "action": item.action.value,
                        **verdict.to_dict(),
                    }
                )
            atomic_write_json(
                report,
                {"schema_version": 1, "origin_seconds": str(origin), "tracks": tracks},
            )
            _write_stage(marker, inputs, [report])
        document = json.loads(report.read_text(encoding="utf-8"))
        tracks = [track for track in document.get("tracks", []) if isinstance(track, dict)]
        out_of_sync = [track for track in tracks if track.get("status") == "out_of_sync"]
        if out_of_sync:
            first = out_of_sync[0]
            raise ReviewRequired(
                f"audio track {first.get('stream_id')} is {first.get('lag_ms')} ms out of "
                "sync with the source",
                details={"report": report.name, "tracks": [t.get("stream_id") for t in out_of_sync]},
            )
        inconclusive = [track.get("stream_id") for track in tracks if track.get("status") == "inconclusive"]
        if inconclusive:
            self.database.add_event(
                EventCreate(
                    job_id=job.id,
                    kind="worker.av-sync-warning",
                    message=(
                        "the audio sync of some tracks could not be measured (too quiet "
                        "or no clear match in the sampled windows); the job continues"
                    ),
                    payload={"tracks": inconclusive, "report": report.name},
                )
            )
        return report

    @staticmethod
    def _reference_png_pipeline(
        script: Path,
        frame: int,
        output: Path,
        *,
        hdr_native: bool,
        source_hdr10: bool,
        color: ColorMetadata,
    ) -> list[list[str]]:
        filters = png_filter_chain(
            hdr_native=hdr_native,
            source_hdr10=source_hdr10,
            color_primaries=color.primaries,
            color_transfer=color.transfer,
            color_matrix=color.matrix,
            color_range=color.range,
        )
        start, keep = reference_frame_preroll(frame)
        return [
            [
                "vspipe",
                "--container",
                "y4m",
                "--start",
                str(start),
                "--end",
                str(frame),
                str(script),
                "-",
            ],
            [
                "ffmpeg",
                "-hide_banner",
                "-nostdin",
                "-v",
                "warning",
                "-f",
                "yuv4mpegpipe",
                "-i",
                "pipe:0",
                "-vf",
                ",".join((keep, *filters)),
                "-frames:v",
                "1",
                "-fps_mode",
                "passthrough",
                "-update",
                "1",
                "-c:v",
                "png",
                "-compression_level",
                "6",
                "-y",
                str(output),
            ],
        ]

    @staticmethod
    def _sample_metric_pipeline(
        reference_png: Path,
        encoded_png: Path,
        ssim_output: Path,
        psnr_output: Path,
    ) -> list[list[str]]:
        """Measure only one selected proof pair, never the complete title."""

        ssim_stats = str(ssim_output).replace("\\", "/").replace(":", "\\:")
        psnr_stats = str(psnr_output).replace("\\", "/").replace(":", "\\:")
        filter_value = (
            "[0:v]format=gbrp16le,split=2[r1][r2];"
            "[1:v]format=gbrp16le,split=2[e1][e2];"
            f"[e1][r1]ssim=stats_file={ssim_stats}[ssimout];"
            f"[e2][r2]psnr=stats_file={psnr_stats}[psnrout]"
        )
        return [
            [
                "ffmpeg",
                "-hide_banner",
                "-nostdin",
                "-v",
                "info",
                "-i",
                str(reference_png),
                "-i",
                str(encoded_png),
                "-filter_complex",
                filter_value,
                "-map",
                "[ssimout]",
                "-map",
                "[psnrout]",
                "-f",
                "null",
                "-",
            ],
        ]

    @staticmethod
    def _reference_y4m_pipeline(
        script: Path, frame: int, output: Path
    ) -> list[list[str]]:
        start, keep = reference_frame_preroll(frame)
        return [
            [
                "vspipe",
                "--container",
                "y4m",
                "--start",
                str(start),
                "--end",
                str(frame),
                str(script),
                "-",
            ],
            [
                "ffmpeg",
                "-hide_banner",
                "-nostdin",
                "-v",
                "warning",
                "-f",
                "yuv4mpegpipe",
                "-i",
                "pipe:0",
                "-vf",
                keep,
                "-frames:v",
                "1",
                # The Y4M muxer rejects 10-bit pixel formats without this
                # (exit code 234), which stopped every UHD HDR10 comparison.
                "-strict",
                "-1",
                "-f",
                "yuv4mpegpipe",
                "-y",
                str(output),
            ],
        ]

    @staticmethod
    def _metric_stat(path: Path, name: str) -> float | str | None:
        """Read one FFmpeg key without making metrics-log wording an invariant."""

        try:
            value = re.search(
                rf"(?:^|\s){re.escape(name)}:([^\s]+)",
                path.read_text(encoding="utf-8", errors="replace"),
            )
        except OSError:
            return None
        if value is None:
            return None
        raw = value.group(1)
        if raw.casefold() in {"inf", "+inf", "-inf", "nan"}:
            return raw
        try:
            return float(raw)
        except ValueError:
            return None

    def _sampled_final_vmaf(
        self,
        job: Job,
        paths: JobPaths,
        selection: ParsedSelection,
        reference_info: Any,
        encoded_input: Path,
        *,
        picture_height: int | None,
        reference_sha256: str,
        encoded_sha256: str,
        timeout: Callable[[], float],
    ) -> Path:
        """VMAF of the finished file on windows spread over the title.

        Informational, not a gate: the native-YUV SSIM/PSNR pairs remain the
        acceptance test.  Both sides are read through VapourSynth with the same
        windows (the reference graph and the final MKV via L-SMASH), so no
        full-title decode is needed.  A failed measurement is recorded as
        unavailable instead of failing a finished encode.
        """

        report = paths.comparison / "video-vmaf.json"
        work = paths.work / "comparison-vmaf"
        work.mkdir(mode=0o750, parents=True, exist_ok=True)
        try:
            windows = plan_sample_windows(
                reference_info.frames,
                Fraction(reference_info.fps_numerator, reference_info.fps_denominator),
                samples=FINAL_VMAF_SAMPLES,
                sample_seconds=FINAL_VMAF_SAMPLE_SECONDS,
            )
        except CrfSearchError as exc:
            atomic_write_json(
                report,
                {"schema_version": 1, "status": "unavailable", "reason": str(exc)},
            )
            return report
        window_pairs = tuple((item.start_frame, item.frame_count) for item in windows)
        frame_rate = Fraction(reference_info.fps_numerator, reference_info.fps_denominator)

        def with_times(items: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
            # Timecodes let the comparison page point at the weakest windows.
            return [
                {
                    **item,
                    "start_seconds": round(float(item["start_frame"] / frame_rate), 3),
                    "end_seconds": round(
                        float((item["start_frame"] + item["frame_count"]) / frame_rate), 3
                    ),
                }
                for item in items
            ]

        reference_plan = self._source_plan(
            paths,
            script_path=work / "reference-sample.vpy",
            temporal_filter=selection.temporal_filter,
            crop=selection.crop,
            sample_windows=window_pairs,
        )
        # The final MKV is already cropped and filtered; L-SMASH indexes it in
        # seconds where BestSource would decode the whole file.
        encode_plan = ReferenceScriptPlan(
            source=encoded_input,
            cache_path=work / "encode-index",
            script_path=work / "encode-sample.vpy",
            sample_windows=window_pairs,
            source_filter=SourceFilter.LSMAS,
        )
        reference_content = render_reference_script(reference_plan)
        encode_content = render_reference_script(encode_plan)
        model_4k = vmaf_model_for_height(picture_height)
        hdr10 = selection.settings.hdr10.enabled
        inputs = {
            "schema_version": 1,
            "reference_sha256": reference_sha256,
            "encoded_sha256": encoded_sha256,
            "reference_script": hashlib.sha256(reference_content.encode()).hexdigest(),
            "encode_script": hashlib.sha256(encode_content.encode()).hexdigest(),
            "model_4k": model_4k,
            "hdr10": hdr10,
        }
        marker = paths.stages / "comparison-sampled-vmaf.json"
        if _valid_stage(marker, inputs, [report]):
            return report
        atomic_write_text(reference_plan.script_path, reference_content)
        atomic_write_text(encode_plan.script_path, encode_content)
        raw = work / "vmaf.json"
        model = "vmaf_4k_v0.6.1" if model_4k else "vmaf_v0.6.1"
        try:
            self._runner(paths).run(
                streamed_vmaf_command(
                    reference_plan.script_path,
                    encode_plan.script_path,
                    raw,
                    hdr10=hdr10,
                    model_4k=model_4k,
                    threads=_vmaf_thread_count(),
                    vmaf_only=True,
                    fifo_root=self.settings.cache_root / "vmaf",
                    encoded_is_script=True,
                ),
                cwd=paths.work,
                stderr_path=paths.logs / "comparison-vmaf.log",
                timeout=timeout(),
            )
            summary = summarize_sampled_vmaf(
                json.loads(raw.read_text(encoding="utf-8")), windows
            )
            summary["windows"] = with_times(summary["windows"])
            document: dict[str, Any] = {
                "schema_version": 1,
                "status": "measured",
                "scope": "sampled_windows_of_the_final_file",
                "model": model,
                "hdr10_proof_transform": hdr10,
                **summary,
            }
            message = (
                f"sampled VMAF of the final file: mean {summary['mean']:.2f}, "
                f"1% low {summary['percentile_1']:.2f} ({summary['frames']} frames)"
            )
        except (
            ProcessFailure,
            subprocess.TimeoutExpired,
            OSError,
            CrfSearchError,
            json.JSONDecodeError,
        ) as exc:
            reason = sanitize_text(str(exc))[:400]
            document = {
                "schema_version": 1,
                "status": "unavailable",
                "reason": reason,
                "model": model,
                "windows": with_times([item.to_dict() for item in windows]),
            }
            message = f"sampled VMAF of the final file is unavailable: {reason}"
        atomic_write_json(report, document)
        _write_stage(marker, inputs, [report])
        self.database.add_event(
            EventCreate(
                job_id=job.id,
                kind="worker.final-vmaf",
                message=message,
                payload={
                    key: document.get(key)
                    for key in ("status", "mean", "harmonic_mean", "percentile_1", "model")
                },
            )
        )
        return report

    def _comparison(self, job: Job, paths: JobPaths) -> None:
        scan, selection = self._load_prepared_scan_and_selection(job, paths)
        encoded_input = paths.muxed_output
        if not encoded_input.is_file():
            raise RuntimeError("final Matroska output is missing before comparison")

        # Twenty-four distributed native-YUV pairs are still bounded, but their
        # open-GOP-safe extraction is materially stronger than the former five
        # RGB screenshots and needs a realistic worker budget.
        comparison_playlist = scan.playlist(selection.playlist_id)
        comparison_base = (
            comparison_playlist.video_streams[0].video
            if comparison_playlist.video_streams
            else None
        )
        budget_scale = comparison_budget_scale(
            comparison_base.width if comparison_base else None,
            comparison_base.height if comparison_base else None,
        )
        time_scale = self._comparison_time_scale
        deadline_seconds = COMPARISON_DEADLINE_SECONDS * budget_scale * time_scale
        comparison_deadline = time.monotonic() + deadline_seconds
        probe_limit = COMPARISON_FRAME_PROBE_TIMEOUT_SECONDS * budget_scale

        def remaining_timeout(per_command_limit: float) -> float:
            remaining = comparison_deadline - time.monotonic()
            if remaining <= 1:
                # The same path as a command timeout: retried with a longer
                # budget, then a resumable review.
                raise subprocess.TimeoutExpired(
                    ["comparison"], deadline_seconds
                )
            return max(1.0, min(per_command_limit * time_scale, remaining))

        script_sha256 = sha256_file(paths.script)
        reference_sha256 = _recorded_output_sha256(
            paths.stages / "reference-remux.json", paths.reference
        )
        if reference_sha256 is None:
            raise RuntimeError("reference remux checkpoint digest is missing")
        encoded_sha256 = _recorded_output_sha256(
            paths.stages / "mux.json", encoded_input
        )
        if encoded_sha256 is None:
            raise RuntimeError("final MKV mux checkpoint digest is missing")
        self.database.record_progress(
            job.id,
            0.925,
            message="fast comparison: preparing bounded samples",
            expected_state=JobState.COMPARISON,
            emit_event=False,
        )

        reference_info_path = paths.comparison / "reference-vapoursynth-info.txt"
        reference_info_inputs = {
            "policy_schema_version": 2,
            "scan_fingerprint": scan.fingerprint,
            "playlist_id": selection.playlist_id,
            "angle": selection.angle,
            "reference_sha256": reference_sha256,
            "script_sha256": script_sha256,
        }
        reference_info_marker = paths.stages / "comparison-reference-info.json"
        if not _valid_stage(
            reference_info_marker, reference_info_inputs, [reference_info_path]
        ):
            self._runner(paths).run(
                vspipe_info_command(paths.script),
                cwd=paths.work,
                stdout_path=reference_info_path,
                stderr_path=paths.logs / "comparison-reference-info.stderr",
                timeout=remaining_timeout(60),
            )
            _write_stage(
                reference_info_marker, reference_info_inputs, [reference_info_path]
            )
        reference_info = parse_vspipe_info(
            reference_info_path.read_text(encoding="utf-8", errors="replace")
        )

        playlist = scan.playlist(selection.playlist_id)
        encoded_packet_report = paths.analysis / "final-video-packet-sizes.csv"
        mux_integrity_report = paths.analysis / "video-mux-integrity.json"
        final_video_timeline_path = (
            paths.work / "video-mux-integrity" / "final-video-timeline.json"
        )
        completeness_report = paths.analysis / "video-frame-completeness.json"
        if not encoded_packet_report.is_file():
            raise ReviewRequired(
                "encoded video packet-count evidence is missing before comparison"
            )
        _assert_stage_outputs_current(
            paths.stages / "video-mux-integrity.json",
            [mux_integrity_report, final_video_timeline_path],
            stage_name="video mux integrity",
        )
        try:
            mux_integrity_document = json.loads(
                mux_integrity_report.read_text(encoding="utf-8")
            )
            final_timeline = parse_packet_timeline(
                final_video_timeline_path.read_text(encoding="utf-8")
            )
            if (
                mux_integrity_document.get("status") != "passed"
                or final_timeline.presentation_span_ms is None
                or final_timeline.presentation_span_ms <= 0
                or final_timeline.missing_pts_count != 0
                or final_timeline.missing_duration_count != 0
            ):
                raise ValueError("final video packet timeline is incomplete")
            final_video_duration = Decimal(
                final_timeline.presentation_span_ms
            ) / Decimal(1000)
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ReviewRequired(
                "final video packet-timeline duration evidence is invalid",
                details={"report": mux_integrity_report.name},
            ) from exc
        completeness_inputs = {
            "policy_schema_version": 3,
            "final_mkv_sha256": encoded_sha256,
            "reference_info_sha256": sha256_file(reference_info_path),
            "encoded_packet_report_sha256": sha256_file(encoded_packet_report),
            "mux_integrity_report_sha256": sha256_file(mux_integrity_report),
            "final_video_timeline_sha256": sha256_file(final_video_timeline_path),
            "title_duration_seconds": str(playlist.duration_seconds),
            "title_duration_is_estimate": _title_duration_is_estimate(scan, playlist),
            "final_video_duration_seconds": str(final_video_duration),
            "tolerance_frames": 2,
        }
        completeness_marker = paths.stages / "video-frame-completeness.json"
        if not _valid_stage(
            completeness_marker,
            completeness_inputs,
            [completeness_report],
        ):
            try:
                encoded_packet_summary = parse_video_packet_sizes(
                    encoded_packet_report.read_text(encoding="utf-8")
                )
                cadence_verdict = require_video_cadence(
                    final_timeline,
                    reference_info.frames,
                    fps_numerator=reference_info.fps_numerator,
                    fps_denominator=reference_info.fps_denominator,
                )
                completeness_verdict = require_video_completeness(
                    reference_info.frames,
                    encoded_packet_summary.packet_count,
                    fps_numerator=reference_info.fps_numerator,
                    fps_denominator=reference_info.fps_denominator,
                    title_duration_seconds=playlist.duration_seconds,
                    final_video_duration_seconds=final_video_duration,
                    tolerance_frames=2,
                    title_duration_is_estimate=_title_duration_is_estimate(scan, playlist),
                )
            except (OSError, ValueError) as exc:
                error = str(exc)
                atomic_write_json(
                    completeness_report,
                    {
                        "schema_version": 1,
                        "status": "needs_review",
                        "error": error,
                    },
                )
                raise ReviewRequired(
                    "video frame-count or duration completeness requires review",
                    details={
                        "error": error,
                        "report": completeness_report.name,
                    },
                ) from exc
            atomic_write_json(
                completeness_report,
                {
                    "schema_version": 1,
                    "status": (
                        "passed_with_warnings"
                        if completeness_verdict.warnings
                        else "passed"
                    ),
                    "encoded_packet_summary": encoded_packet_summary.to_dict(),
                    "cadence_verdict": cadence_verdict.to_dict(),
                    "verdict": completeness_verdict.to_dict(),
                },
            )
            if completeness_verdict.warnings:
                self.database.add_event(
                    EventCreate(
                        job_id=job.id,
                        kind="worker.video-duration-warning",
                        message=(
                            "the estimated playlist duration differs from the "
                            "frame count; the job continues"
                        ),
                        payload={
                            "warnings": list(completeness_verdict.warnings),
                            "report": completeness_report.name,
                        },
                    )
                )
            _write_stage(
                completeness_marker,
                completeness_inputs,
                [completeness_report],
            )
        try:
            completeness_document = json.loads(
                completeness_report.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise ReviewRequired(
                "video completeness report is missing or invalid"
            ) from exc

        intervals = plan_sample_intervals(reference_info)
        interval_manifest = [
            {
                "start_seconds": str(item.start_seconds),
                "duration_seconds": str(item.duration_seconds),
            }
            for item in intervals
        ]
        sample_plan = {
            "schema_version": 2,
            "strategy": "bounded_distributed_read_intervals",
            "intervals": interval_manifest,
            "planned_interval_seconds_per_input": str(
                sum((item.duration_seconds for item in intervals), Decimal(0))
            ),
            "full_title_scan": False,
        }

        encoded_origin_path = paths.comparison / "sampled-encoded-origin.json"
        encoded_origin_inputs = {"final_mkv_sha256": encoded_sha256}
        encoded_origin_marker = (
            paths.stages / "comparison-sampled-encoded-origin-v2.json"
        )
        if not _valid_stage(
            encoded_origin_marker, encoded_origin_inputs, [encoded_origin_path]
        ):
            self._runner(paths).run(
                ffprobe_frame_origin_command(encoded_input),
                cwd=paths.work,
                stdout_path=encoded_origin_path,
                stderr_path=paths.logs / "comparison-sampled-encoded-origin.stderr",
                timeout=remaining_timeout(30),
            )
            _write_stage(
                encoded_origin_marker, encoded_origin_inputs, [encoded_origin_path]
            )
        try:
            encoded_pts_origin = parse_ffprobe_frame_origin(
                encoded_origin_path.read_text(encoding="utf-8")
            )
        except FrameSelectionError as exc:
            raise ReviewRequired(
                f"encoded comparison PTS origin is invalid: {exc}"
            ) from exc

        encoded_probe = paths.comparison / "sampled-encoded-frames.json"
        encoded_probe_inputs = {
            "final_mkv_sha256": encoded_sha256,
            "sample_plan": sample_plan,
            "pts_origin": str(encoded_pts_origin),
        }
        encoded_probe_marker = (
            paths.stages / "comparison-sampled-encoded-frame-probe-v2.json"
        )

        def probe_encoded_frames() -> None:
            if _valid_stage(encoded_probe_marker, encoded_probe_inputs, [encoded_probe]):
                return
            self._runner(paths).run(
                ffprobe_sampled_frame_command(
                    encoded_input, intervals, pts_origin=encoded_pts_origin
                ),
                cwd=paths.work,
                stdout_path=encoded_probe,
                stderr_path=paths.logs / "comparison-sampled-encoded-probe.stderr",
                timeout=remaining_timeout(probe_limit),
            )
            _write_stage(encoded_probe_marker, encoded_probe_inputs, [encoded_probe])

        def parse_encoded_sample() -> list[FrameRecord]:
            try:
                return parse_sampled_ffprobe_frames(
                    encoded_probe.read_text(encoding="utf-8"),
                    reference_info,
                    pts_origin=encoded_pts_origin,
                )
            except FrameSelectionError as exc:
                raise ReviewRequired(
                    f"encoded comparison sample is invalid: {exc}"
                ) from exc

        source_type_available = selection.temporal_filter is TemporalFilter.PROGRESSIVE
        # On an unchanged progressive timeline, the user's strict source/encode
        # I/P/B requirement is mandatory. A temporal transform has no meaningful
        # one-to-one source bitstream frame type, so it remains index/PTS aligned.
        require_source_type_match = source_type_available
        source_by_index: dict[int, FrameRecord] = {}
        source_pts_origin: Decimal | None = None
        if source_type_available:
            source_origin_path = paths.comparison / "sampled-source-origin.json"
            source_origin_inputs = {"reference_sha256": reference_sha256}
            source_origin_marker = (
                paths.stages / "comparison-sampled-source-origin-v2.json"
            )
            if not _valid_stage(
                source_origin_marker, source_origin_inputs, [source_origin_path]
            ):
                self._runner(paths).run(
                    ffprobe_frame_origin_command(paths.reference),
                    cwd=paths.work,
                    stdout_path=source_origin_path,
                    stderr_path=paths.logs / "comparison-sampled-source-origin.stderr",
                    timeout=remaining_timeout(30),
                )
                _write_stage(
                    source_origin_marker,
                    source_origin_inputs,
                    [source_origin_path],
                )
            try:
                source_pts_origin = parse_ffprobe_frame_origin(
                    source_origin_path.read_text(encoding="utf-8")
                )
            except FrameSelectionError as exc:
                raise ReviewRequired(
                    f"source comparison PTS origin is invalid: {exc}"
                ) from exc
            source_probe = paths.comparison / "sampled-source-frames.json"
            source_probe_inputs = {
                "reference_sha256": reference_sha256,
                "sample_plan": sample_plan,
                "pts_origin": str(source_pts_origin),
            }
            source_probe_marker = (
                paths.stages / "comparison-sampled-source-frame-probe-v2.json"
            )
            def probe_source_frames() -> None:
                if _valid_stage(source_probe_marker, source_probe_inputs, [source_probe]):
                    return
                self._runner(paths).run(
                    ffprobe_sampled_frame_command(
                        paths.reference, intervals, pts_origin=source_pts_origin
                    ),
                    cwd=paths.work,
                    stdout_path=source_probe,
                    stderr_path=paths.logs / "comparison-sampled-source-probe.stderr",
                    timeout=remaining_timeout(probe_limit),
                )
                _write_stage(source_probe_marker, source_probe_inputs, [source_probe])

            # The two sampled decodes read different files (UHD: 18 + 12 min
            # one after the other).
            self._live(paths).update(
                0.05,
                detail=(
                    "képtípusok vizsgálata a mintaszakaszokon",
                    "checking frame types in the sample sections",
                ),
                force=True,
            )
            self._run_independent(paths, [probe_encoded_frames, probe_source_frames])
            encoded = parse_encoded_sample()
            try:
                source_frames = parse_sampled_ffprobe_frames(
                    source_probe.read_text(encoding="utf-8"),
                    reference_info,
                    pts_origin=source_pts_origin,
                )
            except FrameSelectionError as exc:
                raise ReviewRequired(
                    f"source comparison sample is invalid: {exc}"
                ) from exc
            source_by_index = {item.presentation_index: item for item in source_frames}
            reference = source_frames
        else:
            probe_encoded_frames()
            encoded = parse_encoded_sample()
            reference = [
                FrameRecord(
                    presentation_index=item.presentation_index,
                    pts_seconds=item.pts_seconds,
                    pict_type=None,
                )
                for item in encoded
            ]

        try:
            pairs, adjusted_counts = select_frame_pairs_reducing_i(
                encoded,
                reference,
                total_pairs=self.settings.comparison_pair_count,
                timeline_frames=reference_info.frames,
                dual_type_match=require_source_type_match,
                # Tracker jobs: enough B pairs for Aither's B-frame comparison.
                type_counts=(
                    tracker_type_counts(self.settings.comparison_pair_count)
                    if selection.tracker_profile is not TrackerProfile.NONE
                    else None
                ),
            )
            if adjusted_counts is not None:
                self.database.add_event(
                    EventCreate(
                        job_id=job.id,
                        kind="worker.comparison-i-pairs",
                        message=(
                            f"comparison uses {adjusted_counts['I']} I pairs: too few "
                            "source and encode I-frames coincide in the sample windows"
                        ),
                        payload={"type_counts": adjusted_counts},
                    )
                )
        except FrameSelectionError as exc:
            raise ReviewRequired(
                "bounded comparison sampling could not find the required "
                f"same-frame I/P/B pairs: {exc}",
                details={
                    "sample_plan": sample_plan,
                    "requested_pairs": self.settings.comparison_pair_count,
                },
            ) from exc

        self.database.record_progress(
            job.id,
            0.94,
            message=f"fast comparison: {len(pairs)} I/P/B pairs selected",
            expected_state=JobState.COMPARISON,
            emit_event=True,
        )

        video = playlist.video_streams[0].video
        assert video is not None
        hdr = selection.settings.hdr10.enabled
        comparison_color = selection.settings.color
        clean_png_root = _ensure_contained_directory(
            paths.work / "comparison-metric-frames",
            root=paths.work,
            description="comparison metric-frame directory",
        )
        native_yuv_root = _ensure_contained_directory(
            paths.work / "comparison-native-yuv",
            root=paths.work,
            description="comparison native-YUV directory",
        )
        pngs: list[Path] = []
        metric_sidecars: list[Path] = []
        metric_samples: list[dict[str, Any]] = []
        # Clean (unlabelled) encode frames for the tracker description.
        screenshot_numbers = screenshot_pair_numbers(
            [pair.category for pair in pairs], selection.tracker_profile.value
        )
        manifest = comparison_manifest(pairs)
        manifest["schema_version"] = 4
        manifest["reference_alignment"] = "same_vapoursynth_output_frame_index"
        manifest["visual_annotation"] = {
            "schema_version": 1,
            "layout": "lossless_png_header_outside_picture_area",
            "fields": [
                "image_role",
                "zero_based_presentation_frame_index",
                "comparison_frame_type",
            ],
            "metrics_use_unannotated_pixels": True,
            "metrics_use_native_yuv_planes": True,
        }
        manifest["sampling"] = {
            **sample_plan,
            "requested_pair_count": self.settings.comparison_pair_count,
            "selected_pair_count": len(pairs),
            "encoded_pts_origin": str(encoded_pts_origin),
            "source_pts_origin": (
                str(source_pts_origin) if source_pts_origin is not None else None
            ),
        }
        manifest["frame_completeness"] = completeness_document
        manifest["distorted_input"] = {
            "role": "final_matroska_video_track_0",
            "path": encoded_input.name,
            "sha256": encoded_sha256,
        }
        manifest["source_bitstream_type_available"] = source_type_available
        manifest["source_bitstream_type_match_required"] = require_source_type_match
        manifest["reference_clip"] = {
            "frames": reference_info.frames,
            "fps_numerator": reference_info.fps_numerator,
            "fps_denominator": reference_info.fps_denominator,
        }
        for number, pair in enumerate(pairs, start=1):
            self._live(paths).update(
                0.2 + 0.6 * (number - 1) / max(1, len(pairs)),
                detail=(f"képpár {number} / {len(pairs)}", f"image pair {number} / {len(pairs)}"),
                force=True,
            )
            label = f"{number:02d}-{pair.category}-f{pair.presentation_index:09d}"
            reference_png = paths.comparison / f"{label}-reference.png"
            encoded_png = paths.comparison / f"{label}-encode.png"
            clean_reference_png = clean_png_root / f"{label}-reference-native.png"
            clean_encoded_png = clean_png_root / f"{label}-encode-native.png"
            encoded_record = next(
                item
                for item in encoded
                if item.presentation_index == pair.presentation_index
            )
            image_inputs = {
                "schema_version": 3,
                "script_sha256": script_sha256,
                "final_mkv_sha256": encoded_sha256,
                "frame": pair.presentation_index,
                "encoded_seek_pts_seconds": str(encoded_record.seek_pts_seconds),
                "extraction": "accurate_timestamp_seek",
                "reference_preroll_frames": LSMAS_FIRST_SEEK_PREROLL_FRAMES,
                "hdr_native": True,
                "visual_annotation": {
                    "schema_version": 1,
                    "source_label": "SOURCE",
                    "encode_label": "ENCODE",
                    "frame_type": pair.category,
                    "source_frame_type_mode": (
                        "native_bitstream_type"
                        if pair.source_pict_type is not None
                        else "matched_to_encode_frame_type"
                    ),
                },
            }
            image_marker = paths.stages / f"comparison-{label}-native-v3.json"
            if not _valid_stage(
                image_marker,
                image_inputs,
                [
                    clean_reference_png,
                    clean_encoded_png,
                    reference_png,
                    encoded_png,
                ],
            ):
                self._runner(paths).run_pipeline(
                    self._reference_png_pipeline(
                        paths.script,
                        pair.presentation_index,
                        clean_reference_png,
                        hdr_native=True,
                        source_hdr10=hdr,
                        color=comparison_color,
                    ),
                    cwd=paths.work,
                    stderr_paths=[
                        paths.logs / f"{label}-reference-vs.log",
                        paths.logs / f"{label}-reference-png.log",
                    ],
                    timeout=remaining_timeout(90),
                )
                self._runner(paths).run(
                    extract_png_at_timestamp_command(
                        encoded_input,
                        encoded_record.seek_pts_seconds,
                        clean_encoded_png,
                        hdr_native=True,
                        source_hdr10=hdr,
                        color_primaries=comparison_color.primaries,
                        color_transfer=comparison_color.transfer,
                        color_matrix=comparison_color.matrix,
                        color_range=comparison_color.range,
                    ),
                    cwd=paths.work,
                    stderr_path=paths.logs / f"{label}-encode-png.log",
                    timeout=remaining_timeout(60),
                )
                self._runner(paths).run(
                    annotate_comparison_png_command(
                        clean_reference_png,
                        reference_png,
                        image_role="SOURCE",
                        presentation_index=pair.presentation_index,
                        pict_type=pair.source_pict_type or pair.category,
                        matched_to_type=pair.source_pict_type is None,
                    ),
                    cwd=paths.work,
                    stderr_path=paths.logs / f"{label}-reference-label.log",
                    timeout=remaining_timeout(30),
                )
                self._runner(paths).run(
                    annotate_comparison_png_command(
                        clean_encoded_png,
                        encoded_png,
                        image_role="ENCODE",
                        presentation_index=pair.presentation_index,
                        pict_type=pair.category,
                    ),
                    cwd=paths.work,
                    stderr_path=paths.logs / f"{label}-encode-label.log",
                    timeout=remaining_timeout(30),
                )
                _write_stage(
                    image_marker,
                    image_inputs,
                    [
                        clean_reference_png,
                        clean_encoded_png,
                        reference_png,
                        encoded_png,
                    ],
                )
            inspect_png(clean_reference_png, require_high_bit_depth=hdr)
            inspect_png(clean_encoded_png, require_high_bit_depth=hdr)
            inspect_png(reference_png, require_high_bit_depth=hdr)
            inspect_png(encoded_png, require_high_bit_depth=hdr)
            pngs.extend((reference_png, encoded_png))
            pair_value = manifest["pairs"][number - 1]
            pair_value["reference_png"] = reference_png.name
            pair_value["encode_png"] = encoded_png.name
            pair_value["visual_label"] = {
                "reference_role": "SOURCE",
                "encode_role": "ENCODE",
                "frame_index": pair.presentation_index,
                "frame_index_base": 0,
                "frame_type": pair.category,
                "source_frame_type_mode": (
                    "native_bitstream_type"
                    if pair.source_pict_type is not None
                    else "matched_to_encode_frame_type"
                ),
            }
            pair_value["encoded_seek_pts_seconds"] = str(
                encoded_record.seek_pts_seconds
            )
            if pair.presentation_index in source_by_index:
                pair_value["source_container_pts_seconds"] = str(
                    source_by_index[pair.presentation_index].seek_pts_seconds
                )
            pair_value["reference_sha256"] = sha256_file(reference_png)
            pair_value["encode_sha256"] = sha256_file(encoded_png)
            if hdr:
                reference_sdr = paths.comparison / f"{label}-reference-sdr.png"
                encoded_sdr = paths.comparison / f"{label}-encode-sdr.png"
                clean_reference_sdr = clean_png_root / f"{label}-reference-sdr.png"
                clean_encoded_sdr = clean_png_root / f"{label}-encode-sdr.png"
                sdr_inputs = dict(image_inputs, hdr_native=False)
                sdr_marker = paths.stages / f"comparison-{label}-sdr-v3.json"
                if not _valid_stage(
                    sdr_marker,
                    sdr_inputs,
                    [
                        clean_reference_sdr,
                        clean_encoded_sdr,
                        reference_sdr,
                        encoded_sdr,
                    ],
                ):
                    self._runner(paths).run_pipeline(
                        self._reference_png_pipeline(
                            paths.script,
                            pair.presentation_index,
                            clean_reference_sdr,
                            hdr_native=False,
                            source_hdr10=True,
                            color=comparison_color,
                        ),
                        cwd=paths.work,
                        stderr_paths=[
                            paths.logs / f"{label}-reference-sdr-vs.log",
                            paths.logs / f"{label}-reference-sdr-png.log",
                        ],
                        timeout=remaining_timeout(90),
                    )
                    self._runner(paths).run(
                        extract_png_at_timestamp_command(
                            encoded_input,
                            encoded_record.seek_pts_seconds,
                            clean_encoded_sdr,
                            hdr_native=False,
                            source_hdr10=True,
                            color_primaries=comparison_color.primaries,
                            color_transfer=comparison_color.transfer,
                            color_matrix=comparison_color.matrix,
                            color_range=comparison_color.range,
                        ),
                        cwd=paths.work,
                        stderr_path=paths.logs / f"{label}-encode-sdr-png.log",
                        timeout=remaining_timeout(60),
                    )
                    self._runner(paths).run(
                        annotate_comparison_png_command(
                            clean_reference_sdr,
                            reference_sdr,
                            image_role="SOURCE",
                            presentation_index=pair.presentation_index,
                            pict_type=pair.source_pict_type or pair.category,
                            matched_to_type=pair.source_pict_type is None,
                        ),
                        cwd=paths.work,
                        stderr_path=paths.logs / f"{label}-reference-sdr-label.log",
                        timeout=remaining_timeout(30),
                    )
                    self._runner(paths).run(
                        annotate_comparison_png_command(
                            clean_encoded_sdr,
                            encoded_sdr,
                            image_role="ENCODE",
                            presentation_index=pair.presentation_index,
                            pict_type=pair.category,
                        ),
                        cwd=paths.work,
                        stderr_path=paths.logs / f"{label}-encode-sdr-label.log",
                        timeout=remaining_timeout(30),
                    )
                    _write_stage(
                        sdr_marker,
                        sdr_inputs,
                        [
                            clean_reference_sdr,
                            clean_encoded_sdr,
                            reference_sdr,
                            encoded_sdr,
                        ],
                    )
                inspect_png(clean_reference_sdr)
                inspect_png(clean_encoded_sdr)
                inspect_png(reference_sdr)
                inspect_png(encoded_sdr)
                pngs.extend((reference_sdr, encoded_sdr))
                pair_value["reference_sdr_png"] = reference_sdr.name
                pair_value["encode_sdr_png"] = encoded_sdr.name
                pair_value["reference_sdr_sha256"] = sha256_file(reference_sdr)
                pair_value["encode_sdr_sha256"] = sha256_file(encoded_sdr)
            if number in screenshot_numbers:
                # The tone-mapped view for HDR (what a browser shows), else the native frame.
                clean_view = (
                    clean_png_root / f"{label}-encode-sdr.png" if hdr else clean_encoded_png
                )
                screenshot = paths.comparison / f"{label}-screenshot.png"
                shutil.copyfile(clean_view, screenshot)
                inspect_png(screenshot)
                pngs.append(screenshot)
                pair_value["screenshot_png"] = screenshot.name
                pair_value["screenshot_sha256"] = sha256_file(screenshot)

            reference_y4m = native_yuv_root / f"{label}-reference.y4m"
            encoded_y4m = native_yuv_root / f"{label}-encode.y4m"
            yuv_inputs = {
                "schema_version": 1,
                "script_sha256": script_sha256,
                "final_mkv_sha256": encoded_sha256,
                "presentation_index": pair.presentation_index,
                "encoded_seek_pts_seconds": str(encoded_record.seek_pts_seconds),
                "pixel_format": selection.settings.pixel_format,
                "reference_preroll_frames": LSMAS_FIRST_SEEK_PREROLL_FRAMES,
            }
            yuv_marker = paths.stages / f"comparison-{label}-native-yuv.json"
            if not _valid_stage(yuv_marker, yuv_inputs, [reference_y4m, encoded_y4m]):
                self._runner(paths).run_pipeline(
                    self._reference_y4m_pipeline(
                        paths.script, pair.presentation_index, reference_y4m
                    ),
                    cwd=paths.work,
                    stderr_paths=[
                        paths.logs / f"{label}-reference-yuv-vs.log",
                        paths.logs / f"{label}-reference-yuv.log",
                    ],
                    timeout=remaining_timeout(120),
                )
                self._runner(paths).run(
                    extract_y4m_at_timestamp_command(
                        encoded_input,
                        encoded_record.seek_pts_seconds,
                        encoded_y4m,
                    ),
                    cwd=paths.work,
                    stderr_path=paths.logs / f"{label}-encode-yuv.log",
                    timeout=remaining_timeout(90),
                )
                _write_stage(yuv_marker, yuv_inputs, [reference_y4m, encoded_y4m])
            ssim_stats = paths.comparison / f"{label}.ssim.log"
            psnr_stats = paths.comparison / f"{label}.psnr.log"
            sample_metric_inputs = {
                "schema_version": 4,
                "reference_y4m_sha256": sha256_file(reference_y4m),
                "encode_y4m_sha256": sha256_file(encoded_y4m),
                "scope": "single_selected_native_yuv_plane_pair",
                "pixel_format": selection.settings.pixel_format,
            }
            sample_metric_marker = paths.stages / f"comparison-{label}-metrics-v4.json"
            if not _valid_stage(
                sample_metric_marker,
                sample_metric_inputs,
                [ssim_stats, psnr_stats],
            ):
                self._runner(paths).run(
                    native_yuv_metric_command(
                        reference_y4m,
                        encoded_y4m,
                        ssim_stats,
                        psnr_stats,
                        pixel_format=selection.settings.pixel_format,
                    ),
                    cwd=paths.work,
                    stderr_path=paths.logs / f"{label}-metrics.log",
                    timeout=remaining_timeout(60),
                )
                if not ssim_stats.is_file() or not psnr_stats.is_file():
                    raise RuntimeError(
                        f"native-YUV SSIM/PSNR output is incomplete for {label}"
                    )
                _write_stage(
                    sample_metric_marker,
                    sample_metric_inputs,
                    [ssim_stats, psnr_stats],
                )
            metric_sidecars.extend((ssim_stats, psnr_stats))
            try:
                ssim_values = parse_ffmpeg_metric_stats(
                    ssim_stats.read_text(encoding="utf-8", errors="replace")
                )
                psnr_values = parse_ffmpeg_metric_stats(
                    psnr_stats.read_text(encoding="utf-8", errors="replace")
                )
            except (OSError, ValueError) as exc:
                raise ReviewRequired(
                    f"native-YUV metrics are invalid for {label}: {exc}"
                ) from exc
            metric_samples.append(
                {
                    "category": pair.category,
                    "presentation_index": pair.presentation_index,
                    "reference_png": reference_png.name,
                    "encode_png": encoded_png.name,
                    "measurement_input": "native_yuv_planes_before_rgb_conversion",
                    "reference_measurement_sha256": sha256_file(reference_y4m),
                    "encode_measurement_sha256": sha256_file(encoded_y4m),
                    "ssim_all": ssim_values.get("All"),
                    "ssim_planes": {
                        "y": ssim_values.get("Y"),
                        "u": ssim_values.get("U"),
                        "v": ssim_values.get("V"),
                    },
                    "psnr_average_db": psnr_values.get("psnr_avg"),
                    # Signed mean error per plane (8-bit code values); None if unreadable.
                    "plane_bias_8bit": plane_bias(reference_y4m, encoded_y4m),
                    "psnr_planes_db": {
                        "y": psnr_values.get("psnr_y"),
                        "u": psnr_values.get("psnr_u"),
                        "v": psnr_values.get("psnr_v"),
                    },
                    "ssim_stats": {
                        "path": ssim_stats.name,
                        "sha256": sha256_file(ssim_stats),
                    },
                    "psnr_stats": {
                        "path": psnr_stats.name,
                        "sha256": sha256_file(psnr_stats),
                    },
                }
            )
            self.database.record_progress(
                job.id,
                0.94 + (0.035 * number / len(pairs)),
                message=f"fast comparison: pair {number}/{len(pairs)} complete",
                expected_state=JobState.COMPARISON,
                emit_event=number == len(pairs),
            )

        # Include Python-side validation, hashing and manifest finalization in
        # the same operator-visible wall-clock budget as the subprocesses.
        remaining_timeout(300)
        finite_ssim = [
            item["ssim_all"]
            for item in metric_samples
            if isinstance(item["ssim_all"], float)
        ]
        finite_psnr = [
            item["psnr_average_db"]
            for item in metric_samples
            if isinstance(item["psnr_average_db"], float)
        ]
        metrics = paths.comparison / "video-metrics.json"
        metric_document = {
            "schema_version": 4,
            "backend": "ffmpeg-native-yuv-sampled-ssim-psnr",
            "scope": "selected_ipb_native_yuv_plane_pairs",
            "full_title_measurement": False,
            "sample_count": len(metric_samples),
            "aggregate": {
                "ssim_all_mean": (
                    sum(finite_ssim) / len(finite_ssim) if finite_ssim else None
                ),
                "psnr_average_db_mean": (
                    sum(finite_psnr) / len(finite_psnr) if finite_psnr else None
                ),
                "plane_bias_8bit_mean": _mean_plane_bias(metric_samples),
            },
            "samples": metric_samples,
        }
        metric_errors = _sampled_video_metric_blockers(metric_samples)
        metric_warnings = tuple(
            item
            for item in _sampled_video_metric_errors(metric_samples)
            if item not in metric_errors
        )
        acceptance = (
            video_metrics_accepted(paths.comparison, metric_errors, metric_samples)
            if metric_errors
            else None
        )
        if not metric_errors:
            gate_status = "passed_with_warnings" if metric_warnings else "passed"
        else:
            gate_status = "accepted_by_operator" if acceptance else "needs_review"
        metric_document["quality_gate"] = {
            "status": gate_status,
            "errors": list(metric_errors),
            "warnings": list(metric_warnings),
            "thresholds": {
                "minimum_sample_ssim": 0.93,
                "minimum_mean_ssim": 0.95,
                "minimum_sample_psnr_db": 35,
                "minimum_mean_psnr_db": 38,
                "maximum_mean_plane_bias_8bit": MAXIMUM_MEAN_PLANE_BIAS,
                "maximum_b_minus_p_ssim_deficit": 0.03,
            },
            "blocking_thresholds": {
                "minimum_sample_ssim": BROKEN_SAMPLE_SSIM,
                "minimum_mean_ssim": BROKEN_MEAN_SSIM,
                "minimum_sample_psnr_db": BROKEN_SAMPLE_PSNR_DB,
                "minimum_mean_psnr_db": BROKEN_MEAN_PSNR_DB,
                "maximum_mean_plane_bias_8bit": MAXIMUM_MEAN_PLANE_BIAS,
            },
        }
        if acceptance is not None:
            metric_document["quality_gate"]["operator_acceptance"] = {
                "accepted_at": acceptance.get("accepted_at"),
            }
        atomic_write_json(metrics, metric_document)
        if metric_errors and acceptance is None:
            raise ReviewRequired(
                "sampled native-YUV video metrics require review",
                details={"errors": list(metric_errors), "report": metrics.name},
            )
        if metric_warnings or acceptance is not None:
            self.database.add_event(
                EventCreate(
                    job_id=job.id,
                    kind="worker.video-metrics-warning",
                    message=(
                        "sampled video metrics accepted by the operator"
                        if acceptance is not None
                        else "sampled video metrics are below the quality policy; the job continues"
                    ),
                    payload={
                        "errors": list(metric_errors),
                        "warnings": list(metric_warnings),
                        "report": metrics.name,
                    },
                )
            )
        _write_stage(
            paths.stages / "comparison-sampled-metrics-v4.json",
            {
                "pairs": [item.to_dict() for item in pairs],
                "backend": metric_document["backend"],
            },
            [metrics, *metric_sidecars],
        )
        manifest["metrics"] = {
            "path": metrics.name,
            "sha256": sha256_file(metrics),
            "backend": metric_document["backend"],
            "scope": metric_document["scope"],
            "sample_count": metric_document["sample_count"],
            "full_title_measurement": metric_document["full_title_measurement"],
            "aggregate": metric_document["aggregate"],
        }
        vmaf_picture_height = (
            None
            if comparison_base is None or comparison_base.height is None
            else comparison_base.height - selection.crop.top - selection.crop.bottom
        )
        self._live(paths).update(
            0.85,
            detail=("mintavett VMAF a kész fájlon", "sampled VMAF on the finished file"),
            force=True,
        )
        vmaf_report = self._sampled_final_vmaf(
            job,
            paths,
            selection,
            reference_info,
            encoded_input,
            picture_height=vmaf_picture_height,
            reference_sha256=reference_sha256,
            encoded_sha256=encoded_sha256,
            timeout=lambda: remaining_timeout(probe_limit),
        )
        vmaf_document = json.loads(vmaf_report.read_text(encoding="utf-8"))
        manifest["vmaf"] = {
            "path": vmaf_report.name,
            "sha256": sha256_file(vmaf_report),
            **{
                key: vmaf_document.get(key)
                for key in (
                    "status",
                    "model",
                    "frames",
                    "mean",
                    "harmonic_mean",
                    "percentile_1",
                    "minimum",
                    "windows",
                )
            },
        }
        manifest_path = paths.comparison / "video-comparison.json"
        atomic_write_json(manifest_path, manifest)
        _current_comparison_pngs(paths, prune=True)
        allowed_metric_names = {path.name for path in metric_sidecars}
        for stale_metric in (
            *paths.comparison.glob("*.ssim.log"),
            *paths.comparison.glob("*.psnr.log"),
        ):
            if stale_metric.name not in allowed_metric_names:
                stale_metric.unlink(missing_ok=True)
        comparison_outputs = [manifest_path, metrics, vmaf_report, *metric_sidecars, *pngs]
        _write_stage(
            paths.stages / "comparison.json",
            {
                "pairs": [item.to_dict() for item in pairs],
                "pair_count": self.settings.comparison_pair_count,
                "sampling_schema_version": 2,
                "visual_annotation_schema_version": 1,
                "hdr": hdr,
            },
            comparison_outputs,
        )
        self._register_artifact(
            job.id,
            manifest_path,
            DatabaseArtifactKind.VIDEO_COMPARISON,
            manifest_path.name,
            mime_type="application/json",
        )
        self._register_artifact(
            job.id,
            vmaf_report,
            DatabaseArtifactKind.REPORT,
            vmaf_report.name,
            mime_type="application/json",
        )
        self._register_artifact(
            job.id,
            completeness_report,
            DatabaseArtifactKind.REPORT,
            completeness_report.name,
            mime_type="application/json",
        )
        for png in pngs:
            self._register_artifact(
                job.id,
                png,
                DatabaseArtifactKind.VIDEO_COMPARISON,
                png.name,
                mime_type="image/png",
            )

        # Scratch from the former full-title implementation must never be
        # copied into the completed comparison sidecars. New bounded probe JSON
        # is also disposable once the durable manifest/checkpoint exists.
        for scratch in (
            paths.comparison / "encoded-frames.json",
            paths.comparison / "source-frames.json",
            encoded_origin_path,
            encoded_probe,
            paths.comparison / "sampled-source-origin.json",
            paths.comparison / "sampled-source-frames.json",
        ):
            scratch.unlink(missing_ok=True)
        legacy_stage_markers = [
            paths.stages / "comparison-frame-probe.json",
            paths.stages / "comparison-source-frame-probe.json",
            paths.stages / "comparison-metrics.json",
            *paths.stages.glob("comparison-*-native.json"),
            *paths.stages.glob("comparison-*-sdr.json"),
            *paths.stages.glob("comparison-*-native-v2.json"),
            *paths.stages.glob("comparison-*-sdr-v2.json"),
            *paths.stages.glob("comparison-*-metrics-v2.json"),
        ]
        for legacy_marker in legacy_stage_markers:
            legacy_marker.unlink(missing_ok=True)
        remaining_timeout(300)
        self.queue.advance(
            job.id,
            JobState.UPLOADING,
            message=f"{len(pairs)} sampled I/P/B comparison pairs complete",
        )

    @staticmethod
    def _record_source_size(
        scan: DiscScan, selection: ParsedSelection, paths: JobPaths
    ) -> None:
        """Keep the disc size of the selected playlist for the statistics view.

        Best effort: statistics must never be able to fail a finished encode.
        """

        try:
            clips = _playlist_source_snapshot(scan, selection.playlist_id)
            atomic_write_json(
                paths.analysis / "source-size.json",
                {
                    "schema_version": 1,
                    "total_bytes": sum(int(clip["size_bytes"]) for clip in clips),
                    "clips": [
                        {
                            "name": Path(str(clip["path"])).name,
                            "size_bytes": int(clip["size_bytes"]),
                        }
                        for clip in clips
                    ],
                },
            )
        except (ReviewRequired, OSError, KeyError, TypeError, ValueError):
            LOG.warning("source size could not be recorded for statistics", exc_info=True)

    def _upload_and_finalize(self, job: Job, paths: JobPaths) -> None:
        scan, selection = self._load_prepared_scan_and_selection(job, paths)
        # An upload reset from the web UI may change the host, the image set or
        # switch the upload off without touching the hash-pinned selection.
        upload_override = read_upload_override(paths.stages)
        if upload_override:
            selection = replace(selection, **upload_override)
        recorded_mux_digest = _recorded_output_sha256(
            paths.stages / "mux.json", paths.muxed_output
        )
        try:
            current_mux_digest = sha256_file(paths.muxed_output)
        except OSError as exc:
            raise ReviewRequired(
                "final Matroska is missing after its validated mux checkpoint"
            ) from exc
        if recorded_mux_digest is None or current_mux_digest != recorded_mux_digest:
            raise ReviewRequired(
                "final Matroska changed after its validated mux checkpoint",
                details={"action": "rerun_mux_and_qc"},
            )
        mux_digest = current_mux_digest
        if selection.is_remux or selection.is_fit:
            self._remux_upload_and_finalize(job, paths, scan, selection, mux_digest)
            return
        video_manifest_path = paths.comparison / "video-comparison.json"
        try:
            video_manifest = json.loads(video_manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                "video comparison manifest is missing or invalid"
            ) from exc
        if not isinstance(
            video_manifest, Mapping
        ) or not _has_current_visual_annotations(video_manifest):
            raise ReviewRequired(
                "comparison images predate the required visible SOURCE/ENCODE, "
                "0-based frame index and I/P/B labels; reapprove the selection "
                "to rebuild the comparison before upload",
                details={
                    "action": "reapprove_selection",
                    "required_video_comparison_schema": 4,
                    "required_visual_annotation_schema": 1,
                },
            )
        pngs = _current_comparison_pngs(paths, prune=False)
        metric_sidecars = _current_video_metric_sidecars(paths)
        video_evidence_pins = _assert_stage_outputs_current(
            paths.stages / "comparison.json",
            [
                video_manifest_path,
                *metric_sidecars,
                *(path for path in pngs if path.parent == paths.comparison),
            ],
            stage_name="video comparison",
        )
        audio_evidence_pins = _assert_stage_outputs_current(
            paths.stages / "qc-audio.json",
            [
                paths.analysis / "audio-comparison.json",
                *(path for path in pngs if path.parent == paths.analysis),
            ],
            stage_name="audio QC",
        )
        validated_public_evidence = {
            **video_evidence_pins,
            **audio_evidence_pins,
        }
        if len(validated_public_evidence) != len(video_evidence_pins) + len(
            audio_evidence_pins
        ):
            raise ReviewRequired("public evidence stage outputs overlap unexpectedly")
        for public_metadata in (
            video_manifest_path,
            paths.analysis / "audio-comparison.json",
            *metric_sidecars,
        ):
            _assert_public_sidecar_safe(public_metadata)
        allowed_names = {path.name for path in pngs}
        if len(allowed_names) != len(pngs):
            raise RuntimeError("comparison image basenames are not unique")
        checkpoint, uploaded, provider_lock = self._upload_evidence_images(
            job,
            paths,
            selection,
            pngs,
            manifest_pairs=video_manifest.get("pairs"),
        )

        bbcode = paths.comparison / "comparison.bbcode"
        aither_comparison = paths.comparison / "comparison-aither.bbcode"
        pairs_document = video_manifest.get("pairs")
        published = pairs_document if isinstance(pairs_document, list) else []
        lines = [f"[b]{selection.output_name} — comparison[/b]"]
        if uploaded and provider_lock:
            lines.append(f"[i]Image host: {provider_lock}[/i]")
        if uploaded:
            # GALLERY_WIDTH-pixel pictures, each linked to its full size.
            lines.extend(gallery_bbcode(published, uploaded))
        else:
            lines.append(
                "[i]Image upload was disabled; see the lossless PNG sidecars.[/i]"
            )
        # Aither's interactive comparison as a separate, ready-to-paste
        # option, for every job (not only Aither tracker jobs).
        comparison_lines = aither_comparison_bbcode(published, uploaded)
        bbcode_outputs = [checkpoint, bbcode]
        if comparison_lines:
            atomic_write_text(aither_comparison, "\n".join(comparison_lines) + "\n")
            _assert_public_sidecar_safe(aither_comparison)
            bbcode_outputs.append(aither_comparison)
        else:
            aither_comparison.unlink(missing_ok=True)
        encode_log = paths.logs / "video-encode.log"
        lines.extend(
            tracker_bbcode(
                selection.tracker_profile.value,
                published,
                uploaded,
                encoder_log=(
                    sanitize_text(
                        encoder_summary(encode_log.read_text(encoding="utf-8", errors="replace"))
                    )
                    if selection.tracker_profile is TrackerProfile.AITHER and encode_log.is_file()
                    else ""
                ),
                codec=selection.settings.encoder.value,
            )
        )
        atomic_write_text(bbcode, "\n".join(lines) + "\n")
        _assert_public_sidecar_safe(checkpoint)
        _assert_public_sidecar_safe(bbcode)
        upload_marker = paths.stages / "upload.json"
        _write_stage(
            upload_marker,
            {
                "upload_images": selection.upload_images,
                "provider": provider_lock,
                "images": {path.name: sha256_file(path) for path in pngs},
            },
            bbcode_outputs,
        )
        self._stop_at_operator_boundary(job.id)

        # Upload adapters are external code and may run for minutes.  Re-open
        # the trust boundary afterwards so a concurrent/local mutation cannot
        # turn previously validated evidence (or the final MKV) into the
        # public release between upload and staging.
        if (
            _recorded_output_sha256(paths.stages / "mux.json", paths.muxed_output)
            != mux_digest
            or sha256_file(paths.muxed_output) != mux_digest
        ):
            raise ReviewRequired(
                "final Matroska changed during public evidence upload",
                details={"action": "rerun_mux_and_qc"},
            )
        pngs = _current_comparison_pngs(paths, prune=False)
        metric_sidecars = _current_video_metric_sidecars(paths)
        revalidated_video_pins = _assert_stage_outputs_current(
            paths.stages / "comparison.json",
            [
                video_manifest_path,
                *metric_sidecars,
                *(path for path in pngs if path.parent == paths.comparison),
            ],
            stage_name="video comparison",
        )
        revalidated_audio_pins = _assert_stage_outputs_current(
            paths.stages / "qc-audio.json",
            [
                paths.analysis / "audio-comparison.json",
                *(path for path in pngs if path.parent == paths.analysis),
            ],
            stage_name="audio QC",
        )
        revalidated_public_evidence = {
            **revalidated_video_pins,
            **revalidated_audio_pins,
        }
        if revalidated_public_evidence != validated_public_evidence:
            raise ReviewRequired(
                "public evidence checkpoint set changed during image upload",
                details={"action": "rerun_qc"},
            )
        for public_metadata in (
            video_manifest_path,
            paths.analysis / "audio-comparison.json",
            *metric_sidecars,
            *bbcode_outputs,
        ):
            _assert_public_sidecar_safe(public_metadata)
        upload_evidence_pins = _assert_stage_outputs_current(
            upload_marker,
            bbcode_outputs,
            stage_name="upload checkpoint",
        )
        pinned_public_files = {
            **validated_public_evidence,
            **upload_evidence_pins,
        }
        if len(pinned_public_files) != len(validated_public_evidence) + len(
            upload_evidence_pins
        ):
            raise ReviewRequired("public upload evidence overlaps producer outputs")

        self._publish_release(
            job,
            paths,
            scan,
            selection,
            mux_digest=mux_digest,
            checkpoint=checkpoint,
            evidence_inputs={
                "comparison_sha256": sha256_file(
                    paths.comparison / "video-comparison.json"
                ),
                "audio_sha256": sha256_file(paths.analysis / "audio-comparison.json"),
            },
            public_analysis_files=(
                paths.analysis / "audio-comparison.json",
                *(path for path in pngs if path.parent == paths.analysis),
            ),
            public_comparison_files=(
                video_manifest_path,
                *bbcode_outputs,
                *metric_sidecars,
                *(path for path in pngs if path.parent == paths.comparison),
            ),
            pinned_public_files=pinned_public_files,
            bbcode_outputs=bbcode_outputs,
            completion_message="encode, QC and comparison completed",
        )

    # --- remux: Aither's REMUX guide, nothing re-encoded ----------------------

    def _process_remux_stage(self, job: Job, paths: JobPaths) -> None:
        """One remux stage: READY prepares, ENCODING demuxes with eac3to,
        MUXING muxes, QC proves the output untouched, COMPARISON takes the
        screenshots.  UPLOADING is shared with encodes."""

        if job.state is JobState.READY:
            self._remux_prepare(job, paths)
        elif job.state is JobState.ENCODING:
            # The serial claim moves a job from READY straight here.
            if not self._remux_preparation_is_current(job, paths):
                self._remux_prepare(job, paths, advance=False)
            with self._step(paths, "eac3to", ("Bontás eac3to-val", "Demuxing with eac3to")):
                self._remux_demux(job, paths)
        elif job.state is JobState.MUXING:
            with self._step(paths, "mux", ("Muxolás", "Muxing")):
                self._remux_mux(job, paths)
        elif job.state is JobState.QC:
            with self._step(paths, "qc", ("Minőségellenőrzés (QC)", "Quality check (QC)")):
                self._remux_qc(job, paths)
        elif job.state is JobState.COMPARISON:
            with self._step(paths, "screenshots", ("Képernyőképek", "Screenshots")):
                self._remux_screenshots(job, paths)

    # -- external sources ------------------------------------------------------------------

    def _external_root(self, paths: JobPaths) -> Path:
        return _ensure_contained_directory(
            paths.work / "external", root=paths.work, description="external source directory"
        )

    def _prepare_external_sources(
        self,
        paths: JobPaths,
        selection: ParsedSelection,
        playlist: PlaylistCandidate,
        reference_sha256: str,
    ) -> None:
        """Fit each external source to the title; stop until the operator approves the fit.

        Nothing here touches the title's own tracks: they are muxed and checked
        as if no external source existed, and these join them afterwards.
        """

        if not selection.external_sources:
            return
        support = external_source.external_support()
        if not support["available"]:
            raise ReviewRequired(
                "this host cannot fit external sources: " + ", ".join(support["missing"]),
                details={"code": "external_source_unavailable", **support},
            )
        video = playlist.video_streams[0].video
        target_fps = external_source.exact_fps(getattr(video, "frame_rate", None))
        if target_fps is None:
            raise ReviewRequired(
                "the title's frame rate is unknown, so nothing can be fitted to it",
                details={"code": "external_source_invalid"},
            )
        root = self._external_root(paths)
        title_signature = root / "title.gray"
        marker = paths.stages / "external-title-signature.json"
        inputs = {"schema_version": 1, "reference_sha256": reference_sha256}
        if not _valid_stage(marker, inputs, [title_signature]):
            with self._step(paths, "external-title", ("A cím képének lenyomata", "Fingerprinting the title's picture")):
                self._runner(paths).run(
                    external_source.signature_command(["-i", str(paths.reference)], title_signature),
                    cwd=root,
                    stderr_path=paths.logs / "external-title-signature.log",
                )
            _write_stage(marker, inputs, [title_signature])
        # The title's own audio, by scan id: (ordinal in the reference, codec,
        # sample rate), for a fill of the parts an external source lacks.
        title_audio = {
            stream.id: (ordinal, stream.codec, stream.sample_rate)
            for ordinal, stream in enumerate(playlist.audio_streams)
        }
        reviews = [
            self._fit_external_source(
                paths, source, target_fps, title_signature, reference_sha256, title_audio
            )
            for source in selection.external_sources
        ]
        pending = [
            review
            for review, source in zip(reviews, selection.external_sources)
            if review["map_sha256"] != source.approved_map_sha256
        ]
        if pending:
            raise ReviewRequired(
                "the external source fit waits for the operator's approval",
                details={
                    "code": "external_source_review",
                    "sources": [item["id"] for item in pending],
                },
            )

    def _external_input(
        self, paths: JobPaths, source: external_spec.ExternalSource, directory: Path
    ) -> tuple[external_source.SourceInfo, list[str], dict[str, Any]]:
        """The source's FFmpeg input; a DVD image is unpacked, a DVD folder linked."""

        try:
            resolved = self.settings.authorize_source(source.path)
            info = external_source.probe_source(resolved)
        except (ConfigurationError, external_source.ExternalSourceError, OSError) as exc:
            raise ReviewRequired(
                f"external source cannot be read: {exc}",
                details={"code": "external_source_invalid", "source": source.id},
            ) from exc
        location = Path(info.path)
        identity: dict[str, Any] = {
            "path": str(location),
            "size": location.stat().st_size if location.is_file() else None,
            "mtime_ns": location.stat().st_mtime_ns,
            "kind": info.kind,
            "title_set": info.title_set,
        }
        if info.kind == external_source.KIND_FILE:
            return info, external_source.input_arguments(info.kind, location), identity
        dvd = _ensure_contained_directory(
            directory / "dvd", root=directory, description="external DVD directory"
        )
        assert info.title_set is not None
        if info.kind == external_source.KIND_DVD_FOLDER:
            originals = external_source.folder_vobs(location, info.title_set)
            identity["vobs"] = [[item.name, item.stat().st_size] for item in originals]
            links = []
            for original in originals:
                link = dvd / original.name.upper()
                link.unlink(missing_ok=True)
                link.symlink_to(original)
                links.append(link)
            return info, external_source.input_arguments(info.kind, location, links), identity
        marker = paths.stages / f"external-{source.id}-unpack.json"
        listing = directory / "image-listing.txt"
        self._runner(paths).run(
            external_source.image_list_command(location),
            cwd=directory,
            stdout_path=listing,
            stderr_path=paths.logs / f"external-{source.id}-image.log",
            timeout=600,
        )
        names = external_source.image_vob_names(
            listing.read_text(encoding="utf-8", errors="replace"), info.title_set
        )
        if not names:
            raise ReviewRequired(
                "the DVD image holds no video of the main title",
                details={"code": "external_source_invalid", "source": source.id},
            )
        unpacked = [dvd / name.rsplit("/", 1)[-1].upper() for name in names]
        inputs = {"schema_version": 1, **identity, "names": names}
        if not _valid_stage(marker, inputs, unpacked):
            with self._step(paths, "external-unpack", ("A DVD-képfájl kibontása", "Unpacking the DVD image")):
                self._runner(paths).run(
                    external_source.image_extract_command(location, names, dvd),
                    cwd=directory,
                    stdout_path=paths.logs / f"external-{source.id}-unpack.log",
                    stderr_path=paths.logs / f"external-{source.id}-unpack.stderr.log",
                )
                for name in dvd.iterdir():
                    if name.name != name.name.upper():
                        name.rename(name.with_name(name.name.upper()))
            _write_stage(marker, inputs, unpacked)
        return info, external_source.input_arguments(info.kind, location, unpacked), identity

    def _external_first_time(
        self, paths: JobPaths, input_args: Sequence[str], specifier: str, output: Path
    ) -> float:
        self._runner(paths).run(
            external_source.first_time_command(input_args, specifier),
            cwd=output.parent,
            stdout_path=output,
            stderr_path=output.with_suffix(".log"),
            timeout=600,
        )
        value = external_source.parse_first_time(output.read_text(encoding="utf-8"))
        if value is None:
            raise ReviewRequired(
                f"the start time of external stream {specifier} is unknown",
                details={"code": "external_source_invalid"},
            )
        return value

    def _fit_external_source(
        self,
        paths: JobPaths,
        source: external_spec.ExternalSource,
        target_fps: Fraction,
        title_signature: Path,
        reference_sha256: str,
        title_audio: Mapping[str, tuple[int, str, int | None]] | None = None,
    ) -> dict[str, Any]:
        directory = _ensure_contained_directory(
            self._external_root(paths) / source.id,
            root=self._external_root(paths),
            description="external source directory",
        )
        info, input_args, identity = self._external_input(paths, source, directory)
        donor_fps = Fraction(info.fps)
        signature = directory / "source.gray"
        marker = paths.stages / f"external-{source.id}-signature.json"
        inputs = {"schema_version": 1, **identity}
        if not _valid_stage(marker, inputs, [signature]):
            with self._step(paths, "external-source", ("A külső forrás képének lenyomata", "Fingerprinting the external picture")):
                self._runner(paths).run(
                    external_source.signature_command(input_args, signature),
                    cwd=directory,
                    stderr_path=paths.logs / f"external-{source.id}-signature.log",
                )
            _write_stage(marker, inputs, [signature])
        map_path = directory / "map.json"
        marker = paths.stages / f"external-{source.id}-map.json"
        inputs = {
            "schema_version": 1,
            "reference_sha256": reference_sha256,
            "source": identity,
            "signature_sha256": _recorded_output_sha256(
                paths.stages / f"external-{source.id}-signature.json", signature
            ),
            "target_fps": str(target_fps),
            "donor_fps": str(donor_fps),
        }
        if not _valid_stage(marker, inputs, [map_path]):
            with self._step(paths, "external-map", ("Képkockák megfeleltetése", "Matching the frames")):
                try:
                    self._runner(paths).run(
                        [
                            sys.executable, "-m", "bdencode.external", "map",
                            str(title_signature), str(signature),
                            str(target_fps), str(donor_fps), str(map_path),
                        ],
                        cwd=directory,
                        stderr_path=paths.logs / f"external-{source.id}-map.log",
                    )
                except ProcessFailure as exc:
                    raise ReviewRequired(
                        "the two pictures could not be matched",
                        details={"code": "external_source_no_match", "source": source.id},
                    ) from exc
            _write_stage(marker, inputs, [map_path])
        document = json.loads(map_path.read_text(encoding="utf-8"))
        total = int(document["target_frames"])
        if not total or int(document["matched_frames"]) < total / 2 or float(document["similarity_median"]) < 0.5:
            raise ReviewRequired(
                "the external picture does not match this title",
                details={
                    "code": "external_source_no_match",
                    "source": source.id,
                    "matched_frames": document["matched_frames"],
                    "target_frames": total,
                    "similarity_median": document["similarity_median"],
                },
            )
        map_sha256 = sha256_file(map_path)
        video_start = self._external_first_time(
            paths, input_args, "v:0", directory / "video-start.json"
        )
        rendered = [
            self._render_external_track(
                paths, source, index, track, info, input_args, directory,
                document, map_sha256, target_fps, donor_fps, video_start,
                title_audio or {},
            )
            for index, track in enumerate(source.tracks)
        ]
        subtitles = [
            self._retime_external_subtitle(
                paths, source, index, subtitle, directory, document, map_sha256, target_fps, donor_fps
            )
            for index, subtitle in enumerate(source.subtitles)
        ]
        review = {
            "schema_version": 1,
            "id": source.id,
            "path": info.path,
            "kind": info.kind,
            "fps": info.fps,
            "target_fps": str(target_fps),
            "map_sha256": map_sha256,
            "map": document,
            "tracks": rendered,
            "subtitles": subtitles,
        }
        atomic_write_json(directory / "review.json", review)
        return review

    def _render_external_track(
        self,
        paths: JobPaths,
        source: external_spec.ExternalSource,
        index: int,
        track: external_spec.ExternalTrack,
        info: external_source.SourceInfo,
        input_args: Sequence[str],
        directory: Path,
        document: Mapping[str, Any],
        map_sha256: str,
        target_fps: Fraction,
        donor_fps: Fraction,
        video_start: float,
        title_audio: Mapping[str, tuple[int, str, int | None]] | None = None,
    ) -> dict[str, Any]:
        details = next((item for item in info.tracks if item.stream == track.stream), None)
        if details is None:
            raise ReviewRequired(
                f"external track {track.stream} does not exist in {source.id}",
                details={"code": "external_source_invalid", "source": source.id},
            )
        stem = f"track-{index:02d}"
        start_path = directory / f"{stem}-start.json"
        audio_start = self._external_first_time(paths, input_args, track.stream, start_path)
        ratio = external_render.speed_ratio(document["mode"], donor_fps, target_fps)
        segments = document["segments"]
        per_frame = external_render.samples_per_frame(target_fps)
        total_samples = external_render.sample_at(int(document["target_frames"]), per_frame)
        audio_offset_samples = int(
            round((audio_start - video_start) * float(ratio) * external_render.SAMPLE_RATE)
        )
        sample_rate = details.sample_rate or external_render.SAMPLE_RATE
        stretched = directory / f"{stem}.stretched.f32"
        stretch_argv = external_render.stretch_command(
            input_args, track.stream, details.codec, details.channels, ratio, track.pitch, sample_rate, stretched
        )
        copy = external_render.copy_is_possible(segments, ratio)
        sync_ms = 0
        if copy:
            first = segments[0]
            sync_ms = int(
                round(((audio_start - video_start) - int(first["offset"]) / float(target_fps)) * 1000)
            )
            copy = sync_ms <= 200
        fill_argv: list[str] | None = None
        fill_path = directory / f"{stem}.fill.f32"
        fill_offset_samples = 0
        if track.fill_from is not None:
            found = (title_audio or {}).get(track.fill_from)
            if found is None:
                raise ReviewRequired(
                    f"the title has no audio stream {track.fill_from} to fill from",
                    details={"code": "external_source_invalid", "source": source.id},
                )
            fill_ordinal, fill_codec, fill_rate = found
            reference_input = ["-i", str(paths.reference)]
            fill_argv = external_render.stretch_command(
                reference_input, f"a:{fill_ordinal}", fill_codec, details.channels,
                Fraction(1), external_render.PITCH_RESTORE,
                fill_rate or external_render.SAMPLE_RATE, fill_path,
            )
            title_video_start = self._external_first_time(
                paths, reference_input, "v:0", directory / "title-video-start.json"
            )
            fill_start = self._external_first_time(
                paths, reference_input, f"a:{fill_ordinal}", directory / f"{stem}-fill-start.json"
            )
            fill_offset_samples = int(
                round((fill_start - title_video_start) * external_render.SAMPLE_RATE)
            )
            # A copy keeps the source as it is, gaps and all.
            if int(document.get("unmatched_frames") or 0) > 0:
                copy = False
        dialnorm = None
        if not copy and details.codec in {"ac3", "eac3"}:
            sample = directory / f"{stem}.first.ac3"
            self._runner(paths).run(
                [
                    "ffmpeg", "-hide_banner", "-nostdin", "-v", "error", *input_args,
                    "-map", f"0:{track.stream}", "-c:a", "copy", "-t", "2",
                    "-f", "ac3" if details.codec == "ac3" else "eac3", "-y", str(sample),
                ],
                cwd=directory,
                stderr_path=paths.logs / f"external-{source.id}-{stem}-probe.log",
            )
            completed = subprocess.run(
                external_render.dialnorm_command(sample),
                capture_output=True, text=True, timeout=60, check=False,
            )
            dialnorm = external_render.parse_dialnorm(completed.stdout)
        bit_rate = details.bit_rate
        if bit_rate is None and details.codec in {"ac3", "eac3"}:
            bit_rate = self._external_bit_rate(input_args, track.stream)
        if copy:
            output = directory / (stem + external_render.sidecar_suffix(details.codec))
            encoding = None
        else:
            try:
                encoding = external_render.choose_encoding(details.codec, details.channels, bit_rate, dialnorm)
            except external_render.RenderError as exc:
                raise ReviewRequired(
                    str(exc), details={"code": "external_source_invalid", "source": source.id}
                ) from exc
            output = directory / f"{stem}.ac3"
        spec = {
            "segments": segments,
            "target_fps": str(target_fps),
            "audio_offset_samples": audio_offset_samples,
            "stretched": str(stretched),
            "channels": details.channels,
            "expected_stretched_samples": None,
            "total_samples": total_samples,
            "output": str(directory / f"{stem}.final.f32"),
            "priming_samples": encoding.priming_samples if encoding else 0,
            "correct_length": track.pitch == external_render.PITCH_KEEP and ratio != 1,
            "fill": (
                {"path": str(fill_path), "offset_samples": fill_offset_samples}
                if fill_argv is not None
                else None
            ),
        }
        inputs = {
            "schema_version": 1,
            "map_sha256": map_sha256,
            "stream": track.stream,
            "pitch": track.pitch,
            "copy": copy,
            "encoding": asdict(encoding) if encoding else None,
            "stretch": [str(item) for item in stretch_argv],
        }
        if fill_argv is not None:
            # Absent without a fill, so an unfilled fit keeps its checkpoint.
            inputs["fill"] = {
                "from": track.fill_from,
                "decode": [str(item) for item in fill_argv],
                "offset_samples": fill_offset_samples,
            }
        marker = paths.stages / f"external-{source.id}-{stem}.json"
        report_path = directory / f"{stem}.json"
        if not _valid_stage(marker, inputs, [output, report_path]):
            label = (f"Hangsáv illesztése: {track.language}", f"Fitting the track: {track.language}")
            with self._step(paths, f"external-{stem}", label):
                self._runner(paths).run(
                    stretch_argv,
                    cwd=directory,
                    stderr_path=paths.logs / f"external-{source.id}-{stem}-stretch.log",
                )
                actual = stretched.stat().st_size // (4 * details.channels)
                silence: dict[str, Any] = {}
                scale = 1.0
                if copy:
                    self._runner(paths).run(
                        external_render.stream_copy_command(input_args, track.stream, output),
                        cwd=directory,
                        stderr_path=paths.logs / f"external-{source.id}-{stem}-copy.log",
                    )
                else:
                    assert encoding is not None
                    spec["expected_stretched_samples"] = actual
                    if spec["correct_length"]:
                        # Tempo-only stretching misses the length by a tiny
                        # factor; the exact resampling shows the right one.
                        exact = directory / f"{stem}.exact.f32"
                        self._runner(paths).run(
                            external_render.stretch_command(
                                input_args, track.stream, details.codec, details.channels,
                                ratio, external_render.PITCH_RESTORE, sample_rate, exact,
                            ),
                            cwd=directory,
                            stderr_path=paths.logs / f"external-{source.id}-{stem}-exact.log",
                        )
                        spec["expected_stretched_samples"] = exact.stat().st_size // (4 * details.channels)
                        exact.unlink(missing_ok=True)
                    if fill_argv is not None:
                        self._runner(paths).run(
                            fill_argv,
                            cwd=directory,
                            stderr_path=paths.logs / f"external-{source.id}-{stem}-fill.log",
                        )
                    spec_path = directory / f"{stem}.spec.json"
                    atomic_write_json(spec_path, spec)
                    assembled = directory / f"{stem}.assemble.json"
                    try:
                        self._runner(paths).run(
                            [sys.executable, "-m", "bdencode.external", "assemble", str(spec_path)],
                            cwd=directory,
                            stdout_path=assembled,
                            stderr_path=paths.logs / f"external-{source.id}-{stem}-assemble.log",
                        )
                    finally:
                        fill_path.unlink(missing_ok=True)
                    silence = json.loads(assembled.read_text(encoding="utf-8"))
                    scale = float(silence.get("scale", 1.0))
                    self._runner(paths).run(
                        external_render.encode_command(
                            Path(spec["output"]), details.channels, encoding, output
                        ),
                        cwd=directory,
                        stderr_path=paths.logs / f"external-{source.id}-{stem}-encode.log",
                    )
                    Path(spec["output"]).unlink(missing_ok=True)
                atomic_write_json(
                    report_path,
                    {
                        "schema_version": 1,
                        "stream": track.stream,
                        "language": track.language,
                        "pitch": track.pitch,
                        "codec": details.codec,
                        "channels": details.channels,
                        "copy": copy,
                        "sync_ms": sync_ms,
                        "encoding": asdict(encoding) if encoding else None,
                        "audio_offset_samples": audio_offset_samples,
                        "scale": scale,
                        "stretched_samples": actual,
                        "silent_samples": silence.get("silent_samples", 0),
                        "fill_from": track.fill_from,
                        "filled_samples": silence.get("filled_samples", 0),
                        "fill_gaps": silence.get("fill_gaps", []),
                        "file": output.name,
                    },
                )
            _write_stage(marker, inputs, [output, report_path])
        return json.loads(report_path.read_text(encoding="utf-8"))

    def _external_bit_rate(self, input_args: Sequence[str], specifier: str) -> int | None:
        completed = subprocess.run(
            [
                "ffprobe", "-hide_banner", "-v", "error", *input_args,
                "-select_streams", specifier,
                "-show_entries", "stream=bit_rate", "-of", "csv=p=0",
            ],
            capture_output=True, text=True, timeout=600, check=False,
        )
        value = (completed.stdout or "").strip().splitlines()
        return int(value[0]) if value and value[0].strip().isdigit() else None

    def _retime_external_subtitle(
        self,
        paths: JobPaths,
        source: external_spec.ExternalSource,
        index: int,
        subtitle: external_spec.ExternalSubtitle,
        directory: Path,
        document: Mapping[str, Any],
        map_sha256: str,
        target_fps: Fraction,
        donor_fps: Fraction,
    ) -> dict[str, Any]:
        try:
            original = self.settings.authorize_source(subtitle.path)
            raw = original.read_bytes()
            cues = external_subtitles.parse_srt(external_subtitles.decode_text(raw))
        except (ConfigurationError, external_subtitles.SubtitleError, OSError) as exc:
            raise ReviewRequired(
                f"external subtitle cannot be read: {exc}",
                details={"code": "external_source_invalid", "source": source.id},
            ) from exc
        grid_fps = donor_fps if document["mode"] == "frame-locked" else target_fps
        moved, counts = external_subtitles.retime(
            cues, document["segments"], target_fps=target_fps, donor_grid_fps=grid_fps
        )
        output = directory / f"subtitle-{index:02d}.srt"
        atomic_write_text(output, external_subtitles.render_srt(moved))
        return {
            "file": output.name,
            "language": subtitle.language,
            "source_sha256": hashlib.sha256(raw).hexdigest(),
            "map_sha256": map_sha256,
            **counts,
        }

    def _restore_base_mux(self, paths: JobPaths) -> None:
        """Back to the title's own mux, so that its stages see what they checked."""

        base = paths.work / "output.base.mkv"
        saved = paths.stages / "mux.base.json"
        if base.is_file() and saved.is_file():
            paths.muxed_output.unlink(missing_ok=True)
            os.link(base, paths.muxed_output)
            shutil.copyfile(saved, paths.stages / "mux.json")

    def _merge_external_tracks(
        self, job: Job, paths: JobPaths, selection: ParsedSelection
    ) -> None:
        """Join the fitted tracks to the checked mux and prove the result.

        The title's streams must come through byte for byte; each fitted track
        must lie where the map puts it.
        """

        if not selection.external_sources:
            return
        with self._step(paths, "external-merge", ("Külső sávok muxolása", "Muxing the external tracks")):
            base = paths.work / "output.base.mkv"
            saved = paths.stages / "mux.base.json"
            if not base.is_file():
                os.link(paths.muxed_output, base)
                shutil.copyfile(paths.stages / "mux.json", saved)
            root = self._external_root(paths)
            audio: list[dict[str, Any]] = []
            subtitles: list[dict[str, Any]] = []
            for source in selection.external_sources:
                directory = root / source.id
                review = json.loads((directory / "review.json").read_text(encoding="utf-8"))
                for track, report in zip(source.tracks, review["tracks"], strict=True):
                    audio.append(
                        {
                            "source": source.id,
                            "external_source": source,
                            "directory": directory,
                            "review": review,
                            "track": track,
                            "report": report,
                            "path": directory / report["file"],
                        }
                    )
                for subtitle, report in zip(source.subtitles, review["subtitles"], strict=True):
                    subtitles.append(
                        {"subtitle": subtitle, "path": directory / report["file"]}
                    )
            identified = subprocess.run(
                ["mkvmerge", "--identify", "--identification-format", "json", str(base)],
                capture_output=True, text=True, timeout=600, check=False,
            )
            base_tracks = (json.loads(identified.stdout or "{}")).get("tracks") or []
            video_start = self._external_video_start(base)
            command = external_merge_command(
                paths.work / "output.merged.mkv",
                base,
                base_tracks,
                audio,
                subtitles,
                title=selection.output_name,
                video_start_seconds=video_start,
            )
            merged = paths.work / "output.merged.mkv"
            merged.unlink(missing_ok=True)
            self._runner(paths).run(
                command,
                cwd=paths.work,
                stdout_path=paths.logs / "external-merge.log",
                stderr_path=paths.logs / "external-merge.stderr.log",
                ok_returncodes=(0, 1),
            )
            if not merged.is_file():
                raise RuntimeError("mkvmerge did not write the merged file")
            self._verify_external_merge(job, paths, base, merged, base_tracks, audio, video_start)
            paths.muxed_output.unlink(missing_ok=True)
            os.replace(merged, paths.muxed_output)
            _write_stage(
                paths.stages / "mux.json",
                {"schema_version": 1, "mode": "external-merge", "base_sha256": sha256_file(base)},
                [paths.muxed_output],
            )
            self._refresh_final_reports(job, paths, selection)
            for item in audio:
                (item["directory"] / item["path"].name).with_suffix(".stretched.f32").unlink(missing_ok=True)

    def _external_video_start(self, path: Path) -> float:
        completed = subprocess.run(
            external_source.first_time_command(["-i", str(path)], "v:0"),
            capture_output=True, text=True, timeout=600, check=False,
        )
        value = external_source.parse_first_time(completed.stdout)
        return value if value is not None else 0.0

    def _verify_external_merge(
        self,
        job: Job,
        paths: JobPaths,
        base: Path,
        merged: Path,
        base_tracks: Sequence[Mapping[str, Any]],
        audio: Sequence[Mapping[str, Any]],
        video_start: float,
    ) -> None:
        final_tracks = (
            json.loads(
                subprocess.run(
                    ["mkvmerge", "--identify", "--identification-format", "json", str(merged)],
                    capture_output=True, text=True, timeout=600, check=False,
                ).stdout
                or "{}"
            ).get("tracks")
            or []
        )
        order = external_final_audio_order(base_tracks, audio)
        hashes: dict[str, list[str]] = {}
        # Base streams in the merged file, by their place in each file.
        final_audio = [item for item in final_tracks if item.get("type") == "audio"]
        if len(final_audio) != len(order):
            raise ReviewRequired(
                "the merged file does not hold the expected audio tracks",
                details={"code": "external_merge_failed"},
            )
        base_audio_count = sum(1 for item in base_tracks if item.get("type") == "audio")
        base_subtitle_count = sum(1 for item in base_tracks if item.get("type") == "subtitles")
        final_positions = {
            entry: position for position, entry in enumerate(order) if isinstance(entry, int)
        }
        report_path = paths.analysis / "external-merge-streams.json"
        maps = {
            "base": [
                "0:v:0",
                *(f"0:a:{index}" for index in range(base_audio_count)),
                *(f"0:s:{index}" for index in range(base_subtitle_count)),
            ],
            "final": [
                "0:v:0",
                *(f"0:a:{final_positions[index]}" for index in range(base_audio_count)),
                *(f"0:s:{index}" for index in range(base_subtitle_count)),
            ],
        }
        for label, path in (("base", base), ("final", merged)):
            output = paths.analysis / f"external-merge-{label}.streamhash"
            self._runner(paths).run(
                [
                    "ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-i", str(path),
                    *[value for item in maps[label] for value in ("-map", item)],
                    "-c", "copy", "-f", "streamhash", "-hash", "sha256", "-y", str(output),
                ],
                cwd=paths.work,
                stderr_path=paths.logs / f"external-merge-{label}-hash.log",
            )
            hashes[label] = output.read_text(encoding="utf-8").split()
        verdicts: list[dict[str, Any]] = []
        if hashes["base"] != hashes["final"]:
            raise ReviewRequired(
                "the merge changed one of the title's own streams",
                details={"code": "external_merge_failed"},
            )
        for position, entry in enumerate(order):
            if isinstance(entry, int):
                continue
            verdicts.append(
                self._verify_external_track(paths, merged, position, audio[entry[1]], video_start)
            )
        atomic_write_json(
            report_path, {"schema_version": 1, "streams_unchanged": True, "tracks": verdicts}
        )
        self._register_artifact(
            job.id,
            report_path,
            DatabaseArtifactKind.REPORT,
            report_path.name,
            mime_type="application/json",
        )
        failed = [item for item in verdicts if item["status"] != "passed"]
        if failed:
            raise ReviewRequired(
                "an external track is not where the map puts it",
                details={
                    "code": "external_merge_failed",
                    "tracks": [
                        {"source": item["source"], "stream": item["stream"], "status": item["status"]}
                        for item in failed
                    ],
                },
            )

    def _verify_external_track(
        self,
        paths: JobPaths,
        merged: Path,
        ordinal: int,
        item: Mapping[str, Any],
        video_start: float,
    ) -> dict[str, Any]:
        directory: Path = item["directory"]
        review = item["review"]
        report = item["report"]
        track = item["track"]
        stem = Path(report["file"]).stem
        stretched = directory / f"{stem}.stretched.f32"
        if not stretched.is_file():
            self._stretch_external_again(paths, item, stretched)
        result = directory / f"{stem}.verify.json"
        spec_path = directory / f"{stem}.verify-spec.json"
        atomic_write_json(
            spec_path,
            {
                "segments": review["map"]["segments"],
                "target_fps": review["target_fps"],
                "channels": report["channels"],
                "stretched": str(stretched),
                "final": str(merged),
                "work": str(directory),
                "ordinal": ordinal,
                "video_start_seconds": video_start,
                "audio_offset_samples": report["audio_offset_samples"],
                "scale": report["scale"],
                "report": str(result),
            },
        )
        self._runner(paths).run(
            [sys.executable, "-m", "bdencode.external", "verify", str(spec_path)],
            cwd=directory,
            stderr_path=paths.logs / f"external-{item['source']}-{stem}-verify.log",
        )
        verdict = json.loads(result.read_text(encoding="utf-8"))
        return {"source": item["source"], "stream": track.stream, **verdict}

    def _stretch_external_again(
        self, paths: JobPaths, item: Mapping[str, Any], stretched: Path
    ) -> None:
        """A finished merge deleted these samples; a repeated one needs them for its proof."""

        directory: Path = item["directory"]
        review = item["review"]
        track = item["track"]
        source = item["external_source"]
        info, input_args, _identity = self._external_input(paths, source, directory)
        details = next((entry for entry in info.tracks if entry.stream == track.stream), None)
        if details is None:
            raise ReviewRequired(
                f"external track {track.stream} does not exist in {source.id}",
                details={"code": "external_merge_failed", "source": source.id},
            )
        ratio = external_render.speed_ratio(
            review["map"]["mode"], Fraction(review["fps"]), Fraction(review["target_fps"])
        )
        self._runner(paths).run(
            external_render.stretch_command(
                input_args,
                track.stream,
                details.codec,
                details.channels,
                ratio,
                track.pitch,
                details.sample_rate or external_render.SAMPLE_RATE,
                stretched,
            ),
            cwd=directory,
            stderr_path=paths.logs / f"external-{source.id}-{stretched.stem}-again.log",
        )

    def _refresh_final_reports(
        self, job: Job, paths: JobPaths, selection: ParsedSelection
    ) -> None:
        """The reports a release uses must describe the file with the fitted tracks."""

        output = paths.muxed_output
        if selection.is_remux or selection.is_fit:
            raw = self._remux_root(paths) / "external-mediainfo.txt"
            self._runner(paths).run(
                ["mediainfo", output.name],
                cwd=output.parent,
                stdout_path=raw,
                stderr_path=paths.logs / "external-mediainfo.log",
                timeout=600,
            )
            mediainfo = paths.analysis / "mediainfo.txt"
            atomic_write_text(
                mediainfo,
                raw.read_text(encoding="utf-8", errors="replace").replace(
                    output.name, f"{selection.output_name}.mkv"
                ),
            )
            identify = paths.analysis / "mkvmerge-identify.json"
            self._runner(paths).run(
                ["mkvmerge", "--identify", "--identification-format", "json", str(output)],
                cwd=paths.work,
                stdout_path=identify,
                stderr_path=paths.logs / "external-identify.log",
                ok_returncodes=(0, 1),
            )
            self._register_artifact(
                job.id, mediainfo, DatabaseArtifactKind.MEDIAINFO, mediainfo.name, mime_type="text/plain"
            )
            self._register_artifact(
                job.id, identify, DatabaseArtifactKind.MKVINFO, identify.name, mime_type="application/json"
            )
            return
        report_root = paths.analysis / "container"
        for command, report in inspection_commands(output, report_root):
            if report.name not in {"mediainfo.txt", "mkvmerge-identify.json", "mkvinfo.txt", "ffprobe-streams.json"}:
                continue
            self._runner(paths).run(
                command,
                cwd=paths.work,
                stdout_path=report,
                stderr_path=report.with_suffix(report.suffix + ".stderr"),
                ok_returncodes=(0, 1) if command[0] == "mkvmerge" else (0,),
            )
            kind = (
                DatabaseArtifactKind.MEDIAINFO
                if report.name == "mediainfo.txt"
                else DatabaseArtifactKind.MKVINFO
                if report.name in {"mkvinfo.txt", "mkvmerge-identify.json"}
                else DatabaseArtifactKind.REPORT
            )
            self._register_artifact(
                job.id,
                report,
                kind,
                report.name,
                mime_type="application/json" if report.suffix == ".json" else "text/plain",
            )

    # -- fitting to a finished MKV --------------------------------------------------------

    def _process_fit_stage(self, job: Job, paths: JobPaths) -> None:
        """READY fits the tracks, MUXING selects the file's own tracks, QC joins and
        proves them, COMPARISON takes the screenshots.  UPLOADING is shared."""

        if job.state is JobState.READY:
            self._fit_prepare(job, paths)
        elif job.state is JobState.ENCODING:
            # The serial claim moves a job from READY straight here.
            if not self._fit_preparation_is_current(job, paths):
                self._fit_prepare(job, paths, advance=False)
            self.queue.advance(job.id, JobState.MUXING, message="nothing to encode: the tracks are fitted")
        elif job.state is JobState.MUXING:
            with self._step(paths, "mux", ("A saját sávok kiválasztása", "Selecting the file's own tracks")):
                self._fit_mux(job, paths)
        elif job.state is JobState.QC:
            self._fit_qc(job, paths)
        elif job.state is JobState.COMPARISON:
            with self._step(paths, "screenshots", ("Képernyőképek", "Screenshots")):
                self._remux_screenshots(job, paths)

    def _fit_preparation_is_current(self, job: Job, paths: JobPaths) -> bool:
        try:
            scan, selection = self._load_scan_and_selection(job, paths)
        except (OSError, TypeError, ValueError, KeyError):
            return False
        return self._external_fit_is_current(paths, selection) and _valid_stage(
            paths.stages / "pipeline-prepare.json",
            self._preparation_inputs(job, scan),
            [paths.reference],
        )

    def _fit_prepare(self, job: Job, paths: JobPaths, *, advance: bool = True) -> None:
        scan, selection = self._load_scan_and_selection(job, paths)
        playlist = scan.playlist(selection.playlist_id)
        reference_sha256 = self._prepare_reference(job, paths, scan, selection, playlist)
        self._prepare_external_sources(paths, selection, playlist, reference_sha256)
        _write_stage(
            paths.stages / "pipeline-prepare.json",
            self._preparation_inputs(job, scan),
            [paths.reference],
        )
        if advance:
            self.queue.advance(job.id, JobState.ENCODING, message="external sources fitted")

    def _stream_hashes(
        self, paths: JobPaths, path: Path, maps: Sequence[str], label: str
    ) -> list[str]:
        """The hash of each mapped stream's packets, in order; timing does not count."""

        output = paths.analysis / f"{label}.streamhash"
        self._runner(paths).run(
            [
                "ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-i", str(path),
                *[value for item in maps for value in ("-map", item)],
                "-c", "copy", "-f", "streamhash", "-hash", "sha256", "-y", str(output),
            ],
            cwd=paths.work,
            stderr_path=paths.logs / f"{label}-hash.log",
        )
        return output.read_text(encoding="utf-8").split()

    def _fit_mux(self, job: Job, paths: JobPaths) -> None:
        self._restore_base_mux(paths)
        scan, selection = self._load_scan_and_selection(job, paths)
        playlist = scan.playlist(selection.playlist_id)
        identified = subprocess.run(
            ["mkvmerge", "--identify", "--identification-format", "json", str(paths.reference)],
            capture_output=True, text=True, timeout=600, check=False,
        )
        file_tracks = json.loads(identified.stdout or "{}").get("tracks") or []
        command, reference_maps, kept_maps = fit_base_mux_command(
            paths.muxed_output,
            paths.reference,
            file_tracks,
            playlist,
            selection.tracks,
            title=selection.output_name,
        )
        marker = paths.stages / "mux.json"
        inputs = {
            "schema_version": 1,
            "mode": "fit",
            "reference_sha256": sha256_file(paths.reference),
            "command": [str(item) for item in command],
        }
        if not _valid_stage(marker, inputs, [paths.muxed_output]):
            paths.muxed_output.unlink(missing_ok=True)
            (paths.work / "output.base.mkv").unlink(missing_ok=True)
            (paths.stages / "mux.base.json").unlink(missing_ok=True)
            self._runner(paths).run(
                command,
                cwd=paths.work,
                stdout_path=paths.logs / "mkvmerge.log",
                stderr_path=paths.logs / "mkvmerge.stderr.log",
                ok_returncodes=(0, 1),
            )
            if not paths.muxed_output.is_file():
                raise RuntimeError("mkvmerge did not write the file")
            before = self._stream_hashes(paths, paths.reference, reference_maps, "fit-reference")
            after = self._stream_hashes(paths, paths.muxed_output, kept_maps, "fit-base")
            if before != after:
                raise ReviewRequired(
                    "selecting the tracks changed one of the file's own streams",
                    details={"code": "external_merge_failed"},
                )
            _write_stage(marker, inputs, [paths.muxed_output])
        self.queue.advance(job.id, JobState.QC, message="the file's own tracks selected")

    def _fit_qc(self, job: Job, paths: JobPaths) -> None:
        self._restore_base_mux(paths)
        _scan, selection = self._load_scan_and_selection(job, paths)
        self._merge_external_tracks(job, paths, selection)
        report = paths.analysis / "external-merge-streams.json"
        _write_stage(
            paths.stages / "remux-qc.json",
            {"schema_version": 1, "mode": "fit", "mux_sha256": sha256_file(paths.muxed_output)},
            [report],
        )
        self.queue.advance(job.id, JobState.COMPARISON, message="the fitted tracks are verified")

    def _remux_root(self, paths: JobPaths) -> Path:
        """``work/remux``: eac3to's working directory (drive W:)."""

        return _ensure_contained_directory(
            paths.work / "remux", root=paths.work, description="remux directory"
        )

    def _eac3to_env(self, paths: JobPaths) -> dict[str, str]:
        # The job's own Wine prefix: two jobs never share drive letters.
        return {**os.environ, "BDENCODE_WINEPREFIX": str(paths.work / "wine")}

    def _remux_plan_path(self, paths: JobPaths) -> Path:
        return paths.analysis / "remux-plan.json"

    def _remux_prepare(self, job: Job, paths: JobPaths, *, advance: bool = True) -> None:
        scan, selection = self._load_scan_and_selection(job, paths)
        support = remux_support()
        if not support["available"]:
            raise ReviewRequired(
                "this host cannot make remuxes: eac3to or Wine is missing",
                details={"code": "remux_unavailable", **support},
            )
        playlist = scan.playlist(selection.playlist_id)
        reference_sha256 = self._prepare_reference(job, paths, scan, selection, playlist)
        self._prepare_external_sources(paths, selection, playlist, reference_sha256)
        with self._step(paths, "language", ("Hangsávok nyelvének ellenőrzése", "Checking audio track languages")):
            selection = self._resolve_selected_languages(job, scan, selection, paths)

        listing_path = paths.analysis / "eac3to-listing.txt"
        listing_marker = paths.stages / "eac3to-listing.json"
        listing_command = remux.eac3to_listing_command(scan.source, selection.playlist_id)
        listing_inputs = {
            "schema_version": 1,
            "scan_fingerprint": scan.fingerprint,
            "command": listing_command,
        }
        if not _valid_stage(listing_marker, listing_inputs, [listing_path]):
            with self._step(paths, "eac3to-listing", ("Lejátszási lista eac3to-val", "Reading the playlist with eac3to")):
                self._runner(paths).run(
                    listing_command,
                    cwd=self._remux_root(paths),
                    env=self._eac3to_env(paths),
                    stdout_path=listing_path,
                    stderr_path=paths.logs / "eac3to-listing.log",
                    timeout=1800,
                )
            _write_stage(listing_marker, listing_inputs, [listing_path])
        try:
            listing = remux.parse_listing(
                listing_path.read_text(encoding="utf-8", errors="replace")
            )
            matched = remux.match_tracks(playlist, listing)
        except remux.RemuxError as exc:
            raise ReviewRequired(
                f"eac3to and the scan disagree about the playlist: {exc}",
                details={"code": exc.code, "report": listing_path.name},
            ) from exc

        retained = remux_output_order(playlist, selection.tracks)
        # The name must say Atmos exactly when the bitstream carries it; eac3to
        # reads it, FFmpeg 5 does not.
        atmos = {
            stream.id: matched[stream.id].atmos and remux.stream_family(stream) != "DD"
            for _item, stream in retained
            if stream.kind is StreamKind.AUDIO
        }
        name_warnings = _release_name_warnings(
            selection.output_name,
            facts=remux_release_facts(
                scan=scan, playlist=playlist, tracks=selection.tracks, atmos=atmos
            ),
        )
        if name_warnings:
            self.database.add_event(
                EventCreate(
                    job_id=job.id,
                    kind="worker.release-name-advice",
                    message="the output name strays from the release-name rules; kept as chosen: "
                    + "; ".join(name_warnings),
                )
            )
        video_stream = playlist.video_streams[0]
        uhd = scan.disc_kind is DiscKind.UHD
        video_props = video_stream.video
        assert video_props is not None
        if len(playlist.video_streams) > 1 and not support.get("dolby_vision"):
            raise ReviewRequired(
                "this host cannot join Dolby Vision layers: dovi_tool is missing",
                details={"code": "remux_unavailable", **support},
            )
        try:
            # The guide: eac3to cannot handle PTS timing on HEVC video.
            outputs = remux.demux_outputs(
                ([] if uhd else [(video_stream, matched[video_stream.id])])
                + [(stream, matched[stream.id]) for _item, stream in retained]
            )
        except remux.RemuxError as exc:
            raise ReviewRequired(str(exc), details={"code": exc.code}) from exc
        chapters = listing.chapters
        plan = {
            "schema_version": 1,
            "playlist_id": selection.playlist_id,
            "reference_sha256": reference_sha256,
            "joined_clips": list(self._remux_joined_clips(paths, scan, playlist, listing)),
            "listing_header": listing.header,
            "chapters": bool(chapters and chapters.chapter_count),
            "chapter_count": chapters.chapter_count if chapters else 0,
            "outputs": [asdict(item) for item in outputs],
            # An UHD disc's video comes from the reference, not from eac3to.
            "video": (
                {
                    "stream_id": video_stream.id,
                    "track": matched[video_stream.id].number,
                    "family": remux.stream_family(video_stream),
                    "filename": REMUX_UHD_VIDEO,
                    "enhancement_layer": len(playlist.video_streams) > 1,
                    "el_type": video_props.dolby_vision_el_type,
                    "aspect": matched[video_stream.id].aspect,
                }
                if uhd
                else None
            ),
            "tracks": {
                str(track.number): {
                    "label": track.label,
                    "family": track.family,
                    "language": track.language,
                    "channels": track.channels,
                    "bit_depth": track.bit_depth,
                    "sample_rate": track.sample_rate,
                    "atmos": track.atmos,
                    "aspect": track.aspect,
                    "video_format": track.video_format,
                    "dialnorm_db": track.dialnorm_db,
                }
                for track in matched.values()
            },
        }
        plan_path = self._remux_plan_path(paths)
        atomic_write_json(plan_path, plan)
        self._register_artifact(
            job.id,
            plan_path,
            DatabaseArtifactKind.MANIFEST,
            plan_path.name,
            mime_type="application/json",
        )
        _write_stage(
            paths.stages / "pipeline-prepare.json",
            self._preparation_inputs(job, scan),
            [paths.reference, plan_path, listing_path],
        )
        if advance:
            self.queue.advance(
                job.id, JobState.ENCODING, message="remux prepared: eac3to matched the playlist"
            )

    def _remux_joined_clips(
        self,
        paths: JobPaths,
        scan: DiscScan,
        playlist: PlaylistCandidate,
        listing: remux.Eac3toListing,
    ) -> tuple[str, ...]:
        """The clips eac3to gets instead of the playlist, or nothing (``remux.whole_clips``).

        The plan numbers the tracks by the playlist's listing, so the clips must
        list the same tracks in the same order.
        """

        presentation: dict[str, tuple[int, int] | None] = {}
        for segment in playlist.segments:
            try:
                presentation[segment.clip_id] = remux.clip_presentation(
                    (scan.source / "BDMV" / "CLIPINF" / f"{segment.clip_id}.clpi").read_bytes()
                )
            except OSError:
                presentation[segment.clip_id] = None
        clips = remux.whole_clips(playlist, presentation)
        if not clips:
            return ()
        joined_path = paths.analysis / "eac3to-clips-listing.txt"
        with self._step(paths, "eac3to-clips-listing", ("A klipek listája eac3to-val", "Reading the clips with eac3to")):
            self._runner(paths).run(
                remux.eac3to_clips_listing_command(scan.source, clips),
                cwd=self._remux_root(paths),
                env=self._eac3to_env(paths),
                stdout_path=joined_path,
                stderr_path=paths.logs / "eac3to-clips-listing.log",
                check=False,
                timeout=1800,
            )
        try:
            joined = remux.parse_listing(joined_path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, remux.RemuxError):
            return ()
        return clips if joined.tracks == listing.tracks else ()

    def _load_remux_plan(self, job: Job, paths: JobPaths, scan: DiscScan) -> dict[str, Any]:
        plan_path = self._remux_plan_path(paths)
        if not _valid_stage(
            paths.stages / "pipeline-prepare.json",
            self._preparation_inputs(job, scan),
            [paths.reference, plan_path, paths.analysis / "eac3to-listing.txt"],
        ):
            raise ReviewRequired(
                "the remux plan does not belong to the current selection",
                details={"action": "rerun_prepare"},
            )
        try:
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ReviewRequired("remux plan is unreadable") from exc
        if not isinstance(plan, dict) or plan.get("schema_version") != 1:
            raise ReviewRequired("remux plan schema is unsupported")
        return plan

    def _remux_files(self, paths: JobPaths, plan: Mapping[str, Any]) -> list[Path]:
        root = self._remux_root(paths)
        files = [root / str(item["filename"]) for item in plan["outputs"]]
        if plan["chapters"]:
            files.append(root / remux.CHAPTERS_NAME)
        return files

    def _remux_demux(self, job: Job, paths: JobPaths) -> None:
        scan, selection = self._load_scan_and_selection(job, paths)
        plan = self._load_remux_plan(job, paths, scan)
        root = self._remux_root(paths)
        outputs = [remux.DemuxOutput(**item) for item in plan["outputs"]]
        command = remux.eac3to_demux_command(
            scan.source,
            selection.playlist_id,
            outputs,
            chapters=bool(plan["chapters"]),
            clips=plan.get("joined_clips") or (),
        )
        log_path = root / remux.LOG_NAME
        findings_path = paths.analysis / "eac3to-findings.json"
        files = [*self._remux_files(paths, plan), log_path, findings_path]
        inputs = {
            "schema_version": 1,
            "plan_sha256": sha256_file(self._remux_plan_path(paths)),
            "command": command,
        }
        marker = paths.stages / "remux-demux.json"
        if not _valid_stage(marker, inputs, files):
            for stale in files:
                stale.unlink(missing_ok=True)
            console = paths.logs / "eac3to-demux.log"
            console_errors = paths.logs / "eac3to-demux.stderr.log"
            live = self._live(paths)

            def progress() -> None:
                text = ""
                for part in (console, console_errors):
                    try:
                        text += part.read_text(encoding="utf-8", errors="replace")[-4096:]
                    except OSError:
                        pass
                fraction = remux.eac3to_progress(text)
                if fraction is not None:
                    live.update(fraction)

            self._run_reported(
                paths,
                command,
                probe=progress,
                cwd=root,
                env=self._eac3to_env(paths),
                stdout_path=console,
                stderr_path=console_errors,
            )
            missing = [
                path.name
                for path in files[:-1]
                if not path.is_file() or path.stat().st_size == 0
            ]
            if missing:
                raise ReviewRequired(
                    "eac3to did not write every planned file: " + ", ".join(missing),
                    details={"code": "eac3to_missing_output", "missing": missing},
                )
            log = log_path.read_text(encoding="utf-8", errors="replace")
            findings = remux.log_findings(log)
            atomic_write_json(
                findings_path,
                {
                    "schema_version": 1,
                    "frames": remux.logged_frame_count(log),
                    "findings": [asdict(item) for item in findings],
                },
            )
            _write_stage(marker, inputs, files)
        # eac3to is done: its Wine prefix (about 100 MB) is not needed again.
        shutil.rmtree(paths.work / "wine", ignore_errors=True)
        report = json.loads(findings_path.read_text(encoding="utf-8"))
        errors = [item["text"] for item in report["findings"] if item["severity"] == "error"]
        if errors:
            raise ReviewRequired(
                "eac3to reported an error while demuxing: " + errors[0],
                details={"code": "eac3to_error", "errors": errors, "report": findings_path.name},
            )
        notes = [item for item in report["findings"] if item["severity"] != "error"]
        if notes:
            self.database.add_event(
                EventCreate(
                    job_id=job.id,
                    kind="worker.eac3to-notes",
                    message="eac3to logged warnings or notes; they are listed with the release",
                    payload={"findings": notes},
                )
            )
        if plan["video"] is not None:
            self._remux_uhd_video(paths, plan)
        self.queue.advance(job.id, JobState.MUXING, message="eac3to demux completed")

    def _remux_video_files(self, paths: JobPaths, plan: Mapping[str, Any]) -> list[Path]:
        """An UHD disc's raw video and the sizes of its layers."""

        if plan["video"] is None:
            return []
        return [
            self._remux_root(paths) / str(plan["video"]["filename"]),
            paths.analysis / "remux-video.json",
        ]

    def _remux_uhd_video(self, paths: JobPaths, plan: Mapping[str, Any]) -> None:
        """The HEVC base layer of the reference, joined with its Dolby Vision
        enhancement layer into one profile 7 track when the disc has one."""

        root = self._remux_root(paths)
        video = plan["video"]
        output = root / str(video["filename"])
        report = paths.analysis / "remux-video.json"
        base = root / "video-bl.hevc"
        enhancement = root / "video-el.hevc"
        dual = bool(video["enhancement_layer"])
        inputs = {
            "schema_version": 1,
            "reference_sha256": _recorded_output_sha256(
                paths.stages / "reference-remux.json", paths.reference
            ),
            "commands": [
                remux.video_extract_command(paths.reference, 0, base),
                *(
                    [
                        remux.video_extract_command(paths.reference, 1, enhancement),
                        remux.dovi_mux_command(base, enhancement, output),
                    ]
                    if dual
                    else []
                ),
            ],
        }
        marker = paths.stages / "remux-video.json"
        if _valid_stage(marker, inputs, [output, report]):
            return
        with self._step(paths, "uhd-video", ("UHD videó kinyerése", "Extracting the UHD video")):
            for stale in (output, report, base, enhancement):
                stale.unlink(missing_ok=True)
            log = paths.logs / "remux-video.log"
            self._runner(paths).run(inputs["commands"][0], cwd=root, stderr_path=log)
            sizes = {"bl_bytes": base.stat().st_size, "el_bytes": 0}
            if dual:
                self._runner(paths).run(inputs["commands"][1], cwd=root, stderr_path=log)
                sizes["el_bytes"] = enhancement.stat().st_size
                self._runner(paths).run(inputs["commands"][2], cwd=root, stderr_path=log)
            else:
                os.replace(base, output)
            sizes["hevc_tier"] = remux.hevc_tier(output)
            atomic_write_json(report, {"schema_version": 1, **sizes})
            # The layers are in the output now; do not hold the space twice.
            base.unlink(missing_ok=True)
            enhancement.unlink(missing_ok=True)
        _write_stage(marker, inputs, [output, report])

    def _remux_duration(self, paths: JobPaths, playlist: PlaylistCandidate) -> Decimal:
        """Exact title length: eac3to's frame count at the video's rate."""

        video = playlist.video_streams[0].video
        assert video is not None
        try:
            report = json.loads(
                (paths.analysis / "eac3to-findings.json").read_text(encoding="utf-8")
            )
            frames = report.get("frames")
        except (OSError, json.JSONDecodeError):
            frames = None
        if isinstance(frames, int) and frames > 0 and video.frame_rate:
            rate = Fraction(video.frame_rate)
            return Decimal(frames) * Decimal(rate.denominator) / Decimal(rate.numerator)
        return Decimal(str(playlist.duration_seconds))

    def _remux_layout(
        self,
        paths: JobPaths,
        selection: ParsedSelection,
        playlist: PlaylistCandidate,
        plan: Mapping[str, Any],
        probes: Mapping[str, Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        """The final MKV's tracks with the guide's names, languages and flags."""

        root = self._remux_root(paths)
        duration = self._remux_duration(paths, playlist)
        streams = {item.id: item for item in playlist.streams}
        items = {item.stream_id: item for item in selection.tracks}
        outputs = [remux.DemuxOutput(**item) for item in plan["outputs"]]
        listed = plan["tracks"]

        def probe_int(name: str, key: str) -> int | None:
            value = probes.get(name, {}).get(key)
            try:
                number = int(value)
            except (TypeError, ValueError):
                return None
            return number if number > 0 else None

        audio_outputs = [item for item in outputs if streams[item.stream_id].kind is StreamKind.AUDIO]
        main = next(
            (
                item
                for item in audio_outputs
                if not item.compatibility
                and TrackRole.COMMENTARY not in streams[item.stream_id].roles
            ),
            audio_outputs[0],
        )
        main_language = items[main.stream_id].bcp47(streams[main.stream_id])
        main_primary = main_language.split("-")[0].casefold()

        layout: list[dict[str, Any]] = []
        if plan["video"] is not None:
            layout.append(
                self._remux_uhd_video_entry(
                    paths, playlist, plan["video"], probes, main_language, duration
                )
            )
        for output in outputs:
            stream = streams[output.stream_id]
            size = (root / output.filename).stat().st_size
            rate_kbps = remux.kbps(size, duration)
            track_info = listed.get(str(output.track), {})
            entry: dict[str, Any] = {
                "file": output.filename,
                "stream_id": output.stream_id,
                "family": output.family,
                "compatibility": output.compatibility,
                "kbps": rate_kbps,
                "default": False,
                "forced": False,
                "original": False,
                "commentary": False,
                "hearing_impaired": False,
                "visual_impaired": False,
                "remove_dialnorm": False,
                "default_duration": None,
            }
            if stream.kind is StreamKind.VIDEO:
                video = stream.video
                assert video is not None
                entry.update(
                    kind="video",
                    language=main_language,
                    default=True,
                    default_duration=remux.default_duration(video.frame_rate, video.field_order),
                    name=remux.video_track_name(
                        family=output.family,
                        kbps_value=rate_kbps,
                        height=video.height,
                        frame_rate=str(video.frame_rate),
                        aspect=track_info.get("aspect"),
                        profile=probes.get(output.filename, {}).get("profile"),
                        level=probe_int(output.filename, "level"),
                        field_order=video.field_order,
                    ),
                )
            elif stream.kind is StreamKind.AUDIO:
                item = items[output.stream_id]
                language = item.bcp47(stream)
                commentary = TrackRole.COMMENTARY in stream.roles
                channels = probe_int(output.filename, "channels") or stream.channels
                sample_rate = probe_int(output.filename, "sample_rate") or stream.sample_rate
                bit_depth = (
                    probe_int(output.filename, "bits_per_raw_sample")
                    or track_info.get("bit_depth")
                    or stream.bit_depth
                )
                described = remux.audio_track_name(
                    family=output.family,
                    channels=channels,
                    sample_rate=sample_rate,
                    kbps_value=rate_kbps,
                    bit_depth=None if output.compatibility else bit_depth,
                    atmos=bool(track_info.get("atmos")) and not output.compatibility,
                    prefix=(
                        "Compatibility Track"
                        if output.compatibility
                        else (item.name or None)
                    ),
                )
                if commentary and not output.compatibility:
                    described = item.name or stream.title or "Commentary"
                entry.update(
                    kind="audio",
                    language=language,
                    name=described,
                    default=output is main,
                    original=(
                        language.split("-")[0].casefold() == main_primary
                        and TrackRole.DUB not in stream.roles
                    ),
                    commentary=commentary,
                    visual_impaired=TrackRole.AUDIO_DESCRIPTION in stream.roles,
                    remove_dialnorm=(
                        not output.compatibility
                        and output.family in remux.REMOVE_DIALNORM_FAMILIES
                    ),
                )
            else:
                item = items[output.stream_id]
                forced = item.subtitle_kind == "forced"
                sdh = TrackRole.SDH in stream.roles
                entry.update(
                    kind="subtitle",
                    language=item.bcp47(stream),
                    name=item.name or ("Forced" if forced else "SDH" if sdh else None),
                    forced=forced,
                    hearing_impaired=sdh,
                    commentary=TrackRole.COMMENTARY in stream.roles,
                    explicit_default=item.default,
                )
            layout.append(entry)

        subtitles = [entry for entry in layout if entry["kind"] == "subtitle"]
        if any(entry["explicit_default"] is not None for entry in subtitles):
            for entry in subtitles:
                entry["default"] = bool(entry["explicit_default"])
        elif main_primary != "en":
            # The guide: regular English subtitles are default when the main
            # audio is not English.
            english = next(
                (
                    entry
                    for entry in subtitles
                    if entry["language"].split("-")[0].casefold() == "en"
                    and not entry["forced"]
                    and not entry["hearing_impaired"]
                    and not entry["commentary"]
                ),
                None,
            )
            if english is not None:
                english["default"] = True
        for entry in subtitles:
            entry.pop("explicit_default", None)
        return layout

    def _remux_uhd_video_entry(
        self,
        paths: JobPaths,
        playlist: PlaylistCandidate,
        planned: Mapping[str, Any],
        probes: Mapping[str, Mapping[str, Any]],
        language: str,
        duration: Decimal,
    ) -> dict[str, Any]:
        """The UHD video track: BDInfo's HEVC line, measured on the layers."""

        stream = playlist.video_streams[0]
        video = stream.video
        assert video is not None
        filename = str(planned["filename"])
        try:
            sizes = json.loads((paths.analysis / "remux-video.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ReviewRequired("the UHD video report is missing") from exc
        dynamic = remux.dynamic_range(video)
        probe = probes.get(filename, {})
        try:
            level = int(probe.get("level"))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            level = None
        base_kbps = remux.kbps(int(sizes["bl_bytes"]), duration)
        el_bytes = int(sizes["el_bytes"])
        return {
            "file": filename,
            "stream_id": stream.id,
            "family": "HEVC",
            "compatibility": False,
            "kbps": base_kbps,
            "kind": "video",
            "language": language,
            "default": True,
            "forced": False,
            "original": False,
            "commentary": False,
            "hearing_impaired": False,
            "visual_impaired": False,
            "remove_dialnorm": False,
            "default_duration": remux.default_duration(video.frame_rate, video.field_order),
            "name": remux.video_track_name(
                family="HEVC",
                kbps_value=base_kbps,
                height=video.height,
                frame_rate=str(video.frame_rate),
                aspect=planned.get("aspect"),
                profile=probe.get("profile"),
                level=level,
                field_order=video.field_order,
                bit_depth=video.bit_depth,
                hdr=(
                    "HDR10+"
                    if "HDR10+" in dynamic
                    else "HDR10"
                    if "HDR" in dynamic
                    else "HLG"
                    if "HLG" in dynamic
                    else None
                ),
                max_luminance_nits=remux.mastering_nits(
                    video.hdr10_static.mastering_display if video.hdr10_static else None
                ),
                color_primaries="BT.2020" if (video.color_primaries or "").casefold() == "bt2020" else "BT.709",
                hevc_tier=sizes.get("hevc_tier"),
                dolby_vision=(
                    # The guide: FEL above about 2500 kbps, otherwise MEL.
                    (planned.get("el_type") or ("FEL" if remux.kbps(el_bytes, duration) > 2500 else "MEL"))
                    if el_bytes
                    else None
                ),
                dolby_vision_kbps=remux.kbps(el_bytes, duration) if el_bytes else None,
            ),
        }

    def _remux_mux(self, job: Job, paths: JobPaths) -> None:
        self._restore_base_mux(paths)
        scan, selection = self._load_scan_and_selection(job, paths)
        playlist = scan.playlist(selection.playlist_id)
        plan = self._load_remux_plan(job, paths, scan)
        root = self._remux_root(paths)
        demux_marker = paths.stages / "remux-demux.json"
        demux_files = [
            *self._remux_files(paths, plan),
            root / remux.LOG_NAME,
            paths.analysis / "eac3to-findings.json",
        ]
        demux_pins = _assert_stage_outputs_current(
            demux_marker, demux_files, stage_name="eac3to demux"
        )
        video_files = self._remux_video_files(paths, plan)
        if video_files:
            demux_pins.update(
                _assert_stage_outputs_current(
                    paths.stages / "remux-video.json", video_files, stage_name="UHD video"
                )
            )
        probes_path = paths.analysis / "remux-streams.json"
        probes: dict[str, Any] = {}
        for item in [*plan["outputs"], *([plan["video"]] if plan["video"] else [])]:
            name = str(item["filename"])
            if item["family"] == "PGS":
                continue
            probe_path = root / f"{name}.probe.json"
            self._runner(paths).run(
                remux.stream_probe_command(root / name),
                cwd=root,
                stdout_path=probe_path,
                stderr_path=paths.logs / "remux-probe.log",
                timeout=600,
            )
            try:
                document = json.loads(probe_path.read_text(encoding="utf-8") or "{}")
                streams = document.get("streams") or [{}]
            except (OSError, TypeError, ValueError, AttributeError):
                streams = [{}]
            probes[name] = streams[0] if isinstance(streams[0], dict) else {}
        atomic_write_json(probes_path, {"schema_version": 1, "streams": probes})
        layout = self._remux_layout(paths, selection, playlist, plan, probes)
        layout_path = paths.analysis / "remux-tracks.json"
        atomic_write_json(layout_path, {"schema_version": 1, "tracks": layout})

        tags_path: Path | None = None
        options = selection.remux or RemuxOptions()
        tags = remux.tags_xml(imdb=options.imdb, tmdb=options.tmdb)
        if tags is not None:
            tags_path = root / "tags.xml"
            atomic_write_text(tags_path, tags)
        else:
            (root / "tags.xml").unlink(missing_ok=True)
        command = remux.remux_mkvmerge_command(
            paths.muxed_output,
            [
                remux.RemuxTrack(
                    path=root / entry["file"],
                    kind=entry["kind"],
                    language=entry["language"],
                    name=entry["name"],
                    default=entry["default"],
                    forced=entry["forced"],
                    original=entry["original"],
                    commentary=entry["commentary"],
                    hearing_impaired=entry["hearing_impaired"],
                    visual_impaired=entry["visual_impaired"],
                    remove_dialnorm=entry["remove_dialnorm"],
                    default_duration=entry["default_duration"],
                )
                for entry in layout
            ],
            title=remux.container_title(selection.output_name),
            chapters=root / remux.CHAPTERS_NAME if plan["chapters"] else None,
            global_tags=tags_path,
        )
        inputs = {
            "schema_version": 1,
            "mode": "remux",
            "demux": {str(path.name): list(pin) for path, pin in demux_pins.items()},
            "layout": layout,
            "tags": tags,
            "command": command,
        }
        marker = paths.stages / "mux.json"
        if not _valid_stage(marker, inputs, [paths.muxed_output]):
            paths.muxed_output.unlink(missing_ok=True)
            # mkvmerge exits 1 for warnings; they stay in its log.
            self._runner(paths).run(
                command,
                cwd=root,
                stdout_path=paths.logs / "mkvmerge.log",
                stderr_path=paths.logs / "mkvmerge.stderr.log",
                ok_returncodes=(0, 1),
            )
            if not paths.muxed_output.is_file():
                raise RuntimeError("mkvmerge did not write the remux")
            _write_stage(marker, inputs, [paths.muxed_output])
        self.queue.advance(job.id, JobState.QC, message="remux muxed")

    def _remux_layout_document(self, paths: JobPaths) -> list[dict[str, Any]]:
        try:
            document = json.loads(
                (paths.analysis / "remux-tracks.json").read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise ReviewRequired("remux track layout is missing") from exc
        tracks = document.get("tracks") if isinstance(document, dict) else None
        if not isinstance(tracks, list) or not tracks:
            raise ReviewRequired("remux track layout is invalid")
        return tracks

    def _remux_qc(self, job: Job, paths: JobPaths) -> None:
        """Prove the remux untouched: every frame and sample equals the disc's.

        The reference is FFmpeg's independent demux of the same playlist, so
        eac3to (under Wine) and mkvmerge are checked by a different reader.
        Video and every audio track decode to the same MD5 as their reference
        stream; the compatibility AC-3 (absent from the reference) is checked
        for sync against its TrueHD; subtitle payloads must hash the same.  A
        multi-clip title is held to its clips instead (``qc.multi_clip``).
        """

        self._restore_base_mux(paths)
        scan, selection = self._load_scan_and_selection(job, paths)
        playlist = scan.playlist(selection.playlist_id)
        output = paths.muxed_output
        mux_digest = _recorded_output_sha256(paths.stages / "mux.json", output)
        if mux_digest is None or sha256_file(output) != mux_digest:
            raise ReviewRequired(
                "the remux changed after its mux checkpoint",
                details={"action": "rerun_mux_and_qc"},
            )
        plan = self._load_remux_plan(job, paths, scan)
        layout = self._remux_layout_document(paths)
        layout_digest = sha256_file(paths.analysis / "remux-tracks.json")
        reference_sha256 = _recorded_output_sha256(
            paths.stages / "reference-remux.json", paths.reference
        )
        if reference_sha256 is None:
            raise ReviewRequired("the reference remux checkpoint is missing")
        report_path = paths.analysis / "remux-qc.json"
        mediainfo_path = paths.analysis / "mediainfo.txt"
        identify_path = paths.analysis / "mkvmerge-identify.json"
        qc_root = _ensure_contained_directory(
            paths.work / "remux-qc", root=paths.work, description="remux QC directory"
        )
        inputs = {
            "schema_version": 1,
            "mux_sha256": mux_digest,
            "reference_sha256": reference_sha256,
            "layout_sha256": layout_digest,
        }
        marker = paths.stages / "remux-qc.json"
        outputs = [report_path, mediainfo_path, identify_path]
        if not _valid_stage(marker, inputs, outputs):
            report = self._run_remux_qc(paths, scan.source, playlist, plan, layout, qc_root)
            atomic_write_json(report_path, report)
            shutil.copyfile(qc_root / "final.mkvmerge.json", identify_path)
            # Plain MediaInfo for the tracker's parser box: run on the relative
            # name, so it shows the release's file name and no server path.
            raw_mediainfo = qc_root / "mediainfo.txt"
            self._runner(paths).run(
                ["mediainfo", output.name],
                cwd=output.parent,
                stdout_path=raw_mediainfo,
                stderr_path=paths.logs / "remux-mediainfo.log",
                timeout=600,
            )
            atomic_write_text(
                mediainfo_path,
                raw_mediainfo.read_text(encoding="utf-8", errors="replace").replace(
                    output.name, f"{selection.output_name}.mkv"
                ),
            )
            _write_stage(marker, inputs, outputs)
        report = json.loads(report_path.read_text(encoding="utf-8"))
        failures = [item for item in report["checks"] if item["status"] == "failed"]
        if failures:
            raise ReviewRequired(
                "remux QC failed: " + failures[0]["message"],
                details={"code": "remux_qc_failed", "report": report_path.name,
                         "failures": [item["message"] for item in failures]},
            )
        self._register_artifact(
            job.id,
            report_path,
            DatabaseArtifactKind.REPORT,
            report_path.name,
            mime_type="application/json",
        )
        self._register_artifact(
            job.id,
            mediainfo_path,
            DatabaseArtifactKind.MEDIAINFO,
            mediainfo_path.name,
            mime_type="text/plain",
        )
        self._register_artifact(
            job.id,
            identify_path,
            DatabaseArtifactKind.MKVINFO,
            identify_path.name,
            mime_type="application/json",
        )
        self._merge_external_tracks(job, paths, selection)
        self.queue.advance(job.id, JobState.COMPARISON, message="remux verified untouched")

    def _remux_clip_streams(
        self, paths: JobPaths, disc_root: Path, clip_id: str, qc_root: Path
    ) -> tuple[Path, dict[str, Any]]:
        """A playlist clip's file and its streams as FFprobe numbers them."""

        clip = disc_root / "BDMV" / "STREAM" / f"{clip_id}.m2ts"
        if not clip.is_file():
            clip = clip.with_suffix(".M2TS")
        if not clip.is_file():
            raise ReviewRequired(f"selected playlist clip is missing: {clip_id}")
        report = qc_root / f"clip-{clip_id}.streams.json"
        self._runner(paths).run(
            multi_clip.clip_streams_command(clip),
            cwd=qc_root,
            stdout_path=report,
            stderr_path=report.with_suffix(".log"),
            timeout=600,
        )
        try:
            return clip, json.loads(report.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ReviewRequired(f"the streams of clip {clip_id} cannot be read: {exc}") from exc

    def _remux_first_subtitle_in_clips(
        self,
        paths: JobPaths,
        playlist: PlaylistCandidate,
        stream: MediaStream,
        clip_streams: Callable[[str], tuple[Path, dict[str, Any]]],
        qc_root: Path,
    ) -> Decimal | None:
        """Title time of a subtitle's first event, read from the clips."""

        title = Decimal(0)
        for segment in playlist.segments:
            in_time = Decimal(str(segment.in_time_seconds))
            out_time = Decimal(str(segment.out_time_seconds))
            clip, document = clip_streams(segment.clip_id)
            ordinal = multi_clip.clip_ordinal(document, "subtitle", stream.pid, stream.codec)
            if ordinal is not None:
                report = qc_root / f"clip-{segment.clip_id}.s{ordinal}.first.json"
                self._runner(paths).run(
                    first_packet_probe_command(clip, f"s:{ordinal}"),
                    cwd=qc_root,
                    stdout_path=report,
                    stderr_path=report.with_suffix(".log"),
                )
                try:
                    first = parse_first_packet_time(json.loads(report.read_text(encoding="utf-8")))
                except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
                    raise ReviewRequired(
                        f"clip {segment.clip_id}: the first subtitle packet is unreadable: {exc}"
                    ) from exc
                if first is not None and first < out_time:
                    return title + first - in_time
            title += out_time - in_time
        return None

    def _remux_packets_at_joins(
        self,
        paths: JobPaths,
        playlist: PlaylistCandidate,
        label: str,
        reference_stream: str,
        final_stream: str,
        qc_root: Path,
    ) -> multi_clip.PacketComparison:
        packets: dict[str, multi_clip.Packets] = {}
        for side, path, stream in (
            ("reference", paths.reference, reference_stream),
            ("final", paths.muxed_output, final_stream),
        ):
            target = qc_root / f"{label}.{side}.packets"
            self._runner(paths).run(
                multi_clip.packet_hash_command(path, stream),
                cwd=qc_root,
                stdout_path=target,
                stderr_path=target.with_suffix(".log"),
            )
            packets[side] = multi_clip.parse_packets(target.read_text(encoding="utf-8"))
            target.unlink(missing_ok=True)
        return multi_clip.compare_packets(
            packets["reference"], packets["final"], multi_clip.join_seconds(playlist.segments)
        )

    def _run_remux_qc(
        self,
        paths: JobPaths,
        disc_root: Path,
        playlist: PlaylistCandidate,
        plan: Mapping[str, Any],
        layout: Sequence[Mapping[str, Any]],
        qc_root: Path,
    ) -> dict[str, Any]:
        output = paths.muxed_output
        checks: list[dict[str, Any]] = []
        multiple_clips = len(playlist.segments) > 1

        def check(name: str, passed: bool, message: str, **details: Any) -> None:
            checks.append(
                {
                    "check": name,
                    "status": "passed" if passed else "failed",
                    "message": message,
                    **details,
                }
            )

        # 1. The container says what the plan says.
        identify = qc_root / "final.mkvmerge.json"
        self._runner(paths).run(
            ["mkvmerge", "-J", str(output)],
            cwd=qc_root,
            stdout_path=identify,
            stderr_path=paths.logs / "remux-identify.log",
            timeout=600,
        )
        try:
            identified = json.loads(identify.read_text(encoding="utf-8"))
            tracks = identified["tracks"]
        except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ReviewRequired(f"the remux cannot be identified: {exc}") from exc
        if len(tracks) != len(layout):
            check(
                "tracks",
                False,
                f"the remux has {len(tracks)} tracks, the plan {len(layout)}",
            )
        else:
            problems: list[str] = []
            for number, (track, planned) in enumerate(zip(tracks, layout)):
                properties = track.get("properties", {})
                # mkvmerge -J says "subtitles" for a subtitle track.
                container_type = {"subtitle": "subtitles"}.get(planned["kind"], planned["kind"])
                if track.get("type") != container_type:
                    problems.append(f"track {number} is {track.get('type')}, planned {planned['kind']}")
                    continue
                language = properties.get("language_ietf") or properties.get("language")
                expected = {
                    "language": planned["language"],
                    "track_name": planned.get("name"),
                    "default_track": planned["default"],
                    "flag_original": planned["original"],
                    "flag_commentary": planned["commentary"],
                    "flag_hearing_impaired": planned["hearing_impaired"],
                    "flag_visual_impaired": planned["visual_impaired"],
                }
                actual = {
                    "language": language,
                    "track_name": properties.get("track_name"),
                    "default_track": bool(properties.get("default_track")),
                    "flag_original": bool(properties.get("flag_original")),
                    "flag_commentary": bool(properties.get("flag_commentary")),
                    "flag_hearing_impaired": bool(properties.get("flag_hearing_impaired")),
                    "flag_visual_impaired": bool(properties.get("flag_visual_impaired")),
                }
                if planned["kind"] == "subtitle":
                    expected["forced_track"] = planned["forced"]
                    actual["forced_track"] = bool(properties.get("forced_track"))
                for key, value in expected.items():
                    if actual[key] != value:
                        problems.append(f"track {number} {key} is {actual[key]!r}, planned {value!r}")
                if properties.get("content_encoding_algorithms"):
                    problems.append(f"track {number} is compressed in the container")
            check(
                "tracks",
                not problems,
                problems[0] if problems else "every track has its planned name, language and flags",
                problems=problems,
            )
        video_plan = plan.get("video")
        if video_plan and video_plan.get("enhancement_layer"):
            # The container must announce the joined layers, or players would
            # treat the file as plain HDR10.
            dovi_report = qc_root / "final.dovi.json"
            self._runner(paths).run(
                remux.dovi_probe_command(output),
                cwd=qc_root,
                stdout_path=dovi_report,
                stderr_path=paths.logs / "remux-dovi-probe.log",
                timeout=600,
            )
            record = remux.parse_dovi_record(dovi_report.read_text(encoding="utf-8"))
            check(
                "dolby_vision",
                record == {"dv_profile": 7, "rpu_present_flag": 1, "el_present_flag": 1, "bl_present_flag": 1},
                f"Dolby Vision record: {record}",
            )
        chapters = identified.get("chapters") or []
        chapter_count = sum(int(item.get("num_entries", 0)) for item in chapters)
        check(
            "chapters",
            chapter_count == int(plan.get("chapter_count") or 0),
            f"{chapter_count} chapters, the disc has {plan.get('chapter_count') or 0}",
        )

        # 2. Every decoded frame and sample equals the reference's.
        reference_audio = {
            stream.id: ordinal for ordinal, stream in enumerate(playlist.audio_streams)
        }
        reference_subtitles = {
            stream.id: ordinal for ordinal, stream in enumerate(playlist.subtitle_streams)
        }
        jobs: list[tuple[str, str, str, str]] = [("video", "v:0", "v:0", "video")]
        final_audio = 0
        final_subtitle = 0
        subtitle_pairs: list[tuple[str, int, int]] = []
        subtitle_streams: dict[str, MediaStream] = {}
        sync_pairs: list[tuple[str, int, int, MediaStream, str]] = []
        streams_by_id = {stream.id: stream for stream in playlist.audio_streams}
        for planned in layout:
            if planned["kind"] == "audio":
                sibling = (
                    next(
                        (
                            stream
                            for stream in playlist.audio_streams
                            if remux.embedded_core_parent(stream, playlist.audio_streams)
                            is streams_by_id[planned["stream_id"]]
                        ),
                        None,
                    )
                    if planned["compatibility"]
                    else None
                )
                reference_stream = sibling or streams_by_id[planned["stream_id"]]
                # The compatibility AC-3 of a reference without its own AC-3
                # has nothing to equal; its sync against the TrueHD still counts.
                if sibling is not None or not planned["compatibility"]:
                    jobs.append(
                        (
                            planned["file"],
                            f"a:{reference_audio[reference_stream.id]}",
                            f"a:{final_audio}",
                            "audio",
                        )
                    )
                sync_pairs.append(
                    (
                        planned["file"],
                        reference_audio[reference_stream.id],
                        final_audio,
                        reference_stream,
                        "DD" if planned["compatibility"] else remux.stream_family(reference_stream),
                    )
                )
                final_audio += 1
            elif planned["kind"] == "subtitle":
                subtitle_pairs.append(
                    (planned["file"], reference_subtitles[planned["stream_id"]], final_subtitle)
                )
                subtitle_streams[planned["file"]] = next(
                    stream for stream in playlist.subtitle_streams if stream.id == planned["stream_id"]
                )
                final_subtitle += 1
        tasks: list[Callable[[], object]] = []
        for label, reference_stream, final_stream, _kind in jobs:
            for side, path, stream in (
                ("reference", paths.reference, reference_stream),
                ("final", output, final_stream),
            ):
                target = qc_root / f"{label}.{side}.md5"

                def task(path: Path = path, stream: str = stream, target: Path = target) -> None:
                    self._runner(paths).run(
                        remux.decoded_md5_command(path, stream),
                        cwd=qc_root,
                        stdout_path=target,
                        stderr_path=target.with_suffix(".log"),
                    )

                tasks.append(task)
        with self._step(paths, "remux-decode", ("Képkockák és minták összevetése", "Comparing every frame and sample")):
            self._run_independent(paths, tasks)
        for label, reference_stream, final_stream, kind in jobs:
            try:
                reference_md5 = remux.parse_md5(
                    (qc_root / f"{label}.reference.md5").read_text(encoding="utf-8")
                )
                final_md5 = remux.parse_md5(
                    (qc_root / f"{label}.final.md5").read_text(encoding="utf-8")
                )
            except (OSError, remux.RemuxError) as exc:
                check(f"{kind}:{label}", False, f"{label} could not be decoded: {exc}")
                continue
            if reference_md5 != final_md5 and kind == "audio" and multiple_clips:
                comparison = self._remux_packets_at_joins(
                    paths, playlist, label, reference_stream, final_stream, qc_root
                )
                check(
                    f"{kind}:{label}",
                    comparison.passed,
                    f"{label}: {comparison.problem}"
                    if comparison.problem
                    else f"{label}: {comparison.packets} packets equal the disc's, "
                    f"{sum(int(item['packets']) for item in comparison.removed)} removed at the clip joins",
                    reference_md5=reference_md5,
                    final_md5=final_md5,
                    removed_at_joins=list(comparison.removed),
                )
                continue
            check(
                f"{kind}:{label}",
                reference_md5 == final_md5,
                (
                    f"{label}: every decoded {'frame' if kind == 'video' else 'sample'} "
                    "equals the disc's"
                )
                if reference_md5 == final_md5
                else f"{label} decodes differently from the disc",
                reference_md5=reference_md5,
                final_md5=final_md5,
            )

        if video_plan and video_plan.get("enhancement_layer"):
            # Decoding covers only the base layer: the enhancement layer and the
            # RPU are compared unit by unit.
            layers = {
                "reference": (paths.reference, 1, dovi_layers.LAYER),
                "final": (output, 0, dovi_layers.JOINED),
            }

            def layer_task(side: str) -> Callable[[], object]:
                path, ordinal, form = layers[side]
                target = qc_root / f"enhancement-layer.{side}.json"
                return lambda: self._runner(paths).run(
                    remux.enhancement_layer_command(path, ordinal, form),
                    cwd=qc_root,
                    stdout_path=target,
                    stderr_path=target.with_suffix(".log"),
                )

            with self._step(
                paths,
                "remux-enhancement-layer",
                ("A Dolby Vision-réteg összevetése", "Comparing the Dolby Vision layer"),
            ):
                self._run_independent(paths, [layer_task(side) for side in layers])
            try:
                digests = {
                    side: json.loads(
                        (qc_root / f"enhancement-layer.{side}.json").read_text(encoding="utf-8")
                    )
                    for side in layers
                }
            except (OSError, json.JSONDecodeError) as exc:
                raise ReviewRequired(f"the enhancement layer cannot be compared: {exc}") from exc
            same = digests["reference"] == digests["final"] and bool(digests["final"].get("units"))
            check(
                "dolby_vision_layer",
                same,
                f"{digests['final'].get('units')} enhancement layer and RPU units equal the disc's"
                if same
                else "the enhancement layer differs from the disc's",
                reference=digests["reference"],
                final=digests["final"],
            )

        # 3. Subtitles: the same PGS payload.
        for label, reference_ordinal, final_ordinal in subtitle_pairs:
            hashes = {}
            for side, path, ordinal in (
                ("reference", paths.reference, reference_ordinal),
                ("final", output, final_ordinal),
            ):
                target = qc_root / f"{label}.{side}.streamhash"
                self._runner(paths).run(
                    stream_payload_hash_command(path, stream_type="s", stream=ordinal),
                    cwd=qc_root,
                    stdout_path=target,
                    stderr_path=target.with_suffix(".log"),
                )
                hashes[side] = target.read_text(encoding="utf-8").strip().split("=")[-1]
            check(
                f"subtitle:{label}",
                hashes["reference"] == hashes["final"] and bool(hashes["final"]),
                f"{label}: the subtitle payload equals the disc's"
                if hashes["reference"] == hashes["final"]
                else f"{label}: the subtitle payload differs from the disc's",
                **hashes,
            )

        # 4. Equal samples can still sit elsewhere on the timeline: measure each
        # track's sound against the disc, from the start of the video on both
        # sides, and each subtitle's first event the same way.
        reference_origin = self._probe_first_packet(
            paths, paths.reference, "v:0", label="remux-reference-video"
        )
        final_origin = self._probe_first_packet(paths, output, "v:0", label="remux-final-video")
        if reference_origin is None or final_origin is None:
            raise ReviewRequired("the remux or its reference has no video packets")
        duration = self._remux_duration(paths, playlist)
        probed_clips: dict[str, tuple[Path, dict[str, Any]]] = {}

        def clip_streams(clip_id: str) -> tuple[Path, dict[str, Any]]:
            if clip_id not in probed_clips:
                probed_clips[clip_id] = self._remux_clip_streams(paths, disc_root, clip_id, qc_root)
            return probed_clips[clip_id]

        for label, reference_ordinal, final_ordinal, reference_stream, family in sync_pairs:
            windows: list[av_sync.SyncWindow] = []
            source_args = audio_decode_input_args(normalize_audio_codec_name(reference_stream.codec))
            # What each window is compared with: the source, its ordinal, its start and
            # the window's start in the remux and its length.
            targets: list[tuple[Path, int, Decimal, Decimal, Decimal]] = []
            if multiple_clips:
                for window in multi_clip.clip_windows(playlist.segments):
                    clip, document = clip_streams(window.clip_id)
                    ordinal = multi_clip.clip_ordinal(
                        document, "audio", reference_stream.pid, reference_stream.codec
                    )
                    if ordinal is not None:
                        targets.append(
                            (
                                clip,
                                ordinal,
                                window.clip_start_seconds,
                                window.title_start_seconds + final_origin,
                                window.seconds,
                            )
                        )
            else:
                targets = [
                    (
                        paths.reference,
                        reference_ordinal,
                        start + reference_origin,
                        start + final_origin,
                        av_sync.WINDOW_SECONDS,
                    )
                    for start in av_sync.window_starts(duration)
                ]
            for index, (source, ordinal, source_start, final_start, seconds) in enumerate(targets):
                reference_raw = qc_root / f"{label}.{index}.reference.f32"
                final_raw = qc_root / f"{label}.{index}.final.f32"
                self._runner(paths).run(
                    av_sync.sync_window_command(
                        source,
                        ordinal,
                        source_start,
                        reference_raw,
                        input_args=source_args,
                        seconds=seconds,
                    ),
                    cwd=qc_root,
                    stderr_path=reference_raw.with_suffix(".log"),
                )
                self._runner(paths).run(
                    av_sync.sync_window_command(output, final_ordinal, final_start, final_raw, seconds=seconds),
                    cwd=qc_root,
                    stderr_path=final_raw.with_suffix(".log"),
                )
                windows.append(
                    av_sync.window_result(
                        final_start,
                        source_start,
                        av_sync.read_samples(reference_raw),
                        av_sync.read_samples(final_raw),
                    )
                )
                reference_raw.unlink(missing_ok=True)
                final_raw.unlink(missing_ok=True)
            verdict = av_sync.judge(
                windows,
                tolerance_ms=multi_clip.tolerance_ms(family) if multiple_clips else av_sync.TOLERANCE_MS,
            )
            check(
                f"sync:{label}",
                verdict.status != "out_of_sync",
                f"{label}: {verdict.lag_ms} ms from the disc ({verdict.status})",
                sync=verdict.to_dict(),
            )
        for label, reference_ordinal, final_ordinal in subtitle_pairs:
            if multiple_clips:
                reference_origin = Decimal(0)
                reference_first = self._remux_first_subtitle_in_clips(
                    paths, playlist, subtitle_streams[label], clip_streams, qc_root
                )
            else:
                reference_first = self._probe_first_packet(
                    paths, paths.reference, f"s:{reference_ordinal}", label=f"remux-reference-s{reference_ordinal}"
                )
            final_first = self._probe_first_packet(
                paths, output, f"s:{final_ordinal}", label=f"remux-final-s{final_ordinal}"
            )
            if reference_first is None or final_first is None:
                check(
                    f"subtitle-sync:{label}",
                    reference_first is None and final_first is None,
                    f"{label}: no subtitle events on either side"
                    if reference_first is None and final_first is None
                    else f"{label}: subtitle events are missing on one side",
                )
                continue
            shift_ms = ((final_first - final_origin) - (reference_first - reference_origin)) * 1000
            check(
                f"subtitle-sync:{label}",
                abs(shift_ms) <= av_sync.TOLERANCE_MS,
                f"{label}: first subtitle event {shift_ms:.3f} ms from the disc",
            )

        failed = [item for item in checks if item["status"] == "failed"]
        return {
            "schema_version": 1,
            "status": "failed" if failed else "passed",
            "checks": checks,
        }

    def _remux_screenshots(self, job: Job, paths: JobPaths) -> None:
        """Evenly spread screenshots of the remux itself (Aither: 3 or more)."""

        scan, selection = self._load_scan_and_selection(job, paths)
        playlist = scan.playlist(selection.playlist_id)
        output = paths.muxed_output
        mux_digest = _recorded_output_sha256(paths.stages / "mux.json", output)
        if mux_digest is None:
            raise ReviewRequired("the remux mux checkpoint is missing")
        video = playlist.video_streams[0].video
        assert video is not None
        count = REMUX_SCREENSHOT_COUNT.get(selection.tracker_profile.value, 6)
        duration = self._remux_duration(paths, playlist)
        rate = Fraction(video.frame_rate or "24000/1001")
        # Skip the first and last tenth (logos, credits); land on a frame.
        times = []
        for index in range(count):
            fraction = Decimal(index + 1) / Decimal(count + 1)
            seconds = duration * (Decimal("0.1") + Decimal("0.8") * fraction)
            frame = int(seconds * Decimal(rate.numerator) / Decimal(rate.denominator))
            times.append(
                (frame, Decimal(frame) * Decimal(rate.denominator) / Decimal(rate.numerator))
            )
        manifest_path = paths.comparison / "remux-screenshots.json"
        public_log = paths.comparison / (FIT_LOG_NAME if selection.is_fit else remux.LOG_NAME)
        pngs = [paths.comparison / f"{number + 1:02d}-screenshot.png" for number in range(count)]
        demux_log = self._remux_root(paths) / remux.LOG_NAME
        log_pins = (
            {}
            if selection.is_fit
            else _assert_stage_outputs_current(
                paths.stages / "remux-demux.json", [demux_log], stage_name="eac3to demux"
            )
        )
        inputs = {
            "schema_version": 1,
            "mux_sha256": mux_digest,
            "frames": [frame for frame, _seconds in times],
            "eac3to_log": [list(pin) for pin in log_pins.values()],
        }
        marker = paths.stages / "remux-screenshots.json"
        outputs = [manifest_path, public_log, *pngs]
        if not _valid_stage(marker, inputs, outputs):
            atomic_write_text(
                public_log,
                self._fit_public_log(paths, selection)
                if selection.is_fit
                else remux.public_log(demux_log.read_text(encoding="utf-8", errors="replace")),
            )
            _assert_public_sidecar_safe(public_log, wine_drives=True)
            for stale in paths.comparison.glob("*.png"):
                stale.unlink(missing_ok=True)
            images = []
            live = self._live(paths)
            for number, ((frame, seconds), png) in enumerate(zip(times, pngs)):
                self._runner(paths).run(
                    extract_png_at_timestamp_command(
                        output,
                        seconds,
                        png,
                        hdr_native=False,
                        # The tone-mapped view for HDR (what a browser shows).
                        source_hdr10="HDR" in remux.dynamic_range(video),
                        color_primaries=video.color_primaries,
                        color_transfer=video.color_transfer,
                        color_matrix=video.color_matrix,
                    ),
                    cwd=paths.work,
                    stderr_path=paths.logs / "remux-screenshots.log",
                )
                inspect_png(png)
                images.append(
                    {
                        "png": png.name,
                        "sha256": sha256_file(png),
                        "frame": frame,
                        "timestamp": remux.timestamp_text(seconds),
                    }
                )
                live.update((number + 1) / count)
            atomic_write_json(
                manifest_path, {"schema_version": 1, "kind": "remux", "images": images}
            )
            _assert_public_sidecar_safe(manifest_path)
            _write_stage(marker, inputs, outputs)
        self._register_artifact(
            job.id,
            manifest_path,
            DatabaseArtifactKind.REPORT,
            manifest_path.name,
            mime_type="application/json",
        )
        self._register_artifact(
            job.id,
            public_log,
            DatabaseArtifactKind.LOG,
            public_log.name,
            mime_type="text/plain",
        )
        for png in pngs:
            self._register_artifact(
                job.id,
                png,
                DatabaseArtifactKind.VIDEO_COMPARISON,
                png.name,
                mime_type="image/png",
            )
        self.queue.advance(
            job.id,
            JobState.UPLOADING,
            message="screenshots taken" if selection.is_fit else "remux screenshots taken",
        )

    def _fit_public_log(self, paths: JobPaths, selection: ParsedSelection) -> str:
        """What was fitted and how, without any server path."""

        lines = []
        for source in selection.external_sources:
            review = json.loads(
                (self._external_root(paths) / source.id / "review.json").read_text(encoding="utf-8")
            )
            mapped = review["map"]
            rate = Fraction(review["target_fps"])
            lines.append(f"External source: {review['kind']}, {review['fps']} fps")
            lines.append(
                f"Title: {review['target_fps']} fps, {mapped['target_frames']} frames; "
                f"{len(mapped['segments'])} fitted parts, picture match {mapped['similarity_median']}, "
                f"{float(mapped['unmatched_frames'] / rate):.1f} s not in the source"
            )
            for report in review["tracks"]:
                encoding = report.get("encoding")
                how = "not re-encoded" if report.get("copy") else f"{encoding['codec']} {encoding['bit_rate'] // 1000} kbps"
                lines.append(f"Track: {report['language']}, {report['codec']} {report['channels']} ch, {how}, pitch {report['pitch']}")
                gaps = report.get("fill_gaps") or []
                if report.get("fill_from") and gaps:
                    gains = [float(item["gain_db"]) for item in gaps]
                    lines.append(
                        f"Parts not in the source: {len(gaps)}, "
                        f"{int(report.get('filled_samples') or 0) / 48000:.1f} s, filled from the title's "
                        f"own {report['fill_from']} at matched level ({min(gains):+.1f} to {max(gains):+.1f} dB)"
                    )
            for report in review["subtitles"]:
                lines.append(
                    f"Subtitle: {report['language']}, {report['kept']} cues, "
                    f"{report['dropped']} dropped, {report['clipped']} clipped"
                )
        return "\n".join(lines) + "\n"

    def _remux_upload_and_finalize(
        self,
        job: Job,
        paths: JobPaths,
        scan: DiscScan,
        selection: ParsedSelection,
        mux_digest: str,
    ) -> None:
        """Upload the screenshots, write the BBCode with the eac3to log and
        publish the remux with its public evidence."""

        manifest_path = paths.comparison / "remux-screenshots.json"
        public_log = paths.comparison / (FIT_LOG_NAME if selection.is_fit else remux.LOG_NAME)
        qc_report = paths.analysis / (
            "external-merge-streams.json" if selection.is_fit else "remux-qc.json"
        )
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            images = [item for item in manifest["images"] if isinstance(item, Mapping)]
        except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ReviewRequired("remux screenshot manifest is missing or invalid") from exc
        pngs = [paths.comparison / str(item["png"]) for item in images]

        def evidence_pins() -> dict[Path, tuple[int, str]]:
            pins = _assert_stage_outputs_current(
                paths.stages / "remux-screenshots.json",
                [manifest_path, public_log, *pngs],
                stage_name="remux screenshots",
            )
            pins.update(
                _assert_stage_outputs_current(
                    paths.stages / "remux-qc.json", [qc_report], stage_name="remux QC"
                )
            )
            return pins

        validated = evidence_pins()
        for public_metadata in (manifest_path, qc_report):
            _assert_public_sidecar_safe(public_metadata)
        _assert_public_sidecar_safe(public_log, wine_drives=True)
        checkpoint, uploaded, provider_lock = self._upload_evidence_images(
            job, paths, replace(selection, upload_image_set="all"), pngs, manifest_pairs=None
        )
        try:
            findings = json.loads(
                (paths.analysis / "eac3to-findings.json").read_text(encoding="utf-8")
            ).get("findings", [])
        except (OSError, json.JSONDecodeError):
            findings = []
        bbcode = paths.comparison / "comparison.bbcode"
        lines = remux_bbcode(
            selection.output_name,
            images,
            uploaded,
            provider=provider_lock,
            profile=selection.tracker_profile.value,
            eac3to_log="" if selection.is_fit else public_log.read_text(encoding="utf-8"),
            kind="tracks added" if selection.is_fit else "remux",
            notes=[
                str(item.get("text"))
                for item in findings
                if isinstance(item, Mapping) and item.get("severity") == "warning"
            ],
        )
        atomic_write_text(bbcode, "\n".join(lines) + "\n")
        _assert_public_sidecar_safe(checkpoint)
        _assert_public_sidecar_safe(bbcode, wine_drives=True)
        bbcode_outputs = [checkpoint, bbcode]
        upload_marker = paths.stages / "upload.json"
        _write_stage(
            upload_marker,
            {
                "mode": "remux",
                "upload_images": selection.upload_images,
                "provider": provider_lock,
                "images": {path.name: sha256_file(path) for path in pngs},
            },
            bbcode_outputs,
        )
        self._stop_at_operator_boundary(job.id)
        # Upload adapters are external code: re-check everything published.
        if (
            _recorded_output_sha256(paths.stages / "mux.json", paths.muxed_output)
            != mux_digest
            or sha256_file(paths.muxed_output) != mux_digest
        ):
            raise ReviewRequired(
                "final Matroska changed during public evidence upload",
                details={"action": "rerun_mux_and_qc"},
            )
        if evidence_pins() != validated:
            raise ReviewRequired(
                "public evidence checkpoint set changed during image upload",
                details={"action": "rerun_qc"},
            )
        upload_pins = _assert_stage_outputs_current(
            upload_marker, bbcode_outputs, stage_name="upload checkpoint"
        )
        self._publish_release(
            job,
            paths,
            scan,
            selection,
            mux_digest=mux_digest,
            checkpoint=checkpoint,
            evidence_inputs={
                "mode": "remux",
                "screenshots_sha256": sha256_file(manifest_path),
                "qc_sha256": sha256_file(qc_report),
            },
            public_comparison_files=(manifest_path, public_log, *bbcode_outputs, *pngs),
            public_analysis_files=(qc_report,),
            pinned_public_files={**validated, **upload_pins},
            bbcode_outputs=bbcode_outputs,
            completion_message=(
                "the fitted tracks are in the file; QC and screenshots completed"
                if selection.is_fit
                else "remux, QC and screenshots completed"
            ),
        )

    def _upload_evidence_images(
        self,
        job: Job,
        paths: JobPaths,
        selection: ParsedSelection,
        pngs: Sequence[Path],
        *,
        manifest_pairs: object,
    ) -> tuple[Path, dict[str, Any], str | None]:
        """Upload the public images to one host, resumable image by image.

        Returns the checkpoint, the uploaded images by PNG name and the host
        the package is locked to (None when upload is off).
        """

        allowed_names = {path.name for path in pngs}
        checkpoint = paths.comparison / "uploads.json"
        checkpoint_document: dict[str, Any] = {}
        uploaded: dict[str, Any] = {}
        top_provider: str | None = None
        if checkpoint.is_file():
            try:
                loaded_checkpoint = json.loads(checkpoint.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ReviewRequired("upload checkpoint is invalid") from exc
            if not isinstance(loaded_checkpoint, dict):
                raise ReviewRequired("upload checkpoint must be a JSON object")
            checkpoint_document = loaded_checkpoint
            checkpoint_schema = checkpoint_document.get("schema_version")
            if checkpoint_schema == 2:
                required_checkpoint_fields = {"schema_version", "images"}
                allowed_checkpoint_fields = {
                    "schema_version",
                    "provider",
                    "provider_provisional",
                    "images",
                }
            elif checkpoint_schema == 1:
                skipped_checkpoint = checkpoint_document.get("skipped") is True
                allowed_checkpoint_fields = (
                    {"schema_version", "skipped", "reason", "images"}
                    if skipped_checkpoint
                    else {"schema_version", "images"}
                )
                required_checkpoint_fields = allowed_checkpoint_fields
                if skipped_checkpoint and selection.upload_images:
                    raise ReviewRequired(
                        "skipped upload checkpoint conflicts with current selection"
                    )
            else:
                raise ReviewRequired("upload checkpoint schema is unsupported")
            checkpoint_fields = set(checkpoint_document)
            if not required_checkpoint_fields.issubset(
                checkpoint_fields
            ) or not checkpoint_fields.issubset(allowed_checkpoint_fields):
                raise ReviewRequired(
                    "upload checkpoint contains unknown or missing fields"
                )
            raw_top_provider = checkpoint_document.get("provider")
            if raw_top_provider is not None:
                if not isinstance(raw_top_provider, str):
                    raise ReviewRequired("upload checkpoint provider is invalid")
                top_provider = raw_top_provider.strip().lower()
                if top_provider not in IMAGE_UPLOAD_PROVIDERS:
                    raise ReviewRequired("upload checkpoint provider is invalid")
            if (
                "provider_provisional" in checkpoint_document
                and checkpoint_document["provider_provisional"] is not True
            ):
                raise ReviewRequired(
                    "upload checkpoint provisional-provider flag is invalid"
                )
            if (
                checkpoint_document.get("provider_provisional") is True
                and top_provider is None
            ):
                raise ReviewRequired(
                    "upload checkpoint provisional provider is missing"
                )
            raw_uploaded = checkpoint_document.get("images", {})
            if not isinstance(raw_uploaded, dict) or not set(raw_uploaded).issubset(
                allowed_names
            ):
                raise ReviewRequired(
                    "upload checkpoint image names do not match current evidence"
                )
            for png in pngs:
                if png.name not in raw_uploaded:
                    continue
                try:
                    parsed_upload = parse_uploaded_image_checkpoint(
                        raw_uploaded[png.name],
                        expected_local_sha256=sha256_file(png),
                        legacy_provider=(
                            top_provider if checkpoint_schema == 2 else None
                        ),
                        infer_legacy_provider=checkpoint_schema == 1,
                    )
                except ValueError as exc:
                    raise ReviewRequired(
                        f"upload checkpoint entry {png.name} is unsafe: {exc}"
                    ) from exc
                uploaded[png.name] = asdict(parsed_upload)
        # Any schema-v2 provider loaded at stage entry is a durable lock.  This
        # includes a provisional pin left by a process interruption after the
        # network call began.  The current invocation may advance its own
        # provisional candidate after a classified-safe failure, but a later
        # invocation must conservatively stay on the persisted provider.
        provider_lock: str | None = (
            top_provider
            if checkpoint_document.get("schema_version") == 2 and top_provider
            else None
        )
        if uploaded:
            item_providers = {
                str(item.get("provider", "")).strip().lower()
                for item in uploaded.values()
                if str(item.get("provider", "")).strip()
            }
            if len(item_providers) > 1 or (
                top_provider and item_providers and top_provider not in item_providers
            ):
                raise ReviewRequired("upload checkpoint mixes image providers")
            # Schema v1 checkpoints predate provider metadata and can only
            # contain ImgBB results.
            provider_lock = (
                provider_lock or top_provider or next(iter(item_providers), "imgbb")
            )
            for item in uploaded.values():
                item.setdefault("provider", provider_lock)

        if selection.upload_images:
            try:
                to_upload = _images_to_upload(
                    pngs,
                    selection.upload_image_set,
                    [item for item in manifest_pairs if isinstance(item, Mapping)]
                    if isinstance(manifest_pairs, list)
                    else None,
                )
                pending = [png for png in to_upload if png.name not in uploaded]
                live = self._live(paths)
                if pending:
                    clients = self._image_upload_clients()
                    by_name = {
                        str(client.provider_name).strip().lower(): client
                        for client in clients
                    }
                    if provider_lock:
                        if (
                            selection.image_upload_provider != "auto"
                            and selection.image_upload_provider != provider_lock
                        ):
                            raise ReviewRequired(
                                "selected image provider conflicts with upload checkpoint"
                            )
                        client = by_name.get(provider_lock)
                        if client is None:
                            raise ImageUploadError(
                                f"checkpoint provider is unavailable: {provider_lock}"
                            )
                        candidates = [client]
                    elif selection.image_upload_provider != "auto":
                        client = by_name.get(selection.image_upload_provider)
                        if client is None:
                            raise ImageUploadError(
                                "selected image upload provider is unavailable",
                                provider=selection.image_upload_provider,
                            )
                        candidates = [client]
                    else:
                        candidates = clients
                    # Every image of the package goes to one host, so a host
                    # must take the largest pending image (UHD comparison PNGs
                    # exceed ImgBB's 32 MB).  Choose such a host up front; a
                    # host that cannot take it is not worth a retry.
                    largest = max(pending, key=lambda png: png.stat().st_size)
                    largest_bytes = largest.stat().st_size

                    def fits(candidate: ImageUploadClient) -> bool:
                        limit = upload_size_limit(candidate)
                        return limit is None or largest_bytes <= limit

                    if selection.image_upload_provider == "auto" and not provider_lock:
                        candidates = [client for client in candidates if fits(client)]
                    if not candidates or not fits(candidates[0]):
                        hosts = ", ".join(
                            f"{str(client.provider_name).strip().lower()} "
                            f"{(upload_size_limit(client) or 0) / 1e6:.0f} MB"
                            for client in (candidates or clients)
                        )
                        raise ReviewRequired(
                            f"comparison image {largest.name} "
                            f"({largest_bytes / 1e6:.1f} MB) exceeds the upload "
                            f"limit of the image host ({hosts})"
                            + (
                                "; the images already uploaded lock this job to "
                                f"{provider_lock}: reset the job's upload to use "
                                "another host"
                                if provider_lock
                                else ""
                            ),
                            details={
                                "code": "image_too_large_for_host",
                                "image": largest.name,
                                "bytes": largest_bytes,
                            },
                        )

                    fallback_failures: list[str] = []
                    finished = False
                    for client in candidates:
                        provider_name = str(client.provider_name).strip().lower()
                        if provider_lock is None:
                            # Persist the candidate before entering adapter code:
                            # the process may die after POST dispatch without an
                            # exception ever reaching this worker.
                            atomic_write_json(
                                checkpoint,
                                {
                                    "schema_version": 2,
                                    "provider": provider_name,
                                    "provider_provisional": True,
                                    "images": uploaded,
                                },
                            )
                        try:
                            checkpoint_lock = threading.Lock()

                            def upload_one(
                                png: Path, client: ImageUploadClient = client
                            ) -> None:
                                nonlocal provider_lock
                                # Never begin a new remote effect after a
                                # durable operator request.  A request arriving
                                # inside upload_png is acknowledged only after
                                # its result/checkpoint is known.
                                self._stop_at_operator_boundary(job.id)
                                result = client.upload_png(png)
                                provider_name = str(client.provider_name).strip().lower()
                                if result.provider != provider_name:
                                    raise ImageUploadError(
                                        "image uploader returned the wrong provider",
                                        provider=provider_name,
                                        provider_may_have_committed=True,
                                    )
                                with checkpoint_lock:
                                    provider_lock = provider_name
                                try:
                                    validated_result = parse_uploaded_image_checkpoint(
                                        asdict(result),
                                        expected_local_sha256=sha256_file(png),
                                        legacy_provider=provider_name,
                                    )
                                except ValueError as exc:
                                    raise ImageUploadError(
                                        "image uploader returned unsafe checkpoint data",
                                        provider=provider_name,
                                        provider_may_have_committed=True,
                                    ) from exc
                                with checkpoint_lock:
                                    uploaded[png.name] = asdict(validated_result)
                                    atomic_write_json(
                                        checkpoint,
                                        {
                                            "schema_version": 2,
                                            "provider": provider_lock,
                                            "images": uploaded,
                                        },
                                    )
                                    done = sum(1 for item in to_upload if item.name in uploaded)
                                    live.update(
                                        done / len(to_upload),
                                        detail=(
                                            f"{done} / {len(to_upload)} kép feltöltve",
                                            f"{done} / {len(to_upload)} images uploaded",
                                        ),
                                    )
                                self._stop_at_operator_boundary(job.id)

                            # The first image alone: its success locks the
                            # whole package to this host.
                            upload_one(pending[0])
                            self._upload_concurrently(client, upload_one, pending[1:])
                            finished = True
                            break
                        except ImageUploadError as exc:
                            if exc.provider_may_have_committed:
                                provider_lock = provider_name
                                atomic_write_json(
                                    checkpoint,
                                    {
                                        "schema_version": 2,
                                        "provider": provider_lock,
                                        "images": uploaded,
                                    },
                                )
                            # A provider is immutable after its first success.
                            # This preserves retry checkpoints and guarantees a
                            # single host for the complete BBCode package.
                            if provider_lock == provider_name or not exc.allow_fallback:
                                raise
                            fallback_failures.append(
                                f"{provider_name}: {sanitize_text(str(exc))[:400]}"
                            )
                            if selection.image_upload_provider != "auto":
                                # A manual provider has no next candidate.  Its
                                # explicitly safe failure must not leave a stale
                                # provisional lock behind.
                                atomic_write_json(
                                    checkpoint,
                                    {"schema_version": 2, "images": uploaded},
                                )
                                raise
                    if not finished:
                        # Every candidate failed before committing an image and
                        # explicitly allowed fallback.  Clear the current-run
                        # provisional pin so a later automatic retry may begin
                        # at the start of the configured chain.
                        atomic_write_json(
                            checkpoint,
                            {"schema_version": 2, "images": uploaded},
                        )
                        detail = "; ".join(fallback_failures)
                        raise ImageUploadError(
                            "all image upload providers are temporarily unavailable"
                            + (f": {detail}" if detail else "")
                        )

                if provider_lock is None:
                    raise ImageUploadError("image upload provider was not selected")
                # Persist a schema-v1 migration even when every image was
                # already present and no network request was necessary.
                atomic_write_json(
                    checkpoint,
                    {
                        "schema_version": 2,
                        "provider": provider_lock,
                        "images": uploaded,
                    },
                )
            except (ProcessInterrupted, ReviewRequired):
                raise
            except ImageUploadError as exc:
                if exc.permanent:
                    # A definitive rejection (file too big, invalid key...):
                    # retrying the same request cannot help.
                    raise ReviewRequired(
                        "the image host rejected the upload: "
                        f"{sanitize_text(str(exc))[:400]}; fix the cause "
                        "(provider, credentials) or turn image upload off",
                        details={
                            "code": "image_upload_rejected",
                            "provider": exc.provider,
                        },
                    ) from exc
                raise
            except Exception as exc:
                raise ImageUploadError(
                    "image upload provider initialization failed"
                ) from exc
        else:
            atomic_write_json(
                checkpoint,
                {
                    "schema_version": 1,
                    "skipped": True,
                    "reason": "upload_images=false",
                    "images": {},
                },
            )
        return checkpoint, uploaded, provider_lock

    def _publish_release(
        self,
        job: Job,
        paths: JobPaths,
        scan: DiscScan,
        selection: ParsedSelection,
        *,
        mux_digest: str,
        checkpoint: Path,
        evidence_inputs: Mapping[str, str],
        public_comparison_files: Sequence[Path],
        public_analysis_files: Sequence[Path],
        pinned_public_files: Mapping[Path, tuple[int, str]],
        bbcode_outputs: Sequence[Path],
        completion_message: str,
    ) -> None:
        """Copy the verified MKV and its public sidecars into completed/."""

        configured_completed_root = self.settings.completed_root
        if os.path.lexists(configured_completed_root) and _unsafe_directory_link(
            configured_completed_root
        ):
            raise ReviewRequired("completed root cannot be a symbolic link or junction")
        configured_completed_root.mkdir(mode=0o750, parents=True, exist_ok=True)
        completed_root = configured_completed_root.resolve(strict=True)
        resolved_data_root = self.settings.data_root.resolve(strict=True)
        if (
            completed_root.parent != resolved_data_root
            or completed_root.name != "completed"
        ):
            raise ReviewRequired("completed root escaped the configured data root")
        completed = completed_root / selection.output_name
        if os.path.lexists(completed) and _unsafe_directory_link(completed):
            raise ReviewRequired(
                "completed release directory cannot be a symbolic link or junction"
            )
        owner = completed / ".bdencode-owner.json"
        if os.path.lexists(owner) and _unsafe_directory_link(owner):
            raise ReviewRequired(
                "completed release owner record cannot be a symbolic link or junction"
            )
        if completed.exists() and not owner.is_file() and any(completed.iterdir()):
            raise ReviewRequired(
                f"completed directory is non-empty and has no BDEncode owner record: {completed}"
            )
        completed.mkdir(mode=0o750, parents=True, exist_ok=True)
        if completed.resolve(strict=True).parent != completed_root:
            raise ReviewRequired("completed release directory escaped completed_root")
        if owner.is_file():
            ownership = json.loads(owner.read_text(encoding="utf-8"))
            legacy_owner = (
                ownership.get("schema_version") == 1
                and ownership.get("job_id") == job.id
            )
            current_owner = (
                ownership.get("schema_version") == 2
                and ownership.get("output_name") == selection.output_name
                and ownership.get("mux_sha256") == mux_digest
            )
            if not legacy_owner and not current_owner:
                raise ReviewRequired(
                    f"completed directory contains a different release: {completed}"
                )
        _validate_completed_members(completed, selection.output_name, allow_legacy=True)
        atomic_write_json(
            owner,
            {
                "schema_version": 2,
                "output_name": selection.output_name,
                "mux_sha256": mux_digest,
            },
        )
        final_output = completed / f"{selection.output_name}.mkv"
        if os.path.lexists(final_output) and _unsafe_directory_link(final_output):
            raise ReviewRequired(
                "completed release output cannot be a symbolic link or junction"
            )
        finalize_inputs = {
            "mux_sha256": mux_digest,
            **evidence_inputs,
            "upload_sha256": sha256_file(checkpoint),
        }
        finalize_marker = paths.stages / "finalize.json"
        if not _valid_stage(finalize_marker, finalize_inputs, [final_output]):
            if (
                final_output.exists()
                and sha256_file(final_output) != finalize_inputs["mux_sha256"]
            ):
                raise ReviewRequired(
                    f"completed output already exists with different content: {final_output}"
                )
            temporary_output = completed / f".{selection.output_name}.mkv.partial"
            shutil.copy2(paths.muxed_output, temporary_output)
            if sha256_file(temporary_output) != finalize_inputs["mux_sha256"]:
                temporary_output.unlink(missing_ok=True)
                raise RuntimeError("completed output copy failed hash verification")
            os.replace(temporary_output, final_output)
            _write_stage(finalize_marker, finalize_inputs, [final_output])
        # Public release sidecars are rebuilt from an explicit allowlist.  This
        # also removes v1 logs/manifests and stale analysis files when an owned
        # completed directory is migrated in place.
        _replace_public_sidecars(
            completed=completed,
            comparison_source=paths.comparison,
            analysis_source=paths.analysis,
            comparison_files=public_comparison_files,
            analysis_files=public_analysis_files,
            expected_files=pinned_public_files,
        )
        sample = self._tracker_sample(
            paths, scan, selection, final_output, completed, mux_digest
        )
        _validate_completed_members(
            completed, selection.output_name, allow_legacy=False
        )
        if sample is not None:
            self._register_artifact(
                job.id,
                sample,
                DatabaseArtifactKind.OTHER,
                f"{SAMPLE_DIRECTORY}/{sample.name}",
                mime_type="video/x-matroska",
            )
        for bbcode_file in bbcode_outputs[1:]:
            self._register_artifact(
                job.id,
                bbcode_file,
                DatabaseArtifactKind.BBCODE,
                bbcode_file.name,
                mime_type="text/plain",
            )
        self._register_artifact(
            job.id,
            final_output,
            DatabaseArtifactKind.OUTPUT,
            final_output.name,
            mime_type="video/x-matroska",
        )
        self._record_source_size(scan, selection, paths)
        self._write_manifest(job, selection, paths, final_output)
        completed_job = self.queue.advance(
            job.id, JobState.COMPLETED, message=completion_message
        )
        self._cleanup_completed_work(completed_job, paths)

    def _tracker_sample(
        self,
        paths: JobPaths,
        scan: DiscScan,
        selection: ParsedSelection,
        final_output: Path,
        completed: Path,
        mux_digest: str,
    ) -> Path | None:
        """nCore's sample: cut from the finished file without re-encoding."""

        if selection.tracker_profile is not TrackerProfile.NCORE:
            return None
        window = sample_window(
            duration_seconds=scan.playlist(selection.playlist_id).duration_seconds,
            size_bytes=final_output.stat().st_size,
            uhd=selection.settings.encoder is VideoEncoder.X265,
        )
        if window is None:
            return None
        start, length = window
        directory = completed / SAMPLE_DIRECTORY
        sample = directory / f"{selection.output_name}.sample.mkv"
        inputs = {
            "schema_version": 1,
            "mux_sha256": mux_digest,
            "start_seconds": start,
            "length_seconds": length,
        }
        marker = paths.stages / "sample.json"
        if _valid_stage(marker, inputs, [sample]):
            return sample
        if os.path.lexists(directory) and _unsafe_directory_link(directory):
            raise ReviewRequired("the Sample directory cannot be a link")
        scratch = paths.work / "sample"
        shutil.rmtree(scratch, ignore_errors=True)
        scratch.mkdir(parents=True)
        self._runner(paths).run(
            [
                "mkvmerge",
                "--output",
                str(scratch / "sample.mkv"),
                "--split",
                f"parts:{_clock(start)}-{_clock(start + length)}",
                str(final_output),
            ],
            cwd=paths.work,
            stderr_path=paths.logs / "sample-mkvmerge.log",
            ok_returncodes=(0, 1),
            timeout=1800,
        )
        produced = sorted(scratch.glob("*.mkv"))
        if len(produced) != 1:
            raise RuntimeError("mkvmerge did not produce exactly one sample file")
        directory.mkdir(exist_ok=True)
        os.replace(produced[0], sample)
        shutil.rmtree(scratch, ignore_errors=True)
        _write_stage(marker, inputs, [sample])
        return sample

    def _cleanup_completed_work(self, job: Job, paths: JobPaths) -> None:
        """Remove only bulky retry data after the durable COMPLETE transition.

        FAILED and operator-paused jobs deliberately retain ``work`` so their
        validated checkpoints can be resumed.  Logs, analysis, comparisons,
        stage records and manifests remain under the job root even after a
        successful encode because database artifacts point to those files.

        Cleanup is best-effort and can never turn an already completed encode
        back into a failure.  Every target is resolved and checked against the
        configured job root before recursive removal.
        """

        if job.state is not JobState.COMPLETED or not paths.work.exists():
            return

        operation = None
        try:
            operation = self.maintenance.begin(
                "completed-workspace-cleanup",
                job.id,
                [
                    MaintenanceTargetSpec(
                        paths.work,
                        paths.root,
                        "completed temporary work directory",
                    )
                ],
                guard=MaintenanceDomainGuard(
                    job_id=job.id,
                    expected_job_version=job.version,
                    allowed_job_states=(JobState.COMPLETED.value,),
                ),
            )
            removed_bytes = int(operation.targets[0]["bytes_moved"])
            self.maintenance.stage(operation.id)
            self.database.record_completed_cleanup(
                job.id,
                expected_version=job.version,
                cleanup=None,
                payload={"bytes_removed": removed_bytes},
                maintenance_operation_id=operation.id,
            )
            self.maintenance.finalize(operation.id)
        except (OSError, RuntimeError) as exc:
            if operation is not None:
                try:
                    current = self.maintenance.operation(operation.id)
                    if current.phase in {
                        MaintenancePhase.INTENT,
                        MaintenancePhase.DETACHED,
                    }:
                        self.maintenance.rollback(operation.id)
                except Exception:
                    LOG.exception("completed job %s workspace rollback failed", job.id)
            LOG.warning("completed job %s workspace cleanup failed: %s", job.id, exc)
            try:
                self.database.add_event(
                    EventCreate(
                        job_id=job.id,
                        kind="job.workspace-cleanup-warning",
                        message="completed encode retained temporary work files",
                        payload={"error_type": type(exc).__name__},
                    )
                )
            except Exception:
                LOG.exception("job %s cleanup warning could not be recorded", job.id)
            return

    def _write_manifest(
        self,
        job: Job,
        selection: ParsedSelection,
        paths: JobPaths,
        output: Path,
    ) -> None:
        stage_records: dict[str, Any] = {}
        for marker in sorted(paths.stages.glob("*.json")):
            stage_records[marker.stem] = json.loads(marker.read_text(encoding="utf-8"))
        manifest_path = str(paths.manifest_json.resolve(strict=False))
        artifacts = [
            item.model_dump(mode="json")
            for item in self.database.list_artifacts(job_id=job.id, limit=1000)
            if item.path != manifest_path
        ]
        command_audit = paths.logs / "commands.jsonl"
        command_records: list[dict[str, Any]] = []
        if command_audit.is_file():
            for line in command_audit.read_text(
                encoding="utf-8", errors="replace"
            ).splitlines():
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(record, dict):
                    command_records.append(record)
        toolchain = capability_snapshot(
            (
                "ffmpeg",
                "ffprobe",
                "x264",
                "x265",
                "vspipe",
                "mkvmerge",
                "mkvinfo",
                "mediainfo",
                "vmaf",
                "bdencode-libbluray-scan",
                "hdr10plus_tool",
                "dovi_tool",
                *(("bdencode-eac3to", "wine") if selection.is_remux else ()),
            )
        )
        optional_reports: dict[str, Any] = {}
        for label, name in (
            ("auto_crf", "crf-search.json"),
            ("dynamic_hdr", "dynamic-hdr.json"),
        ):
            candidate = paths.analysis / name
            if candidate.is_file():
                try:
                    optional_reports[label] = json.loads(
                        candidate.read_text(encoding="utf-8")
                    )
                except (OSError, json.JSONDecodeError):
                    optional_reports[label] = {"error": "unreadable report"}
        atomic_write_json(
            paths.manifest_json,
            {
                "schema_version": 1,
                "job_id": job.id,
                "source_path": job.source_path,
                "selection": job.selection,
                # A remux has no encoder; its settings are an unused placeholder.
                "encoder_settings": (
                    None if selection.is_remux or selection.is_fit else selection.settings.to_dict()
                ),
                **optional_reports,
                "output": {
                    "path": str(output),
                    "sha256": sha256_file(output),
                    "size_bytes": output.stat().st_size,
                },
                "stages": stage_records,
                "artifacts": artifacts,
                "runtime_provenance": toolchain,
                "command_audit": {
                    "path": str(command_audit),
                    "sha256": sha256_file(command_audit)
                    if command_audit.is_file()
                    else None,
                    "records": command_records,
                },
                "comparison_attached_to_mkv": False,
                "manifest_registered_separately": True,
            },
        )
        self._register_artifact(
            job.id,
            paths.manifest_json,
            DatabaseArtifactKind.MANIFEST,
            paths.manifest_json.name,
            mime_type="application/json",
        )

    def _register_artifact(
        self,
        job_id: str,
        path: Path,
        kind: DatabaseArtifactKind,
        name: str,
        *,
        scan_id: str | None = None,
        mime_type: str | None = None,
    ) -> None:
        resolved = path.resolve(strict=True)
        digest = sha256_file(resolved)
        for current in self.database.list_artifacts(job_id=job_id, limit=1000):
            if current.path == str(resolved) and current.sha256 == digest:
                return
        self.database.create_artifact(
            ArtifactCreate(
                job_id=job_id,
                scan_id=scan_id,
                kind=kind,
                name=name,
                path=str(resolved),
                mime_type=mime_type,
                sha256=digest,
                size_bytes=resolved.stat().st_size,
                metadata={"sidecar": kind is not DatabaseArtifactKind.OUTPUT},
            )
        )


def run_worker(
    database: Database,
    settings: Settings,
    once: bool = False,
    poll_interval: float | None = None,
    stop_requested: Callable[[], bool] | None = None,
) -> int:
    """Run one serial encode lane plus one lightweight concurrent scan lane.

    ``once`` remains deterministic for maintenance/tests and processes at most
    one claimed job without starting the background preparation lane.
    """
    settings = settings.validate()
    settings.create_directories()
    database.initialize()
    interval = settings.worker_poll_seconds if poll_interval is None else poll_interval
    if interval < 0:
        raise ValueError("poll_interval cannot be negative")
    stopping = False

    def should_stop() -> bool:
        return stopping or bool(stop_requested and stop_requested())

    worker = PipelineWorker(database, settings, stop_requested=should_stop)
    instance_lock = None
    fcntl_module = None

    if os.name == "posix":
        import fcntl as fcntl_module  # type: ignore[no-redef]

        instance_path = settings.state_root / "worker.lock"
        instance_lock = instance_path.open("a+b")
        os.chmod(instance_path, 0o640)
        try:
            fcntl_module.flock(
                instance_lock.fileno(), fcntl_module.LOCK_EX | fcntl_module.LOCK_NB
            )
        except BlockingIOError:
            instance_lock.close()
            LOG.error("another BDEncode worker already owns %s", instance_path)
            return 75

    def stop(_signum: int, _frame: Any) -> None:
        nonlocal stopping
        stopping = True

    previous: dict[int, Any] = {}
    for number in (signal.SIGINT, signal.SIGTERM):
        try:
            previous[number] = signal.signal(number, stop)
        except (ValueError, OSError):
            pass

    idle_sleep = max(interval, 0.05)
    backup_check = {"next": 0.0}

    def maintain_backups() -> None:
        """Write the scheduled database backup when it is due (best effort)."""

        if settings.backup_interval_hours <= 0 or database.path == ":memory:":
            return
        now = time.monotonic()
        if now < backup_check["next"]:
            return
        backup_check["next"] = now + 600
        try:
            from .db_backup import ensure_scheduled_backup

            created = ensure_scheduled_backup(
                Path(database.path).expanduser(),
                database.backup_directory,
                interval=timedelta(hours=settings.backup_interval_hours),
                keep={"scheduled": settings.backup_keep_scheduled},
            )
            if created is not None:
                LOG.info("scheduled database backup written: %s", created.name)
        except Exception:
            LOG.exception("scheduled database backup failed; will retry later")

    def claim_lane(
        current: Callable[[], Job | None],
        claim: Callable[[], Job | None],
    ) -> Job | None:
        """Observe or claim one lane while excluding deployment transactions."""

        if _maintenance_active():
            return None
        if fcntl_module is None:
            return current() or claim()
        deployment_path = settings.state_root / "deployment.lock"
        with deployment_path.open("a+b") as deployment_lock:
            os.chmod(deployment_path, 0o640)
            while not should_stop():
                try:
                    fcntl_module.flock(
                        deployment_lock.fileno(),
                        fcntl_module.LOCK_SH | fcntl_module.LOCK_NB,
                    )
                    break
                except BlockingIOError:
                    time.sleep(min(idle_sleep, 0.2))
            if should_stop():
                return None
            try:
                if _maintenance_active():
                    return None
                return current() or claim()
            finally:
                fcntl_module.flock(deployment_lock.fileno(), fcntl_module.LOCK_UN)

    preparation_thread: threading.Thread | None = None
    try:
        _sd_notify("READY=1\nSTATUS=Ready; waiting for an encode job")
        if once:
            job = claim_lane(database.encoding_job, worker.queue.claim_next_ready)
            if job is None:
                job = claim_lane(database.preparing_job, worker.queue.claim_next)
            if job is not None:
                worker.process_job(job)
            return 0

        preparation_worker = PipelineWorker(
            database,
            settings,
            stop_requested=should_stop,
        )

        def prepare_jobs() -> None:
            while not should_stop():
                try:
                    job = claim_lane(
                        database.preparing_job,
                        preparation_worker.queue.claim_next,
                    )
                    if job is None:
                        time.sleep(idle_sleep)
                        continue
                    preparation_worker.process_job(job)
                except Exception:
                    LOG.exception(
                        "preparation lane failed; retrying after poll interval"
                    )
                    time.sleep(idle_sleep)

        preparation_thread = threading.Thread(
            target=prepare_jobs,
            name="bdencode-preparation",
            daemon=True,
        )
        preparation_thread.start()

        while not should_stop():
            job = claim_lane(database.encoding_job, worker.queue.claim_next_ready)
            if job is None:
                maintain_backups()
                time.sleep(idle_sleep)
                continue
            worker.process_job(job)
            # A processing review/upload pause intentionally keeps the encode
            # lane. Polling lets an API action resume it without a restart.
            time.sleep(idle_sleep)
        return 0
    finally:
        stopping = True
        if preparation_thread is not None:
            preparation_thread.join(timeout=min(max(idle_sleep * 2, 0.2), 5.0))
        for number, handler in previous.items():
            signal.signal(number, handler)
        if instance_lock is not None:
            if fcntl_module is not None:
                fcntl_module.flock(instance_lock.fileno(), fcntl_module.LOCK_UN)
            instance_lock.close()


__all__ = [
    "ParsedSelection",
    "PipelineWorker",
    "ReviewRequired",
    "parse_selection",
    "run_worker",
]
