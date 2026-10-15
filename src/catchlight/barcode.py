"""Barcode and QR decoding through the zbar command line tool (zbarimg)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from .i18n import _

DEFAULT_COMMAND = "zbarimg"
NOTHING_FOUND = 4


class BarcodeError(RuntimeError):
    """Raised when the decoder is missing or fails unexpectedly."""


@dataclass(slots=True)
class Code:
    """One decoded symbol."""

    text: str
    kind: str = ""
    path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"text": self.text, "type": self.kind, "path": self.path}


def command_path(command: str = DEFAULT_COMMAND) -> str | None:
    """Return the decoder path, or None when it is not installed."""

    return shutil.which(command)


def available(command: str = DEFAULT_COMMAND) -> bool:
    return command_path(command) is not None


def parse_output(payload: str) -> list[Code]:
    """Parse zbarimg default output, one TYPE:payload line per symbol."""

    codes: list[Code] = []
    for raw in payload.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("scanned ") and line.endswith("barcode symbols"):
            continue
        kind, separator, text = line.partition(":")
        if not separator or not text:
            continue
        codes.append(Code(text=text, kind=kind.strip()))
    return codes


def decode_file(
    path: str | Path,
    command: str = DEFAULT_COMMAND,
    timeout: int = 60,
    extra_args: tuple[str, ...] = (),
) -> list[Code]:
    """Decode every symbol in one image file."""

    binary = command_path(command)
    if binary is None:
        raise BarcodeError(_("未找到 zbarimg，请安装 zbar"))
    args = [binary, "--quiet", "--nodbus", *extra_args, str(path)]
    try:
        completed = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
    except OSError as exc:
        raise BarcodeError(str(exc)) from None
    except subprocess.TimeoutExpired:
        raise BarcodeError(_("解码超时")) from None
    if completed.returncode not in (0, NOTHING_FOUND):
        message = completed.stderr.strip() or _("zbarimg 退出码 {returncode}").format(
            returncode=completed.returncode
        )
        raise BarcodeError(message)
    codes = parse_output(completed.stdout)
    for code in codes:
        code.path = str(path)
    return codes


def decode(image: Image.Image, command: str = DEFAULT_COMMAND, timeout: int = 60) -> list[Code]:
    """Decode every symbol in a Pillow image."""

    with tempfile.TemporaryDirectory(prefix="catchlight-barcode-") as directory:
        target = Path(directory) / "input.png"
        image.convert("RGB").save(target)
        return decode_file(target, command=command, timeout=timeout)
