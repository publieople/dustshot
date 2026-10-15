"""Spot private text in a capture and turn it into masking items."""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from .annotation.items import Item, MosaicItem, RectItem, Style
from .capture.base import Geometry
from .ocr import WordBox

PADDING = 4

# Deliberately conservative patterns: a false positive only costs a painted-over word, while a
# false negative leaks the very thing this feature exists for.
PATTERNS: dict[str, re.Pattern[str]] = {
    "email": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+"),
    "phone": re.compile(r"(?<!\d)\+?\d[\d\s().-]{6,}\d(?!\d)"),
    "id-card": re.compile(r"(?<![\dXx])\d{17}[\dXx](?![\dXx])"),
    "bank-card": re.compile(r"(?<!\d)\d{4}(?:[ -]?\d{4}){3,4}(?!\d)"),
    "secret": re.compile(r"(?:sk|pk|ghp|gho|ghs|AKIA|xox[baprs])[-_A-Za-z0-9]{12,}"),
}

# Most specific first: a long digit run is a card number before it is a phone number, and
# _deduplicate keeps the first label when two patterns cover the same words.
KINDS = ("email", "id-card", "bank-card", "secret", "phone")


@dataclass(slots=True)
class Match:
    kind: str
    text: str
    box: Geometry

    def to_dict(self) -> dict[str, object]:
        return {"kind": self.kind, "text": self.text, "box": self.box.as_tuple()}


def _word_box(word: WordBox) -> Geometry:
    return Geometry(word.x, word.y, word.width, word.height)


def _union(boxes: Iterable[Geometry]) -> Geometry:
    boxes = list(boxes)
    left = min(box.x for box in boxes)
    top = min(box.y for box in boxes)
    right = max(box.right for box in boxes)
    bottom = max(box.bottom for box in boxes)
    return Geometry(left, top, right - left, bottom - top)


def _line_text(words: Sequence[WordBox]) -> tuple[str, list[tuple[int, WordBox]]]:
    parts: list[str] = []
    spans: list[tuple[int, WordBox]] = []
    offset = 0
    for word in words:
        parts.append(word.text)
        spans.append((offset, word))
        offset += len(word.text) + 1
    return " ".join(parts), spans


def _covering_words(spans: list[tuple[int, WordBox]], start: int, end: int) -> list[WordBox]:
    covered = []
    for offset, word in spans:
        stop = offset + len(word.text)
        if offset < end and stop > start:
            covered.append(word)
    return covered


def _find_in_line(words: Sequence[WordBox], kinds: Sequence[str]) -> list[Match]:
    text, spans = _line_text(words)
    found: list[Match] = []
    for kind in kinds:
        pattern = PATTERNS[kind]
        for hit in pattern.finditer(text):
            covered = _covering_words(spans, hit.start(), hit.end())
            if not covered:
                continue
            found.append(Match(kind, hit.group(0), _union(_word_box(word) for word in covered)))
    return found


def find_sensitive(
    words: Sequence[WordBox],
    kinds: Sequence[str] = KINDS,
    detector=None,
) -> list[Match]:
    """Return one match per sensitive run, grouped by OCR line."""
    grouped: dict[int, list[WordBox]] = {}
    for word in words:
        if not word.text.strip():
            continue
        grouped.setdefault(word.line, []).append(word)

    matches: list[Match] = []
    for key in sorted(grouped):
        line_words = sorted(grouped[key], key=lambda word: word.x)
        matches.extend(_find_in_line(line_words, kinds))
    if detector is not None:
        matches.extend(detector(words, list(kinds)))
    return _deduplicate(matches)


def _deduplicate(matches: Sequence[Match]) -> list[Match]:
    kept: list[Match] = []
    for match in matches:
        for other in kept:
            same_spot = other.box.intersects(match.box)
            nested = other.text in match.text or match.text in other.text
            if same_spot and nested:
                if len(other.text) < len(match.text):
                    kept[kept.index(other)] = match
                break
        else:
            kept.append(match)
    return kept


def boxes(matches: Iterable[Match], padding: int = PADDING) -> list[Geometry]:
    result = []
    for match in matches:
        result.append(
            Geometry(
                match.box.x - padding,
                match.box.y - padding,
                match.box.width + 2 * padding,
                match.box.height + 2 * padding,
            )
        )
    return result


def mask_items(
    matches: Sequence[Match],
    block: int = 8,
    mode: str = "solid",
    blur_radius: int = 12,
    padding: int = PADDING,
    color: str = "#101114",
) -> list[Item]:
    """Build one masking item per match; the caller adds them to a document.

    The default mode paints an opaque block, the only effect guaranteed to remove the text.
    The softer mosaic and blur effects stay available for captures that are shared on purpose.
    """
    items: list[Item] = []
    for box in boxes(matches, padding=padding):
        width = max(2, box.width)
        height = max(2, box.height)
        if mode == "solid":
            style = Style(color=color, width=1, fill=True, opacity=1.0, solid=True)
            items.append(RectItem(style=style, x=box.x, y=box.y, width=width, height=height))
        else:
            items.append(
                MosaicItem(
                    x=box.x,
                    y=box.y,
                    width=width,
                    height=height,
                    block=block,
                    mode=mode,
                    blur_radius=blur_radius,
                )
            )
    return items
