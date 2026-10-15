"""Cropping and rotating the base image together with its annotations."""

from __future__ import annotations

from PIL import Image

from dustshot.annotation.document import MAX_IMAGE_HISTORY, Document
from dustshot.annotation.items import (
    LineItem,
    MosaicItem,
    PencilItem,
    RectItem,
    TextItem,
)
from dustshot.capture.base import Geometry
from dustshot.config import AnnotationSettings


def make_document(size: tuple[int, int] = (100, 80)) -> Document:
    return Document(Image.new("RGB", size, (255, 255, 255)), AnnotationSettings())


def test_crop_trims_the_image_and_shifts_the_annotations() -> None:
    doc = make_document()
    doc.add(RectItem(x=30, y=20, width=20, height=10))
    assert doc.crop(Geometry(10, 5, 50, 40))
    assert doc.size == (50, 40)
    box = doc.items[0]
    assert (box.x, box.y) == (20, 15)


def test_crop_keeps_partly_visible_items_and_drops_the_rest() -> None:
    doc = make_document()
    doc.add(RectItem(x=0, y=0, width=30, height=30))
    doc.add(RectItem(x=60, y=60, width=10, height=10))
    assert doc.crop(Geometry(20, 20, 40, 40))
    assert len(doc.items) == 1
    assert doc.items[0].x == -20


def test_crop_rejects_empty_and_unchanged_boxes() -> None:
    doc = make_document()
    assert doc.crop(Geometry(0, 0, 100, 80)) is False
    assert doc.crop(Geometry(200, 200, 10, 10)) is False
    assert doc.size == (100, 80)
    assert not doc.can_undo


def test_crop_clamps_to_the_image() -> None:
    doc = make_document()
    assert doc.crop(Geometry(90, 70, 100, 100))
    assert doc.size == (10, 10)


def test_crop_is_undoable_and_redoable() -> None:
    doc = make_document()
    doc.add(RectItem(x=30, y=20, width=20, height=10))
    assert doc.crop(Geometry(10, 5, 50, 40))
    assert doc.undo()
    assert doc.size == (100, 80)
    assert (doc.items[0].x, doc.items[0].y) == (30, 20)
    assert doc.redo()
    assert doc.size == (50, 40)
    assert (doc.items[0].x, doc.items[0].y) == (20, 15)


def test_rotate_swaps_the_size_and_turns_boxes() -> None:
    doc = make_document()
    doc.add(RectItem(x=10, y=20, width=30, height=40))
    assert doc.rotate(1)
    assert doc.size == (80, 100)
    box = doc.items[0]
    assert (box.x, box.y, box.width, box.height) == (20, 10, 40, 30)


def test_rotate_turns_lines_and_strokes_clockwise() -> None:
    doc = make_document()
    doc.add(LineItem(x1=10, y1=20, x2=30, y2=60))
    doc.add(PencilItem(points=[(0, 0), (5, 79)]))
    assert doc.rotate(1)
    line = doc.items[0]
    assert (line.x1, line.y1, line.x2, line.y2) == (59, 10, 19, 30)
    assert doc.items[1].points == [(79, 0), (0, 5)]


def test_rotate_anticlockwise_matches_three_clockwise_turns() -> None:
    doc = make_document()
    doc.add(RectItem(x=10, y=20, width=30, height=40))
    assert doc.rotate(-1)
    assert doc.size == (80, 100)
    box = doc.items[0]
    assert (box.x, box.y, box.width, box.height) == (20, 60, 40, 30)


def test_labels_keep_their_orientation() -> None:
    doc = make_document()
    doc.add(TextItem(x=0, y=0, text="hi", size=20))
    before = doc.items[0].bbox()
    assert doc.rotate(1)
    label = doc.items[0]
    assert label.text == "hi"
    # The anchor follows the pixels, the glyphs stay upright and the same size.
    assert (label.x, label.y) == (80 - before.y - before.height, before.x)
    after = label.bbox()
    assert (after.width, after.height) == (before.width, before.height)


def test_a_full_turn_restores_the_document() -> None:
    doc = make_document()
    doc.add(RectItem(x=10, y=20, width=30, height=40))
    doc.add(LineItem(x1=1, y1=2, x2=3, y2=4))
    assert doc.rotate(4) is False
    for _ in range(4):
        assert doc.rotate(1)
    assert doc.size == (100, 80)
    box = doc.items[0]
    assert (box.x, box.y, box.width, box.height) == (10, 20, 30, 40)
    line = doc.items[1]
    assert (line.x1, line.y1, line.x2, line.y2) == (1, 2, 3, 4)


def test_rotation_is_undoable() -> None:
    doc = make_document()
    doc.add(RectItem(x=10, y=20, width=30, height=40))
    assert doc.rotate(1)
    assert doc.undo()
    assert doc.size == (100, 80)
    assert (doc.items[0].x, doc.items[0].width) == (10, 30)
    assert doc.redo()
    assert doc.size == (80, 100)
    assert (doc.items[0].x, doc.items[0].width) == (20, 40)


def test_rendering_survives_a_crop_that_leaves_items_half_outside() -> None:
    doc = make_document()
    doc.add(RectItem(x=0, y=0, width=40, height=40))
    doc.add(MosaicItem(x=0, y=0, width=40, height=40, mode="blur"))
    doc.add(TextItem(x=0, y=0, text="hi", size=14))
    assert doc.crop(Geometry(20, 20, 40, 40))
    assert doc.render().size == (40, 40)


def test_the_oldest_base_images_are_released() -> None:
    doc = Document(Image.new("RGB", (400, 300), (0, 0, 0)), AnnotationSettings())
    for _ in range(MAX_IMAGE_HISTORY + 3):
        assert doc.rotate(1)
    steps = 0
    while doc.undo():
        steps += 1
    assert steps == MAX_IMAGE_HISTORY
