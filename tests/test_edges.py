"""Window border detection and the snapping selection state."""

from __future__ import annotations

from PIL import Image, ImageDraw

from dustshot.capture.base import Frame, Geometry, OutputInfo
from dustshot.capture.edges import EdgeMap, detect, snap_move, snap_point, snap_rect
from dustshot.selection import MIN_SIZE, SelectionMode, SelectionState

BOX = (100, 80, 400, 320)
TOLERANCE = 4  # the detector works on a downscaled copy, so a few pixels of slack


def make_frame(
    boxes: tuple[tuple[int, int, int, int], ...] = (BOX,), origin: tuple[int, int] = (0, 0)
) -> Frame:
    """A white canvas with black window outlines, standing in for a frozen frame."""

    size = (800, 600)
    image = Image.new("L", size, 255)
    draw = ImageDraw.Draw(image)
    for left, top, right, bottom in boxes:
        draw.rectangle((left, top, right, bottom), outline=0, width=3)
    logical = Geometry(origin[0], origin[1], size[0], size[1])
    output = OutputInfo(name="DP-1", logical=logical, scale=1.0, physical=logical, primary=True)
    return Frame(image, output)


def near(value: float, target: float) -> bool:
    return abs(value - target) <= TOLERANCE


def test_detect_finds_every_border_of_a_box() -> None:
    edges = detect(make_frame())
    assert not edges.is_empty
    for x in (BOX[0], BOX[2]):
        assert edges.nearest_column(x, TOLERANCE) is not None, x
    for y in (BOX[1], BOX[3]):
        assert edges.nearest_row(y, TOLERANCE) is not None, y


def test_detect_reports_coordinates_in_desktop_space() -> None:
    edges = detect(make_frame(origin=(1920, 0)))
    assert edges.nearest_column(1920 + BOX[0], TOLERANCE) is not None
    assert edges.columns[0].position >= 1920


def test_detect_ignores_a_flat_frame() -> None:
    blank = Frame(Image.new("L", (800, 600), 255), OutputInfo(name="DP-1", logical=Geometry(0, 0, 800, 600)))
    assert detect(blank).is_empty


def test_enclosing_box_wraps_the_pointer() -> None:
    edges = detect(make_frame())
    box = edges.enclosing_box(250, 200)
    assert box is not None
    assert near(box.x, BOX[0]) and near(box.y, BOX[1])
    assert near(box.right, BOX[2]) and near(box.bottom, BOX[3])
    assert edges.enclosing_box(700, 550) is None


def test_empty_map_snaps_nothing() -> None:
    edges = EdgeMap()
    rect = Geometry(10, 10, 50, 50)
    assert edges.nearest_column(10) is None
    assert edges.enclosing_box(10, 10) is None
    assert snap_point(11, 12, edges) == (11, 12)
    assert snap_rect(rect, edges) == (rect, ())
    assert snap_move(rect, edges) == (rect, ())


def test_snap_point_pulls_each_axis_onto_a_border() -> None:
    edges = detect(make_frame())
    x, y = snap_point(BOX[0] + 5, BOX[1] - 5, edges)
    assert near(x, BOX[0]) and near(y, BOX[1])
    assert snap_point(250, 200, edges) == (250, 200)


def test_snap_rect_reports_which_sides_moved() -> None:
    edges = detect(make_frame())
    rect = Geometry(BOX[0] + 4, BOX[1] + 4, 120, 90)
    snapped, sides = snap_rect(rect, edges)
    assert set(sides) == {"left", "top"}
    assert near(snapped.x, BOX[0]) and near(snapped.y, BOX[1])
    # Only the requested sides move; the far sides stay where they were.
    assert snapped.right == rect.right and snapped.bottom == rect.bottom


def test_snap_rect_keeps_the_size_when_a_side_is_not_requested() -> None:
    edges = detect(make_frame())
    rect = Geometry(BOX[0] + 4, BOX[1] + 4, 120, 90)
    snapped, sides = snap_rect(rect, edges, sides="r")
    assert sides == ()
    assert snapped == rect


def test_snap_move_translates_without_resizing() -> None:
    edges = detect(make_frame())
    rect = Geometry(BOX[0] + 5, 200, 60, 40)
    moved, sides = snap_move(rect, edges)
    assert near(moved.x, BOX[0])
    assert moved.width == rect.width and moved.height == rect.height
    assert "left" in sides


def make_state(**kwargs: object) -> SelectionState:
    state = SelectionState(Geometry(0, 0, 800, 600), **kwargs)
    state.edges = detect(make_frame())
    return state


def test_drag_snaps_a_new_selection_onto_the_window() -> None:
    state = make_state()
    assert state.press(BOX[0] + 5, BOX[1] + 5) is SelectionMode.NEW
    state.drag(BOX[2] - 5, BOX[3] - 5)
    region = state.release(BOX[2] - 5, BOX[3] - 5)
    assert region is not None
    assert near(region.x, BOX[0]) and near(region.y, BOX[1])
    assert near(region.right, BOX[2]) and near(region.bottom, BOX[3])
    assert set(state.snap_sides) == {"left", "top", "right", "bottom"}


def test_a_bare_click_selects_the_whole_window() -> None:
    state = make_state()
    state.press(250, 200)
    region = state.release(250, 200)
    assert region is not None
    assert near(region.x, BOX[0]) and near(region.right, BOX[2])
    assert near(region.y, BOX[1]) and near(region.bottom, BOX[3])


def test_a_bare_click_on_empty_desktop_selects_nothing() -> None:
    state = make_state()
    state.press(700, 550)
    assert state.release(700, 550) is None


def test_alt_releases_the_pointer_from_the_borders() -> None:
    state = make_state()
    state.snapping = False
    state.press(105, 85)
    state.drag(395, 315)
    assert state.release(395, 315) == Geometry(105, 85, 290, 230)
    assert state.snap_sides == ()
    # A bare click is a click, not a window pick, while snapping is off.
    state.clear()
    state.press(250, 200)
    assert state.release(250, 200) is None


def test_move_slides_the_region_onto_a_border() -> None:
    state = make_state()
    state.region = Geometry(BOX[0] + 3, 200, 60, 40)
    state.press(120, 220)
    assert state.mode is SelectionMode.MOVE
    state.drag(125, 225)
    region = state.release(125, 225)
    assert region is not None
    assert near(region.x, BOX[0])
    assert region.width == 60 and region.height == 40


def test_resize_snaps_the_dragged_corner() -> None:
    state = make_state()
    state.region = Geometry(BOX[0], BOX[1], 100, 60)
    assert state.press(BOX[0], BOX[1]) is SelectionMode.RESIZE
    state.drag(150, 150)
    region = state.release(150, 150)
    assert region is not None
    assert region.width >= MIN_SIZE and region.height >= MIN_SIZE


def test_hover_previews_the_box_under_the_pointer() -> None:
    state = make_state()
    box = state.hover(250, 200)
    assert box is not None and near(box.x, BOX[0])
    state.region = Geometry(BOX[0], BOX[1], 300, 240)
    assert state.hover(250, 200) is None
    assert state.hover(700, 550) is None
