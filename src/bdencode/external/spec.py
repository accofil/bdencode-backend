"""What a selection may ask of an external source."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

from .render import PITCH_KEEP, PITCH_RESTORE

SOURCE_KEYS = {"id", "path", "tracks", "subtitles", "approved_map_sha256"}
TRACK_KEYS = {"stream", "language", "name", "default", "position", "pitch"}
SUBTITLE_KEYS = {"path", "language", "name", "default", "forced"}

_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,15}$")
_STREAM = re.compile(r"^(a:\d{1,2}|#0x[0-9a-f]{1,4})$")
_LANGUAGE = re.compile(r"^[a-z]{2,3}(-[A-Za-z0-9]+)*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ExternalSpecError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ExternalTrack:
    stream: str
    language: str
    name: str | None = None
    default: bool = False
    position: int = 0
    pitch: str = PITCH_RESTORE


@dataclass(frozen=True, slots=True)
class ExternalSubtitle:
    path: str
    language: str
    name: str | None = None
    default: bool = False
    forced: bool = False


@dataclass(frozen=True, slots=True)
class ExternalSource:
    id: str
    path: str
    tracks: tuple[ExternalTrack, ...] = ()
    subtitles: tuple[ExternalSubtitle, ...] = ()
    approved_map_sha256: str | None = None


def valid_id(value: str) -> bool:
    return bool(_ID.fullmatch(value))


def _only(raw: Mapping[str, Any], allowed: set[str], what: str) -> None:
    unknown = set(raw) - allowed
    if unknown:
        raise ExternalSpecError(f"unknown {what} field(s): " + ", ".join(sorted(unknown)))


def _text(raw: Mapping[str, Any], key: str, what: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ExternalSpecError(f"{what} needs a {key}")
    return value


def _flag(raw: Mapping[str, Any], key: str, what: str) -> bool:
    value = raw.get(key, False)
    if not isinstance(value, bool):
        raise ExternalSpecError(f"{what} {key} must be true or false")
    return value


def _language(raw: Mapping[str, Any], what: str) -> str:
    value = _text(raw, "language", what)
    if not _LANGUAGE.fullmatch(value):
        raise ExternalSpecError(f"{what} language is not valid: {value}")
    return value


def _name(raw: Mapping[str, Any], what: str) -> str | None:
    value = raw.get("name")
    if value is not None and not isinstance(value, str):
        raise ExternalSpecError(f"{what} name must be text")
    return value or None


def parse_track(raw: Any) -> ExternalTrack:
    if not isinstance(raw, Mapping):
        raise ExternalSpecError("an external track must be an object")
    _only(raw, TRACK_KEYS, "external track")
    stream = _text(raw, "stream", "an external track")
    if not _STREAM.fullmatch(stream):
        raise ExternalSpecError(f"external track stream is not valid: {stream}")
    position = raw.get("position", 0)
    if isinstance(position, bool) or not isinstance(position, int) or position < 0:
        raise ExternalSpecError("external track position must be a whole number")
    pitch = raw.get("pitch", PITCH_RESTORE)
    if pitch not in {PITCH_RESTORE, PITCH_KEEP}:
        raise ExternalSpecError("external track pitch must be restore or keep")
    return ExternalTrack(
        stream=stream,
        language=_language(raw, "an external track"),
        name=_name(raw, "external track"),
        default=_flag(raw, "default", "external track"),
        position=position,
        pitch=pitch,
    )


def parse_subtitle(raw: Any) -> ExternalSubtitle:
    if not isinstance(raw, Mapping):
        raise ExternalSpecError("an external subtitle must be an object")
    _only(raw, SUBTITLE_KEYS, "external subtitle")
    path = _text(raw, "path", "an external subtitle")
    if not path.casefold().endswith(".srt"):
        raise ExternalSpecError("an external subtitle must be an .srt file")
    return ExternalSubtitle(
        path=path,
        language=_language(raw, "an external subtitle"),
        name=_name(raw, "external subtitle"),
        default=_flag(raw, "default", "external subtitle"),
        forced=_flag(raw, "forced", "external subtitle"),
    )


def parse_external_sources(raw: Any) -> tuple[ExternalSource, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ExternalSpecError("external_sources must be a list")
    sources = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, Mapping):
            raise ExternalSpecError("an external source must be an object")
        _only(item, SOURCE_KEYS, "external source")
        identifier = _text(item, "id", "an external source")
        if not _ID.fullmatch(identifier) or identifier in seen:
            raise ExternalSpecError(f"external source id is not valid: {identifier}")
        seen.add(identifier)
        tracks = item.get("tracks", [])
        subtitles = item.get("subtitles", [])
        if not isinstance(tracks, list) or not isinstance(subtitles, list):
            raise ExternalSpecError("external tracks and subtitles must be lists")
        if not tracks and not subtitles:
            raise ExternalSpecError("an external source needs a track or a subtitle")
        approved = item.get("approved_map_sha256")
        if approved is not None and not (isinstance(approved, str) and _SHA256.fullmatch(approved)):
            raise ExternalSpecError("approved_map_sha256 is not a SHA-256")
        parsed = tuple(parse_track(track) for track in tracks)
        streams = [track.stream for track in parsed]
        if len(streams) != len(set(streams)):
            raise ExternalSpecError("an external track is selected twice")
        sources.append(
            ExternalSource(
                id=identifier,
                path=_text(item, "path", "an external source"),
                tracks=parsed,
                subtitles=tuple(parse_subtitle(subtitle) for subtitle in subtitles),
                approved_map_sha256=approved,
            )
        )
    return tuple(sources)
