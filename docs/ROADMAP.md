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

## M3 — Pinboard  (partial)

- done: floating layer-shell pin window, drag to move, scroll to zoom (0.15x - 4x), hover
  toolbar, copy / save / close, keyboard shortcuts, opacity and border from settings.
- planned: several pins at once, click-through, grouping, snapping to edges, per-pin opacity
  control in the UI.

## M4 — OCR and capture extras  (partial)

- done: tesseract CLI wrapper with TSV word boxes, language discovery, 2x upscale preprocess,
  `eng+chi_sim` default, editor OCR panel and the `catchlight ocr` command (`ocr.py`).
- planned: QR and barcode decoding, scrolling capture, automatic blur of detected sensitive text.

## M5 — Recording, integration, packaging  (partial)

- done: `wf-recorder` backend for a region or a whole output, wall-clock limit, GIF conversion
  through ffmpeg, a small recording control window, `catchlight doctor` diagnostics, hotkey
  templates for niri / Hyprland / Sway / GNOME / KDE, CI and release workflows.
- planned: tray icon, a browsable capture history, a ScreenCast-portal backend for compositors
  without wlr-screencopy, Flatpak packaging, translations.

## Deliberately out of scope

- Windows and macOS: the capture and overlay layers are Wayland specific.
- Cloud upload, accounts, telemetry: Catchlight never talks to the network.
- Any code, asset or file format taken from another screenshot utility; see
  docs/INDEPENDENCE.md for the clean-room statement.
