"""Recognise Atmos and DTS:X audio, which the scan's FFmpeg 5 does not report.

FFmpeg 5 calls a TrueHD Atmos stream plain TrueHD, so a release name could not
truthfully say Atmos.  MediaInfo reads it from the bitstream in about a second:
``Dolby TrueHD with Dolby Atmos`` on the stream's PID.  Only the main playlists
are probed, and everything fails soft: without an answer the scan stays as it was.
"""

from __future__ import annotations

import json
import logging
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, Mapping

from .media.bluray import DiscScan, PlaylistCandidate, StreamKind
from .process import ProcessFailure

LOG = logging.getLogger(__name__)

_OBJECT_MARKS = ("atmos", "dts:x", "dts-x", "dtsx")


def object_audio_pids(report: Mapping[str, Any]) -> frozenset[int]:
    """The PIDs of MediaInfo's audio tracks that carry Atmos or DTS:X."""

    media = report.get("media")
    tracks = media.get("track") if isinstance(media, Mapping) else None
    pids: set[int] = set()
    for track in tracks if isinstance(tracks, list) else ():
        if not isinstance(track, Mapping) or track.get("@type") != "Audio":
            continue
        text = " ".join(
            str(track.get(key) or "")
            for key in ("Format_Commercial_IfAny", "Format_Commercial", "Format_Profile", "Format")
        ).casefold()
        if not any(mark in text for mark in _OBJECT_MARKS):
            continue
        # A multiplexed PID is written as "4352-1"; the PID is what counts.
        identifier = str(track.get("ID") or "").split("-")[0].split(" ")[0]
        if identifier.isdigit():
            pids.add(int(identifier))
    return frozenset(pids)


def _with_object_audio(playlist: PlaylistCandidate, pids: frozenset[int]) -> PlaylistCandidate:
    return replace(
        playlist,
        streams=tuple(
            # The embedded AC-3 on a TrueHD PID carries no objects.
            replace(stream, object_audio=True)
            if stream.kind is StreamKind.AUDIO
            and stream.pid in pids
            and stream.codec.casefold() != "ac3"
            else stream
            for stream in playlist.streams
        ),
    )


def detect_object_audio(
    scan: DiscScan,
    disc_root: Path,
    *,
    run: Callable[..., Any],
    read_text: Callable[[Path], str],
    work: Path,
    logs: Path,
    mediainfo: str = "mediainfo",
) -> DiscScan:
    """Mark the Atmos and DTS:X streams of the main playlists."""

    longest = max((item.duration_seconds for item in scan.playlists if item.recommended), default=0.0)
    if longest <= 0.0:
        longest = max((item.duration_seconds for item in scan.playlists), default=0.0)
    work.mkdir(mode=0o750, parents=True, exist_ok=True)
    answers: dict[str, frozenset[int]] = {}
    updated: list[PlaylistCandidate] = []
    for playlist in scan.playlists:
        carrying = any(
            stream.kind is StreamKind.AUDIO and stream.codec.casefold() in {"truehd", "eac3", "dts"}
            for stream in playlist.streams
        )
        if not carrying or not playlist.segments or playlist.duration_seconds < longest * 0.5:
            updated.append(playlist)
            continue
        clip = playlist.segments[0].clip_id
        if clip not in answers:
            report = work / f"mediainfo-{clip}.json"
            try:
                run(
                    [mediainfo, "--Output=JSON", str(disc_root / "BDMV" / "STREAM" / f"{clip}.m2ts")],
                    cwd=work,
                    stdout_path=report,
                    stderr_path=logs / "object-audio-probe.log",
                    timeout=300,
                )
                answers[clip] = object_audio_pids(json.loads(read_text(report)))
            except (ProcessFailure, OSError, ValueError, AttributeError) as exc:
                LOG.info("clip %s: MediaInfo gave no object-audio answer: %s", clip, exc)
                answers[clip] = frozenset()
        pids = answers[clip]
        updated.append(_with_object_audio(playlist, pids) if pids else playlist)
    return replace(scan, playlists=tuple(updated))


__all__ = ["detect_object_audio", "object_audio_pids"]
