"""Selection state machine for the capture overlay.

Kept free of GTK so drag, move and resize behaviour is unit testable. Public
coordinates are compositor logical coordinates; the overlay widget works in
output local coordinates and uses the conversion helpers here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from .capture.base import Geometry
from .capture.edges import SNAP_TOLERANCE, EdgeMap, snap_move, snap_point

MIN_SIZE = 5
HANDLE_RADIUS = 10
HANDLE_NAMES = ("nw", "n", "ne", "e", "se", "s", "sw", "w")

LINE_EPSILON = 1
"""A side within this many pixels of a detected border counts as snapped onto it."""


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

    edges: EdgeMap | None = None
    """Detected window and control borders of this output, in desktop coordinates."""

    snapping: bool = True
    """False while Alt is held: the pointer then goes exactly where it is put."""

    snap_sides: tuple[str, ...] = ()
    """Sides of the current region sitting on a detected border, for the guides."""

    hover_box: Geometry | None = None
    """The box under the pointer while idle; a click picks it up whole."""

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

    def _snapped_point(self, x: float, y: float) -> tuple[int, int]:
        if not self.snapping or self.edges is None:
            return (round(x), round(y))
        return snap_point(x, y, self.edges)

    def _sides_on_lines(self, region: Geometry | None) -> tuple[str, ...]:
        """Which sides of the region sit exactly on a detected border."""

        if region is None or not self.snapping or self.edges is None:
            return ()
        on_line: list[str] = []
        for name, value, columns in (
            ("left", region.x, True),
            ("right", region.right, True),
            ("top", region.y, False),
            ("bottom", region.bottom, False),
        ):
            lines = self.edges.columns if columns else self.edges.rows
            if any(abs(line.position - value) <= LINE_EPSILON for line in lines):
                on_line.append(name)
        return tuple(on_line)

    def _snap_moved(self, region: Geometry) -> Geometry:
        """Slide a moved region onto the nearest border without resizing it."""

        if not self.snapping or self.edges is None:
            return region
        moved, _sides = snap_move(region, self.edges, SNAP_TOLERANCE)
        return moved

    def _click_box(self, lx: float, ly: float) -> Geometry | None:
        """The detected box under a bare click, if there is one."""

        if not self.snapping or self.edges is None:
            return None
        x, y = self.to_desktop(lx, ly)
        return self.edges.enclosing_box(x, y)

    def hover(self, lx: float, ly: float) -> Geometry | None:
        """Track the box under the pointer so the overlay can preview it."""

        inside_region = self.has_region() and self.region_contains_local(lx, ly)
        if self.mode is not SelectionMode.IDLE or inside_region or not self.snapping or self.edges is None:
            self.hover_box = None
            return None
        x, y = self.to_desktop(lx, ly)
        self.hover_box = self.edges.enclosing_box(x, y)
        return self.hover_box

    def region_local_of(self, region: Geometry) -> Geometry:
        """Convert a desktop rectangle of this output into local coordinates."""

        return Geometry(
            region.x - self.bounds.x,
            region.y - self.bounds.y,
            region.width,
            region.height,
        )

    def region_local(self) -> Geometry | None:
        if self.region is None:
            return None
        return self.region_local_of(self.region)

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
        self.snap_sides = ()

        handle = self.hit_handle(lx, ly)
        if handle:
            self.cursor = self.to_desktop(lx, ly)
            self.anchor = (lx, ly)
            self.mode = SelectionMode.RESIZE
            self.active_handle = handle
            self._resize_start = self.region
            return self.mode

        x, y = self.to_desktop(lx, ly)
        if self.region_contains_local(lx, ly):
            self.mode = SelectionMode.MOVE
            self._move_offset = (self.region.x - x, self.region.y - y)
            self.anchor = (lx, ly)
            self.cursor = (x, y)
            return self.mode

        x, y = self._snapped_point(x, y)
        self.cursor = (x, y)
        self.anchor = (x - self.bounds.x, y - self.bounds.y)
        self.mode = SelectionMode.NEW
        self.region = Geometry(x, y, 0, 0)
        return self.mode

    def drag(self, lx: float, ly: float) -> SelectionMode:
        lx, ly = self.clamp_local(lx, ly)
        x, y = self.to_desktop(lx, ly)
        self.cursor = (x, y)
        if self.mode is SelectionMode.NEW and self.anchor is not None:
            ax, ay = self.anchor
            snapped_x, snapped_y = self._snapped_point(x, y)
            self.region = _clamp_inside(
                Geometry.from_points(ax + self.bounds.x, ay + self.bounds.y, snapped_x, snapped_y),
                self.bounds,
            )
        elif self.mode is SelectionMode.MOVE and self.region is not None:
            offset_x, offset_y = self._move_offset
            moved = self._snap_moved(
                Geometry(x + offset_x, y + offset_y, self.region.width, self.region.height)
            )
            self.region = _clamp_inside(moved, self.bounds)
        elif self.mode is SelectionMode.RESIZE and self._resize_start is not None:
            self.region = _resize(
                self._resize_start,
                self.active_handle,
                self._snapped_point(x, y),
                self.bounds,
            )
        self.snap_sides = self._sides_on_lines(self.region)
        return self.mode

    def release(self, lx: float, ly: float) -> Geometry | None:
        mode = self.mode
        if mode is not SelectionMode.IDLE:
            self.drag(lx, ly)
        self.mode = SelectionMode.IDLE
        self.active_handle = ""
        self._resize_start = None
        clicked = mode is SelectionMode.NEW and not self.has_region()
        if self.region is not None and (self.region.width < MIN_SIZE or self.region.height < MIN_SIZE):
            picked = self._click_box(lx, ly) if clicked else None
            if picked is not None:
                # A bare click on a window or control selects the whole box.
                self.region = _clamp_inside(picked, self.bounds)
            elif mode is SelectionMode.NEW:
                self.region = None
            else:
                self.region = _clamp_inside(self.region, self.bounds)
        elif self.region is not None:
            self.region = _clamp_inside(self.region, self.bounds)
        self.snap_sides = self._sides_on_lines(self.region)
        return self.region

    def cancel(self) -> None:
        """Abort the gesture and drop the region (Esc / right click)."""
        self.mode = SelectionMode.IDLE
        self.region = None
        self.anchor = None
        self.cursor = None
        self.active_handle = ""
        self.snap_sides = ()
        self._move_offset = (0, 0)
        self._resize_start = None

    def clear(self) -> None:
        """Alias of cancel() kept for readability at call sites."""
        self.cancel()

    def select_all(self) -> Geometry:
        self.region = Geometry(self.bounds.x, self.bounds.y, self.bounds.width, self.bounds.height)
        self.mode = SelectionMode.IDLE
        self.snap_sides = self._sides_on_lines(self.region)
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
