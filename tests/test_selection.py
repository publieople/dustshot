"""Selection state machine (no GTK required)."""

from __future__ import annotations

from dustshot.capture.base import Geometry
from dustshot.selection import MIN_SIZE, SelectionMode, SelectionState


def make_state() -> SelectionState:
    return SelectionState(Geometry(0, 0, 1000, 800))


def test_new_selection_from_drag() -> None:
    state = make_state()
    assert state.press(10, 10) is SelectionMode.NEW
    state.drag(300, 200)
    region = state.release(300, 200)
    assert region == Geometry(10, 10, 290, 190)
    assert state.has_region()


def test_tiny_drag_clears_region() -> None:
    state = make_state()
    state.press(50, 50)
    state.drag(52, 51)
    assert state.release(52, 51) is None
    assert not state.has_region()


def test_move_uses_region_interior() -> None:
    state = make_state()
    state.select_all()
    state.press(500, 400)
    state.drag(600, 500)
    region = state.release(600, 500)
    assert region is not None
    assert state.mode is SelectionMode.MOVE or region == Geometry(0, 0, 1000, 800)


def test_resize_from_handle() -> None:
    state = make_state()
    state.press(10, 10)
    state.drag(300, 200)
    state.release(300, 200)
    assert state.hit_handle(10, 10) == "nw"
    assert state.press(10, 10) is SelectionMode.RESIZE
    state.drag(0, 0)
    region = state.release(0, 0)
    assert region == Geometry(0, 0, 300, 200)


def test_clamp_inside_bounds() -> None:
    state = make_state()
    state.press(900, 700)
    state.drag(2000, 2000)
    region = state.release(2000, 2000)
    assert region is not None
    assert region.right <= 1000
    assert region.bottom <= 800


def test_select_all_and_nudge() -> None:
    state = make_state()
    state.select_all()
    assert state.region_size() == (1000, 800)
    state.nudge(-50, -50)
    assert state.region_local() == Geometry(0, 0, 1000, 800)


def test_resize_by_respects_minimum() -> None:
    state = make_state()
    state.select_all()
    state.resize_by(-10000, -10000)
    size = state.region_size()
    assert size[0] >= MIN_SIZE
    assert size[1] >= MIN_SIZE


def test_cancel_clears_state() -> None:
    state = make_state()
    state.select_all()
    state.cancel()
    assert not state.has_region()
    assert state.mode is SelectionMode.IDLE


def test_size_text() -> None:
    state = make_state()
    state.press(10, 20)
    state.drag(210, 120)
    state.release(210, 120)
    assert state.size_text() == "200 x 100"


def test_handles_and_region_contains() -> None:
    state = make_state()
    state.select_all()
    assert len(state.handles()) == 8
    assert state.region_contains_local(10, 10)
    assert not state.region_contains_local(-5, -5)
