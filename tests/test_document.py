"""Document model: edits, undo history, serial numbers and projects."""

from __future__ import annotations

from PIL import Image

from dustshot.annotation.document import Document
from dustshot.annotation.items import RectItem, SerialItem, Style
from dustshot.config import AnnotationSettings


def make_document() -> Document:
    return Document(Image.new("RGB", (200, 150), (255, 255, 255)), AnnotationSettings())


def test_add_remove_and_undo() -> None:
    doc = make_document()
    rect = RectItem(x=10, y=10, width=50, height=40)
    doc.add(rect)
    assert len(doc.items) == 1
    assert doc.can_undo
    assert doc.undo()
    assert doc.items == []
    assert doc.can_redo
    assert doc.redo()
    assert len(doc.items) == 1


def test_update_and_revision() -> None:
    doc = make_document()
    rect = RectItem(x=0, y=0, width=10, height=10)
    doc.add(rect)
    revision = doc.revision
    moved = RectItem(x=5, y=5, width=10, height=10, style=Style(), id=rect.id)
    doc.update(moved)
    assert doc.revision > revision
    assert doc.items[0].x == 5


def test_hit_test_and_remove_last() -> None:
    doc = make_document()
    doc.add(RectItem(x=10, y=10, width=40, height=40))
    assert doc.hit_test(20, 20) is not None
    assert doc.hit_test(199, 149) is None
    assert doc.remove_last()
    assert doc.items == []


def test_serial_numbers_increment() -> None:
    doc = make_document()
    first = doc.add_serial(10, 10)
    second = doc.add_serial(40, 40)
    assert isinstance(first, SerialItem)
    assert (first.number, second.number) == (1, 2)
    assert doc.next_serial() == 3


def test_clear_and_dirty() -> None:
    doc = make_document()
    assert not doc.dirty
    doc.add(RectItem(x=0, y=0, width=5, height=5))
    assert doc.dirty
    doc.clear()
    assert doc.items == []
    assert not doc.dirty
    assert doc.undo()
    assert len(doc.items) == 1


def test_project_round_trip(tmp_path) -> None:
    doc = make_document()
    doc.add(RectItem(x=10, y=10, width=50, height=40))
    doc.add_serial(100, 100)
    path = doc.save_project(tmp_path / "shot.cln")
    assert path.exists()

    restored = Document.load_project(path)
    assert [item.to_dict() for item in restored.items] == [item.to_dict() for item in doc.items]
    assert restored.size == doc.size


def test_render_returns_base_size() -> None:
    doc = make_document()
    doc.add(RectItem(x=10, y=10, width=50, height=40))
    rendered = doc.render()
    assert rendered.size == (200, 150)
