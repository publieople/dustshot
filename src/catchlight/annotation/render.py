"""Software renderer that turns a list of annotations into pixels.

Pillow is used rather than Cairo so that rendering works in headless CI and in
plain command line exports. The GTK canvas draws the same item objects through
Cairo; geometry lives in items.py so both stay in sync.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from .fonts import load_font, text_size
from .items import (
    ArrowItem,
    EllipseItem,
    HighlighterItem,
    Item,
    LineItem,
    MosaicItem,
    PencilItem,
    RectItem,
    SerialItem,
    TextItem,
)


def _rgba(color: str, alpha: float) -> tuple[int, int, int, int]:
    from .items import _rgb

    r, g, b = _rgb(color)
    return (r, g, b, max(0, min(255, round(alpha * 255))))


def _overlay(size: tuple[int, int]) -> Image.Image:
    return Image.new("RGBA", size, (0, 0, 0, 0))


def _draw_rect(canvas: Image.Image, item: RectItem, blender) -> None:
    layer = _overlay(canvas.size)
    draw = ImageDraw.Draw(layer)
    box = [item.x, item.y, item.right - 1, item.bottom - 1]
    alpha = item.style.alpha()
    outline = _rgba(item.style.color, alpha)
    fill = _rgba(item.style.color, alpha * 0.35) if item.style.fill else None
    width = max(1, item.style.width)
    if item.radius > 0:
        if fill is not None:
            draw.rounded_rectangle(box, radius=item.radius, fill=fill, outline=outline, width=width)
        else:
            draw.rounded_rectangle(box, radius=item.radius, outline=outline, width=width)
    elif fill is not None:
        draw.rectangle(box, fill=fill, outline=outline, width=width)
    else:
        draw.rectangle(box, outline=outline, width=width)
    blender(layer)


def _draw_ellipse(canvas: Image.Image, item: EllipseItem, blender) -> None:
    layer = _overlay(canvas.size)
    draw = ImageDraw.Draw(layer)
    box = [item.x, item.y, item.right - 1, item.bottom - 1]
    alpha = item.style.alpha()
    if item.style.fill:
        draw.ellipse(box, fill=_rgba(item.style.color, alpha * 0.35))
    draw.ellipse(box, outline=_rgba(item.style.color, alpha), width=max(1, item.style.width))
    blender(layer)


def _draw_line(canvas: Image.Image, item: LineItem, blender) -> None:
    layer = _overlay(canvas.size)
    draw = ImageDraw.Draw(layer)
    draw.line(
        [(item.x1, item.y1), (item.x2, item.y2)],
        fill=_rgba(item.style.color, item.style.alpha()),
        width=max(1, item.style.width),
    )
    blender(layer)


def _draw_arrow(canvas: Image.Image, item: ArrowItem, blender) -> None:
    layer = _overlay(canvas.size)
    draw = ImageDraw.Draw(layer)
    color = _rgba(item.style.color, item.style.alpha())
    width = max(1, item.style.width)
    head = item.head_points()
    import math

    angle = item.angle()
    size = item.head_size()
    tail = (item.x2 - size * math.cos(angle), item.y2 - size * math.sin(angle))
    draw.line([(item.x1, item.y1), tail], fill=color, width=width)
    if item.style.fill:
        draw.polygon(head, fill=color)
    else:
        draw.line([head[1], head[0], head[2]], fill=color, width=width, joint="curve")
    blender(layer)


def _draw_stroke(canvas: Image.Image, item: Item, blender, *, alpha: float = 1.0) -> None:
    if not item.points:
        return
    layer = _overlay(canvas.size)
    draw = ImageDraw.Draw(layer)
    color = _rgba(item.style.color, item.style.alpha() * alpha)
    points = list(item.points)
    width = max(1, item.style.width)
    if len(points) == 1:
        x, y = points[0]
        radius = width / 2.0
        draw.ellipse([x - radius, y - radius, x + radius, y + radius], fill=color)
    else:
        draw.line(points, fill=color, width=width, joint="curve")
        for x, y in (points[0], points[-1]):
            radius = width / 2.0
            draw.ellipse([x - radius, y - radius, x + radius, y + radius], fill=color)
    if isinstance(item, HighlighterItem):
        layer = layer.filter(ImageFilter.GaussianBlur(0.6))
    blender(layer)


def _draw_text(canvas: Image.Image, item: TextItem, blender) -> None:
    layer = _overlay(canvas.size)
    draw = ImageDraw.Draw(layer)
    font = load_font(item.size, bold=item.bold)
    fill = _rgba(item.style.color, item.style.alpha())
    line_height = round((getattr(font, "size", item.size) or item.size) * 1.3)
    spacing = max(1, int(item.size * 0.15))
    y = item.y
    for line in item.text.split("\n"):
        draw.text((item.x, y), line, font=font, fill=fill)
        y += line_height + spacing
    blender(layer)


def _draw_serial(canvas: Image.Image, item: SerialItem, blender) -> None:
    layer = _overlay(canvas.size)
    draw = ImageDraw.Draw(layer)
    size = max(8, item.size)
    box = [item.x, item.y, item.x + size - 1, item.y + size - 1]
    color = _rgba(item.style.color, item.style.alpha())
    draw.ellipse(box, fill=color)
    font = load_font(max(8, int(size * 0.62)), bold=True)
    label = str(item.number)
    tw, th = text_size(font, label)
    draw.text(
        (item.x + (size - tw) / 2.0, item.y + (size - th) / 2.0),
        label,
        font=font,
        fill=(255, 255, 255, 255),
    )
    blender(layer)


def _effect_region(canvas: Image.Image, item: MosaicItem) -> None:
    box = (item.x, item.y, item.right, item.bottom)
    box = (
        max(0, box[0]),
        max(0, box[1]),
        min(canvas.width, box[2]),
        min(canvas.height, box[3]),
    )
    if box[2] <= box[0] or box[3] <= box[1]:
        return
    region = canvas.crop(box)
    if item.mode == "blur":
        region = region.filter(ImageFilter.GaussianBlur(max(1, item.blur_radius)))
    else:
        block = max(2, item.block)
        small = region.resize(
            (max(1, region.width // block), max(1, region.height // block)),
            Image.NEAREST,
        )
        region = small.resize(region.size, Image.NEAREST)
    canvas.paste(region, box)


def render(base: Image.Image, items: Sequence[Item], *, keep_alpha: bool = False) -> Image.Image:
    """Render annotations over a copy of base.

    Effects such as mosaic and blur sample the canvas as it looks at their place
    in the stack, so later annotations are not smeared by an earlier effect.
    """

    canvas = base.convert("RGBA")

    def blender(layer: Image.Image) -> None:
        canvas.alpha_composite(layer)

    for item in items:
        if isinstance(item, RectItem):
            _draw_rect(canvas, item, blender)
        elif isinstance(item, EllipseItem):
            _draw_ellipse(canvas, item, blender)
        elif isinstance(item, ArrowItem):
            _draw_arrow(canvas, item, blender)
        elif isinstance(item, LineItem):
            _draw_line(canvas, item, blender)
        elif isinstance(item, MosaicItem):
            _effect_region(canvas, item)
        elif isinstance(item, TextItem):
            _draw_text(canvas, item, blender)
        elif isinstance(item, SerialItem):
            _draw_serial(canvas, item, blender)
        elif isinstance(item, (PencilItem, HighlighterItem)):
            _draw_stroke(canvas, item, blender)

    if keep_alpha:
        return canvas
    return canvas.convert("RGB")


def difference_ratio(a: Image.Image, b: Image.Image) -> float:
    """Fraction of channels that differ; used by tests to assert no-op rendering."""

    if a.size != b.size:
        return 1.0
    diff = ImageChops.difference(a.convert("RGB"), b.convert("RGB"))
    histogram = diff.histogram()
    changed = sum(count for index, count in enumerate(histogram) if index % 256 != 0)
    total = a.size[0] * a.size[1] * 3
    return changed / total if total else 0.0


def render_to_file(base: Image.Image, items: Iterable[Item], path) -> None:
    render(base, list(items)).save(path)
