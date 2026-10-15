# Roadmap

Catchlight is built in six milestones. This file records what each one covers, how far it has
come, and what is deliberately left out. Status legend: **done**, **partial**, **planned**.

## M0 — Foundations  (done)

- src-layout package with a `catchlight` console entry point (`pyproject.toml`).
- Typed settings store in `~/.config/catchlight/config.json`; unknown keys survive a reload so
  newer or older builds do not destroy each other's options (`config.py`).
- Geometry / output model with per-output scale (logical vs physical pixels) shared by every
  other module (`capture/base.py`).
- Capture backend over wlr-screencopy: output discovery through `niri msg --json outputs`, frames
  through `grim` (`capture/screencopy.py`).
- History index in `~/.local/share/catchlight/history.json`, capped at 500 entries (`history.py`).

## M1 — Region capture  (done)

- One layer-shell overlay window per output on the `overlay` layer, keyboard-exclusive
  (`ui/selector.py`).
- Frozen backdrop, dim outside the selection, eight resize handles, live size label.
- Magnifier with colour probe, crosshair, arrow-key nudging (Shift = 10 px), Space / Ctrl+A
  select-all, last region restored on the next run.
- Enter = save + copy, Ctrl+C = copy only, Ctrl+S = save only, Ctrl+R = hand the region to the
  recorder, Esc / right click = cancel.

## M2 — Annotation editor  (done)

- One Pillow renderer used by both the GUI and the headless tests: rectangle, ellipse, line,
  arrow, pen, highlighter, text, serial numbers, mosaic and blur (`annotation/render.py`).
- Snapshot undo/redo, hit testing, move and resize of the selected item, per-tool widths, a
  ten-colour palette, CJK-aware font resolution (`annotation/fonts.py`).
- Save, copy, pin or OCR straight from the editor; projects round-trip through a `.cln` file
  (a zip holding `annotations.json` and `image.png`).

## M3 — Pinboard  (done)

- done: floating layer-shell pin window, drag to move, scroll to zoom (0.15x - 4x), hover
  toolbar, copy / save / close, keyboard shortcuts, opacity and border from settings.
- done: several pins at once (CatchlightApp.spawn_pin), pin-again from the toolbar or the editor,
  edge and centre snapping while dragging (snap.py), a centre button, click-through (only the
  hover toolbar stays clickable) and a per-pin opacity slider.
- done: pin groups (pinboard.py): the link toggle (联动) ties two or more pins together
  so they share every drag and every zoom step, a group that drops below two members is
  dissolved again, and grouped members are clamped to the output they sit on.

## M4 — OCR and capture extras  (done)

- done: tesseract CLI wrapper with TSV word boxes, language discovery, 2x upscale preprocess,
  `eng+chi_sim` default, editor OCR panel and the `catchlight ocr` command (`ocr.py`).
- done: QR and barcode decoding through zbarimg (barcode.py, the catchlight codes command, text
  or JSON output, region capture when no file is given).
- done: sensitive text detection (redact.py): email, phone, ID card, bank card and API key
  patterns over OCR word boxes, opaque or mosaic or blur masking, `catchlight redact` command
  and an editor toolbar button.
- done: scrolling capture (scroll.py): row-signature overlap detection, seamless vertical
  stitching, wtype / ydotool auto-advance, a manual mode, and a guard that reports a screen
  that never moved. Verified on a live niri session against a 2048x6000 page.

## M5 — Recording, integration, packaging  (partial)

- done: `wf-recorder` backend for a region or a whole output, wall-clock limit, GIF conversion
  through ffmpeg, a small recording control window, `catchlight doctor` diagnostics, hotkey
  templates for niri / Hyprland / Sway / GNOME / KDE, CI and release workflows.
- done: a browsable capture history window (catchlight history --gui) with thumbnails and
  edit / copy / pin / open-folder / delete actions per entry.
- done: desktop integration assets in `packaging/` — a desktop entry with region / full /
  record / OCR / history actions, AppStream metadata (validated with appstreamcli) and icons,
  plus a starting Flatpak manifest that CI cannot build because capture needs a live session.
- done: `catchlight tray` publishes a StatusNotifierItem icon with a dbusmenu (region / full
  capture, recording, history, quit) and spawns the matching CLI command per row; the menu model and
  the icon are unit-tested and the D-Bus server has cross-process tests (`dbus-run-session`).
- done: a ScreenCast-portal backend (capture/portal.py) for compositors without wlr-screencopy:
  the CreateSession / SelectSources / Start / OpenPipeWireRemote dance, one PipeWire stream per
  shared monitor read through GStreamer, and `--backend auto|grim|portal` on every capture command
  plus a `catchlight doctor` row. Compositors that only publish DMA-BUF streams (niri) fail the
  plain `videoconvert` pipeline, so a GL import pipeline is tried second. Verified on a live niri
  session: a 2560x1600 PNG that matches `grim` on a static desktop (0.6% of pixels differ, mostly
  the clock), with the D-Bus dance covered by cross-process tests under `dbus-run-session`.
- planned: a tested Flatpak build, translations.

## Deliberately out of scope

- Windows and macOS: the capture and overlay layers are Wayland specific.
- Binding a pin to one specific window: pins already sit on the layer-shell overlay layer above
  every window, and the layer protocol cannot attach a surface to another window.
- Cloud upload, accounts, telemetry: Catchlight never talks to the network.
- Any code, asset or file format taken from another screenshot utility; see
  docs/INDEPENDENCE.md for the clean-room statement.
