from __future__ import annotations

import io

import pytest

from bdencode.dovi_layers import (
    JOINED,
    LAYER,
    enhancement_units,
    layer_digest,
    layer_extract_command,
    main,
    nal_units,
)


def _unit(kind: int, payload: bytes) -> bytes:
    return bytes([kind << 1, 1]) + payload


BASE = _unit(1, b"base slice")
RPU = _unit(62, b"rpu payload")
ENHANCEMENT = _unit(1, b"enhancement slice")
ENHANCEMENT_PARAMETERS = _unit(33, b"enhancement sps")


def _wrapped(unit: bytes) -> bytes:
    return _unit(63, unit)


def _stream(*units: bytes, long_start: bool = False) -> io.BytesIO:
    start = b"\x00\x00\x00\x01" if long_start else b"\x00\x00\x01"
    return io.BytesIO(b"".join(start + unit for unit in units))


@pytest.mark.parametrize("chunk_size", [1, 2, 3, 4, 7, 1024])
@pytest.mark.parametrize("long_start", [False, True])
def test_units_are_found_across_chunk_boundaries(chunk_size: int, long_start: bool) -> None:
    units = [BASE, RPU, ENHANCEMENT, _unit(20, b"\x00\x00\x03" + b"x" * 40)]

    found = list(nal_units(_stream(*units, long_start=long_start), chunk_size=chunk_size))

    assert found == units


def test_nothing_before_the_first_start_code_is_a_unit() -> None:
    assert list(nal_units(io.BytesIO(b"junk\x00\x00\x01" + BASE), chunk_size=3)) == [BASE]
    assert list(nal_units(io.BytesIO(b""))) == []
    assert list(nal_units(io.BytesIO(b"no start code at all"))) == []


def test_a_joined_track_yields_the_units_of_the_layer_track() -> None:
    layer = _stream(RPU, ENHANCEMENT_PARAMETERS, ENHANCEMENT)
    joined = _stream(
        BASE,
        RPU,
        _wrapped(ENHANCEMENT_PARAMETERS),
        _wrapped(ENHANCEMENT),
        BASE,
        long_start=True,
    )

    assert list(enhancement_units(joined, JOINED)) == list(enhancement_units(layer, LAYER))


def test_the_digests_agree_only_on_equal_layers() -> None:
    layer = layer_digest(_stream(RPU, ENHANCEMENT), LAYER)

    assert layer == layer_digest(_stream(BASE, RPU, _wrapped(ENHANCEMENT)), JOINED)
    assert layer["units"] == 2
    # A lost unit, a changed unit and moved unit boundaries all differ.
    assert layer != layer_digest(_stream(BASE, RPU), JOINED)
    assert layer != layer_digest(_stream(RPU, _wrapped(_unit(1, b"another slice"))), JOINED)
    assert layer_digest(_stream(_unit(1, b"ab" + b"cd")), LAYER) != layer_digest(
        _stream(_unit(1, b"ab"), b"cd"), LAYER
    )


def test_the_extract_command_copies_one_layer_as_annex_b() -> None:
    command = layer_extract_command("/work/reference.mkv", 1)

    assert command[command.index("-map") + 1] == "0:v:1"
    assert command[command.index("-c") + 1] == "copy"
    assert "hevc_mp4toannexb" in command
    assert command[-3:] == ["-f", "hevc", "-"]


def test_bad_arguments_are_refused() -> None:
    assert main([]) == 2
    assert main(["file", "0", "other"]) == 2
