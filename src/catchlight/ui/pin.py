"""Pinned image windows: always-on-top overlay snippets for Catchlight."""

from __future__ import annotations

import os
import tempfile
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, Gtk
from PIL import Image

from .layer import init_window
from .pixbuf import to_pixbuf

MIN_SCALE = 0.15
MAX_SCALE = 4.0
BORDER = (0.98, 0.30, 0.24)


class PinWindow(Gtk.ApplicationWindow):
    """A frameless overlay window showing one image."""

    def __init__(
        self,
        app: Any,
        image: Image.Image,
        settings: Any = None,
        position: tuple[int, int] = (140, 140),
        scale: float = 1.0,
        on_close: Any = None,
    ) -> None:
        super().__init__(application=app)
        self.app = app
        self.settings = settings
        self.image = image.convert("RGBA") if image.mode == "RGBA" else image.convert("RGB")
        self.scale = max(MIN_SCALE, min(MAX_SCALE, float(scale)))
        self.position = (int(position[0]), int(position[1]))
        self.on_close = on_close
        self._drag_start: tuple[int, int] | None = None
        self._toolbar: Gtk.Widget | None = None

        self.set_title("Catchlight pin")
        self.area = Gtk.DrawingArea()
        self.area.set_draw_func(self._draw)
        self.set_child(self._build())
        init_window(
            self,
            layer="overlay",
            anchors=("top", "left"),
            margins=(self.position[1], 0, 0, self.position[0]),
            exclusive_zone=-1,
            keyboard="none",
            namespace="catchlight-pin",
        )
        self._apply_size()

        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", self._on_drag_begin)
        drag.connect("drag-update", self._on_drag_update)
        self.area.add_controller(drag)

        right = Gtk.GestureClick()
        right.set_button(3)
        right.connect("pressed", lambda *_: self.close())
        self.area.add_controller(right)

        scroll = Gtk.EventControllerScroll()
        scroll.set_flags(Gtk.EventControllerScrollFlags.BOTH_AXES)
        scroll.connect("scroll", self._on_scroll)
        self.area.add_controller(scroll)

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_key)
        self.add_controller(keys)

        motion = Gtk.EventControllerMotion()
        motion.connect("enter", lambda *_: self._show_toolbar(True))
        motion.connect("leave", lambda *_: self._show_toolbar(False))
        self.area.add_controller(motion)

        self.connect("close-request", self._on_close_request)
        if app is not None:
            app.hold()

    # ------------------------------------------------------------------ layout
    def _build(self) -> Gtk.Widget:
        overlay = Gtk.Overlay()
        overlay.set_child(self.area)
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        toolbar.add_css_class("toolbar")
        toolbar.set_halign(Gtk.Align.CENTER)
        toolbar.set_valign(Gtk.Align.END)
        toolbar.set_margin_bottom(8)
        for label, callback, tip in (
            ("1:1", self._reset_zoom, "恢复原始大小"),
            ("复制", self._copy, "复制到剪贴板"),
            ("保存", self._save, "保存为文件"),
            ("贴图", self._pin_again, "再贴一张"),
            ("关闭", lambda: self.close(), "关闭 (Esc)"),
        ):
            button = Gtk.Button(label=label)
            button.connect("clicked", lambda _b, cb=callback: cb())
            button.set_tooltip_text(tip)
            toolbar.append(button)
        self._toolbar = toolbar
        overlay.add_overlay(toolbar)
        return overlay

    def _apply_size(self) -> None:
        width = max(1, round(self.image.width * self.scale))
        height = max(1, round(self.image.height * self.scale))
        self.area.set_size_request(width, height)
        self.area.queue_draw()

    def _move_to(self, x: int, y: int) -> None:
        self.position = (int(x), int(y))
        self.set_margin_top(max(0, int(y)))
        self.set_margin_left(max(0, int(x)))

    def _show_toolbar(self, visible: bool) -> None:
        if self._toolbar is not None:
            self._toolbar.set_visible(visible)

    # ----------------------------------------------------------------- drawing
    def _draw(self, area: Gtk.DrawingArea, cr: Any, width: int, height: int) -> None:
        cr.set_source_rgba(0.08, 0.09, 0.11, 0.9)
        cr.paint()
        cr.set_source_rgba(*BORDER, 0.9)
        cr.set_line_width(2.0)
        cr.rectangle(1.0, 1.0, max(1, width - 2), max(1, height - 2))
        cr.stroke()
        if self.scale == 1.0:
            pixbuf = to_pixbuf(self.image)
            cr.save()
            cr.translate(2.0, 2.0)
            Gdk.cairo_set_source_pixbuf(cr, pixbuf, 0, 0)
            cr.paint()
            cr.restore()
            return
        target = (max(1, round(self.image.width * self.scale)), max(1, round(self.image.height * self.scale)))
        resized = self.image.resize(target, Image.LANCZOS)
        pixbuf = to_pixbuf(resized)
        cr.save()
        cr.translate(2.0, 2.0)
        Gdk.cairo_set_source_pixbuf(cr, pixbuf, 0, 0)
        cr.paint()
        cr.restore()

    # ------------------------------------------------------------------ events
    def _on_drag_begin(self, gesture: Gtk.GestureDrag, sx: float, sy: float) -> None:
        self._drag_start = self.position

    def _on_drag_update(self, gesture: Gtk.GestureDrag, dx: float, dy: float) -> None:
        if self._drag_start is None:
            return
        self._move_to(int(self._drag_start[0] + dx), int(self._drag_start[1] + dy))

    def _on_scroll(self, controller: Gtk.EventControllerScroll, dx: float, dy: float) -> bool:
        if dy == 0:
            return False
        factor = 1.1 if dy < 0 else (1 / 1.1)
        new_scale = max(MIN_SCALE, min(MAX_SCALE, self.scale * factor))
        if abs(new_scale - self.scale) < 1e-4:
            return True
        self.scale = new_scale
        self._apply_size()
        return True

    def _on_key(self, controller: Gtk.EventControllerKey, keyval: int, code: int, state: Any) -> bool:
        ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
        if keyval == Gdk.KEY_Escape:
            self.close()
            return True
        if ctrl and keyval in (Gdk.KEY_c, Gdk.KEY_C):
            self._copy()
            return True
        if ctrl and keyval in (Gdk.KEY_s, Gdk.KEY_S):
            self._save()
            return True
        if keyval in (Gdk.KEY_plus, Gdk.KEY_equal):
            self._zoom(1.1)
            return True
        if keyval == Gdk.KEY_minus:
            self._zoom(1 / 1.1)
            return True
        if keyval == Gdk.KEY_1:
            self._reset_zoom()
            return True
        return False

    # ----------------------------------------------------------------- actions
    def _zoom(self, factor: float) -> None:
        self.scale = max(MIN_SCALE, min(MAX_SCALE, self.scale * factor))
        self._apply_size()

    def _reset_zoom(self) -> None:
        self.scale = 1.0
        self._apply_size()

    def _copy(self) -> bool:
        from ..clipboard import copy_image

        return copy_image(self.image)

    def _save(self) -> str | None:
        from ..output import save_image

        capture = getattr(self.settings, "capture", None)
        if capture is None:
            handle, path = tempfile.mkstemp(prefix="catchlight-pin-", suffix=".png")
            os.close(handle)
            self.image.save(path)
            return path
        return str(save_image(self.image, capture))

    def _pin_again(self) -> None:
        parent = self.app
        PinWindow(
            parent,
            self.image.copy(),
            self.settings,
            position=(self.position[0] + 28, self.position[1] + 28),
            scale=self.scale,
        )

    def _on_close_request(self, window: Gtk.Window) -> bool:
        if self.app is not None:
            self.app.release()
        if self.on_close is not None:
            self.on_close(self)
        return False


def pin_image(app: Any, image: Image.Image, settings: Any = None, **kwargs: Any) -> PinWindow:
    return PinWindow(app, image, settings, **kwargs)
