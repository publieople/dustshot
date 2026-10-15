"""Capture backend based on the wlr-screencopy protocol (grim) plus niri introspection.

Two small command line tools are used:

* niri msg outputs - to learn output names, logical geometry and scale factors
* grim             - to grab pixels (wlr-screencopy), either the whole desktop,
                     one output, or an arbitrary logical region

The compositor side is deliberately kept behind this module so that a
portal/PipeWire backend can be added later without touching the UI.
"""

from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path

from PIL import Image

from .base import Frame, Geometry, OutputInfo


class CaptureError(RuntimeError):
    """Raised when a capture could not be produced."""


def grim_path() -> str:
    return os.environ.get("CATCHLIGHT_GRIM", "grim")


def niri_path() -> str:
    return os.environ.get("CATCHLIGHT_NIRI", "niri")


def have_grim() -> bool:
    return shutil.which(grim_path()) is not None


def have_niri() -> bool:
    return shutil.which(niri_path()) is not None


def _run(cmd: Sequence[str], timeout: float = 30.0) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(cmd, capture_output=True, timeout=timeout, check=False)
    except FileNotFoundError as exc:  # pragma: no cover - depends on host tooling
        raise CaptureError(f"required tool not found: {cmd[0]}") from exc
    except subprocess.TimeoutExpired as exc:  # pragma: no cover
        raise CaptureError(f"{cmd[0]} timed out after {timeout}s") from exc


_OUTPUT_RE = re.compile(r'^Output "(?P<desc>.*)" \((?P<name>[^)]+)\)$')


def parse_outputs(text: str) -> list[OutputInfo]:
    """Parse the human readable output of niri msg outputs.

    Kept separate from the process call so it can be unit tested with a fixture.
    """

    outputs: list[OutputInfo] = []
    current: dict[str, object] | None = None

    def flush() -> None:
        if not current:
            return
        logical = current.get("logical")
        if not isinstance(logical, Geometry):
            return
        scale = float(current.get("scale") or 1.0)
        physical = Geometry(0, 0, round(logical.width * scale), round(logical.height * scale))
        outputs.append(
            OutputInfo(
                name=str(current.get("name", "")),
                description=str(current.get("desc", "")),
                logical=logical,
                scale=scale,
                physical=physical,
            )
        )

    for raw_line in text.splitlines():
        line = raw_line.strip()
        match = _OUTPUT_RE.match(line)
        if match:
            flush()
            current = {"name": match.group("name"), "desc": match.group("desc")}
            continue
        if current is None:
            continue
        if line.startswith("Logical position:"):
            values = line.split(":", 1)[1]
            x_text, _, y_text = values.partition(",")
            current["logical_pos"] = (int(x_text.strip()), int(y_text.strip()))
        elif line.startswith("Logical size:"):
            width_text, _, height_text = line.split(":", 1)[1].partition("x")
            position = current.get("logical_pos") or (0, 0)
            current["logical"] = Geometry(
                position[0], position[1], int(width_text.strip()), int(height_text.strip())
            )
        elif line.startswith("Scale:"):
            current["scale"] = float(line.split(":", 1)[1].strip())

    flush()

    if outputs:
        first = outputs[0]
        outputs[0] = OutputInfo(
            name=first.name,
            description=first.description,
            logical=first.logical,
            scale=first.scale,
            physical=first.physical,
            primary=True,
        )
    return outputs


def list_outputs() -> list[OutputInfo]:
    """Return the outputs reported by niri, or raise CaptureError."""

    if not have_niri():
        raise CaptureError("niri is not installed; cannot enumerate outputs")
    result = _run([niri_path(), "msg", "outputs"])
    if result.returncode != 0:
        message = result.stderr.decode("utf-8", "replace").strip()
        raise CaptureError(message or "niri msg outputs failed")
    outputs = parse_outputs(result.stdout.decode("utf-8", "replace"))
    if not outputs:
        raise CaptureError("niri reported no usable outputs")
    return outputs


def primary_output() -> OutputInfo:
    outputs = list_outputs()
    return next((o for o in outputs if o.primary), outputs[0])


def output_for_point(point: tuple[int, int] | None) -> OutputInfo:
    """Return the output containing a logical point, falling back to primary."""

    outputs = list_outputs()
    if point is not None:
        for output in outputs:
            if output.logical.contains_point(point[0], point[1]):
                return output
    return next((o for o in outputs if o.primary), outputs[0])


_POINTER_SUPPORTED: bool | None = None


def pointer_position() -> tuple[int, int] | None:
    """Best effort logical pointer position in compositor coordinates.

    niri has no pointer query (its msg subcommands expose outputs, windows and
    interactive pickers only), so this returns None there and callers must fall
    back to the cursor tracked by the overlay itself. The probe result is cached
    because callers may ask on every frame.
    """

    global _POINTER_SUPPORTED
    if not have_niri():
        return None
    if _POINTER_SUPPORTED is False:
        return None
    result = _run([niri_path(), "msg", "--json", "pointer"])
    if result.returncode != 0:
        _POINTER_SUPPORTED = False
        return None
    _POINTER_SUPPORTED = True
    try:
        import json

        payload = json.loads(result.stdout.decode("utf-8", "replace"))
    except ValueError:
        return None
    if isinstance(payload, dict):
        x = payload.get("x")
        y = payload.get("y")
        if isinstance(x, int) and isinstance(y, int):
            return (x, y)
    return None


def _decode_png(payload: bytes) -> Image.Image:
    if not payload:
        raise CaptureError("capture backend returned no data")
    try:
        return Image.open(io.BytesIO(payload)).convert("RGB")
    except Exception as exc:  # pragma: no cover - depends on backend output
        raise CaptureError(f"could not decode captured image: {exc}") from exc


def _grim_stdout(args: Sequence[str]) -> Image.Image:
    if not have_grim():
        raise CaptureError("grim is not installed; install it or set CATCHLIGHT_GRIM")
    result = _run([grim_path(), *args, "-"])
    if result.returncode != 0:
        message = result.stderr.decode("utf-8", "replace").strip()
        raise CaptureError(message or "grim failed")
    return _decode_png(result.stdout)


def capture_output(output: OutputInfo | None = None) -> Frame:
    """Capture one output at native resolution."""

    info = output or primary_output()
    image = _grim_stdout(["-o", info.name])
    refreshed = OutputInfo(
        name=info.name,
        description=info.description,
        logical=info.logical,
        scale=info.scale,
        physical=Geometry(0, 0, image.width, image.height),
        primary=info.primary,
    )
    return Frame(image=image, output=refreshed)


def capture_all() -> Image.Image:
    """Capture every output stitched into one desktop sized image."""

    return _grim_stdout([])


def capture_region(region: Geometry) -> Image.Image:
    """Capture an arbitrary logical region straight from the compositor."""

    if region.is_empty():
        raise ValueError("cannot capture an empty region")
    return _grim_stdout(["-g", region.as_grim_geometry()])


def capture_region_from_frame(frame: Frame, region: Geometry) -> Image.Image:
    """Crop an already captured frame instead of grabbing the screen again."""

    return frame.crop_logical(region)


def save_capture(image: Image.Image, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
    return path
