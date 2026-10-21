"""Identify the tracks of a playlist before the operator chooses them.

Disc metadata often leaves the operator guessing: audio languages can be
missing or wrong, and nothing on a Blu-ray says whether a subtitle stream is a
full subtitle or a forced one.  After the scan the worker therefore reads a few
short windows of the recommended playlist straight from the disc, once per
window, and keeps per audio stream a mono 16 kHz WAV (for speech language
detection) and per subtitle stream the copied PGS packets.

* Audio: the faster-whisper language detection already used during
  preparation runs on the WAVs; the result is a suggestion with confidence.
* Subtitles: PGS events are counted (a displayed caption is one packet of at
  least ``EVENT_MIN_BYTES``; the clearing packets are small).  A full
  subtitle shows several captions a minute, a forced one only a few in the
  whole film, so the event rate decides, helped by a comparison with the
  other subtitle streams of the same language.
* Subtitle language (3.10): a few captions of every stream are read, PGS ones
  with OCR, text ones as text, and the language is told from the words
  (:mod:`bdencode.media.subtitle_language`).

The source is a Blu-ray folder (libbluray, addressed by PID) or a remux MKV
file (addressed by its stream index).  A window or a stream that cannot be
read is skipped and noted; only a playlist that yields nothing fails.

Everything here is advisory: the wizard shows it, the operator decides.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import subtitle_language as sublang
from .inference import SampleWindow, sample_windows

ANALYSIS_SCHEMA_VERSION = 2
WINDOW_COUNT = 6
WINDOW_SECONDS = 30.0
EVENT_MIN_BYTES = 512
# Events per sampled minute.  Full subtitles of a feature film measured
# 10-17/min (La Femme Nikita, three streams); forced ones carry a handful of
# captions in the whole film.
FULL_MIN_RATE = 3.0
FORCED_MAX_RATE = 1.0
# A stream with at most this share of the busiest same-language stream's
# events is the forced one of the pair.
FORCED_RELATIVE_SHARE = 0.25
MAX_ANALYSED_PLAYLISTS = 3


@dataclass(frozen=True, slots=True)
class StreamRef:
    """A selectable stream: its scan id, a file key and its ffmpeg input index.

    ``pid`` is the transport PID on a disc and the stream index in an MKV; it
    only names the window files.
    """

    stream_id: str
    pid: int
    input_index: int
    codec: str = ""


def source_input_args(source: Path, playlist: int) -> list[str]:
    """FFmpeg input of the analysed title: a disc playlist or a remux file."""

    if source.is_file():
        return ["-i", str(source)]
    return ["-playlist", str(playlist), "-i", f"bluray:{source.as_posix()}"]


def probe_streams_command(disc_root: Path, playlist: int, *, ffprobe: str = "ffprobe") -> list[str]:
    if disc_root.is_file():
        return [ffprobe, "-v", "error", "-show_entries", "stream=index,id,codec_type", "-of", "json", str(disc_root)]
    return [
        ffprobe, "-v", "error", "-playlist", str(playlist),
        "-show_entries", "stream=index,id,codec_type", "-of", "json",
        f"bluray:{disc_root.as_posix()}",
    ]


def parse_stream_indexes(document: str | Mapping[str, Any]) -> dict[int, int]:
    """PID -> first ffmpeg input index (a TrueHD PID also carries its AC-3 core)."""

    raw = json.loads(document) if isinstance(document, str) else document
    indexes: dict[int, int] = {}
    for stream in raw.get("streams", []) if isinstance(raw, Mapping) else []:
        if not isinstance(stream, Mapping):
            continue
        try:
            pid = int(str(stream.get("id")), 0)
            index = int(stream.get("index"))
        except (TypeError, ValueError):
            continue
        indexes.setdefault(pid, index)
    return indexes


def window_extract_command(
    disc_root: Path,
    playlist: int,
    window: SampleWindow,
    audio: Sequence[StreamRef],
    subtitles: Sequence[StreamRef],
    out_dir: Path,
    *,
    ffmpeg: str = "ffmpeg",
) -> list[str]:
    """One read of the window: a WAV per audio stream, a Matroska per subtitle."""

    inputs = source_input_args(disc_root, playlist)
    command = [
        ffmpeg, "-hide_banner", "-nostdin", "-v", "error", "-y",
        # A window starts anywhere: a DTS-HD or TrueHD frame cut in half must
        # not end the read (3.9 failed a whole disc on it).
        "-err_detect", "ignore_err",
        *inputs[:-2],
        "-ss", f"{window.start_seconds:.3f}",
        "-t", f"{window.duration_seconds:.3f}",
        *inputs[-2:],
    ]
    for ref in audio:
        command += [
            "-map", f"0:{ref.input_index}", "-vn", "-sn", "-dn",
            "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
            str(out_dir / f"audio-{ref.pid}.wav"),
        ]
    for ref in subtitles:
        command += [
            "-map", f"0:{ref.input_index}", "-c", "copy", "-f", "matroska",
            str(out_dir / f"subtitle-{ref.pid}.mks"),
        ]
    return command


def packet_sizes_command(path: Path, *, ffprobe: str = "ffprobe") -> list[str]:
    return [ffprobe, "-v", "error", "-show_entries", "packet=size", "-of", "csv=p=0", str(path)]


def _subtitle_language(
    ref: StreamRef,
    windows_dirs: Sequence[Path],
    work_dir: Path,
    run: "Runner",
) -> dict[str, Any]:
    """Read a few captions of one subtitle stream and tell their language."""

    codec = ref.codec.lower()
    texts: list[str] = []
    if codec in sublang.TEXT_SUBTITLE_CODECS:
        for out_dir in windows_dirs:
            mks = out_dir / f"subtitle-{ref.pid}.mks"
            if mks.is_file():
                try:
                    texts.append(sublang.srt_text(run(sublang.text_subtitle_command(mks), out_dir)))
                except Exception:  # noqa: BLE001 - a window without captions
                    continue
        method = "text"
    elif codec in sublang.BITMAP_SUBTITLE_CODECS:
        if shutil.which("tesseract") is None:
            return {"status": "unavailable", "reason": "tesseract_missing", "method": "ocr"}
        captions: list[tuple[float, int, int, bytes]] = []
        for out_dir in windows_dirs:
            mks = out_dir / f"subtitle-{ref.pid}.mks"
            sup = out_dir / f"subtitle-{ref.pid}.sup"
            if not mks.is_file():
                continue
            try:
                run(sublang.sup_command(mks, sup), out_dir)
                captions.extend(sublang.pgs_captions(sup.read_bytes()))
            except Exception:  # noqa: BLE001 - an unreadable window
                continue
        ocr_dir = work_dir / f"ocr-{ref.pid}"
        ocr_dir.mkdir(parents=True, exist_ok=True)
        for number, (_at, width, height, grey) in enumerate(
            sublang.spread(captions, sublang.OCR_CAPTIONS_PER_STREAM)
        ):
            image = ocr_dir / f"caption-{number:02d}.pgm"
            sublang.write_pgm(image, width, height, grey)
            try:
                texts.append(run(sublang.ocr_command(image), ocr_dir).strip())
            except Exception:  # noqa: BLE001 - one unreadable caption
                continue
        method = "ocr"
    else:
        return {"status": "unavailable", "reason": "unsupported_codec", "codec": ref.codec}
    joined = "\n".join(text for text in texts if text)
    return sublang.summarise(sublang.identify_text_language(joined), method, joined)


def count_events(packet_sizes_csv: str, min_bytes: int = EVENT_MIN_BYTES) -> int:
    """Captions among the packets: PGS captions are large, the clearing packets
    small; a text subtitle (SubRip, ASS) packet is one caption whatever its size."""

    count = 0
    for line in packet_sizes_csv.splitlines():
        try:
            if int(line.strip().split(",")[0]) >= min_bytes:
                count += 1
        except ValueError:
            continue
    return count


def event_min_bytes(codec: str) -> int:
    return 1 if codec.lower() in sublang.TEXT_SUBTITLE_CODECS else EVENT_MIN_BYTES


def classify_subtitles(
    events: Mapping[str, int],
    sampled_seconds: float,
    languages: Mapping[str, str | None],
) -> dict[str, dict[str, Any]]:
    """Per subtitle stream: event rate and a full/forced suggestion with confidence."""

    minutes = max(sampled_seconds / 60.0, 1e-9)
    rates = {stream_id: count / minutes for stream_id, count in events.items()}
    busiest: dict[str | None, float] = {}
    for stream_id, rate in rates.items():
        language = languages.get(stream_id)
        busiest[language] = max(busiest.get(language, 0.0), rate)
    result: dict[str, dict[str, Any]] = {}
    for stream_id, rate in rates.items():
        language = languages.get(stream_id)
        peer = busiest.get(language, 0.0)
        relative_forced = (
            language is not None
            and peer >= FULL_MIN_RATE
            and rate <= peer * FORCED_RELATIVE_SHARE
            and sum(1 for other in rates if languages.get(other) == language) > 1
        )
        if rate >= FULL_MIN_RATE and not relative_forced:
            kind, confidence = "full", "high" if rate >= 2 * FULL_MIN_RATE else "medium"
        elif rate <= FORCED_MAX_RATE or relative_forced:
            kind = "forced"
            confidence = "high" if (rate <= FORCED_MAX_RATE and relative_forced) or rate == 0 else "medium"
        else:
            kind, confidence = None, "low"
        result[stream_id] = {
            "events": events[stream_id],
            "sampled_seconds": round(sampled_seconds, 1),
            "events_per_minute": round(rate, 2),
            "suggested_kind": kind,
            "confidence": confidence,
        }
    return result


def analysis_windows(duration_seconds: float) -> tuple[SampleWindow, ...]:
    return sample_windows(duration_seconds, count=WINDOW_COUNT, sample_duration=WINDOW_SECONDS)


def playlists_to_analyse(playlists: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """The recommended playlists, at most a few, one per distinct track set."""

    chosen: list[Mapping[str, Any]] = []
    signatures: set[tuple[str, ...]] = set()
    for playlist in playlists:
        if not playlist.get("recommended"):
            continue
        signature = tuple(
            str(stream.get("id"))
            for stream in playlist.get("streams") or []
            if isinstance(stream, Mapping) and stream.get("kind") in ("audio", "subtitle")
        )
        if not signature or signature in signatures:
            continue
        signatures.add(signature)
        chosen.append(playlist)
        if len(chosen) >= MAX_ANALYSED_PLAYLISTS:
            break
    return chosen


LanguageDetector = Callable[[Sequence[tuple[Path, SampleWindow]]], Mapping[str, Any]]
Runner = Callable[[list[str], Path], str]


def analyse_playlist(
    disc_root: Path,
    playlist: Mapping[str, Any],
    work_dir: Path,
    *,
    run: Runner,
    detect_language: LanguageDetector | None,
    on_window: Callable[[int, int], None] | None = None,
) -> dict[str, Any]:
    """Read the windows once and analyse every audio and subtitle stream.

    ``run(argv, cwd)`` runs a command and returns its standard output;
    ``detect_language`` turns (wav, window) samples into a consensus record,
    or is ``None`` when speech detection is unavailable.
    """

    playlist_number = int(str(playlist["playlist_id"]))
    duration = float(playlist.get("duration_seconds") or 0.0)
    if duration <= 0:
        raise ValueError("playlist duration is unknown")
    streams = [s for s in playlist.get("streams") or [] if isinstance(s, Mapping)]
    single_file = disc_root.is_file()
    indexes = (
        {}
        if single_file
        else parse_stream_indexes(run(probe_streams_command(disc_root, playlist_number), work_dir))
    )

    def refs(kind: str) -> list[StreamRef]:
        found: list[StreamRef] = []
        seen: set[int] = set()
        for stream in streams:
            if stream.get("kind") != kind:
                continue
            codec = str(stream.get("codec") or "")
            if single_file:
                # A remux file: streams are addressed by their own index.
                index = stream.get("index")
                if not isinstance(index, int) or index in seen:
                    continue
                seen.add(index)
                found.append(StreamRef(str(stream["id"]), index, index, codec))
                continue
            pid = stream.get("pid")
            if not isinstance(pid, int) or pid in seen or pid not in indexes:
                continue
            seen.add(pid)
            found.append(StreamRef(str(stream["id"]), pid, indexes[pid], codec))
        return found

    audio, subtitles = refs("audio"), refs("subtitle")
    windows = analysis_windows(duration)
    samples: dict[int, list[tuple[Path, SampleWindow]]] = {ref.pid: [] for ref in audio}
    events: dict[str, int] = {ref.stream_id: 0 for ref in subtitles}
    sampled = 0.0
    read_dirs: list[Path] = []
    skipped: list[dict[str, Any]] = []
    for number, window in enumerate(windows, start=1):
        out_dir = work_dir / f"window-{number:02d}"
        out_dir.mkdir(parents=True, exist_ok=True)
        try:
            run(window_extract_command(disc_root, playlist_number, window, audio, subtitles, out_dir), out_dir)
        except Exception as exc:  # noqa: BLE001 - one unreadable window is skipped
            skipped.append({"window": number, "reason": type(exc).__name__})
            if on_window is not None:
                on_window(number, len(windows))
            continue
        read_dirs.append(out_dir)
        sampled += window.duration_seconds
        for ref in audio:
            wav = out_dir / f"audio-{ref.pid}.wav"
            if wav.is_file() and wav.stat().st_size > 44:
                samples[ref.pid].append((wav, window))
        for ref in subtitles:
            mks = out_dir / f"subtitle-{ref.pid}.mks"
            if mks.is_file():
                try:
                    events[ref.stream_id] += count_events(
                        run(packet_sizes_command(mks), out_dir), event_min_bytes(ref.codec)
                    )
                except Exception:  # noqa: BLE001 - an empty or cut window file
                    skipped.append({"window": number, "stream_id": ref.stream_id, "reason": "unreadable_subtitle_window"})
        if on_window is not None:
            on_window(number, len(windows))
    if not read_dirs:
        raise RuntimeError("no analysis window could be read")

    languages = {
        str(stream["id"]): (stream.get("language") or {}).get("iso639_2t")
        for stream in streams
        if isinstance(stream.get("language"), Mapping) or stream.get("language") is None
    }
    audio_result: dict[str, Any] = {}
    for ref in audio:
        if detect_language is None:
            audio_result[ref.stream_id] = {"status": "unavailable"}
            continue
        try:
            record = dict(detect_language(samples[ref.pid]))
        except Exception as exc:  # noqa: BLE001 - advisory only, never fails the scan
            audio_result[ref.stream_id] = {"status": "unavailable", "reason": type(exc).__name__}
            continue
        audio_result[ref.stream_id] = {"status": "detected", **record}
    # Every stream sharing a PID (TrueHD and its AC-3 core) gets the result.
    for stream in streams:
        if stream.get("kind") == "audio" and str(stream["id"]) not in audio_result:
            twin = next((ref for ref in audio if ref.pid == stream.get("pid")), None)
            if twin is not None:
                audio_result[str(stream["id"])] = audio_result[twin.stream_id]
    subtitle_result = classify_subtitles(events, sampled, languages) if subtitles else {}
    for ref in subtitles:
        try:
            language = _subtitle_language(ref, read_dirs, work_dir, run)
        except Exception as exc:  # noqa: BLE001 - advisory only
            language = {"status": "unavailable", "reason": type(exc).__name__}
        subtitle_result.setdefault(ref.stream_id, {})["language"] = language
    return {
        "schema_version": ANALYSIS_SCHEMA_VERSION,
        "windows": [
            {"start_seconds": w.start_seconds, "duration_seconds": w.duration_seconds} for w in windows
        ],
        "skipped": skipped,
        "audio": audio_result,
        "subtitles": subtitle_result,
    }
