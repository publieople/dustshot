# Packaging assets

Static desktop-integration files for Catchlight.

| File | Purpose |
| --- | --- |
| `io.github.catchlight.desktop` | desktop entry with region / full / record / OCR / history actions |
| `io.github.catchlight.metainfo.xml` | AppStream metadata used by software centres |
| `icons/hicolor/*/apps/io.github.catchlight.png` | application icon |
| `io.github.catchlight.yml` | Flatpak manifest |

Install the desktop entry, the metadata and the icon for the current user:

    install -Dm644 packaging/io.github.catchlight.desktop ~/.local/share/applications/io.github.catchlight.desktop
    install -Dm644 packaging/io.github.catchlight.metainfo.xml ~/.local/share/metainfo/io.github.catchlight.metainfo.xml
    cp -r packaging/icons/hicolor ~/.local/share/icons/

The Flatpak manifest is a starting point and has not been built here: it needs the
gtk4-layer-shell module, and the GNOME runtime already ships PyGObject and pycairo.
Build it from the repository root with:

    flatpak-builder --user --install --force-clean build-dir packaging/io.github.catchlight.yml
