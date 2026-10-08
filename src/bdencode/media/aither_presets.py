"""Built-in encoder presets that follow Aither encoding practice.

Each preset expands to ordinary ``EncoderSettings`` values, so the selection,
the manifest and the FFmpeg command show exactly what was used.  The values
come from encodes reviewed on the Aither forum and from the guides its
encoders point to (Silent Aperture, the x264/x265 documentation): no SAO,
-3:-3 deblock, strong psychovisual settings and no CU-tree/MB-tree for grain;
CU-tree/MB-tree, a little more AQ and softer deblock for clean digital
sources; lower psy and softer deblock for animation.  They are starting
points: a test encode of the actual source decides the final numbers.

2160p presets are x265 (Aither has no x264 UHD slot); 1080p presets target
the x264 Quality slot (larger, transparent encodes).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from ..i18n import t
from .profiles import VideoEncoder, recommended_profile


@dataclass(frozen=True, slots=True)
class AitherPreset:
    id: str
    encoder: VideoEncoder
    content: str  # grain | clean | animation
    label: tuple[str, str]  # (hungarian, english)
    description: tuple[str, str]  # (hungarian, english)
    crf_hint: tuple[str, str]  # (hungarian, english)
    settings: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """The preset for the API, its texts in the request's language."""

        return {
            "id": self.id,
            "encoder": self.encoder.value,
            "content": self.content,
            "label": t(*self.label),
            "description": t(*self.description),
            "crf_hint": t(*self.crf_hint),
            "settings": dict(self.settings),
        }


_X265_COMMON: dict[str, Any] = {
    "preset": "slow",
    "tune": "none",
    "bframes": 8,
    "b_adapt": 2,
    "b_pyramid": True,
    "ref": 4,
    "rc_lookahead": 60,
    "me": "star",
    "subme": 5,
    "merange": 57,
    "weightp": 1,
    "weightb": True,
    "sao": False,
    "limit_sao": False,
    "rect": True,
    "amp": False,
    "early_skip": False,
    "rskip": 1,
    "tu_intra_depth": 3,
    "tu_inter_depth": 3,
    "limit_tu": 0,
    "rd": 4,
    "rdoq_level": 2,
    "noise_reduction": 0,
}

_X264_COMMON: dict[str, Any] = {
    "preset": "veryslow",
    "tune": "none",
    "bframes": 16,
    "b_adapt": 2,
    "b_pyramid": True,
    "ref": 4,
    "me": "umh",
    "subme": 10,
    "merange": 32,
    "trellis": 2,
    "partitions": "all",
    "direct": "auto",
    "weightp": 2,
    "weightb": True,
    "aq_mode": 3,
    "psy_rdoq": 0.0,
    "chroma_qp_offset": -2,
    "open_gop": False,
    "fast_pskip": False,
    "dct_decimate": False,
    "noise_reduction": 0,
}

_PRESETS: tuple[AitherPreset, ...] = (
    AitherPreset(
        "aither_uhd_grain",
        VideoEncoder.X265,
        "grain",
        ("Aither UHD – szemcsés film", "Aither UHD – grainy film"),
        (
            "Filmre forgatott, szemcsés UHD-hoz: SAO és erős intra simítás ki, "
            "cutree ki, psy-rd 2,0 / psy-rdoq 1,0, deblock -3:-3, aq-mode 2. "
            "A szemcse megmarad, de a fájl nagyobb és a kódolás lassabb.",
            "For grainy UHD shot on film: SAO and strong intra smoothing off, "
            "cutree off, psy-rd 2.0 / psy-rdoq 1.0, deblock -3:-3, aq-mode 2. "
            "The grain is kept, but the file is larger and the encode slower.",
        ),
        (
            "CRF 16–18; méretcéllal a remux 40–80%-a.",
            "CRF 16–18; with a size target, 40–80% of the remux.",
        ),
        {
            **_X265_COMMON,
            "crf": 17.0,
            "aq_mode": 2,
            "aq_strength": 0.8,
            "qcomp": 0.6,
            "psy_rd": 2.0,
            "psy_rdoq": 1.0,
            "deblock_alpha": -3,
            "deblock_beta": -3,
            "strong_intra_smoothing": False,
            "cutree": False,
        },
    ),
    AitherPreset(
        "aither_uhd_clean",
        VideoEncoder.X265,
        "clean",
        ("Aither UHD – tiszta, digitális film", "Aither UHD – clean, digital film"),
        (
            "Modern, kevéssé zajos UHD-hoz: cutree be, aq-mode 3 0,9-es "
            "erősséggel a sávosodás ellen, psy-rd 1,5 / psy-rdoq 0,8, deblock -2:-2, "
            "SAO ki.",
            "For modern, low-noise UHD: cutree on, aq-mode 3 at strength 0.9 "
            "against banding, psy-rd 1.5 / psy-rdoq 0.8, deblock -2:-2, SAO off.",
        ),
        (
            "CRF 18–20; méretcéllal a remux 30–50%-a.",
            "CRF 18–20; with a size target, 30–50% of the remux.",
        ),
        {
            **_X265_COMMON,
            "crf": 18.5,
            "aq_mode": 3,
            "aq_strength": 0.9,
            "qcomp": 0.65,
            "psy_rd": 1.5,
            "psy_rdoq": 0.8,
            "deblock_alpha": -2,
            "deblock_beta": -2,
            "strong_intra_smoothing": True,
            "cutree": True,
        },
    ),
    AitherPreset(
        "aither_uhd_animation",
        VideoEncoder.X265,
        "animation",
        ("Aither UHD – animáció", "Aither UHD – animation"),
        (
            "Animációhoz: alacsonyabb psy (kontúrok gyűrődése ellen), deblock "
            "-1:-1, aq-mode 3 0,7-es erősséggel, 16 B-frame, cutree be.",
            "For animation: lower psy (against rippling line art), deblock "
            "-1:-1, aq-mode 3 at strength 0.7, 16 B-frames, cutree on.",
        ),
        ("CRF 17–19.", "CRF 17–19."),
        {
            **_X265_COMMON,
            "crf": 18.0,
            "bframes": 16,
            "aq_mode": 3,
            "aq_strength": 0.7,
            "qcomp": 0.65,
            "psy_rd": 1.0,
            "psy_rdoq": 0.5,
            "deblock_alpha": -1,
            "deblock_beta": -1,
            "strong_intra_smoothing": True,
            "cutree": True,
            "tu_intra_depth": 2,
            "tu_inter_depth": 2,
        },
    ),
    AitherPreset(
        "aither_bd_quality_grain",
        VideoEncoder.X264,
        "grain",
        ("Aither 1080p Quality – szemcsés film", "Aither 1080p Quality – grainy film"),
        (
            "Az Aither Quality slotjába: veryslow, mbtree ki (qcomp 0,6), "
            "deblock -3:-3, aq-mode 3 0,8, psy-rd 1,0:0, 16 B-frame, ref 4, "
            "no-fast-pskip, no-dct-decimate, zárt GOP.",
            "For Aither's Quality slot: veryslow, mbtree off (qcomp 0.6), "
            "deblock -3:-3, aq-mode 3 0.8, psy-rd 1.0:0, 16 B-frames, ref 4, "
            "no-fast-pskip, no-dct-decimate, closed GOP.",
        ),
        (
            "CRF 15–17; jellemzően a remux 45–60%-a.",
            "CRF 15–17; typically 45–60% of the remux.",
        ),
        {
            **_X264_COMMON,
            "crf": 16.5,
            "rc_lookahead": 60,
            "aq_strength": 0.8,
            "qcomp": 0.6,
            "psy_rd": 1.0,
            "deblock_alpha": -3,
            "deblock_beta": -3,
            "mbtree": False,
        },
    ),
    AitherPreset(
        "aither_bd_quality_clean",
        VideoEncoder.X264,
        "clean",
        ("Aither 1080p Quality – tiszta film", "Aither 1080p Quality – clean film"),
        (
            "Tiszta, digitális 1080p-hez: mbtree be (qcomp 0,75, előretekintés "
            "250), deblock -2:-2, aq-mode 3 0,8, psy-rd 1,0:0, 16 B-frame.",
            "For clean, digital 1080p: mbtree on (qcomp 0.75, lookahead "
            "250), deblock -2:-2, aq-mode 3 0.8, psy-rd 1.0:0, 16 B-frames.",
        ),
        ("CRF 16–18.", "CRF 16–18."),
        {
            **_X264_COMMON,
            "crf": 17.0,
            "rc_lookahead": 250,
            "aq_strength": 0.8,
            "qcomp": 0.75,
            "psy_rd": 1.0,
            "deblock_alpha": -2,
            "deblock_beta": -2,
            "mbtree": True,
        },
    ),
    AitherPreset(
        "aither_bd_quality_animation",
        VideoEncoder.X264,
        "animation",
        ("Aither 1080p Quality – animáció", "Aither 1080p Quality – animation"),
        (
            "Animációhoz: mbtree be (qcomp 0,75), psy-rd 0,8:0, aq-mode 3 0,65, "
            "deblock -1:-1, 16 B-frame.",
            "For animation: mbtree on (qcomp 0.75), psy-rd 0.8:0, aq-mode 3 0.65, "
            "deblock -1:-1, 16 B-frames.",
        ),
        ("CRF 15–17.", "CRF 15–17."),
        {
            **_X264_COMMON,
            "crf": 16.0,
            "rc_lookahead": 250,
            "aq_strength": 0.65,
            "qcomp": 0.75,
            "psy_rd": 0.8,
            "deblock_alpha": -1,
            "deblock_beta": -1,
            "mbtree": True,
        },
    ),
)


def aither_presets(encoder: VideoEncoder | str) -> tuple[AitherPreset, ...]:
    wanted = VideoEncoder(encoder)
    return tuple(item for item in _PRESETS if item.encoder is wanted)


def aither_preset(encoder: VideoEncoder | str, preset_id: str) -> AitherPreset:
    for item in aither_presets(encoder):
        if item.id == preset_id:
            return item
    raise ValueError(f"unknown Aither preset: {preset_id}")


def aither_preset_settings(
    encoder: VideoEncoder | str,
    preset_id: str,
    *,
    content_type: str = "film",
) -> dict[str, Any]:
    """Concrete values for every field any preset of this encoder manages.

    Presets are mutually exclusive: fields another preset sets but this one
    does not fall back to the recommended defaults, so switching presets
    leaves nothing behind.  Optional tools fall back to ``None`` (the
    encoder preset's own value).
    """

    encoder = VideoEncoder(encoder)
    preset = aither_preset(encoder, preset_id)
    baseline = recommended_profile(encoder, content_type=content_type)
    managed = sorted({key for item in aither_presets(encoder) for key in item.settings})
    values: dict[str, Any] = {}
    for key in managed:
        current = getattr(baseline, key)
        values[key] = getattr(current, "value", current)
    values.update(preset.settings)
    # The result must be a valid profile; fail here rather than in a job.
    recommended_profile(encoder, detail_level="pro", content_type=content_type, overrides=values)
    return values
