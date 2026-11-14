from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from pathlib import Path
import shutil
import subprocess

import pytest

from bdencode.media.bluray import (
    MediaStream,
    PlaylistCandidate,
    StreamKind,
    VideoCodec,
    VideoProperties,
)
from bdencode import remux
from bdencode.remux import (
    decoded_md5_command,
    RemuxError,
    RemuxTrack,
    audio_track_name,
    container_title,
    default_duration,
    demux_outputs,
    eac3to_demux_command,
    eac3to_progress,
    embedded_core_parent,
    hevc_tier,
    kbps,
    log_findings,
    logged_frame_count,
    mastering_nits,
    match_tracks,
    parse_dovi_record,
    parse_listing,
    public_log,
    remux_mkvmerge_command,
    tags_xml,
    video_track_name,
)

# Real eac3to 3.36 output (Wine 8) of discs on the test servers.
HOUSEMAID_UHD = """\
-------------------------------------------------------------------------------                                                                               M2TS, 2 video tracks, 6 audio tracks, 3 subtitle tracks, 2:11:22, 24p /1.001
1: Chapters, 16 chapters
2: h265/HEVC, 2160p24 /1.001 (16:9), 10 bits
3: h265/HEVC, 1920x1088 24p /1.001 (30:17), 10 bits
4: TrueHD/AC3 (Atmos), English, 7.1 channels, 48kHz, dialnorm: -28dB
   (embedded: AC3, 5.1 channels, 448kbps, 48kHz)
5: AC3, English, 2.0 channels, 192kbps, 48kHz
6: AC3, Spanish, 5.1 channels, 384kbps, 48kHz
7: AC3, French, 5.1 channels, 384kbps, 48kHz
8: AC3, English, 2.0 channels, 192kbps, 48kHz, dialnorm: -25dB
9: AC3, English, 2.0 channels, 192kbps, 48kHz
10: Subtitle (PGS), English
11: Subtitle (PGS), Spanish
12: Subtitle (PGS), French
"""

SPIRITUAL_LOVE_LOG = """\
eac3to v3.36
command line: "C:\\eac3to\\eac3to.exe" S:\\BDMV\\PLAYLIST\\00001.mpls 1:chapters.txt 3:a3.thd 3:a3.ac3 7:s7.sup -progressnumbers -log=W:\\eac3to.log
------------------------------------------------------------------------------
M2TS, 1 video track, 2 audio tracks, 3 subtitle tracks, 1:29:22, 24p
1: Chapters, 12 chapters
2: h264/AVC, 1080p24 (16:9)
3: TrueHD/AC3, Chinese, 5.1 channels, 96kHz
   (embedded: AC3, 5.1 channels, 640kbps, 48kHz)
4: TrueHD/AC3, Chinese, 5.1 channels, 96kHz
   (embedded: AC3, 5.1 channels, 640kbps, 48kHz)
5: Subtitle (PGS), Chinese
6: Subtitle (PGS), Chinese
7: Subtitle (PGS), English
[v02] The video framerate is correct, but rather unusual.  <WARNING>
Creating file "chapters.txt"...
[s07] Extracting subtitle track number 7...
[a03] Extracting audio track number 3...
[a03] Extracting AC3 stream...
[a03] Extracting audio track number 3...
[a03] Extracting TrueHD stream...
[a03] Creating file "a3.thd"...
[a03] Creating file "a3.ac3"...
[s07] Creating file "s7.sup"...
Video track 2 contains 128685 frames.
Subtitle track 7 contains 1177 captions.
eac3to processing took 3 minutes, 15 seconds.
Done.
"""

QUIET_LISTING = """\
M2TS, 1 video track, 1 audio track, 1:36:16, 24p /1.001
1: Chapters, 12 chapters
2: h264/AVC, 1080p24 /1.001 (16:9)
3: DTS Master Audio, English, 5.1 channels, 24 bits, 48kHz
   (core: DTS, 5.1 channels, 1509kbps, 48kHz)
"""

MCCABE_LISTING = """\
M2TS, 1 video track, 2 audio tracks, 1 subtitle track, 2:01:11, 24p /1.001
1: Chapters, 19 chapters
2: h265/HEVC, 2160p24 /1.001 (16:9), 10 bits
3: RAW/PCM, English, 1.0 channels, 24 bits, 48kHz
4: AC3, English, 1.0 channels, 192kbps, 48kHz
5: Subtitle (PGS), English
"""


def test_the_uhd_listing_gives_every_track_with_its_properties() -> None:
    listing = parse_listing(HOUSEMAID_UHD)

    assert listing.header.startswith("M2TS, 2 video tracks, 6 audio tracks")
    assert listing.chapters is not None and listing.chapters.chapter_count == 16
    base, enhancement = listing.of_kind("video")
    assert (base.family, base.video_format, base.aspect) == ("HEVC", "2160p24 /1.001", "16:9")
    assert enhancement.video_format == "1920x1088 24p /1.001"
    truehd = listing.tracks[3]
    assert (truehd.family, truehd.atmos, truehd.channels, truehd.language) == (
        "TRUEHD",
        True,
        8,
        "English",
    )
    assert truehd.dialnorm_db == -28
    assert (truehd.embedded_ac3_channels, truehd.embedded_ac3_kbps) == (6, 448)
    assert truehd.has_embedded_ac3
    stereo = listing.tracks[4]
    assert (stereo.family, stereo.channels, stereo.kbps, stereo.sample_rate) == (
        "DD",
        2,
        192,
        48000,
    )
    assert [item.language for item in listing.of_kind("subtitle")] == [
        "English",
        "Spanish",
        "French",
    ]


def test_lpcm_and_dts_hd_ma_listings() -> None:
    pcm = parse_listing(MCCABE_LISTING).tracks[2]
    assert (pcm.family, pcm.channels, pcm.bit_depth) == ("LPCM", 1, 24)
    dts = parse_listing(QUIET_LISTING).tracks[2]
    assert (dts.family, dts.channels, dts.bit_depth) == ("DTSHDMA", 6, 24)
    assert dts.details == ("(core: DTS, 5.1 channels, 1509kbps, 48kHz)",)
    assert not dts.has_embedded_ac3


def test_a_log_is_also_a_listing_and_keeps_track_notes() -> None:
    listing = parse_listing(SPIRITUAL_LOVE_LOG)

    assert [item.number for item in listing.tracks] == [1, 2, 3, 4, 5, 6, 7]
    assert listing.tracks[1].notes == ("The video framerate is correct, but rather unusual.  <WARNING>",)
    assert logged_frame_count(SPIRITUAL_LOVE_LOG) == 128685


def test_the_unusual_framerate_warning_is_not_a_finding() -> None:
    assert log_findings(SPIRITUAL_LOVE_LOG) == ()


def test_tagged_warnings_errors_and_forced_captions_are_findings() -> None:
    log = (
        "[a03] Audio overlaps for 12ms at playtime 0:45:12.  <WARNING>\n"
        "[v02] The video bitstream is broken.  <ERROR>\n"
        "Subtitle track 7 contains 959 normal and 170 forced captions.\n"
        "Video track 2 contains 128685 frames.\n"
    )

    findings = log_findings(log)

    assert [(item.severity, item.text) for item in findings] == [
        ("warning", "[a03] Audio overlaps for 12ms at playtime 0:45:12."),
        ("error", "[v02] The video bitstream is broken."),
        ("info", "Subtitle track 7 contains 959 normal and 170 forced captions."),
    ]


def test_public_log_folds_windows_line_ends() -> None:
    assert public_log("eac3to v3.36\r\nDone.\r\n\r\n") == "eac3to v3.36\nDone.\n"


def test_progress_numbers() -> None:
    assert eac3to_progress("process: 27%\x08\x08\x08process: 31%") == 0.31
    assert eac3to_progress("nothing yet") is None


def _video(codec: str = "h264", video_codec: VideoCodec = VideoCodec.AVC, pid: int = 4113) -> MediaStream:
    return MediaStream(
        id=f"video:{pid}",
        index=0,
        pid=pid,
        kind=StreamKind.VIDEO,
        codec=codec,
        video=VideoProperties(codec=video_codec, width=1920, height=1080, frame_rate="24/1"),
    )


def _audio(pid: int, codec: str, channels: int, profile: str | None = None) -> MediaStream:
    return MediaStream(
        id=f"audio:{pid}",
        index=pid - 4351,
        pid=pid,
        kind=StreamKind.AUDIO,
        codec=codec,
        codec_profile=profile,
        channels=channels,
    )


def _subtitle(pid: int) -> MediaStream:
    return MediaStream(
        id=f"subtitle:{pid}", index=pid - 4600, pid=pid, kind=StreamKind.SUBTITLE, codec="hdmv_pgs_subtitle"
    )


def _spiritual_love() -> PlaylistCandidate:
    return PlaylistCandidate(
        playlist_id="00001",
        duration_seconds=5362.0,
        streams=(
            _video(),
            _audio(4352, "truehd", 6),
            _audio(4353, "truehd", 6),
            _subtitle(4608),
            _subtitle(4609),
            _subtitle(4610),
        ),
    )


def test_scan_streams_are_matched_to_eac3to_tracks_in_order() -> None:
    matched = match_tracks(_spiritual_love(), parse_listing(SPIRITUAL_LOVE_LOG))

    assert {key: value.number for key, value in matched.items()} == {
        "video:4113": 2,
        "audio:4352": 3,
        "audio:4353": 4,
        "subtitle:4608": 5,
        "subtitle:4609": 6,
        "subtitle:4610": 7,
    }


def test_a_codec_or_count_disagreement_refuses_the_match() -> None:
    playlist = _spiritual_love()
    wrong_codec = PlaylistCandidate(
        playlist_id="00001",
        duration_seconds=5362.0,
        streams=(_video(), _audio(4352, "dts", 6, "DTS-HD MA"), *playlist.streams[2:]),
    )
    with pytest.raises(RemuxError) as mismatch:
        match_tracks(wrong_codec, parse_listing(SPIRITUAL_LOVE_LOG))
    assert mismatch.value.code == "eac3to_track_mismatch"

    missing_subtitle = PlaylistCandidate(
        playlist_id="00001", duration_seconds=5362.0, streams=playlist.streams[:-1]
    )
    with pytest.raises(RemuxError) as count:
        match_tracks(missing_subtitle, parse_listing(SPIRITUAL_LOVE_LOG))
    assert count.value.code == "eac3to_track_count_mismatch"


def test_truehd_gets_its_embedded_ac3_as_a_compatibility_output() -> None:
    playlist = _spiritual_love()
    listing = parse_listing(SPIRITUAL_LOVE_LOG)
    matched = match_tracks(playlist, listing)
    selected = [(stream, matched[stream.id]) for stream in playlist.streams if stream.id in {"video:4113", "audio:4352", "subtitle:4610"}]

    outputs = demux_outputs(selected)

    assert [(item.track, item.filename, item.family, item.compatibility) for item in outputs] == [
        (2, "02-video.h264", "AVC", False),
        (3, "03-audio.thd", "TRUEHD", False),
        (3, "03-compatibility.ac3", "DD", True),
        (7, "07-subtitle.sup", "PGS", False),
    ]
    assert eac3to_demux_command("/discs/Spiritual Love", "00001", outputs) == [
        "bdencode-eac3to",
        "/discs/Spiritual Love",
        "S:\\BDMV\\PLAYLIST\\00001.mpls",
        "1:chapters.txt",
        "2:02-video.h264",
        "3:03-audio.thd",
        "3:03-compatibility.ac3",
        "-keepDialnorm",
        "7:07-subtitle.sup",
        "-progressnumbers",
        "-log=eac3to.log",
    ]


def test_lpcm_is_demuxed_to_flac() -> None:
    listing = parse_listing(MCCABE_LISTING)
    stream = _audio(4352, "pcm_bluray", 1)

    (output,) = demux_outputs([(stream, listing.tracks[2])])

    assert (output.filename, output.family) == ("03-audio.flac", "FLAC")


def test_a_main_10_stream_is_10_bits_even_when_the_scan_leaves_it_open() -> None:
    name = video_track_name(
        family="HEVC",
        kbps_value=63002,
        height=2160,
        frame_rate="24000/1001",
        aspect="16:9",
        profile="Main 10",
        level=153,
        hevc_tier="High",
    )

    assert "Main 10 @ Level 5.1 @ High / 4:2:0 / 10 bits" in name


def test_bdinfo_style_names() -> None:
    assert (
        video_track_name(
            family="AVC",
            kbps_value=27023,
            height=1080,
            frame_rate="24000/1001",
            aspect="16:9",
            profile="High",
            level=41,
        )
        == "MPEG-4 AVC Video / 27023 kbps / 1080p / 23.976 fps / 16:9 / High Profile 4.1"
    )
    assert (
        video_track_name(
            family="HEVC",
            kbps_value=50156,
            height=2160,
            frame_rate="24000/1001",
            aspect="16:9",
            profile="Main 10",
            level=153,
            bit_depth=10,
            hdr="HDR10",
            max_luminance_nits=1000,
            color_primaries="BT.2020",
            hevc_tier="High",
            dolby_vision="FEL",
            dolby_vision_kbps=5860,
        )
        == "MPEG-H HEVC Video / 50156 kbps / 2160p / 23.976 fps / 16:9 / Main 10 @ Level 5.1 @ High"
        " / 4:2:0 / 10 bits / 1000nits / HDR10 / BT.2020 / Dolby Vision FEL @ 5860 kbps"
    )
    assert (
        audio_track_name(family="DTSHDMA", channels=6, sample_rate=48000, kbps_value=3611, bit_depth=24)
        == "DTS-HD Master Audio / 5.1 / 48 kHz / 3611 kbps / 24-bit"
    )
    assert (
        audio_track_name(family="TRUEHD", channels=8, sample_rate=48000, kbps_value=4500, bit_depth=24, atmos=True)
        == "Dolby TrueHD/Atmos Audio / 7.1 / 48 kHz / 4500 kbps / 24-bit"
    )
    assert (
        audio_track_name(
            family="DD", channels=6, sample_rate=48000, kbps_value=640, prefix="Compatibility Track"
        )
        == "Compatibility Track / Dolby Digital Audio / 5.1 / 48 kHz / 640 kbps"
    )
    assert (
        audio_track_name(family="FLAC", channels=2, sample_rate=48000, kbps_value=752, bit_depth=16)
        == "FLAC Audio / 2.0 / 48 kHz / 752 kbps / 16-bit"
    )


def test_bitrate_is_whole_kilobits_per_second() -> None:
    assert kbps(1_000_000, 8) == 1000
    assert kbps(19_510_790_891, Decimal("5775.937500")) == 27024


def test_container_titles() -> None:
    assert container_title("The.Quiet.2005.1080p.BluRay.REMUX.AVC.DTS-HD.MA.5.1-GRP") == "The Quiet (2005)"
    assert container_title("Blade.Runner.2049.2017.2160p.UHD.BluRay.REMUX.HEVC-GRP") == "Blade Runner 2049 (2017)"
    assert container_title("Casanova.S01E04.1080p.BluRay.REMUX.AVC.DD.2.0-GRP") == "Casanova - S01E04"


def test_progressive_video_gets_an_explicit_frame_duration() -> None:
    assert default_duration("24000/1001", "progressive") == "24000/1001p"
    assert default_duration("30000/1001", "tt") is None


def test_the_mkvmerge_command_sets_the_guides_flags() -> None:
    command = remux_mkvmerge_command(
        Path("out.mkv"),
        [
            RemuxTrack(Path("02-video.h264"), "video", "zh", "MPEG-4 AVC Video / ...", default=True, default_duration="24/1p"),
            RemuxTrack(Path("03-audio.thd"), "audio", "zh", "Dolby TrueHD Audio / ...", default=True, original=True, remove_dialnorm=True),
            RemuxTrack(Path("03-compatibility.ac3"), "audio", "zh", "Compatibility Track / ...", original=True),
            RemuxTrack(Path("07-subtitle.sup"), "subtitle", "en", default=True),
        ],
        title="Spiritual Love (1987)",
        chapters=Path("chapters.txt"),
    )

    assert command[:8] == [
        "mkvmerge",
        "--output",
        "out.mkv",
        "--title",
        "Spiritual Love (1987)",
        "--chapter-language",
        "en",
        "--chapters",
    ]
    thd = command.index("03-audio.thd")
    assert command[thd - 2 : thd] == ["--compression", "0:none"]
    assert "--remove-dialog-normalization-gain" in command[command.index("02-video.h264") : thd]
    sup = command.index("07-subtitle.sup")
    assert command[command.index("03-compatibility.ac3") : sup].count("--remove-dialog-normalization-gain") == 0
    assert ["--forced-display-flag", "0:no"] == command[sup - 4 : sup - 2]
    assert command[-2:] == ["--track-order", "0:0,1:0,2:0,3:0"]


def test_global_tags() -> None:
    xml = tags_xml(imdb="tt0123456", tmdb="movie/42")
    assert xml is not None
    assert "<TargetTypeValue>50</TargetTypeValue>" in xml
    assert "<Name>TMDB</Name><String>movie/42</String>" in xml
    assert tags_xml(imdb=None, tmdb=None) is None


def test_the_scan_lists_a_truehd_pid_twice_and_eac3to_once() -> None:
    truehd = replace(_audio(4352, "truehd", 6), id="audio:4352:truehd")
    core = replace(_audio(4352, "ac3", 6), id="audio:4352:ac3")
    second = replace(_audio(4353, "truehd", 6), id="audio:4353:truehd")
    second_core = replace(_audio(4353, "ac3", 6), id="audio:4353:ac3")
    playlist = PlaylistCandidate(
        playlist_id="00001",
        duration_seconds=5362.0,
        streams=(_video(), truehd, core, second, second_core, _subtitle(4608), _subtitle(4609), _subtitle(4610)),
    )
    listing = parse_listing(SPIRITUAL_LOVE_LOG)

    matched = match_tracks(playlist, listing)

    assert matched["audio:4352:truehd"].number == 3
    assert matched["audio:4352:ac3"].number == 3
    assert matched["audio:4353:truehd"].number == 4
    assert matched["audio:4353:ac3"].number == 4
    assert embedded_core_parent(core, playlist.audio_streams) is truehd
    assert embedded_core_parent(truehd, playlist.audio_streams) is None

    # Keeping only the AC-3 of a TrueHD/AC3 track: eac3to takes it by extension.
    (only_core,) = demux_outputs([(core, matched[core.id])])
    assert (only_core.track, only_core.filename, only_core.family, only_core.compatibility) == (
        3,
        "03-audio.ac3",
        "DD",
        False,
    )


def test_the_hevc_tier_comes_from_the_first_sps(tmp_path: Path) -> None:
    high = tmp_path / "high.hevc"
    # AUD, then an SPS (NAL type 33): header 42 01, id byte, tier bit set in the profile byte.
    high.write_bytes(b"\x00\x00\x00\x01\x46\x01\x50" + b"\x00\x00\x01\x42\x01\x01\x22\x20")
    assert hevc_tier(high) == "High"
    main = tmp_path / "main.hevc"
    main.write_bytes(b"\x00\x00\x01\x42\x01\x01\x02\x20")
    assert hevc_tier(main) == "Main"
    none = tmp_path / "none.hevc"
    none.write_bytes(b"\x00\x00\x01\x46\x01\x50")
    assert hevc_tier(none) is None


def test_mastering_peak_and_dolby_vision_record() -> None:
    assert mastering_nits("G(13250,34500)B(7500,3000)R(34000,16000)WP(15635,16450)L(40000000,50)") == 4000
    assert mastering_nits(None) is None
    report = '{"streams":[{"side_data_list":[{"side_data_type":"DOVI configuration record","dv_profile":7,"rpu_present_flag":1,"el_present_flag":1,"bl_present_flag":1}]}]}'
    assert parse_dovi_record(report) == {
        "dv_profile": 7,
        "rpu_present_flag": 1,
        "el_present_flag": 1,
        "bl_present_flag": 1,
    }
    assert parse_dovi_record('{"streams":[{}]}') is None


@pytest.mark.skipif(shutil.which("sh") is None, reason="needs a POSIX shell")
def test_the_eac3to_wrapper_is_valid_shell() -> None:
    wrapper = Path(__file__).parents[1] / "install" / "bdencode-eac3to"
    assert bytes([13]) not in wrapper.read_bytes()

    checked = subprocess.run(["sh", "-n", str(wrapper)], capture_output=True, text=True)

    assert checked.returncode == 0, checked.stderr


def test_the_hash_of_a_track_does_not_depend_on_its_timestamps() -> None:
    """A multi-clip title's audio timestamps step back at the joins; -xerror then
    stopped the QC of God Forgives, I Don't (1967) although every sample matched."""

    command = decoded_md5_command("r.mkv", "a:0")
    assert "-xerror" in command
    assert command[command.index("-af") + 1] == "asetpts=N/SR/TB"
    assert "-af" not in decoded_md5_command("r.mkv", "v:0")


def test_a_track_that_runs_on_in_digital_silence_after_the_disc_is_explained() -> None:
    """The Last Whale Singer (2025, German disc): eac3to kept 0.81 s of
    silence past the playlist's end; every sample before it was the disc's."""

    ok, message = remux.judge_silent_tail(
        reference_md5="a" * 32, shared_md5="a" * 32, tail_samples=38_912, tail_peak_db=-91.0, sample_rate=48_000,
    )
    assert ok and "811 ms of digital silence" in message

    assert remux.judge_silent_tail(
        reference_md5="a" * 32, shared_md5="b" * 32, tail_samples=38_912, tail_peak_db=-91.0, sample_rate=48_000,
    ) == (False, "decodes differently from the disc")
    loud, why = remux.judge_silent_tail(
        reference_md5="a" * 32, shared_md5="a" * 32, tail_samples=38_912, tail_peak_db=-40.0, sample_rate=48_000,
    )
    assert not loud and "with sound" in why
    long_tail, why = remux.judge_silent_tail(
        reference_md5="a" * 32, shared_md5="a" * 32, tail_samples=3 * 48_000, tail_peak_db=-91.0, sample_rate=48_000,
    )
    assert not long_tail and "runs on 3.000 s" in why
    nothing, _ = remux.judge_silent_tail(
        reference_md5="a" * 32, shared_md5="a" * 32, tail_samples=0, tail_peak_db=None, sample_rate=48_000,
    )
    assert not nothing


def test_volumedetect_output_gives_samples_and_peak() -> None:
    text = "[Parsed_volumedetect_2 @ 0x1] n_samples: 233472\n[Parsed_volumedetect_2 @ 0x1] mean_volume: -91.0 dB\n[Parsed_volumedetect_2 @ 0x1] max_volume: -91.0 dB\n"
    assert remux.parse_audio_level(text) == (233_472, -91.0)
    assert remux.parse_audio_level("") == (0, None)
    command = remux.decoded_md5_command("final.mkv", "a:0", end_sample=262_474_240)
    assert command[command.index("-af") + 1] == "asetpts=N/SR/TB,atrim=end_sample=262474240"
    level = remux.audio_level_command("final.mkv", "a:0", start_sample=5)
    assert level[level.index("-af") + 1] == "asetpts=N/SR/TB,atrim=start_sample=5,volumedetect"


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs a real ffmpeg")
def test_real_ffmpeg_tells_a_silent_tail_from_the_shared_part(tmp_path) -> None:
    import subprocess

    reference = tmp_path / "reference.mkv"
    final = tmp_path / "final.mkv"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=1:sample_rate=48000",
         "-c:a", "flac", "-y", str(reference)],
        check=True,
    )
    subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(reference), "-af", "apad=pad_len=24000",
         "-c:a", "flac", "-y", str(final)],
        check=True,
    )

    def run(command: list[str]) -> str:
        completed = subprocess.run(command, capture_output=True, text=True, check=True)
        return completed.stdout + completed.stderr

    total, _ = remux.parse_audio_level(run(remux.audio_level_command(reference, "a:0")))
    assert total == 48_000
    full = remux.parse_md5(run(remux.decoded_md5_command(reference, "a:0")))
    shared = remux.parse_md5(run(remux.decoded_md5_command(final, "a:0", end_sample=total)))
    assert shared == full != remux.parse_md5(run(remux.decoded_md5_command(final, "a:0")))
    tail, peak = remux.parse_audio_level(run(remux.audio_level_command(final, "a:0", start_sample=total)))
    assert tail == 24_000 and peak is not None and peak <= remux.SILENT_TAIL_MAX_DB
