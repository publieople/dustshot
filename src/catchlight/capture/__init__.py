"""Frame acquisition backends."""

from .base import Frame, Geometry, OutputInfo
from .screencopy import (
    CaptureError,
    capture_all,
    capture_output,
    capture_region,
    capture_region_from_frame,
    have_grim,
    have_niri,
    list_outputs,
    output_for_point,
    parse_outputs,
    pointer_position,
    primary_output,
    save_capture,
)

__all__ = [
    "CaptureError",
    "Frame",
    "Geometry",
    "OutputInfo",
    "capture_all",
    "capture_output",
    "capture_region",
    "capture_region_from_frame",
    "have_grim",
    "have_niri",
    "list_outputs",
    "output_for_point",
    "parse_outputs",
    "pointer_position",
    "primary_output",
    "save_capture",
]
