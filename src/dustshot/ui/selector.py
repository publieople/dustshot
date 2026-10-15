"""Full screen region selection overlay built on GTK4 layer shell.

One overlay window is created per monitor. The screenshot of each output is
taken once, up front, and reused for the dimmed backdrop, the bright selection
and the magnifier, so confirming a selection needs no second capture.
"""

from __future__ import annotations

from dataclasses import dataclass

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")

from gi.repository import Gdk, Gio, GLib, Gtk, Pango, PangoCairo
from PIL import Image

from .. import APP_ID
from ..capture.base import Frame, Geometry, OutputInfo
from ..capture.edges import detect
from ..capture.screencopy import CaptureError, capture_output, list_outputs
from ..i18n import _
from ..selection import SelectionMode, SelectionState

ACCENT = (1.0, 0.231, 0.188, 1.0)
DIM_ALPHA = 0.45
HANDLE_SIZE = 5.0
MAGNIFIER_SOURCE = 96
MAGNIFIER_ZOOM = 6


@dataclass
class SelectionResult:
    action: str = "cancel"
    region: Geometry | None = None
    frame: Frame | None = None
    key: str = ""
    full: bool = False

    @property
    def confirmed(self) -> bool:
        return self.action == "confirm" and self.region is not None and not self.region.is_empty()


class OutputOverlay(Gtk.ApplicationWindow):
    def __init__(self, selector: RegionSelector, frame: Frame, monitor) -> None:
        super().__init__(application=selector.app)
        self.selector = selector
        self.frame = frame
        self.output = frame.output
        self.state = SelectionState(bounds=self.output.logical)
        # Borders come from the frozen frame: the sandbox hides the compositor
        # window list, but the pixels of every window are already here.
        self.state.edges = detect(frame)
        self.cursor: tuple[int, int] | None = None
        self.hint_timer = 0
        self.message = ""
        self._backdrop_cache = None
        self._backdrop_size = (0, 0)

        self.set_title("Dustshot selection")
        # A layer surface must stay resizable: turning that off makes GTK keep
        # its default 200x200 size instead of the compositor proposed one.
        self.area = self._build_area()
        self.set_child(self.area)

        from .layer import init_window

        init_window(self, monitor=monitor, layer="overlay", exclusive_zone=-1, keyboard="exclusive")

        key = Gtk.EventControllerKey()
        key.connect("key-pressed", self._on_key)
        self.add_controller(key)

        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._on_motion)
        motion.connect("leave", self._on_leave)
        self.add_controller(motion)

        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", self._on_drag_begin)
        drag.connect("drag-update", self._on_drag_update)
        drag.connect("drag-end", self._on_drag_end)
        self.add_controller(drag)

        click = Gtk.GestureClick()
        click.set_button(3)
        click.connect("pressed", self._on_right_click)
        self.add_controller(click)

        scroll = Gtk.EventControllerScroll()
        scroll.set_flags(Gtk.EventControllerScrollFlags.BOTH_AXES)
        scroll.connect("scroll", self._on_scroll)
        self.add_controller(scroll)

    # ------------------------------------------------------------------- widgets
    def _build_area(self) -> Gtk.Widget:
        area = Gtk.DrawingArea()
        area.set_draw_func(self._draw)
        area.set_hexpand(True)
        area.set_vexpand(True)
        cursor = Gdk.Cursor.new_from_name("crosshair", None)
        area.set_cursor(cursor)
        return area

    # --------------------------------------------------------------------- input
    def _on_motion(self, controller, x: float, y: float) -> None:
        self.state.snapping = _snapping_allowed(controller)
        self.cursor = (int(x), int(y))
        self.state.hover(x, y)
        self.area.queue_draw()

    def _on_leave(self, _controller) -> None:
        self.cursor = None
        self.state.hover_box = None
        self.area.queue_draw()

    def _on_drag_begin(self, gesture, x: float, y: float) -> None:
        self.state.snapping = _snapping_allowed(gesture)
        self.state.press(x, y)
        self.cursor = (int(x), int(y))
        self._notify()
        self.area.queue_draw()

    def _on_drag_update(self, gesture, offset_x: float, offset_y: float) -> None:
        self.state.snapping = _snapping_allowed(gesture)
        point = gesture.get_start_point()
        self.state.drag(point.x + offset_x, point.y + offset_y)
        self._notify()
        self.area.queue_draw()

    def _on_drag_end(self, gesture, offset_x: float, offset_y: float) -> None:
        if self.state.mode is SelectionMode.IDLE:
            return
        point = gesture.get_start_point()
        self.state.release(point.x + offset_x, point.y + offset_y)
        self._notify()
        self.area.queue_draw()

    def _on_right_click(self, _gesture, _n_press, _x: float, _y: float) -> None:
        self.selector.finish("cancel", key="right-click")

    def _on_scroll(self, controller, _dx: float, dy: float) -> bool:
        modifiers = controller.get_current_event_state()
        if modifiers & Gdk.ModifierType.CONTROL_MASK:
            delta = 10 if dy < 0 else -10
            self.state.resize_by(delta, delta)
        else:
            step = 1 if dy < 0 else -1
            self.state.nudge(0, -step)
        self._notify()
        self.area.queue_draw()
        return True

    def _on_key(self, _controller, keyval: int, _keycode: int, mods: Gdk.ModifierType) -> bool:
        control = bool(mods & Gdk.ModifierType.CONTROL_MASK)
        shift = bool(mods & Gdk.ModifierType.SHIFT_MASK)
        if keyval == Gdk.KEY_Escape:
            self.selector.finish("cancel", key="escape")
            return True
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            self._confirm("enter", full=False)
            return True
        if control and keyval in (Gdk.KEY_c, Gdk.KEY_s):
            self._confirm("ctrl-c" if keyval == Gdk.KEY_c else "ctrl-s", full=False)
            return True
        if control and keyval == Gdk.KEY_a:
            self.state.select_all()
            self._notify()
            self.area.queue_draw()
            return True
        if control and keyval == Gdk.KEY_r:
            self._confirm("ctrl-r", full=False)
            return True
        step = 10 if shift else 1
        moved = True
        if keyval == Gdk.KEY_Left:
            self.state.nudge(-step, 0)
        elif keyval == Gdk.KEY_Right:
            self.state.nudge(step, 0)
        elif keyval == Gdk.KEY_Up:
            self.state.nudge(0, -step)
        elif keyval == Gdk.KEY_Down:
            self.state.nudge(0, step)
        elif keyval == Gdk.KEY_BackSpace:
            self.state.clear()
        else:
            moved = False
        if moved:
            self._notify()
            self.area.queue_draw()
            return True
        if keyval in (Gdk.KEY_space,):
            self.state.select_all()
            self._notify()
            self.area.queue_draw()
            return True
        return False

    def _confirm(self, key: str, full: bool = False) -> None:
        if full:
            self.state.select_all()
        region = self.state.region
        if region is None or region.is_empty():
            if self.state.bounds.width and self.state.bounds.height:
                self.flash(_("先拖出一个区域，或按 Ctrl+A 全选"))
            return
        self.selector.finish("confirm", region=region, key=key)

    def flash(self, message: str) -> None:
        self.message = message
        self.area.queue_draw()
        if self.hint_timer:
            GLib.source_remove(self.hint_timer)
        self.hint_timer = GLib.timeout_add(1800, self._clear_message)

    def _clear_message(self) -> bool:
        self.hint_timer = 0
        self.message = ""
        self.area.queue_draw()
        return False

    # -------------------------------------------------------------------- drawing
    def _notify(self) -> None:
        self.selector.on_update(self.state)

    def _draw(self, _area, cr, width: int, height: int) -> None:
        self._draw_backdrop(cr, width, height)
        region = self.state.region_local()
        self._draw_dim(cr, width, height, region)
        if region is not None and not region.is_empty():
            self._draw_region(cr, region)
            self._draw_size_label(cr, region)
            self._draw_guides(cr, width, height, region)
        else:
            self._draw_preview(cr)
        self._draw_crosshair(cr, width, height)
        self._draw_magnifier(cr, width, height)
        self._draw_hints(cr, width, height)

    def _backdrop(self, width: int, height: int):
        if self._backdrop_cache is None or self._backdrop_size != (width, height):
            image = self.frame.image
            if (image.width, image.height) != (width, height):
                image = image.resize((max(1, width), max(1, height)), Image.LANCZOS)
            from .pixbuf import to_pixbuf

            self._backdrop_cache = to_pixbuf(image)
            self._backdrop_size = (width, height)
        return self._backdrop_cache

    def _draw_backdrop(self, cr, width: int, height: int) -> None:
        if self.frame is None:
            cr.set_source_rgb(0.05, 0.05, 0.07)
            cr.paint()
            return
        Gdk.cairo_set_source_pixbuf(cr, self._backdrop(width, height), 0, 0)
        cr.paint()

    def _draw_dim(self, cr, width: int, height: int, region: Geometry | None) -> None:
        cr.set_source_rgba(0.0, 0.0, 0.0, DIM_ALPHA)
        if region is None or region.is_empty():
            cr.rectangle(0, 0, width, height)
            cr.fill()
            return
        left, top = region.x, region.y
        right, bottom = region.x + region.width, region.y + region.height
        cr.rectangle(0, 0, width, top)
        cr.rectangle(0, bottom, width, height - bottom)
        cr.rectangle(0, top, left, region.height)
        cr.rectangle(right, top, width - right, region.height)
        cr.fill()

    def _draw_region(self, cr, region: Geometry) -> None:
        cr.set_source_rgba(*ACCENT)
        cr.set_line_width(1.5)
        cr.rectangle(region.x + 0.5, region.y + 0.5, region.width - 1, region.height - 1)
        cr.stroke()
        for _name, hx, hy in self.state.handles():
            self._draw_handle(cr, hx, hy)

    def _draw_handle(self, cr, x: float, y: float) -> None:
        cr.set_source_rgba(1.0, 1.0, 1.0, 1.0)
        cr.arc(x, y, HANDLE_SIZE, 0, 6.283185307179586)
        cr.fill()
        cr.set_source_rgba(*ACCENT)
        cr.set_line_width(1.5)
        cr.arc(x, y, HANDLE_SIZE, 0, 6.283185307179586)
        cr.stroke()

    def _draw_size_label(self, cr, region: Geometry) -> None:
        text = f"{region.width} x {region.height}"
        layout = _make_layout(cr, text, 12, bold=True)
        _ink, logical = layout.get_pixel_extents()
        pad = 6
        box_w = logical.width + pad * 2
        box_h = logical.height + pad * 2
        x = min(max(0, region.x + region.width / 2 - box_w / 2), max(0, self.state.bounds.width - box_w))
        y = region.y - box_h - 4 if region.y - box_h - 4 > 4 else region.y + 4
        cr.set_source_rgba(0.0, 0.0, 0.0, 0.72)
        self._rounded(cr, x, y, box_w, box_h, 6)
        cr.fill()
        cr.set_source_rgb(1.0, 1.0, 1.0)
        cr.move_to(x + pad, y + pad)
        PangoCairo.show_layout(cr, layout)

    def _draw_preview(self, cr) -> None:
        """Show the window or control a click would pick up."""

        box = self.state.hover_box
        if box is None:
            return
        local = self.state.region_local_of(box)
        if local is None or local.is_empty():
            return
        cr.set_source_rgba(*ACCENT)
        cr.set_line_width(1.5)
        cr.rectangle(local.x + 0.5, local.y + 0.5, local.width - 1, local.height - 1)
        cr.stroke()

    def _draw_guides(self, cr, width: int, height: int, region: Geometry) -> None:
        """Extend every snapped side as a line across the output."""

        if not self.state.snap_sides:
            return
        sides = {
            "left": region.x,
            "right": region.x + region.width,
            "top": region.y,
            "bottom": region.y + region.height,
        }
        cr.set_source_rgba(1.0, 0.231, 0.188, 0.6)
        cr.set_line_width(1.0)
        for side in self.state.snap_sides:
            value = sides.get(side)
            if value is None:
                continue
            if side in ("left", "right"):
                cr.move_to(value + 0.5, 0)
                cr.line_to(value + 0.5, height)
            else:
                cr.move_to(0, value + 0.5)
                cr.line_to(width, value + 0.5)
        cr.stroke()

    def _draw_crosshair(self, cr, width: int, height: int) -> None:
        if self.cursor is None:
            return
        x, y = self.cursor
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.45)
        cr.set_line_width(1.0)
        cr.move_to(0, y + 0.5)
        cr.line_to(width, y + 0.5)
        cr.move_to(x + 0.5, 0)
        cr.line_to(x + 0.5, height)
        cr.stroke()

    def _draw_magnifier(self, cr, width: int, height: int) -> None:
        if self.cursor is None or self.frame is None:
            return
        point = self.state.to_desktop(*self.cursor)
        half = MAGNIFIER_SOURCE // 2
        box = Geometry(point[0] - half, point[1] - half, MAGNIFIER_SOURCE, MAGNIFIER_SOURCE)
        physical = self.frame.logical_to_physical_box(box)
        if physical.is_empty():
            return
        image = self.frame.image.crop(physical.as_pil_box())
        if image.width <= 0 or image.height <= 0:
            return
        zoomed = image.resize((image.width * MAGNIFIER_ZOOM, image.height * MAGNIFIER_ZOOM), Image.NEAREST)
        from .pixbuf import to_pixbuf

        panel_w = zoomed.width
        panel_h = zoomed.height + 22
        x = self.cursor[0] + 28
        y = self.cursor[1] + 28
        if x + panel_w > width:
            x = self.cursor[0] - panel_w - 28
        if y + panel_h > height:
            y = self.cursor[1] - panel_h - 28
        x = max(4, x)
        y = max(4, y)
        cr.set_source_rgba(0.0, 0.0, 0.0, 0.8)
        self._rounded(cr, x - 2, y - 2, panel_w + 4, panel_h + 4, 6)
        cr.fill()
        Gdk.cairo_set_source_pixbuf(cr, to_pixbuf(zoomed), x, y)
        cr.paint()
        center_x = x + panel_w / 2
        center_y = y + zoomed.height / 2
        cr.set_source_rgba(*ACCENT)
        cr.set_line_width(1.0)
        half = MAGNIFIER_ZOOM / 2
        cr.rectangle(center_x - half, center_y - half, MAGNIFIER_ZOOM, MAGNIFIER_ZOOM)
        cr.stroke()
        sample_x = min(self.frame.image.width - 1, max(0, physical.x + physical.width // 2))
        sample_y = min(self.frame.image.height - 1, max(0, physical.y + physical.height // 2))
        color = self.frame.image.getpixel((sample_x, sample_y))[:3]
        text = f"#{color[0]:02x}{color[1]:02x}{color[2]:02x}   {point[0]}, {point[1]}"
        cr.set_source_rgb(1.0, 1.0, 1.0)
        cr.move_to(x + 4, y + zoomed.height + 4)
        PangoCairo.show_layout(cr, _make_layout(cr, text, 11))

    def _draw_hints(self, cr, width: int, height: int) -> None:
        hints = _(
            "拖动选择区域    回车 保存并复制    Ctrl+C 复制    空格/Ctrl+A 全选"
            "    Ctrl+R 录制    Alt 关闭吸附    Esc 取消"
        )
        layout = _make_layout(cr, hints, 12)
        _ink, logical = layout.get_pixel_extents()
        pad = 10
        box_w = logical.width + pad * 2
        box_h = logical.height + pad * 2
        x = (width - box_w) / 2
        y = height - box_h - 24
        cr.set_source_rgba(0.0, 0.0, 0.0, 0.75)
        self._rounded(cr, x, y, box_w, box_h, box_h / 2)
        cr.fill()
        cr.set_source_rgb(0.94, 0.94, 0.96)
        cr.move_to(x + pad, y + pad)
        PangoCairo.show_layout(cr, layout)
        if self.message:
            message_layout = _make_layout(cr, self.message, 13, bold=True)
            _ink, message_logical = message_layout.get_pixel_extents()
            message_w = message_logical.width + pad * 2
            mx = (width - message_w) / 2
            my = y - message_logical.height - pad * 2 - 12
            cr.set_source_rgba(0.75, 0.16, 0.12, 0.92)
            self._rounded(cr, mx, my, message_w, message_logical.height + pad * 2, 8)
            cr.fill()
            cr.set_source_rgb(1.0, 1.0, 1.0)
            cr.move_to(mx + pad, my + pad)
            PangoCairo.show_layout(cr, message_layout)

    @staticmethod
    def _rounded(cr, x: float, y: float, width: float, height: float, radius: float) -> None:
        import math

        radius = min(radius, width / 2, height / 2)
        cr.new_sub_path()
        cr.arc(x + width - radius, y + radius, radius, -math.pi / 2, 0)
        cr.arc(x + width - radius, y + height - radius, radius, 0, math.pi / 2)
        cr.arc(x + radius, y + height - radius, radius, math.pi / 2, math.pi)
        cr.arc(x + radius, y + radius, radius, math.pi, 1.5 * math.pi)
        cr.close_path()


def _snapping_allowed(controller) -> bool:
    """Alt temporarily releases the selection from the detected borders."""

    try:
        modifiers = controller.get_current_event_state()
    except Exception:  # no current event: keep snapping on
        return True
    return not (modifiers & Gdk.ModifierType.ALT_MASK)


def _make_layout(cr, text: str, size: int, bold: bool = False) -> Pango.Layout:
    """Build a layout bound to the draw context so metrics match what is drawn."""

    layout = PangoCairo.create_layout(cr)
    description = Pango.FontDescription()
    description.set_family("Noto Sans CJK SC")
    description.set_size(int(size * Pango.SCALE))
    if bold:
        description.set_weight(Pango.Weight.BOLD)
    layout.set_font_description(description)
    layout.set_text(text, -1)
    return layout


class RegionSelector:
    """Runs the overlay for every output and returns one selection."""

    def __init__(self, settings=None) -> None:
        self.settings = settings
        self.app = Gtk.Application(
            application_id=APP_ID + ".selector",
            flags=Gio.ApplicationFlags.NON_UNIQUE,
        )
        self.app.connect("activate", self._on_activate)
        self.overlays: list[OutputOverlay] = []
        self.frames: list[Frame] = []
        self.result = SelectionResult()

    # -------------------------------------------------------------------- run
    def pick(self, frames: list[Frame] | None = None) -> SelectionResult:
        self.frames = frames if frames is not None else self._capture_all()
        if not self.frames:
            raise CaptureError("no output available for selection")
        self.app.run([])
        return self.result

    def _capture_all(self) -> list[Frame]:
        frames: list[Frame] = []
        for info in list_outputs():
            try:
                frames.append(capture_output(info))
            except CaptureError:
                continue
        return frames

    def _on_activate(self, _app) -> None:
        display = Gdk.Display.get_default()
        monitors = display.get_monitors() if display is not None else None
        for frame in self.frames:
            monitor = _monitor_for(monitors, frame.output)
            overlay = OutputOverlay(self, frame, monitor)
            if self.settings is not None:
                last = getattr(self.settings.capture, "last_region", None)
                if last:
                    region = Geometry.from_tuple(tuple(last))
                    if region.intersects(frame.output.logical):
                        overlay.state.region = region.clamped(
                            frame.output.logical.width, frame.output.logical.height
                        ).translated(frame.output.logical.x, frame.output.logical.y)
            self.overlays.append(overlay)
            overlay.present()
            overlay.set_visible(True)
            overlay.grab_focus()
        self.app.hold()

    # ---------------------------------------------------------------- helpers
    def on_update(self, _state: SelectionState) -> None:
        for overlay in self.overlays:
            if overlay.state is not _state:
                overlay.queue_draw()

    def pointer_logical(self, output: OutputInfo) -> tuple[int, int] | None:
        try:
            from ..capture.screencopy import pointer_position

            position = pointer_position()
        except Exception:
            return None
        if position is None:
            return None
        if not output.logical.contains_point(position[0], position[1]):
            return None
        return position

    def finish(self, action: str, region: Geometry | None = None, key: str = "") -> None:
        self.result = SelectionResult(action=action, region=region, key=key)
        owner = None
        for candidate in self.overlays:
            if region is not None and candidate.state.region == region:
                owner = candidate
                break
        if owner is None and self.overlays:
            owner = self.overlays[0]
        if owner is not None:
            self.result.frame = owner.frame
            self.result.full = region is not None and region == owner.state.bounds
        overlays = list(self.overlays)
        self.overlays = []
        for overlay in overlays:
            overlay.state.cancel()
            overlay.destroy()
        if self.app.get_is_registered():
            self.app.release()
        self.app.quit()


def _monitor_for(monitors, output: OutputInfo):
    if monitors is None:
        return None
    for index in range(monitors.get_n_items()):
        monitor = monitors.get_item(index)
        geometry = monitor.get_geometry()
        if (geometry.x, geometry.y) == (output.logical.x, output.logical.y):
            return monitor
    return None


def select_region(settings=None, frames: list[Frame] | None = None) -> SelectionResult:
    return RegionSelector(settings=settings).pick(frames)
