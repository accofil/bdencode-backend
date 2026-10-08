from __future__ import annotations

from pathlib import Path

import pytest

from bdencode.process import classify_media_diagnostics
from bdencode.qc.integrity import clip_join_decode_command, split_clip_join_lines

PROGRESS = "frame=151082 fps=287 q=-1.0 size=74980608KiB time=01:44:56.45 speed=12x    \r"
# The end of a real remux (The Last Boy Scout, playlist 00002): the main clip
# joins a one-second closing clip.
JOIN = (
    "[mpegts @ 0x5863d0c0f500] Packet corrupt (stream = 0, dts = NOPTS).\n"
    "[vist#0:0/hevc @ 0x5863d0d67680] timestamp discontinuity (stream id=4113): "
    "-6327863200, new offset= 6327863200\n"
    "[aist#0:3/dts @ 0x5863d0f3f040] timestamp discontinuity (stream id=4353): "
    "6327873866, new offset= -10666\n"
    "[aist#0:2/pcm_bluray @ 0x5863d0f403c0] timestamp discontinuity (stream id=4352): "
    "-6327868867, new offset= 6327858201\n"
    "[truehd @ 0x5863d0c633c0] mlpparse: Parity check failed.\n"
    "[aist#0:5/ac3 @ 0x5863d0fcdb00] timestamp discontinuity (stream id=4354): "
    "6327890200, new offset= -31999\n"
    "[aist#0:6/ac3 @ 0x5863d0fcbf80] timestamp discontinuity (stream id=4355): "
    "-6327858200, new offset= 6327826201\n"
)
SUMMARY = (
    "[out#0/matroska @ 0x5863d0fcc740] video:66599106KiB audio:8588347KiB "
    "muxing overhead: 0.093582%\n"
)


def test_the_messages_of_a_clip_join_are_set_apart() -> None:
    log = PROGRESS * 20 + JOIN + SUMMARY + PROGRESS * 3

    remaining, joined = split_clip_join_lines(log, 1)

    assert classify_media_diagnostics(log, context="source")
    assert classify_media_diagnostics(remaining, context="source") == ()
    assert len(joined) == 7
    assert joined[0].endswith("Packet corrupt (stream = 0, dts = NOPTS).")
    assert any("mlpparse: Parity check failed" in line for line in joined)
    # Progress records and the muxer's summary are not join messages.
    assert all(not line.startswith(("frame=", "[out#")) for line in joined)
    assert "muxing overhead" in remaining


def test_a_log_with_more_jumps_than_joins_is_not_explained() -> None:
    log = PROGRESS + JOIN + PROGRESS * 20 + JOIN

    assert split_clip_join_lines(log, 0) is None
    assert split_clip_join_lines(log, 1) is None
    remaining, joined = split_clip_join_lines(log, 2)
    assert len(joined) == 14
    assert classify_media_diagnostics(remaining, context="source") == ()


def test_damage_away_from_a_join_stays_in_the_log() -> None:
    damage = "[mpegts @ 0x1] Packet corrupt (stream = 0, dts = 4512000).\n"
    log = damage + PROGRESS * 12 + JOIN

    remaining, joined = split_clip_join_lines(log, 1)

    assert damage.strip() not in joined
    codes = {item.code for item in classify_media_diagnostics(remaining, context="source")}
    assert "corrupt_packet" in codes


def test_subtitle_jumps_belong_to_the_joins_whenever_they_come() -> None:
    late_subtitle = (
        "[sist#0:7/hdmv_pgs_subtitle @ 0x2] timestamp discontinuity (stream id=4768): "
        "-6327863200, new offset= 6327863200\n"
    )
    log = PROGRESS + JOIN + PROGRESS * 30 + late_subtitle

    remaining, joined = split_clip_join_lines(log, 1)

    assert late_subtitle.strip() in joined
    assert classify_media_diagnostics(remaining, context="source") == ()
    # Without a join a subtitle jump is not explained either.
    plain = PROGRESS + late_subtitle
    remaining, joined = split_clip_join_lines(plain, 0)
    assert joined == () and late_subtitle.strip() in remaining


def test_a_log_without_jumps_is_unchanged() -> None:
    log = PROGRESS * 5 + SUMMARY

    assert split_clip_join_lines(log, 1) == (log, ())
    with pytest.raises(ValueError):
        split_clip_join_lines(log, -1)


def test_the_join_decode_covers_both_sides_of_the_join_strictly() -> None:
    command = clip_join_decode_command(Path("reference.mkv"), 6327.8632)

    assert command[command.index("-ss") + 1] == "6307.863"
    assert command[command.index("-t") + 1] == "30.000"
    assert command.index("-ss") < command.index("-i")
    assert "-xerror" in command and command[command.index("-err_detect") + 1] == "explode"
    maps = [command[index + 1] for index, item in enumerate(command) if item == "-map"]
    assert maps == ["0:v:0", "0:a?"]
    early = clip_join_decode_command(Path("reference.mkv"), 5.0)
    assert early[early.index("-ss") + 1] == "0.000"
    assert early[early.index("-t") + 1] == "15.000"
    with pytest.raises(ValueError):
        clip_join_decode_command(Path("reference.mkv"), -1.0)
