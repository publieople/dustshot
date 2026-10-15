"""Browsable window over the capture history file."""

from __future__ import annotations

import contextlib
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk
from PIL import Image, ImageOps

from .. import clipboard
from ..history import History, HistoryEntry
from ..i18n import _
from .pixbuf import to_pixbuf

THUMBNAIL = (240, 160)
CARD_WIDTH = 272


def thumbnail(path: str) -> Any:
    """Return a GdkPixbuf with a small copy of the image, or None."""

    try:
        with Image.open(path) as image:
            image.load()
            thumb = ImageOps.contain(image.convert("RGB"), THUMBNAIL, Image.LANCZOS)
    except (OSError, ValueError):
        return None
    return to_pixbuf(thumb)


def human_bytes(count: int) -> str:
    value = float(max(0, int(count)))
    for unit in ("B", "KiB", "MiB", "GiB"):
        if value < 1024 or unit == "GiB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GiB"


def describe(entry: HistoryEntry) -> str:
    when = datetime.fromtimestamp(entry.created).strftime("%Y-%m-%d %H:%M")
    size = human_bytes(entry.bytes) if entry.bytes else "?"
    return f"{when} · {entry.width}×{entry.height} · {size}"


class HistoryWindow(Gtk.ApplicationWindow):
    """Grid of recent captures with edit, copy, pin and reveal actions."""

    def __init__(
        self,
        app: Any,
        settings: Any = None,
        history: History | None = None,
        limit: int = 60,
        on_close: Any = None,
    ) -> None:
        super().__init__(application=app)
        self.app = app
        self.settings = settings
        self.history = history or History()
        self.limit = int(limit)
        self.on_close = on_close
        self.set_title(_("Dustshot 历史"))
        self.set_default_size(900, 640)

        header = Gtk.HeaderBar()
        for label, tip, callback in (
            (_("刷新"), _("重新读取历史记录"), self.refresh),
            (_("清空"), _("删除全部历史记录"), self.clear),
            (_("关闭"), _("关闭窗口 (Esc)"), self.close),
        ):
            button = Gtk.Button(label=label)
            button.set_tooltip_text(tip)
            button.connect("clicked", lambda _b, cb=callback: cb())
            header.pack_end(button)
        self.set_titlebar(header)

        self.flow = Gtk.FlowBox()
        self.flow.set_valign(Gtk.Align.START)
        self.flow.set_selection_mode(Gtk.SelectionMode.NONE)
        self.flow.set_max_children_per_line(3)
        self.flow.set_column_spacing(12)
        self.flow.set_row_spacing(12)
        self.flow.set_margin_top(12)
        self.flow.set_margin_bottom(12)
        self.flow.set_margin_start(12)
        self.flow.set_margin_end(12)

        scroller = Gtk.ScrolledWindow()
        scroller.set_child(self.flow)
        empty = Gtk.Label(label=_("还没有截图记录"))
        empty.add_css_class("dim-label")
        self.stack = Gtk.Stack()
        self.stack.add_named(scroller, "grid")
        self.stack.add_named(empty, "empty")
        self.set_child(self.stack)

        self.connect("close-request", self._on_close_request)
        if app is not None:
            app.hold()
        self.refresh()

    # ------------------------------------------------------------------ build
    def _card(self, entry: HistoryEntry) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.add_css_class("card")
        box.set_size_request(CARD_WIDTH, -1)
        box.set_margin_top(4)
        box.set_margin_bottom(4)

        if entry.exists():
            pixbuf = thumbnail(entry.path)
            preview = (
                Gtk.Picture.new_for_pixbuf(pixbuf) if pixbuf is not None else Gtk.Label(label=_("无法预览"))
            )
        else:
            preview = Gtk.Label(label=_("文件已不存在"))
            preview.add_css_class("dim-label")
        preview.set_size_request(THUMBNAIL[0], THUMBNAIL[1])
        box.append(preview)

        name = Gtk.Label(label=Path(entry.path).name)
        name.set_ellipsize(3)
        name.set_xalign(0.0)
        box.append(name)

        meta = Gtk.Label(label=describe(entry))
        meta.add_css_class("dim-label")
        meta.set_xalign(0.0)
        box.append(meta)

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        for label, tip, callback in (
            (_("编辑"), _("在编辑器里打开"), lambda: self._edit(entry)),
            (_("复制"), _("复制到剪贴板"), lambda: self._copy(entry)),
            (_("贴图"), _("钉在屏幕上"), lambda: self._pin(entry)),
            (_("目录"), _("在文件管理器里显示"), lambda: self._reveal(entry)),
            (_("删除"), _("从历史记录里移除"), lambda: self._remove(entry)),
        ):
            button = Gtk.Button(label=label)
            button.set_tooltip_text(tip)
            button.connect("clicked", lambda _b, cb=callback: cb())
            actions.append(button)
        box.append(actions)
        return box

    # ---------------------------------------------------------------- actions
    def refresh(self) -> None:
        self.history.load()
        while (child := self.flow.get_first_child()) is not None:
            self.flow.remove(child)
        entries = list(self.history.recent(limit=self.limit))
        for entry in entries:
            self.flow.append(self._card(entry))
        self.stack.set_visible_child_name("grid" if entries else "empty")

    def clear(self) -> None:
        self.history.entries = []
        self.history.save()
        self.refresh()

    def _image(self, entry: HistoryEntry) -> Any:
        image = Image.open(entry.path)
        image.load()
        return image.convert("RGB")

    def _edit(self, entry: HistoryEntry) -> None:
        opener = getattr(self.app, "open_editor_path", None)
        if opener is None or not entry.exists():
            return
        opener(entry.path)

    def _copy(self, entry: HistoryEntry) -> None:
        if entry.exists():
            clipboard.copy_image(self._image(entry))

    def _pin(self, entry: HistoryEntry) -> None:
        spawner = getattr(self.app, "spawn_pin", None)
        if spawner is not None and entry.exists():
            spawner(self._image(entry), position=(160, 160))

    def _reveal(self, entry: HistoryEntry) -> None:
        target = Path(entry.path)
        folder = target.parent if target.parent.exists() else Path.home()
        with contextlib.suppress(OSError):
            subprocess.Popen(["xdg-open", str(folder)])

    def _remove(self, entry: HistoryEntry) -> None:
        self.history.entries = [item for item in self.history.entries if item.path != entry.path]
        self.history.save()
        self.refresh()

    def _on_close_request(self, window: Gtk.Window) -> bool:
        if self.app is not None:
            self.app.release()
        if self.on_close is not None:
            self.on_close(self)
        return False
