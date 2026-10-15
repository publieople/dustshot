"""PIL renderer behaviour."""

from __future__ import annotations

from PIL import Image

from dustshot.annotation.items import MosaicItem, RectItem, Style
from dustshot.annotation.render import difference_ratio, render, render_to_file


def white(size: tuple[int, int] = (120, 90)) -> Image.Image:
    return Image.new("RGB", size, (255, 255, 255))


def test_render_draws_rect() -> None:
    base = white()
    output = render(base, [RectItem(x=10, y=10, width=40, height=30, style=Style(fill=True))])
    assert output.size == base.size
    assert difference_ratio(base, output) > 0.0


def test_render_mosaic_changes_pixels() -> None:
    base = Image.new("RGB", (80, 80), (255, 255, 255))
    for x in range(0, 80, 4):
        for y in range(80):
            base.putpixel((x, y), (0, 0, 0))
    item = MosaicItem(x=10, y=10, width=40, height=40, block=8)
    output = render(base, [item])
    assert difference_ratio(base, output) > 0.0


def test_render_keeps_alpha_when_asked() -> None:
    base = white()
    output = render(base, [], keep_alpha=True)
    assert output.mode == "RGBA"


def test_render_to_file(tmp_path) -> None:
    target = tmp_path / "out.png"
    assert render_to_file(white(), [RectItem(x=0, y=0, width=10, height=10)], target) is None
    assert target.exists()
    assert Image.open(target).size == (120, 90)


def test_difference_ratio_identical() -> None:
    assert difference_ratio(white(), white()) == 0.0


def test_solid_fill_covers_the_region_opaquely() -> None:
    base = white()
    region = {"x": 10, "y": 10, "width": 40, "height": 30}
    solid = RectItem(style=Style(color="#101114", fill=True, solid=True), **region)
    soft = RectItem(style=Style(color="#101114", fill=True), **region)
    assert render(base, [solid]).getpixel((30, 25)) == (16, 17, 20)
    assert render(base, [soft]).getpixel((30, 25)) != (16, 17, 20)
