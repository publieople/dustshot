"""Command line interface for Catchlight."""

from __future__ import annotations

import argparse
import contextlib
import json
import shutil
import sys
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from . import __version__, clipboard, ocr
from .config import Settings, SettingsStore, cache_dir, config_path, data_dir, ensure_dirs
from .history import History

PROGRAM = "catchlight"

DESCRIPTION = "Wayland 原生的截图、标注与贴图工具"

EPILOG = """常用示例：
    catchlight                         框选截图并打开编辑器
    catchlight full                    截取全部输出
    catchlight region --pin            框选后直接钉在屏幕上
    catchlight ocr                     框选后识别文字
    catchlight record --gif            框选后录制并转 GIF
    catchlight pin shot.png            把已有图片钉在屏幕上
    catchlight doctor                  检查运行环境
"""


# --------------------------------------------------------------------------- helpers


def load_store() -> SettingsStore:
    return SettingsStore()


def require_gui() -> None:
    """Preload libgtk4-layer-shell before anything imports Gtk."""

    from .ui.layer import ensure_preload

    ensure_preload()


def parse_rect(text: str) -> Any:
    from .capture.base import Geometry

    parts = [piece.strip() for piece in text.replace("x", ",").split(",")]
    if len(parts) != 4:
        raise SystemExit("区域格式应为 x,y,w,h")
    try:
        return Geometry(*(int(float(piece)) for piece in parts))
    except ValueError as exc:
        raise SystemExit(f"区域必须是数字：{exc}") from exc


def parse_point(text: str) -> tuple[int, int]:
    pieces = [piece.strip() for piece in text.split(",")]
    if len(pieces) != 2:
        raise SystemExit("坐标格式应为 x,y")
    return int(pieces[0]), int(pieces[1])


def load_image(path: str) -> Any:
    from PIL import Image

    if path == "-":
        return Image.open(sys.stdin.buffer).convert("RGB")
    target = Path(path).expanduser()
    if not target.exists():
        raise SystemExit(f"找不到文件：{target}")
    image = Image.open(str(target))
    image.load()
    return image.convert("RGB")


def capture_full() -> Any:
    from .capture import screencopy

    return screencopy.capture_all()


def capture_region(region: Any) -> Any:
    from .capture import screencopy

    return screencopy.capture_region(region)


def pick_region(settings: Settings) -> Any:
    require_gui()
    from .ui.selector import select_region

    return select_region(settings)


def store_image(
    image: Any,
    settings: Settings,
    kind: str = "capture",
    note: str = "",
    path: str | None = None,
    copy: bool | None = None,
) -> str:
    from . import output

    target = str(output.save_image(image, settings.capture, path=path))
    try:
        history = History()
        history.record_image(target, image, kind=kind, note=note)
        history.save()
    except OSError:
        pass
    should_copy = settings.capture.copy_after_capture if copy is None else copy
    if should_copy:
        clipboard.copy_image(image)
    return target


def remember_region(settings: Settings, region: Any) -> None:
    if not settings.capture.remember_last_region or region is None:
        return
    settings.capture.last_region = [region.x, region.y, region.width, region.height]


def open_editor(image: Any, settings: Settings, source: str = "") -> int:
    require_gui()
    from .ui.app import run_gui

    return run_gui(settings, "editor", images=[image], options={"source": source})


def open_pin(image: Any, settings: Settings, position: tuple[int, int], scale: float) -> int:
    require_gui()
    from .ui.app import run_gui

    return run_gui(settings, "pin", images=[image], options={"position": position, "scale": scale})


def start_recording(args: argparse.Namespace, settings: Settings, region: Any = None) -> int:
    require_gui()
    from .ui.app import run_gui

    options = {
        "fps": args.fps if getattr(args, "fps", None) else settings.recording.fps,
        "audio": bool(getattr(args, "audio", False)),
        "gif": bool(getattr(args, "gif", False)),
        "gif_fps": getattr(args, "gif_fps", None) or settings.recording.gif_fps,
        "gif_width": getattr(args, "gif_width", None) or settings.recording.gif_width,
        "duration": getattr(args, "duration", None),
        "backend": getattr(args, "backend", None),
        "output": getattr(args, "output", None),
    }
    return run_gui(settings, "record", options=options, region=region)


def apply_overrides(settings: Settings, args: argparse.Namespace) -> None:
    if getattr(args, "dir", None):
        settings.capture.save_dir = str(Path(args.dir).expanduser())
    if getattr(args, "format", None):
        settings.capture.image_format = args.format
    if getattr(args, "no_copy", False):
        settings.capture.copy_after_capture = False


# ------------------------------------------------------------------------- commands


def command_capture(args: argparse.Namespace, settings: Settings, store: SettingsStore) -> int:
    apply_overrides(settings, args)
    delay = float(getattr(args, "delay", 0) or 0)
    if delay > 0:
        time.sleep(delay)

    explicit = getattr(args, "rect", None)
    source = "full" if args.command == "full" else "region"
    result = None
    region = None

    if explicit:
        region = parse_rect(explicit)
        image = capture_region(region)
    elif args.command == "full":
        image = capture_full()
    else:
        result = pick_region(settings)
        if result.key == "ctrl-r" and result.region is not None:
            return start_recording(args, settings, region=result.region)
        if not result.confirmed:
            print("已取消")
            return 0
        if result.full:
            image = capture_full()
        else:
            region = result.region
            image = capture_region(region)

    if region is not None:
        remember_region(settings, region)
        with contextlib.suppress(OSError):
            store.save()

    note = ""
    if region is not None:
        note = json.dumps([region.x, region.y, region.width, region.height])

    if result is not None and result.key == "ctrl-c":
        clipboard.copy_image(image)
        print("已复制到剪贴板")
        return 0

    if result is not None and result.key == "ctrl-s":
        path = store_image(image, settings, kind=source, note=note, copy=False)
        print(f"已保存：{path}")
        return 0

    path = store_image(image, settings, kind=source, note=note)
    print(f"已保存：{path}")

    if getattr(args, "no_editor", False):
        return 0
    if getattr(args, "pin", False):
        position = parse_point(args.position) if getattr(args, "position", None) else (140, 140)
        return open_pin(image, settings, position, float(getattr(args, "scale", 1.0)))
    if settings.capture.open_editor:
        return open_editor(image, settings, source=source)
    return 0


def command_edit(args: argparse.Namespace, settings: Settings, store: SettingsStore) -> int:
    image = load_image(args.file)
    return open_editor(image, settings, source=str(args.file))


def command_pin(args: argparse.Namespace, settings: Settings, store: SettingsStore) -> int:
    if args.file:
        image = load_image(args.file)
    else:
        result = pick_region(settings)
        if not result.confirmed:
            print("已取消")
            return 0
        image = capture_region(result.region) if result.region is not None else capture_full()
    position = parse_point(args.position) if args.position else (140, 140)
    return open_pin(image, settings, position, float(args.scale))


def command_ocr(args: argparse.Namespace, settings: Settings, store: SettingsStore) -> int:
    if args.file:
        image = load_image(args.file)
    else:
        result = pick_region(settings)
        if not result.confirmed:
            print("已取消")
            return 0
        image = capture_region(result.region) if result.region is not None else capture_full()

    languages = args.lang or settings.ocr.languages
    try:
        outcome = ocr.recognize(image, languages=languages, psm=args.psm)
    except ocr.OcrError as exc:
        print(f"OCR 失败：{exc}", file=sys.stderr)
        return 2

    if args.json:
        payload = {
            "text": outcome.text,
            "languages": outcome.languages,
            "confidence": outcome.confidence,
            "words": [asdict(word) for word in outcome.words],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(outcome.text)
        summary = (
            f"--- {len(outcome.words)} 个词，置信度 {outcome.confidence:.2f}，语言 {outcome.languages} ---"
        )
        print(summary, file=sys.stderr)
    if args.copy:
        clipboard.copy_text(outcome.text)
    return 0


def command_record(args: argparse.Namespace, settings: Settings, store: SettingsStore) -> int:
    if args.full:
        return start_recording(args, settings, region=None)
    result = pick_region(settings)
    if not result.confirmed:
        print("已取消")
        return 0
    return start_recording(args, settings, region=result.region)


def command_history(args: argparse.Namespace, settings: Settings, store: SettingsStore) -> int:
    history = History()
    if args.clear:
        history.entries = []
        history.save()
        print("已清空历史记录")
        return 0
    entries = history.recent(limit=args.limit)
    if args.json:
        print(json.dumps([asdict(entry) for entry in entries], ensure_ascii=False, indent=2))
        return 0
    if not entries:
        print("还没有截图记录")
        return 0
    for entry in entries:
        when = datetime.fromtimestamp(entry.created).strftime("%Y-%m-%d %H:%M:%S")
        print(f"{when}  {entry.kind:<8s} {entry.width:5d}x{entry.height:<5d}  {entry.path}")
    return 0


def coerce(current: Any, raw: str) -> Any:
    if isinstance(current, bool):
        return raw.strip().lower() in {"1", "true", "yes", "on", "y"}
    if isinstance(current, int):
        return int(raw)
    if isinstance(current, float):
        return float(raw)
    if isinstance(current, list):
        return json.loads(raw)
    return raw


def set_setting(settings: Settings, assignment: str) -> None:
    key, separator, raw = assignment.partition("=")
    if not separator:
        raise SystemExit("设置格式应为 段.字段=值，例如 capture.image_format=jpg")
    section, _, field = key.strip().partition(".")
    target = getattr(settings, section, None)
    if target is None:
        sections = ["capture", "annotation", "pin", "ocr", "recording"]
        raise SystemExit("没有这个设置段：{}（可用：{}）".format(section, ", ".join(sections)))
    if not hasattr(target, field):
        fields = sorted(vars(target))
        raise SystemExit("没有这个字段：{}.{}（可用：{}）".format(section, field, ", ".join(fields)))
    try:
        setattr(target, field, coerce(getattr(target, field), raw))
    except (TypeError, ValueError) as exc:
        raise SystemExit(f"值不合法：{exc}") from exc


def command_settings(args: argparse.Namespace, settings: Settings, store: SettingsStore) -> int:
    if args.reset:
        store.reset()
        print("已恢复默认设置")
        return 0
    if args.set:
        for assignment in args.set:
            set_setting(settings, assignment)
        path = store.save()
        print(f"已写入 {path}")
        return 0
    if args.show:
        print(json.dumps(asdict(store.load()), indent=2, ensure_ascii=False, sort_keys=True))
        return 0
    print(f"配置文件：{config_path()}")
    print(f"数据目录：{data_dir()}")
    print(f"缓存目录：{cache_dir()}")
    return 0


HOTKEY_TEMPLATES = {
    "niri": """# ~/.config/niri/config.kdl
binds {
    Mod+Shift+S { spawn "catchlight" "region"; }
    Mod+Shift+F { spawn "catchlight" "full"; }
    Mod+Shift+O { spawn "catchlight" "ocr"; }
    Mod+Shift+R { spawn "catchlight" "record" "--gif"; }
    Mod+Shift+V { spawn "catchlight" "pin"; }
}""",
    "hyprland": """# ~/.config/hypr/hyprland.conf
bind = SUPER SHIFT, S, exec, catchlight region
bind = SUPER SHIFT, F, exec, catchlight full
bind = SUPER SHIFT, O, exec, catchlight ocr
bind = SUPER SHIFT, R, exec, catchlight record --gif
bind = SUPER SHIFT, V, exec, catchlight pin""",
    "sway": """# ~/.config/sway/config
bindsym $mod+Shift+s exec catchlight region
bindsym $mod+Shift+f exec catchlight full
bindsym $mod+Shift+o exec catchlight ocr
bindsym $mod+Shift+r exec catchlight record --gif""",
    "gnome": """# GNOME：设置 -> 键盘 -> 自定义快捷键
名称: Catchlight 截图    命令: catchlight region    按键: Super+Shift+S
名称: Catchlight 全屏    命令: catchlight full      按键: Super+Shift+F
名称: Catchlight 取字    命令: catchlight ocr       按键: Super+Shift+O
名称: Catchlight 录制    命令: catchlight record --gif   按键: Super+Shift+R""",
    "kde": """# 系统设置 -> 快捷键 -> 自定义快捷键 -> 新建 -> 命令/URL
动作: Catchlight 截图   触发器: Meta+Shift+S   命令: catchlight region
动作: Catchlight 全屏   触发器: Meta+Shift+F   命令: catchlight full
动作: Catchlight 取字   触发器: Meta+Shift+O   命令: catchlight ocr
动作: Catchlight 录制   触发器: Meta+Shift+R   命令: catchlight record --gif""",
    "wlroots": """# 其它 wlroots 合成器（同 sway 写法）
bindsym $mod+Shift+s exec catchlight region
bindsym $mod+Shift+f exec catchlight full""",
}


def detect_compositor() -> str:
    import os

    if os.environ.get("NIRI_SOCKET"):
        return "niri"
    if os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        return "hyprland"
    if os.environ.get("SWAYSOCK"):
        return "sway"
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
    if "kde" in desktop or "plasma" in desktop:
        return "kde"
    if "gnome" in desktop:
        return "gnome"
    return "wlroots"


def command_hotkeys(args: argparse.Namespace, settings: Settings, store: SettingsStore) -> int:
    name = args.compositor or detect_compositor()
    if name == "auto":
        name = detect_compositor()
    template = HOTKEY_TEMPLATES.get(name)
    if template is None:
        print("支持的合成器：{}".format(", ".join(sorted(HOTKEY_TEMPLATES))), file=sys.stderr)
        return 2
    print(f"# Catchlight 快捷键（{name}）")
    print(template)
    print("")
    print(f"提示：{PROGRAM} 是唯一入口命令，所有子命令都支持 --help。")
    return 0


def command_doctor(args: argparse.Namespace, settings: Settings, store: SettingsStore) -> int:
    checks: list[tuple[str, bool, str]] = []

    def add(name: str, ok: bool, detail: str = "") -> None:
        checks.append((name, ok, detail))

    add("Wayland 会话", bool(sys.platform.startswith("linux")), sys.platform)
    import os

    display = os.environ.get("WAYLAND_DISPLAY", "")
    add("WAYLAND_DISPLAY", bool(display), display or "未设置")
    add("grim（截图）", shutil.which("grim") is not None, shutil.which("grim") or "未安装")
    add("niri IPC（区域/指针）", shutil.which("niri") is not None, shutil.which("niri") or "未安装")
    have_clipboard = shutil.which("wl-copy") is not None and shutil.which("wl-paste") is not None
    add("wl-copy/wl-paste（剪贴板）", have_clipboard, shutil.which("wl-copy") or "未安装")
    add("tesseract（OCR）", shutil.which("tesseract") is not None, shutil.which("tesseract") or "未安装")
    backends = [name for name in ("wf-recorder", "gpu-screen-recorder") if shutil.which(name)]
    add("录制后端（wf-recorder / gpu-screen-recorder）", bool(backends), ", ".join(backends) or "未安装")
    add("ffmpeg（GIF 转换）", shutil.which("ffmpeg") is not None, shutil.which("ffmpeg") or "未安装")

    try:
        import gi

        gi.require_version("Gtk", "4.0")
        from gi.repository import Gtk

        gtk_version = f"Gtk {Gtk.get_major_version()}.{Gtk.get_minor_version()}.{Gtk.get_micro_version()}"
        add("GTK4 / PyGObject", True, gtk_version)
    except Exception as exc:
        add("GTK4 / PyGObject", False, str(exc))

    lib = None
    try:
        from .ui.layer import library_path, preload_active

        lib = library_path()
        add("gtk4-layer-shell", lib is not None, lib or "未安装（贴图/选区会退化为普通窗口）")
        if preload_active():
            detail = "已预加载"
        else:
            detail = "缺少库，功能会退化" if lib is None else "需要时会自动重新执行以预加载"
        add("layer-shell 预加载", True, detail)
    except Exception as exc:
        add("gtk4-layer-shell", False, str(exc))

    langs: list[str] = []
    try:
        langs = ocr.available_languages()
    except Exception:
        langs = []
    add("OCR 语言包", bool(langs), ", ".join(langs) if langs else "未安装（tesseract-data-eng 等）")

    directory = Path(settings.capture.save_dir).expanduser()
    try:
        ensure_dirs()
        directory.mkdir(parents=True, exist_ok=True)
        writable = directory.is_dir()
        add("保存目录可写", writable, str(directory))
    except OSError as exc:
        add("保存目录可写", False, f"{directory}（{exc}）")

    width = max(len(name) for name, _, _ in checks)
    failures = 0
    for name, ok, detail in checks:
        mark = "[ok]  " if ok else "[!!]  "
        if not ok:
            failures += 1
        print(f"{mark}{name:<{width}} {detail}")
    print("")
    if failures:
        print(f"{failures} 项需要处理；缺少的可选依赖只影响对应功能。")
    else:
        print("环境看起来一切正常。")
    return 0


def command_version(args: argparse.Namespace, settings: Settings, store: SettingsStore) -> int:
    print(f"{PROGRAM} {__version__}")
    return 0


COMMANDS = {
    "region": command_capture,
    "full": command_capture,
    "capture": command_capture,
    "edit": command_edit,
    "pin": command_pin,
    "ocr": command_ocr,
    "record": command_record,
    "history": command_history,
    "settings": command_settings,
    "hotkeys": command_hotkeys,
    "doctor": command_doctor,
    "version": command_version,
}


# --------------------------------------------------------------------------- parser


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROGRAM,
        description=DESCRIPTION,
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version="%(prog)s " + __version__)
    subparsers = parser.add_subparsers(dest="command", metavar="命令")

    def add_capture_options(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("--edit", dest="force_editor", action="store_true", help="截完立刻打开编辑器")
        sub.add_argument("--no-editor", action="store_true", help="截完不打开编辑器")
        sub.add_argument("--pin", action="store_true", help="截完把图片钉在屏幕上")
        sub.add_argument("--position", metavar="X,Y", help="贴图初始位置（配合 --pin）")
        sub.add_argument("--scale", type=float, default=1.0, metavar="N", help="贴图初始缩放（配合 --pin）")
        sub.add_argument("--dir", metavar="PATH", help="本次保存目录")
        sub.add_argument("--format", choices=["png", "jpg", "jpeg", "webp"], help="本次保存格式")
        sub.add_argument("--no-copy", action="store_true", help="本次不复制到剪贴板")
        sub.add_argument("--delay", type=float, default=0.0, metavar="SEC", help="截图前延时")
        sub.add_argument("--rect", metavar="X,Y,W,H", help="直接截取指定区域（不弹选区）")

    region = subparsers.add_parser("region", help="框选截图（默认命令）")
    add_capture_options(region)

    full = subparsers.add_parser("full", help="截取所有输出")
    add_capture_options(full)

    capture = subparsers.add_parser("capture", help="同 region")
    add_capture_options(capture)

    edit = subparsers.add_parser("edit", help="打开编辑器编辑已有图片")
    edit.add_argument("file", help="图片路径，- 表示从标准输入读取")

    pin = subparsers.add_parser("pin", help="把图片钉在屏幕上")
    pin.add_argument("file", nargs="?", help="图片路径；省略时先框选截图")
    pin.add_argument("--position", metavar="X,Y", default="140,140", help="初始位置（默认 140,140）")
    pin.add_argument("--scale", type=float, default=1.0, metavar="N", help="初始缩放（默认 1.0）")

    ocr_parser = subparsers.add_parser("ocr", help="识别图片或框选区域的文字")
    ocr_parser.add_argument("file", nargs="?", help="图片路径；省略时先框选截图")
    ocr_parser.add_argument("--lang", help="语言，例如 eng+chi_sim")
    ocr_parser.add_argument("--psm", type=int, default=6, help="tesseract 页面分割模式（默认 6）")
    ocr_parser.add_argument("--copy", action="store_true", help="把识别结果复制到剪贴板")
    ocr_parser.add_argument("--json", action="store_true", help="输出带词框的 JSON")

    record = subparsers.add_parser("record", help="录制屏幕（可转 GIF）")
    record.add_argument("--full", action="store_true", help="录制整个桌面，不框选")
    record.add_argument("--fps", type=int, help="帧率")
    record.add_argument("--audio", action="store_true", help="录制系统音频（需要 wf-recorder）")
    record.add_argument("--gif", action="store_true", help="录制结束后转成 GIF")
    record.add_argument("--gif-fps", type=int, help="GIF 帧率")
    record.add_argument("--gif-width", type=int, help="GIF 宽度")
    record.add_argument("--duration", type=float, metavar="SEC", help="最长录制秒数")
    record.add_argument("--backend", choices=["wf-recorder", "gpu-screen-recorder"], help="指定录制后端")
    record.add_argument("--output", metavar="PATH", help="输出文件路径")

    history = subparsers.add_parser("history", help="查看截图历史")
    history.add_argument("--limit", type=int, default=20, help="显示条数（默认 20）")
    history.add_argument("--json", action="store_true", help="以 JSON 输出")
    history.add_argument("--clear", action="store_true", help="清空历史记录")

    settings = subparsers.add_parser("settings", help="查看或修改设置")
    settings.add_argument("--show", action="store_true", help="打印全部设置（JSON）")
    settings.add_argument("--set", action="append", metavar="段.字段=值", help="修改一项设置，可重复")
    settings.add_argument("--reset", action="store_true", help="恢复默认设置")

    hotkeys = subparsers.add_parser("hotkeys", help="生成桌面快捷键配置片段")
    hotkeys.add_argument("--compositor", choices=[*sorted(HOTKEY_TEMPLATES), "auto"], help="指定合成器")

    subparsers.add_parser("doctor", help="检查运行环境")
    subparsers.add_parser("version", help="显示版本")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    command = args.command or "region"
    args.command = command
    handler = COMMANDS.get(command)
    if handler is None:
        parser.error(f"未知命令：{command}")

    store = load_store()
    settings = store.load()
    if command in {"region", "full", "capture"} and getattr(args, "force_editor", False):
        settings.capture.open_editor = True

    try:
        return handler(args, settings, store)
    except KeyboardInterrupt:
        print("", file=sys.stderr)
        return 130
    except BrokenPipeError:
        return 0
    except Exception as exc:
        from .capture.screencopy import CaptureError

        if isinstance(exc, (CaptureError, ocr.OcrError)):
            print(f"出错：{exc}", file=sys.stderr)
            return 2
        raise


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
