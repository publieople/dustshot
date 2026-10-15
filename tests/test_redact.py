"""Sensitive-text detection: the patterns, the box mapping and the mask items."""

from __future__ import annotations

from catchlight.annotation.items import MosaicItem, RectItem
from catchlight.capture.base import Geometry
from catchlight.ocr import WordBox
from catchlight.redact import KINDS, Match, boxes, find_sensitive, mask_items


def word(text: str, x: int, y: int, line: int = 1001, width: int | None = None) -> WordBox:
    return WordBox(text=text, x=x, y=y, width=width or len(text) * 8, height=14, confidence=90.0, line=line)


def test_email_is_found_and_boxed() -> None:
    words = [word("contact:", 10, 20), word("po@example.com", 90, 20)]
    matches = find_sensitive(words)
    assert [match.kind for match in matches] == ["email"]
    assert matches[0].text == "po@example.com"
    assert matches[0].box == Geometry(90, 20, len("po@example.com") * 8, 14)


def test_multi_word_match_covers_every_word() -> None:
    words = [word("call", 10, 10), word("+86", 50, 10), word("13800138000", 90, 10)]
    matches = find_sensitive(words, kinds=("phone",))
    assert len(matches) == 1
    assert matches[0].box.x == 50
    assert matches[0].box.right == 90 + len("13800138000") * 8


def test_chinese_id_and_bank_card() -> None:
    id_matches = find_sensitive([word("11010519491231002X", 0, 0)], kinds=("id-card",))
    assert id_matches and id_matches[0].kind == "id-card"
    card = find_sensitive(
        [word("6222", 0, 0), word("0202", 40, 0), word("0202", 80, 0), word("0202", 120, 0)]
    )
    assert any(match.kind == "bank-card" for match in card)


def test_api_tokens_are_matched() -> None:
    matches = find_sensitive([word("ghp_abcdefghijklmnopqrstuvwxyz", 4, 4)], kinds=("secret",))
    assert matches and matches[0].text.startswith("ghp_")


def test_plain_text_is_left_alone() -> None:
    words = [
        word("The", 0, 0),
        word("sampling", 30, 0),
        word("rate", 90, 0),
        word("is", 120, 0),
        word("48", 140, 0),
    ]
    assert find_sensitive(words) == []


def test_matches_are_grouped_by_line() -> None:
    words = [
        word("a@b.co", 0, 0, line=1001),
        word("c@d.co", 0, 30, line=1002),
    ]
    matches = find_sensitive(words, kinds=("email",))
    assert [match.text for match in matches] == ["a@b.co", "c@d.co"]


def test_overlapping_matches_are_merged() -> None:
    duplicates = [
        Match("bank-card", "6222 0202 0202 0202", Geometry(0, 0, 120, 14)),
        Match("bank-card", "6222 0202 0202 0202", Geometry(0, 0, 120, 14)),
    ]
    assert len(find_sensitive([], kinds=(), detector=lambda words, kinds: duplicates)) == 1


def test_boxes_add_padding_and_stay_positive() -> None:
    padded = boxes([Match("email", "a@b.co", Geometry(0, 0, 20, 10))], padding=4)
    assert padded == [Geometry(-4, -4, 28, 18)]


def test_mask_items_use_the_requested_effect() -> None:
    items = mask_items(
        [Match("email", "a@b.co", Geometry(3, 5, 30, 10))], block=8, mode="blur", blur_radius=6
    )
    assert len(items) == 1
    item = items[0]
    assert (item.x, item.y, item.width, item.height) == (-1, 1, 38, 18)
    assert item.block == 8 and item.mode == "blur" and item.blur_radius == 6


def test_pattern_kinds_are_stable() -> None:
    assert KINDS == ("email", "id-card", "bank-card", "secret", "phone")


def test_solid_mode_returns_an_opaque_rectangle() -> None:
    items = mask_items([Match("email", "a@b.co", Geometry(10, 20, 40, 12))])
    assert len(items) == 1
    item = items[0]
    assert isinstance(item, RectItem)
    assert item.style.fill is True
    assert item.style.opacity == 1.0
    assert (item.x, item.y, item.width, item.height) == (6, 16, 48, 20)


def test_mosaic_mode_still_available() -> None:
    items = mask_items([Match("email", "a@b.co", Geometry(10, 20, 40, 12))], mode="mosaic", block=6)
    assert isinstance(items[0], MosaicItem)
    assert items[0].block == 6
