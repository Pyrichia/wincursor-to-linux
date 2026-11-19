# wincurtolinux

Convert a Windows cursor scheme (`.ani` animated cursors and `.cur` static cursors, optionally with an installer `.inf`) into a Linux **Xcursor theme**. The script also installs and activates the theme on most Linux desktops.

- Keeps animation frames, frame order and timing. Windows measures timing in jiffies (1/60 s), and the script converts them exactly.
- Keeps each frame's hotspot and scales it to every output size.
- Generates multiple cursor sizes, from 24 px up to 256 px.
- Adds aliases (legacy X11 names, CSS names and the hashed names some browsers and toolkits request), so one Windows cursor covers every name an app might ask for.
- Detects your distro, container, session type and desktop, then installs to a folder that desktop actually reads.
- Writes a `.tar.xz` or `.tar.gz` theme archive for "install from file" dialogs or for sharing.

---

## ⚠️ Disclaimer

- **This code was written by Claude, Anthropic's AI model**, at a user's request. It has not been professionally audited.
- **Use it entirely at your own risk.** No warranty of any kind is given, express or implied. The authors accept no liability for damage, data loss, broken desktop settings or anything else that results from using it.
- **Updates and bug fixes are unlikely.** The project is published as is.
- **Please don't open bug reports, issues or feature requests.** If you want something changed, **fork the repository** and patch it yourself. Forks, improvements and derived versions are welcome.
- Cursor artwork belongs to its original creators. Converting a cursor pack doesn't change its licence, so check the pack's terms before you redistribute converted themes.

---

## Requirements

- Linux with Python **3.8 or newer**
- **One** of these conversion engines:

| Engine | Install | Notes |
|---|---|---|
| **win2xcur** (preferred) | `pip install --user win2xcur` | Needs ImageMagick's MagickWand library (see below). |
| **Pillow** (fallback) | `pip install --user pillow` | Pure Python plus Pillow. Used automatically if win2xcur or ImageMagick isn't available. |

ImageMagick library for win2xcur:

| Distro family | Package |
|---|---|
| Fedora / RHEL | `sudo dnf install ImageMagick-libs` |
| Debian / Ubuntu / Mint | `sudo apt install libmagickwand-6.q16-7` (or `libmagickwand-dev`) |
| Arch / Manjaro | `sudo pacman -S imagemagick` |
| openSUSE | `sudo zypper install ImageMagick` |
| Immutable systems (Silverblue, Kinoite, Bazzite and similar) | Install the packages in a distrobox or toolbox container and run the script there, or use the Pillow engine. |

Optional: your desktop's own settings tool (`plasma-apply-cursortheme`, `gsettings`, `xfconf-query`, `swaymsg`, `hyprctl`) for automatic activation with `--apply`.

The script never calls `sudo` itself.

---

## Setup

```bash
git clone <your-fork-url> wincurtolinux
cd wincurtolinux
pip install --user win2xcur      # or: pip install --user pillow
chmod +x wincurtolinux.py
./wincurtolinux.py --help
```

If `pip` complains about an "externally managed environment", use a virtual environment:

```bash
python3 -m venv ~/.venvs/wincur
~/.venvs/wincur/bin/pip install win2xcur pillow
~/.venvs/wincur/bin/python wincurtolinux.py --help
```

---

## Quick start

```bash
# Detect the desktop, convert, install and print the activation command
./wincurtolinux.py "My Cursor Pack.zip"

# Same, but also activate the theme
./wincurtolinux.py "My Cursor Pack.zip" --apply

# Slow every animation step down by 40 ms
./wincurtolinux.py "My Cursor Pack.zip" --slowdown 40 --apply

# See what would happen without writing anything
./wincurtolinux.py ./unzipped-pack --dry-run
```

---

## Command-line switches

| Switch | Default | Purpose |
|---|---|---|
| `input` (positional) | — | A `.zip` file, or a folder containing `.ani` / `.cur` files (searched recursively). |
| `--desktop {auto,kde,gnome,cinnamon,mate,xfce,budgie,lxqt,sway,hyprland,other}` | `auto` | Target desktop. Detected automatically; the script asks if detection fails and it's run interactively, and uses `other` if it isn't. |
| `--name NAME` | from `.inf` | Theme name. Defaults to the scheme name in the `.inf`, otherwise the input file or folder name. Characters other than `A-Z a-z 0-9 _ . -` are replaced with `_`. |
| `--sizes PX [PX ...]` | `24 32 48 64 96 128 192 256` | Nominal cursor sizes to generate (8–512). Sizes above the source resolution are upscaled and softer. |
| `--slowdown MS` | `0` | Adds MS milliseconds to **every original animation step** (0–5000). `0` keeps the exact Windows timing. |
| `--filter {auto,lanczos,nearest,mitchell,box}` | `auto` | Scaling filter. `auto` uses `nearest` for exact integer upscales, such as 96→192, to keep pixel art crisp, and `lanczos` otherwise. |
| `--engine {auto,win2xcur,pillow}` | `auto` | Conversion engine. `auto` tries win2xcur first, then Pillow. |
| `--dest DIR` | detected | Icon folder to install into. Overrides the detected location. |
| `--system` | off | Install for all users (see the install locations below). You must run the script as root yourself. |
| `--inherits THEME` | detected | Fallback theme for cursor names the pack doesn't provide. |
| `--cursor-size PX` | `24` | Size passed to sway or Hyprland when activating. |
| `--out DIR` | — | Build the theme into DIR and stop; nothing is installed or activated. |
| `--force` | off | Replace an existing theme or archive without asking. |
| `--archive-dir DIR` | current folder | Where to write the `.tar.xz` / `.tar.gz` archive. |
| `--no-archive` | off | Don't write an archive. |
| `--dry-run` | off | Convert in a temporary folder, print a full report, and write nothing. |
| `--apply` | off | Activate the theme after installing, using the desktop's own tool. |
| `-h`, `--help` | — | Show help. |

### Editable settings at the top of the script

| Setting | Purpose |
|---|---|
| `SIZES` | Default output sizes. |
| `ANIMATION_SLOWDOWN_MS` | Default slowdown, used when `--slowdown` isn't given. |
| `DEFAULT_JIFFIES` | Step delay used when an `.ani` has no usable timing (default 10 jiffies, about 167 ms). |
| `MIN_FRAME_MS` | Shortest frame allowed (17 ms, one Windows jiffy). |
| `INHERITS` | Fallback theme candidates per desktop; the first one installed is used. |
| `HOTSPOT_OVERRIDES` | Per-role hotspot fixes in source pixels, e.g. `{"Arrow": (4, 2)}`. |
| `ROLE_MAP` | **Mapping table**: Windows role → Linux cursor names. The first name becomes the real file and the rest become symlinks. |
| `FALLBACKS` | Extra Linux names the pack has no artwork for, pointed at the closest mapped cursor. |
| `FILENAME_ROLES` | Filename → role guesses, used only when there's no usable `.inf`. |

---

## Input

### Valid input types

| Input | Accepted |
|---|---|
| `.zip` archive | ✅ Extracted safely to a temporary folder; entries that would escape it are refused. |
| Folder | ✅ Searched recursively. |
| `.ani` (animated cursor, RIFF/ACON) | ✅ Icon-based frames in PNG or BMP format, with optional `seq ` and `rate` chunks. |
| `.cur` (static cursor) | ✅ PNG or BMP images, including 32-bit alpha, 1-bit masks and multiple sizes (the largest is used). |
| `.inf` (Windows scheme installer) | ✅ Optional, used to assign roles. |
| `.ico`, `.png`, `.rar`, `.7z`, raw-bitmap ANI | ❌ Not supported. Extract `.rar` and `.7z` packs first and pass the folder. |

### Expected source layout

Any layout works, because the search is recursive. A typical Windows pack looks like this:

```
My Cursor Pack.zip
└── My Cursor Pack/
    ├── Readme.txt            (ignored)
    └── cursors/
        ├── Install.inf       (optional but recommended)
        ├── normal.ani
        ├── help.ani
        ├── working.ani
        ├── busy.ani
        ├── precision.cur
        ├── text.ani
        ├── handwriting.ani
        ├── unavailable.ani
        ├── vertical.ani
        ├── horizontal.ani
        ├── diagonal1.ani
        ├── diagonal2.ani
        ├── move.ani
        ├── alternate.ani
        ├── link.ani
        ├── pin.ani           (optional)
        └── person.ani        (optional)
```

Filenames are matched case-insensitively. Files the script can't assign a role to are listed as notes and skipped.

### How the `.inf` file is used

Windows cursor packs usually ship an installer `.inf` that writes a registry value under `HKCU\Control Panel\Cursors\Schemes`. That value lists the cursor files in a **fixed order** that Windows defines:

| # | Windows role | Main Linux name |
|---|---|---|
| 1 | Arrow (Normal Select) | `default` |
| 2 | Help | `help` |
| 3 | AppStarting (Working in Background) | `progress` |
| 4 | Wait (Busy) | `wait` |
| 5 | Crosshair (Precision Select) | `crosshair` |
| 6 | IBeam (Text Select) | `text` |
| 7 | NWPen (Handwriting) | `pencil` |
| 8 | No (Unavailable) | `not-allowed` |
| 9 | SizeNS (Vertical Resize) | `ns-resize` |
| 10 | SizeWE (Horizontal Resize) | `ew-resize` |
| 11 | SizeNWSE (Diagonal Resize 1) | `nwse-resize` |
| 12 | SizeNESW (Diagonal Resize 2) | `nesw-resize` |
| 13 | SizeAll (Move) | `move` |
| 14 | UpArrow (Alternate Select) | `center_ptr` |
| 15 | Hand (Link Select) | `pointer` |
| 16 | Pin (Location Select) | `pin` |
| 17 | Person (Person Select) | `person` |

The script finds that registry line in any `*.inf` in the input, expands `%variables%` from the `[Strings]` section, and assigns each file to its role by position. That's reliable even when filenames are unusual. Without a usable `.inf`, or for files it doesn't list, the script falls back to `FILENAME_ROLES`. The scheme name from the `.inf` becomes the default theme name.

---

## Output

### Theme folder

```
<ThemeName>/
├── index.theme        ([Icon Theme] Name, Comment, Inherits)
├── cursor.theme       (same content; read by some KDE/X11 tools)
├── README.txt         (sizes, engine, timing, uninstall note)
└── cursors/
    ├── default        (Xcursor file: all sizes, all frames)
    ├── left_ptr -> default
    ├── pointer
    ├── hand2 -> pointer
    └── ...            (about 130 names, mostly symlinks)
```

- Cursor files use the standard **Xcursor** binary format with premultiplied ARGB, one image per size per frame, and per-frame delays in milliseconds.
- Identical images are stored once, so repeated animation frames don't inflate the file.
- Every file is re-read and checked after writing.

### Archive

The script writes `<ThemeName>.tar.xz` or `<ThemeName>.tar.gz`, whichever is smaller (usually `.tar.xz`), to `--archive-dir`. The archive contains the theme folder with symlinks kept and file ownership neutralised. Use it with a desktop's "Install from File…" option, or to share the theme.

---

## Where themes are installed

### Per-user (default)

| Situation | Location |
|---|---|
| Any desktop, normal session | `~/.icons/<ThemeName>` |
| `XCURSOR_PATH` set without `~/.icons` | The first folder in your home directory listed in `XCURSOR_PATH` (with a warning if there's none) |
| Inside **distrobox** with a separate container home | The **host** home (`$DISTROBOX_HOST_HOME/.icons`) |
| `--dest DIR` | `DIR/<ThemeName>` |

`~/.icons` is used rather than `~/.local/share/icons` because **KDE Plasma's cursor settings list only scans `~/.icons`** and the system folders. libXcursor, GTK/GNOME and the wlroots compositors read `~/.icons` too.

### System-wide (`--system`, run as root)

| System type | Location |
|---|---|
| Traditional distros (Fedora Workstation, Ubuntu, Debian, Arch, openSUSE…) | `/usr/share/icons/<ThemeName>` |
| Immutable/ostree systems (Silverblue, Kinoite, Bazzite, NixOS…) | `/usr/local/share/icons/<ThemeName>` (`/usr` is read-only). Plasma's settings list doesn't scan this folder, so a per-user install is recommended there. |

### Activation per desktop

| Desktop | `--apply` runs | Or use the GUI |
|---|---|---|
| KDE Plasma | `plasma-apply-cursortheme <name>` | System Settings → Colours & Themes → Cursors |
| GNOME | `gsettings set org.gnome.desktop.interface cursor-theme <name>` | GNOME Tweaks → Appearance → Cursor |
| Budgie | same as GNOME | Budgie Desktop Settings → Style → Cursor |
| Cinnamon | `gsettings set org.cinnamon.desktop.interface cursor-theme <name>` | System Settings → Themes → Mouse Pointer |
| MATE | `gsettings set org.mate.peripherals-mouse cursor-theme <name>` | Control Center → Appearance → Theme → Customize → Pointer |
| Xfce | `xfconf-query -c xsettings -p /Gtk/CursorThemeName -n -t string -s <name>` | Settings → Mouse and Touchpad → Theme |
| LXQt | — (GUI only) | LXQt Configuration Center → Appearance → Cursor |
| sway | `swaymsg 'seat * xcursor_theme <name> <size>'` | To make it permanent, add the same line to `~/.config/sway/config` |
| Hyprland | `hyprctl setcursor <name> <size>` | To make it permanent, add `env = XCURSOR_THEME,<name>` and `env = XCURSOR_SIZE,<size>` to `hyprland.conf` |
| Other / unknown | — | Set `XCURSOR_THEME` and `XCURSOR_SIZE`, or put `[Icon Theme]` / `Inherits=<name>` in `~/.icons/default/index.theme` |

Inside a container, activation commands run on the host through `distrobox-host-exec`, `host-spawn` or `flatpak-spawn --host`, whichever is available.

**Flatpak apps** may need access to the theme folder:

```bash
flatpak override --user --filesystem=~/.icons:ro
```

Restart apps, or log out and back in, if some keep showing the old cursor.

---

## Animation timing

Windows `.ani` files give delays in **jiffies (1/60 s)**, either per step (the `rate` chunk) or as one value for all steps (the `anih` header). The script converts them exactly, merges consecutive identical frames, and prints each cursor's loop length.

- If a pack feels too fast, use `--slowdown MS`, or set `ANIMATION_SLOWDOWN_MS`. The value is added to every original step, so the rhythm of the animation is kept.
- Missing or zero delays fall back to the header rate, then to `DEFAULT_JIFFIES`, and a timing note is printed.

---

## Uninstall

```bash
rm -rf ~/.icons/<ThemeName>
```

Then choose another cursor theme in your desktop settings.

---

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Theme missing from Plasma's cursor list | It was installed to `~/.local/share/icons`. Move it to `~/.icons`, which is now the default. |
| "Could not find theme" from `plasma-apply-cursortheme` | Same as above, or `XCURSOR_PATH` is set without `~/.icons`. |
| "No usable conversion engine" | Install `win2xcur` together with ImageMagick, or install `pillow`. |
| Animation too fast | Use `--slowdown 30` to `--slowdown 60`. |
| Hotspot slightly off | Add an entry to `HOTSPOT_OVERRIDES`. |
| Wrong cursor in a role | Fix the `.inf`, rename the files, or edit `FILENAME_ROLES` and `ROLE_MAP`. |

---

## Licence and contributions

No support is offered. **Fork it to fix or extend it. Please don't file issues or requests.** Pick and add a licence of your choice before publishing (MIT is a common option).
