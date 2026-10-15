"""Annotation primitives: geometry and serialisation round trips."""

from __future__ import annotations

import pytest

from dustshot.annotation.items import (
    ArrowItem,
    EllipseItem,
    HighlighterItem,
    Item,
    LineItem,
    MosaicItem,
    PencilItem,
    RectItem,
    SerialItem,
    Style,
    TextItem,
    item_from_dict,
    items_from_jsonable,
    items_to_jsonable,
)


def all_items() -> list[Item]:
    return [
        RectItem(x=10, y=10, width=100, height=50, radius=4),
        EllipseItem(x=0, y=0, width=40, height=40),
        LineItem(x1=0, y1=0, x2=50, y2=50),
        ArrowItem(x1=0, y1=0, x2=80, y2=20),
        PencilItem(points=[(0, 0), (5, 5), (10, 0)]),
        HighlighterItem(points=[(0, 0), (30, 30)]),
        TextItem(x=5, y=5, text="你好 Dustshot", size=18, bold=True),
        SerialItem(x=100, y=100, number=3, size=22),
        MosaicItem(x=20, y=20, width=60, height=60, mode="blur", blur_radius=8),
    ]


@pytest.mark.parametrize("index", range(len(all_items())))
def test_round_trip(index: int) -> None:
    item = all_items()[index]
    payload = item.to_dict()
    restored = item_from_dict(payload)
    assert type(restored) is type(item)
    assert restored.to_dict() == payload


def test_jsonable_round_trip() -> None:
    items = all_items()
    payload = items_to_jsonable(items)
    restored = items_from_jsonable(payload)
    assert [item.to_dict() for item in restored] == [item.to_dict() for item in items]


def test_bbox_and_move() -> None:
    rect = RectItem(x=10, y=20, width=30, height=40)
    box = rect.bbox()
    assert (box.x, box.y, box.width, box.height) == (10, 20, 30, 40)
    rect.move(5, -5)
    assert (rect.x, rect.y) == (15, 15)

    line = LineItem(x1=10, y1=10, x2=50, y2=30)
    box = line.bbox()
    assert (box.x, box.y, box.width, box.height) == (10, 10, 40, 20)


def test_scaled_resizes_geometry() -> None:
    rect = RectItem(x=10, y=10, width=40, height=40)
    rect.scaled(2.0)
    assert (rect.x, rect.y, rect.width, rect.height) == (20, 20, 80, 80)

    stroke = PencilItem(points=[(10, 10), (20, 20)])
    stroke.scaled(0.5)
    assert stroke.points == [(5, 5), (10, 10)]


def test_style_helpers() -> None:
    style = Style(color="#ff3b30", width=4, opacity=0.5)
    assert style.rgb() == (255, 59, 48)
    assert style.alpha() == 0.5
    assert Style(color="#00ff00").alpha() == 1.0
    assert Style.from_dict(style.to_dict()) == style


def test_arrow_head_points() -> None:
    arrow = ArrowItem(x1=0, y1=0, x2=100, y2=0)
    assert len(arrow.head_points()) == 3
    assert arrow.angle() == pytest.approx(0.0)


def test_style_carries_the_solid_flag() -> None:
    style = Style(color="#101114", fill=True, solid=True)
    payload = style.to_dict()
    assert payload["solid"] is True
    assert Style.from_dict(payload) == style
    assert Style.from_dict({"color": "#ff3b30"}).solid is False
