"""Tool warnings and known Blu-ray quirks are recorded; only real defects stop a job."""

from __future__ import annotations

import pytest

from bdencode.mux import (
    classify_mkvmerge_warning,
    classify_mkvmerge_warnings,
    mkvmerge_warning_lines,
)
from bdencode.process import classify_media_diagnostics
from bdencode.qc.integrity import classify_final_decode_log, split_clip_join_lines


def _progress(seconds: float) -> str:
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return (
        f"frame=  171234 fps=287 q=-1.0 size=74980608kB "
        f"time={int(hours):02d}:{int(minutes):02d}:{secs:05.2f} bitrate=N/A speed=12x    \r"
    )


# --- ffmpeg 5.1 and 6/7 join messages ----------------------------------------

# FFmpeg 5.1 (Debian 12) logs no timestamp jump at -v info: only the cut packet.
JOIN_51 = (
    "[mpegts @ 0x55d0c0f500] Packet corrupt (stream = 0, dts = NOPTS).\n"
    "[truehd @ 0x55d0c633c0] mlpparse: Parity check failed.\n"
)


def test_ffmpeg_51_join_messages_are_found_by_the_progress_time() -> None:
    log = (
        "".join(_progress(t) for t in range(7100, 7176, 5))
        + JOIN_51
        + "".join(_progress(t) for t in range(7180, 7300, 5))
    )

    assert {item.code for item in classify_media_diagnostics(log, context="source")} == {
        "corrupt_packet",
        "unclassified_error",
    }
    remaining, joined = split_clip_join_lines(log, 1, moments=[7180.0])

    assert len(joined) == 2
    assert classify_media_diagnostics(remaining, context="source") == ()


def test_damage_far_from_every_join_is_not_set_apart_by_time() -> None:
    log = (
        _progress(100)
        + "[mpegts @ 0x1] Packet corrupt (stream = 0, dts = 4512000).\n"
        + _progress(105)
        + "".join(_progress(t) for t in range(7170, 7190, 5))
    )

    remaining, joined = split_clip_join_lines(log, 1, moments=[7180.0, 7300.0])

    assert joined == ()
    assert "corrupt_packet" in {
        item.code for item in classify_media_diagnostics(remaining, context="source")
    }


def test_only_cut_packet_messages_are_set_apart_by_time() -> None:
    other = "[h264 @ 0x2] error while decoding MB 12 34, bytestream 56\n"
    log = _progress(7175) + JOIN_51 + other + _progress(7185)

    remaining, joined = split_clip_join_lines(log, 1, moments=[7180.0])

    assert len(joined) == 2 and other.strip() not in joined
    assert "decode_error" in {
        item.code for item in classify_media_diagnostics(remaining, context="source")
    }


def test_a_log_without_progress_gives_no_time() -> None:
    remaining, joined = split_clip_join_lines(JOIN_51, 1, moments=[7180.0])

    assert joined == () and remaining == JOIN_51


def test_the_cut_last_packet_at_the_end_of_the_title_is_set_apart() -> None:
    summary = "[out#0/matroska @ 0x3] video:66599106kB audio:8588347kB muxing overhead: 0.09%\n"
    log = "".join(_progress(t) for t in range(7150, 7200, 5)) + _progress(7199.9) + JOIN_51 + summary

    remaining, joined = split_clip_join_lines(log, 0, moments=[7200.0])

    assert len(joined) == 2
    assert classify_media_diagnostics(remaining, context="source") == ()
    # Without the title end as a moment the cut packet stays source damage.
    remaining, joined = split_clip_join_lines(log, 0)
    assert joined == ()


@pytest.mark.parametrize(
    "jump",
    [
        # FFmpeg 6.1+
        "[vist#0:0/hevc @ 0x5] timestamp discontinuity (stream id=4113): -6327863200, new offset= 6327863200",
        # FFmpeg 6.1+ with a -loglevel level tag
        "[aist#0:2/truehd @ 0x6] [warning] timestamp discontinuity (stream id=4352): 1, new offset= 2",
        # FFmpeg 5.1 at debug level: no context
        "timestamp discontinuity for stream #0:1 (id=4352, type=audio): -6327868867, new offset= 6327858201",
        "[debug] timestamp discontinuity for stream #0:0 (id=4113, type=video): -1, new offset= 1",
    ],
)
def test_both_ffmpeg_formats_of_a_timestamp_jump_make_a_join_burst(jump: str) -> None:
    log = _progress(10) + JOIN_51 + jump + "\n" + _progress(20)

    assert split_clip_join_lines(log, 0) is None
    remaining, joined = split_clip_join_lines(log, 1)
    assert jump in joined and len(joined) == 3
    assert classify_media_diagnostics(remaining, context="source") == ()


def test_a_ffmpeg_51_subtitle_jump_belongs_to_the_joins() -> None:
    late = "timestamp discontinuity for stream #0:7 (id=4768, type=subtitle): -1, new offset= 1"
    log = _progress(10) + late + "\n" + _progress(20)

    _remaining, joined = split_clip_join_lines(log, 1)
    assert joined == (late,)


# --- source log classification ----------------------------------------------


def test_info_level_lines_never_reach_the_catch_all_rule() -> None:
    log = "\n".join(
        [
            "[info] Input #0, matroska,webm, from 'reference.mkv':",
            "[info]   Metadata:",
            "[info]     title           : Mission Failed: Error 404",
            "[hevc @ 0x1] [verbose] Decoding failed attempt note",
            "[Parsed_cropdetect_0 @ 0x2] [info] x1:0 x2:1919 y1:140 y2:939 crop=1920:800:0:140",
        ]
    )
    assert classify_media_diagnostics(log, context="source") == ()
    # The untagged stream header of -v info.
    header = "\n".join(
        [
            "Input #0, mpegts, from 'bluray:/disc':",
            "  Metadata:",
            "    title           : Director's Cut - Error Free",
            "  Stream #0:1[0x1100]: Audio: truehd, 48000 Hz, 7.1, s32 (24 bit)",
            "    Chapter #0:3: start 600.000, end 1200.000",
        ]
    )
    assert classify_media_diagnostics(header, context="source") == ()


def test_error_level_lines_still_reach_the_catch_all_rule() -> None:
    for line in (
        "[matroska @ 0x1] [error] Read failed somewhere",
        "Error opening input file reference.mkv.",
        "[dts @ 0x3] something failed",
    ):
        codes = {item.code for item in classify_media_diagnostics(line, context="source")}
        assert codes == {"unclassified_error"}, line


def test_a_timestamp_jump_is_a_recorded_warning_in_the_source_logs() -> None:
    line = "[vist#0:0/hevc @ 0x5] timestamp discontinuity (stream id=4113): -1, new offset= 1"

    (source,) = classify_media_diagnostics(line, context="source")
    assert source.code == "timestamp_discontinuity" and source.requires_review is False
    (generic,) = classify_media_diagnostics(line, context="generic")
    assert generic.requires_review is True


# --- final full decode -----------------------------------------------------


def test_final_decode_join_messages_verified_at_the_source_are_excused() -> None:
    source_join = ["[mpegts @ 0x5863d0c0f500] Packet corrupt (stream = 0, dts = NOPTS)."]
    log = "[matroska,webm @ 0x77] Packet corrupt (stream = 3, dts = NOPTS).\n"

    verdict = classify_final_decode_log(log, join_messages=source_join)
    assert verdict.blocking == () and len(verdict.excused_join_messages) == 1
    assert verdict.status == "passed_with_warnings"
    # One verified join message excuses one line, not more.
    twice = classify_final_decode_log(log * 2, join_messages=source_join)
    assert len(twice.blocking) == 1
    # Without the source's verified join the same line blocks.
    assert classify_final_decode_log(log).blocking


def test_final_decode_parser_notes_are_warnings_and_decode_errors_block() -> None:
    verdict = classify_final_decode_log(
        "[truehd @ 0x1] mlpparse: Parity check failed.\n"
        "[null @ 0x2] Application provided invalid, non monotonically increasing dts to muxer\n"
        "frame= 1234 fps=300 q=-0.0 size=N/A time=00:00:51.43 bitrate=N/A speed=12x\r"
    )
    assert verdict.blocking == ()
    assert len(verdict.warnings) == 2

    for line in (
        "[hevc @ 0x1] Error while decoding stream #0:0: Invalid data found when processing input",
        "[h264 @ 0x2] concealing 120 DC, 120 AC, 120 MV errors in P frame",
        "[matroska,webm @ 0x3] Read error at pos. 123456 (0x1e240)",
        "[matroska,webm @ 0x4] Length 9 indicated by an EBML number's first byte 0x00 at pos 1 exceeds max length 8.",
    ):
        assert classify_final_decode_log(line).blocking == (line,), line
    assert classify_final_decode_log("").status == "passed"


# --- mkvmerge warnings -------------------------------------------------------


def test_mkvmerge_warning_lines_are_read_from_its_console_output() -> None:
    output = (
        "mkvmerge v74.0.0 ('You Oughta Know') 64-bit\n"
        "Progress: 45%\rProgress: 100%\r\n"
        "Warning: 'audio.mka' track 0: A timestamp gap of 2.5s was found.\n"
        "The cue entries (the index) are being written...\n"
        "#GUI#warning Something else\n"
    )
    assert mkvmerge_warning_lines(output) == (
        "'audio.mka' track 0: A timestamp gap of 2.5s was found.",
        "Something else",
    )


@pytest.mark.parametrize(
    ("message", "code", "blocking"),
    [
        (
            "'/srv/jobs/a/audio-01.mka' track 0: This AC-3 track does not start with a "
            "valid AC-3 header. The first 1536 bytes will be skipped.",
            "stream_starts_mid_frame",
            False,
        ),
        (
            "'a.mka' track 0: The TrueHD track does not start on a sync frame; the first "
            "120 bytes were skipped because they are corrupt.",
            "stream_starts_mid_frame",
            False,
        ),
        ("'a.mks' track 0: A timestamp gap of 3.2s was found.", "timestamps", False),
        ("'a.mka' track 0: Non-monotonic timestamps were found.", "timestamps", False),
        ("'a.mka' track 0: The DTS-HD core has a different bit rate.", "audio_bitstream", False),
        ("'s.mks' track 0: The PGS subtitle has an empty composition.", "subtitles", False),
        ("Chapter 3 starts after the end of the file.", "chapters", False),
        ("The file has 2 unknown elements at 0x1234 which will be ignored.", "ignored_metadata", False),
        ("Something nobody has seen before.", "unknown", False),
        ("'a.mka' track 0: The file is truncated.", "data_loss", True),
        ("'a.mka' track 0: 3 frames were dropped.", "data_loss", True),
        ("'s.mks' track 2: The track is not supported and will be ignored.", "data_loss", True),
        ("'a.mka': Read error at position 123.", "data_loss", True),
        ("'a.mka' track 0: Unexpected end of file.", "data_loss", True),
    ],
)
def test_mkvmerge_warning_classes(message: str, code: str, blocking: bool) -> None:
    warning = classify_mkvmerge_warning(message)

    assert (warning.code, warning.blocking) == (code, blocking)
    assert "/srv/jobs" not in warning.message


def test_empty_mkvmerge_messages_are_skipped() -> None:
    assert classify_mkvmerge_warnings(["", "  "]) == ()
