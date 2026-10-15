"""Tesseract helpers that do not need the binary."""

from __future__ import annotations

import shutil

import pytest
from PIL import Image

from dustshot import ocr

TSV = "\t".join(
    [
        "level",
        "page_num",
        "block_num",
        "par_num",
        "line_num",
        "word_num",
        "left",
        "top",
        "width",
        "height",
        "conf",
        "text",
    ]
)
ROWS = [
    ["5", "1", "1", "1", "1", "1", "10", "20", "30", "12", "95.5", "Hello"],
    ["5", "1", "1", "1", "1", "2", "50", "20", "40", "12", "88.0", "world"],
    ["5", "1", "1", "1", "2", "1", "10", "40", "30", "12", "91.0", "第二行"],
]


def payload() -> str:
    return "\n".join([TSV] + ["\t".join(row) for row in ROWS])


def test_parse_tsv_reads_words() -> None:
    words = ocr.parse_tsv(payload())
    assert [word.text for word in words] == ["Hello", "world", "第二行"]
    assert words[0].x == 10
    assert words[0].width == 30
    assert words[0].confidence == pytest.approx(95.5)
    assert words[0].line == words[1].line
    assert words[2].line != words[0].line


def test_parse_tsv_skips_low_confidence_and_empty() -> None:
    rows = [*ROWS, ["5", "1", "1", "1", "3", "1", "0", "0", "1", "1", "-1", ""]]
    text = "\n".join([TSV] + ["\t".join(row) for row in rows])
    words = ocr.parse_tsv(text)
    assert len(words) == 3


def test_join_words_groups_lines_without_cjk_spaces() -> None:
    words = ocr.parse_tsv(payload())
    assert ocr.join_words(words) == "Hello world\n第二行"


def test_parse_tsv_handles_empty_payload() -> None:
    assert ocr.parse_tsv("") == []


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract is not installed")
def test_recognize_runs_when_available() -> None:
    image = Image.new("RGB", (200, 60), (255, 255, 255))
    result = ocr.recognize(image, languages="eng")
    assert isinstance(result, ocr.OcrResult)
