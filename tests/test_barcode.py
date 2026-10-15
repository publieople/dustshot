"""Barcode decoding helpers."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from catchlight import barcode


def test_parse_output_reads_type_and_payload() -> None:
    payload = "QR-Code:https://example.com\nean13:1234567890128\n"
    codes = barcode.parse_output(payload)
    assert [(code.kind, code.text) for code in codes] == [
        ("QR-Code", "https://example.com"),
        ("ean13", "1234567890128"),
    ]


def test_parse_output_ignores_the_summary_line() -> None:
    payload = "\nscanned 0 barcode symbols\n"
    assert barcode.parse_output(payload) == []


def test_decode_requires_the_decoder(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(barcode.shutil, "which", lambda _name: None)
    with pytest.raises(barcode.BarcodeError):
        barcode.decode(Image.new("RGB", (8, 8)))


@pytest.mark.skipif(
    barcode.available() is False or shutil.which("qrencode") is None,
    reason="zbarimg and qrencode are required",
)
def test_decode_reads_a_generated_qr_code(tmp_path: Path) -> None:
    source = tmp_path / "qr.png"
    subprocess.run(
        ["qrencode", "-o", str(source), "-s", "6", "catchlight"],
        check=True,
        capture_output=True,
    )
    codes = barcode.decode_file(source)
    assert [code.text for code in codes] == ["catchlight"]
    assert codes[0].kind.lower().startswith("qr")
