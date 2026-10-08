"""Tracker rules a job can follow: Aither, or nCore with the Hungarian release rules.

The rules come from the trackers' own pages (Aither's upload and encode rules;
nCore's wiki: upload rules, dupe rules and torrent names) and from the
Hungarian release standard nCore points to (github.com/encoding-hun/
rules-and-standards).  BDEncode never blocks a job on them: the wizard
proposes a compliant plan, and these findings explain every remaining
deviation in Hungarian, before the encode starts.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Sequence

from .media.bluray import MediaStream, PlaylistCandidate, StreamKind, TrackRole
from .media.planner import TrackAction, TrackSelection
from .release_naming import AUDIO_CODEC_LABELS, audio_codec_family, channel_layout


class TrackerProfile(StrEnum):
    NONE = "none"
    AITHER = "aither"
    NCORE = "ncore"


@dataclass(frozen=True, slots=True)
class TrackerFinding:
    code: str
    message: str
    severity: str = "warning"  # warning | info

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message, "severity": self.severity}


@dataclass(frozen=True, slots=True)
class _Planned:
    kind: StreamKind
    language: str
    codec: str
    channels: int | None
    source_channels: int | None
    commentary: bool
    dub: bool
    forced: bool
    sdh: bool
    pgs: bool
    source_lossless_stereo: bool


# Audio an nCore 1080p encode may carry; FLAC/AAC only up to 2.0.
NCORE_1080P_AUDIO = frozenset({"DD", "DDP", "DTS", "AAC", "FLAC"})
NCORE_2160P_AUDIO = NCORE_1080P_AUDIO | {"TRUEHD", "DTSHDMA", "DTSHDHRA", "DTSX"}
# These need a DD@640 (2.0: DD@256 or AAC) compatibility track on nCore.
NCORE_NEEDS_COMPAT = frozenset({"DTS", "TRUEHD", "DTSHDMA", "DTSHDHRA", "DTSX"})
NCORE_MAX_TRACKS = 16
_LOSSLESS = frozenset({"TRUEHD", "DTSHDMA", "DTSX", "FLAC", "LPCM"})
_LANGUAGE_NAMES = {
    "hu": "magyar",
    "en": "angol",
    "de": "német",
    "fr": "francia",
    "it": "olasz",
    "es": "spanyol",
    "ja": "japán",
    "ko": "koreai",
    "zh": "kínai",
    "ru": "orosz",
    "pl": "lengyel",
    "cs": "cseh",
    "und": "ismeretlen nyelvű",
}


def _language_name(code: str) -> str:
    return _LANGUAGE_NAMES.get(code, code)


def _planned(
    playlist: PlaylistCandidate, tracks: Sequence[TrackSelection]
) -> list[_Planned]:
    streams = {item.id: item for item in playlist.streams}
    ordered = sorted(enumerate(tracks), key=lambda pair: (pair[1].order, pair[0]))
    result: list[_Planned] = []
    for _index, item in ordered:
        stream: MediaStream | None = streams.get(item.stream_id)
        if item.action is TrackAction.OMIT or stream is None:
            continue
        if stream.kind is StreamKind.VIDEO:
            continue
        source_family = audio_codec_family(stream.codec, stream.codec_profile)
        if stream.kind is StreamKind.AUDIO:
            if item.action is TrackAction.COPY:
                codec = source_family
                channels = stream.channels
            else:
                codec = {
                    TrackAction.FLAC: "FLAC",
                    TrackAction.AC3: "DD",
                    TrackAction.EAC3: "DDP",
                    TrackAction.DTS: "DTS",
                }[item.action]
                channels = (
                    min(stream.channels, 6)
                    if item.action is not TrackAction.FLAC and stream.channels
                    else stream.channels
                )
        else:
            codec = stream.codec
            channels = None
        forced = item.subtitle_kind == "forced" or bool(item.forced)
        result.append(
            _Planned(
                kind=stream.kind,
                language=item.bcp47(stream).split("-")[0].casefold(),
                codec=codec,
                channels=channels,
                source_channels=stream.channels,
                commentary=TrackRole.COMMENTARY in stream.roles,
                dub=TrackRole.DUB in stream.roles,
                forced=forced,
                sdh=TrackRole.SDH in stream.roles,
                pgs="pgs" in stream.codec.casefold(),
                source_lossless_stereo=source_family in _LOSSLESS
                and (stream.channels or 0) <= 2,
            )
        )
    return result


def _original_language(audio: Sequence[_Planned]) -> str | None:
    spoken = [item for item in audio if not item.commentary]
    for candidates in (
        [item for item in spoken if not item.dub and item.language != "und"],
        [item for item in spoken if item.language not in {"hu", "und"}],
        spoken,
    ):
        if candidates:
            return candidates[0].language
    return None


def _label(codec: str) -> str:
    return AUDIO_CODEC_LABELS.get(codec, codec)


def _ncore(encoder: str, planned: Sequence[_Planned]) -> list[TrackerFinding]:
    findings: list[TrackerFinding] = []
    audio = [item for item in planned if item.kind is StreamKind.AUDIO]
    subtitles = [item for item in planned if item.kind is StreamKind.SUBTITLE]
    uhd = encoder == "x265"
    allowed = NCORE_2160P_AUDIO if uhd else NCORE_1080P_AUDIO
    resolution = "2160p" if uhd else "1080p"
    for item in audio:
        name = _language_name(item.language)
        if item.codec not in allowed:
            findings.append(
                TrackerFinding(
                    "ncore_audio_format",
                    f"{_label(item.codec)} hang ({name}) {resolution}-es nCore-encode-on nem "
                    "engedett; javasolt: E-AC3 (DD+) 5.1, 1024 kbps."
                    if not uhd
                    else f"{_label(item.codec)} hang ({name}) az nCore-on nem engedett; "
                    "a többcsatornás LPCM-et TrueHD-, DTS-HD MA- vagy E-AC3-sávvá kell alakítani.",
                )
            )
        elif item.codec in {"FLAC", "AAC"} and (item.channels or 0) > 2:
            findings.append(
                TrackerFinding(
                    "ncore_audio_format",
                    f"{_label(item.codec)} hang ({name}) az nCore-on legfeljebb 2.0 lehet.",
                )
            )
        elif item.codec == "FLAC" and not uhd and not item.source_lossless_stereo:
            findings.append(
                TrackerFinding(
                    "ncore_audio_format",
                    f"FLAC ({name}) 1080p-n csak legfeljebb 2.0-s veszteségmentes forrásból mehet.",
                )
            )
        if item.codec in NCORE_NEEDS_COMPAT and not item.commentary:
            if not any(
                other is not item
                and not other.commentary
                and other.language == item.language
                and other.codec in {"DD", "AAC"}
                for other in audio
            ):
                findings.append(
                    TrackerFinding(
                        "ncore_compat_missing",
                        f"{_label(item.codec)} ({name}) mellé kötelező egy DD@640 "
                        "(2.0 esetén DD@256 vagy AAC) kompatibilitási sáv.",
                    )
                )
        if (
            item.channels is not None
            and item.source_channels is not None
            and item.channels < item.source_channels
            and not item.commentary
            # A downmixed DD beside a full-channel track of the same language is the compat track.
            and not (
                item.codec == "DD"
                and any(
                    other is not item
                    and not other.commentary
                    and other.language == item.language
                    and (other.channels or 0) >= (item.source_channels or 0)
                    for other in audio
                )
            )
        ):
            findings.append(
                TrackerFinding(
                    "ncore_channels",
                    f"A(z) {name} hang {channel_layout(item.source_channels) or item.source_channels} "
                    f"helyett {channel_layout(item.channels) or item.channels} lett; az nCore a forrás "
                    "csatornaszámát kéri (7.1-es E-AC3 FFmpeg-gel nem készíthető).",
                )
            )
        if item.commentary and (item.codec not in {"DD", "AAC"} or (item.channels or 0) > 2):
            findings.append(
                TrackerFinding(
                    "ncore_commentary",
                    "A magyar szabvány szerint a kommentár csak AC3 (DD) vagy AAC lehet, legfeljebb 2.0.",
                    "info",
                )
            )

    original = _original_language(audio)
    permitted = {"hu", "en", "de"} | ({original} if original else set())
    for language in sorted({item.language for item in audio if not item.commentary} - permitted):
        findings.append(
            TrackerFinding(
                "ncore_language",
                f"{_language_name(language).capitalize()} hang az nCore-on nem mehet "
                "(csak magyar, angol, német és az eredeti nyelv).",
            )
        )
    spoken = [item for item in audio if not item.commentary]
    if any(item.language == "hu" for item in spoken) and spoken and spoken[0].language != "hu":
        findings.append(
            TrackerFinding(
                "ncore_order",
                "A magyar hangnak kell az első és alapértelmezett sávnak lennie; utána az eredeti, "
                "az angol, végül a kommentár.",
            )
        )
    total = 1 + len(audio) + len(subtitles)
    if total > NCORE_MAX_TRACKS:
        findings.append(
            TrackerFinding(
                "ncore_track_count",
                f"{total} sáv lenne a fájlban; az nCore legfeljebb {NCORE_MAX_TRACKS}-ot enged "
                "(videó, hang és felirat együtt).",
            )
        )

    dubbed = {item.language for item in spoken}
    for language in sorted({item.language for item in subtitles if item.forced} - dubbed):
        findings.append(
            TrackerFinding(
                "ncore_forced_without_dub",
                f"Kiegészítő (forced) {_language_name(language)} felirat csak akkor mehet, "
                f"ha van {_language_name(language)} szinkron is.",
            )
        )

    def subtitle_rank(item: _Planned) -> int:
        kind = 0 if item.forced else (2 if item.sdh else 1)
        if item.language == "hu":
            return kind
        if item.language == original:
            return 3 + kind
        return 6

    ranks = [subtitle_rank(item) for item in subtitles if not item.commentary]
    if ranks != sorted(ranks):
        findings.append(
            TrackerFinding(
                "ncore_subtitle_order",
                "Feliratsorrend: magyar forced, magyar, magyar SDH, eredeti forced, eredeti, "
                "eredeti SDH, végül a többi.",
            )
        )
    if any(item.pgs for item in subtitles):
        findings.append(
            TrackerFinding(
                "ncore_pgs",
                "PGS felirat marad: az nCore elfogadja, de a magyar encode-szabvány SRT-t kér "
                "(x264 HD-nél PGS nem is engedett).",
                "info",
            )
        )
    return findings


def _aither(planned: Sequence[_Planned]) -> list[TrackerFinding]:
    findings: list[TrackerFinding] = []
    audio = [item for item in planned if item.kind is StreamKind.AUDIO]
    subtitles = [item for item in planned if item.kind is StreamKind.SUBTITLE]
    original = _original_language(audio)
    permitted = {"en"} | ({original} if original else set())
    for language in sorted({item.language for item in audio if not item.commentary} - permitted):
        findings.append(
            TrackerFinding(
                "aither_language",
                f"Aitheren csak az eredeti nyelvű és az angol hang mehet (plusz kommentár); "
                f"a(z) {_language_name(language)} sávot ki kell hagyni.",
            )
        )
    for item in audio:
        if item.codec == "TRUEHD" and not any(
            other is not item
            and not other.commentary
            and other.language == item.language
            and other.codec in {"DD", "DDP"}
            for other in audio
        ):
            findings.append(
                TrackerFinding(
                    "aither_compat_missing",
                    f"A TrueHD ({_language_name(item.language)}) mellé önálló DD vagy DD+ "
                    "kompatibilitási sáv kell.",
                )
            )
    english_audio = any(item.language == "en" and not item.commentary for item in audio)
    english_subtitles = any(
        item.language == "en" and not item.forced and not item.commentary for item in subtitles
    )
    if audio and not english_audio and not english_subtitles:
        findings.append(
            TrackerFinding(
                "aither_english_subtitles",
                "Nincs angol hang, ezért angol (teljes) felirat kötelező.",
            )
        )
    return findings


def tracker_findings(
    profile: TrackerProfile,
    *,
    encoder: str,
    playlist: PlaylistCandidate,
    tracks: Sequence[TrackSelection],
) -> tuple[TrackerFinding, ...]:
    """Every deviation of the track plan from the chosen tracker's rules."""

    if profile is TrackerProfile.NONE:
        return ()
    planned = _planned(playlist, tracks)
    if profile is TrackerProfile.NCORE:
        return tuple(_ncore(encoder, planned))
    return tuple(_aither(planned))


__all__ = [
    "NCORE_1080P_AUDIO",
    "NCORE_2160P_AUDIO",
    "NCORE_MAX_TRACKS",
    "NCORE_NEEDS_COMPAT",
    "TrackerFinding",
    "TrackerProfile",
    "tracker_findings",
]
