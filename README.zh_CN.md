# Dustshot

[![CI](https://github.com/publieople/dustshot/actions/workflows/ci.yml/badge.svg)](https://github.com/publieople/dustshot/actions/workflows/ci.yml)
[![License: GPL-3.0-or-later](https://img.shields.io/badge/license-GPL--3.0--or--later-blue.svg)](LICENSE)

[English](README.md) · 简体中文

一个 Wayland 原生的截图、标注与贴图工具，使用 Python 与 GTK 4 编写。

Dustshot 会冻结一帧桌面画面，让你以像素级精度框选区域、做标注，然后复制、保存、OCR 识别，
或者把它「贴」成悬浮窗口。它通过 `grim` 使用 wlr-screencopy、通过 `gtk4-layer-shell` 使用
wlr-layer-shell，所以在 wlroots 系合成器（niri、Hyprland、Sway 等）上不需要 portal 也能工作。

> 独立实现：没有使用任何其它截图工具的代码、素材或私有文件格式。
> 参见 [docs/INDEPENDENCE.md](docs/INDEPENDENCE.md)。

![区域选择覆盖层](docs/images/selector.png)

*区域截图：桌面被冻结成一帧画面，选中区域保持原亮度，八个缩放手柄、实时尺寸标签、
带取色器的放大镜，以及底部快捷键提示条。*

![标注编辑器](docs/images/editor.png)

*编辑器：十二个工具的工具栏、调色板、每种工具的线宽、快照式撤销/重做、裁剪与 90° 旋转，
标题栏里还有保存 / 复制 / 贴图 / OCR。*

![贴图](docs/images/pin.png)

*贴图板：任何截图（或图片文件）都能悬浮在桌面之上，可拖动、可缩放，悬停工具栏支持复制、
保存、再贴一张、编辑、居中、鼠标穿透和不透明度。*

![截图历史](docs/images/history.png)

*可浏览的截图历史（`dustshot history --gui`）。*

![敏感信息遮挡](docs/images/redact.png)

*`dustshot redact`：OCR 找出邮箱、电话、身份证与银行卡号、API key，然后用不透明色块遮住
（也支持马赛克与模糊）。*

![托盘图标](docs/images/tray.png)

*`dustshot tray`：状态栏里的 StatusNotifierItem 图标，菜单可以截取区域或整个输出、开始录制、
打开截图历史。*

## 功能

- **区域截图**：把桌面冻结成一帧画面，每个输出一块全屏覆盖层，选区外压暗，八个缩放手柄，
  实时尺寸标签，带取色器的放大镜，十字辅助线，并会吸附到背景里窗口与控件的边框（按住 Alt
  可临时关闭吸附，自由框选）。
- **标注编辑器**：矩形、椭圆、直线、箭头、画笔、荧光笔、文字、序号、马赛克和模糊；裁剪到
  拖出的方框（回车应用，Esc 放弃），用 Ctrl+← / Ctrl+→ 旋转 90°；十色调色板、每种工具单独
  的线宽、快照式撤销/重做、任意图元可选中拖动，不离开窗口就能保存 / 复制 / 贴图。
- **贴图**：把一张或多张截图丢到屏幕上变成置顶悬浮窗；拖动移动（带边缘与中心吸附）、滚轮
  缩放、每张独立不透明度、鼠标穿透、居中新按钮，以及悬停工具栏（复制、保存、再贴、编辑、
  关闭）；编辑 / Ctrl+E 会把贴图重新送进标注编辑器，改完按原缩放放回。联动开关可以把两张以上
  贴图绑成一组，一起移动和缩放，组里少于两张时自动解散。
- **OCR**：封装 tesseract，保留词框与行分组，默认 `eng+chi_sim`，预处理时放大 2 倍。
- **二维码与条形码**：`dustshot codes` 用 `zbarimg` 解码二维码和一维条码，可以读文件，也可以
  现场截一个区域，输出文本或 JSON。
- **敏感信息**：`dustshot redact` 先跑 OCR，找出邮箱、电话、身份证、银行卡号和 API key，
  然后盖上不透明色块（实心、马赛克或模糊三种）；编辑器工具栏里也有同名按钮。
- **滚动截图**：`dustshot scroll` 每次翻页后重新截取同一区域，找出相邻两帧共有的行并拼成一张
  长图；翻页由 wtype 或 ydotool 驱动，也可以 `--manual` 手动翻页。
- **录制**：通过 `wf-recorder` 把区域或整个输出录成 MP4（H.264），可用 ffmpeg 转 GIF，支持
  按时长自动停止，并有一个小停止窗口。
- **ScreenCast portal**：`--backend portal` 直接驱动 `org.freedesktop.portal.ScreenCast`
  （CreateSession / SelectSources / Start / OpenPipeWireRemote），再通过 GStreamer 与 PipeWire
  抓取每个被共享的显示器，所以在没有 wlr-screencopy 的合成器上也能区域或全屏截图；只提供
  DMA-BUF 流的合成器会走 GL 导入。
- **托盘图标**：`dustshot tray` 发布一个 StatusNotifierItem 图标，dbusmenu 菜单可以截区域或
  全屏、开始录制、打开截图历史、退出；每一行都在自己的进程里执行对应的 CLI 命令。
- **多语言界面**：界面文字都走 gettext，`po/` 里的英文目录会编译进 `src/dustshot/locale/`，
  按会话语言加载，也可以用 `DUSTSHOT_LANG=en` 为单次运行强制指定语言。
- **额外功能**：可浏览的截图历史窗口（`dustshot history --gui`）、`.cln` 编辑器工程文件、
  快捷键模板、`dustshot doctor`。

## 支持的桌面环境

Dustshot 是 Wayland 原生工具，**没有 X11 后端**。

| 桌面 / 合成器 | 截图方式 | 覆盖层与贴图 | 说明 |
| --- | --- | --- | --- |
| niri、Hyprland、Sway 等 wlroots 系 | `grim`（wlr-screencopy） | 走 wlr-layer-shell：真正的全屏覆盖层与置顶贴图 | 体验最完整；滚动截图的自动翻页用 wtype / ydotool |
| GNOME（Mutter）、KDE Plasma（KWin） | `--backend portal`（ScreenCast + PipeWire） | 没有 layer-shell，覆盖层与贴图退化成普通窗口 | 第一次截图需要在 portal 对话框里授权共享屏幕 |
| Flatpak 沙箱 | 强制走 portal（安全上下文会隐藏 wlr-screencopy） | 同上，退化为普通窗口 | 构建与沙箱差异见 [packaging/README.md](packaging/README.md) |
| X11 会话 | 不支持 | — | grim 与 layer-shell 都是 Wayland 协议 |

托盘图标需要状态栏支持 StatusNotifierItem（KDE Plasma、waybar、quickshell / noctalia 等）。
OCR、条码、录制调用的是外部命令（tesseract、zbarimg、wf-recorder），与合成器无关。

## 环境要求

- Python 3.11 或更新版本、GTK 4、`gtk4-layer-shell`
- `grim`（截图），以及实现了 wlr-screencopy 的合成器
- 可选：OCR 需要 `tesseract` 与语言包，录制需要 `wf-recorder` 和 `ffmpeg`，
  GTK 剪贴板不可用时需要 `wl-clipboard`
- 可选：`dustshot tray` 需要状态栏提供 StatusNotifierWatcher（KDE Plasma、quickshell /
  noctalia、waybar 等）
- 可选：`--backend portal` 需要桌面 portal 本体、PyGObject、`pipewiresrc` 和 GL 插件
  （Arch：`xdg-desktop-portal`、`python-gobject`、`gst-plugin-pipewire`、`gst-plugins-base`）

Arch / CachyOS 上：

```fish
sudo pacman -S --needed python gtk4 gtk4-layer-shell grim tesseract tesseract-data-eng tesseract-data-chi_sim wf-recorder ffmpeg wl-clipboard
```

一个需要知道的运行时细节：`gtk4-layer-shell` 必须在 `libwayland` 之前预加载，
所以 Dustshot 在需要时会用设置好的 `LD_PRELOAD` 重新执行自己。它不会安装或修改你系统里的
任何东西；设置 `DUSTSHOT_NO_REEXEC=1` 可以关掉这次重新执行。

## 安装

```fish
git clone https://github.com/publieople/dustshot
cd dustshot
python3 -m venv .venv
source .venv/bin/activate.fish
pip install -e '.[gtk]'

# 或者用 pipx，把 GUI 依赖集中在一个环境里：
pipx install 'dustshot[gtk] @ git+https://github.com/publieople/dustshot'
```

GUI extra 的 Python 依赖只有 `PyGObject` 和 `pycairo`；编辑器、渲染器、配置存储和 CLI
没有它们也能工作（CI 测的就是这部分）。

### 桌面集成

`packaging/` 里带了 desktop entry（含区域 / 全屏 / 录制 / OCR / 历史五个动作）、AppStream
元数据和图标，所以它会出现在应用菜单里：

```fish
install -Dm644 packaging/io.github.publieople.Dustshot.desktop ~/.local/share/applications/io.github.publieople.Dustshot.desktop
install -Dm644 packaging/io.github.publieople.Dustshot.metainfo.xml ~/.local/share/metainfo/io.github.publieople.Dustshot.metainfo.xml
cp -r packaging/icons/hicolor ~/.local/share/icons/
```

Flatpak manifest 在 `packaging/io.github.publieople.Dustshot.yml`，已经在本机 niri 会话上
构建并实测通过（沙箱里 `--backend auto` 会改用 ScreenCast portal），构建步骤与沙箱限制见
[packaging/README.md](packaging/README.md)。CI 不构建它，因为截图与覆盖层需要真实的 Wayland 会话。

## 用法

```text
dustshot                     # 区域截图，直接进入编辑器
dustshot full                # 整个输出，进入编辑器
dustshot full --backend portal  # 同上，但走 ScreenCast portal
dustshot capture --no-editor # 只截图，保存/复制，不打开编辑器
dustshot edit IMAGE          # 用编辑器打开一个已有文件
dustshot pin IMAGE           # 把一张图片贴到屏幕上
dustshot ocr [IMAGE]         # 识别文字（不给文件时先截一个区域）
dustshot codes [IMAGE]       # 解码二维码与条形码
dustshot redact [IMAGE]      # 找出并遮住敏感文字
dustshot scroll --steps 4    # 滚动并拼接成长截图
dustshot tray                  # 在系统托盘里常驻一个图标
dustshot record --duration 15 --gif
dustshot history --limit 10
dustshot history --gui       # 浏览截图历史
dustshot settings --show
dustshot settings --set capture.image_format=jpg
dustshot hotkeys --compositor niri
dustshot doctor              # 检查依赖与环境
dustshot version
```

常用参数：`--rect 100,100,800,600` 跳过覆盖层直接截指定矩形、`--backend auto|grim|portal`、
`--dir`、`--format`、`--no-copy`、`--delay SECONDS`、`--pin`、`--position X,Y`、`--scale`。
完整列表用 `dustshot 命令 --help` 查看。

## 快捷键

区域选择覆盖层：

| 按键 | 动作 |
| --- | --- |
| 拖动 | 画出 / 移动 / 缩放选区 |
| 方向键、Shift+方向键 | 每次微调 1 px / 10 px |
| Ctrl + 滚轮 | 放大或缩小选区 |
| 空格 / Ctrl+A | 选中整个输出 |
| Backspace | 清空选区 |
| 回车 | 保存并复制 |
| Ctrl+C / Ctrl+S | 只复制 / 只保存 |
| Ctrl+R | 录制选中的区域 |
| Esc / 右键 | 取消 |

编辑器：

| 按键 | 动作 |
| --- | --- |
| Ctrl+Z / Ctrl+Shift+Z | 撤销 / 重做 |
| Ctrl+C / Ctrl+V | 复制 / 粘贴图片 |
| Ctrl+S / Ctrl+P | 保存 / 贴图 |
| Delete / Backspace | 删除选中的图元 |
| Esc | 取消选中 |
| + / - | 调整当前工具线宽 |
| 1 - 9 | 选择调色板颜色 |

另外：拖动裁剪工具框选后按 **回车** 应用裁剪，**Esc** 放弃；**Ctrl+← / Ctrl+→** 逆时针 / 顺时针
旋转 90°；区域选择时按住 **Alt** 关闭边缘吸附。

贴图窗口：`+` / `-` 缩放、`1` 恢复 1:1、Ctrl+C 复制、Ctrl+S 保存、**Ctrl+E** 回到编辑器、
Esc 或右键关闭。悬停工具栏里还有 1:1、编辑、复制、保存、再贴、居中、穿透开关、不透明度滑杆，
以及把多张贴图绑在一起的联动开关。

## 合成器配置

`dustshot hotkeys` 会按合成器打印一份可直接粘贴的配置片段（niri、Hyprland、Sway、GNOME、
KDE，或通用 wlroots 配置）。niri：

```kdl
binds {
    Print { spawn-sh "dustshot region"; }
    Mod+Print { spawn-sh "dustshot full"; }
}
```

Hyprland：

```text
bind = , Print, exec, dustshot region
bind = SUPER, Print, exec, dustshot full
```

## 配置

设置保存在 `~/.config/dustshot/config.json`，用 `dustshot settings --set SECTION.FIELD=VALUE`
写入。可配置的段有 `capture`、`annotation`、`pin`、`ocr` 和 `recording`；截图历史保存在
`~/.local/share/dustshot/history.json`；截图默认存到 `<图片目录>/Screenshots`（跟随 XDG 图片
目录，系统没有定义时用 `~/Pictures`）。

## 翻译

界面文字用 `_()` 包裹，通过 gettext（domain `dustshot`）解析。目录文件放在 `po/`，编译进
`src/dustshot/locale/<语言>/LC_MESSAGES/dustshot.mo`，随包发布；没有目录文件时，所有查词都会
返回原始中文串。

```sh
DUSTSHOT_LANG=en dustshot full      # 单次运行强制英文
python3 -m dustshot.i18n available    # 列出已编译的目录
python3 -m dustshot.i18n compile      # 从 po/*.po 重新编译所有 .mo

# 增删或修改文案之后刷新模板
xgettext --language=Python --keyword=_ --keyword=ngettext:1,2 --from-code=UTF-8 \
    --package-name=dustshot --add-comments=TRANSLATORS \
    -o po/dustshot.pot $(find src -name '*.py' | sort)
```

`DUSTSHOT_LANG`（`:` 或 `,` 分隔，越靠前优先级越高）会覆盖会话语言，
`DUSTSHOT_LOCALEDIR` 可以把查词指向另一个目录。

## 开发

```fish
python3 -m venv .venv; source .venv/bin/activate.fish
pip install -e '.[dev]'
python -m pytest        # 不需要显示会话
ruff check src tests
ruff format --check src tests
```

测试套件刻意避开 GTK：`dustshot/` 下除 `dustshot.ui` 之外都能在无头环境导入，渲染器基于
Pillow，所以 CI 跑在普通 Ubuntu 镜像上。模块地图见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)，
里程碑状态见 [docs/ROADMAP.md](docs/ROADMAP.md)。

## 许可证

GPL-3.0-or-later，见 [LICENSE](LICENSE)。
