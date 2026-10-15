"""Gtk.Application used by every graphical Catchlight entry point."""

from __future__ import annotations

import signal
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gio, GLib, Gtk
from PIL import Image

from .. import clipboard, output
from ..annotation.document import Document
from ..config import Settings
from ..history import History
from ..record import Recorder, RecordError
from .editor import EditorWindow
from .history_window import HistoryWindow
from .pin import PinWindow


def stitch(images: Iterable[Image.Image]) -> Image.Image:
    """Join several output grabs into a single image."""

    frames = [image.convert("RGB") for image in images]
    if not frames:
        raise ValueError("no images to stitch")
    if len(frames) == 1:
        return frames[0]
    width = sum(frame.width for frame in frames)
    height = max(frame.height for frame in frames)
    canvas = Image.new("RGB", (width, height), (0, 0, 0))
    x = 0
    for frame in frames:
        canvas.paste(frame, (x, 0))
        x += frame.width
    return canvas


def load_image(path: str | Path) -> Image.Image:
    image = Image.open(str(path))
    image.load()
    return image.convert("RGB")


class RecordControlWindow(Gtk.ApplicationWindow):
    """Small always-available window that stops the recording."""

    def __init__(self, app: CatchlightApp, recorder: Recorder, options: dict[str, Any]) -> None:
        super().__init__(application=app)
        self.app = app
        self.recorder = recorder
        self.options = options
        self.started = time.time()
        self.set_title("Catchlight 录制")
        self.set_default_size(320, 120)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_margin_top(16)
        box.set_margin_bottom(16)
        box.set_margin_start(16)
        box.set_margin_end(16)
        self.label = Gtk.Label(label="正在录制 00:00")
        self.label.add_css_class("title-3")
        box.append(self.label)
        hint = Gtk.Label(label=f"{recorder.backend} -> {recorder.output}")
        hint.add_css_class("dim-label")
        hint.set_ellipsize(3)
        box.append(hint)
        stop = Gtk.Button(label="停止录制")
        stop.add_css_class("suggested-action")
        stop.connect("clicked", lambda _b: self.finish())
        box.append(stop)
        self.set_child(box)

        GLib.timeout_add(500, self._tick)
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, self._on_signal)
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, self._on_signal)
        duration = self.options.get("duration")
        if duration:
            GLib.timeout_add(int(float(duration) * 1000), self._on_signal)

    def _tick(self) -> bool:
        elapsed = time.time() - self.started
        minutes, seconds = int(elapsed // 60), int(elapsed % 60)
        self.label.set_text(f"正在录制 {minutes:02d}:{seconds:02d}")
        return True

    def _on_signal(self, *args: Any) -> bool:
        self.finish()
        return False

    def finish(self) -> None:
        try:
            result = self.recorder.stop()
            self.app.recording_result = result
        except RecordError as exc:
            self.app.recording_error = str(exc)
        self.close()


class CatchlightApp(Gtk.Application):
    """Owns the windows for one CLI invocation."""

    def __init__(
        self,
        settings: Settings,
        action: str = "editor",
        images: Iterable[Image.Image] | None = None,
        options: dict[str, Any] | None = None,
        region: Any = None,
    ) -> None:
        super().__init__(application_id="io.github.catchlight.gui", flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.settings = settings
        self.action = action
        self.images = list(images or [])
        self.options = dict(options or {})
        self.region = region
        self.history = History()
        self.editors: list[EditorWindow] = []
        self.pins: list[PinWindow] = []
        self.extra: list[Any] = []
        self.recording_result: Any = None
        self.recording_error: str | None = None
        self._started = False
        self._recorder: Recorder | None = None

    # ------------------------------------------------------------------ entry
    def do_activate(self) -> None:
        if self._started:
            return
        self._started = True
        getattr(self, "_run_" + self.action, self._run_editor)()

    # ----------------------------------------------------------------- actions
    def _save(self, image: Image.Image, kind: str = "capture", note: str = "") -> str:
        path = str(output.save_image(image, self.settings.capture))
        try:
            self.history.record_image(path, image, kind=kind, note=note)
            self.history.save()
        except Exception:
            pass
        if self.settings.capture.copy_after_capture:
            clipboard.copy_image(image)
        return path

    def _document(self, image: Image.Image, source: str = "") -> Document:
        return Document(image, self.settings.annotation, source=source)

    def _open_editor(self, image: Image.Image, source: str = "") -> EditorWindow:
        window = EditorWindow(
            self,
            self._document(image, source),
            self.settings,
            on_done=self._on_editor_done,
        )
        self.editors.append(window)
        window.present()
        return window

    def _run_editor(self) -> None:
        if not self.images:
            path = self._save(self._capture_full(), kind="full")
            self.images = [load_image(path)]
        for image in self.images:
            self._open_editor(image, self.options.get("source", ""))

    def _run_pin(self) -> None:
        position = self.options.get("position") or (140, 140)
        scale = float(self.options.get("scale", 1.0))
        offset = 0
        for image in self.images:
            self.spawn_pin(image, position=(position[0] + offset, position[1] + offset), scale=scale)
            offset += 28

    def spawn_pin(
        self,
        image: Image.Image,
        position: tuple[int, int] = (140, 140),
        scale: float = 1.0,
    ) -> PinWindow:
        """Create a pin window and keep the application alive while it is open."""

        window = PinWindow(
            self,
            image,
            self.settings,
            position=position,
            scale=scale,
            on_close=self.forget_pin,
        )
        self.pins.append(window)
        window.present()
        return window

    def forget_pin(self, window: Any) -> None:
        if window in self.pins:
            self.pins.remove(window)
        self._maybe_quit()

    def add_extra(self, window: Any) -> None:
        """Track one more window that should keep the application alive."""

        self.extra.append(window)

    def _on_extra_done(self, window: Any) -> None:
        if window in self.extra:
            self.extra.remove(window)
        self._maybe_quit()

    def _maybe_quit(self) -> None:
        if not self.editors and not self.pins and not self.extra:
            self.quit()

    def _run_history(self) -> None:
        window = HistoryWindow(
            self,
            self.settings,
            limit=int(self.options.get("limit", 60)),
            on_close=self._on_extra_done,
        )
        self.add_extra(window)
        window.present()

    def open_editor_path(self, path: str) -> EditorWindow:
        """Open the editor on an existing file."""

        return self._open_editor(load_image(path), source=path)

    def _run_record(self) -> None:
        options = self.options
        path = options.get("output")
        if not path:
            name = output.build_name(self.settings.capture)
            suffix = f".{self.settings.recording.container}"
            directory = output.resolve_save_dir(self.settings.capture)
            path = str(directory / (name + suffix))
        try:
            recorder = Recorder.start(
                path,
                region=self.region,
                fps=int(options.get("fps", self.settings.recording.fps)),
                backend=options.get("backend"),
                audio=bool(options.get("audio")),
            )
        except RecordError as exc:
            print(f"录制失败：{exc}", file=__import__("sys").stderr)
            self.quit()
            return
        self._recorder = recorder
        window = RecordControlWindow(self, recorder, options)
        window.present()

    def _on_editor_done(self, window: EditorWindow) -> None:
        if window in self.editors:
            self.editors.remove(window)
        self._maybe_quit()

    # ------------------------------------------------------------------ finish
    def finish_recording(self) -> None:
        if self._recorder is None or self.recording_result is None:
            return
        result = self.recording_result
        print(f"已保存录制：{result.path} ({result.duration:.1f}s, {result.backend})")
        options = self.options
        if options.get("gif"):
            try:
                target = self._recorder.to_gif(
                    fps=int(options.get("gif_fps", self.settings.recording.gif_fps)),
                    width=int(options.get("gif_width", self.settings.recording.gif_width)),
                )
                print(f"已生成 GIF：{target}")
            except RecordError as exc:
                print(f"GIF 转换失败：{exc}", file=__import__("sys").stderr)

    def _capture_full(self) -> Image.Image:
        from ..capture import screencopy

        frames = [screencopy.capture_output(info).image for info in screencopy.list_outputs()]
        return stitch(frames)


def run_gui(
    settings: Settings,
    action: str,
    images: Iterable[Image.Image] | None = None,
    options: dict[str, Any] | None = None,
    region: Any = None,
) -> int:
    """Start the GUI for one action and return a process exit code."""

    app = CatchlightApp(settings, action, images=images, options=options, region=region)
    status = app.run([])
    if app.recording_error:
        print(f"录制出错：{app.recording_error}", file=__import__("sys").stderr)
        return 1
    if action == "record":
        app.finish_recording()
    return int(status or 0)
