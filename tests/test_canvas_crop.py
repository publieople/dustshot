"""The crop tool on the canvas: drag geometry, overlay and applying the crop."""

from __future__ import annotations

import os

import pytest

gi = pytest.importorskip("gi")
gi.require_version("Gtk", "4.0")

import cairo
from PIL import Image

from dustshot.annotation.document import Document
from dustshot.annotation.items import RectItem
from dustshot.capture.base import Geometry
from dustshot.config import AnnotationSettings
from dustshot.ui.canvas import Canvas

pytestmark = pytest.mark.skipif(
    not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")),
    reason="需要一个图形会话",
)

WIDTH, HEIGHT = 800, 600


class FakeGesture:
    """Stands in for Gtk.GestureDrag, which needs a real pointer."""

    def __init__(self, sx: float, sy: float, cx: float, cy: float) -> None:
        self.sx, self.sy, self.cx, self.cy = sx, sy, cx, cy

    def get_start_point(self) -> tuple[bool, float, float]:
        return (True, self.sx, self.sy)

    def get_offset(self) -> tuple[float, float]:
        return (self.cx, self.cy)

    def get_current_button(self) -> int:
        return 1


def make_canvas(size: tuple[int, int] = (400, 300)) -> Canvas:
    document = Document(Image.new("RGB", size, (255, 255, 255)), AnnotationSettings())
    canvas = Canvas(document, AnnotationSettings())
    canvas._compute_layout(WIDTH, HEIGHT)
    return canvas


def drag(canvas: Canvas, start: tuple[float, float], end: tuple[float, float]) -> None:
    x0, y0 = canvas.to_widget(*start)
    x1, y1 = canvas.to_widget(*end)
    gesture = FakeGesture(x0, y0, x1 - x0, y1 - y0)
    canvas._on_drag_begin(gesture, x0, y0)
    canvas._on_drag_update(gesture, x1 - x0, y1 - y0)
    canvas._on_drag_end(gesture, x1 - x0, y1 - y0)


def paint(canvas: Canvas) -> Image.Image:
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, WIDTH, HEIGHT)
    canvas._draw(canvas, cairo.Context(surface), WIDTH, HEIGHT)
    surface.flush()
    buffer = surface.get_data()
    return Image.frombuffer("RGBA", (WIDTH, HEIGHT), bytes(buffer), "raw", "BGRA", 0, 1).convert("RGB")


def test_the_crop_tool_records_the_dragged_rectangle() -> None:
    canvas = make_canvas()
    canvas.set_tool("crop")
    drag(canvas, (20, 10), (260, 160))
    assert canvas.tool == "crop"
    assert canvas.crop_rect is not None
    assert canvas.crop_rect.as_tuple() == (20, 10, 240, 150)


def test_a_tiny_drag_leaves_no_rectangle() -> None:
    canvas = make_canvas()
    canvas.set_tool("crop")
    drag(canvas, (20, 10), (22, 12))
    assert canvas.crop_rect is None


def test_the_overlay_dims_everything_outside_the_rectangle() -> None:
    canvas = make_canvas()
    canvas.set_tool("crop")
    drag(canvas, (20, 10), (260, 160))
    image = paint(canvas)
    inside = image.getpixel((300, 200))
    assert inside == (255, 255, 255)
    outside = image.getpixel((215, 165))
    assert outside[0] < 200, outside
    assert image.getpixel((590, 440))[0] < 200


def test_switching_tools_drops_the_rectangle() -> None:
    canvas = make_canvas()
    canvas.set_tool("crop")
    drag(canvas, (20, 10), (260, 160))
    assert canvas.crop_rect is not None
    canvas.set_tool("rect")
    assert canvas.crop_rect is None


def test_applying_the_crop_trims_the_document_and_can_be_undone() -> None:
    canvas = make_canvas((120, 90))
    canvas.doc.add(RectItem(x=0, y=0, width=10, height=10))
    canvas.set_tool("crop")
    drag(canvas, (20, 10), (100, 80))
    assert canvas.apply_crop() is True
    assert canvas.doc.size == (80, 70)
    assert canvas.crop_rect is None
    assert canvas.doc.undo() is True
    assert canvas.doc.size == (120, 90)


def test_applying_without_a_rectangle_reports_failure() -> None:
    canvas = make_canvas()
    assert canvas.apply_crop() is False
    assert canvas.doc.size == (400, 300)


def test_cancel_crop_only_clears_an_existing_rectangle() -> None:
    canvas = make_canvas()
    assert canvas.cancel_crop() is False
    canvas.crop_rect = Geometry(10, 10, 50, 50)
    assert canvas.cancel_crop() is True
    assert canvas.crop_rect is None
    assert canvas.doc.size == (400, 300)
