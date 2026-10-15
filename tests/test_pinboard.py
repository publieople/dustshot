"""Tests for the pin group model."""

from __future__ import annotations

from dustshot.pinboard import MAX_SCALE, MIN_SCALE, PinBoard


class FakePin:
    def __init__(self, x: int = 0, y: int = 0, scale: float = 1.0) -> None:
        self.position = (x, y)
        self.scale = scale

    def place(self, x: int, y: int) -> None:
        self.position = (x, y)

    def set_scale(self, scale: float) -> None:
        self.scale = scale


def test_a_lone_pin_moves_and_zooms_by_itself() -> None:
    board = PinBoard()
    pin = FakePin(10, 20)
    board.add(pin)
    assert board.members(pin) == [pin]
    assert board.move(pin, 40, 60) == [(pin, 40, 60)]
    assert [(member, round(scale, 4)) for member, scale in board.zoom(pin, 2.0)] == [(pin, 2.0)]


def test_grouping_needs_two_pins() -> None:
    board = PinBoard()
    pin = FakePin()
    board.group([pin])
    assert board.group_of(pin) is None


def test_grouped_pins_move_by_the_same_delta() -> None:
    board = PinBoard()
    first, second = FakePin(100, 100), FakePin(300, 220)
    board.group([first, second])
    moves = board.move(first, 130, 90)
    assert moves == [(first, 130, 90), (second, 330, 210)]


def test_grouped_pins_zoom_by_the_same_factor() -> None:
    board = PinBoard()
    first, second = FakePin(), FakePin()
    board.group([first, second])
    for member, scale in board.zoom(first, 2.0):
        member.set_scale(scale)
    assert (first.scale, second.scale) == (2.0, 2.0)
    for member, scale in board.zoom(second, 0.5):
        member.set_scale(scale)
    assert (first.scale, second.scale) == (1.0, 1.0)


def test_zoom_is_clamped_for_every_member() -> None:
    board = PinBoard()
    first, second = FakePin(scale=3.5), FakePin(scale=0.2)
    board.group([first, second])
    assert board.zoom(first, 4.0) == [(first, MAX_SCALE), (second, 0.8)]
    assert board.zoom(first, 0.001) == [(first, MIN_SCALE), (second, MIN_SCALE)]


def test_moves_never_go_negative() -> None:
    board = PinBoard()
    first, second = FakePin(50, 50), FakePin(4, 4)
    board.group([first, second])
    moves = board.move(first, 0, 0)
    assert {pin: (x, y) for pin, x, y in moves} == {first: (0, 0), second: (0, 0)}


def test_pin_can_only_belong_to_one_group() -> None:
    board = PinBoard()
    first, second, third = FakePin(), FakePin(), FakePin()
    board.group([first, second])
    board.group([second, third])
    assert board.group_of(first) is None
    assert board.group_of(second) == board.group_of(third)
    assert board.members(second) == [second, third]
    assert board.groups() == [[second, third]]


def test_removing_a_member_leaves_the_rest_grouped() -> None:
    board = PinBoard()
    first, second, third = FakePin(), FakePin(), FakePin()
    board.group([first, second, third])
    board.remove(second)
    assert board.members(first) == [first, third]
    board.remove(first)
    assert board.members(third) == [third]
    board.remove(third)
    assert board.groups() == []


def test_ungroup_detaches_one_pin() -> None:
    board = PinBoard()
    first, second = FakePin(), FakePin()
    board.group([first, second])
    board.ungroup(first)
    assert board.group_of(first) is None
    assert board.members(second) == [second]


def test_move_after_regrouping_follows_the_new_group() -> None:
    board = PinBoard()
    first, second, third = FakePin(0, 0), FakePin(0, 100), FakePin(0, 200)
    board.group([first, second])
    board.group([first, third])
    moves = board.move(first, 10, 10)
    assert moves == [(first, 10, 10), (third, 10, 210)]
