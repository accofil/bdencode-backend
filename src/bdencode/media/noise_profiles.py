"""Named grain/noise presets expressed as concrete encoder settings.

A preset is only a convenience for the operator: it expands to ordinary
``EncoderSettings`` field values, so the selection, the manifest and the FFmpeg
command always describe the exact numbers that were used.  Nothing here touches
the reference picture; noise handling is performed by the encoder itself, which
keeps the SSIM/PSNR/VMAF evidence a statement about the codec rather than about
a pre-filter.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping

from ..i18n import t
from .profiles import EncoderSettings, VideoEncoder, recommended_profile


@dataclass(frozen=True, slots=True)
class NoiseProfile:
    id: str
    label: tuple[str, str]  # (hungarian, english)
    description: tuple[str, str]  # (hungarian, english)
    settings: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """The preset for the API, its texts in the request's language."""

        return {
            "id": self.id,
            "label": t(*self.label),
            "description": t(*self.description),
            "settings": dict(self.settings),
        }


_X264: tuple[NoiseProfile, ...] = (
    NoiseProfile(
        "off",
        ("Nincs", "None"),
        (
            "A forrás zaját és szemcséjét az alapértelmezett profil kezeli.",
            "The default profile handles the source's noise and grain.",
        ),
        {},
    ),
    NoiseProfile(
        "preserve_grain",
        ("Szemcse megtartása", "Preserve grain"),
        (
            "Filmszemcsés forráshoz: grain tune, magasabb qcomp és enyhébb deblock, "
            "hogy a szemcse ne simuljon el. Nagyobb fájlméretre számíts.",
            "For film-grain sources: grain tune, higher qcomp and softer deblock "
            "so the grain is not smoothed away. Expect a larger file.",
        ),
        {
            "tune": "grain",
            "qcomp": 0.75,
            "aq_strength": 0.65,
            "deblock_alpha": -2,
            "deblock_beta": -2,
            "psy_rdoq": 0.15,
            "noise_reduction": 0,
        },
    ),
    NoiseProfile(
        "light_denoise",
        ("Enyhe zajszűrés", "Light denoise"),
        (
            "Kódolóba épített zajcsökkentés (nr 40): a finom digitális zajt "
            "csökkenti, a részleteket érintetlenül hagyja.",
            "Encoder-built-in noise reduction (nr 40): reduces fine digital noise "
            "and leaves detail untouched.",
        ),
        {"noise_reduction": 40},
    ),
    NoiseProfile(
        "medium_denoise",
        ("Közepes zajszűrés", "Medium denoise"),
        (
            "Kódolóba épített zajcsökkentés (nr 120): látható zajos vagy szemcsés "
            "forráshoz, mérhető bitrate-megtakarítással.",
            "Encoder-built-in noise reduction (nr 120): for visibly noisy or grainy "
            "sources, with a measurable bitrate saving.",
        ),
        {"noise_reduction": 120},
    ),
    NoiseProfile(
        "strong_denoise",
        ("Erős zajszűrés", "Strong denoise"),
        (
            "Kódolóba épített zajcsökkentés (nr 300): nagyon zajos forráshoz. "
            "Részletvesztést okozhat, a QC-kapuk ezt jelzik.",
            "Encoder-built-in noise reduction (nr 300): for very noisy sources. "
            "It can cost detail; the QC gates report it.",
        ),
        {"noise_reduction": 300},
    ),
)

_X265: tuple[NoiseProfile, ...] = (
    _X264[0],
    NoiseProfile(
        "preserve_grain",
        ("Szemcse megtartása", "Preserve grain"),
        (
            "Filmszemcsés UHD forráshoz: grain tune, magasabb psy-rd/psy-rdoq, "
            "kikapcsolt SAO és enyhébb deblock. Nagyobb fájlméretre számíts.",
            "For film-grain UHD sources: grain tune, higher psy-rd/psy-rdoq, "
            "SAO off and softer deblock. Expect a larger file.",
        ),
        {
            "tune": "grain",
            "psy_rd": 2.5,
            "psy_rdoq": 3.0,
            "qcomp": 0.75,
            "aq_strength": 0.8,
            "deblock_alpha": -2,
            "deblock_beta": -2,
            "sao": False,
            "noise_reduction": 0,
        },
    ),
    NoiseProfile(
        "light_denoise",
        ("Enyhe zajszűrés", "Light denoise"),
        (
            "Kódolóba épített zajcsökkentés (nr-intra/nr-inter 100): a finom "
            "digitális zajt csökkenti.",
            "Encoder-built-in noise reduction (nr-intra/nr-inter 100): reduces "
            "fine digital noise.",
        ),
        {"noise_reduction": 100},
    ),
    NoiseProfile(
        "medium_denoise",
        ("Közepes zajszűrés", "Medium denoise"),
        (
            "Kódolóba épített zajcsökkentés (nr-intra/nr-inter 250): látható zajos "
            "vagy szemcsés forráshoz.",
            "Encoder-built-in noise reduction (nr-intra/nr-inter 250): for visibly "
            "noisy or grainy sources.",
        ),
        {"noise_reduction": 250},
    ),
    NoiseProfile(
        "strong_denoise",
        ("Erős zajszűrés", "Strong denoise"),
        (
            "Kódolóba épített zajcsökkentés (nr-intra/nr-inter 500): nagyon zajos "
            "forráshoz. Részletvesztést okozhat, a QC-kapuk ezt jelzik.",
            "Encoder-built-in noise reduction (nr-intra/nr-inter 500): for very "
            "noisy sources. It can cost detail; the QC gates report it.",
        ),
        {"noise_reduction": 500},
    ),
)


def noise_profiles(encoder: VideoEncoder | str) -> tuple[NoiseProfile, ...]:
    return _X264 if VideoEncoder(encoder) is VideoEncoder.X264 else _X265


def noise_profile(encoder: VideoEncoder | str, profile_id: str) -> NoiseProfile:
    for item in noise_profiles(encoder):
        if item.id == profile_id:
            return item
    raise ValueError(f"unknown noise profile: {profile_id}")


def preset_settings(
    encoder: VideoEncoder | str,
    profile_id: str,
    *,
    content_type: str = "film",
) -> dict[str, Any]:
    """Return concrete values for every field the preset family manages.

    Presets are mutually exclusive choices.  Each result therefore starts from
    the encoder's recommended defaults for ``content_type`` and only then
    applies the preset, so switching from a grain preset to a denoise preset
    cannot leave a grain ``qcomp`` behind.
    """

    encoder = VideoEncoder(encoder)
    preset = noise_profile(encoder, profile_id)
    baseline = recommended_profile(encoder, content_type=content_type)
    managed = sorted({key for item in noise_profiles(encoder) for key in item.settings})
    values: dict[str, Any] = {}
    for key in managed:
        current = getattr(baseline, key)
        values[key] = getattr(current, "value", current)
    values.update(preset.settings)
    return values


def apply_noise_profile(
    settings: EncoderSettings, profile_id: str, *, content_type: str = "film"
) -> EncoderSettings:
    """Return ``settings`` with the preset applied; other fields are untouched."""

    return replace(
        settings,
        **preset_settings(settings.encoder, profile_id, content_type=content_type),
    )
