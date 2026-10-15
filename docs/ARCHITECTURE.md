# Architecture

Catchlight is split so that everything except `catchlight.ui` is importable without GTK. That is
what lets the test suite and CI run headless.

| Module | Responsibility |
| --- | --- |
| `catchlight/config.py` | `Settings` dataclasses, palette defaults, JSON store under XDG dirs |
| `catchlight/capture/base.py` | `Geometry`, `OutputInfo`, `Frame`; logical/physical scale maths |
| `catchlight/capture/screencopy.py` | output discovery (`niri msg`), frames (`grim`), region capture |
| `catchlight/selection.py` | the region state machine (new / move / resize, handles, clamping) |
| `catchlight/annotation/items.py` | item model, style, registry, JSON round-trip |
| `catchlight/annotation/render.py` | the Pillow renderer shared by GUI and tests |
| `catchlight/annotation/document.py` | one edited image: items, undo stack, hit testing, `.cln` |
| `catchlight/annotation/fonts.py` | `fc-match` font lookup with CJK fallbacks |
| `catchlight/output.py` | naming, unique paths, format handling, save directory resolution |
| `catchlight/clipboard.py` | `Gdk.Clipboard` when GTK is up, `wl-copy` / `wl-paste` otherwise |
| `catchlight/history.py` | the JSON capture index |
| `catchlight/ocr.py` | tesseract wrapper, TSV parsing, word grouping |
| `catchlight/record.py` | `wf-recorder` / `gpu-screen-recorder` backends, GIF conversion |
| `catchlight/ui/layer.py` | gtk4-layer-shell setup plus the `LD_PRELOAD` re-exec dance |
| `catchlight/ui/selector.py` | the full-screen region overlay |
| `catchlight/ui/canvas.py` | the annotation canvas (Pillow render + Cairo blit, live preview) |
| `catchlight/ui/editor.py` | the editor window: toolbar, palette, actions, OCR panel |
| `catchlight/ui/pin.py` | the floating pinned image |
| `catchlight/ui/app.py` | `Gtk.Application` that owns the windows for one CLI invocation |
| `catchlight/cli.py` | argparse front end for every command |

## Two implementation notes worth knowing

1. **`LD_PRELOAD` for layer-shell.** `gtk4-layer-shell` must be loaded before `libwayland`, so
   `ui/layer.py` re-executes the interpreter with `LD_PRELOAD` set when the library is not
   already active (`ensure_preload()`). Every entry point calls it before importing GTK.
2. **Pillow for rendering.** Annotations are composited with Pillow rather than Cairo so the same
   code path can be unit tested without a display; the GUI only blits the result through a
   `GdkPixbuf` and overlays the item that is currently being dragged.
