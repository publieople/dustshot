"""Pinned image windows: always-on-top overlay snippets for Dustshot."""

from __future__ import annotations

import os
import tempfile
from typing import TYPE_CHECKING, Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gtk
from PIL import Image

from ..capture.base import Geometry
from ..i18n import _
from ..snap import centre_position, snap_position
from .layer import init_window, layer_shell
from .pixbuf import to_pixbuf

if TYPE_CHECKING:  # the editor imports this module, so keep the import lazy
    from ..annotation.document import Document
    from .editor import EditorWindow

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
        group: str | None = None,
        on_close: Any = None,
    ) -> None:
        super().__init__(application=app)
        self.app = app
        self.settings = settings
        self.group = group
        self.linked = False
        self.image = image.convert("RGBA") if image.mode == "RGBA" else image.convert("RGB")
        self.scale = max(MIN_SCALE, min(MAX_SCALE, float(scale)))
        self.position = (int(position[0]), int(position[1]))
        self.on_close = on_close
        self._drag_start: tuple[int, int] | None = None
        self._drag_bounds: Geometry | None = None
        self.click_through = False
        self._toolbar: Gtk.Widget | None = None
        self._editor: Any = None
        self._closed = False

        self.set_title("Dustshot pin")
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
            namespace="dustshot-pin",
        )
        self._shell = layer_shell()
        self._apply_size()

        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", self._on_drag_begin)
        drag.connect("drag-update", self._on_drag_update)
        self.area.add_controller(drag)

        right = Gtk.GestureClick()
        right.set_button(3)
        right.connect("pressed", lambda *_args: self.close())
        self.area.add_controller(right)

        scroll = Gtk.EventControllerScroll()
        scroll.set_flags(Gtk.EventControllerScrollFlags.BOTH_AXES)
        scroll.connect("scroll", self._on_scroll)
        self.area.add_controller(scroll)

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_key)
        self.add_controller(keys)

        motion = Gtk.EventControllerMotion()
        motion.connect("enter", lambda *_args: self._show_toolbar(True))
        motion.connect("leave", lambda *_args: self._show_toolbar(False))
        self.area.add_controller(motion)

        self.connect("close-request", self._on_close_request)
        if app is not None:
            app.hold()

    # ------------------------------------------------------------------ layout
    def _build(self) -> Gtk.Widget:
        overlay = Gtk.Overlay()
        overlay.set_child(self.area)
        # A FlowBox keeps the controls usable on small pins: the surface is only
        # as wide as the image, so a single long row would be clipped.
        toolbar = Gtk.FlowBox()
        toolbar.set_selection_mode(Gtk.SelectionMode.NONE)
        toolbar.set_max_children_per_line(3)
        toolbar.set_column_spacing(4)
        toolbar.set_row_spacing(4)
        toolbar.set_halign(Gtk.Align.CENTER)
        toolbar.set_valign(Gtk.Align.END)
        toolbar.set_margin_bottom(8)
        for label, callback, tip in (
            ("1:1", self._reset_zoom, _("恢复原始大小")),
            (_("编辑"), self._edit, _("在编辑器里继续修改这张贴图 (Ctrl+E)")),
            (_("复制"), self._copy, _("复制到剪贴板")),
            (_("保存"), self._save, _("保存为文件")),
            (_("贴图"), self._pin_again, _("再贴一张")),
            (_("关闭"), lambda: self.close(), _("关闭 (Esc)")),
        ):
            button = Gtk.Button(label=label)
            button.connect("clicked", lambda _b, cb=callback: cb())
            button.set_tooltip_text(tip)
            toolbar.append(button)

        centre = Gtk.Button(label=_("居中"))
        centre.set_tooltip_text(_("把贴图移到屏幕中央"))
        centre.connect("clicked", lambda _b: self._centre())
        toolbar.append(centre)

        self.link_button = Gtk.ToggleButton(label=_("联动"))
        self.link_button.set_tooltip_text(_("与其他开启联动的贴图一起移动和缩放"))
        self.link_button.connect("toggled", self._on_link_toggled)
        toolbar.append(self.link_button)

        self.click_button = Gtk.ToggleButton(label=_("穿透"))
        self.click_button.set_tooltip_text(_("只让下方工具条响应鼠标，图片区域点击穿透"))
        self.click_button.connect("toggled", self._on_click_through_toggled)
        toolbar.append(self.click_button)

        self.opacity_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0.2, 1.0, 0.05)
        self.opacity_scale.set_value(1.0)
        self.opacity_scale.set_size_request(104, -1)
        self.opacity_scale.set_tooltip_text(_("不透明度"))
        self.opacity_scale.connect("value-changed", self._on_opacity_changed)
        toolbar.append(self.opacity_scale)

        self._toolbar = toolbar
        overlay.add_overlay(toolbar)
        return overlay

    def _apply_size(self) -> None:
        width = max(1, round(self.image.width * self.scale))
        height = max(1, round(self.image.height * self.scale))
        self.area.set_size_request(width, height)
        self.area.queue_draw()
        if self.click_through:
            self._apply_input_region()

    def _move_to(self, x: int, y: int) -> None:
        """Move the layer surface by rewriting its layer-shell margins."""

        self.position = (max(0, int(x)), max(0, int(y)))
        shell = self._shell
        if shell is None:
            return
        shell.set_margin(self, shell.Edge.TOP, self.position[1])
        shell.set_margin(self, shell.Edge.LEFT, self.position[0])

    def place(self, x: int, y: int) -> None:
        """Move this window, used for grouped moves."""

        self._move_to(x, y)

    def set_scale(self, scale: float) -> None:
        """Set an absolute zoom level, used for grouped zooms."""

        value = max(MIN_SCALE, min(MAX_SCALE, float(scale)))
        if abs(value - self.scale) < 1e-4:
            return
        self.scale = value
        self._apply_size()

    def _move_with_group(self, x: int, y: int) -> None:
        mover = getattr(self.app, "move_pin", None)
        if self.group is not None and mover is not None:
            mover(self, x, y)
            return
        self._move_to(x, y)

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
        self._drag_bounds = self._monitor_bounds()

    def _on_drag_update(self, gesture: Gtk.GestureDrag, dx: float, dy: float) -> None:
        if self._drag_start is None:
            return
        x = int(self._drag_start[0] + dx)
        y = int(self._drag_start[1] + dy)
        bounds = self._drag_bounds
        if bounds is not None:
            width = max(1, round(self.image.width * self.scale))
            height = max(1, round(self.image.height * self.scale))
            x, y = snap_position(x, y, width, height, bounds)
        self._move_with_group(x, y)

    def _on_scroll(self, controller: Gtk.EventControllerScroll, dx: float, dy: float) -> bool:
        if dy == 0:
            return False
        self._zoom(1.1 if dy < 0 else (1 / 1.1))
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
        if ctrl and keyval in (Gdk.KEY_e, Gdk.KEY_E):
            self._edit()
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
        zoomer = getattr(self.app, "zoom_pin", None)
        if self.group is not None and zoomer is not None:
            zoomer(self, factor)
            return
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
            handle, path = tempfile.mkstemp(prefix="dustshot-pin-", suffix=".png")
            os.close(handle)
            self.image.save(path)
            return path
        return str(save_image(self.image, capture))

    def _edit(self) -> EditorWindow | None:
        """Reopen the editor on this pin so the picture can be changed further."""

        from .editor import EditorWindow

        if self._editor is not None:
            self._editor.present()
            return self._editor
        editor = EditorWindow(self.app, self._pin_document(), self.settings, on_done=self._editor_done)
        self._editor = editor
        editor.present()
        return editor

    def _pin_document(self) -> Document:
        from ..annotation.document import Document

        return Document(self.image.copy(), getattr(self.settings, "annotation", None), source="pin")

    def _editor_done(self, editor: EditorWindow) -> None:
        """Take the edited picture back into the pin and drop the editor."""

        self._editor = None
        if self._closed:
            return
        self.set_image(editor.document.render())

    def set_image(self, image: Image.Image) -> None:
        """Replace the pinned picture, keeping the current zoom level."""

        self.image = image.convert("RGBA") if image.mode == "RGBA" else image.convert("RGB")
        self._apply_size()

    def _pin_again(self) -> None:
        parent = self.app
        spot = (self.position[0] + 28, self.position[1] + 28)
        spawner = getattr(parent, "spawn_pin", None)
        if spawner is not None:
            spawner(self.image.copy(), position=spot, scale=self.scale, group=self.group)
            return
        PinWindow(parent, self.image.copy(), self.settings, position=spot, scale=self.scale)

    # -------------------------------------------------------------- toolbars
    def _monitor_bounds(self) -> Geometry:
        display = self.get_display()
        monitor = None
        surface = self.get_surface()
        if surface is not None:
            monitor = display.get_monitor_at_surface(surface)
        if monitor is None:
            monitor = display.get_primary_monitor()
        if monitor is None:
            return Geometry(0, 0, 1920, 1080)
        geometry = monitor.get_geometry()
        return Geometry(geometry.x, geometry.y, geometry.width, geometry.height)

    def _centre(self) -> None:
        width = max(1, round(self.image.width * self.scale))
        height = max(1, round(self.image.height * self.scale))
        x, y = centre_position(width, height, self._monitor_bounds())
        self._move_to(x, y)

    def _on_link_toggled(self, button: Gtk.ToggleButton) -> None:
        self.linked = bool(button.get_active())
        linker = getattr(self.app, "link_pin", None)
        if linker is not None:
            linker(self, self.linked)

    def _on_click_through_toggled(self, button: Gtk.ToggleButton) -> None:
        self.click_through = bool(button.get_active())
        self._apply_input_region()

    def _apply_input_region(self) -> None:
        surface = self.get_surface()
        if surface is None:
            return
        if not self.click_through:
            surface.set_input_region(None)
            return
        import cairo

        width = max(1, round(self.image.width * self.scale))
        height = max(1, round(self.image.height * self.scale))
        strip = min(max(56, height // 4), height)
        region = cairo.Region([cairo.RectangleInt(0, max(0, height - strip), width, strip)])
        surface.set_input_region(region)

    def _on_opacity_changed(self, scale: Gtk.Scale) -> None:
        self.set_opacity(float(scale.get_value()))

    def _on_close_request(self, window: Gtk.Window) -> bool:
        self._closed = True
        if self.app is not None:
            if self.on_close is not None:
                self.on_close(self)
            else:
                forget = getattr(self.app, "forget_pin", None)
                if forget is not None:
                    forget(self)
            self.app.release()
        return False


def pin_image(app: Any, image: Image.Image, settings: Any = None, **kwargs: Any) -> PinWindow:
    return PinWindow(app, image, settings, **kwargs)
