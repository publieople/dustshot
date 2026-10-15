"""Translation support for the interface text.

The message catalogues live next to this module in
``locale/<language>/LC_MESSAGES/catchlight.mo`` and are looked up once per process by
:func:`install`.  Without a compiled catalogue every lookup returns the original message, so
the application keeps working in Chinese and the tests stay independent of the locale.
"""

from __future__ import annotations

import gettext
import os
import shutil
import subprocess
from pathlib import Path

DOMAIN = "catchlight"
LOCALE_DIR = Path(__file__).resolve().parent / "locale"
PROJECT_DIR = Path(__file__).resolve().parents[2]
PO_DIR = PROJECT_DIR / "po"
LANGUAGE_VARIABLE = "CATCHLIGHT_LANG"
LOCALE_VARIABLE = "CATCHLIGHT_LOCALEDIR"

_translation: gettext.NullTranslations = gettext.NullTranslations()


class TranslationError(RuntimeError):
    """Raised when a catalogue cannot be compiled."""


def locale_dir() -> Path:
    """Return the directory that holds the compiled catalogues."""

    override = os.environ.get(LOCALE_VARIABLE)
    return Path(override).expanduser() if override else LOCALE_DIR


def requested_languages(locale: str | None = None) -> list[str] | None:
    """Return the language preference, or None to let gettext read the environment."""

    if locale:
        return [locale]
    override = os.environ.get(LANGUAGE_VARIABLE)
    if override:
        return [piece for piece in override.replace(",", ":").split(":") if piece]
    return None


def translation(locale: str | None = None, localedir: str | Path | None = None) -> gettext.NullTranslations:
    """Load the catalogue for ``locale``, falling back to the original messages."""

    directory = Path(localedir) if localedir is not None else locale_dir()
    return gettext.translation(DOMAIN, str(directory), languages=requested_languages(locale), fallback=True)


def install(locale: str | None = None, localedir: str | Path | None = None) -> gettext.NullTranslations:
    """Activate a catalogue for this process and for every later ``_(...)`` call."""

    global _translation
    _translation = translation(locale, localedir)
    return _translation


def _(message: str) -> str:
    """Translate one message, returning it unchanged when no catalogue is loaded."""

    return _translation.gettext(message)


def ngettext(singular: str, plural: str, number: int) -> str:
    """Translate a plural form."""

    return _translation.ngettext(singular, plural, number)


def catalogue_path(language: str, localedir: str | Path | None = None) -> Path:
    """Return where the compiled catalogue for ``language`` belongs."""

    directory = Path(localedir) if localedir is not None else locale_dir()
    return directory / language / "LC_MESSAGES" / f"{DOMAIN}.mo"


def available(localedir: str | Path | None = None) -> list[str]:
    """Return the languages that ship a compiled catalogue, sorted."""

    directory = Path(localedir) if localedir is not None else locale_dir()
    if not directory.is_dir():
        return []
    return sorted(path.parent.parent.name for path in directory.glob(f"*/LC_MESSAGES/{DOMAIN}.mo"))


def compile_catalogs(podir: str | Path | None = None, localedir: str | Path | None = None) -> list[Path]:
    """Compile every ``po/*.po`` catalogue with msgfmt and return the written files."""

    msgfmt = shutil.which("msgfmt")
    if msgfmt is None:
        raise TranslationError(_("找不到 msgfmt：请安装 gettext"))
    source = Path(podir) if podir is not None else PO_DIR
    target = Path(localedir) if localedir is not None else locale_dir()
    written: list[Path] = []
    for po in sorted(source.glob("*.po")):
        destination = catalogue_path(po.stem, target)
        destination.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            [msgfmt, "--check", "-o", str(destination), str(po)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise TranslationError(
                _("msgfmt 失败（{catalog}）：{detail}").format(catalog=po.name, detail=result.stderr.strip())
            )
        written.append(destination)
    return written


def _main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="python3 -m catchlight.i18n", description=_("编译或列出翻译目录"))
    parser.add_argument("action", choices=("available", "compile"), nargs="?", default="available")
    args = parser.parse_args(argv)
    if args.action == "compile":
        for path in compile_catalogs():
            print(path)
        return 0
    print(" ".join(available()))
    return 0


# Importing this module installs the catalogue, so every module that uses ``_`` only
# has to import it to get translated text.
install()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
