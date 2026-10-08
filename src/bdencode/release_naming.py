"""Encode release names: one grammar for Aither and Hungarian (nCore) names.

Aither::

    Title.Year[.Cut].2160p.UHD.BluRay[.Dual-Audio].DTS-HD.MA.5.1[.Atmos][.DV.HDR].x265-TAG

Hungarian release rules (encoding-hun, the standard nCore points to)::

    Title.Year.2160p.UHD.BluRay[.DV.HDR].TrueHD.7.1[.Atmos].x265[.HUN]-TAG

Between the source and the video codec only allowlisted technical tokens may
appear, in any order; three-letter language tags may follow the codec.  Every
token a name advertises must be true of the planned output, so a name can
never claim an audio format, channel layout, Atmos, HDR flavour or language
that the encode does not carry.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from .media.language import iso639_2_to_bcp47, normalize_iso639_2


@dataclass(frozen=True, slots=True)
class AudioOutput:
    """One planned output audio track, as a release name may describe it."""

    codec: str  # TRUEHD, DTSHDMA, DTSHDHRA, DTSX, DTS, DDP, DD, FLAC, LPCM, AAC, OPUS, OTHER
    channels: int | None = None
    atmos: bool = False
    language: str = "und"  # BCP 47 primary subtag, lower case
    commentary: bool = False


@dataclass(frozen=True, slots=True)
class ReleaseFacts:
    encoder: str  # "x264" | "x265"
    audio: tuple[AudioOutput, ...] = ()
    # Any of SDR, HDR, HDR10+, DV, HLG.
    dynamic_range: frozenset[str] = frozenset({"SDR"})


@dataclass(frozen=True, slots=True)
class ReleaseName:
    title: str
    resolution: str
    source: str
    tokens: tuple[str, ...]
    codec: str
    languages: tuple[str, ...]
    group: str | None


_GROUP = r"[A-Za-z0-9][A-Za-z0-9._-]{0,31}"
_LANGUAGE_TAG = r"(?:[1-9]x)?[A-Za-z]{3}"


def _name_pattern(resolution: str, source: str, codec: str) -> re.Pattern[str]:
    return re.compile(
        rf"^(?P<title>.+?)\.(?P<resolution>{resolution})\.(?P<source>{source})"
        rf"(?P<middle>(?:\.[^.]+)*?)\.(?P<codec>{codec})"
        rf"(?P<languages>(?:\.{_LANGUAGE_TAG})*)(?:-(?P<group>{_GROUP}))?$",
        re.IGNORECASE,
    )


RELEASE_NAME_PATTERNS: dict[str, re.Pattern[str]] = {
    "x264": _name_pattern("1080p", "BluRay", "x264"),
    "x265": _name_pattern("2160p", r"UHD\.BluRay", "x265"),
}

EXAMPLE_NAMES = {
    "x264": "Title.Year.1080p.BluRay.DTS-HD.MA.5.1.x264-GROUP",
    "x265": "Title.Year.2160p.UHD.BluRay.TrueHD.7.1.Atmos.DV.HDR.x265-GROUP",
}

# Order matters: the first alternative that ends on a token boundary wins.
_AUDIO = (
    r"DTS-HD\.MA|DTS-HD\.HRA?|DTS[-.]X|DTS-ES|DTS|TrueHD|DDP|DD\+|E-?AC-?3|DD|AC-?3"
    r"|FLAC|L?PCM|AAC|Opus"
)
_CHANNELS = r"[1-9]\.[0-2]"
_TOKEN = re.compile(
    rf"(?:(?P<audio>{_AUDIO})(?:\.?(?P<audio_channels>{_CHANNELS}))?"
    rf"|(?P<channels>{_CHANNELS})"
    r"|(?P<atmos>Atmos)"
    r"|(?P<hdr10plus>HDR10Plus|HDR10\+|HDR10P)"
    r"|(?P<hdr>HDR10|HDR)"
    r"|(?P<dv>DV|DoVi|Dolby\.Vision)"
    r"|(?P<hlg>HLG)"
    r"|(?P<sdr>SDR)"
    r"|(?P<dual>Dual-Audio)"
    r"|(?P<multi>MULTi)"
    r"|(?P<hybrid>Hybrid))"
    r"(?=\.|$)",
    re.IGNORECASE,
)
_AUDIO_CODECS = (
    (re.compile(r"DTS-HD\.MA", re.I), "DTSHDMA"),
    (re.compile(r"DTS-HD\.HRA?", re.I), "DTSHDHRA"),
    (re.compile(r"DTS[-.]X", re.I), "DTSX"),
    (re.compile(r"DTS(?:-ES)?", re.I), "DTS"),
    (re.compile(r"TrueHD", re.I), "TRUEHD"),
    (re.compile(r"DDP|DD\+|E-?AC-?3", re.I), "DDP"),
    (re.compile(r"DD|AC-?3", re.I), "DD"),
    (re.compile(r"FLAC", re.I), "FLAC"),
    (re.compile(r"L?PCM", re.I), "LPCM"),
    (re.compile(r"AAC", re.I), "AAC"),
    (re.compile(r"Opus", re.I), "OPUS"),
)
AUDIO_CODEC_LABELS = {
    "DTSHDMA": "DTS-HD MA",
    "DTSHDHRA": "DTS-HD HRA",
    "DTSX": "DTS:X",
    "DTS": "DTS",
    "TRUEHD": "TrueHD",
    "DDP": "E-AC-3 (DD+)",
    "DD": "AC-3 (DD)",
    "FLAC": "FLAC",
    "LPCM": "LPCM",
    "AAC": "AAC",
    "OPUS": "Opus",
}
# Codec tags left in the title part are inherited source metadata.
_INHERITED = re.compile(
    r"(?<![A-Za-z0-9])(?:DTS-HD|DTS-X|TrueHD|DDP|DD\+|E-?AC-?3|FLAC|LPCM"
    r"|x26[45]|H\.?26[45]|HEVC|AVC|REMUX)(?![A-Za-z])",
    re.IGNORECASE,
)
_SOURCE_DISC_TAGS = ("COMPLETEBLURAY", "BDMV", "BLURAYAVC", "BLURAYHEVC")


def channel_count(layout: str) -> int:
    """``5.1`` -> 6, ``7.1`` -> 8, ``2.0`` -> 2."""

    main, _, lfe = layout.partition(".")
    return int(main) + int(lfe or 0)


def channel_layout(count: int | None) -> str | None:
    return {1: "1.0", 2: "2.0", 3: "2.1", 6: "5.1", 7: "6.1", 8: "7.1"}.get(count or 0)


def audio_codec_family(codec: str, profile: str | None = None) -> str:
    """Name-level codec family of an untouched (copied) source stream."""

    name = (codec or "").casefold()
    detail = (profile or "").upper()
    if name == "truehd" or name == "mlp":
        return "TRUEHD"
    if name in {"dts", "dca"}:
        if "DTS:X" in detail or "DTS-X" in detail:
            return "DTSX"
        if "MA" in detail and "HD" in detail:
            return "DTSHDMA"
        if "HRA" in detail or ("HD" in detail and "HR" in detail):
            return "DTSHDHRA"
        return "DTS"
    if name == "ac3":
        return "DD"
    if name == "eac3":
        return "DDP"
    if name == "flac":
        return "FLAC"
    if name.startswith("pcm"):
        return "LPCM"
    if name == "aac":
        return "AAC"
    if name == "opus":
        return "OPUS"
    return "OTHER"


def parse_release_name(name: str, encoder: str) -> ReleaseName | None:
    """Split a name that fits the grammar; ``None`` when it does not."""

    pattern = RELEASE_NAME_PATTERNS.get(encoder)
    match = pattern.fullmatch(name) if pattern else None
    if match is None:
        return None
    middle = match.group("middle")
    tokens: list[str] = []
    position = 1 if middle.startswith(".") else 0
    while position < len(middle):
        token = _TOKEN.match(middle, position)
        if token is None:
            return None
        tokens.append(token.group(0))
        position = token.end() + 1
    languages = tuple(
        item for item in match.group("languages").split(".") if item
    )
    return ReleaseName(
        title=match.group("title"),
        resolution=match.group("resolution"),
        source=match.group("source"),
        tokens=tuple(tokens),
        codec=match.group("codec"),
        languages=languages,
        group=match.group("group"),
    )


def _audio_claims(tokens: Iterable[str]) -> list[tuple[str, int | None, str]]:
    """``(codec family, channel count or None, original text)`` per audio tag."""

    claims: list[tuple[str, int | None, str]] = []
    for text in tokens:
        token = _TOKEN.fullmatch(text)
        if token is None:
            continue
        if token.group("audio"):
            codec_text = token.group("audio")
            family = next(
                family for pattern, family in _AUDIO_CODECS if pattern.fullmatch(codec_text)
            )
            layout = token.group("audio_channels")
            claims.append((family, channel_count(layout) if layout else None, text))
        elif token.group("channels") and claims and claims[-1][1] is None:
            family, _channels, original = claims[-1]
            claims[-1] = (family, channel_count(token.group("channels")), f"{original}.{text}")
    return claims


def _codec_satisfies(claimed: str, actual: str) -> bool:
    # DTS:X rides on a DTS-HD MA stream; either name describes it.
    return claimed == actual or (claimed == "DTSHDMA" and actual == "DTSX")


def release_name_problems(name: str, facts: ReleaseFacts) -> list[str]:
    """Every reason the name is not a truthful encode name for ``facts``."""

    example = EXAMPLE_NAMES.get(facts.encoder, EXAMPLE_NAMES["x265"])
    parsed = parse_release_name(name, facts.encoder) if "_" not in name else None
    if parsed is None:
        return [f"output_name must be a clean encode name such as {example}"]
    compact = re.sub(r"[^A-Z0-9]+", "", name.upper())
    problems: list[str] = []
    if any(tag in compact for tag in _SOURCE_DISC_TAGS):
        problems.append(
            "output_name contains a source-disc/source-codec tag; remove inherited release metadata"
        )
    if _INHERITED.search(parsed.title):
        problems.append(
            "output_name carries codec or remux tags before the resolution; remove inherited release metadata"
        )

    tokens = {item.casefold() for item in parsed.tokens}
    audio = [item for item in facts.audio]
    for family, channels, text in _audio_claims(parsed.tokens):
        candidates = [item for item in audio if _codec_satisfies(family, item.codec)]
        if not candidates:
            problems.append(
                f"output_name advertises {AUDIO_CODEC_LABELS.get(family, family)} audio ({text}) "
                "that is not present in the retained output plan"
            )
        elif channels is not None and not any(item.channels == channels for item in candidates):
            problems.append(
                f"output_name advertises {text} but no retained "
                f"{AUDIO_CODEC_LABELS.get(family, family)} track has {channel_layout(channels) or channels} channels"
            )
    if "atmos" in tokens and not any(item.atmos for item in audio):
        problems.append("output_name advertises Atmos but no retained track keeps the Atmos objects")

    dynamic = facts.dynamic_range
    for claimed, needed, label in (
        (("dv", "dovi", "dolby.vision"), "DV", "Dolby Vision"),
        (("hdr10plus", "hdr10+", "hdr10p"), "HDR10+", "HDR10+"),
        (("hdr", "hdr10"), "HDR", "HDR"),
        (("hlg",), "HLG", "HLG"),
        (("sdr",), "SDR", "SDR"),
    ):
        if tokens & set(claimed) and needed not in dynamic:
            problems.append(f"output_name advertises {label} but the planned video is not {label}")

    spoken = [item for item in audio if not item.commentary]
    languages = {item.language for item in spoken if item.language != "und"}
    if "multi" in tokens and len(languages) < 2:
        problems.append(
            "output_name says MULTi but the retained audio plan has fewer than two languages"
        )
    if "dual-audio" in tokens and (len(languages) < 2 or "en" not in languages):
        problems.append(
            "output_name says Dual-Audio but the retained audio is not an original track plus an English dub"
        )
    for tag in parsed.languages:
        count_text, _, code = tag.rpartition("x") if re.match(r"^[1-9]x", tag, re.I) else ("", "", tag)
        iso = normalize_iso639_2(code)
        bcp47 = (iso639_2_to_bcp47(iso) if iso else None) or ""
        if not bcp47:
            problems.append(f"output_name has an unknown language tag: {tag}")
            continue
        wanted = int(count_text) if count_text else 1
        present = sum(1 for item in spoken if item.language == bcp47.split("-")[0].casefold())
        if present < wanted:
            problems.append(
                f"output_name advertises {tag} but the retained audio has "
                f"{present} {code.upper()} track(s)"
            )
    return problems


__all__ = [
    "AUDIO_CODEC_LABELS",
    "AudioOutput",
    "EXAMPLE_NAMES",
    "RELEASE_NAME_PATTERNS",
    "ReleaseFacts",
    "ReleaseName",
    "audio_codec_family",
    "channel_count",
    "channel_layout",
    "parse_release_name",
    "release_name_problems",
]
