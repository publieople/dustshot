"""One D-Bus process for the tray tests: either a stub watcher or one tray item.

A synchronous D-Bus call from a connection to itself never dispatches its own
handler, so the item and the watcher have to live in processes of their own:

    python tests/tray_process.py watcher
    python tests/tray_process.py item /tmp/spawned.log
"""

from __future__ import annotations

import signal
import sys
from pathlib import Path

import gi

gi.require_version("GLib", "2.0")
from gi.repository import Gio, GLib

WATCHER_NAME = "org.kde.StatusNotifierWatcher"
WATCHER_PATH = "/StatusNotifierWatcher"
NAME_FLAG_DO_NOT_QUEUE = 0x4
NAME_RESULT_PRIMARY_OWNER = 1
CALL_TIMEOUT_MS = 5000

WATCHER_XML = """<node>
  <interface name="org.kde.StatusNotifierWatcher">
    <property name="RegisteredStatusNotifierItems" type="as" access="read"/>
    <property name="IsStatusNotifierHostRegistered" type="b" access="read"/>
    <property name="ProtocolVersion" type="i" access="read"/>
    <method name="RegisterStatusNotifierItem">
      <arg name="service" type="s" direction="in"/>
    </method>
  </interface>
</node>"""


def _connection():
    return Gio.bus_get_sync(Gio.BusType.SESSION, None)


def _stop(loop: GLib.MainLoop) -> bool:
    loop.quit()
    return False


def _signal_source():
    # PyGObject moved this off GLib, and its callbacks arrive positionally.
    try:
        gi.require_version("GLibUnix", "2.0")
    except ValueError:  # pragma: no cover - missing on old PyGObject
        return GLib.unix_signal_add
    from gi.repository import GLibUnix

    return GLibUnix.signal_add


def _watch_signals(loop: GLib.MainLoop) -> None:
    for number in (signal.SIGINT, signal.SIGTERM):
        _signal_source()(GLib.PRIORITY_DEFAULT, number, _stop, loop)


def run_watcher() -> int:
    connection = _connection()
    reply = connection.call_sync(
        "org.freedesktop.DBus",
        "/org/freedesktop/DBus",
        "org.freedesktop.DBus",
        "RequestName",
        GLib.Variant("(su)", (WATCHER_NAME, NAME_FLAG_DO_NOT_QUEUE)),
        None,
        Gio.DBusCallFlags.NONE,
        CALL_TIMEOUT_MS,
        None,
    )
    if reply.unpack()[0] != NAME_RESULT_PRIMARY_OWNER:
        print("busy", flush=True)
        return 2
    registered: list[str] = []
    info = Gio.DBusNodeInfo.new_for_xml(WATCHER_XML).interfaces[0]

    def on_call(_connection, _sender, _path, _interface, method, parameters, invocation):
        if method == "RegisterStatusNotifierItem":
            registered.append(parameters.unpack()[0])
        invocation.return_value(None)

    def on_property(_connection, _sender, _path, _interface, name, *_rest):
        if name == "RegisteredStatusNotifierItems":
            return GLib.Variant("as", registered)
        if name == "IsStatusNotifierHostRegistered":
            return GLib.Variant("b", True)
        if name == "ProtocolVersion":
            return GLib.Variant("i", 0)
        return None

    connection.register_object(WATCHER_PATH, info, on_call, on_property, None)
    print("ready", flush=True)
    loop = GLib.MainLoop()
    _watch_signals(loop)
    loop.run()
    return 0


def run_item(log_path: str) -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from dustshot.ui.tray import TrayError, TrayItem

    log = Path(log_path)
    log.write_text("")
    commands: list[tuple[str, ...]] = []

    def spawn(command: tuple[str, ...]) -> None:
        commands.append(command)
        log.write_text("".join(" ".join(row) + chr(10) for row in commands))

    loop = GLib.MainLoop()
    try:
        item = TrayItem(spawn=spawn, on_quit=loop.quit)
    except TrayError as exc:
        print(f"error:{exc}", flush=True)
        return 1
    print(item.bus_name, flush=True)
    _watch_signals(loop)
    loop.run()
    item.close()
    return 0


def main(argv: list[str]) -> int:
    if len(argv) == 2 and argv[1] == "watcher":
        return run_watcher()
    if len(argv) == 3 and argv[1] == "item":
        return run_item(argv[2])
    print("usage: tray_process.py watcher | item LOG", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
