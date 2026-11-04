"""Which frame of the external source shows each frame of the title.

Both videos are reduced to 64x36 grey signatures.  The search goes from coarse
to exact:

1. shot-change rhythm finds the rough offset every 25 seconds; it does not care
   about cropping or grading;
2. those offsets give frame pairs, from which the picture geometry follows (a
   PAL DVD is often a 1.78 crop of a 2.39 film);
3. a best-path search over per-frame similarity gives the offset of every frame,
   allowing for a panning crop;
4. a splice removes frames from one side only, so each change of offset is
   re-solved as one splice between its two trusted neighbours.

The offset ``k`` means: title frame ``m`` shows source frame ``m + k``.  A frame
locked source (PAL speed-up: every film frame kept, shown faster) maps frame for
frame.  A time locked source (the same running time at another frame rate) is
first sampled onto the title's frame grid, so the same search serves both.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any, Sequence

SIGNATURE_WIDTH = 64
SIGNATURE_HEIGHT = 36

COARSE_WINDOW = 2400
COARSE_STEP = 600
COARSE_MIN_SCORE = 0.25
COARSE_MIN_MARGIN = 1.3

# The donor grid: the middle of the picture, inside any letterbox.
_GRID_Y = (12, 25)
_GRID_X = (14, 50)
_CENTRE_X = (SIGNATURE_WIDTH - 1) / 2
_CENTRE_Y = (SIGNATURE_HEIGHT - 1) / 2

BLOCK = 600
SPREAD = 30
JUMP_PENALTY = 10.0

# What a run of equal offsets must show to be trusted.  A short run must look
# clearly alike; a long one may be weak, because different title cards or a worn
# print lower the similarity without moving the film.
TRUST_SHORT_FRAMES = 24
TRUST_SHORT_SIMILARITY = 0.75
TRUST_LONG_FRAMES = 240
TRUST_LONG_SIMILARITY = 0.40
SPLICE_MARGIN = 240
MIN_RUN_ADVANTAGE = 0.03


class FrameMapError(ValueError):
    """The two pictures could not be matched."""


@dataclass(frozen=True, slots=True)
class Geometry:
    """Where a donor signature point lies in the title's signature."""

    scale_x: float
    scale_y: float
    shift_x: float
    shift_y: float
    similarity: float
    pan_shifts: tuple[int, ...] = (0,)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scale_x": self.scale_x,
            "scale_y": self.scale_y,
            "shift_x": self.shift_x,
            "shift_y": self.shift_y,
            "similarity": round(self.similarity, 4),
            "pan_shifts": list(self.pan_shifts),
        }


def load_signature(path: Path) -> Any:
    """The frames of a raw grey signature as ``frames x 36 x 64``, memory mapped."""

    import numpy as np

    size = SIGNATURE_WIDTH * SIGNATURE_HEIGHT
    data = np.memmap(path, dtype=np.uint8, mode="r")
    frames = data.size // size
    if frames == 0:
        raise FrameMapError(f"{path.name} holds no frames")
    return data[: frames * size].reshape(frames, SIGNATURE_HEIGHT, SIGNATURE_WIDTH)


def frame_grid(donor_frames: int, step: Fraction) -> Any:
    """Donor frame index for each grid position; ``step`` is donor frames per grid frame."""

    import numpy as np

    count = int(Fraction(donor_frames) / step) + 1
    positions = np.floor(np.arange(count, dtype=np.float64) * float(step) + 0.5).astype(np.int64)
    return positions[positions < donor_frames]


def activity(frames: Any, grid: Any | None = None) -> Any:
    """How much each frame differs from the previous one, with slow trends removed."""

    import numpy as np

    total = len(frames) if grid is None else len(grid)
    out = np.zeros(total, dtype=np.float32)
    previous = None
    y0, y1 = _GRID_Y
    x0, x1 = _GRID_X
    for start in range(0, total, 4096):
        indexes = slice(start, start + 4096) if grid is None else grid[start : start + 4096]
        block = np.asarray(frames[indexes][:, y0:y1, x0:x1], dtype=np.float32)
        joined = block if previous is None else np.concatenate((previous[None], block))
        diff = np.abs(np.diff(joined, axis=0)).mean(axis=(1, 2))
        if previous is None:
            out[start + 1 : start + len(block)] = diff
        else:
            out[start : start + len(block)] = diff
        previous = block[-1]
    out = np.log1p(out)
    summed = np.concatenate(([0.0], np.cumsum(out, dtype=np.float64)))
    half = 24
    positions = np.arange(total)
    low = np.clip(positions - half, 0, total)
    high = np.clip(positions + half + 1, 0, total)
    return (out - (summed[high] - summed[low]) / (high - low)).astype(np.float32)


def coarse_offsets(
    target: Any, donor: Any, *, window: int = COARSE_WINDOW, step: int = COARSE_STEP
) -> list[tuple[int, int, float, float]]:
    """``(title frame, offset, score, runner-up score)`` of each rhythm window."""

    import numpy as np

    size = len(donor)
    if size <= window or len(target) <= window:
        raise FrameMapError("the pictures are too short to compare")
    fft_size = 1 << (size + window).bit_length()
    donor_fft = np.fft.rfft(donor, fft_size)
    summed = np.concatenate(([0.0], np.cumsum(donor.astype(np.float64))))
    squared = np.concatenate(([0.0], np.cumsum(donor.astype(np.float64) ** 2)))
    energy = squared[window:size] - squared[: size - window]
    energy -= (summed[window:size] - summed[: size - window]) ** 2 / window
    energy = np.sqrt(np.maximum(energy, 1e-9))
    rows: list[tuple[int, int, float, float]] = []
    for start in range(0, len(target) - window, step):
        part = target[start : start + window].astype(np.float64)
        part -= part.mean()
        norm = float(np.linalg.norm(part))
        if norm < 1e-6:
            continue
        corr = np.fft.irfft(donor_fft * np.conj(np.fft.rfft(part, fft_size)), fft_size)
        score = corr[: size - window] / (norm * energy)
        best = int(np.argmax(score))
        rest = score.copy()
        rest[max(0, best - 50) : best + 50] = -1.0
        rows.append((start, best - start, float(score[best]), float(rest.max())))
    return rows


def trusted_offsets(rows: Sequence[tuple[int, int, float, float]]) -> list[tuple[int, int]]:
    return [
        (frame, offset)
        for frame, offset, score, runner_up in rows
        if score >= COARSE_MIN_SCORE and score >= COARSE_MIN_MARGIN * runner_up
    ]


def _normalise(block: Any) -> Any:
    import numpy as np

    block = block.reshape(len(block), -1)
    block = block - block.mean(axis=1, keepdims=True)
    return block / np.maximum(np.linalg.norm(block, axis=1, keepdims=True), 1.0)


def _sample(frames: Any, xs: Any, ys: Any) -> Any:
    import numpy as np

    x0 = np.clip(np.floor(xs).astype(int), 0, SIGNATURE_WIDTH - 2)
    y0 = np.clip(np.floor(ys).astype(int), 0, SIGNATURE_HEIGHT - 2)
    fx = (xs - x0)[None, None, :]
    fy = (ys - y0)[None, :, None]
    upper = frames[:, y0]
    lower = frames[:, y0 + 1]
    top = upper[:, :, x0] * (1 - fx) + upper[:, :, x0 + 1] * fx
    bottom = lower[:, :, x0] * (1 - fx) + lower[:, :, x0 + 1] * fx
    return top * (1 - fy) + bottom * fy


def _grid() -> tuple[Any, Any]:
    import numpy as np

    return np.arange(*_GRID_X), np.arange(*_GRID_Y)


def _mapped(geometry: Geometry, pan: int = 0) -> tuple[Any, Any]:
    gx, gy = _grid()
    xs = (gx - _CENTRE_X) * geometry.scale_x + _CENTRE_X + geometry.shift_x + pan
    ys = (gy - _CENTRE_Y) * geometry.scale_y + _CENTRE_Y + geometry.shift_y
    return xs, ys


def _pan_shifts(scale_x: float, shift_x: float) -> tuple[int, ...]:
    """A donor showing less than the title's width may pan across it, shot by shot."""

    if scale_x >= 0.95:
        return (0,)
    gx, _gy = _grid()
    half = float(gx.max() - _CENTRE_X) * scale_x
    room = _CENTRE_X - half - abs(shift_x)
    reach = int(min(room, 16.0)) // 4 * 4
    return tuple(range(-reach, reach + 1, 4)) or (0,)


def estimate_geometry(target: Any, donor: Any, pairs: Sequence[tuple[int, int]]) -> Geometry:
    """Scale and shift of the title's picture under the donor's, from known frame pairs."""

    import numpy as np

    if not pairs:
        raise FrameMapError("no reliable frame pair was found between the two pictures")
    chosen = list(pairs)
    if len(chosen) > 240:
        chosen = [chosen[index] for index in np.linspace(0, len(chosen) - 1, 240).astype(int)]
    a = np.asarray(target[[frame for frame, _ in chosen]], dtype=np.float32)
    b = np.asarray(donor[[frame for _, frame in chosen]], dtype=np.float32)
    gx, gy = _grid()
    expected = _normalise(b[:, gy][:, :, gx])

    def score(sx: float, sy: float, dx: float, dy: float, subset: int) -> float:
        xs = (gx - _CENTRE_X) * sx + _CENTRE_X + dx
        ys = (gy - _CENTRE_Y) * sy + _CENTRE_Y + dy
        if xs.min() < 0 or xs.max() > SIGNATURE_WIDTH - 1 or ys.min() < 0 or ys.max() > SIGNATURE_HEIGHT - 1:
            return -1.0
        return float((_normalise(_sample(a[::subset], xs, ys)) * expected[::subset]).sum(axis=1).mean())

    subset = max(1, len(chosen) // 60)
    results: list[tuple[float, float, float, float, float]] = []
    for sx in np.arange(0.60, 1.42, 0.04):
        for sy in np.arange(0.60, 1.42, 0.04):
            for dx in np.arange(-6.0, 6.1, 2.0):
                for dy in np.arange(-4.0, 4.1, 2.0):
                    results.append((score(sx, sy, dx, dy, subset), float(sx), float(sy), float(dx), float(dy)))
    results.sort(reverse=True)
    best = results[0]
    for candidate in results[:4]:
        _s, cx, cy, cdx, cdy = candidate
        for sx in np.arange(cx - 0.04, cx + 0.041, 0.01):
            for sy in np.arange(cy - 0.04, cy + 0.041, 0.01):
                for dx in (cdx - 1.0, cdx, cdx + 1.0):
                    for dy in (cdy - 1.0, cdy, cdy + 1.0):
                        value = score(sx, sy, dx, dy, 1)
                        if value > best[0]:
                            best = (value, float(sx), float(sy), float(dx), float(dy))
    similarity, sx, sy, dx, dy = best
    return Geometry(
        round(sx, 3),
        round(sy, 3),
        round(dx, 2),
        round(dy, 2),
        similarity,
        _pan_shifts(sx, dx),
    )


def _title_vectors(frames: Any, geometry: Geometry) -> Any:
    """``pans x frames x points``; each pan position is compared, the best one counts."""

    import numpy as np

    block = np.asarray(frames, dtype=np.float32)
    out = []
    for pan in geometry.pan_shifts:
        xs, ys = _mapped(geometry, pan)
        out.append(_normalise(_sample(block, xs, ys)))
    return np.stack(out)


def _donor_vectors(frames: Any) -> Any:
    import numpy as np

    gx, gy = _grid()
    block = np.asarray(frames, dtype=np.float32)
    return _normalise(block[:, gy][:, :, gx])


def _candidates(trusted: Sequence[tuple[int, int]], blocks: int) -> list[Any]:
    import numpy as np

    out: list[Any] = []
    for block in range(blocks):
        centre = block * BLOCK
        near = {offset for frame, offset in trusted if abs(frame - centre) <= 5 * BLOCK}
        if not near:
            if not out:
                far = sorted(trusted, key=lambda item: abs(item[0] - centre))[:1]
                near = {offset for _frame, offset in far}
            else:
                out.append(out[-1])
                continue
        values = sorted({value for offset in near for value in range(offset - SPREAD, offset + SPREAD + 1)})
        out.append(np.asarray(values, dtype=np.int32))
    return out


def best_path(
    target: Any,
    donor: Any,
    grid: Any | None,
    geometry: Geometry,
    trusted: Sequence[tuple[int, int]],
) -> Any:
    """The offset of every title frame: the best path over per-frame similarity."""

    import numpy as np

    total = len(target)
    donor_total = len(donor) if grid is None else len(grid)
    if not trusted:
        raise FrameMapError("no reliable offset was found between the two pictures")
    candidates = _candidates(trusted, total // BLOCK + 2)
    scores: Any = None
    current: Any = None
    keys: list[Any] = []
    backs: list[Any] = []
    for start in range(0, total, BLOCK):
        block_end = min(total, start + BLOCK)
        title = _title_vectors(target[start:block_end], geometry)
        cand = candidates[start // BLOCK]
        low = max(0, start + int(cand[0]))
        high = min(donor_total, block_end + int(cand[-1]) + 1)
        if high > low:
            source = np.arange(low, high) if grid is None else grid[low:high]
            vectors = _donor_vectors(donor[source])
        else:
            vectors = None
        for frame in range(start, block_end):
            index = frame + cand
            sim = np.full(len(cand), -1.0, dtype=np.float32)
            valid = (index >= low) & (index < high)
            if vectors is not None and valid.any():
                sim[valid] = (vectors[index[valid] - low] @ title[:, frame - start].T).max(axis=1)
            if scores is None:
                updated = sim.astype(np.float64)
                back = np.full(len(cand), -1, dtype=np.int32)
            else:
                leader = int(np.argmax(scores))
                position = np.clip(np.searchsorted(current, cand), 0, len(current) - 1)
                stay = np.where(current[position] == cand, scores[position], -np.inf)
                jump = scores[leader] - JUMP_PENALTY
                keep = stay >= jump
                updated = np.where(keep, stay, jump) + sim
                back = np.where(keep, position, leader).astype(np.int32)
            scores = updated
            current = cand
            keys.append(cand)
            backs.append(back)
    state = int(np.argmax(scores))
    path = np.zeros(total, dtype=np.int32)
    for frame in range(total - 1, -1, -1):
        path[frame] = keys[frame][state]
        state = int(backs[frame][state])
    return path


def similarity_along(target: Any, donor: Any, grid: Any | None, geometry: Geometry, frames: Any, offsets: Any) -> Any:
    """Similarity of title ``frames`` to the donor frames at ``offsets`` (-1 outside the donor)."""

    import numpy as np

    donor_total = len(donor) if grid is None else len(grid)
    out = np.full(len(frames), -1.0, dtype=np.float32)
    for start in range(0, len(frames), 4096):
        chunk = frames[start : start + 4096]
        index = chunk + offsets[start : start + 4096]
        valid = (index >= 0) & (index < donor_total)
        if not valid.any():
            continue
        title = _title_vectors(target[chunk[valid]], geometry)
        source = index[valid] if grid is None else grid[index[valid]]
        vectors = _donor_vectors(donor[source])
        values = (title * vectors[None]).sum(axis=2).max(axis=0)
        positions = np.flatnonzero(valid) + start
        out[positions] = values
    return out


@dataclass(slots=True)
class _Run:
    start: int
    end: int
    offset: int


def _runs(path: Any) -> list[_Run]:
    import numpy as np

    changes = np.flatnonzero(np.diff(path)) + 1
    bounds = [0, *changes.tolist(), len(path)]
    return [_Run(a, b, int(path[a])) for a, b in zip(bounds, bounds[1:])]


def _trusted_runs(runs: Sequence[_Run], similarity: Any) -> list[_Run]:
    import numpy as np

    kept: list[_Run] = []
    for run in runs:
        frames = run.end - run.start
        median = float(np.median(similarity[run.start : run.end]))
        trusted = (frames >= TRUST_SHORT_FRAMES and median >= TRUST_SHORT_SIMILARITY) or (
            frames >= TRUST_LONG_FRAMES and median >= TRUST_LONG_SIMILARITY
        )
        if not trusted:
            continue
        if kept and kept[-1].offset == run.offset:
            kept[-1].end = run.end
        else:
            kept.append(_Run(run.start, run.end, run.offset))
    return kept


def _without_chance_runs(
    target: Any, donor: Any, grid: Any | None, geometry: Geometry, runs: Sequence[_Run]
) -> list[_Run]:
    """Drop short runs their neighbour's offset explains just as well.

    In a nearly still shot many offsets look alike, so a short run proves nothing
    unless it is clearly better than simply continuing its neighbour.
    """

    import numpy as np

    kept: list[_Run] = []
    for index, run in enumerate(runs):
        frames = run.end - run.start
        neighbours = [runs[i] for i in (index - 1, index + 1) if 0 <= i < len(runs)]
        if frames >= TRUST_LONG_FRAMES or not neighbours:
            kept.append(run)
            continue
        span = np.arange(run.start, run.end)
        own = similarity_along(target, donor, grid, geometry, span, np.full(frames, run.offset))
        chance = False
        for neighbour in neighbours:
            other = similarity_along(target, donor, grid, geometry, span, np.full(frames, neighbour.offset))
            valid = other > -1.0
            if not valid.any():
                # Before or after the donor's picture under that offset: only a
                # near perfect match can show that this part really exists there.
                chance = chance or float(own.mean()) < 0.95
            elif float((own[valid] - other[valid]).mean()) < MIN_RUN_ADVANTAGE:
                chance = True
        if not chance:
            kept.append(run)
    return kept or list(runs)


def _merge_equal(runs: Sequence[_Run]) -> list[_Run]:
    merged: list[_Run] = []
    for run in runs:
        if merged and merged[-1].offset == run.offset:
            merged[-1].end = run.end
        else:
            merged.append(_Run(run.start, run.end, run.offset))
    return merged


def _solve_splice(
    target: Any, donor: Any, grid: Any | None, geometry: Geometry, left: _Run, right: _Run
) -> tuple[int, int, int]:
    """One splice between two trusted runs: ``(left end, right start, uncertainty)``.

    When the title has frames the donor lacks (the offset falls) they form a gap
    of exactly that many frames.  When the donor has frames the title lacks (it
    rises), the title continues without one.
    """

    import numpy as np

    gap = max(0, left.offset - right.offset)
    first = max(left.start + 1, left.end - SPLICE_MARGIN)
    last = min(right.end - 1 - gap, right.start + SPLICE_MARGIN)
    if last < first:
        return left.end, max(left.end, right.start), 0
    frames = np.arange(first, last + gap + 1)
    with_left = similarity_along(target, donor, grid, geometry, frames, np.full(len(frames), left.offset))
    with_right = similarity_along(target, donor, grid, geometry, frames, np.full(len(frames), right.offset))
    left_sum = np.concatenate(([0.0], np.cumsum(with_left, dtype=np.float64)))
    right_sum = np.concatenate(([0.0], np.cumsum(with_right, dtype=np.float64)))
    choices = np.arange(0, last - first + 1)
    totals = left_sum[choices] + (right_sum[-1] - right_sum[choices + gap])
    best = int(np.argmax(totals))
    near = np.flatnonzero(totals >= totals[best] - 0.5)
    return first + best, first + best + gap, int(near.max() - near.min())


def fit_runs(
    target: Any, donor: Any, grid: Any | None, geometry: Geometry, path: Any, similarity: Any
) -> list[dict[str, int]]:
    """Trusted runs with exact splices, as ``start, end, offset, uncertainty``."""

    donor_total = len(donor) if grid is None else len(grid)
    runs = _trusted_runs(_runs(path), similarity)
    if not runs:
        raise FrameMapError("no part of the two pictures matches")
    runs = _merge_equal(_without_chance_runs(target, donor, grid, geometry, runs))
    while True:
        working = [_Run(run.start, run.end, run.offset) for run in runs]
        uncertainty = [0] * len(working)
        for index in range(len(working) - 1):
            left = working[index]
            right = working[index + 1]
            end, start, spread = _solve_splice(target, donor, grid, geometry, left, right)
            left.end = end
            right.start = start
            uncertainty[index + 1] = spread
        # A splice can leave almost nothing of a short run: then the run was a
        # chance match inside the splice, and its neighbours meet directly.
        squeezed = [
            index
            for index, run in enumerate(working)
            if 0 < index < len(working) - 1 and run.end - run.start < TRUST_SHORT_FRAMES
        ]
        if not squeezed:
            break
        runs = [run for index, run in enumerate(runs) if index != squeezed[0]]
    working[0].start = max(0, -working[0].offset)
    working[-1].end = min(len(target), donor_total - working[-1].offset)
    return [
        {"start": run.start, "end": run.end, "offset": run.offset, "uncertainty": spread}
        for run, spread in zip(working, uncertainty)
        if run.end > run.start
    ]


@dataclass(frozen=True, slots=True)
class Hypothesis:
    mode: str  # "frame-locked" or "time-locked"
    score: float
    trusted: tuple[tuple[int, int], ...]
    step: Fraction


def _hypothesis(mode: str, target_activity: Any, donor: Any, step: Fraction) -> Hypothesis:
    import numpy as np

    grid = None if step == 1 else frame_grid(len(donor), step)
    donor_activity = activity(donor, grid)
    rows = coarse_offsets(target_activity, donor_activity)
    trusted = trusted_offsets(rows)
    score = float(np.median([row[2] for row in rows])) if rows else 0.0
    return Hypothesis(mode, score, tuple(trusted), step)


def build_frame_map(
    target_path: Path,
    donor_path: Path,
    *,
    target_fps: Fraction,
    donor_fps: Fraction,
) -> dict[str, Any]:
    """Compare two signatures; the result is what the audio and subtitle fitting need."""

    import numpy as np

    target = load_signature(target_path)
    donor = load_signature(donor_path)
    target_activity = activity(target)
    choices = [_hypothesis("frame-locked", target_activity, donor, Fraction(1))]
    if donor_fps != target_fps:
        choices.append(
            _hypothesis("time-locked", target_activity, donor, donor_fps / target_fps)
        )
    chosen = max(choices, key=lambda item: item.score)
    grid = None if chosen.step == 1 else frame_grid(len(donor), chosen.step)
    pairs = [
        (frame + COARSE_WINDOW // 2, frame + COARSE_WINDOW // 2 + offset)
        for frame, offset in chosen.trusted
    ]
    pairs = [
        (frame, int(position if grid is None else grid[position]))
        for frame, position in pairs
        if 0 <= frame < len(target) and 0 <= position < (len(donor) if grid is None else len(grid))
    ]
    geometry = estimate_geometry(target, donor, pairs)
    path = best_path(target, donor, grid, geometry, chosen.trusted)
    frames = np.arange(len(target))
    similarity = similarity_along(target, donor, grid, geometry, frames, path)
    runs = fit_runs(target, donor, grid, geometry, path, similarity)
    segments = []
    fitted = np.zeros(len(target), dtype=bool)
    fitted_similarity = np.full(len(target), -1.0, dtype=np.float32)
    for run in runs:
        span = np.arange(run["start"], run["end"])
        values = similarity_along(
            target, donor, grid, geometry, span, np.full(len(span), run["offset"])
        )
        fitted[span] = True
        fitted_similarity[span] = values
        segments.append(
            {
                "target_start": run["start"],
                "target_end": run["end"],
                "offset": run["offset"],
                "boundary_uncertainty_frames": run["uncertainty"],
                "similarity_median": round(float(np.median(values)), 4),
                "similarity_p10": round(float(np.percentile(values, 10)), 4),
            }
        )
    matched = fitted_similarity[fitted]
    return {
        "mode": chosen.mode,
        "rhythm_score": round(chosen.score, 4),
        "geometry": geometry.to_dict(),
        "target_frames": len(target),
        "donor_frames": len(donor),
        "grid_step": str(chosen.step),
        "segments": segments,
        "matched_frames": int(fitted.sum()),
        "unmatched_frames": int((~fitted).sum()),
        "similarity_median": round(float(np.median(matched)), 4) if matched.size else 0.0,
        "share_at_least_0_8": round(float((matched >= 0.8).mean()), 4) if matched.size else 0.0,
    }
