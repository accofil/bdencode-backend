from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path

import pytest

from bdencode.vapoursynth import (
    LSMAS_FIRST_SEEK_PREROLL_FRAMES,
    LSMAS_SAMPLE_WARMUP_DISTANCE,
    ReferenceScriptPlan,
    SourceFilter,
    reference_frame_preroll,
    render_reference_script,
)
from bdencode.worker import PipelineWorker

needs_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None, reason="needs a real ffmpeg"
)


def test_a_single_reference_frame_is_decoded_after_a_preroll() -> None:
    # Taffin: a fresh L-SMASH instance served keyframe 66334 as the black
    # opening picture; read after any earlier frame it was exact.
    assert reference_frame_preroll(66334) == (
        66334 - LSMAS_FIRST_SEEK_PREROLL_FRAMES,
        f"select=eq(n\\,{LSMAS_FIRST_SEEK_PREROLL_FRAMES})",
    )
    assert reference_frame_preroll(3) == (0, "select=eq(n\\,3)")
    assert reference_frame_preroll(0) == (0, "select=eq(n\\,0)")
    with pytest.raises(ValueError):
        reference_frame_preroll(-1)


@pytest.mark.parametrize("builder", ["png", "y4m"])
def test_comparison_reference_pipelines_keep_only_the_requested_frame(
    builder: str,
) -> None:
    script = Path("reference.vpy")
    if builder == "png":
        from bdencode.media.profiles import ColorMetadata

        vspipe, ffmpeg = PipelineWorker._reference_png_pipeline(
            script,
            66334,
            Path("reference.png"),
            hdr_native=True,
            source_hdr10=False,
            color=ColorMetadata(),
        )
        filters = ffmpeg[ffmpeg.index("-vf") + 1]
        assert filters.startswith(
            f"select=eq(n\\,{LSMAS_FIRST_SEEK_PREROLL_FRAMES}),"
        )
    else:
        vspipe, ffmpeg = PipelineWorker._reference_y4m_pipeline(
            script, 66334, Path("reference.y4m")
        )
        assert ffmpeg[ffmpeg.index("-vf") + 1] == (
            f"select=eq(n\\,{LSMAS_FIRST_SEEK_PREROLL_FRAMES})"
        )
    start = vspipe[vspipe.index("--start") + 1]
    end = vspipe[vspipe.index("--end") + 1]
    assert (int(start), int(end)) == (66334 - LSMAS_FIRST_SEEK_PREROLL_FRAMES, 66334)
    assert ffmpeg[ffmpeg.index("-frames:v") + 1] == "1"


@needs_ffmpeg
def test_real_ffmpeg_keeps_the_last_frame_of_the_preroll(tmp_path: Path) -> None:
    frames = LSMAS_FIRST_SEEK_PREROLL_FRAMES + 1
    piped = tmp_path / "from-vspipe.y4m"
    # What vspipe sends for --start frame-preroll --end frame.
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-v", "error", "-f", "lavfi",
            "-i", "testsrc2=size=64x64:rate=24:duration=1",
            "-frames:v", str(frames), "-f", "yuv4mpegpipe", "-y", str(piped),
        ],
        check=True,
    )
    expected = tmp_path / "expected.y4m"
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-v", "error", "-f", "yuv4mpegpipe",
            "-i", str(piped), "-vf", f"select=eq(n\\,{frames - 1})",
            "-frames:v", "1", "-f", "rawvideo", "-y", str(expected),
        ],
        check=True,
    )
    output = tmp_path / "reference.y4m"
    command = PipelineWorker._reference_y4m_pipeline(Path("r.vpy"), 100, output)[1]
    with piped.open("rb") as stdin:
        completed = subprocess.run(command, stdin=stdin, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    raw = tmp_path / "kept.raw"
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-v", "error", "-f", "yuv4mpegpipe",
            "-i", str(output), "-f", "rawvideo", "-y", str(raw),
        ],
        check=True,
    )
    first = tmp_path / "first.raw"
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-v", "error", "-f", "yuv4mpegpipe",
            "-i", str(piped), "-frames:v", "1", "-f", "rawvideo", "-y", str(first),
        ],
        check=True,
    )

    def digest(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    assert digest(raw) == digest(expected)
    assert digest(raw) != digest(first)


def _plan(tmp_path: Path, windows: tuple[tuple[int, int], ...], **kwargs: object) -> str:
    return render_reference_script(
        ReferenceScriptPlan(
            source=tmp_path / "reference.mkv",
            cache_path=tmp_path / "cache",
            script_path=tmp_path / "sample.vpy",
            sample_windows=windows,
            **kwargs,  # type: ignore[arg-type]
        )
    )


def test_a_sample_script_spends_its_first_seek_before_the_first_window(
    tmp_path: Path,
) -> None:
    content = _plan(tmp_path, ((38533, 48), (66334, 48)))
    warm = f"src.get_frame({38533 - LSMAS_SAMPLE_WARMUP_DISTANCE})"
    assert warm in content
    assert content.index(warm) < content.index("Splice")


def test_the_warmup_is_left_out_where_it_cannot_help(tmp_path: Path) -> None:
    assert "get_frame" not in _plan(tmp_path, ((10, 48), (500, 48)))
    assert "get_frame" not in _plan(
        tmp_path, ((38533, 48),), source_filter=SourceFilter.BESTSOURCE
    )
    assert "get_frame" not in _plan(tmp_path, ())
