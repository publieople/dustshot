"""Text recognition through Tesseract.

Tesseract is treated as an optional external tool: the TSV output is parsed so
that word boxes are available for the overlay, and the plain text is rebuilt
from those boxes to keep a single process per recognition.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageOps


class OcrError(RuntimeError):
    """Raised when recognition cannot run."""


@dataclass
class WordBox:
    text: str
    x: int
    y: int
    width: int
    height: int
    confidence: float = 0.0
    line: int = 0

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    @property
    def box(self) -> tuple[int, int, int, int]:
        return (self.x, self.y, self.right, self.bottom)

    def center(self) -> tuple[int, int]:
        return (self.x + self.width // 2, self.y + self.height // 2)


@dataclass
class OcrResult:
    text: str = ""
    words: list[WordBox] = field(default_factory=list)
    languages: str = ""
    confidence: float = 0.0

    def is_empty(self) -> bool:
        return not self.text.strip()

    def lines(self) -> list[str]:
        return [line for line in self.text.splitlines() if line.strip()]


def tesseract_cmd(cmd: str = "tesseract") -> str | None:
    return shutil.which(cmd)


def tesseract_available(cmd: str = "tesseract") -> bool:
    return tesseract_cmd(cmd) is not None


def available_languages(cmd: str = "tesseract") -> list[str]:
    binary = tesseract_cmd(cmd)
    if not binary:
        return []
    try:
        result = subprocess.run([binary, "--list-langs"], capture_output=True, timeout=15.0, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return []
    lines = result.stdout.decode("utf-8", "replace").splitlines()
    return sorted(line.strip() for line in lines[1:] if line.strip())


def choose_languages(preferred: str, cmd: str = "tesseract") -> str:
    """Drop requested languages that are not installed."""

    installed = set(available_languages(cmd))
    if not installed:
        return preferred
    wanted = [part for part in preferred.replace(",", "+").split("+") if part]
    kept = [part for part in wanted if part in installed]
    if not kept:
        kept = [part for part in ("eng",) if part in installed] or sorted(installed)[:1]
    return "+".join(kept)


def preprocess(image: Image.Image, upscale: float = 2.0, grayscale: bool = True) -> Image.Image:
    prepared = image.convert("RGB")
    if upscale and upscale > 1.0:
        prepared = prepared.resize(
            (max(1, int(prepared.width * upscale)), max(1, int(prepared.height * upscale))),
            Image.LANCZOS,
        )
    if grayscale:
        prepared = ImageOps.autocontrast(ImageOps.grayscale(prepared)).convert("RGB")
    return prepared


def parse_tsv(payload: str) -> list[WordBox]:
    """Parse Tesseract TSV output into word boxes."""

    words: list[WordBox] = []
    lines = payload.splitlines()
    if not lines:
        return words
    header = lines[0].split("\t")
    try:
        index = {name: position for position, name in enumerate(header)}
    except AttributeError:
        return words

    def value(cells: list[str], name: str, default: str = "") -> str:
        position = index.get(name)
        if position is None or position >= len(cells):
            return default
        return cells[position]

    for raw in lines[1:]:
        cells = raw.split("\t")
        if len(cells) < len(header):
            continue
        text = value(cells, "text").strip()
        if not text:
            continue
        try:
            confidence = float(value(cells, "conf", "-1"))
        except ValueError:
            confidence = -1.0
        if confidence < 0:
            continue
        try:
            words.append(
                WordBox(
                    text=text,
                    x=int(value(cells, "left", "0")),
                    y=int(value(cells, "top", "0")),
                    width=int(value(cells, "width", "0")),
                    height=int(value(cells, "height", "0")),
                    confidence=confidence,
                    line=int(value(cells, "line_num", "0")) + 1000 * int(value(cells, "par_num", "0")),
                )
            )
        except ValueError:
            continue
    return words


def _is_cjk(char: str) -> bool:
    code = ord(char)
    return (
        0x3040 <= code <= 0x30FF
        or 0x3400 <= code <= 0x4DBF
        or 0x4E00 <= code <= 0x9FFF
        or 0xF900 <= code <= 0xFAFF
        or 0xFF00 <= code <= 0xFFEF
    )


def join_words(words: list[WordBox]) -> str:
    """Rebuild readable text, respecting CJK line breaking."""

    output: list[str] = []
    previous: WordBox | None = None
    for word in words:
        if previous is not None:
            if word.line != previous.line:
                output.append("\n")
            else:
                left = previous.text[-1:] if previous.text else ""
                right = word.text[:1]
                if not (_is_cjk(left) or _is_cjk(right)):
                    output.append(" ")
        output.append(word.text)
        previous = word
    return "".join(output)


def recognize(
    image: Image.Image,
    languages: str = "eng+chi_sim",
    cmd: str = "tesseract",
    psm: int = 6,
    upscale: float = 2.0,
    timeout: float = 120.0,
) -> OcrResult:
    """Run Tesseract over an image and return text plus word boxes."""

    binary = tesseract_cmd(cmd)
    if not binary:
        raise OcrError("tesseract is not installed; install it or set ocr.tesseract_cmd")
    lang = choose_languages(languages, cmd)
    prepared = preprocess(image, upscale=upscale)
    with tempfile.TemporaryDirectory(prefix="catchlight-ocr-") as workdir:
        source = Path(workdir) / "input.png"
        prepared.save(source)
        try:
            result = subprocess.run(
                [binary, str(source), "stdout", "-l", lang, "--psm", str(psm), "tsv"],
                capture_output=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise OcrError(f"tesseract timed out after {timeout:g}s") from exc
        except OSError as exc:
            raise OcrError(f"could not run tesseract: {exc}") from exc
    if result.returncode not in (0, 1):
        message = result.stderr.decode("utf-8", "replace").strip()
        raise OcrError(message or "tesseract failed")

    words = parse_tsv(result.stdout.decode("utf-8", "replace"))
    scale = upscale if upscale and upscale > 0 else 1.0
    if scale != 1.0:
        for word in words:
            word.x = round(word.x / scale)
            word.y = round(word.y / scale)
            word.width = max(1, round(word.width / scale))
            word.height = max(1, round(word.height / scale))
    confidence = sum(word.confidence for word in words) / len(words) if words else 0.0
    return OcrResult(text=join_words(words), words=words, languages=lang, confidence=confidence)
