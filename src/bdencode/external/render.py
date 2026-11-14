"""Building a track of the title's length from an external track and the frame map.

The whole track is first brought to the title's speed in one pass, so that one
map frame is an exact number of samples: 25 fps to 24000/1001 is 2002 samples at
48 kHz.  The pieces are then laid on the title's timeline, by sample number.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any, Mapping, Sequence

SAMPLE_RATE = 48_000
# Short enough not to be heard as a fade, long enough to prevent a click.
FADE_SAMPLES = 240
# Where a part the source lacks is filled from the title's own sound, the two
# cross over this long (25 ms): the music of two mixes meets without a click.
FILL_CROSSFADE_SAMPLES = 1_200
# The fill's level is matched on this much sound on both sides of each gap.
FILL_LEVEL_WINDOW_SAMPLES = 2 * SAMPLE_RATE
# Quieter than this (mean square, about -70 dBFS) gives no usable level.
FILL_LEVEL_FLOOR = 1e-7
FILL_GAIN_LIMITS = (0.25, 4.0)  # +-12 dB
# FFmpeg's AC-3 encoder delays the sound by this many samples.
AC3_PRIMING_SAMPLES = 256

PITCH_RESTORE = "restore"
PITCH_KEEP = "keep"

_LOSSY_CODECS = {"ac3", "eac3", "dts", "mp2", "mp3", "aac"}


class RenderError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Piece:
    """Output samples ``[start, end)`` come from stretched samples from ``source``."""

    start: int
    end: int
    source: int


def speed_ratio(mode: str, donor_fps: Fraction, target_fps: Fraction) -> Fraction:
    """How many times longer the track must become to run with the title."""

    return donor_fps / target_fps if mode == "frame-locked" else Fraction(1)


def stretch_filter(ratio: Fraction, pitch: str, source_rate: int) -> str | None:
    """The filter that gives the track the title's speed, ending at 48 kHz.

    ``restore`` plays the same samples slower, which undoes a PAL speed-up
    exactly: the rational resampling leaves no drift.  ``keep`` changes the tempo
    only, for a track whose pitch is already right.
    """

    parts: list[str] = []
    if ratio != 1:
        if pitch == PITCH_RESTORE:
            stretched = Fraction(source_rate) * ratio
            if stretched.denominator != 1:
                raise RenderError(f"no exact resampling for {ratio} at {source_rate} Hz")
            parts.append(f"aresample={stretched.numerator}:resampler=soxr:precision=28")
            parts.append(f"asetrate={source_rate}")
        elif pitch == PITCH_KEEP:
            parts.append(f"rubberband=tempo={float(1 / ratio):.10f}:pitchq=quality")
        else:
            raise RenderError(f"unknown pitch handling: {pitch}")
    if source_rate != SAMPLE_RATE:
        parts.append(f"aresample={SAMPLE_RATE}:resampler=soxr:precision=28")
    return ",".join(parts) or None


def stretch_command(
    input_args: Sequence[str],
    stream: str,
    codec: str,
    channels: int,
    ratio: Fraction,
    pitch: str,
    source_rate: int,
    output: Path,
    *,
    ffmpeg: str = "ffmpeg",
) -> list[str]:
    """Decode without dynamic range compression, to raw float samples at the title's speed."""

    drc = ("-drc_scale", "0") if codec in {"ac3", "eac3"} else ()
    chain = stretch_filter(ratio, pitch, source_rate)
    return [
        ffmpeg, "-hide_banner", "-nostdin", "-v", "error",
        *drc,
        *input_args,
        "-map", f"0:{stream}",
        "-vn", "-sn", "-dn",
        *(("-af", chain) if chain else ()),
        "-ac", str(channels),
        "-c:a", "pcm_f32le", "-f", "f32le", "-y", str(output),
    ]


def samples_per_frame(target_fps: Fraction) -> Fraction:
    return Fraction(SAMPLE_RATE) / target_fps


def sample_at(frame: int, per_frame: Fraction) -> int:
    return int(frame * per_frame + Fraction(1, 2))


def plan_pieces(
    segments: Sequence[Mapping[str, Any]],
    target_fps: Fraction,
    *,
    audio_offset_samples: int = 0,
) -> list[Piece]:
    """Title samples and where they come from.

    ``audio_offset_samples`` is how far the track's sound starts after the
    source's first picture, at the title's speed.
    """

    per_frame = samples_per_frame(target_fps)
    pieces = []
    for segment in segments:
        start = sample_at(int(segment["target_start"]), per_frame)
        end = sample_at(int(segment["target_end"]), per_frame)
        donor_picture = sample_at(int(segment["target_start"]) + int(segment["offset"]), per_frame)
        pieces.append(Piece(start, end, donor_picture - audio_offset_samples))
    return pieces


@dataclass(frozen=True, slots=True)
class Fill:
    """The title's own sound for the parts the source lacks.

    ``path`` holds float samples with the fitted track's channel count;
    ``offset_samples`` is where its first sample lies on the title's clock.
    """

    path: Path
    offset_samples: int = 0


def _energy(block: Any) -> float:
    return float((block.astype("float64") ** 2).mean()) if block.size else 0.0


def assemble(
    stretched: Path,
    output: Path,
    *,
    channels: int,
    total_samples: int,
    pieces: Sequence[Piece],
    priming_samples: int = 0,
    scale: float = 1.0,
    fill: Fill | None = None,
) -> dict[str, Any]:
    """Lay the pieces on the timeline; between and around them is digital silence,
    or with ``fill`` the title's own sound at the source's level.

    ``priming_samples`` are left off the start, so the encoded track starts at the
    title's first picture with no container delay.  ``scale`` corrects the small
    length error of a tempo-only stretch; a rational resampling has none.

    A gap's fill gets the level that makes it as loud as the fitted sound on its
    two sides (``FILL_LEVEL_WINDOW_SAMPLES`` each, the same moments of both), or
    the whole track's level where the sides are silent, within
    ``FILL_GAIN_LIMITS``; it crosses over with the fitted sound in
    ``FILL_CROSSFADE_SAMPLES``.
    """

    import numpy as np

    source = np.memmap(stretched, dtype=np.float32, mode="r")
    available = source.size // channels
    source = source[: available * channels].reshape(available, channels)
    fade_length = FILL_CROSSFADE_SAMPLES if fill is not None else FADE_SAMPLES
    fade = np.linspace(0.0, 1.0, fade_length, dtype=np.float32)[:, None]

    # Where the fitted sound really is: (title start, title end, source start,
    # fades in), the source advancing one sample per title sample from there.
    present: list[tuple[int, int, int, bool]] = []
    for piece in pieces:
        first = max(piece.start, priming_samples)
        if piece.end <= first:
            continue
        source_start = int(round((piece.source + (first - piece.start)) * scale))
        length = piece.end - first
        lead = max(0, -source_start)
        usable = max(0, min(length - lead, available - max(0, source_start)))
        if usable:
            fades_in = piece.start >= priming_samples and piece.start > 0
            present.append((first + lead, first + lead + usable, max(0, source_start), fades_in))

    filler = None
    if fill is not None:
        data = np.memmap(fill.path, dtype=np.float32, mode="r")
        frames = data.size // channels
        filler = data[: frames * channels].reshape(frames, channels)

    def fill_block(title_start: int, count: int) -> Any:
        block = np.zeros((max(count, 0), channels), dtype=np.float32)
        if filler is None or count <= 0:
            return block
        first = title_start - fill.offset_samples  # type: ignore[union-attr]
        low, high = max(0, first), min(len(filler), first + count)
        if high > low:
            block[low - first : high - first] = filler[low:high]
        return block

    def fitted_block(span: tuple[int, int, int, bool], title_start: int, count: int) -> Any:
        offset = title_start - span[0]
        return np.asarray(source[span[2] + offset : span[2] + offset + count], dtype=np.float32)

    gaps: list[dict[str, Any]] = []
    if filler is not None:
        edges = [priming_samples]
        for span in present:
            edges.extend((span[0], span[1]))
        edges.append(total_samples)
        bounds = [(edges[index], edges[index + 1]) for index in range(0, len(edges), 2)]
        # The whole track's level, from a second in each of up to 60 places.
        fitted_energy = fill_energy = 0.0
        spots = [span for span in present if span[1] - span[0] >= SAMPLE_RATE]
        for span in spots[:: max(1, len(spots) // 60)]:
            middle = (span[0] + span[1] - SAMPLE_RATE) // 2
            fitted_energy += _energy(fitted_block(span, middle, SAMPLE_RATE))
            fill_energy += _energy(fill_block(middle, SAMPLE_RATE))
        overall = (
            (fitted_energy / fill_energy) ** 0.5
            if fitted_energy > FILL_LEVEL_FLOOR and fill_energy > FILL_LEVEL_FLOOR
            else 1.0
        )
        for gap_start, gap_end in bounds:
            if gap_end <= gap_start:
                continue
            fitted_energy = fill_energy = 0.0
            for span in present:
                if span[1] == gap_start:
                    count = min(FILL_LEVEL_WINDOW_SAMPLES, span[1] - span[0])
                    fitted_energy += _energy(fitted_block(span, span[1] - count, count))
                    fill_energy += _energy(fill_block(span[1] - count, count))
                if span[0] == gap_end:
                    count = min(FILL_LEVEL_WINDOW_SAMPLES, span[1] - span[0])
                    fitted_energy += _energy(fitted_block(span, span[0], count))
                    fill_energy += _energy(fill_block(span[0], count))
            local = fitted_energy > FILL_LEVEL_FLOOR and fill_energy > FILL_LEVEL_FLOOR
            gain = (fitted_energy / fill_energy) ** 0.5 if local else overall
            gain = min(max(gain, FILL_GAIN_LIMITS[0]), FILL_GAIN_LIMITS[1])
            gaps.append({"start": gap_start, "end": gap_end, "gain": gain, "local": local})

    def gain_at(position: int) -> float:
        for gap in gaps:
            if gap["start"] <= position < gap["end"]:
                return float(gap["gain"])
        return 1.0

    silent = 0
    filled = 0
    written = 0
    with output.open("wb") as handle:
        position = priming_samples

        def empty(until: int) -> None:
            nonlocal position, silent, filled, written
            while position < until:
                gap_end = next(
                    (gap["end"] for gap in gaps if gap["start"] <= position < gap["end"]), until
                )
                count = min(until, gap_end, position + (1 << 20)) - position
                if filler is not None:
                    block = fill_block(position, count) * np.float32(gain_at(position))
                    filled += count
                else:
                    block = np.zeros((count, channels), dtype=np.float32)
                    silent += count
                handle.write(block.tobytes())
                written += count
                position += count

        for start, end, source_start, fades_in in present:
            empty(start)
            remaining = end - start
            cursor = source_start
            done = 0
            while remaining > 0:
                count = min(remaining, 1 << 20)
                block = np.array(source[cursor : cursor + count], dtype=np.float32)
                if done == 0 and fades_in:
                    width = min(fade_length, count)
                    block[:width] *= fade[:width]
                    if filler is not None:
                        block[:width] += (
                            fill_block(start, width) * (1 - fade[:width]) * np.float32(gain_at(start - 1))
                        )
                if remaining - count == 0:
                    width = min(fade_length, count)
                    block[-width:] *= fade[:width][::-1]
                    if filler is not None:
                        block[-width:] += (
                            fill_block(end - width, width)
                            * (1 - fade[:width][::-1])
                            * np.float32(gain_at(end))
                        )
                handle.write(block.tobytes())
                cursor += count
                done += count
                remaining -= count
                written += count
            position = end
        empty(total_samples)
    report: dict[str, Any] = {
        "samples_written": written,
        "silent_samples": silent,
        "source_samples": available,
        "total_samples": total_samples,
    }
    if fill is not None:
        report["filled_samples"] = filled
        report["fill_gaps"] = [
            {
                "start_seconds": round(gap["start"] / SAMPLE_RATE, 3),
                "seconds": round((gap["end"] - gap["start"]) / SAMPLE_RATE, 3),
                "gain_db": round(20 * float(np.log10(gap["gain"])), 1),
                "level_from": "sides" if gap["local"] else "whole_track",
            }
            for gap in gaps
        ]
    return report


@dataclass(frozen=True, slots=True)
class Encoding:
    codec: str
    bit_rate: int
    dialnorm: int | None = None

    @property
    def priming_samples(self) -> int:
        return AC3_PRIMING_SAMPLES if self.codec == "ac3" else 0


def choose_encoding(
    codec: str, channels: int, bit_rate: int | None, dialnorm: int | None
) -> Encoding:
    """AC-3, at the source's rate for a lossy source and the top rate for a better one.

    The HU standard allows this for a stretched track; downmixing never happens.
    """

    if channels < 1 or channels > 6:
        raise RenderError(f"{channels} channels cannot be stretched to AC-3 without a downmix")
    limit = 640_000 if channels > 2 else 384_000
    if codec in _LOSSY_CODECS and bit_rate:
        rate = min(limit, max(192_000 if channels > 1 else 96_000, bit_rate))
    else:
        rate = limit
    if dialnorm is not None and not -31 <= dialnorm <= -1:
        dialnorm = None
    return Encoding("ac3", rate, dialnorm)


_LAYOUTS = {1: "mono", 2: "stereo", 3: "2.1", 4: "quad", 5: "5.0(side)", 6: "5.1(side)"}


def encode_command(
    raw: Path, channels: int, encoding: Encoding, output: Path, *, ffmpeg: str = "ffmpeg"
) -> list[str]:
    return [
        ffmpeg, "-hide_banner", "-nostdin", "-v", "error",
        "-f", "f32le", "-ar", str(SAMPLE_RATE), "-ch_layout", _LAYOUTS[channels], "-i", str(raw),
        "-c:a", encoding.codec, "-b:a", str(encoding.bit_rate),
        *(("-dialnorm", str(encoding.dialnorm)) if encoding.dialnorm is not None else ()),
        "-f", "ac3", "-y", str(output),
    ]


def dialnorm_command(path: Path) -> list[str]:
    return ["mediainfo", "--Inform=Audio;%dialnorm%", str(path)]


def parse_dialnorm(text: str) -> int | None:
    value = (text or "").strip().split(" ")[0].split("/")[0].strip()
    try:
        return int(value)
    except ValueError:
        return None


def stream_copy_command(
    input_args: Sequence[str], stream: str, output: Path, *, ffmpeg: str = "ffmpeg"
) -> list[str]:
    return [
        ffmpeg, "-hide_banner", "-nostdin", "-v", "error",
        *input_args,
        "-map", f"0:{stream}", "-vn", "-sn", "-dn",
        "-c:a", "copy", "-y", str(output),
    ]


def copy_is_possible(segments: Sequence[Mapping[str, Any]], ratio: Fraction) -> bool:
    """One unbroken piece at the same speed needs no new encoding, so it must not get one."""

    return ratio == 1 and len(segments) == 1


def sidecar_suffix(codec: str) -> str:
    return {
        "ac3": ".ac3",
        "eac3": ".eac3",
        "dts": ".dts",
        "truehd": ".thd",
        "flac": ".flac",
        "aac": ".m4a",
        "mp2": ".mp2",
        "mp3": ".mp3",
    }.get(codec, ".mka")
