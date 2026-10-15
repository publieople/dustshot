"""Tests for the gettext plumbing and the shipped catalogues."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from dustshot import i18n


def parse_catalogue(path: Path) -> dict[str, tuple[str, bool]]:
    """Return ``{msgid: (msgstr, fuzzy)}`` for a .po or .pot file."""

    entries: dict[str, tuple[str, bool]] = {}
    msgid: str | None = None
    msgstr: str | None = None
    fuzzy = False
    pending_fuzzy = False

    def flush() -> None:
        if msgid is not None:
            entries[msgid] = (msgstr or "", fuzzy)

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("#,"):
            pending_fuzzy = "fuzzy" in line
            continue
        if line.startswith("#"):
            continue
        if line.startswith("msgid "):
            flush()
            msgid, msgstr, fuzzy = json.loads(line[6:]), None, pending_fuzzy
            pending_fuzzy = False
            continue
        if line.startswith("msgstr "):
            msgstr = json.loads(line[7:])
            continue
        if line.startswith(chr(34)):
            piece = json.loads(line)
            if msgstr is None:
                msgid = (msgid or "") + piece
            else:
                msgstr += piece
    flush()
    return entries


@pytest.fixture(autouse=True)
def restore_translation():
    """Keep ``install`` calls from leaking into the other tests."""

    original = i18n._translation
    yield
    i18n._translation = original


def test_missing_catalogues_keep_the_original_text():
    translation = i18n.translation(locale="zz")
    assert translation.gettext("已清空历史记录") == "已清空历史记录"


def test_the_english_catalogue_is_available():
    assert "en" in i18n.available()


def test_the_english_catalogue_translates():
    translation = i18n.translation(locale="en")
    assert translation.gettext("已清空历史记录") == "History cleared"
    assert translation.gettext("找不到 zbarimg") == "找不到 zbarimg"


def test_install_switches_the_module_language(monkeypatch):
    monkeypatch.setenv(i18n.LANGUAGE_VARIABLE, "en")
    i18n.install()
    assert i18n._("已清空历史记录") == "History cleared"
    assert i18n.ngettext("{count} file", "{count} files", 2) == "{count} files"


def test_the_language_variable_wins_over_the_environment(monkeypatch):
    monkeypatch.setenv(i18n.LANGUAGE_VARIABLE, "en")
    i18n.install(locale="zz")
    assert i18n._("已清空历史记录") == "已清空历史记录"


def test_requested_languages_splits_the_override(monkeypatch):
    monkeypatch.setenv(i18n.LANGUAGE_VARIABLE, "en:de,fr")
    assert i18n.requested_languages() == ["en", "de", "fr"]
    assert i18n.requested_languages("ja") == ["ja"]


def test_locale_dir_follows_the_override(monkeypatch, tmp_path):
    monkeypatch.setenv(i18n.LOCALE_VARIABLE, str(tmp_path))
    assert i18n.locale_dir() == tmp_path
    assert i18n.catalogue_path("en") == tmp_path / "en" / "LC_MESSAGES" / "dustshot.mo"


def test_catalogue_path_defaults_to_the_package_directory():
    assert i18n.catalogue_path("en") == i18n.LOCALE_DIR / "en" / "LC_MESSAGES" / "dustshot.mo"


def test_the_template_and_the_catalogue_agree():
    template = parse_catalogue(i18n.PO_DIR / "dustshot.pot")
    catalogue = parse_catalogue(i18n.PO_DIR / "en.po")
    assert set(template) - {""} == set(catalogue) - {""}


def test_every_message_is_translated():
    catalogue = parse_catalogue(i18n.PO_DIR / "en.po")
    missing = [msgid for msgid, (msgstr, _fuzzy) in catalogue.items() if msgid and not msgstr.strip()]
    fuzzy = [msgid for msgid, (_msgstr, is_fuzzy) in catalogue.items() if msgid and is_fuzzy]
    assert missing == []
    assert fuzzy == []


def test_the_template_covers_the_interface():
    template = parse_catalogue(i18n.PO_DIR / "dustshot.pot")
    assert len(template) > 200
    assert "已保存：{path}" in template


def test_compile_catalogs_writes_a_mo_file(tmp_path):
    if shutil.which("msgfmt") is None:
        pytest.skip("msgfmt is not installed")
    written = i18n.compile_catalogs(podir=i18n.PO_DIR, localedir=tmp_path)
    assert written == [tmp_path / "en" / "LC_MESSAGES" / "dustshot.mo"]
    assert written[0].stat().st_size > 0


def test_main_lists_and_compiles(capsys, tmp_path, monkeypatch):
    if shutil.which("msgfmt") is None:
        pytest.skip("msgfmt is not installed")
    assert i18n._main([]) == 0
    assert "en" in capsys.readouterr().out
    monkeypatch.setenv(i18n.LOCALE_VARIABLE, str(tmp_path))
    assert i18n._main(["compile"]) == 0
    assert (tmp_path / "en" / "LC_MESSAGES" / "dustshot.mo").exists()


def test_compile_catalogs_reports_a_missing_msgfmt(monkeypatch):
    monkeypatch.setattr(i18n.shutil, "which", lambda _name: None)
    with pytest.raises(i18n.TranslationError):
        i18n.compile_catalogs()
