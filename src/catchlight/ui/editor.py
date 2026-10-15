"""Annotation editor window for Catchlight."""

from __future__ import annotations

import threading
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, GLib, Gtk

from .. import clipboard, ocr, output
from ..annotation.document import Document
from ..config import DEFAULT_PALETTE
from ..history import History
from .canvas import TOOLS, Canvas
from .pin import PinWindow


def _header_button(label: str, tooltip: str, callback: Any) -> Gtk.Button:
    button = Gtk.Button(label=label)
    button.set_tooltip_text(tooltip)
    button.connect("clicked", lambda _b: callback())
    return button


class EditorWindow(Gtk.ApplicationWindow):
    """Toolbar plus canvas annotation window."""

    def __init__(self, app: Any, document: Document, settings: Any = None, on_done: Any = None) -> None:
        super().__init__(application=app)
        self.app = app
        self.settings = settings
        self.document = document
        self.on_done = on_done
        self.history = History()
        self._ocr_busy = False
        annotation = getattr(settings, "annotation", None)
        self.set_title("Catchlight 编辑器")
        self.set_default_size(1180, 780)

        self.canvas = Canvas(document, annotation, on_change=self._on_change, on_status=self._set_status)

        header = Gtk.HeaderBar()
        header.set_title_widget(Gtk.Label(label="Catchlight"))
        for label, tip, callback in (
            ("撤销", "撤销 (Ctrl+Z)", self.undo),
            ("重做", "重做 (Ctrl+Shift+Z)", self.redo),
            ("复制", "复制到剪贴板 (Ctrl+C)", self.copy),
            ("保存", "保存为文件 (Ctrl+S)", self.save),
            ("保存并复制", "保存、复制并关闭", self.finish),
            ("贴图", "把当前图像贴到屏幕 (Ctrl+P)", self.pin),
            ("OCR", "识别图中的文字", self.toggle_ocr),
            ("关闭", "关闭 (Ctrl+W)", self.close),
        ):
            header.pack_end(_header_button(label, tip, callback))
        self.set_titlebar(header)

        self.ocr_view = Gtk.TextView()
        self.ocr_view.set_editable(False)
        self.ocr_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        scroller = Gtk.ScrolledWindow()
        scroller.set_child(self.ocr_view)
        scroller.set_size_request(320, -1)
        self.ocr_panel = Gtk.Revealer()
        self.ocr_panel.set_child(scroller)
        self.ocr_panel.set_reveal_child(False)
        self.ocr_panel.set_transition_type(Gtk.RevealerTransitionType.SLIDE_LEFT)

        center = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        center.append(self.canvas)
        center.append(self.ocr_panel)
        center.set_vexpand(True)

        self.status = Gtk.Label(label="就绪")
        self.status.set_xalign(0.0)
        self.status.add_css_class("dim-label")
        self.status.set_margin_start(10)
        self.status.set_margin_end(10)
        self.status.set_margin_top(4)
        self.status.set_margin_bottom(6)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        root.append(self._build_toolbar(annotation))
        root.append(center)
        root.append(self.status)
        self.set_child(root)

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_key)
        self.add_controller(keys)
        self.connect("close-request", self._on_close_request)
        self._set_status(f"就绪  |  {TOOLS[0][1]}")
        self.canvas._emit_status()

    # ------------------------------------------------------------------ toolbar
    def _build_toolbar(self, annotation: Any) -> Gtk.Widget:
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        bar.add_css_class("toolbar")
        bar.set_margin_top(6)
        bar.set_margin_bottom(6)
        bar.set_margin_start(8)
        bar.set_margin_end(8)

        self.tool_buttons: dict[str, Gtk.ToggleButton] = {}
        first: Gtk.ToggleButton | None = None
        for key, label in TOOLS:
            button = Gtk.ToggleButton(label=label)
            button.set_tooltip_text(label)
            if first is None:
                first = button
                button.set_active(True)
            else:
                button.set_group(first)
            button.connect("toggled", self._on_tool_toggled, key)
            self.tool_buttons[key] = button
            bar.append(button)

        bar.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))

        palette = self._palette(annotation)
        bar.append(palette)

        bar.append(Gtk.Label(label="粗细"))
        self.width_spin = Gtk.SpinButton.new_with_range(1, 60, 1)
        self.width_spin.set_value(self.canvas.tool_width())
        self.width_spin.connect("value-changed", lambda spin: self.canvas.set_width(int(spin.get_value())))
        bar.append(self.width_spin)

        bar.append(Gtk.Label(label="字号"))
        self.size_spin = Gtk.SpinButton.new_with_range(8, 96, 1)
        self.size_spin.set_value(int(getattr(annotation, "text_size", 16) or 16))
        self.size_spin.connect(
            "value-changed",
            lambda spin: setattr(self.canvas, "text_size", int(spin.get_value())),
        )
        bar.append(self.size_spin)

        bar.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        bar.append(_header_button("清除", "删除全部标注", self.clear_items))
        bar.append(_header_button("删除所选", "删除选中的图元 (Delete)", self.canvas.delete_selected))
        return bar

    def _palette(self, annotation: Any) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        colors = list(getattr(annotation, "palette", None) or DEFAULT_PALETTE)
        current = str(getattr(annotation, "color", colors[0]) or colors[0])
        first: Gtk.ToggleButton | None = None
        self.color_buttons: list[tuple[str, Gtk.ToggleButton]] = []
        for color in colors:
            button = Gtk.ToggleButton()
            button.set_tooltip_text(color)
            button.set_size_request(24, 24)
            provider = Gtk.CssProvider()
            css = (
                f"button {{ background-image: none; background-color: {color};"
                " border: 1px solid rgba(0,0,0,0.45); border-radius: 4px;"
                " min-width: 22px; min-height: 22px; padding: 0; }"
                " button:checked { border: 2px solid #ffffff; }"
            )
            provider.load_from_data(css.encode("utf-8"))
            button.get_style_context().add_provider(provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            if first is None:
                first = button
            else:
                button.set_group(first)
            if color.lower() == current.lower():
                button.set_active(True)
            button.connect("toggled", self._on_color_toggled, color)
            self.color_buttons.append((color, button))
            box.append(button)
        return box

    # ------------------------------------------------------------------- status
    def _set_status(self, text: str) -> None:
        self.status.set_text(text)

    def _on_change(self) -> None:
        self.canvas.refresh()

    def _on_tool_toggled(self, button: Gtk.ToggleButton, key: str) -> None:
        if button.get_active():
            self.canvas.set_tool(key)
            spin = getattr(self, "width_spin", None)
            if spin is not None:
                value = self.canvas.tool_width(key)
                if int(spin.get_value()) != value:
                    spin.set_value(value)

    def _on_color_toggled(self, button: Gtk.ToggleButton, color: str) -> None:
        if button.get_active():
            self.canvas.set_color(color)
            if self.settings is not None and hasattr(self.settings, "annotation"):
                self.settings.annotation.color = color

    # ------------------------------------------------------------------ actions
    def undo(self) -> None:
        if self.document.undo():
            self.canvas.selected = None
            self.canvas.changed()
            self._set_status("已撤销")
        else:
            self._set_status("没有可撤销的操作")

    def redo(self) -> None:
        if self.document.redo():
            self.canvas.selected = None
            self.canvas.changed()
            self._set_status("已重做")
        else:
            self._set_status("没有可重做的操作")

    def clear_items(self) -> None:
        self.document.clear()
        self.canvas.selected = None
        self.canvas.changed()
        self._set_status("已清除全部标注")

    def copy(self) -> bool:
        image = self.document.render()
        ok = clipboard.copy_image(image)
        self._set_status("已复制到剪贴板" if ok else "复制失败，请检查 wl-clipboard")
        return ok

    def save(self) -> str | None:
        image = self.document.render()
        capture = getattr(self.settings, "capture", None)
        path = str(output.save_image(image, capture))
        try:
            self.history.record_image(path, image, kind="editor")
            self.history.save()
        except Exception:
            pass
        if capture is not None and getattr(capture, "copy_after_capture", True):
            clipboard.copy_image(image)
        self._set_status(f"已保存 {path}")
        return path

    def finish(self) -> None:
        self.save()
        self.copy()
        self.close()

    def pin(self) -> None:
        image = self.document.render()
        PinWindow(self.app, image, self.settings, position=(180, 180))
        self._set_status("已贴图，可拖动移动、滚轮缩放")

    def paste(self) -> None:
        image = clipboard.paste_image()
        if image is None:
            self._set_status("剪贴板里没有图片")
            return
        self.document = Document(image, getattr(self.settings, "annotation", None), source="clipboard")
        self.canvas.doc = self.document
        self.canvas.selected = None
        self.canvas._cache_sig = ()
        self.canvas.changed()
        self._set_status(f"已粘贴剪贴板图片 {image.size[0]} x {image.size[1]}")

    def toggle_ocr(self) -> None:
        if self.ocr_panel.get_reveal_child():
            self.ocr_panel.set_reveal_child(False)
            return
        self.ocr_panel.set_reveal_child(True)
        self.run_ocr()

    def run_ocr(self) -> None:
        if self._ocr_busy:
            return
        self._ocr_busy = True
        self._set_status("正在识别文字…")
        image = self.document.render()
        languages = getattr(getattr(self.settings, "ocr", None), "languages", "eng+chi_sim")
        language = str(languages or "eng+chi_sim")

        def work() -> None:
            try:
                result = ocr.recognize(image, languages=language)
                payload = result.text.strip() or "(没有识别到文字)"
            except Exception as exc:  # pragma: no cover - depends on tesseract
                payload = f"识别失败：{exc}"
            GLib.idle_add(self._apply_ocr, payload)

        threading.Thread(target=work, daemon=True).start()

    def _apply_ocr(self, text: str) -> bool:
        self._ocr_busy = False
        buffer = self.ocr_view.get_buffer()
        buffer.set_text(text)
        self._set_status(f"识别完成，共 {len(text)} 个字符")
        return False

    def _close_request(self) -> None:
        if self.on_done is not None:
            self.on_done(self)

    def _on_close_request(self, window: Gtk.Window) -> bool:
        self._close_request()
        return False

    # --------------------------------------------------------------------- keys
    def _on_key(self, controller: Gtk.EventControllerKey, keyval: int, code: int, state: Any) -> bool:
        ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
        shift = bool(state & Gdk.ModifierType.SHIFT_MASK)
        if ctrl and keyval in (Gdk.KEY_z, Gdk.KEY_Z):
            self.redo() if shift else self.undo()
            return True
        if ctrl and keyval in (Gdk.KEY_y, Gdk.KEY_Y):
            self.redo()
            return True
        if ctrl and keyval in (Gdk.KEY_s, Gdk.KEY_S):
            self.save()
            return True
        if ctrl and keyval in (Gdk.KEY_c, Gdk.KEY_C):
            self.copy()
            return True
        if ctrl and keyval in (Gdk.KEY_v, Gdk.KEY_V):
            self.paste()
            return True
        if ctrl and keyval in (Gdk.KEY_p, Gdk.KEY_P):
            self.pin()
            return True
        if ctrl and keyval in (Gdk.KEY_w, Gdk.KEY_W):
            self.close()
            return True
        if keyval in (Gdk.KEY_Delete, Gdk.KEY_BackSpace):
            self.canvas.delete_selected()
            return True
        if keyval == Gdk.KEY_Escape:
            self.canvas.deselect()
            return True
        if keyval in (Gdk.KEY_plus, Gdk.KEY_equal):
            self.canvas.set_width(self.canvas.style.width + 1)
            return True
        if keyval == Gdk.KEY_minus:
            self.canvas.set_width(self.canvas.style.width - 1)
            return True
        if not ctrl and keyval in range(Gdk.KEY_1, Gdk.KEY_9 + 1):
            index = keyval - Gdk.KEY_1
            if index < len(self.color_buttons):
                self.color_buttons[index][1].set_active(True)
                return True
        return False


def open_editor(app: Any, document: Document, settings: Any = None, on_done: Any = None) -> EditorWindow:
    window = EditorWindow(app, document, settings, on_done=on_done)
    window.present()
    return window
