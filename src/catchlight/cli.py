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

from . import __version__, barcode, clipboard, ocr, scroll
from .config import Settings, SettingsStore, cache_dir, config_path, data_dir, ensure_dirs
from .history import History
from .i18n import _

PROGRAM = "catchlight"

DESCRIPTION = _("Wayland 原生的截图、标注与贴图工具")

EPILOG = _("""常用示例：
    catchlight                         框选截图并打开编辑器
    catchlight full                    截取全部输出
    catchlight region --pin            框选后直接钉在屏幕上
    catchlight ocr                     框选后识别文字
    catchlight record --gif            框选后录制并转 GIF
    catchlight pin shot.png            把已有图片钉在屏幕上
    catchlight codes                   框选并识别二维码/条码
    catchlight redact                 框选并自动遮住敏感信息
    catchlight scroll --steps 4         滚动截图并拼接成长图
    catchlight history --gui           浏览截图历史
    catchlight tray                   在系统托盘里驻留一个图标
    catchlight doctor                  检查运行环境
""")


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
        raise SystemExit(_("区域格式应为 x,y,w,h"))
    try:
        return Geometry(*(int(float(piece)) for piece in parts))
    except ValueError as exc:
        raise SystemExit(_("区域必须是数字：{exc}").format(exc=exc)) from exc


def parse_point(text: str) -> tuple[int, int]:
    pieces = [piece.strip() for piece in text.split(",")]
    if len(pieces) != 2:
        raise SystemExit(_("坐标格式应为 x,y"))
    return int(pieces[0]), int(pieces[1])


def load_image(path: str) -> Any:
    from PIL import Image

    if path == "-":
        return Image.open(sys.stdin.buffer).convert("RGB")
    target = Path(path).expanduser()
    if not target.exists():
        raise SystemExit(_("找不到文件：{target}").format(target=target))
    image = Image.open(str(target))
    image.load()
    return image.convert("RGB")


def capture_backend(name: str = "auto") -> str:
    """Resolve the requested capture backend to the one that will be used."""

    from .capture import portal, screencopy

    grim = screencopy.have_grim()
    if name == "auto" and grim:
        return "grim"
    return portal.backend_choice(name, grim=grim, portal=portal.have_portal())


def capture_full(backend: str = "auto") -> Any:
    from .capture import portal, screencopy

    if capture_backend(backend) == "portal":
        return portal.capture_all()
    return screencopy.capture_all()


def capture_region(region: Any, backend: str = "auto") -> Any:
    from .capture import portal, screencopy

    if capture_backend(backend) == "portal":
        return portal.capture_region(region)
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
    backend = getattr(args, "backend", None) or "auto"
    result = None
    region = None

    if explicit:
        region = parse_rect(explicit)
        image = capture_region(region, backend)
    elif args.command == "full":
        image = capture_full(backend)
    else:
        result = pick_region(settings)
        if result.key == "ctrl-r" and result.region is not None:
            return start_recording(args, settings, region=result.region)
        if not result.confirmed:
            print(_("已取消"))
            return 0
        if result.full:
            image = capture_full(backend)
        else:
            region = result.region
            image = capture_region(region, backend)

    if region is not None:
        remember_region(settings, region)
        with contextlib.suppress(OSError):
            store.save()

    note = ""
    if region is not None:
        note = json.dumps([region.x, region.y, region.width, region.height])

    if result is not None and result.key == "ctrl-c":
        clipboard.copy_image(image)
        print(_("已复制到剪贴板"))
        return 0

    if result is not None and result.key == "ctrl-s":
        path = store_image(image, settings, kind=source, note=note, copy=False)
        print(_("已保存：{path}").format(path=path))
        return 0

    path = store_image(image, settings, kind=source, note=note)
    print(_("已保存：{path}").format(path=path))

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
            print(_("已取消"))
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
            print(_("已取消"))
            return 0
        image = capture_region(result.region) if result.region is not None else capture_full()

    languages = args.lang or settings.ocr.languages
    try:
        outcome = ocr.recognize(image, languages=languages, psm=args.psm)
    except ocr.OcrError as exc:
        print(_("OCR 失败：{exc}").format(exc=exc), file=sys.stderr)
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
        summary = _("--- {words} 个词，置信度 {confidence:.2f}，语言 {languages} ---").format(
            words=len(outcome.words),
            confidence=outcome.confidence,
            languages=outcome.languages,
        )
        print(summary, file=sys.stderr)
    if args.copy:
        clipboard.copy_text(outcome.text)
    return 0


def command_codes(args: argparse.Namespace, settings: Settings, store: SettingsStore) -> int:
    if args.file:
        image = load_image(args.file)
    else:
        result = pick_region(settings)
        if not result.confirmed:
            print(_("已取消"))
            return 0
        image = capture_region(result.region) if result.region is not None else capture_full()

    try:
        codes = barcode.decode(image, command=args.decoder)
    except barcode.BarcodeError as exc:
        print(_("条码识别失败：{exc}").format(exc=exc), file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps([code.to_dict() for code in codes], ensure_ascii=False, indent=2))
    elif not codes:
        print(_("没有找到条码或二维码"), file=sys.stderr)
    else:
        for code in codes:
            label = code.kind or "barcode"
            print(f"{label}	{code.text}")
    if args.copy and codes:
        clipboard.copy_text("\n".join(code.text for code in codes))
    return 0


def command_redact(args: argparse.Namespace, settings: Settings, store: SettingsStore) -> int:
    from . import redact
    from .annotation.render import render as render_image
    from .annotation.render import render_to_file

    if args.file:
        image = load_image(args.file)
    else:
        result = pick_region(settings)
        if not result.confirmed:
            print(_("已取消"))
            return 0
        image = capture_region(result.region) if result.region is not None else capture_full()

    kinds = (
        tuple(piece.strip() for piece in args.kinds.split(",") if piece.strip())
        if args.kinds
        else redact.KINDS
    )
    unknown = [kind for kind in kinds if kind not in redact.PATTERNS]
    if unknown:
        print(_("未知的类型：{types}").format(types=", ".join(unknown)), file=sys.stderr)
        return 2

    languages = args.lang or settings.ocr.languages
    try:
        outcome = ocr.recognize(image, languages=languages, psm=args.psm)
    except ocr.OcrError as exc:
        print(_("OCR 失败：{exc}").format(exc=exc), file=sys.stderr)
        return 2

    matches = redact.find_sensitive(outcome.words, kinds=kinds)
    if not matches:
        print(_("没有发现敏感信息"), file=sys.stderr)
        return 0

    items = redact.mask_items(
        matches,
        block=args.block or settings.annotation.mosaic_block,
        mode=args.mode,
        blur_radius=settings.annotation.blur_radius,
        padding=args.padding,
    )
    if args.json:
        print(json.dumps([match.to_dict() for match in matches], ensure_ascii=False, indent=2))
    else:
        for match in matches:
            print(f"{match.kind}	{match.text}")

    rendered = render_image(image, items)
    if args.output:
        target = Path(args.output).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        render_to_file(image, items, target)
        print(_("已脱敏并保存：{target}").format(target=target))
    elif not args.edit:
        note = json.dumps([match.to_dict() for match in matches], ensure_ascii=False)
        saved = store_image(rendered, settings, kind="redact", note=note)
        print(_("已脱敏并保存：{saved}").format(saved=saved))
    if args.copy:
        clipboard.copy_image(rendered)
    if args.edit:
        return open_editor(rendered, settings, source=args.file or "")
    return 0


def command_scroll(args: argparse.Namespace, settings: Settings, store: SettingsStore) -> int:
    apply_overrides(settings, args)
    delay = float(getattr(args, "delay", 0) or 0)
    if delay > 0:
        time.sleep(delay)

    explicit = getattr(args, "rect", None)
    region = parse_rect(explicit) if explicit else pick_region(settings).region
    if region is None:
        print(_("已取消"))
        return 0
    remember_region(settings, region)
    with contextlib.suppress(OSError):
        store.save()

    steps = max(1, int(getattr(args, "steps", 5) or 5))
    min_overlap = max(1, int(getattr(args, "min_overlap", scroll.MIN_OVERLAP) or scroll.MIN_OVERLAP))
    settle = max(0.0, float(getattr(args, "settle", 0.0) or 0.0))
    if getattr(args, "manual", False):

        def advance() -> None:
            input(_("滚动到下一屏后按回车继续…"))

    else:

        def advance() -> None:
            scroll.advance_scroll(getattr(args, "advance", None))

    def announce(index: int, image: Any) -> None:
        print(
            _("  第 {index}/{steps} 帧：{width} x {height}").format(
                index=index, steps=steps, width=image.width, height=image.height
            ),
            file=sys.stderr,
        )

    try:
        canvas, overlaps = scroll.scroll_capture(
            region,
            steps=steps,
            capture=capture_region,
            advance=advance,
            min_overlap=min_overlap,
            settle=settle,
            on_step=announce,
        )
    except scroll.ScrollError as error:
        print(_("滚动截图失败：{error}").format(error=error), file=sys.stderr)
        return 1

    note = json.dumps(
        {"region": [region.x, region.y, region.width, region.height], "overlaps": overlaps},
        ensure_ascii=False,
    )
    copy = False if getattr(args, "no_copy", False) else None
    path = store_image(
        canvas,
        settings,
        kind="scroll",
        note=note,
        path=getattr(args, "output", None),
        copy=copy,
    )
    print(
        _("已保存滚动截图：{path}（{width} x {height}，{frames} 帧）").format(
            path=path, width=canvas.width, height=canvas.height, frames=len(overlaps) + 1
        )
    )

    if getattr(args, "no_editor", False):
        return 0
    if getattr(args, "force_editor", False) or settings.capture.open_editor:
        return open_editor(canvas, settings, source="scroll")
    return 0


def command_record(args: argparse.Namespace, settings: Settings, store: SettingsStore) -> int:
    if args.full:
        return start_recording(args, settings, region=None)
    result = pick_region(settings)
    if not result.confirmed:
        print(_("已取消"))
        return 0
    return start_recording(args, settings, region=result.region)


def command_history(args: argparse.Namespace, settings: Settings, store: SettingsStore) -> int:
    if getattr(args, "gui", False):
        require_gui()
        from .ui.app import run_gui

        return run_gui(settings, "history", options={"limit": args.limit})
    history = History()
    if args.clear:
        history.entries = []
        history.save()
        print(_("已清空历史记录"))
        return 0
    entries = history.recent(limit=args.limit)
    if args.json:
        print(json.dumps([asdict(entry) for entry in entries], ensure_ascii=False, indent=2))
        return 0
    if not entries:
        print(_("还没有截图记录"))
        return 0
    for entry in entries:
        when = datetime.fromtimestamp(entry.created).strftime("%Y-%m-%d %H:%M:%S")
        print(f"{when}  {entry.kind:<8s} {entry.width:5d}x{entry.height:<5d}  {entry.path}")
    return 0


def command_tray(args: argparse.Namespace, settings: Settings, store: SettingsStore) -> int:
    from .ui.tray import run_tray

    return run_tray(settings)


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
        raise SystemExit(_("设置格式应为 段.字段=值，例如 capture.image_format=jpg"))
    section, _sep, field = key.strip().partition(".")
    target = getattr(settings, section, None)
    if target is None:
        sections = ["capture", "annotation", "pin", "ocr", "recording"]
        raise SystemExit(_("没有这个设置段：{}（可用：{}）").format(section, ", ".join(sections)))
    if not hasattr(target, field):
        fields = sorted(vars(target))
        raise SystemExit(_("没有这个字段：{}.{}（可用：{}）").format(section, field, ", ".join(fields)))
    try:
        setattr(target, field, coerce(getattr(target, field), raw))
    except (TypeError, ValueError) as exc:
        raise SystemExit(_("值不合法：{exc}").format(exc=exc)) from exc


def command_settings(args: argparse.Namespace, settings: Settings, store: SettingsStore) -> int:
    if args.reset:
        store.reset()
        print(_("已恢复默认设置"))
        return 0
    if args.set:
        for assignment in args.set:
            set_setting(settings, assignment)
        path = store.save()
        print(_("已写入 {path}").format(path=path))
        return 0
    if args.show:
        print(json.dumps(asdict(store.load()), indent=2, ensure_ascii=False, sort_keys=True))
        return 0
    print(_("配置文件：{path}").format(path=config_path()))
    print(_("数据目录：{path}").format(path=data_dir()))
    print(_("缓存目录：{path}").format(path=cache_dir()))
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
    "gnome": _("""# GNOME：设置 -> 键盘 -> 自定义快捷键
名称: Catchlight 截图    命令: catchlight region    按键: Super+Shift+S
名称: Catchlight 全屏    命令: catchlight full      按键: Super+Shift+F
名称: Catchlight 取字    命令: catchlight ocr       按键: Super+Shift+O
名称: Catchlight 录制    命令: catchlight record --gif   按键: Super+Shift+R"""),
    "kde": _("""# 系统设置 -> 快捷键 -> 自定义快捷键 -> 新建 -> 命令/URL
动作: Catchlight 截图   触发器: Meta+Shift+S   命令: catchlight region
动作: Catchlight 全屏   触发器: Meta+Shift+F   命令: catchlight full
动作: Catchlight 取字   触发器: Meta+Shift+O   命令: catchlight ocr
动作: Catchlight 录制   触发器: Meta+Shift+R   命令: catchlight record --gif"""),
    "wlroots": _("""# 其它 wlroots 合成器（同 sway 写法）
bindsym $mod+Shift+s exec catchlight region
bindsym $mod+Shift+f exec catchlight full"""),
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
        print(_("支持的合成器：{}").format(", ".join(sorted(HOTKEY_TEMPLATES))), file=sys.stderr)
        return 2
    print(_("# Catchlight 快捷键（{name}）").format(name=name))
    print(template)
    print("")
    print(_("提示：{PROGRAM} 是唯一入口命令，所有子命令都支持 --help。").format(PROGRAM=PROGRAM))
    return 0


def command_doctor(args: argparse.Namespace, settings: Settings, store: SettingsStore) -> int:
    checks: list[tuple[str, bool, str]] = []

    def add(name: str, ok: bool, detail: str = "") -> None:
        checks.append((name, ok, detail))

    add(_("Wayland 会话"), bool(sys.platform.startswith("linux")), sys.platform)
    import os

    display = os.environ.get("WAYLAND_DISPLAY", "")
    add("WAYLAND_DISPLAY", bool(display), display or _("未设置"))
    add(_("grim（截图）"), shutil.which("grim") is not None, shutil.which("grim") or _("未安装"))
    add(_("niri IPC（区域/指针）"), shutil.which("niri") is not None, shutil.which("niri") or _("未安装"))
    have_clipboard = shutil.which("wl-copy") is not None and shutil.which("wl-paste") is not None
    add(_("wl-copy/wl-paste（剪贴板）"), have_clipboard, shutil.which("wl-copy") or _("未安装"))
    add("tesseract（OCR）", shutil.which("tesseract") is not None, shutil.which("tesseract") or _("未安装"))
    backends = [name for name in ("wf-recorder", "gpu-screen-recorder") if shutil.which(name)]
    add(
        _("录制后端（wf-recorder / gpu-screen-recorder）"), bool(backends), ", ".join(backends) or _("未安装")
    )
    add(_("ffmpeg（GIF 转换）"), shutil.which("ffmpeg") is not None, shutil.which("ffmpeg") or _("未安装"))

    try:
        from .capture import portal

        version = portal.portal_version()
        add(
            "ScreenCast portal（--backend portal）",
            version is not None,
            f"version {version}" if version is not None else _("不可用"),
        )
    except Exception as exc:  # pragma: no cover - depends on host
        add("ScreenCast portal（--backend portal）", False, str(exc))

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
        add("gtk4-layer-shell", lib is not None, lib or _("未安装（贴图/选区会退化为普通窗口）"))
        if preload_active():
            detail = _("已预加载")
        else:
            detail = _("缺少库，功能会退化") if lib is None else _("需要时会自动重新执行以预加载")
        add(_("layer-shell 预加载"), True, detail)
    except Exception as exc:
        add("gtk4-layer-shell", False, str(exc))

    langs: list[str] = []
    try:
        langs = ocr.available_languages()
    except Exception:
        langs = []
    add(_("OCR 语言包"), bool(langs), ", ".join(langs) if langs else _("未安装（tesseract-data-eng 等）"))

    directory = Path(settings.capture.save_dir).expanduser()
    try:
        ensure_dirs()
        directory.mkdir(parents=True, exist_ok=True)
        writable = directory.is_dir()
        add(_("保存目录可写"), writable, str(directory))
    except OSError as exc:
        add(_("保存目录可写"), False, f"{directory}（{exc}）")

    width = max(len(name) for name, _unused, _unused2 in checks)
    failures = 0
    for name, ok, detail in checks:
        mark = "[ok]  " if ok else "[!!]  "
        if not ok:
            failures += 1
        print(f"{mark}{name:<{width}} {detail}")
    print("")
    if failures:
        print(_("{failures} 项需要处理；缺少的可选依赖只影响对应功能。").format(failures=failures))
    else:
        print(_("环境看起来一切正常。"))
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
    "codes": command_codes,
    "redact": command_redact,
    "scroll": command_scroll,
    "tray": command_tray,
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
    subparsers = parser.add_subparsers(dest="command", metavar=_("命令"))

    def add_capture_options(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("--edit", dest="force_editor", action="store_true", help=_("截完立刻打开编辑器"))
        sub.add_argument("--no-editor", action="store_true", help=_("截完不打开编辑器"))
        sub.add_argument("--pin", action="store_true", help=_("截完把图片钉在屏幕上"))
        sub.add_argument("--position", metavar="X,Y", help=_("贴图初始位置（配合 --pin）"))
        sub.add_argument(
            "--scale", type=float, default=1.0, metavar="N", help=_("贴图初始缩放（配合 --pin）")
        )
        sub.add_argument("--dir", metavar="PATH", help=_("本次保存目录"))
        sub.add_argument("--format", choices=["png", "jpg", "jpeg", "webp"], help=_("本次保存格式"))
        sub.add_argument("--no-copy", action="store_true", help=_("本次不复制到剪贴板"))
        sub.add_argument("--delay", type=float, default=0.0, metavar="SEC", help=_("截图前延时"))
        sub.add_argument("--rect", metavar="X,Y,W,H", help=_("直接截取指定区域（不弹选区）"))
        sub.add_argument(
            "--backend",
            choices=["auto", "grim", "portal"],
            default="auto",
            help=_("截图后端：auto 优先 grim，没有 grim 时用 ScreenCast portal"),
        )

    region = subparsers.add_parser("region", help=_("框选截图（默认命令）"))
    add_capture_options(region)

    full = subparsers.add_parser("full", help=_("截取所有输出"))
    add_capture_options(full)

    capture = subparsers.add_parser("capture", help=_("同 region"))
    add_capture_options(capture)

    edit = subparsers.add_parser("edit", help=_("打开编辑器编辑已有图片"))
    edit.add_argument("file", help=_("图片路径，- 表示从标准输入读取"))

    pin = subparsers.add_parser("pin", help=_("把图片钉在屏幕上"))
    pin.add_argument("file", nargs="?", help=_("图片路径；省略时先框选截图"))
    pin.add_argument("--position", metavar="X,Y", default="140,140", help=_("初始位置（默认 140,140）"))
    pin.add_argument("--scale", type=float, default=1.0, metavar="N", help=_("初始缩放（默认 1.0）"))

    ocr_parser = subparsers.add_parser("ocr", help=_("识别图片或框选区域的文字"))
    ocr_parser.add_argument("file", nargs="?", help=_("图片路径；省略时先框选截图"))
    ocr_parser.add_argument("--lang", help=_("语言，例如 eng+chi_sim"))
    ocr_parser.add_argument("--psm", type=int, default=6, help=_("tesseract 页面分割模式（默认 6）"))
    ocr_parser.add_argument("--copy", action="store_true", help=_("把识别结果复制到剪贴板"))
    ocr_parser.add_argument("--json", action="store_true", help=_("输出带词框的 JSON"))

    scroll_parser = subparsers.add_parser("scroll", help=_("滚动截图：连续截图并自动拼接成长图"))
    scroll_parser.add_argument("--steps", type=int, default=5, metavar="N", help=_("截图帧数（默认 5）"))
    scroll_parser.add_argument(
        "--advance",
        choices=["wtype", "ydotool"],
        help=_("自动滚动后端（默认自动选择）"),
    )
    scroll_parser.add_argument("--manual", action="store_true", help=_("自己滚动，每滚一屏按回车继续"))
    scroll_parser.add_argument(
        "--min-overlap",
        type=int,
        default=scroll.MIN_OVERLAP,
        metavar="N",
        help=_("最小重叠行数（默认 24）"),
    )
    scroll_parser.add_argument(
        "--settle",
        type=float,
        default=0.35,
        metavar="SEC",
        help=_("每滚一屏后等待画面稳定的秒数（默认 0.35）"),
    )
    scroll_parser.add_argument("--rect", metavar="X,Y,W,H", help=_("直接截取指定区域（不弹选区）"))
    scroll_parser.add_argument("--edit", dest="force_editor", action="store_true", help=_("拼接完打开编辑器"))
    scroll_parser.add_argument("--no-editor", action="store_true", help=_("拼接完不打开编辑器"))
    scroll_parser.add_argument("--dir", metavar="PATH", help=_("本次保存目录"))
    scroll_parser.add_argument(
        "--format",
        choices=["png", "jpg", "jpeg", "webp"],
        help=_("本次保存格式"),
    )
    scroll_parser.add_argument("--no-copy", action="store_true", help=_("本次不复制到剪贴板"))
    scroll_parser.add_argument("--delay", type=float, default=0.0, metavar="SEC", help=_("开始前延时"))
    scroll_parser.add_argument("--output", metavar="PATH", help=_("输出文件路径"))

    record = subparsers.add_parser("record", help=_("录制屏幕（可转 GIF）"))
    record.add_argument("--full", action="store_true", help=_("录制整个桌面，不框选"))
    record.add_argument("--fps", type=int, help=_("帧率"))
    record.add_argument("--audio", action="store_true", help=_("录制系统音频（需要 wf-recorder）"))
    record.add_argument("--gif", action="store_true", help=_("录制结束后转成 GIF"))
    record.add_argument("--gif-fps", type=int, help=_("GIF 帧率"))
    record.add_argument("--gif-width", type=int, help=_("GIF 宽度"))
    record.add_argument("--duration", type=float, metavar="SEC", help=_("最长录制秒数"))
    record.add_argument("--backend", choices=["wf-recorder", "gpu-screen-recorder"], help=_("指定录制后端"))
    record.add_argument("--output", metavar="PATH", help=_("输出文件路径"))

    codes = subparsers.add_parser("codes", help=_("识别图片或框选区域的二维码/条码"))
    codes.add_argument("file", nargs="?", help=_("图片路径；省略时先框选截图"))
    codes.add_argument(
        "--command",
        dest="decoder",
        default=barcode.DEFAULT_COMMAND,
        metavar="CMD",
        help=_("解码命令（默认 zbarimg）"),
    )
    codes.add_argument("--copy", action="store_true", help=_("把识别结果复制到剪贴板"))
    codes.add_argument("--json", action="store_true", help=_("以 JSON 输出"))

    redact_parser = subparsers.add_parser("redact", help=_("找出并遮住图片中的敏感文字"))
    redact_parser.add_argument("file", nargs="?", help=_("图片路径；省略时先框选截图"))
    redact_parser.add_argument("--lang", help=_("OCR 语言，默认取设置"))
    redact_parser.add_argument("--psm", type=int, default=6, help=_("tesseract 页面分割模式（默认 6）"))
    redact_parser.add_argument("--kinds", metavar="LIST", help=_("只查找这些类型，逗号分隔"))
    redact_parser.add_argument(
        "--mode", choices=["solid", "mosaic", "blur"], default="solid", help=_("遮住方式")
    )
    redact_parser.add_argument("--padding", type=int, default=4, help=_("每块外扩像素（默认 4）"))
    redact_parser.add_argument("--block", type=int, help=_("马赛克块大小"))
    redact_parser.add_argument("--edit", action="store_true", help=_("在编辑器里打开结果"))
    redact_parser.add_argument("--output", metavar="PATH", help=_("输出文件路径"))
    redact_parser.add_argument("--copy", action="store_true", help=_("把脱敏后的图片复制到剪贴板"))
    redact_parser.add_argument("--json", action="store_true", help=_("以 JSON 输出命中的内容"))

    subparsers.add_parser("tray", help=_("在系统托盘里驻留一个图标"))

    history = subparsers.add_parser("history", help=_("查看截图历史"))
    history.add_argument("--limit", type=int, default=20, help=_("显示条数（默认 20）"))
    history.add_argument("--json", action="store_true", help=_("以 JSON 输出"))
    history.add_argument("--clear", action="store_true", help=_("清空历史记录"))
    history.add_argument("--gui", action="store_true", help=_("打开可浏览的历史窗口"))

    settings = subparsers.add_parser("settings", help=_("查看或修改设置"))
    settings.add_argument("--show", action="store_true", help=_("打印全部设置（JSON）"))
    settings.add_argument("--set", action="append", metavar=_("段.字段=值"), help=_("修改一项设置，可重复"))
    settings.add_argument("--reset", action="store_true", help=_("恢复默认设置"))

    hotkeys = subparsers.add_parser("hotkeys", help=_("生成桌面快捷键配置片段"))
    hotkeys.add_argument("--compositor", choices=[*sorted(HOTKEY_TEMPLATES), "auto"], help=_("指定合成器"))

    subparsers.add_parser("doctor", help=_("检查运行环境"))
    subparsers.add_parser("version", help=_("显示版本"))

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    command = args.command or "region"
    args.command = command
    handler = COMMANDS.get(command)
    if handler is None:
        parser.error(_("未知命令：{command}").format(command=command))

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
            print(_("出错：{exc}").format(exc=exc), file=sys.stderr)
            return 2
        raise


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
