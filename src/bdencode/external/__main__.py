"""The heavy steps of external source fitting, run by the worker as subprocesses.

``python -m bdencode.external map <target sig> <donor sig> <target fps> <donor fps> <out.json>``
``python -m bdencode.external assemble <spec.json>``
``python -m bdencode.external verify <spec.json>``
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from fractions import Fraction
from pathlib import Path

from .frame_map import build_frame_map
from .render import Fill, assemble, plan_pieces
from .verify import (
    expected_window,
    final_window_command,
    judge,
    measure_window,
    window_frames,
)


def _map(arguments: list[str]) -> int:
    target, donor, target_fps, donor_fps, output = arguments
    document = build_frame_map(
        Path(target),
        Path(donor),
        target_fps=Fraction(target_fps),
        donor_fps=Fraction(donor_fps),
    )
    Path(output).write_text(json.dumps(document, indent=1), encoding="utf-8")
    return 0


def _assemble(arguments: list[str]) -> int:
    spec = json.loads(Path(arguments[0]).read_text(encoding="utf-8"))
    target_fps = Fraction(spec["target_fps"])
    pieces = plan_pieces(
        spec["segments"], target_fps, audio_offset_samples=int(spec["audio_offset_samples"])
    )
    stretched = Path(spec["stretched"])
    channels = int(spec["channels"])
    expected = int(spec["expected_stretched_samples"])
    actual = stretched.stat().st_size // (4 * channels)
    # Only a tempo-only stretch misses its length, and only by a tiny factor.
    scale = actual / expected if spec.get("correct_length") and expected else 1.0
    report = assemble(
        stretched,
        Path(spec["output"]),
        channels=channels,
        total_samples=int(spec["total_samples"]),
        pieces=pieces,
        priming_samples=int(spec["priming_samples"]),
        scale=scale,
        fill=(
            Fill(Path(spec["fill"]["path"]), int(spec["fill"]["offset_samples"]))
            if spec.get("fill")
            else None
        ),
    )
    report["scale"] = scale
    print(json.dumps(report))
    return 0


def _verify(arguments: list[str]) -> int:
    import numpy as np

    spec = json.loads(Path(arguments[0]).read_text(encoding="utf-8"))
    target_fps = Fraction(spec["target_fps"])
    channels = int(spec["channels"])
    stretched = np.memmap(spec["stretched"], dtype=np.float32, mode="r")
    final = Path(spec["final"])
    windows = []
    with tempfile.TemporaryDirectory(dir=spec["work"]) as directory:
        scratch = Path(directory) / "window.f32"
        for frame, offset in window_frames(spec["segments"], target_fps):
            start = float(Fraction(frame) / target_fps) + float(spec["video_start_seconds"])
            subprocess.run(
                final_window_command(final, int(spec["ordinal"]), start, scratch), check=True
            )
            decoded = np.fromfile(scratch, dtype=np.float32)
            expected = expected_window(
                stretched,
                channels,
                frame=frame,
                offset=offset,
                target_fps=target_fps,
                audio_offset_samples=int(spec["audio_offset_samples"]),
                scale=float(spec.get("scale", 1.0)),
            )
            windows.append(measure_window(decoded, expected, frame, target_fps))
    Path(spec["report"]).write_text(json.dumps(judge(windows), indent=1), encoding="utf-8")
    return 0


def main(arguments: list[str]) -> int:
    commands = {"map": _map, "assemble": _assemble, "verify": _verify}
    if not arguments or arguments[0] not in commands:
        print(__doc__, file=sys.stderr)
        return 2
    return commands[arguments[0]](arguments[1:])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
