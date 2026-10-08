"""Which comparison images are published, and uploading several of them at once."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from bdencode.worker import PipelineWorker, _images_to_upload

HDR_SET = [
    Path("01-I-f000000000-reference.png"),
    Path("01-I-f000000000-reference-sdr.png"),
    Path("01-I-f000000000-encode.png"),
    Path("01-I-f000000000-encode-sdr.png"),
    Path("audio-01-source-spectrum.png"),
]


def names(paths: list[Path]) -> list[str]:
    return [path.name for path in paths]


def test_the_sdr_set_publishes_the_tone_mapped_views_and_the_spectrograms() -> None:
    assert names(_images_to_upload(HDR_SET, "sdr")) == [
        "01-I-f000000000-reference-sdr.png",
        "01-I-f000000000-encode-sdr.png",
        "audio-01-source-spectrum.png",
    ]
    assert names(_images_to_upload(HDR_SET, "native")) == [
        "01-I-f000000000-reference.png",
        "01-I-f000000000-encode.png",
        "audio-01-source-spectrum.png",
    ]
    assert _images_to_upload(HDR_SET, "all") == HDR_SET


def test_an_sdr_title_keeps_its_pictures_in_the_sdr_set() -> None:
    sdr_title = [Path("01-I-f000000000-reference.png"), Path("01-I-f000000000-encode.png")]
    assert _images_to_upload(sdr_title, "sdr") == sdr_title


class ParallelHost:
    supports_parallel_upload = True

    def __init__(self, *, fail: str | None = None) -> None:
        self.active = 0
        self.peak = 0
        self.done: list[str] = []
        self.fail = fail
        self.lock = threading.Lock()


def upload_with(host: ParallelHost):
    def upload_one(png: Path) -> None:
        with host.lock:
            host.active += 1
            host.peak = max(host.peak, host.active)
        time.sleep(0.05)
        with host.lock:
            host.active -= 1
        if png.name == host.fail:
            raise RuntimeError(f"upload of {png.name} failed")
        with host.lock:
            host.done.append(png.name)

    return upload_one


def test_a_parallel_host_uploads_a_few_images_at_once() -> None:
    host = ParallelHost()
    pngs = [Path(f"{index:02d}.png") for index in range(9)]

    PipelineWorker._upload_concurrently(host, upload_with(host), pngs)  # type: ignore[arg-type]

    assert sorted(host.done) == names(pngs)
    assert 1 < host.peak <= 3


def test_after_a_failure_no_new_upload_starts_and_the_error_surfaces() -> None:
    host = ParallelHost(fail="01.png")
    pngs = [Path(f"{index:02d}.png") for index in range(12)]

    with pytest.raises(RuntimeError, match="01.png failed"):
        PipelineWorker._upload_concurrently(host, upload_with(host), pngs)  # type: ignore[arg-type]

    # Only the uploads already in flight could finish.
    assert len(host.done) < len(pngs) - 1


def test_hosts_without_parallel_support_upload_in_order() -> None:
    host = ParallelHost()
    host.supports_parallel_upload = False  # type: ignore[misc]
    pngs = [Path(f"{index:02d}.png") for index in range(5)]

    PipelineWorker._upload_concurrently(host, upload_with(host), pngs)  # type: ignore[arg-type]

    assert host.done == names(pngs)
    assert host.peak == 1
