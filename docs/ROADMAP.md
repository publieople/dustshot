# Roadmap

Dustshot is built in six milestones. This file records what each one covers, how far it has
come, and what is deliberately left out. Status legend: **done**, **partial**, **planned**.

## M0 — Foundations  (done)

- src-layout package with a `dustshot` console entry point (`pyproject.toml`).
- Typed settings store in `~/.config/dustshot/config.json`; unknown keys survive a reload so
  newer or older builds do not destroy each other's options (`config.py`).
- Geometry / output model with per-output scale (logical vs physical pixels) shared by every
  other module (`capture/base.py`).
- Capture backend over wlr-screencopy: output discovery through `niri msg --json outputs`, frames
  through `grim` (`capture/screencopy.py`).
- History index in `~/.local/share/dustshot/history.json`, capped at 500 entries (`history.py`).

## M1 — Region capture  (done)

- One layer-shell overlay window per output on the `overlay` layer, keyboard-exclusive
  (`ui/selector.py`).
- Frozen backdrop, dim outside the selection, eight resize handles, live size label.
- Magnifier with colour probe, crosshair, arrow-key nudging (Shift = 10 px), Space / Ctrl+A
  select-all, last region restored on the next run.
- Enter = save + copy, Ctrl+C = copy only, Ctrl+S = save only, Ctrl+R = hand the region to the
  recorder, Esc / right click = cancel.
- done: snapping to the windows and controls behind the overlay. The borders of the frozen frame are
  found by projecting edge energy onto both axes (capture/edges.py), so a dragged or nudged side
  lands on the nearest border within 12 px without asking the compositor for window geometry — which
  a Flatpak client cannot do. Alt suspends snapping for the current drag.

## M2 — Annotation editor  (done)

- One Pillow renderer used by both the GUI and the headless tests: rectangle, ellipse, line,
  arrow, pen, highlighter, text, serial numbers, mosaic and blur (`annotation/render.py`).
- Snapshot undo/redo, hit testing, move and resize of the selected item, per-tool widths, a
  ten-colour palette, CJK-aware font resolution (`annotation/fonts.py`).
- Save, copy, pin or OCR straight from the editor; projects round-trip through a `.cln` file
  (a zip holding `annotations.json` and `image.png`).
- done: crop and rotation. The crop tool marks the box to keep (Enter applies it, Esc drops it) and
  Ctrl+Left / Ctrl+Right rotate the picture in 90° steps; both go through the same snapshot undo
  stack as the annotations and keep the item coordinates in step (annotation/document.py).

## M3 — Pinboard  (done)

- done: floating layer-shell pin window, drag to move, scroll to zoom (0.15x - 4x), hover
  toolbar, copy / save / close, keyboard shortcuts, opacity and border from settings.
- done: several pins at once (DustshotApp.spawn_pin), pin-again from the toolbar or the editor,
  edge and centre snapping while dragging (snap.py), a centre button, click-through (only the
  hover toolbar stays clickable) and a per-pin opacity slider.
- done: a pin can be sent back into the editor: the 编辑 button or Ctrl+E reopens it in the
  annotation editor, and the rendered picture replaces the pin at the same zoom when the editor
  closes; a result that arrives after the pin was closed is dropped.
- done: pin groups (pinboard.py): the link toggle (联动) ties two or more pins together
  so they share every drag and every zoom step, a group that drops below two members is
  dissolved again, and grouped members are clamped to the output they sit on.

## M4 — OCR and capture extras  (done)

- done: tesseract CLI wrapper with TSV word boxes, language discovery, 2x upscale preprocess,
  `eng+chi_sim` default, editor OCR panel and the `dustshot ocr` command (`ocr.py`).
- done: QR and barcode decoding through zbarimg (barcode.py, the dustshot codes command, text
  or JSON output, region capture when no file is given).
- done: sensitive text detection (redact.py): email, phone, ID card, bank card and API key
  patterns over OCR word boxes, opaque or mosaic or blur masking, `dustshot redact` command
  and an editor toolbar button.
- done: scrolling capture (scroll.py): row-signature overlap detection, seamless vertical
  stitching, wtype / ydotool auto-advance, a manual mode, and a guard that reports a screen
  that never moved. Verified on a live niri session against a 2048x6000 page.

## M5 — Recording, integration, packaging  (done)

- done: `wf-recorder` backend for a region or a whole output, wall-clock limit, GIF conversion
  through ffmpeg, a small recording control window, `dustshot doctor` diagnostics, hotkey
  templates for niri / Hyprland / Sway / GNOME / KDE, CI and release workflows.
- done: a browsable capture history window (dustshot history --gui) with thumbnails and
  edit / copy / pin / open-folder / delete actions per entry.
- done: desktop integration assets in `packaging/` — a desktop entry with region / full /
  record / OCR / history actions, AppStream metadata (validated with appstreamcli) and icons,
  plus a starting Flatpak manifest that CI cannot build because capture needs a live session.
- done: `dustshot tray` publishes a StatusNotifierItem icon with a dbusmenu (region / full
  capture, recording, history, quit) and spawns the matching CLI command per row; the menu model and
  the icon are unit-tested and the D-Bus server has cross-process tests (`dbus-run-session`).
- done: a ScreenCast-portal backend (capture/portal.py) for compositors without wlr-screencopy:
  the CreateSession / SelectSources / Start / OpenPipeWireRemote dance, one PipeWire stream per
  shared monitor read through GStreamer, and `--backend auto|grim|portal` on every capture command
  plus a `dustshot doctor` row. Compositors that only publish DMA-BUF streams (niri) fail the
  plain `videoconvert` pipeline, so a GL import pipeline is tried second. Verified on a live niri
  session: a 2560x1600 PNG that matches `grim` on a static desktop (0.6% of pixels differ, mostly
  the clock), with the D-Bus dance covered by cross-process tests under `dbus-run-session`.
- done: translations (i18n.py): every interface string goes through gettext, `po/dustshot.pot`
  carries 294 messages, the English catalogue is fully translated and compiled into
  `src/dustshot/locale/en/LC_MESSAGES/dustshot.mo` (shipped as package data), and
  `DUSTSHOT_LANG` / `DUSTSHOT_LOCALEDIR` drive the lookup, with tests for the catalogue
  completeness and the `python3 -m dustshot.i18n compile` tool.
- done: a tested Flatpak build (`packaging/io.github.publieople.Dustshot.yml`, GNOME runtime 51): the
  manifest bundles gtk4-layer-shell, grim and wl-clipboard from git, installs Pillow and
  dustshot with pip and ships the desktop entry, the AppStream metadata and the icon sizes. A
  sandboxed client connects through a Wayland security context, so niri hides wlr-screencopy and
  wlr-layer-shell from it — `--backend auto` picks the ScreenCast portal there, overlays and pins
  fall back to ordinary windows, the tray item falls back to a bus name under the application id,
  and OCR / recording stay on the host install. Verified on a live niri session: a 2560x1600
  full-screen PNG and a 400x300 region capture taken from the sandbox match the host `grim`
  output, and `dustshot doctor` reports the sandbox. The default save directory follows the host
  XDG pictures folder (the manifest grants `xdg-config/user-dirs.dirs` read-only, since a sandbox
  home is private and would otherwise swallow every default capture).

## Deliberately out of scope

- Windows and macOS: the capture and overlay layers are Wayland specific.
- Binding a pin to one specific window: pins already sit on the layer-shell overlay layer above
  every window, and the layer protocol cannot attach a surface to another window.
- Cloud upload, accounts, telemetry: Dustshot never talks to the network.
- Any code, asset or file format taken from another screenshot utility; see
  docs/INDEPENDENCE.md for the clean-room statement.
