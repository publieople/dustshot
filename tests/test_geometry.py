"""Geometry maths and frame coordinate conversion."""

from __future__ import annotations

from PIL import Image

from dustshot.capture.base import Frame, Geometry, OutputInfo


def test_geometry_properties() -> None:
    box = Geometry(10, 20, 30, 40)
    assert box.right == 40
    assert box.bottom == 60
    assert box.area == 1200
    assert not box.is_empty()
    assert Geometry(5, 5, 0, 10).is_empty()


def test_translated_scaled_clamped() -> None:
    box = Geometry(10, 20, 30, 40)
    assert box.translated(5, -5) == Geometry(15, 15, 30, 40)
    assert box.scaled(2.0) == Geometry(20, 40, 60, 80)
    assert Geometry(-10, -10, 50, 50).clamped(100, 100) == Geometry(0, 0, 40, 40)
    assert Geometry(90, 90, 50, 50).clamped(100, 100) == Geometry(90, 90, 10, 10)


def test_union_and_intersection() -> None:
    left = Geometry(0, 0, 10, 10)
    right = Geometry(5, 5, 10, 10)
    assert left.union(right) == Geometry(0, 0, 15, 15)
    assert left.intersects(right)
    assert not left.intersects(Geometry(50, 50, 10, 10))
    assert left.contains_point(5, 5)
    assert not left.contains_point(15, 15)


def test_from_points_and_covering() -> None:
    assert Geometry.from_points(10, 20, 30, 5) == Geometry(10, 5, 20, 15)
    assert Geometry.covering([(0, 0), (10, 20)]) == Geometry(0, 0, 10, 20)
    assert Geometry.covering([(0, 0), (10, 20)], padding=2) == Geometry(-2, -2, 14, 24)


def test_as_pil_box_and_grim_geometry() -> None:
    box = Geometry(10, 20, 30, 40)
    assert box.as_tuple() == (10, 20, 30, 40)
    assert box.as_pil_box() == (10, 20, 40, 60)
    assert box.as_grim_geometry() == "10,20 30x40"
    assert Geometry.from_tuple((1, 2, 3, 4)) == Geometry(1, 2, 3, 4)


def test_frame_logical_to_physical() -> None:
    image = Image.new("RGB", (200, 200), (0, 0, 0))
    output = OutputInfo(
        name="eDP-1",
        description="test",
        logical=Geometry(0, 0, 100, 100),
        scale=2.0,
        physical=Geometry(0, 0, 200, 200),
        primary=True,
    )
    frame = Frame(image=image, output=output)
    assert frame.scale == 2.0
    assert frame.logical_size == (100, 100)
    assert frame.physical_size == (200, 200)
    assert frame.logical_to_physical_box(Geometry(10, 10, 20, 20)) == Geometry(20, 20, 40, 40)


def test_frame_crop_logical_uses_scale() -> None:
    image = Image.new("RGB", (200, 200), (0, 0, 0))
    for x in range(100, 200):
        for y in range(0, 200):
            image.putpixel((x, y), (255, 0, 0))
    output = OutputInfo(
        name="eDP-1",
        logical=Geometry(0, 0, 100, 100),
        scale=2.0,
        physical=Geometry(0, 0, 200, 200),
    )
    frame = Frame(image=image, output=output)
    cropped = frame.crop_logical(Geometry(50, 0, 50, 100))
    assert cropped.size == (100, 200)
    assert cropped.getpixel((0, 0)) == (255, 0, 0)
