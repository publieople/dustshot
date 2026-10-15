"""Annotation canvas widget (GTK4 + Cairo) used by the Dustshot editor."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GdkPixbuf, Gtk
from PIL import Image

from ..annotation.document import Document
from ..annotation.items import (
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
)
from ..capture.base import Geometry
from ..i18n import _
from .pixbuf import to_pixbuf

ACCENT = (0.98, 0.30, 0.24)
GRID_BG = (0.10, 0.11, 0.13)

#: tool key -> (label, hint)
TOOLS: tuple[tuple[str, str], ...] = (
    ("select", _("选择")),
    ("rect", _("矩形")),
    ("ellipse", _("椭圆")),
    ("line", _("直线")),
    ("arrow", _("箭头")),
    ("pencil", _("画笔")),
    ("highlighter", _("荧光笔")),
    ("text", _("文字")),
    ("serial", _("序号")),
    ("mosaic", _("马赛克")),
    ("blur", _("模糊")),
    ("crop", _("裁剪")),
)

BOX_TOOLS = ("rect", "ellipse", "mosaic", "blur")
STROKE_TOOLS = ("pencil", "highlighter")
HANDLE_RADIUS = 10
MIN_DRAG = 3
MAX_DISPLAY = 1600

TOOL_HINTS = {
    "select": _("拖动图元移动，拖手柄缩放；Delete 删除"),
    "rect": _("拖动绘制矩形"),
    "ellipse": _("拖动绘制椭圆"),
    "line": _("拖动绘制直线"),
    "arrow": _("拖动绘制箭头"),
    "pencil": _("按住拖动自由绘制"),
    "highlighter": _("按住拖动绘制荧光笔"),
    "text": _("单击后输入文字，回车确认"),
    "serial": _("单击添加递增序号"),
    "mosaic": _("拖动框选马赛克区域"),
    "blur": _("拖动框选模糊区域"),
    "crop": _("拖动框选要保留的区域，回车应用"),
}


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


class Canvas(Gtk.DrawingArea):
    """Displays the document and turns pointer input into annotation items."""

    def __init__(
        self,
        document: Document,
        annotation_settings: Any = None,
        on_change: Any = None,
        on_status: Any = None,
    ) -> None:
        super().__init__()
        self.doc = document
        self.annotation = annotation_settings
        self.on_change = on_change
        self.on_status = on_status

        self.tool = "select"
        self.style = Style()
        self.widths = {
            "shape": int(getattr(annotation_settings, "shape_width", 3) or 3),
            "pencil": int(getattr(annotation_settings, "pencil_width", 3) or 3),
            "highlighter": int(getattr(annotation_settings, "highlighter_width", 14) or 14),
        }
        if annotation_settings is not None:
            self.style.color = str(getattr(annotation_settings, "color", "#ff3b30") or "#ff3b30")
            self.style.fill = bool(getattr(annotation_settings, "fill_shapes", False))
        self.style.width = self.widths["shape"]
        self.text_size = int(getattr(annotation_settings, "text_size", 16) or 16)
        self.serial_size = int(getattr(annotation_settings, "serial_size", 20) or 20)
        self.serial_start = int(getattr(annotation_settings, "serial_start", 1) or 1)
        self.mosaic_block = int(getattr(annotation_settings, "mosaic_block", 12) or 12)
        self.blur_radius = int(getattr(annotation_settings, "blur_radius", 12) or 12)

        self.scale = 1.0
        self.offset = (0.0, 0.0)
        self.selected: Item | None = None
        self.crop_rect: Geometry | None = None
        self._drag_mode = ""
        self._drag_handle = ""
        self._drag_origin = (0.0, 0.0)
        self._drag_start_bbox: Geometry | None = None
        self._drag_start_item: dict[str, Any] | None = None
        self._preview: Item | None = None
        self._preview_sig = ""
        self._cache_sig: tuple[Any, ...] = ()
        self._cache_image: Image.Image | None = None
        self._cache_pixbuf: GdkPixbuf.Pixbuf | None = None

        self.set_focusable(True)
        self.set_draw_func(self._draw)
        self.set_hexpand(True)
        self.set_vexpand(True)

        drag = Gtk.GestureDrag()
        drag.set_button(1)
        drag.connect("drag-begin", self._on_drag_begin)
        drag.connect("drag-update", self._on_drag_update)
        drag.connect("drag-end", self._on_drag_end)
        self.add_controller(drag)

        click = Gtk.GestureClick()
        click.set_button(3)
        click.connect("pressed", self._on_right_click)
        self.add_controller(click)

        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._on_motion)
        motion.connect("leave", self._on_leave)
        self.add_controller(motion)

    # ------------------------------------------------------------------ helpers
    @property
    def image_size(self) -> tuple[int, int]:
        return self.doc.size

    def _compute_layout(self, width: int, height: int) -> None:
        iw, ih = self.image_size
        if iw <= 0 or ih <= 0:
            self.scale = 1.0
            self.offset = (0.0, 0.0)
            return
        scale = min(width / iw, height / ih)
        if scale > 1.0:
            scale = 1.0 if iw <= MAX_DISPLAY else width / iw
        scale = _clamp(scale, 0.05, 4.0)
        self.scale = scale
        self.offset = ((width - iw * scale) / 2.0, (height - ih * scale) / 2.0)

    def to_widget(self, x: float, y: float) -> tuple[float, float]:
        return (self.offset[0] + x * self.scale, self.offset[1] + y * self.scale)

    def to_image(self, x: float, y: float) -> tuple[float, float]:
        return ((x - self.offset[0]) / self.scale, (y - self.offset[1]) / self.scale)

    def refresh(self) -> None:
        self.queue_draw()

    def set_tool(self, tool: str) -> None:
        self.tool = tool
        if tool != "crop":
            self.crop_rect = None
        if tool != "select":
            self.deselect()
        self._emit_status()

    def set_color(self, color: str) -> None:
        self.style.color = color
        if self.selected is not None:
            self.selected.style.color = color
            self.doc.touch()
            self.changed()
        self.refresh()

    def _family(self, tool: str | None = None) -> str:
        tool = tool or self.tool
        if tool == "pencil":
            return "pencil"
        if tool == "highlighter":
            return "highlighter"
        return "shape"

    def tool_width(self, tool: str | None = None) -> int:
        return max(1, int(self.widths.get(self._family(tool), 3)))

    def set_width(self, width: int) -> None:
        value = max(1, int(width))
        self.widths[self._family()] = value
        self.style.width = self.tool_width("rect")
        if self.selected is not None:
            self.selected.style.width = value
            self.doc.touch()
            self.changed()
        self.refresh()

    def select(self, item: Item | None) -> None:
        self.selected = item
        self.refresh()
        self._emit_status()

    def deselect(self) -> None:
        if self.selected is not None:
            self.selected = None
            self.refresh()
            self._emit_status()

    def delete_selected(self) -> bool:
        if self.selected is None:
            return False
        ok = self.doc.remove(self.selected.id)
        self.selected = None
        self.changed()
        return ok

    def changed(self) -> None:
        self.refresh()
        if self.on_change is not None:
            self.on_change()

    def _emit_status(self) -> None:
        if self.on_status is None:
            return
        iw, ih = self.image_size
        hint = TOOL_HINTS.get(self.tool, "")
        self.on_status(f"{iw} x {ih}  |  {self.tool}  |  {hint}")

    # ------------------------------------------------------------ item building
    def _style_for(self, tool: str) -> Style:
        style = Style(
            color=self.style.color,
            width=self.tool_width(tool),
            fill=bool(self.style.fill),
            opacity=0.35 if tool == "highlighter" else 1.0,
        )
        if tool == "mosaic":
            style.width = 0
        return style

    def _new_item(self, tool: str, x: float, y: float) -> Item | None:
        style = self._style_for(tool)
        x, y = round(x), round(y)
        if tool == "rect":
            return RectItem(style=style, x=x, y=y, width=0, height=0, radius=0)
        if tool == "ellipse":
            return EllipseItem(style=style, x=x, y=y, width=0, height=0)
        if tool == "line":
            return LineItem(style=style, x1=x, y1=y, x2=x, y2=y)
        if tool == "arrow":
            return ArrowItem(style=style, x1=x, y1=y, x2=x, y2=y)
        if tool == "pencil":
            return PencilItem(style=style, points=[(x, y)])
        if tool == "highlighter":
            return HighlighterItem(style=style, points=[(x, y)])
        if tool == "mosaic":
            return MosaicItem(style=style, x=x, y=y, width=0, height=0, block=self.mosaic_block)
        if tool == "blur":
            return MosaicItem(
                style=style,
                x=x,
                y=y,
                width=0,
                height=0,
                mode="blur",
                blur_radius=self.blur_radius,
            )
        return None

    def _update_drag_geometry(self, item: Item, x0: float, y0: float, x1: float, y1: float) -> None:
        left, right = sorted((x0, x1))
        top, bottom = sorted((y0, y1))
        if isinstance(item, LineItem):
            item.x2, item.y2 = round(x1), round(y1)
            return
        if isinstance(item, (PencilItem, HighlighterItem)):
            item.append(float(x1), float(y1), 1.5)
            return
        if isinstance(item, MosaicItem):
            item.x = round(left)
            item.y = round(top)
            item.width = round(right - left)
            item.height = round(bottom - top)
            return
        if hasattr(item, "width") and hasattr(item, "x"):
            item.x = round(left)
            item.y = round(top)
            item.width = round(right - left)
            item.height = round(bottom - top)

    # ------------------------------------------------------------------ gestures
    def _on_drag_begin(self, gesture: Gtk.GestureDrag, sx: float, sy: float) -> None:
        self.grab_focus()
        ix, iy = self.to_image(sx, sy)
        self._drag_origin = (ix, iy)
        if self.tool == "text":
            self._drag_mode = ""
            self._prompt_text(ix, iy)
            return
        if self.tool == "serial":
            self._drag_mode = ""
            self._add_serial(ix, iy)
            return
        if self.tool in BOX_TOOLS or self.tool in STROKE_TOOLS or self.tool in ("line", "arrow"):
            self._preview = self._new_item(self.tool, ix, iy)
            self._drag_mode = "create"
            self.clamp_preview()
            self.refresh()
            return
        if self.tool == "crop":
            self.crop_rect = None
            self._drag_mode = "crop"
            self.refresh()
            return
        if self.tool == "select":
            self._begin_select_drag(ix, iy)
            return

    def _on_drag_update(self, gesture: Gtk.GestureDrag, dx: float, dy: float) -> None:
        if gesture.get_current_button() != 1 and self._drag_mode == "":
            return
        _ok, sx, sy = gesture.get_start_point()
        cx, cy = gesture.get_offset()
        ix0, iy0 = self.to_image(sx, sy)
        ix1, iy1 = self.to_image(sx + cx, sy + cy)
        if self._drag_mode == "crop":
            iw, ih = self.image_size
            left, right = sorted((_clamp(ix0, 0.0, float(iw)), _clamp(ix1, 0.0, float(iw))))
            top, bottom = sorted((_clamp(iy0, 0.0, float(ih)), _clamp(iy1, 0.0, float(ih))))
            self.crop_rect = Geometry(round(left), round(top), round(right - left), round(bottom - top))
            self.refresh()
            return
        if self._drag_mode == "create" and self._preview is not None:
            self._update_drag_geometry(self._preview, ix0, iy0, ix1, iy1)
            self.clamp_preview()
            self.refresh()
            return
        if self._drag_mode in ("move", "resize") and self.selected is not None:
            self._update_select_drag(ix1, iy1)
            return

    def _on_drag_end(self, gesture: Gtk.GestureDrag, dx: float, dy: float) -> None:
        if self._drag_mode == "crop":
            self._drag_mode = ""
            rect = self.crop_rect
            if rect is not None and (rect.width < MIN_DRAG or rect.height < MIN_DRAG):
                self.crop_rect = None
            self.refresh()
            self._emit_status()
            return
        if self._drag_mode == "create" and self._preview is not None:
            item = self._preview
            self._preview = None
            if self._item_visible(item):
                self.doc.add(item)
                self.selected = item
                self.changed()
            else:
                self.refresh()
            self._drag_mode = ""
            self._emit_status()
            return
        if self._drag_mode in ("move", "resize") and self.selected is not None:
            self.doc.touch()
            self._drag_mode = ""
            self._drag_start_item = None
            self._drag_start_bbox = None
            self.changed()
            return
        self._drag_mode = ""

    # ----------------------------------------------------------------- cropping
    def apply_crop(self) -> bool:
        """Trim the document to the dragged rectangle, if there is one."""
        rect = self.crop_rect
        self.crop_rect = None
        ok = rect is not None and self.doc.crop(rect)
        if ok:
            self.selected = None
            self._preview = None
            self.changed()
        else:
            self.refresh()
        self._emit_status()
        return ok

    def cancel_crop(self) -> bool:
        if self.crop_rect is None:
            return False
        self.crop_rect = None
        self.refresh()
        return True

    def _item_visible(self, item: Item) -> bool:
        if isinstance(item, (PencilItem, HighlighterItem)):
            return len(item.points) > 1
        if isinstance(item, LineItem):
            return abs(item.x2 - item.x1) > MIN_DRAG or abs(item.y2 - item.y1) > MIN_DRAG
        if isinstance(item, MosaicItem):
            return item.width >= MIN_DRAG and item.height >= MIN_DRAG
        if hasattr(item, "width"):
            return item.width >= MIN_DRAG and item.height >= MIN_DRAG
        return True

    def clamp_preview(self) -> None:
        item = self._preview
        if item is None:
            return
        iw, ih = self.image_size
        if isinstance(item, LineItem):
            item.x1 = int(_clamp(item.x1, 0, iw))
            item.y1 = int(_clamp(item.y1, 0, ih))
            item.x2 = int(_clamp(item.x2, 0, iw))
            item.y2 = int(_clamp(item.y2, 0, ih))
            return
        if isinstance(item, (PencilItem, HighlighterItem)):
            item.points = [(int(_clamp(px, 0, iw)), int(_clamp(py, 0, ih))) for px, py in item.points]
            return
        if hasattr(item, "width"):
            item.x = int(_clamp(item.x, 0, iw))
            item.y = int(_clamp(item.y, 0, ih))
            item.width = int(_clamp(item.width, 0, iw - item.x))
            item.height = int(_clamp(item.height, 0, ih - item.y))

    # ------------------------------------------------------------- select drag
    def _begin_select_drag(self, ix: float, iy: float) -> None:
        wx, wy = self.to_widget(ix, iy)
        if self.selected is not None:
            handle = self._handle_at(wx, wy, self.selected)
            if handle:
                self.doc.push_undo()
                self._drag_mode = "resize"
                self._drag_handle = handle
                self._drag_start_bbox = self.selected.bbox()
                self._drag_start_item = dict(self.selected.to_dict())
                return
        item = self.doc.hit_test(ix, iy)
        if item is not None:
            self.selected = item
            self.doc.push_undo()
            self._drag_mode = "move"
            self._drag_start_item = dict(item.to_dict())
            self.refresh()
            self._emit_status()
            return
        self.selected = None
        self._drag_mode = ""
        self.refresh()
        self._emit_status()

    def _handle_points(self, item: Item) -> dict[str, tuple[float, float]]:
        box = item.bbox()
        left, top = self.to_widget(box.x, box.y)
        right, bottom = self.to_widget(box.right, box.bottom)
        cx = (left + right) / 2.0
        cy = (top + bottom) / 2.0
        return {
            "nw": (left, top),
            "n": (cx, top),
            "ne": (right, top),
            "e": (right, cy),
            "se": (right, bottom),
            "s": (cx, bottom),
            "sw": (left, bottom),
            "w": (left, cy),
        }

    def _handle_at(self, wx: float, wy: float, item: Item) -> str:
        for name, (hx, hy) in self._handle_points(item).items():
            if abs(wx - hx) <= HANDLE_RADIUS and abs(wy - hy) <= HANDLE_RADIUS:
                return name
        return ""

    def _update_select_drag(self, ix: float, iy: float) -> None:
        item = self.selected
        if item is None or self._drag_start_item is None:
            return
        if self._drag_mode == "move":
            ox, oy = self._drag_origin
            start = self._drag_start_item
            dx = round(ix - ox)
            dy = round(iy - oy)
            for key in ("x", "x1"):
                if key in start:
                    setattr(item, key, int(start[key]) + dx)
            for key in ("y", "y1"):
                if key in start:
                    setattr(item, key, int(start[key]) + dy)
            if "x2" in start:
                item.x2 = int(start["x2"]) + dx
            if "y2" in start:
                item.y2 = int(start["y2"]) + dy
            if "points" in start:
                item.points = [(int(px) + dx, int(py) + dy) for px, py in start["points"]]
            self.refresh()
            return
        box = self._drag_start_bbox
        if box is None:
            return
        left, top, right, bottom = box.x, box.y, box.right, box.bottom
        handle = self._drag_handle
        if "w" in handle:
            left = round(ix)
        if "e" in handle:
            right = round(ix)
        if "n" in handle:
            top = round(iy)
        if "s" in handle:
            bottom = round(iy)
        if left > right:
            left, right = right, left
        if top > bottom:
            top, bottom = bottom, top
        new_box = Geometry(left, top, max(1, right - left), max(1, bottom - top))
        self._apply_resize(item, self._drag_start_item, box, new_box)
        self.refresh()

    def _apply_resize(
        self,
        item: Item,
        start: dict[str, Any],
        old: Geometry,
        new: Geometry,
    ) -> None:
        if old.width <= 0 or old.height <= 0:
            return
        if isinstance(item, (PencilItem, HighlighterItem)):
            fx = new.width / float(old.width)
            fy = new.height / float(old.height)
            points = [(int(px), int(py)) for px, py in start.get("points", [])]
            item.points = [
                (round(new.x + (px - old.x) * fx), round(new.y + (py - old.y) * fy)) for px, py in points
            ]
            return
        if isinstance(item, LineItem):
            item.x1 = round(new.x + (start.get("x1", old.x) - old.x) * new.width / float(old.width))
            item.y1 = round(new.y + (start.get("y1", old.y) - old.y) * new.height / float(old.height))
            item.x2 = round(new.x + (start.get("x2", old.right) - old.x) * new.width / float(old.width))
            item.y2 = round(new.y + (start.get("y2", old.bottom) - old.y) * new.height / float(old.height))
            return
        if isinstance(item, (TextItem, SerialItem)):
            item.x = round(new.x)
            item.y = round(new.y)
            return
        if hasattr(item, "width"):
            item.x = int(new.x)
            item.y = int(new.y)
            item.width = int(new.width)
            item.height = int(new.height)

    # --------------------------------------------------------------- text input
    def _prompt_text(self, ix: float, iy: float) -> None:
        wx, wy = self.to_widget(ix, iy)
        popover = Gtk.Popover()
        popover.set_parent(self)
        entry = Gtk.Entry()
        entry.set_placeholder_text(_("输入文字后回车"))
        entry.set_width_chars(24)
        popover.set_child(entry)
        rect = Gdk.Rectangle()
        rect.x, rect.y, rect.width, rect.height = int(wx), int(wy), 1, 1
        popover.set_pointing_to(rect)
        popover.popup()
        entry.grab_focus()

        def commit(_entry: Gtk.Entry) -> None:
            text = entry.get_text()
            popover.popdown()
            popover.unparent()
            if text.strip():
                item = TextItem(
                    style=self._style_for("text"),
                    x=round(ix),
                    y=round(iy),
                    text=text,
                    size=self.text_size,
                )
                self.doc.add(item)
                self.selected = item
                self.changed()

        def cancel(_entry: Gtk.Entry, keyval: int, _code: int, _state: Any) -> bool:
            if keyval == Gdk.KEY_Escape:
                popover.popdown()
                popover.unparent()
                return True
            return False

        entry.connect("activate", commit)
        entry.connect("key-pressed", cancel)

    def _add_serial(self, ix: float, iy: float) -> None:
        item = self.doc.add_serial(ix, iy, self.serial_size)
        self.selected = item
        self.changed()

    # ------------------------------------------------------------------ drawing
    def _render_image(self, width: int, height: int) -> Image.Image:
        items: Sequence[Item] = list(self.doc.items)
        if self._preview is not None:
            items = [*list(items), self._preview]
        sig = (self.doc.revision, self.scale, len(items), self._preview_signature())
        if self._cache_image is not None and self._cache_sig == sig:
            return self._cache_image
        if self._preview is not None:
            from ..annotation.render import render

            image = render(self.doc.base, items)
        else:
            image = self.doc.render()
        if self.scale != 1.0:
            target = (
                max(1, round(image.width * self.scale)),
                max(1, round(image.height * self.scale)),
            )
            image = image.resize(target, Image.LANCZOS)
        self._cache_image = image
        self._cache_sig = sig
        self._cache_pixbuf = to_pixbuf(image)
        return image

    def _preview_signature(self) -> str:
        if self._preview is None:
            return ""
        try:
            return json.dumps(self._preview.to_dict(), sort_keys=True)
        except (TypeError, ValueError):
            return str(id(self._preview))

    def _draw(self, area: Gtk.DrawingArea, cr: Any, width: int, height: int) -> None:
        self._compute_layout(width, height)
        cr.set_source_rgb(*GRID_BG)
        cr.paint()
        if self.image_size[0] <= 0:
            return
        image = self._render_image(width, height)
        pixbuf = self._cache_pixbuf
        if pixbuf is None:
            pixbuf = to_pixbuf(image)
            self._cache_pixbuf = pixbuf
        cr.save()
        cr.translate(self.offset[0], self.offset[1])
        Gdk.cairo_set_source_pixbuf(cr, pixbuf, 0, 0)
        cr.paint()
        cr.restore()

        ox, oy = self.offset
        iw, ih = self.image_size
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.25)
        cr.set_line_width(1.0)
        cr.rectangle(ox - 0.5, oy - 0.5, iw * self.scale + 1, ih * self.scale + 1)
        cr.stroke()

        if self.selected is not None:
            self._draw_selection(cr, self.selected)
        if self.crop_rect is not None:
            self._draw_crop(cr)

    def _draw_crop(self, cr: Any) -> None:
        rect = self.crop_rect
        if rect is None or rect.is_empty():
            return
        left, top = self.to_widget(rect.x, rect.y)
        right, bottom = self.to_widget(rect.right, rect.bottom)
        ox, oy = self.offset
        ir, ib = self.to_widget(*self.image_size)
        cr.save()
        cr.set_source_rgba(0.0, 0.0, 0.0, 0.45)
        for band in (
            (ox, oy, ir - ox, top - oy),
            (ox, bottom, ir - ox, ib - bottom),
            (ox, top, left - ox, bottom - top),
            (right, top, ir - right, bottom - top),
        ):
            cr.rectangle(*band)
        cr.fill()
        cr.set_source_rgba(*ACCENT, 1.0)
        cr.set_line_width(1.5)
        cr.rectangle(left, top, right - left, bottom - top)
        cr.stroke()
        cr.restore()

    def _draw_selection(self, cr: Any, item: Item) -> None:
        for _name, (hx, hy) in self._handle_points(item).items():
            size = 7.0
            cr.set_source_rgba(1.0, 1.0, 1.0, 0.95)
            cr.rectangle(hx - size / 2 + 0.5, hy - size / 2 + 0.5, size - 1, size - 1)
            cr.fill_preserve()
            cr.set_source_rgba(*ACCENT, 1.0)
            cr.set_line_width(1.4)
            cr.stroke()

    # ------------------------------------------------------------------ events
    def _on_right_click(self, gesture: Gtk.GestureClick, n_press: int, x: float, y: float) -> None:
        self._preview = None
        self.deselect()
        self.refresh()

    def _on_motion(self, controller: Gtk.EventControllerMotion, x: float, y: float) -> None:
        ix, iy = self.to_image(x, y)
        if self.on_status is not None and self.tool == "select":
            iw, ih = self.image_size
            self.on_status(f"{iw} x {ih}  |  {int(ix)}, {int(iy)}")

    def _on_leave(self, controller: Gtk.EventControllerMotion) -> None:
        self._emit_status()
