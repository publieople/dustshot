"""Edge and centre snapping for the floating pin windows."""

from __future__ import annotations

from .capture.base import Geometry

SNAP_THRESHOLD = 12


def snap_value(value: int, targets: list[int], threshold: int = SNAP_THRESHOLD) -> int:
    """Return the closest target within threshold, or the value itself."""

    best = value
    best_distance = threshold + 1
    for target in targets:
        distance = abs(value - target)
        if distance <= threshold and distance < best_distance:
            best = target
            best_distance = distance
    return best


def snap_position(
    x: int,
    y: int,
    width: int,
    height: int,
    bounds: Geometry,
    threshold: int = SNAP_THRESHOLD,
) -> tuple[int, int]:
    """Snap a box of width x height to the edges or centre lines of bounds.

    The box is always kept inside bounds, even when snapping is off.
    """

    xs = [bounds.x, bounds.right - width, bounds.x + (bounds.width - width) // 2]
    ys = [bounds.y, bounds.bottom - height, bounds.y + (bounds.height - height) // 2]
    snapped_x = snap_value(int(x), xs, threshold)
    snapped_y = snap_value(int(y), ys, threshold)
    max_x = max(bounds.x, bounds.right - width)
    max_y = max(bounds.y, bounds.bottom - height)
    snapped_x = min(max(snapped_x, bounds.x), max_x)
    snapped_y = min(max(snapped_y, bounds.y), max_y)
    return int(snapped_x), int(snapped_y)


def centre_position(width: int, height: int, bounds: Geometry) -> tuple[int, int]:
    """Return the top-left corner that centres a box inside bounds."""

    return (
        bounds.x + max(0, (bounds.width - width) // 2),
        bounds.y + max(0, (bounds.height - height) // 2),
    )
