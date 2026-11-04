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


def assemble(
    stretched: Path,
    output: Path,
    *,
    channels: int,
    total_samples: int,
    pieces: Sequence[Piece],
    priming_samples: int = 0,
    scale: float = 1.0,
) -> dict[str, Any]:
    """Lay the pieces on the timeline; between and around them is digital silence.

    ``priming_samples`` are left off the start, so the encoded track starts at the
    title's first picture with no container delay.  ``scale`` corrects the small
    length error of a tempo-only stretch; a rational resampling has none.
    """

    import numpy as np

    source = np.memmap(stretched, dtype=np.float32, mode="r")
    available = source.size // channels
    source = source[: available * channels].reshape(available, channels)
    fade = np.linspace(0.0, 1.0, FADE_SAMPLES, dtype=np.float32)[:, None]
    silent = 0
    written = 0
    with output.open("wb") as handle:
        position = priming_samples

        def silence(until: int) -> None:
            nonlocal position, silent, written
            remaining = until - position
            block = np.zeros((min(remaining, 1 << 20), channels), dtype=np.float32) if remaining > 0 else None
            while remaining > 0:
                count = min(remaining, len(block))
                handle.write(block[:count].tobytes())
                remaining -= count
                silent += count
                written += count
            position = max(position, until)

        for piece in pieces:
            first = max(piece.start, priming_samples)
            if piece.end <= first:
                continue
            silence(first)
            source_start = int(round((piece.source + (first - piece.start)) * scale))
            length = piece.end - first
            lead = max(0, -source_start)
            usable = max(0, min(length - lead, available - max(0, source_start)))
            if lead:
                silence(first + lead)
            cursor = max(0, source_start)
            remaining = usable
            done = 0
            while remaining > 0:
                count = min(remaining, 1 << 20)
                block = np.array(source[cursor : cursor + count], dtype=np.float32)
                if done == 0 and piece.start >= priming_samples and piece.start > 0:
                    span = min(FADE_SAMPLES, count)
                    block[:span] *= fade[:span]
                if remaining - count == 0:
                    span = min(FADE_SAMPLES, count)
                    block[-span:] *= fade[:span][::-1]
                handle.write(block.tobytes())
                cursor += count
                done += count
                remaining -= count
                written += count
            position = first + lead + usable
        silence(total_samples)
    return {
        "samples_written": written,
        "silent_samples": silent,
        "source_samples": available,
        "total_samples": total_samples,
    }


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
