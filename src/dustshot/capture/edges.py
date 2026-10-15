"""Find the borders of windows and controls in a frozen frame.

The overlay already holds a screenshot taken before the selection starts, so the
borders of every visible window are pixels in that image. Reading the pixels keeps
snapping compositor agnostic: a Flatpak client cannot ask the compositor for window
geometry (the sandbox hides the niri IPC socket and the privileged protocols), but
it can always look at the backdrop it is drawing.

The detector projects gradient energy onto the x and y axes: a straight border
shows up as a peak in one projection, and a window is the box between four peaks.
Coordinates come back in logical desktop coordinates, ready to snap a selection.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass

from PIL import Image, ImageFilter

from .base import Frame, Geometry

WORK_WIDTH = 720
"""Detection runs on a copy this many pixels wide; lines stay crisp and it is fast."""

PEAK_SIGMA = 2.0
"""A peak has to stand this many standard deviations above the column/row average."""

PEAK_FRACTION = 0.25
"""A peak also has to reach this fraction of the strongest one, to skip photo texture."""

MIN_PEAK = 10.0
"""Absolute floor on the 0-255 edge scale; the filter rests around 8 on flat colour."""

MIN_GAP = 3
"""Two peaks closer than this in the work image are the same border."""

SNAP_TOLERANCE = 12
"""Logical pixels a selection side may travel to land on a detected line."""

MIN_BOX = 24
"""Smallest box that still counts as a window or a control while picking."""


@dataclass(frozen=True)
class Line:
    """One straight border."""

    position: int
    strength: float


@dataclass(frozen=True)
class EdgeMap:
    """The strong vertical and horizontal borders of one output.

    columns and rows carry logical desktop coordinates; width and height are the
    output logical size.
    """

    columns: tuple[Line, ...] = ()
    rows: tuple[Line, ...] = ()
    width: int = 0
    height: int = 0

    @property
    def is_empty(self) -> bool:
        return not self.columns and not self.rows

    @staticmethod
    def _positions(lines: tuple[Line, ...]) -> list[int]:
        return [line.position for line in lines]

    def nearest_column(self, x: float, tolerance: int = SNAP_TOLERANCE) -> Line | None:
        return _nearest(self.columns, self._positions(self.columns), x, tolerance)

    def nearest_row(self, y: float, tolerance: int = SNAP_TOLERANCE) -> Line | None:
        return _nearest(self.rows, self._positions(self.rows), y, tolerance)

    def column_around(self, x: float) -> tuple[Line | None, Line | None]:
        """The closest border at or left of x, and the first one right of it."""

        positions = self._positions(self.columns)
        index = bisect.bisect_right(positions, x)
        left = self.columns[index - 1] if index > 0 else None
        right = self.columns[index] if index < len(self.columns) else None
        return left, right

    def row_around(self, y: float) -> tuple[Line | None, Line | None]:
        positions = self._positions(self.rows)
        index = bisect.bisect_right(positions, y)
        top = self.rows[index - 1] if index > 0 else None
        bottom = self.rows[index] if index < len(self.rows) else None
        return top, bottom

    def enclosing_box(self, px: float, py: float, min_size: int = MIN_BOX) -> Geometry | None:
        """The box a pointer sits in: nearest borders left, right, above and below."""

        left, right = self.column_around(px)
        top, bottom = self.row_around(py)
        if left is None or right is None or top is None or bottom is None:
            return None
        box = Geometry(
            left.position, top.position, right.position - left.position, bottom.position - top.position
        )
        if box.width < min_size or box.height < min_size:
            return None
        return box


def _nearest(lines: tuple[Line, ...], positions: list[int], value: float, tolerance: int) -> Line | None:
    if not lines:
        return None
    index = bisect.bisect_left(positions, round(value))
    best: Line | None = None
    for candidate in (index - 1, index, index + 1):
        if not 0 <= candidate < len(lines):
            continue
        distance = abs(lines[candidate].position - value)
        if distance <= tolerance and (best is None or distance < abs(best.position - value)):
            best = lines[candidate]
    return best


def detect(frame: Frame, work_width: int = WORK_WIDTH) -> EdgeMap:
    """Project the frame gradients onto both axes and keep the strong peaks."""

    image = frame.image.convert("L")
    logical_width, logical_height = frame.logical_size
    origin_x = frame.output.logical.x
    origin_y = frame.output.logical.y
    if logical_width <= 0 or logical_height <= 0 or image.width <= 0 or image.height <= 0:
        return EdgeMap(width=max(0, logical_width), height=max(0, logical_height))
    work_w = max(8, min(work_width, image.width))
    work_h = max(8, round(image.height * work_w / image.width))
    small = image.resize((work_w, work_h), Image.BOX)
    filtered = small.filter(ImageFilter.FIND_EDGES)
    columns = _peaks(_column_values(filtered, work_w), interior=True)
    rows = _peaks(_row_values(filtered, work_h), interior=True)
    step_x = logical_width / work_w
    step_y = logical_height / work_h
    return EdgeMap(
        columns=tuple(Line(origin_x + round(index * step_x), strength) for index, strength in columns),
        rows=tuple(Line(origin_y + round(index * step_y), strength) for index, strength in rows),
        width=logical_width,
        height=logical_height,
    )


def _column_values(image: Image.Image, width: int) -> list[float]:
    """Collapse the image to one value per column."""

    return [float(value) for value in image.resize((width, 1), Image.BOX).tobytes()]


def _row_values(image: Image.Image, height: int) -> list[float]:
    """Collapse the image to one value per row."""

    return [float(value) for value in image.resize((1, height), Image.BOX).tobytes()]


def _peaks(values: list[float], *, interior: bool = False) -> list[tuple[int, float]]:
    """Local maxima above an adaptive threshold, sorted by position.

    The gradient filter clamps at the picture boundary and reports a maximum there,
    which is an artefact of the capture, not a border in the scene. interior drops
    the outer ring before measuring, so a flat frame stays empty.
    """

    offset = 0
    series = values
    if interior and len(values) > 2:
        series = values[1:-1]
        offset = 1
    if not series:
        return []
    count = len(series)
    mean = sum(series) / count
    variance = sum((value - mean) ** 2 for value in series) / count
    threshold = max(mean + PEAK_SIGMA * variance**0.5, MIN_PEAK, PEAK_FRACTION * max(series))
    candidates = [(value, index) for index, value in enumerate(series) if value >= threshold]
    candidates.sort(key=lambda item: (-item[0], item[1]))
    chosen: list[tuple[int, float]] = []
    for value, index in candidates:
        if all(abs(index - kept) > MIN_GAP for kept, _strength in chosen):
            chosen.append((index, value))
    chosen.sort()
    return [(index + offset, value) for index, value in chosen]


def snap_point(x: float, y: float, edges: EdgeMap, tolerance: int = SNAP_TOLERANCE) -> tuple[int, int]:
    """Pull one point onto the nearest border, per axis."""

    snapped_x = edges.nearest_column(x, tolerance)
    snapped_y = edges.nearest_row(y, tolerance)
    return (
        round(x) if snapped_x is None else snapped_x.position,
        round(y) if snapped_y is None else snapped_y.position,
    )


def snap_rect(
    rect: Geometry, edges: EdgeMap, tolerance: int = SNAP_TOLERANCE, sides: str = ""
) -> tuple[Geometry, tuple[str, ...]]:
    """Move the requested sides onto nearby borders.

    The sides argument selects a subset of "lrtb"; an empty string snaps all four.
    A side that would cross the opposite one keeps its original position.
    """

    wanted = sides or "lrtb"
    snapped: list[str] = []
    left = snap_value(
        "l" in wanted, rect.x, edges, columns=True, tolerance=tolerance, label="left", out=snapped
    )
    right = snap_value(
        "r" in wanted, rect.right, edges, columns=True, tolerance=tolerance, label="right", out=snapped
    )
    top = snap_value(
        "t" in wanted, rect.y, edges, columns=False, tolerance=tolerance, label="top", out=snapped
    )
    bottom = snap_value(
        "b" in wanted, rect.bottom, edges, columns=False, tolerance=tolerance, label="bottom", out=snapped
    )
    x = rect.x if left is None else left
    right_edge = rect.right if right is None else right
    y = rect.y if top is None else top
    bottom_edge = rect.bottom if bottom is None else bottom
    if right_edge - x < 1:
        x, right_edge = rect.x, rect.right
        snapped = [side for side in snapped if side not in ("left", "right")]
    if bottom_edge - y < 1:
        y, bottom_edge = rect.y, rect.bottom
        snapped = [side for side in snapped if side not in ("top", "bottom")]
    return Geometry(x, y, right_edge - x, bottom_edge - y), tuple(snapped)


def snap_move(
    rect: Geometry, edges: EdgeMap, tolerance: int = SNAP_TOLERANCE
) -> tuple[Geometry, tuple[str, ...]]:
    """Translate a rectangle so its closest side lands on a border.

    Size is preserved: moving a selection should not resize it, so on each axis the
    smaller of the two corrections wins.
    """

    moved = rect
    snapped: list[str] = []
    shift_x = _axis_shift(rect.x, rect.right, edges.columns, tolerance)
    if shift_x is not None:
        delta, side = shift_x
        moved = Geometry(moved.x + delta, moved.y, moved.width, moved.height)
        snapped.append("left" if side == 0 else "right")
    shift_y = _axis_shift(rect.y, rect.bottom, edges.rows, tolerance)
    if shift_y is not None:
        delta, side = shift_y
        moved = Geometry(moved.x, moved.y + delta, moved.width, moved.height)
        snapped.append("top" if side == 0 else "bottom")
    return moved, tuple(snapped)


def _axis_shift(start: float, end: float, lines: tuple[Line, ...], tolerance: int) -> tuple[int, int] | None:
    """Smallest translation putting start or end on a line, and which one moved."""

    positions = EdgeMap._positions(lines)
    best: tuple[int, int] | None = None
    for side, value in ((0, start), (1, end)):
        line = _nearest(lines, positions, value, tolerance)
        if line is None:
            continue
        delta = line.position - round(value)
        if delta == 0:
            continue
        if best is None or abs(delta) < abs(best[0]):
            best = (delta, side)
    return best


def snap_value(
    wanted: bool,
    value: float,
    edges: EdgeMap,
    *,
    columns: bool,
    tolerance: int,
    label: str,
    out: list[str],
) -> int | None:
    """Snap one edge and record it in out when it moved onto a border."""

    if not wanted:
        return None
    lines = edges.columns if columns else edges.rows
    positions = EdgeMap._positions(lines)
    line = _nearest(lines, positions, value, tolerance)
    if line is None:
        return None
    out.append(label)
    return line.position
