"""Snapping helpers used by the pin windows."""

from __future__ import annotations

from catchlight.capture.base import Geometry
from catchlight.snap import centre_position, snap_position, snap_value


def test_snap_value_picks_the_nearest_target() -> None:
    assert snap_value(103, [100, 200], threshold=12) == 100
    assert snap_value(150, [100, 200], threshold=12) == 150
    assert snap_value(190, [100, 200], threshold=12) == 200


def test_snap_position_aligns_to_the_left_and_top_edges() -> None:
    bounds = Geometry(0, 0, 1920, 1080)
    assert snap_position(5, 7, 400, 300, bounds) == (0, 0)


def test_snap_position_aligns_to_the_right_and_bottom_edges() -> None:
    bounds = Geometry(0, 0, 1920, 1080)
    assert snap_position(1512, 772, 400, 300, bounds) == (1520, 780)


def test_snap_position_centres_when_close_to_the_middle() -> None:
    bounds = Geometry(0, 0, 1920, 1080)
    assert snap_position(758, 388, 400, 300, bounds) == (760, 390)


def test_snap_position_keeps_the_box_inside_bounds() -> None:
    bounds = Geometry(100, 200, 800, 600)
    assert snap_position(-500, -500, 200, 100, bounds) == (100, 200)
    assert snap_position(5000, 5000, 200, 100, bounds) == (700, 700)


def test_snap_position_ignores_targets_when_the_box_is_wider_than_bounds() -> None:
    bounds = Geometry(0, 0, 200, 200)
    assert snap_position(30, 40, 300, 300, bounds) == (0, 0)


def test_centre_position_centres_a_box() -> None:
    bounds = Geometry(10, 20, 1000, 800)
    assert centre_position(200, 100, bounds) == (410, 370)
