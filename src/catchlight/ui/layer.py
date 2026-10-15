"""Optional gtk4-layer-shell integration.

Layer shell is what makes a true always-on-top overlay and pinboard possible on
a wlroots style compositor. When the typelib is missing the UI still runs, it
just falls back to regular toplevel windows.
"""

from __future__ import annotations

LAYER_SHELL = "Gtk4LayerShell"
LAYER_SHELL_VERSION = "1.0"


def layer_shell():
    """Return the Gtk4LayerShell module or None."""

    try:
        import gi

        gi.require_version(LAYER_SHELL, LAYER_SHELL_VERSION)
        from gi.repository import Gtk4LayerShell

        return Gtk4LayerShell
    except Exception:
        return None


def available() -> bool:
    return layer_shell() is not None


def init_window(
    window,
    monitor=None,
    layer: str = "overlay",
    anchors: tuple[str, ...] = ("top", "bottom", "left", "right"),
    margins: tuple[int, int, int, int] = (0, 0, 0, 0),
    exclusive_zone: int = -1,
    keyboard: str = "exclusive",
    namespace: str = "catchlight",
) -> bool:
    """Configure a window as a layer surface.

    anchors is a subset of top/bottom/left/right, margins is (top, right, bottom, left).
    Returns True when layer shell was applied.
    """

    shell = layer_shell()
    if shell is None:
        return False
    shell.init_for_window(window)
    shell.set_namespace(window, namespace)
    layers = {
        "background": shell.Layer.BACKGROUND,
        "bottom": shell.Layer.BOTTOM,
        "top": shell.Layer.TOP,
        "overlay": shell.Layer.OVERLAY,
    }
    shell.set_layer(window, layers.get(layer, shell.Layer.OVERLAY))
    edge = {
        "top": shell.Edge.TOP,
        "bottom": shell.Edge.BOTTOM,
        "left": shell.Edge.LEFT,
        "right": shell.Edge.RIGHT,
    }
    for name in ("top", "bottom", "left", "right"):
        shell.set_anchor(window, edge[name], name in anchors)
    top, right, bottom, left = margins
    shell.set_margin(window, shell.Edge.TOP, top)
    shell.set_margin(window, shell.Edge.RIGHT, right)
    shell.set_margin(window, shell.Edge.BOTTOM, bottom)
    shell.set_margin(window, shell.Edge.LEFT, left)
    shell.set_exclusive_zone(window, exclusive_zone)
    keyboard_modes = {
        "none": shell.KeyboardMode.NONE,
        "exclusive": shell.KeyboardMode.EXCLUSIVE,
        "ondemand": shell.KeyboardMode.ON_DEMAND,
    }
    shell.set_keyboard_mode(window, keyboard_modes.get(keyboard, shell.KeyboardMode.EXCLUSIVE))
    if monitor is not None:
        shell.set_monitor(window, monitor)
    return True


def reexec_argv() -> list[str]:
    """Build the argv that re-runs this process through the interpreter.

    sys.orig_argv[0] is whatever the user typed ("python3"), which is not a
    path we can hand to execve as a script, so it is replaced by the resolved
    interpreter. A plain script path is kept: python runs it directly.
    """

    import os
    import sys
    from pathlib import Path

    argv = list(getattr(sys, "orig_argv", None) or [])
    if not argv:
        return [sys.executable, *sys.argv]

    first = os.path.basename(argv[0])
    if first.startswith("python"):
        argv[0] = sys.executable
    elif Path(first).suffix == ".py":
        argv = [sys.executable, *argv]
    return argv


def is_layer_window(window) -> bool:
    shell = layer_shell()
    if shell is None:
        return False
    try:
        return bool(shell.is_layer_window(window))
    except Exception:
        return False


LIBRARY_NAMES = (
    "libgtk4-layer-shell.so",
    "libgtk4-layer-shell.so.0",
    "libgtk4-layer-shell.so.1",
)
LIBRARY_DIRS = (
    "/app/lib",
    "/app/lib64",
    "/usr/lib",
    "/usr/lib64",
    "/usr/local/lib",
    "/usr/lib/x86_64-linux-gnu",
)


def library_dirs() -> list[str]:
    """Return the directories to search, the loader path first.

    A Flatpak installs the library into /app/lib and points LD_LIBRARY_PATH at it, while a
    distribution package lands in /usr/lib; searching the loader path first also lets a
    sandboxed build shadow a host copy.
    """

    import os
    from pathlib import Path

    directories = [piece for piece in os.environ.get("LD_LIBRARY_PATH", "").split(":") if piece]
    directories.extend(LIBRARY_DIRS)
    seen: list[str] = []
    for directory in directories:
        if directory not in seen and Path(directory).is_dir():
            seen.append(directory)
    return seen


def library_path() -> str | None:
    """Locate libgtk4-layer-shell so it can be preloaded ahead of libwayland."""

    import ctypes.util
    from pathlib import Path

    found = ctypes.util.find_library("gtk4-layer-shell")
    candidates = []
    if found and Path(found).is_absolute():
        candidates.append(found)
    for directory in library_dirs():
        for name in LIBRARY_NAMES:
            candidates.append(str(Path(directory) / name))
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    return None


def preload_active() -> bool:
    import os

    return "gtk4-layer-shell" in os.environ.get("LD_PRELOAD", "")


def ensure_preload() -> bool:
    """Re-exec the process with libgtk4-layer-shell preloaded.

    GTK4 Layer Shell only works when its library is loaded before
    libwayland-client; a Python process imports GTK first, so the overlay would
    silently fall back to an ordinary window. Import this module and call this
    function before importing Gtk. Returns True when the process was replaced.
    """

    import os
    import sys

    if preload_active() or os.environ.get("CATCHLIGHT_NO_REEXEC") == "1":
        return False
    if not available():
        return False
    path = library_path()
    if path is None:
        return False
    environment = dict(os.environ)
    environment["LD_PRELOAD"] = (path + " " + environment.get("LD_PRELOAD", "")).strip()
    environment["CATCHLIGHT_PRELOADED"] = "1"
    os.execve(sys.executable, reexec_argv(), environment)
    return True  # pragma: no cover - exec never returns
