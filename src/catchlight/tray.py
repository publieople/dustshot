"""StatusNotifierItem model: the tray menu and the icon the host draws.

Everything in this module works without PyGObject, so the headless test suite can
cover the menu and the icon bytes; the D-Bus server itself lives in
catchlight.ui.tray and is imported only by the tray command.
"""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image, ImageDraw

from . import APP_ID
from .i18n import _

ICON_NAME = "io.github.catchlight"
TITLE = "Catchlight"
TOOLTIP = _("Wayland 原生的截图、标注与贴图工具")
ITEM_PATH = "/StatusNotifierItem"
MENU_PATH = "/MenuBar"
MENU_ROOT = 0
QUIT_ID = 7
BUS_PREFIX = "org.kde.StatusNotifierItem"
WATCHER_NAME = "org.kde.StatusNotifierWatcher"
WATCHER_PATH = "/StatusNotifierWatcher"


def item_bus_names(pid: int, sandbox_id: str | None = None) -> tuple[str, ...]:
    """The bus names the tray item may own, the conventional one first.

    StatusNotifierItem items normally live in the org.kde namespace, but a sandbox only lets
    a process own names inside its own application id, so the item retries there.
    """

    return (
        f"{BUS_PREFIX}-{pid}-1",
        f"{sandbox_id or APP_ID}.StatusNotifierItem-{pid}-1",
    )


RED = (232, 74, 60, 255)
YELLOW = (233, 196, 106, 255)
BACKDROP = (16, 17, 20, 255)


@dataclass(frozen=True, slots=True)
class MenuEntry:
    """One row of the tray menu; a separator carries no label and no command."""

    id: int
    label: str = ""
    command: tuple[str, ...] = ()
    separator: bool = False


MENU: tuple[MenuEntry, ...] = (
    MenuEntry(1, _("区域截图"), ("region",)),
    MenuEntry(2, _("全屏截图"), ("full",)),
    MenuEntry(3, _("录制区域"), ("record",)),
    MenuEntry(4, separator=True),
    MenuEntry(5, _("截图历史"), ("history", "--gui")),
    MenuEntry(6, separator=True),
    MenuEntry(QUIT_ID, _("退出托盘")),
)


def entries() -> tuple[MenuEntry, ...]:
    """The menu rows in display order."""

    return MENU


def entry(entry_id: int) -> MenuEntry | None:
    """The row with this id, or None."""

    for candidate in MENU:
        if candidate.id == entry_id:
            return candidate
    return None


def command_for(entry_id: int) -> tuple[str, ...] | None:
    """The CLI arguments a row runs; None for a separator or an unknown row."""

    found = entry(entry_id)
    if found is None or found.separator or not found.command:
        return None
    return found.command


def is_quit(entry_id: int) -> bool:
    return entry_id == QUIT_ID


def icon_image(size: int = 48) -> Image.Image:
    """Draw the tray icon: the dark tile, the red ring and the yellow tick."""

    if size < 8:
        raise ValueError(_("图标尺寸至少 8 像素"))
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    stroke = max(1, round(size / 12))
    draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=max(2, round(size / 6)), fill=BACKDROP)
    inset = round(size * 0.22)
    draw.ellipse((inset, inset, size - inset - 1, size - inset - 1), outline=RED, width=stroke)
    middle = size / 2
    dot = max(1, round(size / 10))
    draw.ellipse((middle - dot, middle - dot, middle + dot, middle + dot), fill=RED)
    draw.line((size * 0.72, size * 0.08, size * 0.9, size * 0.3), fill=YELLOW, width=stroke)
    return image


def pixmap(image: Image.Image) -> tuple[int, int, bytes]:
    """Encode an image as IconPixmap wants it: ARGB32 in network byte order."""

    rgba = image.convert("RGBA")
    red, green, blue, alpha = rgba.split()
    ordered = Image.merge("RGBA", (alpha, red, green, blue))
    return rgba.width, rgba.height, ordered.tobytes()


def icon_pixmap(size: int = 48) -> tuple[int, int, bytes]:
    return pixmap(icon_image(size))
