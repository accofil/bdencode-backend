"""An evaluation of a finished encode from its own measurements.

The comparison stage measures a lot (sampled SSIM/PSNR per I/P/B pair, sampled
VMAF windows of the final file, sizes, the encoder's own statistics, audio
checks); this module turns those numbers into a verdict, findings and
suggested setting changes for the next encode of a similar disc.

Two sources produce the same document shape:

* ``deterministic``: fixed, documented thresholds (``THRESHOLDS``) and rules;
  always available, no network.
* an AI provider (OpenAI or Claude) when its key is set: it receives only the
  measured facts (no pictures, no paths) and answers in a strict schema.  Its
  suggestions are checked against ``SUGGESTION_BOUNDS`` like any operator
  input; on any failure the deterministic evaluation stands.

Texts are stored in both interface languages (``{"hu": ..., "en": ...}``).
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Mapping

SCHEMA_VERSION = 1
EVALUATION_NAME = "comparison-evaluation.json"

# The deterministic evaluation's fixed variables.  VMAF figures are the
# sampled windows of the final file (vmaf_v0.6.1, or the 4K model for UHD).
THRESHOLDS: dict[str, float] = {
    # verdict bands: (mean VMAF, 1% low VMAF)
    "transparent_vmaf_mean": 95.0,
    "transparent_vmaf_low": 90.0,
    "good_vmaf_mean": 93.0,
    "good_vmaf_low": 87.0,
    "acceptable_vmaf_mean": 90.0,
    "acceptable_vmaf_low": 83.0,
    # an encode this far above transparency spends bits it does not need
    "overkill_vmaf_mean": 95.0,
    "overkill_vmaf_low": 91.0,
    # below this saving an encode hardly beats keeping the source
    "low_saving_ratio": 0.20,
    "pointless_saving_ratio": 0.10,
    # a weak spot worth a lower CRF
    "weak_vmaf_low": 85.0,
    "weak_window_mean": 88.0,
    "weak_sample_ssim": 0.95,
    # B-frames clearly softer than P-frames
    "b_ssim_deficit": 0.01,
    # bits per pixel per frame above which a transparent 1080p x264 encode is
    # generous (grain-free film usually needs well under 0.30)
    "generous_bpp_x264": 0.30,
    "generous_bpp_x265": 0.20,
}
# Size change of one CRF step, for estimates only (x265: measured 21 % on a
# real UHD title, see crf_search.DEFAULT_SIZE_SLOPE; x264 is usually milder).
SIZE_FACTOR_PER_CRF = {"x264": 1.15, "x265": 1.21}

# Settings a suggestion may change, with the range a value must fall in.
SUGGESTION_BOUNDS: dict[str, tuple[float, float, str]] = {
    "crf": (8.0, 30.0, "float"),
    "aq_strength": (0.3, 2.0, "float"),
    "psy_rd": (0.0, 2.0, "float"),
    "psy_rdoq": (0.0, 5.0, "float"),
    "deblock_alpha": (-3.0, 3.0, "int"),
    "deblock_beta": (-3.0, 3.0, "int"),
    "bframes": (1.0, 16.0, "int"),
    "ref": (1.0, 16.0, "int"),
    "qcomp": (0.5, 0.9, "float"),
    "aq_mode": (0.0, 3.0, "int"),
}
VERDICTS = ("transparent", "good", "acceptable", "weak")


def _text(hu: str, en: str) -> dict[str, str]:
    return {"hu": hu, "en": en}


def _load(*candidates: Path) -> Any:
    for path in candidates:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
    return None


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _encoder_stats(log_text: str) -> dict[str, Any]:
    stats: dict[str, Any] = {}
    for kind, qp, size in re.findall(
        r"frame ([IPB]):\s*\d+\s+Avg QP:\s*([\d.]+)\s+size:\s*(\d+)", log_text
    ):
        stats[f"avg_qp_{kind}"] = float(qp)
        stats[f"avg_frame_bytes_{kind}"] = int(size)
    rate = re.findall(r"kb/s:\s*([\d.]+)", log_text)
    if rate:
        stats["encoder_kbps"] = float(rate[-1])
    return stats


def collect_facts(job_root: Path, completed_dir: Path | None = None) -> dict[str, Any] | None:
    """The measured facts of a finished comparison, or ``None`` without one."""

    comparison = [job_root / "comparison"]
    if completed_dir is not None:
        comparison.append(completed_dir / "comparison")
    metrics = _load(*(path / "video-metrics.json" for path in comparison))
    if not isinstance(metrics, Mapping) or not isinstance(metrics.get("samples"), list):
        return None
    plan = _load(job_root / "encode-plan.json") or {}
    decisions = plan.get("decisions") if isinstance(plan, Mapping) else {}
    decisions = decisions if isinstance(decisions, Mapping) else {}
    source_video = (decisions.get("source_video") or {}).get("video") or {}
    crop = decisions.get("crop") or {}
    encoder_settings = decisions.get("encoder") if isinstance(decisions.get("encoder"), Mapping) else {}
    encoder = str(plan.get("output_encoder") or "x264")
    width = _number(source_video.get("width"))
    height = _number(source_video.get("height"))
    if width and height:
        width -= (_number(crop.get("left")) or 0) + (_number(crop.get("right")) or 0)
        height -= (_number(crop.get("top")) or 0) + (_number(crop.get("bottom")) or 0)

    manifest = _load(*(path / "video-comparison.json" for path in comparison)) or {}
    verdict = ((manifest.get("frame_completeness") or {}).get("verdict") or {}) if isinstance(manifest, Mapping) else {}
    duration = _number(verdict.get("final_video_duration_seconds"))
    fps_num, fps_den = _number(verdict.get("fps_numerator")), _number(verdict.get("fps_denominator"))
    fps = fps_num / fps_den if fps_num and fps_den else None

    samples = []
    by_type: dict[str, list[float]] = {"I": [], "P": [], "B": []}
    for index, sample in enumerate(metrics["samples"], start=1):
        if not isinstance(sample, Mapping):
            continue
        ssim, psnr = _number(sample.get("ssim_all")), _number(sample.get("psnr_average_db"))
        kind = str(sample.get("category") or "")
        samples.append({"n": index, "type": kind, "frame": sample.get("presentation_index"), "ssim": ssim, "psnr": psnr})
        if ssim is not None and kind in by_type and ssim < 1.0:
            by_type[kind].append(ssim)
    measured = [item for item in samples if item["ssim"] is not None and item["ssim"] < 1.0]
    aggregate = metrics.get("aggregate") or {}
    weakest = min(measured, key=lambda item: item["ssim"], default=None)

    vmaf_doc = _load(*(path / "video-vmaf.json" for path in comparison)) or {}
    windows = [
        {"start_seconds": _number(item.get("start_seconds")), "mean": _number(item.get("mean"))}
        for item in (vmaf_doc.get("windows") or [])
        if isinstance(item, Mapping)
    ]
    windows = [item for item in windows if item["mean"] is not None]
    efficiency = _load(job_root / "analysis/video-efficiency.json") or {}
    eff_verdict = efficiency.get("verdict") or {} if isinstance(efficiency, Mapping) else {}
    source_bytes, encoded_bytes = _number(eff_verdict.get("source_bytes")), _number(eff_verdict.get("encoded_bytes"))
    log_path = job_root / "logs/video-encode.log"
    stats = _encoder_stats(log_path.read_text(encoding="utf-8", errors="replace")) if log_path.is_file() else {}
    video_kbps = (encoded_bytes * 8 / duration / 1000) if encoded_bytes and duration else stats.get("encoder_kbps")
    audio = _load(job_root / "analysis/audio-comparison.json") or {}
    audio_tracks = [
        {
            "stream_id": track.get("stream_id"),
            "action": track.get("action"),
            "codec": (track.get("encode") or {}).get("codec") if isinstance(track.get("encode"), Mapping) else track.get("codec"),
            "warnings": len(track.get("warnings") or []),
        }
        for track in (audio.get("tracks") or [])
        if isinstance(track, Mapping)
    ] if isinstance(audio, Mapping) else []

    facts = {
        "schema_version": SCHEMA_VERSION,
        "encoder": encoder,
        "content_kind": decisions.get("content_kind"),
        "source": {
            "codec": source_video.get("codec"),
            "width": source_video.get("width"),
            "height": source_video.get("height"),
            "bit_depth": source_video.get("bit_depth"),
            "hdr10": bool(source_video.get("hdr10")),
            "frame_rate": source_video.get("frame_rate"),
        },
        "encoded_picture": {"width": width, "height": height, "fps": fps, "duration_seconds": duration},
        "settings": {
            key: encoder_settings.get(key)
            for key in ("crf", "preset", "tune", "aq_mode", "aq_strength", "psy_rd", "psy_rdoq", "deblock_alpha",
                        "deblock_beta", "bframes", "ref", "keyint", "qcomp", "me", "subme", "trellis", "noise_reduction")
            if key in encoder_settings
        },
        "sizes": {
            "source_video_bytes": source_bytes,
            "encoded_video_bytes": encoded_bytes,
            "saving_ratio": (1 - encoded_bytes / source_bytes) if source_bytes and encoded_bytes else None,
            "video_kbps": video_kbps,
            "source_video_kbps": (source_bytes * 8 / duration / 1000) if source_bytes and duration else None,
            "bits_per_pixel": (video_kbps * 1000 / (width * height * fps)) if video_kbps and width and height and fps else None,
        },
        "metrics": {
            "ssim_mean": _number(aggregate.get("ssim_all_mean")),
            "psnr_mean_db": _number(aggregate.get("psnr_average_db_mean")),
            "ssim_mean_by_type": {kind: _mean(values) for kind, values in by_type.items()},
            "weakest_sample": weakest,
            "sample_count": len(samples),
            "gate_status": (metrics.get("quality_gate") or {}).get("status"),
            "gate_warnings": list((metrics.get("quality_gate") or {}).get("warnings") or []),
        },
        "vmaf": {
            "status": vmaf_doc.get("status"),
            "model": vmaf_doc.get("model"),
            "mean": _number(vmaf_doc.get("mean")),
            "harmonic_mean": _number(vmaf_doc.get("harmonic_mean")),
            "one_percent_low": _number(vmaf_doc.get("percentile_1")),
            "minimum": _number(vmaf_doc.get("minimum")),
            "weakest_window": min(windows, key=lambda item: item["mean"], default=None),
            "window_count": len(windows),
        },
        "encoder_stats": stats,
        "audio": audio_tracks,
    }
    return facts


def facts_digest(facts: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(facts, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _fmt(value: float | None, digits: int = 2) -> str:
    return "—" if value is None else f"{value:.{digits}f}"


def _crf_suggestion(current: float, step: float, encoder: str, reason: dict[str, str]) -> dict[str, Any]:
    factor = SIZE_FACTOR_PER_CRF.get(encoder, 1.15) ** step
    change = (1 / factor - 1) * 100
    return {
        "field": "crf",
        "current": current,
        "value": round(current + step, 1),
        "reason": reason,
        "estimated_size_change_percent": round(change),
    }


def deterministic_evaluation(facts: Mapping[str, Any]) -> dict[str, Any]:
    """The verdict, findings and suggestions from ``THRESHOLDS`` alone."""

    th = THRESHOLDS
    vmaf, metrics, sizes = facts["vmaf"], facts["metrics"], facts["sizes"]
    encoder = str(facts.get("encoder") or "x264")
    mean, low = vmaf.get("mean"), vmaf.get("one_percent_low")
    findings: list[dict[str, str]] = []
    suggestions: list[dict[str, Any]] = []

    if mean is None or low is None:
        verdict = "acceptable" if (metrics.get("ssim_mean") or 0) >= 0.97 else "weak"
        findings.append(_text("Nincs VMAF-mérés; az értékelés csak az SSIM/PSNR-mintákra épül.",
                              "No VMAF measurement; the evaluation rests on the SSIM/PSNR samples only."))
    elif mean >= th["transparent_vmaf_mean"] and low >= th["transparent_vmaf_low"]:
        verdict = "transparent"
    elif mean >= th["good_vmaf_mean"] and low >= th["good_vmaf_low"]:
        verdict = "good"
    elif mean >= th["acceptable_vmaf_mean"] and low >= th["acceptable_vmaf_low"]:
        verdict = "acceptable"
    else:
        verdict = "weak"

    if mean is not None and low is not None:
        findings.append(_text(
            f"VMAF átlag {_fmt(mean)}, 1% low {_fmt(low)}, minimum {_fmt(vmaf.get('minimum'))} ({vmaf.get('window_count')} mintaablak).",
            f"VMAF mean {_fmt(mean)}, 1% low {_fmt(low)}, minimum {_fmt(vmaf.get('minimum'))} ({vmaf.get('window_count')} sample windows).",
        ))
    findings.append(_text(
        f"SSIM átlag {_fmt(metrics.get('ssim_mean'), 4)}, PSNR átlag {_fmt(metrics.get('psnr_mean_db'), 1)} dB {metrics.get('sample_count')} képpáron.",
        f"Mean SSIM {_fmt(metrics.get('ssim_mean'), 4)}, mean PSNR {_fmt(metrics.get('psnr_mean_db'), 1)} dB over {metrics.get('sample_count')} pairs.",
    ))
    saving = sizes.get("saving_ratio")
    if saving is not None:
        findings.append(_text(
            f"A videó {saving * 100:.0f}%-kal kisebb a forrásnál ({_fmt(sizes.get('video_kbps'), 0)} kb/s a forrás {_fmt(sizes.get('source_video_kbps'), 0)} kb/s-ával szemben).",
            f"The video is {saving * 100:.0f}% smaller than the source ({_fmt(sizes.get('video_kbps'), 0)} kb/s against the source's {_fmt(sizes.get('source_video_kbps'), 0)} kb/s).",
        ))

    current_crf = _number((facts.get("settings") or {}).get("crf"))
    weak_window = vmaf.get("weakest_window") or {}
    weakest = metrics.get("weakest_sample") or {}
    weak_spot = (
        (low is not None and low < th["weak_vmaf_low"])
        or (weak_window.get("mean") is not None and weak_window["mean"] < th["weak_window_mean"])
        or (weakest.get("ssim") is not None and weakest["ssim"] < th["weak_sample_ssim"])
    )
    overkill = (
        mean is not None and low is not None
        and mean >= th["overkill_vmaf_mean"] and low >= th["overkill_vmaf_low"]
    )
    if current_crf is not None and weak_spot:
        suggestions.append(_crf_suggestion(current_crf, -1.0, encoder, _text(
            "Van gyenge pont (1% low, leggyengébb ablak vagy minta a határ alatt): eggyel alacsonyabb CRF több bitet ad a nehéz jeleneteknek.",
            "There is a weak spot (1% low, weakest window or sample under its limit): one CRF lower gives the hard scenes more bits.",
        )))
    elif current_crf is not None and overkill:
        step = 1.0 if (saving is not None and saving < th["low_saving_ratio"]) or mean >= 96.0 else 0.5
        suggestions.append(_crf_suggestion(current_crf, step, encoder, _text(
            "Az eredmény a láthatósági küszöb felett van, a többlet bit nem látszik: magasabb CRF-fel érdemben kisebb fájl lesz, átlátszó maradva.",
            "The result sits above the visibility threshold and the extra bits do not show: a higher CRF gives a clearly smaller file while staying transparent.",
        )))
    if saving is not None and saving < th["pointless_saving_ratio"]:
        findings.append(_text(
            "A kódolás alig takarít meg helyet: ennél a lemeznél a forrás megtartása (remux) is ésszerű lehet.",
            "The encode saves hardly any space: for this disc keeping the source (remux) may be just as sensible.",
        ))
    elif saving is not None and saving < th["low_saving_ratio"]:
        findings.append(_text(
            "A megtakarítás kicsi egy kódoláshoz képest.",
            "The saving is small for an encode.",
        ))
    bpp = sizes.get("bits_per_pixel")
    generous = th["generous_bpp_x265"] if encoder == "x265" else th["generous_bpp_x264"]
    if bpp is not None and verdict == "transparent" and bpp > generous:
        findings.append(_text(
            f"Bőkezű bitráta: {bpp:.3f} bit/pixel (átlátszó eredménynél {generous:.2f} felett).",
            f"Generous bitrate: {bpp:.3f} bits per pixel (above {generous:.2f} for a transparent result).",
        ))
    by_type = metrics.get("ssim_mean_by_type") or {}
    b_mean, p_mean = by_type.get("B"), by_type.get("P")
    if b_mean is not None and p_mean is not None and p_mean - b_mean > th["b_ssim_deficit"]:
        findings.append(_text(
            f"A B-képek érezhetően lágyabbak (SSIM {b_mean:.4f} a P-képek {p_mean:.4f}-ével szemben).",
            f"B-frames are noticeably softer (SSIM {b_mean:.4f} against {p_mean:.4f} for P-frames).",
        ))
        settings = facts.get("settings") or {}
        if encoder == "x264" and _number(settings.get("psy_rd")) is not None and _number(settings["psy_rd"]) < 1.1:
            suggestions.append({
                "field": "psy_rd",
                "current": _number(settings["psy_rd"]),
                "value": round(_number(settings["psy_rd"]) + 0.1, 2),
                "reason": _text("Kicsit több pszichovizuális részletmegőrzés a lágyabb B-képekhez.",
                                "A little more psycho-visual detail retention for the softer B-frames."),
            })
    if weak_window.get("mean") is not None and weak_window.get("start_seconds") is not None:
        start = int(weak_window["start_seconds"])
        findings.append(_text(
            f"Leggyengébb VMAF-ablak: {start // 3600:01d}:{start % 3600 // 60:02d}:{start % 60:02d} körül ({_fmt(weak_window['mean'])}).",
            f"Weakest VMAF window: around {start // 3600:01d}:{start % 3600 // 60:02d}:{start % 60:02d} ({_fmt(weak_window['mean'])}).",
        ))
    copies = [track for track in facts.get("audio") or [] if track.get("action") == "copy"]
    if copies and len(copies) == len(facts.get("audio") or []):
        findings.append(_text("A hangsávok bitpontos másolatok.", "The audio tracks are bit-exact copies."))

    summaries = {
        "transparent": _text("Átlátszó kódolás: szemmel nem különböztethető meg a forrástól.",
                             "Transparent encode: indistinguishable from the source by eye."),
        "good": _text("Jó kódolás: csak közelről, nehéz jeleneteknél lehet eltérés.",
                      "Good encode: differences only up close in hard scenes."),
        "acceptable": _text("Elfogadható kódolás, de látható veszteség előfordulhat.",
                            "Acceptable encode, but visible loss can occur."),
        "weak": _text("Gyenge kódolás: látható minőségvesztés várható.",
                      "Weak encode: visible quality loss is to be expected."),
    }
    if suggestions and suggestions[0]["field"] == "crf":
        crf = suggestions[0]
        summary = summaries[verdict]
        summary = _text(
            summary["hu"] + f" Javaslat hasonló lemezhez: CRF {crf['current']:g} → {crf['value']:g} (becslés: {crf['estimated_size_change_percent']:+d}% méret).",
            summary["en"] + f" Suggestion for a similar disc: CRF {crf['current']:g} → {crf['value']:g} (estimate: {crf['estimated_size_change_percent']:+d}% size).",
        )
    else:
        summary = summaries[verdict]
    return {
        "schema_version": SCHEMA_VERSION,
        "source": "deterministic",
        "model": None,
        "verdict": verdict,
        "summary": summary,
        "findings": findings,
        "suggestions": suggestions,
        "confidence": None,
        "thresholds": dict(THRESHOLDS),
    }


def validate_suggestion(field: str, value: Any) -> float | int | None:
    """A suggested value inside ``SUGGESTION_BOUNDS``, or ``None``."""

    bounds = SUGGESTION_BOUNDS.get(field)
    number = _number(value if not isinstance(value, str) else value.strip())
    if bounds is None or number is None or not bounds[0] <= number <= bounds[1]:
        return None
    if bounds[2] == "int":
        return int(round(number)) if abs(number - round(number)) < 1e-9 else None
    return round(number, 2)


AI_INSTRUCTIONS = (
    "You evaluate one finished Blu-ray video encode for a home encoder tool. "
    "You receive only measured facts: sampled SSIM/PSNR pairs by frame type, "
    "sampled VMAF windows of the final file, sizes and bitrates, the encoder's "
    "own statistics, the encoder settings and the deterministic evaluation of "
    "the tool. Judge visual transparency (VMAF mean and 1% low matter most; "
    "SSIM/PSNR samples confirm), efficiency (saving against the source, bits "
    "per pixel) and whether settings should change for the NEXT encode of a "
    "similar disc. Suggest at most four changes, only for the allowed fields "
    "and within their ranges, each with a short reason; suggest nothing if the "
    "settings are already right. Give every text in Hungarian (natural, plain) "
    "and English. Do not invent measurements."
)


def ai_output_schema() -> dict[str, Any]:
    text_pair = {
        "type": "object",
        "additionalProperties": False,
        "required": ["hu", "en"],
        "properties": {"hu": {"type": "string"}, "en": {"type": "string"}},
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["verdict", "summary", "findings", "suggestions", "confidence"],
        "properties": {
            "verdict": {"type": "string", "enum": list(VERDICTS)},
            "summary": text_pair,
            "findings": {"type": "array", "items": text_pair},
            "suggestions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["field", "value", "reason"],
                    "properties": {
                        "field": {"type": "string", "enum": sorted(SUGGESTION_BOUNDS)},
                        "value": {"type": "string"},
                        "reason": text_pair,
                    },
                },
            },
            "confidence": {"type": "number"},
        },
    }


def ai_input(facts: Mapping[str, Any], baseline: Mapping[str, Any]) -> str:
    return json.dumps(
        {
            "facts": facts,
            "deterministic_evaluation": {
                key: baseline.get(key) for key in ("verdict", "summary", "findings", "suggestions")
            },
            "allowed_fields": {
                name: {"minimum": low, "maximum": high, "type": kind}
                for name, (low, high, kind) in SUGGESTION_BOUNDS.items()
            },
        },
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )


def _pair(value: Any) -> dict[str, str] | None:
    if (
        isinstance(value, Mapping)
        and isinstance(value.get("hu"), str)
        and isinstance(value.get("en"), str)
    ):
        return {"hu": value["hu"][:1000], "en": value["en"][:1000]}
    return None


def evaluation_from_ai(
    document: Mapping[str, Any],
    facts: Mapping[str, Any],
    *,
    source: str,
    model: str | None,
) -> dict[str, Any]:
    """Check an AI answer and shape it like the deterministic document."""

    verdict = document.get("verdict")
    summary = _pair(document.get("summary"))
    confidence = _number(document.get("confidence"))
    if verdict not in VERDICTS or summary is None or confidence is None or not 0 <= confidence <= 1:
        raise ValueError("the AI evaluation has an invalid shape")
    findings = [pair for pair in (_pair(item) for item in document.get("findings") or []) if pair][:10]
    settings = facts.get("settings") or {}
    suggestions = []
    for item in (document.get("suggestions") or [])[:4]:
        if not isinstance(item, Mapping):
            continue
        field = item.get("field")
        value = validate_suggestion(str(field), item.get("value"))
        reason = _pair(item.get("reason"))
        if value is None or reason is None:
            continue
        suggestion = {"field": field, "current": settings.get(field), "value": value, "reason": reason}
        current = _number(settings.get(field))
        if field == "crf" and current is not None:
            factor = SIZE_FACTOR_PER_CRF.get(str(facts.get("encoder")), 1.15) ** (value - current)
            suggestion["estimated_size_change_percent"] = round((1 / factor - 1) * 100)
        suggestions.append(suggestion)
    return {
        "schema_version": SCHEMA_VERSION,
        "source": source,
        "model": model,
        "verdict": verdict,
        "summary": summary,
        "findings": findings,
        "suggestions": suggestions,
        "confidence": confidence,
        "thresholds": dict(THRESHOLDS),
    }


__all__ = [
    "EVALUATION_NAME",
    "SUGGESTION_BOUNDS",
    "THRESHOLDS",
    "AI_INSTRUCTIONS",
    "ai_input",
    "ai_output_schema",
    "collect_facts",
    "deterministic_evaluation",
    "evaluation_from_ai",
    "facts_digest",
    "validate_suggestion",
]
