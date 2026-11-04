"""Tracker-ready BBCode: Aither's comparison block and nCore's description parts.

Aither's Video Comparisons Guide asks for at least ten source/encode pairs of
the same frame type (B-frames preferred, P acceptable, I-frames avoided) in a
``[comparison=Source, Encode]`` block with space-separated PNG URLs; frame-info
labels on comps are normal.  Its screenshot rules ask for 3–9 *clean* PNGs at
the MediaInfo resolution, full-linked with ``[img=350]`` inside ``[center]``;
personal encodes also need the x264/x265 log.  nCore wants exactly three
screenshots at the encode's resolution (``[imgw]`` above 640×480) and, for a
quality trump, comparison links under the usual centred header.

Comparisons use the uploaded labelled pairs; screenshots use the clean frames
the comparison stage copies for tracker jobs.  HDR titles use their SDR views,
which browsers show correctly.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Sequence

COMPARISON_MINIMUM = 10
# Only this many of the measured pairs are uploaded and published: enough for
# a convincing comparison (Aither asks for ten) without flooding the host.
PUBLISHED_PAIR_COUNT = 10
COMPARISON_MAXIMUM = PUBLISHED_PAIR_COUNT
SCREENSHOT_COUNTS = {"aither": 6, "ncore": 3}

# x264/x265 log lines worth publishing: the encoder's own [info]/[warning]
# lines (settings at the start, frame statistics at the end) and the summary.
_ENCODER_LINE = re.compile(
    r"^(?:x26[45] \[(?:info|warning)\]: .*"
    r"|\[libx26[45] @ [^\]]+\] .*"
    r"|encoded \d+ frames in .*)$"
)
_LIBX_PREFIX = re.compile(r"^\[(libx26[45]) @ [^\]]+\] ")


def _presentation(item: Mapping[str, Any]) -> int:
    return int(item.get("presentation_index") or 0)


def published_pairs(
    pairs: Sequence[Mapping[str, Any]], count: int = PUBLISHED_PAIR_COUNT
) -> list[Mapping[str, Any]]:
    """The pairs whose pictures are uploaded, in time order.

    B pairs first, then P, I-frames only when the others run out; each kind
    spread over the runtime.
    """

    ordered = sorted(pairs, key=_presentation)
    chosen: list[Mapping[str, Any]] = []
    for category in ("B", "P", "I"):
        missing = count - len(chosen)
        if missing <= 0:
            break
        chosen += _spread([item for item in ordered if item.get("category") == category], missing)
    return sorted(chosen, key=_presentation)


def comparison_pairs(pairs: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """The published B and P pairs (never I-frames), in time order."""

    return [item for item in published_pairs(pairs) if item.get("category") in {"B", "P"}]


def _spread(items: Sequence[Any], count: int) -> list[Any]:
    if count <= 0:
        return []
    if len(items) <= count:
        return list(items)
    step = (len(items) - 1) / (count - 1) if count > 1 else 0
    return [items[round(index * step)] for index in range(count)]


def screenshot_pair_numbers(categories: Sequence[str], profile: str) -> set[int]:
    """1-based pair numbers whose clean encode frame becomes a screenshot.

    B pairs spread over the runtime (P pairs only when B pairs run out); none
    without a tracker profile.
    """

    wanted = SCREENSHOT_COUNTS.get(profile, 0)
    if not wanted:
        return set()
    numbered = list(enumerate(categories, start=1))
    b_pairs = [number for number, category in numbered if category == "B"]
    p_pairs = [number for number, category in numbered if category == "P"]
    chosen = _spread(b_pairs, wanted)
    if len(chosen) < wanted:
        chosen += _spread(p_pairs, wanted - len(chosen))
    return set(chosen)


def encoder_summary(log_text: str) -> str:
    """The encoder's settings and statistics lines from an FFmpeg encode log."""

    lines = []
    for raw in log_text.splitlines():
        line = raw.strip()
        if _ENCODER_LINE.match(line):
            lines.append(_LIBX_PREFIX.sub(lambda match: f"{match.group(1)}: ", line))
    return "\n".join(lines)


def _image(
    pair: Mapping[str, Any], role: str, uploaded: Mapping[str, Mapping[str, Any]]
) -> Mapping[str, Any] | None:
    # SDR view first: a tone-mapped HDR picture is what a browser can show.
    for key in (f"{role}_sdr_png", f"{role}_png"):
        name = pair.get(key)
        if isinstance(name, str) and name in uploaded:
            return uploaded[name]
    return None


def _timestamp(value: Any) -> str:
    try:
        seconds = int(Decimal(str(value)))
    except (InvalidOperation, ValueError):
        return "?"
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def _complete(
    pairs: Sequence[Mapping[str, Any]], uploaded: Mapping[str, Mapping[str, Any]]
) -> list[tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]]]:
    rows = []
    for pair in comparison_pairs(pairs):
        reference = _image(pair, "reference", uploaded)
        encode = _image(pair, "encode", uploaded)
        if reference is not None and encode is not None:
            rows.append((pair, reference, encode))
    return rows


def _screenshots(
    pairs: Sequence[Mapping[str, Any]], uploaded: Mapping[str, Mapping[str, Any]]
) -> list[Mapping[str, Any]]:
    ordered = sorted(pairs, key=lambda item: int(item.get("presentation_index") or 0))
    return [
        uploaded[name]
        for pair in ordered
        if isinstance(name := pair.get("screenshot_png"), str) and name in uploaded
    ]


GALLERY_WIDTH = 400
_SPECTRUM = re.compile(r"^audio-(\d+)-(source|encode)-spectrum\.png$")


def _thumbnail(item: Mapping[str, Any], width: int) -> str:
    """A ``width``-pixel picture linked to the host's full-size view."""

    image = item.get("image_url")
    viewer = item.get("viewer_url") or image
    if not isinstance(image, str) or not image:
        return str(item.get("bbcode", ""))
    return f"[url={viewer}][img={width}]{image}[/img][/url]"


def gallery_bbcode(
    pairs: Sequence[Mapping[str, Any]],
    uploaded: Mapping[str, Mapping[str, Any]],
    *,
    width: int = GALLERY_WIDTH,
) -> list[str]:
    """Every uploaded picture at ``width`` pixels, each linked to its full size.

    The source/encode pairs side by side in time order (instead of one
    full-size picture per line by file name, which put every encode before
    its source), then the clean screenshots and the audio spectra.
    """

    lines: list[str] = []
    shown: set[str] = set()
    rows = []
    for pair in published_pairs(pairs):
        reference = _image(pair, "reference", uploaded)
        encode = _image(pair, "encode", uploaded)
        if reference is not None and encode is not None:
            rows.append((pair, reference, encode))
    if rows:
        lines.extend(("", "[center][b]Source | Encode[/b]"))
        for number, (pair, reference, encode) in enumerate(rows, start=1):
            lines.extend(
                (
                    "",
                    f"{number:02d} · {pair.get('category')}-frame · "
                    f"{_timestamp(pair.get('encoded_pts_seconds'))}",
                    f"{_thumbnail(reference, width)} {_thumbnail(encode, width)}",
                )
            )
        lines.append("[/center]")
        for _pair, reference, encode in rows:
            shown.update((str(reference.get("image_url")), str(encode.get("image_url"))))
    screenshots = [
        item for item in _screenshots(pairs, uploaded) if item.get("image_url") not in shown
    ]
    if screenshots:
        lines.extend(("", "[center][b]Screenshots[/b]"))
        lines.append(" ".join(_thumbnail(item, width) for item in screenshots))
        lines.append("[/center]")
        shown.update(str(item.get("image_url")) for item in screenshots)
    spectra: dict[str, dict[str, Mapping[str, Any]]] = {}
    for name, item in uploaded.items():
        match = _SPECTRUM.match(name)
        if match:
            spectra.setdefault(match.group(1), {})[match.group(2)] = item
    if spectra:
        lines.extend(("", "[center][b]Audio spectrum: Source | Encode[/b]"))
        for track in sorted(spectra):
            row = [spectra[track][role] for role in ("source", "encode") if role in spectra[track]]
            lines.append(" ".join(_thumbnail(item, width) for item in row))
            shown.update(str(item.get("image_url")) for item in row)
        lines.append("[/center]")
    rest = [
        uploaded[name] for name in sorted(uploaded) if uploaded[name].get("image_url") not in shown
    ]
    if rest:
        lines.append("")
        lines.extend(_thumbnail(item, width) for item in rest)
    return lines


def aither_comparison_bbcode(
    pairs: Sequence[Mapping[str, Any]],
    uploaded: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    """Aither's interactive comparison: one ``[comparison=Source, Encode]``
    block of full-size source/encode URLs (B and P pairs, time order)."""

    rows = _complete(pairs, uploaded)
    if not rows:
        return []
    urls = " ".join(
        f"{reference['image_url']} {encode['image_url']}" for _pair, reference, encode in rows
    )
    lines = [f"[comparison=Source, Encode]{urls}[/comparison]"]
    if len(rows) < COMPARISON_MINIMUM:
        lines.append(
            f"[i]Only {len(rows)} B/P pairs were uploaded; Aither asks for at least "
            f"{COMPARISON_MINIMUM}.[/i]"
        )
    return lines


def aither_bbcode(
    pairs: Sequence[Mapping[str, Any]],
    uploaded: Mapping[str, Mapping[str, Any]],
    *,
    encoder_log: str = "",
    codec: str = "x265",
) -> list[str]:
    rows = _complete(pairs, uploaded)
    lines: list[str] = []
    screenshots = _screenshots(pairs, uploaded)
    if screenshots:
        lines.extend(("", "[b]Aither — screenshots[/b]", "[center]"))
        lines.extend(
            f"[url={item['viewer_url']}][img=350]{item['image_url']}[/img][/url]"
            for item in screenshots
        )
        lines.append("[/center]")
    if rows:
        lines.extend(("", "[b]Aither — comparison (same frame type, B preferred)[/b]"))
        lines.extend(aither_comparison_bbcode(pairs, uploaded))
    if encoder_log:
        lines.extend(("", f"[spoiler={codec} log][code]", encoder_log, "[/code][/spoiler]"))
    return lines


def ncore_bbcode(
    pairs: Sequence[Mapping[str, Any]], uploaded: Mapping[str, Mapping[str, Any]]
) -> list[str]:
    rows = _complete(pairs, uploaded)
    lines: list[str] = []
    screenshots = _screenshots(pairs, uploaded)
    if screenshots:
        lines.extend(("", "[b]nCore — képek (pontosan 3, az encode felbontásában)[/b]"))
        lines.extend(f"[imgw]{item['image_url']}[/imgw]" for item in screenshots)
    if rows:
        lines.extend(
            (
                "",
                "[b]nCore — összehasonlítás (cseréhez)[/b]",
                "[center][size=12pt][highlight]Forrás vs. Encode[/highlight][/size]",
                "",
            )
        )
        for number, (pair, reference, encode) in enumerate(rows, start=1):
            lines.append(
                f"[url={reference['viewer_url']}]Forrás {number:02d}[/url] · "
                f"[url={encode['viewer_url']}]Encode {number:02d}[/url] "
                f"({pair.get('category')}-frame, {_timestamp(pair.get('encoded_pts_seconds'))})"
            )
        lines.append("[/center]")
    return lines


def remux_bbcode(
    output_name: str,
    screenshots: Sequence[Mapping[str, Any]],
    uploaded: Mapping[str, Mapping[str, Any]],
    *,
    provider: str | None,
    profile: str,
    eac3to_log: str,
    notes: Sequence[str] = (),
    width: int = GALLERY_WIDTH,
    kind: str = "remux",
) -> list[str]:
    """A remux's description: screenshots and the eac3to log.

    Aither: 3 or more screenshots via BBCode, and a personal remux "must
    contain eac3to logs for all source discs".  nCore takes its pictures as
    ``[imgw]``.  ``notes`` are eac3to's warnings, shown above the log.
    """

    lines = [f"[b]{output_name} — {kind}[/b]"]
    if uploaded and provider:
        lines.append(f"[i]Image host: {provider}[/i]")
    pictures = [
        uploaded[item["png"]]
        for item in screenshots
        if isinstance(item.get("png"), str) and item["png"] in uploaded
    ]
    if pictures:
        if profile == "ncore":
            lines.extend(("", "[b]nCore — képek[/b]"))
            lines.extend(
                f"[imgw]{item['image_url']}[/imgw]" for item in pictures if item.get("image_url")
            )
        else:
            lines.extend(("", "[center][b]Screenshots[/b]"))
            lines.extend(_thumbnail(item, width) for item in pictures)
            lines.append("[/center]")
    else:
        lines.append("[i]Image upload was disabled; see the lossless PNG sidecars.[/i]")
    if notes:
        lines.extend(("", "[b]eac3to notes[/b]", *(f"• {note}" for note in notes)))
    if eac3to_log.strip():
        lines.extend(
            ("", "[spoiler=eac3to log][code]", eac3to_log.rstrip("\n"), "[/code][/spoiler]")
        )
    return lines


def tracker_bbcode(
    profile: str,
    pairs: Sequence[Mapping[str, Any]],
    uploaded: Mapping[str, Mapping[str, Any]],
    *,
    encoder_log: str = "",
    codec: str = "x265",
) -> list[str]:
    if profile == "aither":
        return aither_bbcode(pairs, uploaded, encoder_log=encoder_log, codec=codec)
    if profile == "ncore":
        return ncore_bbcode(pairs, uploaded)
    return []


__all__ = [
    "COMPARISON_MAXIMUM",
    "COMPARISON_MINIMUM",
    "GALLERY_WIDTH",
    "aither_comparison_bbcode",
    "gallery_bbcode",
    "PUBLISHED_PAIR_COUNT",
    "SCREENSHOT_COUNTS",
    "aither_bbcode",
    "comparison_pairs",
    "encoder_summary",
    "ncore_bbcode",
    "published_pairs",
    "remux_bbcode",
    "screenshot_pair_numbers",
    "tracker_bbcode",
]
