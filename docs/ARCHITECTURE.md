# Architecture

Dustshot is split so that everything except `dustshot.ui` is importable without GTK. That is
what lets the test suite and CI run headless.

| Module | Responsibility |
| --- | --- |
| `dustshot/config.py` | `Settings` dataclasses, palette defaults, JSON store under XDG dirs |
| `dustshot/capture/base.py` | `Geometry`, `OutputInfo`, `Frame`; logical/physical scale maths |
| `dustshot/capture/screencopy.py` | output discovery (`niri msg`), frames (`grim`), region capture |
| `dustshot/capture/niri.py` | niri's own screenshot picker: IPC request, file wait, clipboard fallback |
| `dustshot/capture/portal.py` | ScreenCast portal client and PipeWire frame grabbing |
| `dustshot/capture/edges.py` | window / control border detection for selection snapping |
| `dustshot/selection.py` | the region state machine (new / move / resize, handles, snapping, clamping) |
| `dustshot/annotation/items.py` | item model, style, registry, JSON round-trip |
| `dustshot/annotation/render.py` | the Pillow renderer shared by GUI and tests |
| `dustshot/annotation/document.py` | one edited image: items, undo stack, hit testing, `.cln` |
| `dustshot/annotation/fonts.py` | `fc-match` font lookup with CJK fallbacks |
| `dustshot/output.py` | naming, unique paths, format handling, save directory resolution |
| `dustshot/clipboard.py` | `Gdk.Clipboard` when GTK is up, `wl-copy` / `wl-paste` otherwise |
| `dustshot/history.py` | the JSON capture index |
| `dustshot/snap.py` | pure geometry helpers for edge and centre snapping |
| `dustshot/barcode.py` | `zbarimg` wrapper: output parsing, file and PIL-image decoding |
| `dustshot/ocr.py` | tesseract wrapper, TSV parsing, word grouping |
| `dustshot/redact.py` | sensitive text patterns, OCR word box grouping, masking items |
| `dustshot/scroll.py` | scrolling capture: row signatures, overlap detection, stitching |
| `dustshot/pinboard.py` | pin groups: shared move and zoom model |
| `dustshot/tray.py` | tray menu model and the SNI icon rendering |
| `dustshot/record.py` | `wf-recorder` / `gpu-screen-recorder` backends, GIF conversion |
| `dustshot/ui/layer.py` | gtk4-layer-shell setup plus the `LD_PRELOAD` re-exec dance |
| `dustshot/ui/selector.py` | the full-screen region overlay |
| `dustshot/ui/canvas.py` | the annotation canvas (Pillow render + Cairo blit, live preview, crop overlay) |
| `dustshot/ui/editor.py` | the editor window: toolbar, palette, actions, OCR panel |
| `dustshot/ui/pin.py` | the floating pinned image (snapping, click-through, opacity, link toggle, editor round-trip) |
| `dustshot/ui/tray.py` | StatusNotifierItem server and dbusmenu |
| `dustshot/ui/history_window.py` | the browsable capture history window |
| `dustshot/ui/app.py` | `Gtk.Application` that owns the windows for one CLI invocation |
| `dustshot/i18n.py` | gettext setup, the `_` helper and the compiled catalogues |
| `dustshot/cli.py` | argparse front end for every command |

## Two implementation notes worth knowing

1. **`LD_PRELOAD` for layer-shell.** `gtk4-layer-shell` must be loaded before `libwayland`, so
   `ui/layer.py` re-executes the interpreter with `LD_PRELOAD` set when the library is not
   already active (`ensure_preload()`). Every entry point calls it before importing GTK.
2. **Pillow for rendering.** Annotations are composited with Pillow rather than Cairo so the same
   code path can be unit tested without a display; the GUI only blits the result through a
   `GdkPixbuf` and overlays the item that is currently being dragged.
