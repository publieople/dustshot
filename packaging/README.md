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

The Flatpak manifest builds Catchlight against the GNOME runtime and is tested on a live
niri session:

    flatpak-builder --user --install --force-clean build-dir packaging/io.github.catchlight.yml
    flatpak run io.github.catchlight doctor
    flatpak run io.github.catchlight full --dir ~/图片/flatpak-test --no-copy --no-editor

`runtime-version: '51'` is the newest GNOME runtime on Flathub (49, 50 and 51 are published).
The manifest bundles gtk4-layer-shell, grim and wl-clipboard from git, installs Pillow and
catchlight itself with pip, and installs the icons, the desktop entry and the AppStream
metadata; GTK 4, PyGObject and GStreamer come from the runtime. `appstream-compose` is off
because composing the catalogue here would need the network to mirror the remote screenshots,
which the build sandbox does not have; Flathub and `appstreamcli validate` compose it instead.

## What the sandbox changes

A sandboxed client reaches the compositor through a Wayland security context, and niri hides
every privileged protocol from it — `zwlr_screencopy_manager_v1` (so grim cannot capture) and
`zwlr_layer_shell_v1` (so overlays and pins become ordinary windows). What that means in
practice:

- `--backend auto` picks the ScreenCast portal inside a sandbox and grim outside it; an explicit
  `--backend grim` is still honoured. The manifest grants `xdg-run/pipewire-0`, which the portal
  needs to deliver frames.
- `catchlight doctor` reports the sandbox in its own row instead of listing grim as available.
- The tray item cannot own `org.kde.StatusNotifierItem-<pid>-1` (a sandbox only lets a process own
  names inside its own application id), so it falls back to
  `io.github.catchlight.StatusNotifierItem-<pid>-1`.
- `$HOME` is a private tmpfs: `--dir ~/Pictures/...` would disappear with the sandbox. The host
  Pictures directory is `~/图片` here (mapped by `--filesystem=xdg-pictures`), so save there.
- tesseract (OCR), zbar (barcodes) and wf-recorder (recording) are not bundled; doctor reports
  them as missing, and `catchlight ... --` helpers stay runnable from the host install.

## Verified

- `flatpak run io.github.catchlight full --dir ~/图片/flatpak-test --no-copy --no-editor` wrote a
  2560x1600 PNG that matches a host `grim` reference of the same desktop (0.0001 of the pixels
  differ by more than 7 levels).
- `... capture --backend portal --rect 100,100,400,300` saved a 500x375 PNG, the same rectangle
  and 1.25 output scale the host build produces.
- `catchlight doctor` inside the sandbox: grim, wl-copy, ffmpeg, the ScreenCast portal, GTK 4,
  gtk4-layer-shell (found under `/app/lib`) and the sandbox row are green; niri IPC, tesseract,
  the OCR language packs and the recording backend are reported as missing on purpose.
