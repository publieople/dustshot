"""Selection state machine for the capture overlay.

Kept free of GTK so drag, move and resize behaviour is unit testable. Public
coordinates are compositor logical coordinates; the overlay widget works in
output local coordinates and uses the conversion helpers here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from .capture.base import Geometry

MIN_SIZE = 5
HANDLE_RADIUS = 10
HANDLE_NAMES = ("nw", "n", "ne", "e", "se", "s", "sw", "w")


class SelectionMode(StrEnum):
    IDLE = "idle"
    NEW = "new"
    MOVE = "move"
    RESIZE = "resize"


@dataclass
class SelectionState:
    """Tracks a rubber band selection on one output."""

    bounds: Geometry
    """Logical rectangle of the output in desktop coordinates."""

    mode: SelectionMode = SelectionMode.IDLE
    region: Geometry | None = None
    anchor: tuple[int, int] | None = None
    cursor: tuple[int, int] | None = None
    active_handle: str = ""
    _move_offset: tuple[int, int] = field(default=(0, 0), repr=False)
    _resize_start: Geometry | None = field(default=None, repr=False)

    # ------------------------------------------------------------------ helpers
    def to_desktop(self, lx: float, ly: float) -> tuple[int, int]:
        return (round(lx) + self.bounds.x, round(ly) + self.bounds.y)

    def to_local(self, x: float, y: float) -> tuple[int, int]:
        return (round(x) - self.bounds.x, round(y) - self.bounds.y)

    def clamp_local(self, lx: float, ly: float) -> tuple[int, int]:
        return (
            max(0, min(round(lx), self.bounds.width)),
            max(0, min(round(ly), self.bounds.height)),
        )

    def region_local(self) -> Geometry | None:
        if self.region is None:
            return None
        return Geometry(
            self.region.x - self.bounds.x,
            self.region.y - self.bounds.y,
            self.region.width,
            self.region.height,
        )

    def region_contains_local(self, lx: float, ly: float) -> bool:
        return self.region is not None and self.region.contains_point(lx + self.bounds.x, ly + self.bounds.y)

    def has_region(self) -> bool:
        return self.region is not None and not self.region.is_empty()

    def region_size(self) -> tuple[int, int]:
        if self.region is None:
            return (0, 0)
        return (self.region.width, self.region.height)

    def size_text(self) -> str:
        width, height = self.region_size()
        return f"{width} x {height}"

    def handles(self) -> list[tuple[str, int, int]]:
        """Handle positions in output local coordinates."""

        box = self.region_local()
        if box is None:
            return []
        left, top = box.x, box.y
        right, bottom = box.x + box.width, box.y + box.height
        mid_x = left + box.width // 2
        mid_y = top + box.height // 2
        return [
            ("nw", left, top),
            ("n", mid_x, top),
            ("ne", right, top),
            ("e", right, mid_y),
            ("se", right, bottom),
            ("s", mid_x, bottom),
            ("sw", left, bottom),
            ("w", left, mid_y),
        ]

    def hit_handle(self, lx: float, ly: float) -> str:
        if not self.has_region():
            return ""
        for name, hx, hy in self.handles():
            if abs(lx - hx) <= HANDLE_RADIUS and abs(ly - hy) <= HANDLE_RADIUS:
                return name
        return ""

    # -------------------------------------------------------------------- input
    def press(self, lx: float, ly: float) -> SelectionMode:
        lx, ly = self.clamp_local(lx, ly)
        self.cursor = self.to_desktop(lx, ly)
        self.anchor = (lx, ly)
        self.active_handle = ""

        handle = self.hit_handle(lx, ly)
        if handle:
            self.mode = SelectionMode.RESIZE
            self.active_handle = handle
            self._resize_start = self.region
            return self.mode

        if self.region_contains_local(lx, ly):
            self.mode = SelectionMode.MOVE
            cursor_x, cursor_y = self.to_desktop(lx, ly)
            self._move_offset = (self.region.x - cursor_x, self.region.y - cursor_y)
            return self.mode

        self.mode = SelectionMode.NEW
        start_x, start_y = self.to_desktop(lx, ly)
        self.region = Geometry(start_x, start_y, 0, 0)
        return self.mode

    def drag(self, lx: float, ly: float) -> SelectionMode:
        lx, ly = self.clamp_local(lx, ly)
        self.cursor = self.to_desktop(lx, ly)
        if self.mode is SelectionMode.NEW and self.anchor is not None:
            ax, ay = self.anchor
            self.region = Geometry.from_points(*self.to_desktop(ax, ay), *self.to_desktop(lx, ly))
        elif self.mode is SelectionMode.MOVE and self.region is not None:
            offset_x, offset_y = self._move_offset
            cursor_x, cursor_y = self.to_desktop(lx, ly)
            self.region = _clamp_inside(
                Geometry(cursor_x + offset_x, cursor_y + offset_y, self.region.width, self.region.height),
                self.bounds,
            )
        elif self.mode is SelectionMode.RESIZE and self._resize_start is not None:
            self.region = _resize(
                self._resize_start,
                self.active_handle,
                self.to_desktop(lx, ly),
                self.bounds,
            )
        return self.mode

    def release(self, lx: float, ly: float) -> Geometry | None:
        if self.mode is not SelectionMode.IDLE:
            self.drag(lx, ly)
        mode = self.mode
        self.mode = SelectionMode.IDLE
        self.active_handle = ""
        self._resize_start = None
        if self.region is not None and (self.region.width < MIN_SIZE or self.region.height < MIN_SIZE):
            if mode is SelectionMode.NEW:
                self.region = None
            else:
                self.region = _clamp_inside(self.region, self.bounds)
        elif self.region is not None:
            self.region = _clamp_inside(self.region, self.bounds)
        return self.region

    def cancel(self) -> None:
        """Abort the gesture and drop the region (Esc / right click)."""
        self.mode = SelectionMode.IDLE
        self.region = None
        self.anchor = None
        self.cursor = None
        self.active_handle = ""
        self._move_offset = (0, 0)
        self._resize_start = None

    def clear(self) -> None:
        """Alias of cancel() kept for readability at call sites."""
        self.cancel()

    def select_all(self) -> Geometry:
        self.region = Geometry(self.bounds.x, self.bounds.y, self.bounds.width, self.bounds.height)
        self.mode = SelectionMode.IDLE
        return self.region

    def nudge(self, dx: int, dy: int) -> None:
        if self.region is None:
            return
        self.region = _clamp_inside(self.region.translated(dx, dy), self.bounds)

    def resize_by(self, dw: int, dh: int) -> None:
        if self.region is None:
            return
        width = max(MIN_SIZE, self.region.width + dw)
        height = max(MIN_SIZE, self.region.height + dh)
        self.region = _clamp_inside(Geometry(self.region.x, self.region.y, width, height), self.bounds)


def _clamp_inside(region: Geometry, bounds: Geometry) -> Geometry:
    width = min(region.width, bounds.width)
    height = min(region.height, bounds.height)
    x = max(bounds.x, min(region.x, bounds.right - width))
    y = max(bounds.y, min(region.y, bounds.bottom - height))
    return Geometry(x, y, width, height)


def _resize(start: Geometry, handle: str, cursor: tuple[int, int], bounds: Geometry) -> Geometry:
    cx, cy = cursor
    left, top, right, bottom = start.x, start.y, start.right, start.bottom
    if "n" in handle:
        top = min(cy, bottom - MIN_SIZE)
    if "s" in handle:
        bottom = max(cy, top + MIN_SIZE)
    if "w" in handle:
        left = min(cx, right - MIN_SIZE)
    if "e" in handle:
        right = max(cx, left + MIN_SIZE)
    left = max(bounds.x, left)
    top = max(bounds.y, top)
    right = min(bounds.right, right)
    bottom = min(bounds.bottom, bottom)
    if right - left < MIN_SIZE or bottom - top < MIN_SIZE:
        return start
    return Geometry(left, top, right - left, bottom - top)
