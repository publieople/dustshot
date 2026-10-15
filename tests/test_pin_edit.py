"""The pin window can hand its picture to the editor and take the result back."""

from __future__ import annotations

from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk
from PIL import Image

from dustshot.annotation.document import Document
from dustshot.annotation.items import RectItem, Style
from dustshot.capture.base import Geometry
from dustshot.ui import editor as editor_module
from dustshot.ui.pin import PinWindow


class FakeEditor:
    """Stands in for EditorWindow, so these tests need no display."""

    def __init__(self, app: Any, document: Document, settings: Any = None, on_done: Any = None) -> None:
        self.app = app
        self.document = document
        self.settings = settings
        self.on_done = on_done
        self.presented = 0

    def present(self) -> None:
        self.presented += 1

    def draw_red_box(self) -> None:
        self.document.items.append(
            RectItem(style=Style(color="#ff0000", fill=True), x=1, y=1, width=6, height=6)
        )


def make_pin(size: tuple[int, int] = (40, 30)) -> PinWindow:
    """Allocate a PinWindow without a display and without layer-shell."""

    pin = PinWindow.__new__(PinWindow)
    pin.image = Image.new("RGB", size, "white")
    pin.settings = None
    pin.app = None
    pin._editor = None
    pin._closed = False
    pin.resizes = []
    pin._apply_size = lambda: pin.resizes.append(pin.image.size)
    return pin


def use_fake_editor(monkeypatch: Any) -> list[FakeEditor]:
    created: list[FakeEditor] = []

    def factory(app: Any, document: Document, settings: Any = None, on_done: Any = None) -> FakeEditor:
        editor = FakeEditor(app, document, settings, on_done=on_done)
        created.append(editor)
        return editor

    monkeypatch.setattr(editor_module, "EditorWindow", factory)
    return created


def test_edit_opens_the_editor_on_the_pinned_picture(monkeypatch):
    created = use_fake_editor(monkeypatch)
    pin = make_pin((40, 30))

    editor = pin._edit()

    assert len(created) == 1
    assert editor is created[0]
    assert editor.presented == 1
    assert editor.document.size == (40, 30)
    assert editor.document.items == []
    assert pin._editor is editor


def test_edit_reuses_the_open_editor(monkeypatch):
    created = use_fake_editor(monkeypatch)
    pin = make_pin()
    first = pin._edit()

    second = pin._edit()

    assert second is first
    assert len(created) == 1
    assert first.presented == 2


def test_ctrl_e_opens_the_editor(monkeypatch):
    created = use_fake_editor(monkeypatch)
    pin = make_pin()
    state = Gdk.ModifierType.CONTROL_MASK

    handled = pin._on_key(None, Gdk.KEY_e, 0, state)

    assert handled is True
    assert len(created) == 1


def test_closing_the_editor_updates_the_pin(monkeypatch):
    use_fake_editor(monkeypatch)
    pin = make_pin((40, 30))
    editor = pin._edit()
    editor.draw_red_box()

    editor.on_done(editor)

    assert pin._editor is None
    assert pin.image.getpixel((3, 3)) == (255, 0, 0)
    assert pin.resizes[-1] == (40, 30)


def test_editing_a_smaller_picture_resizes_the_pin(monkeypatch):
    use_fake_editor(monkeypatch)
    pin = make_pin((80, 60))
    editor = pin._edit()
    assert editor.document.crop(Geometry(0, 0, 20, 10)) is True

    editor.on_done(editor)

    assert pin.image.size == (20, 10)
    assert pin.resizes[-1] == (20, 10)


def test_a_late_result_is_dropped_once_the_pin_is_closed(monkeypatch):
    use_fake_editor(monkeypatch)
    pin = make_pin()
    editor = pin._edit()
    editor.draw_red_box()
    pin._closed = True

    editor.on_done(editor)

    assert pin.image.getpixel((3, 3)) == (255, 255, 255)
    assert pin.resizes == []


def test_set_image_keeps_the_zoom_level():
    pin = make_pin((40, 30))
    pin.scale = 1.5

    pin.set_image(Image.new("RGB", (10, 10), "blue"))

    assert pin.scale == 1.5
    assert pin.image.size == (10, 10)
    assert pin.resizes == [(10, 10)]
