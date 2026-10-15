"""A fake org.freedesktop.portal.Desktop used by the D-Bus tests.

Run as: python tests/portal_process.py portal LOG [normal|cancel]

It speaks just enough of the ScreenCast portal (CreateSession / SelectSources /
Start / OpenPipeWireRemote plus the Request.Response signal and Session.Close)
to drive the real client in another process, and appends every call it saw to
LOG as one JSON object per line.
"""

from __future__ import annotations

import json
import socket
import sys
from pathlib import Path

import gi

gi.require_version("GLib", "2.0")
from gi.repository import Gio, GLib

BUS_NAME = "org.freedesktop.portal.Desktop"
OBJECT_PATH = "/org/freedesktop/portal/desktop"
SCREENCAST = "org.freedesktop.portal.ScreenCast"
REQUEST = "org.freedesktop.portal.Request"
SESSION = "org.freedesktop.portal.Session"
VERSION = 5

PORTAL_XML = """
<node>
  <interface name="org.freedesktop.portal.ScreenCast">
    <method name="CreateSession">
      <arg type="a{sv}" name="options" direction="in"/>
      <arg type="o" name="handle" direction="out"/>
    </method>
    <method name="SelectSources">
      <arg type="o" name="session_handle" direction="in"/>
      <arg type="a{sv}" name="options" direction="in"/>
      <arg type="o" name="handle" direction="out"/>
    </method>
    <method name="Start">
      <arg type="o" name="session_handle" direction="in"/>
      <arg type="s" name="parent_window" direction="in"/>
      <arg type="a{sv}" name="options" direction="in"/>
      <arg type="o" name="handle" direction="out"/>
    </method>
    <method name="OpenPipeWireRemote">
      <arg type="o" name="session_handle" direction="in"/>
      <arg type="a{sv}" name="options" direction="in"/>
      <arg type="h" name="fd" direction="out"/>
    </method>
    <property name="version" type="u" access="read"/>
  </interface>
  <interface name="org.freedesktop.portal.Request">
    <method name="Close"/>
    <signal name="Response">
      <arg type="u" name="response"/>
      <arg type="a{sv}" name="results"/>
    </signal>
  </interface>
  <interface name="org.freedesktop.portal.Session">
    <method name="Close"/>
  </interface>
</node>
"""


def _escape(unique_name: str) -> str:
    sender = unique_name[1:] if unique_name.startswith(":") else unique_name
    return sender.replace(".", "_")


def request_path(unique_name: str, token: str) -> str:
    return f"{OBJECT_PATH}/request/{_escape(unique_name)}/{token}"


def session_path(unique_name: str, token: str) -> str:
    return f"{OBJECT_PATH}/session/{_escape(unique_name)}/{token}"


class FakePortal:
    def __init__(self, connection, log_path: Path, mode: str) -> None:
        self.connection = connection
        self.log_path = Path(log_path)
        self.mode = mode
        self.node = Gio.DBusNodeInfo.new_for_xml(PORTAL_XML)
        self.sessions = []
        self.sockets = []
        self.registrations = []

    # ------------------------------------------------------------------ helpers
    def record(self, entry: dict) -> None:
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")

    def emit_response(self, sender: str, token: str, code: int, results: dict) -> None:
        self.connection.emit_signal(
            None,
            request_path(sender, token),
            REQUEST,
            "Response",
            GLib.Variant("(ua{sv})", (code, results)),
        )

    # -------------------------------------------------------------------- setup
    def register(self) -> None:
        self.registrations.append(
            self.connection.register_object(
                OBJECT_PATH,
                self.node.lookup_interface(SCREENCAST),
                self.on_method,
                self.on_property,
                None,
            )
        )

    def register_session(self, path: str) -> None:
        if path in self.sessions:
            return
        self.sessions.append(path)
        self.registrations.append(
            self.connection.register_object(
                path,
                self.node.lookup_interface(SESSION),
                self.on_session_method,
                None,
                None,
            )
        )

    # ----------------------------------------------------------------- handlers
    def on_property(self, _connection, _sender, _path, _interface, name, *_rest):
        if name == "version":
            return GLib.Variant("u", VERSION)
        return None

    def on_session_method(self, _connection, _sender, path, _interface, method, _parameters, invocation):
        self.record({"method": method, "session": path})
        invocation.return_value(None)

    def on_method(self, _connection, sender, _path, _interface, method, parameters, invocation):
        values = parameters.unpack()
        if method == "CreateSession":
            options = values[0]
            token = str(options.get("handle_token", "create"))
            session = session_path(sender, str(options.get("session_handle_token", "session")))
            self.record({"method": method, "options": options})
            self.register_session(session)
            invocation.return_value(GLib.Variant("(o)", (request_path(sender, token),)))
            if self.mode == "cancel":
                self.emit_response(sender, token, 1, {})
            else:
                self.emit_response(sender, token, 0, {"session_handle": GLib.Variant("s", session)})
            return
        if method == "SelectSources":
            session, options = values
            token = str(options.get("handle_token", "select"))
            self.record({"method": method, "session": session, "options": options})
            invocation.return_value(GLib.Variant("(o)", (request_path(sender, token),)))
            self.emit_response(sender, token, 0, {})
            return
        if method == "Start":
            session, parent, options = values
            token = str(options.get("handle_token", "start"))
            self.record({"method": method, "session": session, "parent": parent, "options": options})
            invocation.return_value(GLib.Variant("(o)", (request_path(sender, token),)))
            streams = [
                (
                    7,
                    {
                        "size": GLib.Variant("(ii)", (64, 48)),
                        "position": GLib.Variant("(ii)", (1920, 0)),
                        "source_type": GLib.Variant("u", 1),
                        "id": GLib.Variant("s", "eDP-1"),
                    },
                )
            ]
            self.emit_response(
                sender,
                token,
                0,
                {
                    "streams": GLib.Variant("a(ua{sv})", streams),
                    "restore_token": GLib.Variant("s", "restore-me"),
                },
            )
            return
        if method == "OpenPipeWireRemote":
            session = values[0]
            self.record({"method": method, "session": session})
            local, remote = socket.socketpair()
            self.sockets.append(local)
            local.sendall(b"portal-fd-ok")
            fd_list = Gio.UnixFDList.new()
            fd_list.append(remote.fileno())
            remote.close()
            invocation.return_value_with_unix_fd_list(GLib.Variant("(h)", (0,)), fd_list)
            return
        invocation.return_error_literal(Gio.DBusError, Gio.DBusError.UNKNOWN_METHOD, method)


def request_name(connection) -> None:
    reply = connection.call_sync(
        "org.freedesktop.DBus",
        "/org/freedesktop/DBus",
        "org.freedesktop.DBus",
        "RequestName",
        GLib.Variant("(su)", (BUS_NAME, 0)),
        GLib.VariantType("(u)"),
        Gio.DBusCallFlags.NONE,
        5000,
        None,
    )
    result = int(reply.unpack()[0])
    if result not in (1, 4):
        raise SystemExit(f"could not own {BUS_NAME}: {result}")


def main(argv: list[str]) -> int:
    log_path = Path(argv[2]) if len(argv) > 2 else Path("/tmp/portal_log.jsonl")
    mode = argv[3] if len(argv) > 3 else "normal"
    connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    request_name(connection)
    portal = FakePortal(connection, log_path, mode)
    portal.register()
    print("ready", flush=True)
    GLib.MainLoop().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
