"""Hash the Dolby Vision enhancement layer of a video without decoding it.

FFmpeg decodes only the base layer, so comparing decoded frames says nothing
about the enhancement layer and the RPU.  This compares their NAL units instead,
as a stream: a separate layer track holds them plainly, a joined profile 7 track
wraps each enhancement unit in a NAL type 63 and keeps the RPU as type 62.  Start
code lengths are not part of the units, because mkvmerge does not keep them.

Run as ``python -m bdencode.dovi_layers <file> <video ordinal> {layer|joined}``;
prints the count and the digest as JSON.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from typing import BinaryIO, Iterator

START_CODE = b"\x00\x00\x01"
NAL_RPU = 62
NAL_WRAPPED_ENHANCEMENT = 63
WRAPPER_BYTES = 2
LAYER = "layer"
JOINED = "joined"


def nal_units(stream: BinaryIO, *, chunk_size: int = 16 * 1024 * 1024) -> Iterator[bytes]:
    """The NAL units of an Annex B stream, without their start codes."""

    buffer = b""
    begin = -1
    search = 0
    while chunk := stream.read(chunk_size):
        buffer += chunk
        while (found := buffer.find(START_CODE, search)) >= 0:
            if begin >= 0 and (unit := buffer[begin:found].rstrip(b"\x00")):
                yield unit
            begin = found + len(START_CODE)
            search = begin
        # A start code can straddle two chunks.
        search = max(search, len(buffer) - (len(START_CODE) - 1))
        keep = begin if begin >= 0 else search
        buffer = buffer[keep:]
        search -= keep
        begin = 0 if begin >= 0 else -1
    if begin >= 0 and (unit := buffer[begin:].rstrip(b"\x00")):
        yield unit


def enhancement_units(stream: BinaryIO, form: str) -> Iterator[bytes]:
    """The enhancement layer's units as the layer track itself holds them."""

    for unit in nal_units(stream):
        if form == LAYER:
            yield unit
            continue
        kind = (unit[0] >> 1) & 0x3F
        if kind == NAL_RPU:
            yield unit
        elif kind == NAL_WRAPPED_ENHANCEMENT:
            yield unit[WRAPPER_BYTES:]


def layer_digest(stream: BinaryIO, form: str) -> dict[str, object]:
    """How many units there are and a digest over them and their boundaries."""

    digest = hashlib.sha256()
    units = 0
    for unit in enhancement_units(stream, form):
        digest.update(len(unit).to_bytes(8, "big"))
        digest.update(unit)
        units += 1
    return {"units": units, "sha256": digest.hexdigest()}


def layer_extract_command(path: str, ordinal: int, *, ffmpeg: str = "ffmpeg") -> list[str]:
    return [
        ffmpeg,
        "-hide_banner",
        "-nostdin",
        "-v",
        "error",
        "-i",
        path,
        "-map",
        f"0:v:{ordinal}",
        "-c",
        "copy",
        "-bsf:v",
        "hevc_mp4toannexb",
        "-f",
        "hevc",
        "-",
    ]


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[2] not in (LAYER, JOINED):
        print("usage: dovi_layers <file> <video ordinal> {layer|joined}", file=sys.stderr)
        return 2
    process = subprocess.Popen(
        layer_extract_command(argv[0], int(argv[1])), stdout=subprocess.PIPE
    )
    assert process.stdout is not None
    with process.stdout:
        result = layer_digest(process.stdout, argv[2])
    if process.wait() != 0:
        print(f"ffmpeg exited with {process.returncode}", file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
