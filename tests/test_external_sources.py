"""Fitting tracks from another source: the map, the sound, the subtitles, the rules."""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path

import pytest

from bdencode.external import render, source, spec, subtitles
from bdencode.previews import PreviewRequest, fit_excerpt_command
from bdencode.worker import (
    _selection_hash,
    external_final_audio_order,
    external_merge_command,
)

FILM = Fraction(24000, 1001)


def test_pal_speed_is_an_exact_ratio_and_one_frame_is_whole_samples() -> None:
    ratio = render.speed_ratio("frame-locked", Fraction(25), FILM)
    assert ratio == Fraction(1001, 960)
    assert render.samples_per_frame(FILM) == 2002
    assert render.speed_ratio("time-locked", Fraction(25), FILM) == 1


def test_restoring_pitch_is_rational_so_it_cannot_drift() -> None:
    chain = render.stretch_filter(Fraction(1001, 960), render.PITCH_RESTORE, 48_000)
    assert chain == "aresample=50050:resampler=soxr:precision=28,asetrate=48000"
    assert "rubberband" in render.stretch_filter(Fraction(1001, 960), render.PITCH_KEEP, 48_000)
    assert render.stretch_filter(Fraction(1), render.PITCH_RESTORE, 48_000) is None
    with pytest.raises(render.RenderError):
        render.stretch_filter(Fraction(1001, 960), "other", 48_000)


def test_only_dolby_decoding_turns_off_dynamic_range_compression() -> None:
    args = ["-i", "x.mkv"]
    with_drc = render.stretch_command(args, "a:0", "ac3", 2, Fraction(1), "restore", 48_000, Path("o"))
    without = render.stretch_command(args, "a:0", "dts", 2, Fraction(1), "restore", 48_000, Path("o"))
    assert with_drc[with_drc.index("-drc_scale") + 1] == "0"
    assert "-drc_scale" not in without


def test_encoding_keeps_a_lossy_sources_rate_and_never_downmixes() -> None:
    assert render.choose_encoding("ac3", 2, 224_000, -27) == render.Encoding("ac3", 224_000, -27)
    assert render.choose_encoding("ac3", 6, 448_000, None).bit_rate == 448_000
    assert render.choose_encoding("flac", 6, None, None).bit_rate == 640_000
    assert render.choose_encoding("flac", 2, None, None).bit_rate == 384_000
    assert render.choose_encoding("ac3", 2, 224_000, 0).dialnorm is None
    with pytest.raises(render.RenderError):
        render.choose_encoding("truehd", 8, None, None)


def test_a_track_needing_no_change_is_not_encoded_again() -> None:
    one = [{"target_start": 0, "target_end": 100, "offset": 5}]
    assert render.copy_is_possible(one, Fraction(1))
    assert not render.copy_is_possible(one, Fraction(1001, 960))
    assert not render.copy_is_possible(one * 2, Fraction(1))


def test_pieces_follow_the_frames_exactly() -> None:
    segments = [
        {"target_start": 140, "target_end": 3347, "offset": -140},
        {"target_start": 3352, "target_end": 5033, "offset": -145},
    ]
    first, second = render.plan_pieces(segments, FILM)
    assert first == render.Piece(140 * 2002, 3347 * 2002, 0)
    assert second == render.Piece(3352 * 2002, 5033 * 2002, (3352 - 145) * 2002)
    assert render.plan_pieces(segments[:1], FILM, audio_offset_samples=100)[0].source == -100


def test_assembly_places_pieces_by_sample_and_silences_the_rest(tmp_path: Path) -> None:
    np = pytest.importorskip("numpy")
    source_path = tmp_path / "in.f32"
    values = np.arange(1, 20_001, dtype=np.float32)
    source_path.write_bytes(np.stack((values, -values), axis=1).tobytes())
    output = tmp_path / "out.f32"
    report = render.assemble(
        source_path,
        output,
        channels=2,
        total_samples=4_000,
        pieces=[render.Piece(1_000, 2_000, 5_000), render.Piece(3_000, 3_500, 100)],
    )
    result = np.fromfile(output, dtype=np.float32).reshape(-1, 2)
    assert len(result) == 4_000
    assert report["silent_samples"] == 2_500
    assert result[:1_000].max() == 0 and result[2_000:3_000].max() == 0 and result[3_500:].max() == 0
    # Between the fades the samples are the source's own, at the planned place.
    assert result[1_500, 0] == 5_501
    assert result[1_500, 1] == -5_501
    assert result[3_250, 0] == 351
    # The joints fade, so they cannot click.
    assert abs(result[1_000, 0]) < 1
    assert abs(result[1_999, 0]) < 1


def test_assembly_drops_the_encoders_priming_from_the_start(tmp_path: Path) -> None:
    np = pytest.importorskip("numpy")
    source_path = tmp_path / "in.f32"
    source_path.write_bytes(np.arange(1, 5_001, dtype=np.float32).tobytes())
    output = tmp_path / "out.f32"
    render.assemble(
        source_path,
        output,
        channels=1,
        total_samples=4_000,
        pieces=[render.Piece(0, 4_000, 0)],
        priming_samples=256,
    )
    result = np.fromfile(output, dtype=np.float32)
    assert len(result) == 3_744
    assert result[0] == 257


def test_assembly_survives_a_source_ending_early_or_starting_late(tmp_path: Path) -> None:
    np = pytest.importorskip("numpy")
    source_path = tmp_path / "in.f32"
    source_path.write_bytes(np.ones(1_000, dtype=np.float32).tobytes())
    output = tmp_path / "out.f32"
    render.assemble(
        source_path,
        output,
        channels=1,
        total_samples=3_000,
        pieces=[render.Piece(0, 3_000, -500)],
    )
    result = np.fromfile(output, dtype=np.float32)
    assert len(result) == 3_000
    assert result[:500].max() == 0
    assert result[1_000] == 1
    assert result[1_600:].max() == 0


SRT = """1
00:00:04,000 --> 00:00:06,000
Before the title has it

2
00:00:10,000 --> 00:00:12,500
Elso sor
masodik

3
00:01:00,000 --> 00:01:02,000
Utana
"""


def test_subtitles_follow_their_picture_through_speed_and_splices() -> None:
    cues = subtitles.parse_srt(SRT)
    assert [cue.start_ms for cue in cues] == [4_000, 10_000, 60_000]
    segments = [
        # Source frames 200..1000 are title frames 300..1100.
        {"target_start": 300, "target_end": 1100, "offset": -100},
        # Source frames 1200..2000 are title frames 1400..2200: 200 source frames removed.
        {"target_start": 1400, "target_end": 2200, "offset": -200},
    ]
    moved, counts = subtitles.retime(cues, segments, target_fps=FILM, donor_grid_fps=Fraction(25))
    assert counts == {"kept": 2, "dropped": 1, "clipped": 0}
    # 10 s at 25 fps is source frame 250, title frame 350.
    assert moved[0].start_ms == round(350 * 1001 / 24)
    assert moved[0].text == "Elso sor\nmasodik"
    # 60 s is source frame 1500, title frame 1700.
    assert moved[1].start_ms == round(1700 * 1001 / 24)


def test_a_subtitle_cut_by_a_splice_is_clipped_not_shifted() -> None:
    cues = [subtitles.Cue(39_000, 49_000, "over the splice")]
    segments = [
        {"target_start": 0, "target_end": 1000, "offset": 0},
        {"target_start": 1000, "target_end": 2000, "offset": 200},
    ]
    moved, counts = subtitles.retime(cues, segments, target_fps=FILM, donor_grid_fps=Fraction(25))
    assert counts["clipped"] == 1
    assert moved[0].start_ms == round(975 * 1001 / 24)
    assert moved[0].end_ms == round(1025 * 1001 / 24)


def test_old_hungarian_subtitle_files_are_read_as_windows_1250() -> None:
    assert subtitles.decode_text("árvíztűrő".encode("cp1250")) == "árvíztűrő"
    assert subtitles.decode_text("árvíztűrő".encode("utf-8-sig")) == "árvíztűrő"
    with pytest.raises(subtitles.SubtitleError):
        subtitles.parse_srt("no cues in this")


def test_rendered_srt_reads_back_the_same() -> None:
    cues = [subtitles.Cue(1_500, 3_250, "egy\nketto"), subtitles.Cue(3_600_001, 3_601_000, "harom")]
    assert subtitles.parse_srt(subtitles.render_srt(cues)) == cues


LSDVD = """Disc Title: ISTEN
Title: 01, Length: 01:47:48.800 Chapters: 17, Cells: 18, Audio streams: 02, Subpictures: 00
\tVTS: 01, TTN: 01, FPS: 25.00, Format: PAL, Aspect ratio: 4/3, Width: 720, Height: 576, DF: ?
\tPalette: 286df0 51f05a
\tAudio: 1, Language: hu - Magyar, Format: ac3, Frequency: 48000, Quantization: drc, Channels: 2, AP: 0, Content: Undefined, Stream id: 0x80
\tAudio: 2, Language: xx - Unknown, Format: ac3, Frequency: 48000, Quantization: drc, Channels: 6, AP: 0, Content: Undefined, Stream id: 0x81
Title: 02, Length: 00:00:40.560 Chapters: 01, Cells: 01, Audio streams: 01, Subpictures: 00
\tVTS: 02, TTN: 01, FPS: 25.00, Format: PAL, Aspect ratio: 16/9, Width: 720, Height: 576, DF: Letterbox
Longest track: 01
"""


class _Done:
    def __init__(self, stdout: str) -> None:
        self.stdout = stdout


def test_dvd_listing_gives_the_longest_title_and_its_streams() -> None:
    titles = source.parse_lsdvd(LSDVD)
    assert [title["number"] for title in titles] == [1, 2]
    assert titles[0]["seconds"] == pytest.approx(6468.8)
    info = source.probe_dvd(source.KIND_DVD_IMAGE, Path("x.iso"), run=lambda *a, **k: _Done(LSDVD))
    assert info.fps == "25"
    assert info.title_set == 1
    assert [track.stream for track in info.tracks] == ["#0x80", "#0x81"]
    assert info.tracks[0].language == "hu"
    assert info.tracks[1].language is None
    assert info.tracks[1].channels == 6


def test_image_members_of_the_title_set_come_in_order() -> None:
    listing = """2023-07-17 15:54:33 .....        18432        18432  VIDEO_TS/VIDEO_TS.IFO
2023-07-17 15:57:29 .....   1073694720   1073694720  VIDEO_TS/VTS_01_2.VOB
2023-07-17 15:57:29 .....   1073694720   1073694720  VIDEO_TS/VTS_01_1.VOB
2023-07-17 15:54:34 .....      1492992      1492992  VIDEO_TS/VTS_01_0.VOB
2023-07-17 15:57:29 .....   1073694720   1073694720  VIDEO_TS/VTS_02_1.VOB
"""
    assert source.image_vob_names(listing, 1) == ["VIDEO_TS/VTS_01_1.VOB", "VIDEO_TS/VTS_01_2.VOB"]


def test_a_release_folder_with_one_image_means_that_image(tmp_path: Path) -> None:
    (tmp_path / "r.iso").write_bytes(b"x")
    (tmp_path / "r.nfo").write_bytes(b"x")
    assert source.resolve_kind(tmp_path) == (source.KIND_DVD_IMAGE, tmp_path / "r.iso")
    (tmp_path / "s.iso").write_bytes(b"x")
    with pytest.raises(source.ExternalSourceError):
        source.resolve_kind(tmp_path)
    video_ts = tmp_path / "d" / "VIDEO_TS"
    video_ts.mkdir(parents=True)
    assert source.resolve_kind(tmp_path / "d") == (source.KIND_DVD_FOLDER, video_ts)
    with pytest.raises(source.ExternalSourceError):
        source.resolve_kind(tmp_path / "missing")
    (tmp_path / "t.txt").write_text("x")
    with pytest.raises(source.ExternalSourceError):
        source.resolve_kind(tmp_path / "t.txt")


def test_a_pipe_in_a_vob_path_is_refused() -> None:
    assert source.input_arguments(source.KIND_FILE, Path("a.mkv")) == ["-i", "a.mkv"]
    args = source.input_arguments(source.KIND_DVD_FOLDER, Path("x"), [Path("a.vob"), Path("b.vob")])
    assert args[-1] == "concat:a.vob|b.vob"
    with pytest.raises(source.ExternalSourceError):
        source.input_arguments(source.KIND_DVD_FOLDER, Path("x"), [Path("a|c.vob"), Path("b.vob")])
    with pytest.raises(source.ExternalSourceError):
        source.input_arguments(source.KIND_DVD_IMAGE, Path("x"))


def test_decimal_frame_rates_mean_the_usual_exact_ones() -> None:
    assert source.exact_fps("24000/1001") == FILM
    assert source.exact_fps("23.976") == FILM
    assert source.exact_fps("29.97") == Fraction(30000, 1001)
    assert source.exact_fps("25") == 25
    assert source.exact_fps(None) is None
    assert source.exact_fps("nonsense") is None


GOOD = {
    "id": "e1",
    "path": "/x/y.iso",
    "tracks": [{"stream": "#0x80", "language": "hun", "default": True, "position": 0, "pitch": "restore"}],
    "subtitles": [{"path": "/x/y.srt", "language": "hun"}],
}


def test_the_selection_contract() -> None:
    parsed = spec.parse_external_sources([GOOD])
    assert parsed[0].tracks[0].default is True
    assert parsed[0].subtitles[0].forced is False
    assert spec.parse_external_sources(None) == ()


@pytest.mark.parametrize(
    "broken",
    [
        {**GOOD, "other": 1},
        {**GOOD, "id": "Bad Id"},
        {**GOOD, "tracks": [], "subtitles": []},
        {**GOOD, "tracks": [{"stream": "a; rm", "language": "hun"}]},
        {**GOOD, "tracks": [{"stream": "a:0", "language": "h u n"}]},
        {**GOOD, "tracks": [{"stream": "a:0", "language": "hun", "pitch": "other"}]},
        {**GOOD, "tracks": [{"stream": "a:0", "language": "hun", "position": -1}]},
        {**GOOD, "tracks": [{"stream": "a:0", "language": "hun"}] * 2},
        {**GOOD, "subtitles": [{"path": "/x/y.sup", "language": "hun"}]},
        {**GOOD, "approved_map_sha256": "abc"},
    ],
)
def test_a_broken_selection_is_refused(broken: dict) -> None:
    with pytest.raises(spec.ExternalSpecError):
        spec.parse_external_sources([broken])


def test_two_sources_cannot_share_an_id() -> None:
    with pytest.raises(spec.ExternalSpecError):
        spec.parse_external_sources([GOOD, GOOD])


def test_approving_a_fit_does_not_repeat_the_titles_own_stages() -> None:
    plain = {"playlist_id": "1", "tracks": []}
    assert _selection_hash(plain) == _selection_hash(
        {**plain, "external_sources": [{**GOOD, "approved_map_sha256": "a" * 64}]}
    )
    assert _selection_hash(plain) != _selection_hash({"playlist_id": "2", "tracks": []})


BASE_TRACKS = [
    {"id": 0, "type": "video"},
    {"id": 1, "type": "audio"},
    {"id": 2, "type": "audio"},
    {"id": 3, "type": "subtitles"},
]


def _audio(position: int, default: bool = False, language: str = "hun") -> dict:
    return {
        "track": spec.ExternalTrack(stream="#0x80", language=language, default=default, position=position),
        "report": {"channels": 2, "codec": "ac3", "encoding": {"codec": "ac3"}},
        "path": Path(f"t{position}.ac3"),
    }


def test_the_external_track_goes_where_it_was_asked() -> None:
    assert external_final_audio_order(BASE_TRACKS, [_audio(0)]) == [("external", 0), 0, 1]
    assert external_final_audio_order(BASE_TRACKS, [_audio(1)]) == [0, ("external", 0), 1]
    assert external_final_audio_order(BASE_TRACKS, [_audio(9)]) == [0, 1, ("external", 0)]


def test_merge_command_orders_tracks_and_moves_the_default() -> None:
    subtitle = {
        "subtitle": spec.ExternalSubtitle(path="s.srt", language="hun", default=True),
        "path": Path("s.srt"),
    }
    command = external_merge_command(
        Path("out.mkv"),
        Path("base.mkv"),
        BASE_TRACKS,
        [_audio(0, default=True)],
        [subtitle],
        title="T",
        video_start_seconds=0.005,
    )
    assert command[command.index("--track-order") + 1] == "0:0,1:0,0:1,0:2,0:3,2:0"
    # The title's own audio gives up the default flag, before its input.
    assert command.index("1:no") < command.index("base.mkv")
    assert command.index("2:no") < command.index("base.mkv")
    # Both fitted streams start with the picture.
    assert command.count("0:5") == 2
    assert "0:hun" in command
    assert "0:Hungarian DD 2.0" in command
    assert "0:UTF-8" in command


def test_merge_keeps_the_titles_default_when_no_external_track_wants_it() -> None:
    command = external_merge_command(
        Path("o.mkv"), Path("b.mkv"), BASE_TRACKS, [_audio(2)], [], title="T", video_start_seconds=0.0
    )
    assert "1:no" not in command
    assert "0:no" in command


def test_the_ear_test_puts_each_track_in_its_own_ear() -> None:
    request = PreviewRequest(100, 20, 480)
    command = fit_excerpt_command(
        Path("ref.mkv"), Path("fit.ac3"), Path("o.mp4"), request, audio="both", hdr=False, video_start_seconds=0.042
    )
    graph = command[command.index("-filter_complex") + 1]
    assert "[0:a:0]" in graph and "[1:a:0]" in graph and "join=inputs=2:channel_layout=stereo" in graph
    # The title's picture is sought by its own timestamps.
    assert command[command.index("-ss") + 1] == "100.042000"
    fitted = fit_excerpt_command(
        Path("ref.mkv"), Path("fit.ac3"), Path("o.mp4"), request, audio="fitted", hdr=False
    )
    assert fitted[fitted.index("-map") + 3] == "1:a:0"


def test_a_subtitle_is_burned_into_the_excerpt_on_the_films_clock() -> None:
    command = fit_excerpt_command(
        Path("ref.mkv"),
        Path("fit.ac3"),
        Path("o.mp4"),
        PreviewRequest(60, 10, 360),
        audio="fitted",
        hdr=False,
        subtitle=Path("/a:b/s'.srt"),
    )
    graph = command[command.index("-filter_complex") + 1]
    assert "setpts=PTS+60.0/TB,subtitles=" in graph
    assert "\\:" in graph and "\\'" in graph


SHA = "c" * 64


@pytest.fixture
def review_api(tmp_path: Path):
    from fastapi.testclient import TestClient

    from bdencode.api import create_app
    from bdencode.config import Settings
    from bdencode.db import Database
    from bdencode.models import JobCreate

    storage = tmp_path / "storage"
    storage.mkdir()
    settings = Settings(data_root=tmp_path / "encode", source_roots=(storage,)).validate()
    settings.create_directories()
    database = Database(tmp_path / "state.sqlite3")
    database.initialize()
    job = database.create_job(JobCreate(source_path=str(storage)))
    client = TestClient(create_app(database, settings=settings), base_url="http://127.0.0.1")
    directory = settings.job_root(job.id) / "work" / "external" / "e1"
    directory.mkdir(parents=True)
    (directory / "review.json").write_text(
        '{"id": "e1", "map_sha256": "' + SHA + '", "tracks": [], "subtitles": []}', encoding="utf-8"
    )
    return client, database, job, storage


def _awaiting_review(database, job) -> None:
    from bdencode.models import JobState
    from bdencode.queue import JobQueue

    queue = JobQueue(database)
    queue.claim_next()
    queue.advance(job.id, JobState.AWAITING_SELECTION, message="scanned")
    database.set_selection(job.id, {"tracks": [], "external_sources": [GOOD]})
    queue.advance(job.id, JobState.ENCODING, message="claimed")
    queue.needs_review(job.id, message="fit waits", details={})


def test_the_review_route_shows_what_was_fitted(review_api) -> None:
    client, database, job, _storage = review_api
    _awaiting_review(database, job)
    items = client.get(f"/api/v1/jobs/{job.id}/external-review").json()["items"]
    assert items[0]["review"]["map_sha256"] == SHA
    assert items[0]["selection"]["id"] == "e1"


def test_only_the_shown_map_can_be_approved(review_api) -> None:
    client, database, job, _storage = review_api
    _awaiting_review(database, job)
    url = f"/api/v1/jobs/{job.id}/external-review/e1/approve"
    assert client.post(url, json={"map_sha256": "d" * 64}).status_code == 409
    assert client.post(url, json={"map_sha256": "nonsense"}).status_code == 422
    response = client.post(url, json={"map_sha256": SHA})
    assert response.status_code == 200, response.text
    stored = database.get_job(job.id)
    assert stored.selection["external_sources"][0]["approved_map_sha256"] == SHA


def test_a_new_pitch_needs_a_new_approval(review_api) -> None:
    client, database, job, _storage = review_api
    _awaiting_review(database, job)
    url = f"/api/v1/jobs/{job.id}/external-review/e1"
    assert client.post(f"{url}/pitch", json={"stream": "a:9", "pitch": "keep"}).status_code == 404
    assert client.post(f"{url}/pitch", json={"stream": "#0x80", "pitch": "keep"}).status_code == 200
    source = database.get_job(job.id).selection["external_sources"][0]
    assert source["tracks"][0]["pitch"] == "keep"
    assert source["approved_map_sha256"] is None


def test_leaving_the_source_out_removes_it_from_the_selection(review_api) -> None:
    client, database, job, _storage = review_api
    _awaiting_review(database, job)
    assert client.post(f"/api/v1/jobs/{job.id}/external-review/e1/discard").status_code == 200
    assert "external_sources" not in database.get_job(job.id).selection


def test_a_review_action_needs_the_review_state(review_api) -> None:
    client, _database, job, _storage = review_api
    response = client.post(f"/api/v1/jobs/{job.id}/external-review/e1/approve", json={"map_sha256": SHA})
    assert response.status_code == 409


def test_a_source_outside_the_roots_cannot_be_probed(review_api, tmp_path: Path) -> None:
    client, _database, _job, storage = review_api
    assert client.get("/api/v1/external-sources/probe", params={"path": str(tmp_path)}).status_code >= 400
    assert client.get("/api/v1/external-sources/probe", params={"path": str(storage / "none.iso")}).status_code >= 400


def test_a_review_route_rejects_a_bad_source_id(review_api) -> None:
    client, database, job, _storage = review_api
    _awaiting_review(database, job)
    response = client.post(
        f"/api/v1/jobs/{job.id}/external-review/..%2F..%2Fe/excerpts", json={"audio": "both"}
    )
    assert response.status_code in {404, 422}
