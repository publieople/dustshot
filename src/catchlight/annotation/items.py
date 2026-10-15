"""Annotation primitives.

Every annotation is a small dataclass with an explicit kind, a style and the
geometry it needs to draw itself. Items are pure data: the GTK canvas and the
offline renderer both consume the same objects, so what is previewed is exactly
what is exported.
"""

from __future__ import annotations

import math
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, ClassVar

from ..capture.base import Geometry

REGISTRY: dict[str, type[Item]] = {}


def register(cls: type[Item]) -> type[Item]:
    REGISTRY[cls.kind] = cls
    return cls


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def _rgb(color: str) -> tuple[int, int, int]:
    """Parse #rgb / #rrggbb / #rrggbbaa into an RGB triple."""

    value = (color or "").strip().lstrip("#")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    if len(value) not in (6, 8):
        return (255, 59, 48)
    try:
        return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))
    except ValueError:
        return (255, 59, 48)


def _alpha(color: str) -> float:
    value = (color or "").strip().lstrip("#")
    if len(value) == 8:
        try:
            return int(value[6:8], 16) / 255.0
        except ValueError:
            return 1.0
    return 1.0


@dataclass
class Style:
    """Visual attributes shared by all annotations."""

    color: str = "#ff3b30"
    width: int = 3
    fill: bool = False
    opacity: float = 1.0

    def rgb(self) -> tuple[int, int, int]:
        return _rgb(self.color)

    def alpha(self) -> float:
        return max(0.0, min(1.0, self.opacity * _alpha(self.color)))

    def to_dict(self) -> dict[str, Any]:
        return {"color": self.color, "width": self.width, "fill": self.fill, "opacity": self.opacity}

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> Style:
        data = data or {}
        return cls(
            color=str(data.get("color", "#ff3b30")),
            width=int(data.get("width", 3)),
            fill=bool(data.get("fill", False)),
            opacity=float(data.get("opacity", 1.0)),
        )


@dataclass
class Item:
    """Base class for annotations."""

    kind: ClassVar[str] = "item"
    style: Style = field(default_factory=Style)
    id: str = field(default_factory=new_id)

    def bbox(self) -> Geometry:
        raise NotImplementedError

    def translation(self) -> tuple[int, int]:
        return (0, 0)

    def move(self, dx: int, dy: int) -> None:
        raise NotImplementedError

    def payload(self) -> dict[str, Any]:
        return {}

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "id": self.id, "style": self.style.to_dict(), **self.payload()}

    @classmethod
    def from_payload(cls, payload: dict[str, Any], style: Style, item_id: str) -> Item:
        raise NotImplementedError

    def scaled(self, factor: float) -> None:
        """Scale geometry in place; used when the capture scale changes."""


@dataclass
class _BoxItem(Item):
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    def bbox(self) -> Geometry:
        return Geometry(self.x, self.y, self.width, self.height)

    def move(self, dx: int, dy: int) -> None:
        self.x += dx
        self.y += dy

    def payload(self) -> dict[str, Any]:
        return {"x": self.x, "y": self.y, "width": self.width, "height": self.height}

    def scaled(self, factor: float) -> None:
        self.x = round(self.x * factor)
        self.y = round(self.y * factor)
        self.width = round(self.width * factor)
        self.height = round(self.height * factor)
        self.style.width = max(1, round(self.style.width * factor))


@register
@dataclass
class RectItem(_BoxItem):
    kind: ClassVar[str] = "rect"
    radius: int = 0

    @classmethod
    def from_box(cls, box: Geometry, style: Style) -> RectItem:
        return cls(style=style, x=box.x, y=box.y, width=box.width, height=box.height)

    def payload(self) -> dict[str, Any]:
        return {**super().payload(), "radius": self.radius}

    @classmethod
    def from_payload(cls, payload: dict[str, Any], style: Style, item_id: str) -> RectItem:
        return cls(
            style=style,
            id=item_id,
            x=int(payload.get("x", 0)),
            y=int(payload.get("y", 0)),
            width=int(payload.get("width", 0)),
            height=int(payload.get("height", 0)),
            radius=int(payload.get("radius", 0)),
        )


@register
@dataclass
class EllipseItem(_BoxItem):
    kind: ClassVar[str] = "ellipse"

    @classmethod
    def from_box(cls, box: Geometry, style: Style) -> EllipseItem:
        return cls(style=style, x=box.x, y=box.y, width=box.width, height=box.height)

    @classmethod
    def from_payload(cls, payload: dict[str, Any], style: Style, item_id: str) -> EllipseItem:
        return cls(
            style=style,
            id=item_id,
            x=int(payload.get("x", 0)),
            y=int(payload.get("y", 0)),
            width=int(payload.get("width", 0)),
            height=int(payload.get("height", 0)),
        )


@register
@dataclass
class LineItem(Item):
    kind: ClassVar[str] = "line"
    x1: int = 0
    y1: int = 0
    x2: int = 0
    y2: int = 0

    def bbox(self) -> Geometry:
        return Geometry.from_points(self.x1, self.y1, self.x2, self.y2)

    def move(self, dx: int, dy: int) -> None:
        self.x1 += dx
        self.y1 += dy
        self.x2 += dx
        self.y2 += dy

    def payload(self) -> dict[str, Any]:
        return {"x1": self.x1, "y1": self.y1, "x2": self.x2, "y2": self.y2}

    def scaled(self, factor: float) -> None:
        self.x1 = round(self.x1 * factor)
        self.y1 = round(self.y1 * factor)
        self.x2 = round(self.x2 * factor)
        self.y2 = round(self.y2 * factor)
        self.style.width = max(1, round(self.style.width * factor))

    @classmethod
    def from_payload(cls, payload: dict[str, Any], style: Style, item_id: str) -> LineItem:
        return cls(
            style=style,
            id=item_id,
            x1=int(payload.get("x1", 0)),
            y1=int(payload.get("y1", 0)),
            x2=int(payload.get("x2", 0)),
            y2=int(payload.get("y2", 0)),
        )


@register
@dataclass
class ArrowItem(LineItem):
    kind: ClassVar[str] = "arrow"
    head: float = 0.0  # 0.0 -> derive from style width

    def head_size(self) -> float:
        base = self.head or 4.0 * max(2.0, float(self.style.width) * 1.4)
        return max(8.0, base)

    def angle(self) -> float:
        return math.atan2(self.y2 - self.y1, self.x2 - self.x1)

    def head_points(self) -> list[tuple[float, float]]:
        size = self.head_size()
        angle = self.angle()
        spread = math.radians(28)
        tip = (float(self.x2), float(self.y2))
        left = (
            tip[0] - size * math.cos(angle - spread),
            tip[1] - size * math.sin(angle - spread),
        )
        right = (
            tip[0] - size * math.cos(angle + spread),
            tip[1] - size * math.sin(angle + spread),
        )
        return [tip, left, right]

    def payload(self) -> dict[str, Any]:
        return {**super().payload(), "head": self.head}

    @classmethod
    def from_payload(cls, payload: dict[str, Any], style: Style, item_id: str) -> ArrowItem:
        return cls(
            style=style,
            id=item_id,
            x1=int(payload.get("x1", 0)),
            y1=int(payload.get("y1", 0)),
            x2=int(payload.get("x2", 0)),
            y2=int(payload.get("y2", 0)),
            head=float(payload.get("head", 0.0)),
        )


@dataclass
class _StrokeItem(Item):
    points: list[tuple[int, int]] = field(default_factory=list)

    def bbox(self) -> Geometry:
        if not self.points:
            return Geometry(0, 0, 0, 0)
        pad = max(1, self.style.width // 2)
        return Geometry.covering(self.points, padding=pad)

    def move(self, dx: int, dy: int) -> None:
        self.points = [(px + dx, py + dy) for px, py in self.points]

    def append(self, x: float, y: float, min_distance: float = 1.0) -> None:
        point = (round(x), round(y))
        if self.points:
            last = self.points[-1]
            if abs(point[0] - last[0]) < min_distance and abs(point[1] - last[1]) < min_distance:
                return
        self.points.append(point)

    def payload(self) -> dict[str, Any]:
        return {"points": [[px, py] for px, py in self.points]}

    def scaled(self, factor: float) -> None:
        self.points = [(round(px * factor), round(py * factor)) for px, py in self.points]
        self.style.width = max(1, round(self.style.width * factor))


@register
@dataclass
class PencilItem(_StrokeItem):
    kind: ClassVar[str] = "pencil"

    @classmethod
    def from_payload(cls, payload: dict[str, Any], style: Style, item_id: str) -> PencilItem:
        points = [(int(p[0]), int(p[1])) for p in payload.get("points", [])]
        return cls(style=style, id=item_id, points=points)


@register
@dataclass
class HighlighterItem(_StrokeItem):
    kind: ClassVar[str] = "highlighter"

    @classmethod
    def from_payload(cls, payload: dict[str, Any], style: Style, item_id: str) -> HighlighterItem:
        points = [(int(p[0]), int(p[1])) for p in payload.get("points", [])]
        return cls(style=style, id=item_id, points=points)


@register
@dataclass
class TextItem(Item):
    kind: ClassVar[str] = "text"
    x: int = 0
    y: int = 0
    text: str = ""
    size: int = 16
    bold: bool = False

    def bbox(self) -> Geometry:
        lines = self.text.split("\n") or [""]
        width = max((len(line) for line in lines), default=0)
        text_width = max(1, int(width * self.size * 0.62))
        text_height = max(1, len(lines) * int(self.size * 1.3))
        return Geometry(self.x, self.y, text_width, text_height)

    def move(self, dx: int, dy: int) -> None:
        self.x += dx
        self.y += dy

    def payload(self) -> dict[str, Any]:
        return {"x": self.x, "y": self.y, "text": self.text, "size": self.size, "bold": self.bold}

    def scaled(self, factor: float) -> None:
        self.x = round(self.x * factor)
        self.y = round(self.y * factor)
        self.size = max(6, round(self.size * factor))
        self.style.width = max(1, round(self.style.width * factor))

    @classmethod
    def from_payload(cls, payload: dict[str, Any], style: Style, item_id: str) -> TextItem:
        return cls(
            style=style,
            id=item_id,
            x=int(payload.get("x", 0)),
            y=int(payload.get("y", 0)),
            text=str(payload.get("text", "")),
            size=int(payload.get("size", 16)),
            bold=bool(payload.get("bold", False)),
        )


@register
@dataclass
class SerialItem(Item):
    kind: ClassVar[str] = "serial"
    x: int = 0
    y: int = 0
    number: int = 1
    size: int = 20

    def bbox(self) -> Geometry:
        return Geometry(self.x, self.y, self.size, self.size)

    def move(self, dx: int, dy: int) -> None:
        self.x += dx
        self.y += dy

    def payload(self) -> dict[str, Any]:
        return {"x": self.x, "y": self.y, "number": self.number, "size": self.size}

    def scaled(self, factor: float) -> None:
        self.x = round(self.x * factor)
        self.y = round(self.y * factor)
        self.size = max(8, round(self.size * factor))
        self.style.width = max(1, round(self.style.width * factor))

    @classmethod
    def from_payload(cls, payload: dict[str, Any], style: Style, item_id: str) -> SerialItem:
        return cls(
            style=style,
            id=item_id,
            x=int(payload.get("x", 0)),
            y=int(payload.get("y", 0)),
            number=int(payload.get("number", 1)),
            size=int(payload.get("size", 20)),
        )


@register
@dataclass
class MosaicItem(_BoxItem):
    kind: ClassVar[str] = "mosaic"
    block: int = 12
    mode: str = "mosaic"  # mosaic | blur
    blur_radius: int = 12

    @classmethod
    def from_box(cls, box: Geometry, style: Style, mode: str = "mosaic") -> MosaicItem:
        return cls(style=style, x=box.x, y=box.y, width=box.width, height=box.height, mode=mode)

    def payload(self) -> dict[str, Any]:
        return {**super().payload(), "block": self.block, "mode": self.mode, "blur_radius": self.blur_radius}

    @classmethod
    def from_payload(cls, payload: dict[str, Any], style: Style, item_id: str) -> MosaicItem:
        return cls(
            style=style,
            id=item_id,
            x=int(payload.get("x", 0)),
            y=int(payload.get("y", 0)),
            width=int(payload.get("width", 0)),
            height=int(payload.get("height", 0)),
            block=int(payload.get("block", 12)),
            mode=str(payload.get("mode", "mosaic")),
            blur_radius=int(payload.get("blur_radius", 12)),
        )


def item_from_dict(data: dict[str, Any]) -> Item:
    kind = str(data.get("kind", ""))
    cls = REGISTRY.get(kind)
    if cls is None:
        raise ValueError(f"unknown annotation kind: {kind!r}")
    style = Style.from_dict(data.get("style"))
    item_id = str(data.get("id") or new_id())
    return cls.from_payload(data, style, item_id)


def items_to_jsonable(items: Sequence[Item]) -> list[dict[str, Any]]:
    return [item.to_dict() for item in items]


def items_from_jsonable(payload: Sequence[dict[str, Any]]) -> list[Item]:
    return [item_from_dict(entry) for entry in payload]
