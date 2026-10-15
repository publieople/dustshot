"""Geometry helpers and the captured-frame container."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from PIL import Image


@dataclass(frozen=True)
class Geometry:
    """An integer rectangle in logical (compositor) coordinates."""

    x: int
    y: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    @property
    def area(self) -> int:
        return max(0, self.width) * max(0, self.height)

    def is_empty(self) -> bool:
        return self.width <= 0 or self.height <= 0

    def translated(self, dx: int, dy: int) -> Geometry:
        return Geometry(self.x + dx, self.y + dy, self.width, self.height)

    def scaled(self, factor: float) -> Geometry:
        return Geometry(
            round(self.x * factor),
            round(self.y * factor),
            round(self.width * factor),
            round(self.height * factor),
        )

    def clamped(self, width: int, height: int) -> Geometry:
        x = max(0, min(self.x, width))
        y = max(0, min(self.y, height))
        right = max(x, min(self.right, width))
        bottom = max(y, min(self.bottom, height))
        return Geometry(x, y, right - x, bottom - y)

    def union(self, other: Geometry) -> Geometry:
        x = min(self.x, other.x)
        y = min(self.y, other.y)
        right = max(self.right, other.right)
        bottom = max(self.bottom, other.bottom)
        return Geometry(x, y, right - x, bottom - y)

    def intersects(self, other: Geometry) -> bool:
        return not (
            self.right <= other.x or other.right <= self.x or self.bottom <= other.y or other.bottom <= self.y
        )

    def contains_point(self, px: float, py: float) -> bool:
        return self.x <= px < self.right and self.y <= py < self.bottom

    def as_tuple(self) -> tuple[int, int, int, int]:
        return (self.x, self.y, self.width, self.height)

    def as_grim_geometry(self) -> str:
        return f"{self.x},{self.y} {self.width}x{self.height}"

    def as_pil_box(self) -> tuple[int, int, int, int]:
        """Pillow crop box: left, upper, right, lower."""

        return (self.x, self.y, self.right, self.bottom)

    @classmethod
    def from_tuple(cls, values: Iterable[int]) -> Geometry:
        x, y, width, height = list(values)
        return cls(int(x), int(y), int(width), int(height))

    @classmethod
    def from_points(cls, x1: float, y1: float, x2: float, y2: float) -> Geometry:
        left, right = sorted((round(min(x1, x2)), round(max(x1, x2))))
        top, bottom = sorted((round(min(y1, y2)), round(max(y1, y2))))
        return cls(left, top, right - left, bottom - top)

    @classmethod
    def covering(cls, points: Iterable[tuple[float, float]], padding: int = 0) -> Geometry:
        pts = list(points)
        if not pts:
            return cls(0, 0, 0, 0)
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        box = cls.from_points(min(xs), min(ys), max(xs), max(ys))
        if padding:
            box = cls(box.x - padding, box.y - padding, box.width + 2 * padding, box.height + 2 * padding)
        return box


@dataclass(frozen=True)
class OutputInfo:
    """One compositor output."""

    name: str
    description: str = ""
    logical: Geometry = Geometry(0, 0, 0, 0)
    scale: float = 1.0
    physical: Geometry = Geometry(0, 0, 0, 0)
    primary: bool = False

    @property
    def safe_scale(self) -> float:
        return self.scale if self.scale > 0 else 1.0


@dataclass
class Frame:
    """A captured still together with the geometry it came from.

    The image is always the full-resolution (physical pixel) capture. Selection
    happens in logical coordinates, so the conversion helpers live here.
    """

    image: Image.Image
    output: OutputInfo

    @property
    def scale(self) -> float:
        return self.output.safe_scale

    @property
    def logical_size(self) -> tuple[int, int]:
        return (self.output.logical.width, self.output.logical.height)

    @property
    def physical_size(self) -> tuple[int, int]:
        return self.image.size

    def logical_to_physical_box(self, box: Geometry, clamp: bool = True) -> Geometry:
        scale = self.scale
        origin_x = self.output.logical.x
        origin_y = self.output.logical.y
        x = round((box.x - origin_x) * scale)
        y = round((box.y - origin_y) * scale)
        right = round((box.right - origin_x) * scale)
        bottom = round((box.bottom - origin_y) * scale)
        physical = Geometry(x, y, max(0, right - x), max(0, bottom - y))
        return physical.clamped(*self.image.size) if clamp else physical

    def crop_logical(self, box: Geometry) -> Image.Image:
        if box.is_empty():
            raise ValueError("cannot crop an empty region")
        physical = self.logical_to_physical_box(box)
        if physical.is_empty():
            raise ValueError("selection does not intersect the captured output")
        return self.image.crop(physical.as_pil_box())

    def thumbnailed(self, max_width: int = 4096) -> Image.Image:
        width, height = self.image.size
        if width <= max_width:
            return self.image
        ratio = max_width / width
        return self.image.resize((max(1, int(width * ratio)), max(1, int(height * ratio))), Image.LANCZOS)
