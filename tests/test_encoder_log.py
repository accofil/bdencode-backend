"""The encoder log: ffmpeg's progress noise out, settings and statistics kept."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bdencode.api import create_app
from bdencode.config import Settings
from bdencode.db import Database
from bdencode.encoder_log import clean_encoder_log, read_encoder_log
from bdencode.models import JobCreate

PROGRESS_BLOCK = (
    "frame=1\nfps=0.00\nstream_0_0_q=0.0\nbitrate=N/A\ntotal_size=603\nout_time_us=0\n"
    "out_time_ms=0\nout_time=00:00:00.000000\ndup_frames=0\ndrop_frames=0\nspeed=N/A\nprogress=continue\n"
)
# ffmpeg also repeats its in-place statistics line with carriage returns.
STATS_CR = "frame=  100 fps=8.0 q=24.0 size=  1024kB time=00:00:04.17 bitrate=2012.6kbits/s speed=0.34x    \r"

RAW = (
    "ffmpeg stats and -progress period set to 2.\n"
    "Input #0, yuv4mpegpipe, from 'pipe:0':\n"
    "[libx264 @ 0x1] 264 - core 164 - options: cabac=1 ref=4 crf=17.5 aq=3:0.80\n"
    "Output #0, matroska, to '/home/accofil/encode/jobs/164d5c19-e9e3-417e-8a9f-e53b87e09029/work/video-encoded.partial.mkv':\n"
    + PROGRESS_BLOCK * 50
    + STATS_CR * 5
    + "frame=139518 fps=8.2 q=-1.0 Lsize=14539218kB time=01:36:58.93 bitrate=20468.6kbits/s speed=0.343x    \n"
    + "frame=139518\nfps=8.23\nprogress=end\n"
    + "video:14538059kB audio:0kB subtitle:0kB other streams:0kB global headers:0kB muxing overhead: 0.007977%\n"
    + "[libx264 @ 0x1] frame I:822   Avg QP:14.68  size:297126\n"
    + "[libx264 @ 0x1] frame P:25151 Avg QP:17.62  size:136927\n"
    + "[libx264 @ 0x1] kb/s:20466.49\n"
)


def test_progress_noise_goes_and_the_final_statistics_stay() -> None:
    cleaned = clean_encoder_log(RAW).splitlines()

    assert not any(line.startswith(("fps=", "out_time", "progress=", "total_size=", "speed=")) for line in cleaned)
    assert sum(line.startswith("frame=") for line in cleaned) == 1  # only the final totals
    assert cleaned.index(next(line for line in cleaned if line.startswith("frame=139518 fps=8.2"))) + 1 == cleaned.index(
        next(line for line in cleaned if line.startswith("video:"))
    )
    assert "[libx264 @ 0x1] kb/s:20466.49" in cleaned
    assert len(cleaned) < 15


def test_the_job_log_is_summarised_and_its_paths_are_masked(tmp_path: Path) -> None:
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "video-encode.log").write_bytes(RAW.encode("utf-8"))

    log = read_encoder_log(tmp_path)

    assert log["available"] and log["finished"] and log["encoder"] == "x264"
    assert log["options"] == "cabac=1 ref=4 crf=17.5 aq=3:0.80"
    assert log["summary"][0].startswith("frame=139518 fps=8.2")
    assert log["summary"][-1] == "[libx264 @ 0x1] kb/s:20466.49"
    assert "/home/accofil" not in log["text"] and "164d5c19" not in log["text"]
    assert log["raw_bytes"] == len(RAW.encode("utf-8"))


def test_a_running_encode_has_a_log_but_no_summary_yet(tmp_path: Path) -> None:
    (tmp_path / "logs").mkdir()
    running = RAW.split("frame=139518 fps=8.2", 1)[0]
    (tmp_path / "logs" / "video-encode.log").write_bytes(running.encode("utf-8"))

    log = read_encoder_log(tmp_path)

    assert log["available"] and not log["finished"] and log["summary"] == []


def test_no_log_means_not_available(tmp_path: Path) -> None:
    assert read_encoder_log(tmp_path) == {"available": False}


def test_a_linked_log_is_not_followed(tmp_path: Path) -> None:
    outside = tmp_path / "secret.log"
    outside.write_text("[libx264 @ 0x1] kb/s:1\n", encoding="utf-8")
    (tmp_path / "logs").mkdir()
    try:
        (tmp_path / "logs" / "video-encode.log").symlink_to(outside)
    except OSError:
        pytest.skip("symbolic links need permission")

    assert read_encoder_log(tmp_path) == {"available": False}


@pytest.fixture
def api(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    settings = Settings(data_root=tmp_path / "data", source_roots=(source,)).validate()
    settings.create_directories()
    database = Database(tmp_path / "state.sqlite3")
    job = database.create_job(JobCreate(source_path=str(source / "Disc"), name="Disc"))
    return TestClient(create_app(database, settings=settings)), settings, job


def test_the_page_reads_the_log_and_can_download_it(api) -> None:
    client, settings, job = api
    assert client.get(f"/api/v1/jobs/{job.id}/encoder-log").json() == {"available": False}
    assert client.get(f"/api/v1/jobs/{job.id}/encoder-log.txt").status_code == 404

    logs = settings.job_root(job.id) / "logs"
    logs.mkdir(parents=True)
    (logs / "video-encode.log").write_bytes(RAW.encode("utf-8"))

    body = client.get(f"/api/v1/jobs/{job.id}/encoder-log").json()
    assert body["finished"] is True and body["line_count"] < 15
    download = client.get(f"/api/v1/jobs/{job.id}/encoder-log.txt")
    assert download.status_code == 200
    assert download.headers["content-type"].startswith("text/plain")
    assert 'filename="x264-encode-log.txt"' in download.headers["content-disposition"]
    assert "Avg QP:14.68" in download.text and "/home/accofil" not in download.text
    assert client.get("/api/v1/jobs/no-such-job/encoder-log").status_code == 404
