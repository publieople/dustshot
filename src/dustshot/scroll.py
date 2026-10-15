"""Scrolling capture: find the overlap between frames and stitch them into one image."""

from __future__ import annotations

import shutil
import subprocess
import time
from collections.abc import Callable, Sequence

from PIL import Image

from .i18n import _

MIN_OVERLAP = 24
BAND = 96
TOLERANCE = 8.0
ADVANCE_BACKENDS = ("wtype", "ydotool")
SCROLL_BUTTON = 5
NEXT_KEY = "Next"


class ScrollError(RuntimeError):
    """Raised when a scrolling capture cannot be advanced or stitched."""


def row_signature(image: Image.Image, columns: int = 48) -> list[tuple[float, float, float]]:
    """Mean colour of every row, sampled on a fixed column grid."""
    frame = image.convert("RGB")
    width, height = frame.size
    if width == 0 or height == 0:
        return []
    step = max(1, width // columns)
    xs = list(range(0, width, step))[:columns]
    pixels = frame.load()
    signature: list[tuple[float, float, float]] = []
    count = float(len(xs))
    for y in range(height):
        red = green = blue = 0.0
        for x in xs:
            pixel = pixels[x, y]
            red += pixel[0]
            green += pixel[1]
            blue += pixel[2]
        signature.append((red / count, green / count, blue / count))
    return signature


def _band_score(
    top: Sequence[tuple[float, float, float]],
    bottom: Sequence[tuple[float, float, float]],
    top_start: int,
    bottom_start: int,
    band: int,
) -> float:
    total = 0.0
    for offset in range(band):
        first = top[top_start + offset]
        second = bottom[bottom_start + offset]
        total += abs(first[0] - second[0]) + abs(first[1] - second[1]) + abs(first[2] - second[2])
    return total / (3.0 * band)


def find_overlap(
    top: Image.Image,
    bottom: Image.Image,
    min_overlap: int = MIN_OVERLAP,
    max_overlap: int | None = None,
    tolerance: float = TOLERANCE,
) -> int:
    """How many rows the bottom of top and the top of bottom share, or 0.

    The comparison uses the last BAND rows of every candidate overlap so the cost stays flat.
    Ties within a quarter of a grey level resolve to the largest overlap, which keeps a frame
    that did not move from being counted twice.
    """
    first = row_signature(top)
    second = row_signature(bottom)
    if not first or not second:
        return 0
    limit = min(len(first), len(second))
    if max_overlap is not None:
        limit = min(limit, max_overlap)
    if limit < min_overlap:
        return 0
    scores: list[tuple[int, float]] = []
    for overlap in range(min_overlap, limit + 1):
        band = min(overlap, BAND)
        score = _band_score(
            first,
            second,
            len(first) - band,
            overlap - band,
            band,
        )
        scores.append((overlap, score))
    best = min(score for _unused, score in scores)
    if best > tolerance:
        return 0
    close = [overlap for overlap, score in scores if score <= best + 0.25]
    return max(close)


def stitch_vertical(
    images: Sequence[Image.Image],
    min_overlap: int = MIN_OVERLAP,
    max_overlap: int | None = None,
    tolerance: float = TOLERANCE,
) -> tuple[Image.Image, list[int]]:
    """Join frames captured while scrolling; returns the canvas and the overlaps used."""
    frames = [image.convert("RGB") for image in images if image is not None]
    if not frames:
        raise ScrollError(_("没有可拼接的画面"))
    canvas = frames[0].copy()
    overlaps: list[int] = []
    for frame in frames[1:]:
        overlap = find_overlap(
            canvas,
            frame,
            min_overlap=min_overlap,
            max_overlap=max_overlap,
            tolerance=tolerance,
        )
        overlaps.append(overlap)
        height = frame.height - overlap
        if height <= 0:
            continue
        merged = Image.new("RGB", (max(canvas.width, frame.width), canvas.height + height))
        merged.paste(canvas, (0, 0))
        merged.paste(frame.crop((0, overlap, frame.width, frame.height)), (0, canvas.height))
        canvas = merged
    return canvas, overlaps


def available_backends() -> list[str]:
    return [name for name in ADVANCE_BACKENDS if shutil.which(name)]


def build_advance_command(
    backend: str = "wtype",
    amount: int = 1,
    command: str | None = None,
) -> list[str]:
    """Build the argv that scrolls the focused window by one screenful."""
    binary = command or backend
    args = [binary]
    if backend == "wtype":
        for _unused in range(max(1, amount)):
            args += ["-k", NEXT_KEY]
        return args
    if backend == "ydotool":
        for _unused in range(max(1, amount)):
            args += ["click", "--", str(SCROLL_BUTTON)]
        return args
    raise ScrollError(_("未知的滚动后端：{backend}").format(backend=backend))


def advance_scroll(backend: str | None = None, amount: int = 1, timeout: float = 10.0) -> None:
    """Scroll the focused window one screenful (wtype key or ydotool wheel click)."""
    chosen = backend or next(iter(available_backends()), "")
    if not chosen:
        raise ScrollError(_("没有可用的滚动后端（需要 wtype 或 ydotool）"))
    args = build_advance_command(chosen, amount=amount)
    if shutil.which(args[0]) is None:
        raise ScrollError(_("找不到滚动命令：{command}").format(command=args[0]))
    try:
        subprocess.run(args, check=True, timeout=timeout, capture_output=True)
    except FileNotFoundError as error:
        raise ScrollError(_("找不到滚动命令：{command}").format(command=args[0])) from error
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or b"").decode("utf-8", "replace").strip()
        raise ScrollError(_("滚动失败：{detail}").format(detail=detail or error.returncode)) from error
    except subprocess.TimeoutExpired as error:
        raise ScrollError(_("滚动命令超时")) from error


def scroll_capture(
    region,
    steps: int = 5,
    capture: Callable[..., Image.Image] | None = None,
    advance: Callable[[], None] | None = None,
    min_overlap: int = MIN_OVERLAP,
    settle: float = 0.0,
    on_step: Callable[[int, Image.Image], None] | None = None,
) -> tuple[Image.Image, list[int]]:
    """Capture steps frames of region, scrolling between them, and stitch the result.

    settle waits for the compositor to present the scrolled frame before the next capture.
    """
    if capture is None:
        raise ScrollError(_("缺少截图函数"))
    count = max(1, steps)
    frames: list[Image.Image] = []
    for index in range(count):
        if index and advance is not None:
            advance()
            if settle > 0:
                time.sleep(settle)
        frame = capture(region)
        frames.append(frame)
        if on_step is not None:
            on_step(index + 1, frame)
    canvas, overlaps = stitch_vertical(frames, min_overlap=min_overlap)
    if len(frames) > 1 and all(overlap >= frames[index].height for index, overlap in enumerate(overlaps)):
        raise ScrollError(
            _(
                "画面没有滚动：可能是滚动工具（wtype/ydotool）没能把输入送到目标窗口，"
                "或者选区内容不足一屏；可以改用 --manual 自己滚动，或换成 --advance ydotool"
            )
        )
    return canvas, overlaps
