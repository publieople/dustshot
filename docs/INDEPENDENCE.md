# Independent implementation statement

Dustshot is an independent, clean-room implementation. It was written from public Wayland
and GTK documentation plus the protocol descriptions listed below. No third-party screenshot
utility's source code, binary, resources, translations, icon set or file format was copied,
decompiled or transcribed, and no compatibility layer for another tool's private formats is
provided.

## What it is built on

- **wlr-screencopy**, the public wlroots protocol, used through the `grim` command line client.
- **wlr-layer-shell**, the public protocol for panels, overlays and wallpapers, used through
  `gtk4-layer-shell`.
- **GTK 4** and **Pillow** for the interface and the raster renderer.
- **tesseract**, **ffmpeg**, **wf-recorder** and **wl-clipboard** as ordinary command line
  dependencies, invoked through their documented interfaces.
- Compositor IPC (`niri msg --json ...`) only where a compositor documents it.

## Naming and branding

The name `Dustshot`, the identifiers `io.github.publieople.Dustshot.*`, the window namespaces
`dustshot` / `dustshot-pin` and every icon and string in this repository are original. No
third-party product name, logo or trademark is used to describe this software, and this project
is not affiliated with, endorsed by, or derived from any other screenshot application.

## File formats

- Screenshots are written as PNG, JPEG or WebP with Pillow.
- Editor projects use `.cln`, a plain zip archive containing `annotations.json` (this project's
  own schema, `FORMAT_VERSION = 1`) and `image.png`.
- Settings and history are plain JSON under the XDG base directories.

Neither the archive layout nor the JSON schema is intended to interoperate with another tool's
project or library format.

## Behaviour choices

The interaction model (frozen frame, dimmed outside region, eight handles, magnifier, pin as a
floating window) follows the conventions that are common to graphical screenshot tools on
Wayland. Shortcut choices come from the platform conventions of the target compositors, and the
hotkey templates shipped by `dustshot hotkeys` are suggestions the user copies into their own
compositor configuration; nothing is installed or modified automatically.

## Licence compatibility

Dustshot is distributed under the GNU General Public License version 3 or later (see
LICENSE). GPL-3.0-or-later was chosen so the project stays compatible with the GPL-licensed
desktop stack it links against (GTK, gtk4-layer-shell) and so redistributed builds keep the
same freedoms.
