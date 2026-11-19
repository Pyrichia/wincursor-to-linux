#!/usr/bin/env python3
"""
wincurtolinux.py - convert a Windows cursor scheme (.ani / .cur, optionally
with an Installer .inf) into an Xcursor theme for Linux desktops.

Engine:
    win2xcur (preferred)  pip install --user win2xcur
                          needs ImageMagick's MagickWand library on the system
                          (Fedora: ImageMagick-libs, Debian/Ubuntu: libmagickwand-6.q16-7,
                           Arch: imagemagick)
    Pillow   (fallback)   pip install --user pillow   - used automatically if
                          win2xcur/ImageMagick are unavailable (--engine pillow)

Examples:
    ./wincurtolinux.py "Windows_Cursor_Pack.zip"                 # detect desktop, install
    ./wincurtolinux.py pack.zip --apply                        # ...and activate it
    ./wincurtolinux.py pack.zip --slowdown 40                  # +40 ms per animation step
    ./wincurtolinux.py ./cursor-folder --desktop gnome --name MyCursors
    ./wincurtolinux.py pack.zip --sizes 24 32 48 64 96
    ./wincurtolinux.py pack.zip --dry-run                      # report only
    ./wincurtolinux.py pack.zip --out ./build                  # build only, no install
    ./wincurtolinux.py pack.zip --no-archive                   # skip the .tar.* file

The script detects the OS (including immutable/ostree systems such as Bazzite
or Silverblue), containers (distrobox, toolbox, Flatpak), the session type and
the desktop (KDE Plasma, GNOME, Cinnamon, MATE, Xfce, Budgie, LXQt, sway,
Hyprland), installs to the per-user directory that desktop actually scans
(~/.icons) and activates the theme with that desktop's own tool.

Besides installing, it writes <name>.tar.xz or <name>.tar.gz (whichever is
smaller) to the current directory, for "install from file" dialogs or sharing.

Animation timing follows the Windows .ani data exactly (1 jiffy = 1/60 s);
use --slowdown MS (or ANIMATION_SLOWDOWN_MS) to slow every step down.
"""

import argparse
import configparser
import io
import lzma
import os
import re
import shutil
import struct
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

# =============================================================================
# CONFIGURATION - edit these tables to taste
# =============================================================================

# Xcursor nominal sizes to generate. Sizes above the source resolution
# are upscaled and therefore softer; delete the ones you
# don't want here or pass --sizes.
SIZES = [24, 32, 48, 64, 96, 128, 192, 256]

# Fallback theme for cursor names this theme doesn't provide: the first one
# found installed is used (per desktop; "*" applies to all others).
INHERITS = {
    "kde": ["breeze_cursors", "Breeze_Light", "Adwaita"],
    "*":   ["Adwaita", "breeze_cursors", "DMZ-White", "default"],
}

# --- Animation timing --------------------------------------------------------
# Windows .ani delays are in "jiffies" of 1/60 s, either per step (rate chunk)
# or one value for all steps (anih header). They are converted exactly.
# ANIMATION_SLOWDOWN_MS adds this many milliseconds to EVERY original animation
# step (e.g. 30 turns 6-jiffy/100 ms steps into 130 ms). --slowdown overrides.
ANIMATION_SLOWDOWN_MS = 0
# Used for steps whose delay is missing or zero. Windows itself falls back to
# the header rate; 10 jiffies (~167 ms) is used when that is missing too.
DEFAULT_JIFFIES = 10
# Windows never shows a frame for less than one jiffy.
MIN_FRAME_MS = 17

# Hotspot overrides in SOURCE pixels, keyed by Windows role: {"Arrow": (18, 12)}
HOTSPOT_OVERRIDES = {}

# -----------------------------------------------------------------------------
# MAPPING TABLE  (Windows role -> Xcursor names)
#   The FIRST name becomes the real file; the rest are symlinks to it.
#   Includes CSS names, legacy X11 names and the hashed names some toolkits
#   (Qt, Firefox, Chromium, GTK2) still ask for.
# -----------------------------------------------------------------------------
ROLE_MAP = {
    "Arrow":       ["default", "left_ptr", "arrow", "top_left_arrow"],
    "Help":        ["help", "question_arrow", "whats_this", "left_ptr_help",
                    "5c6cd98b3f3ebcb1f9c7f1c204630408",
                    "d9ce0ab605698f320427677b458ad60b"],
    "AppStarting": ["progress", "left_ptr_watch", "half-busy",
                    "08e8e1c95fe2fc01f976f1e063a24ccd",
                    "3ecb610c1bf2410f44200f48c40d3599"],
    "Wait":        ["wait", "watch", "clock"],
    "Crosshair":   ["crosshair", "cross", "tcross", "cross_reverse", "diamond_cross"],
    "IBeam":       ["text", "xterm", "ibeam"],
    "NWPen":       ["pencil", "draft"],
    "No":          ["not-allowed", "no-drop", "crossed_circle", "forbidden",
                    "circle", "dnd-no-drop", "03b6e0fcb3499374a867c041f52298f0"],
    "SizeNS":      ["ns-resize", "n-resize", "s-resize", "row-resize", "size_ver",
                    "v_double_arrow", "sb_v_double_arrow", "double_arrow",
                    "top_side", "bottom_side", "split_v",
                    "00008160000006810000408080010102",
                    "2870a09082c103050810ffdffffe0204"],
    "SizeWE":      ["ew-resize", "e-resize", "w-resize", "col-resize", "size_hor",
                    "h_double_arrow", "sb_h_double_arrow", "left_side",
                    "right_side", "split_h",
                    "028006030e0e7ebffc7f7070c0600140",
                    "14fef782d02440884392942c11205230"],
    "SizeNWSE":    ["nwse-resize", "nw-resize", "se-resize", "size_fdiag",
                    "fd_double_arrow", "top_left_corner", "bottom_right_corner",
                    "fcf1c3c7cd4491d801f1e1c78f100000"],
    "SizeNESW":    ["nesw-resize", "ne-resize", "sw-resize", "size_bdiag",
                    "bd_double_arrow", "top_right_corner", "bottom_left_corner",
                    "c7088f0f3e6c8088236ef8e1e3e70000"],
    "SizeAll":     ["move", "fleur", "all-scroll", "all-resize", "size_all",
                    "grab", "grabbing", "openhand", "closedhand", "dnd-move",
                    "pointer-move",
                    "4498f0e0c1937ffe01fd06f973665830",
                    "9081237383d90e509aa00f00170e968f"],
    "UpArrow":     ["center_ptr", "up-arrow", "up_arrow", "sb_up_arrow"],
    "Hand":        ["pointer", "hand2", "hand1", "hand", "pointing_hand",
                    "9d800788f1b08800ae810202380a0822",
                    "e29285e634086352946a0e7090d73106"],
    "Pin":         ["pin"],
    "Person":      ["person"],
}

# Names with no artwork in a typical Windows scheme -> closest mapped name.
FALLBACKS = {
    "copy": "default", "dnd-copy": "default", "dnd-none": "default",
    "dnd-ask": "default", "context-menu": "default", "icon": "default",
    "right_ptr": "default",
    "1081e37283d90000800003c07f3ef6bf": "default",   # copy
    "6407b0e94181790501fd1e167b474872": "default",   # copy
    "b66166c04f8c3109214a4fbd64a50fc8": "default",   # copy
    "alias": "pointer", "link": "pointer", "dnd-link": "pointer",
    "3085a0e285430894940527032f8b26df": "pointer",   # link
    "640fb0e74195791501fd1ed57b41487f": "pointer",   # link
    "a2a266d0498c3104214a47bd64ab0fc8": "pointer",   # alias
    "cell": "crosshair", "plus": "crosshair", "color-picker": "crosshair",
    "zoom-in": "crosshair", "zoom-out": "crosshair", "target": "crosshair",
    "dot": "crosshair", "dotbox": "crosshair", "dot_box_mask": "crosshair",
    "vertical-text": "text",
    "X_cursor": "not-allowed", "pirate": "not-allowed",
    "pin": "pointer", "person": "pointer",
}

# Order of files in a Windows "Control Panel\Cursors\Schemes" registry value
# (this is how the Installer .inf says which file plays which role).
SCHEME_ORDER = ["Arrow", "Help", "AppStarting", "Wait", "Crosshair", "IBeam",
                "NWPen", "No", "SizeNS", "SizeWE", "SizeNWSE", "SizeNESW",
                "SizeAll", "UpArrow", "Hand", "Pin", "Person"]

# Used only when no usable .inf is found: lowercase filename stem -> role.
FILENAME_ROLES = {
    "normal": "Arrow", "arrow": "Arrow", "pointer": "Arrow", "normal select": "Arrow",
    "help": "Help", "help select": "Help",
    "working in background": "AppStarting", "working": "AppStarting",
    "appstarting": "AppStarting", "background": "AppStarting",
    "busy": "Wait", "wait": "Wait",
    "precision": "Crosshair", "precision select": "Crosshair", "cross": "Crosshair",
    "text": "IBeam", "text select": "IBeam", "beam": "IBeam", "ibeam": "IBeam",
    "handwriting": "NWPen", "pen": "NWPen",
    "unavailable": "No", "no": "No",
    "vertical": "SizeNS", "vertical1": "SizeNS", "vertical resize": "SizeNS",
    "horizontal": "SizeWE", "horizontal resize": "SizeWE",
    "diagonal resize 1": "SizeNWSE", "diagonal1": "SizeNWSE", "dgn1": "SizeNWSE",
    "diagonal resize 2": "SizeNESW", "diagonal2": "SizeNESW", "dgn2": "SizeNESW",
    "move": "SizeAll", "move2": "SizeAll",
    "alternative": "UpArrow", "alternative2": "UpArrow", "alternate": "UpArrow",
    "up": "UpArrow",
    "link": "Hand", "link select": "Hand", "hand": "Hand",
    "pin": "Pin", "location": "Pin", "person": "Person",
}

# =============================================================================
# Engines: load a Windows cursor and render it at a given nominal size
# =============================================================================

def _scale_hotspot(hx, hy, src_w, src_h, dst_w, dst_h):
    """Map the centre of the hotspot pixel and clamp inside the new image."""
    nx = int(round((hx + 0.5) * dst_w / src_w - 0.5))
    ny = int(round((hy + 0.5) * dst_h / src_h - 0.5))
    return min(max(nx, 0), dst_w - 1), min(max(ny, 0), dst_h - 1)


def ani_timing(data):
    """Read the timing of an .ani: ([jiffies per step], source, [issues]).

    Static cursors (.cur) return ([], "static", []).
    """
    if data[:4] != b"RIFF" or data[8:12] != b"ACON":
        return [], "static", []
    st = {}

    def walk(pos, end):
        while pos + 8 <= min(end, len(data)):
            cid, size = data[pos:pos + 4], struct.unpack_from("<I", data, pos + 4)[0]
            body = pos + 8
            if cid == b"LIST" and data[body:body + 4] == b"fram":
                walk(body + 4, body + size)
            elif cid == b"anih" and size >= 36:
                st["anih"] = struct.unpack_from("<9I", data, body)
            elif cid in (b"rate", b"seq "):
                st[cid] = list(struct.unpack_from("<%dI" % (size // 4), data, body))
            pos = body + size + (size & 1)

    walk(12, len(data))
    if "anih" not in st:
        return [], "static", ["no anih header"]
    _s, nframes, nsteps, _w, _h, _b, _p, hdr_rate, flags = st["anih"]
    nsteps = nsteps or nframes
    issues = []
    if hdr_rate == 0:
        issues.append("header rate is 0")
    base = hdr_rate or DEFAULT_JIFFIES
    rate = st.get(b"rate")
    if rate:
        if len(rate) != nsteps:
            issues.append("rate chunk has %d entries for %d steps" % (len(rate), nsteps))
        jif = [(rate[i] if i < len(rate) else base) for i in range(nsteps)]
        source = "per-step rate chunk"
    else:
        jif = [base] * nsteps
        source = "header rate" if hdr_rate else "missing (default %d jiffies)" % DEFAULT_JIFFIES
    if any(j == 0 for j in jif):
        issues.append("zero-length steps replaced by %d jiffies" % base)
        jif = [j or base for j in jif]
    return jif, source, issues


def step_delays_ms(jiffies, slowdown_ms):
    """Per-step delays in (float) ms, Windows timing plus the user's slowdown."""
    return [j * 1000.0 / 60.0 + slowdown_ms for j in jiffies]


def merge_steps(keys, delays_ms):
    """Merge consecutive identical frames: -> [(step_index, total_ms)]."""
    out = []
    for i, key in enumerate(keys):
        d = delays_ms[i] if i < len(delays_ms) else (delays_ms[-1] if delays_ms else 0)
        if out and keys[out[-1][0]] == key:
            out[-1][1] += d
        else:
            out.append([i, d])
    if len(out) <= 1:
        return [(out[0][0] if out else 0, 0)]
    return [(i, max(MIN_FRAME_MS, int(round(d)))) for i, d in out]


def _pick_filter(choice, src, dst):
    """'auto' keeps pixel art crisp on exact integer upscales, smooth otherwise."""
    if choice != "auto":
        return choice
    return "nearest" if dst > src and dst % src == 0 else "lanczos"


class Win2xcurEngine:
    """Parse with win2xcur, resize with ImageMagick (Wand), write with win2xcur."""
    name = "win2xcur"

    def __init__(self):
        from win2xcur.parser import open_blob          # noqa: F401 (import check)
        from win2xcur.writer import to_x11             # noqa: F401
        from win2xcur.cursor import CursorFrame, CursorImage  # noqa: F401
        import wand.image                              # noqa: F401
        self._open_blob, self._to_x11 = open_blob, to_x11
        self._Frame, self._Image = CursorFrame, CursorImage

    def convert(self, path, sizes, filt, override, delays_ms):
        """Return (Xcursor bytes, number of animation frames written).

        delays_ms: per original step, from ani_timing(); win2xcur's own delays
        are ignored so both engines share one timing implementation.
        """
        frames = self._open_blob(Path(path).read_bytes()).frames
        bases = [max(fr.images, key=lambda c: c.image.width * c.image.height) for fr in frames]
        keys = [(b.image.signature, b.hotspot) for b in bases]

        out = []
        steps = [(bases[i], ms) for i, ms in merge_steps(keys, delays_ms)]
        for base, ms in steps:
            sw, sh = base.image.width, base.image.height
            hx, hy = override or base.hotspot
            images = []
            for size in sizes:
                scale = size / float(max(sw, sh))
                w, h = max(1, round(sw * scale)), max(1, round(sh * scale))
                img = base.image.clone()
                if (w, h) != (sw, sh):
                    f = _pick_filter(filt, max(sw, sh), size)
                    img.resize(w, h, filter={"nearest": "point"}.get(f, f))
                images.append(self._Image(img, _scale_hotspot(hx, hy, sw, sh, w, h), size))
            # win2xcur stores int(delay * 1000); +0.5 ms keeps our rounding exact.
            out.append(self._Frame(images, (ms + 0.5) / 1000.0 if ms else 0))
        # win2xcur writes frame-major; libXcursor groups by nominal size itself.
        return self._to_x11(out), len(steps)


class PillowEngine:
    """Self-contained fallback: own ANI/CUR parser, Pillow decode, own writer."""
    name = "pillow"
    XC_IMAGE = 0xFFFD0002

    def __init__(self):
        from PIL import Image, IcoImagePlugin
        self.Image, self.Ico = Image, IcoImagePlugin

    # ---- parsing -----------------------------------------------------------
    def _decode_icon(self, blob):
        rsv, typ, count = struct.unpack_from("<HHH", blob, 0)
        if rsv != 0 or typ not in (1, 2) or count < 1:
            raise ValueError("not an ICO/CUR image")
        entries = []
        patched = bytearray(blob)
        patched[2:4] = b"\x01\x00"                     # Pillow only reads type 1
        for i in range(count):
            o = 6 + 16 * i
            w, h, _c, _r, a, b, _sz, off = struct.unpack_from("<BBBBHHII", blob, o)
            # In .cur files these two fields hold the hotspot; Pillow reads them
            # as planes/bpp, so replace them with real values before decoding.
            bpp = 32 if blob[off:off + 4] == b"\x89PNG" else struct.unpack_from("<H", blob, off + 14)[0]
            struct.pack_into("<HH", patched, o + 4, 1, bpp)
            entries.append(((w or 256), (h or 256), a, b))
        w, h, a, b = max(entries, key=lambda e: e[0] * e[1])
        img = self.Ico.IcoFile(io.BytesIO(bytes(patched))).getimage((w, h)).convert("RGBA")
        return img, ((a, b) if typ == 2 else (0, 0))

    def _parse_ani(self, data):
        st = {"anih": None, "icons": [], "seq": None, "rate": None}

        def walk(pos, end):
            while pos + 8 <= min(end, len(data)):
                cid, size = data[pos:pos + 4], struct.unpack_from("<I", data, pos + 4)[0]
                body = pos + 8
                if cid == b"LIST" and data[body:body + 4] == b"fram":
                    walk(body + 4, body + size)
                elif cid == b"anih":
                    st["anih"] = struct.unpack_from("<9I", data, body)
                elif cid == b"icon":
                    st["icons"].append(data[body:body + size])
                elif cid in (b"seq ", b"rate"):
                    st[cid.decode().strip()] = list(struct.unpack_from("<%dI" % (size // 4), data, body))
                pos = body + size + (size & 1)

        walk(12, len(data))
        if not st["anih"] or not st["icons"]:
            raise ValueError("ANI without header or frames")
        _s, _nf, nsteps, _w, _h, _b, _p, _rate, flags = st["anih"]
        if not flags & 1:
            raise ValueError("ANI with raw bitmap frames is not supported")
        frames = [self._decode_icon(b) for b in st["icons"]]
        order = st["seq"] if (flags & 2 and st["seq"]) else list(range(len(frames)))
        order = [i if i < len(frames) else 0 for i in order[:nsteps or None]]
        return frames, order                       # order = frame index per step

    # ---- rendering / writing ----------------------------------------------
    def convert(self, path, sizes, filt, override, delays_ms):
        data = Path(path).read_bytes()
        if data[:4] == b"RIFF":
            frames, order = self._parse_ani(data)
        else:
            frames, order = [self._decode_icon(data)], [0]
        steps = [(order[i], ms) for i, ms in merge_steps(order, delays_ms)]
        Image = self.Image
        filters = {"nearest": Image.Resampling.NEAREST, "lanczos": Image.Resampling.LANCZOS,
                   "mitchell": Image.Resampling.BICUBIC, "box": Image.Resampling.BOX}
        chunks = []
        for size in sizes:
            cache = {}
            for fi, ms in steps:
                if fi not in cache:
                    img, (hx, hy) = frames[fi]
                    if override:
                        hx, hy = override
                    sw, sh = img.size
                    scale = size / float(max(sw, sh))
                    w, h = max(1, round(sw * scale)), max(1, round(sh * scale))
                    if (w, h) != (sw, sh):
                        img = img.resize((w, h), filters[_pick_filter(filt, max(sw, sh), size)])
                    r, g, b, a = img.convert("RGBa").split()      # premultiplied
                    px = Image.merge("RGBA", (b, g, r, a)).tobytes()
                    cache[fi] = (w, h) + _scale_hotspot(hx, hy, sw, sh, w, h) + (px,)
                w, h, nx, ny, px = cache[fi]
                head = struct.pack("<9I", 36, self.XC_IMAGE, size, 1, w, h, nx, ny, ms)
                chunks.append((size, head + px))
        pos = 16 + 12 * len(chunks)
        out = bytearray(b"Xcur" + struct.pack("<3I", 16, 0x10000, len(chunks)))
        for size, blob in chunks:
            out += struct.pack("<3I", self.XC_IMAGE, size, pos)
            pos += len(blob)
        for _s, blob in chunks:
            out += blob
        return bytes(out), len(steps)


def make_engine(choice):
    errors = []
    for cls in ([Win2xcurEngine, PillowEngine] if choice == "auto" else
                [{"win2xcur": Win2xcurEngine, "pillow": PillowEngine}[choice]]):
        try:
            return cls()
        except Exception as e:                         # ImportError, Wand's ImportError, ...
            errors.append("%s: %s" % (cls.name, str(e).splitlines()[0] if str(e) else type(e).__name__))
    sys.exit("No usable conversion engine.\n  " + "\n  ".join(errors) +
             "\nInstall one of:\n"
             "  pip install --user win2xcur   (plus ImageMagick: dnf install ImageMagick-libs |"
             " apt install libmagickwand-6.q16-7 | pacman -S imagemagick)\n"
             "  pip install --user pillow")


# =============================================================================
# Xcursor verification (independent of the engine that wrote the file)
# =============================================================================

def compact_xcursor(data):
    """Store byte-identical image chunks once; TOC entries may share an offset.

    Animations that revisit a frame (seq chunks) otherwise duplicate it at every
    size, which matters at 192/256 px. libXcursor seeks per TOC entry, so this
    is fully compatible.
    """
    _hdr, _ver, ntoc = struct.unpack_from("<3I", data, 4)
    toc, blobs, index = [], [], {}
    for i in range(ntoc):
        typ, sub, pos = struct.unpack_from("<3I", data, 16 + 12 * i)
        hsize, _t, _s, _v, w, h = struct.unpack_from("<6I", data, pos)
        blob = data[pos:pos + hsize + w * h * 4]
        if blob not in index:
            index[blob] = len(blobs)
            blobs.append(blob)
        toc.append((typ, sub, index[blob]))
    base = 16 + 12 * ntoc
    offsets, pos = [], base
    for b in blobs:
        offsets.append(pos)
        pos += len(b)
    out = [data[:16]] + [struct.pack("<3I", t, s, offsets[k]) for t, s, k in toc] + blobs
    return b"".join(out)


def verify_xcursor(path):
    """Return {nominal_size: frame_count}; raise ValueError if malformed."""
    d = Path(path).read_bytes()
    if d[:4] != b"Xcur":
        raise ValueError("%s: bad magic" % path)
    _hdr, _ver, ntoc = struct.unpack_from("<3I", d, 4)
    sizes = {}
    for i in range(ntoc):
        typ, sub, pos = struct.unpack_from("<3I", d, 16 + 12 * i)
        _hs, ctype, csub, _v, w, h, hx, hy, _dl = struct.unpack_from("<9I", d, pos)
        if (ctype, csub) != (typ, sub) or hx >= w or hy >= h or w > 0x7FFF or h > 0x7FFF:
            raise ValueError("%s: chunk %d inconsistent" % (path, i))
        if pos + 36 + w * h * 4 > len(d):
            raise ValueError("%s: chunk %d truncated" % (path, i))
        sizes[sub] = sizes.get(sub, 0) + 1
    return sizes


# =============================================================================
# Source discovery
# =============================================================================

def safe_extract(zip_path, dest):
    dest = Path(dest).resolve()
    with zipfile.ZipFile(zip_path) as z:
        for m in z.infolist():
            target = (dest / m.filename).resolve()
            if dest != target and dest not in target.parents:
                raise ValueError("unsafe path in zip: %s" % m.filename)
        z.extractall(dest)


def _read_inf(path):
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-16", "cp1252"):
        try:
            text = raw.decode(enc)
            if "[" in text:
                break
        except UnicodeError:
            continue
    cp = configparser.RawConfigParser(strict=False, delimiters=("=",),
                                      comment_prefixes=(";",), allow_no_value=True)
    cp.optionxform = str
    cp.read_string(text)
    return cp, text


def roles_from_inf(root):
    """Use the scheme registry line of an Installer .inf to map files to roles.

    Returns (scheme_name or None, {role: filename}) or (None, {}) if unusable.
    """
    for inf in sorted(Path(root).rglob("*.inf")):
        try:
            cp, text = _read_inf(inf)
        except (configparser.Error, UnicodeError):
            continue
        strings = {}
        for sec in cp.sections():
            if sec.lower() == "strings":
                strings = {k.lower(): (v or "").strip().strip('"') for k, v in cp.items(sec)}
        m = re.search(r'Cursors\\Schemes"\s*,\s*"?([^",]*)"?\s*,[^,]*,\s*"([^"]+)"', text)
        if not m:
            continue

        def expand(s):
            return re.sub(r"%(\w+)%", lambda k: strings.get(k.group(1).lower(), ""), s)

        scheme = expand(m.group(1)).strip() or None
        files = [expand(p).replace("\\", "/").rsplit("/", 1)[-1].strip()
                 for p in m.group(2).split(",")]
        roles = {SCHEME_ORDER[i]: f for i, f in enumerate(files[:len(SCHEME_ORDER)]) if f}
        if roles:
            return scheme, roles
    return None, {}


def collect_sources(root):
    """Return (scheme_name, {role: Path}, [unassigned paths], how)."""
    files = {}
    for p in sorted(Path(root).rglob("*")):
        if p.is_file() and p.suffix.lower() in (".ani", ".cur"):
            files.setdefault(p.name.lower(), p)
    scheme, inf_roles = roles_from_inf(root)
    roles, how = {}, "filenames"
    for role, fname in inf_roles.items():
        if fname.lower() in files:
            roles[role] = files[fname.lower()]
    if roles:
        how = "Installer .inf"
    used = set(roles.values())
    for p in files.values():                            # fill gaps by filename
        role = FILENAME_ROLES.get(p.stem.lower())
        if p not in used and role and role not in roles:
            roles[role] = p
            used.add(p)
    unassigned = [p for p in files.values() if p not in used]
    return scheme, roles, unassigned, how


# =============================================================================
# Theme assembly
# =============================================================================

def check_tables():
    seen = {}
    for role, names in ROLE_MAP.items():
        for n in names:
            if n in seen:
                sys.exit("config error: '%s' is listed under both %s and %s" % (n, seen[n], role))
            seen[n] = role
    for n, target in FALLBACKS.items():
        if target not in seen:
            sys.exit("config error: fallback target '%s' is not in ROLE_MAP" % target)


def build_theme(theme_dir, engine, roles, sizes, filt, env, name, inherits, comment, slowdown):
    cdir = Path(theme_dir) / "cursors"
    cdir.mkdir(parents=True)
    provided, report = set(), []
    for role, names in ROLE_MAP.items():
        src = roles.get(role)
        if not src:
            continue
        jiffies, tsource, issues = ani_timing(src.read_bytes())
        delays = step_delays_ms(jiffies, slowdown)
        data, nframes = engine.convert(src, sizes, filt, HOTSPOT_OVERRIDES.get(role), delays)
        (cdir / names[0]).write_bytes(compact_xcursor(data))
        found = verify_xcursor(cdir / names[0])
        if sorted(found) != sorted(sizes):
            raise ValueError("%s: expected sizes %s, got %s" % (names[0], sizes, sorted(found)))
        for alias in names[1:]:
            os.symlink(names[0], cdir / alias)
            provided.add(alias)
        provided.add(names[0])
        timing = None
        if jiffies and nframes > 1:
            windows_ms = sum(jiffies) * 1000.0 / 60.0
            timing = (len(jiffies), windows_ms, sum(delays), tsource, issues)
        report.append((role, src.name, names[0], nframes, timing, len(names) - 1))
    for n, target in FALLBACKS.items():
        if n not in provided and target in provided:
            os.symlink(os.readlink(cdir / target) if (cdir / target).is_symlink() else target,
                       cdir / n)

    meta = "[Icon Theme]\nName=%s\nComment=%s\nInherits=%s\n" % (name, comment, inherits)
    (Path(theme_dir) / "index.theme").write_text(meta)
    (Path(theme_dir) / "cursor.theme").write_text(meta)     # read by some KDE/X11 tools
    (Path(theme_dir) / "README.txt").write_text(
        "%s - Xcursor theme generated by wincurtolinux.py (%s engine).\n"
        "Sizes: %s\nAnimation: Windows timing%s\nSource: %s\n\n"
        "Uninstall: delete this directory, then pick another cursor theme.\n"
        % (name, engine.name, ", ".join(map(str, sizes)),
           " +%g ms per step" % slowdown if slowdown else "", comment))
    return report


# =============================================================================
# Environment detection: OS, container, session, desktop, install locations
# =============================================================================

DESKTOPS = ["kde", "gnome", "cinnamon", "mate", "xfce", "budgie", "lxqt",
            "sway", "hyprland", "other"]

# XDG_CURRENT_DESKTOP / DESKTOP_SESSION token -> desktop key
_DESKTOP_TOKENS = {
    "kde": "kde", "plasma": "kde", "gnome": "gnome", "gnome-classic": "gnome",
    "ubuntu": "gnome", "unity": "gnome", "pantheon": "gnome", "pop": "gnome",
    "x-cinnamon": "cinnamon", "cinnamon": "cinnamon", "mate": "mate",
    "xfce": "xfce", "budgie": "budgie", "budgie-desktop": "budgie",
    "lxqt": "lxqt", "sway": "sway", "hyprland": "hyprland",
}


def _os_release(root=""):
    info = {}
    for p in (root + "/etc/os-release", root + "/usr/lib/os-release"):
        try:
            for line in Path(p).read_text().splitlines():
                k, _, v = line.partition("=")
                if k and v:
                    info[k.strip()] = v.strip().strip('"')
            break
        except OSError:
            continue
    return info


def detect_env():
    e = {}
    e["container"] = (os.environ.get("CONTAINER_ID")
                      or ("toolbox" if os.environ.get("TOOLBOX_PATH") else None)
                      or ("flatpak" if Path("/.flatpak-info").exists() else None)
                      or ("container" if Path("/run/.containerenv").exists()
                          or Path("/.dockerenv").exists() else None))
    # In distrobox/toolbox the host's root is visible at /run/host.
    host_root = "/run/host" if e["container"] and Path("/run/host/etc").exists() else ""
    osr = _os_release(host_root) or _os_release()
    e["os"] = osr.get("PRETTY_NAME") or osr.get("NAME") or "Linux"
    e["os_id"] = osr.get("ID", "")
    e["immutable"] = (Path(host_root + "/run/ostree-booted").exists()
                      or e["os_id"] in ("nixos",)
                      or "ostree" in osr.get("VARIANT_ID", ""))
    e["session"] = os.environ.get("XDG_SESSION_TYPE") or \
        ("wayland" if os.environ.get("WAYLAND_DISPLAY") else
         "x11" if os.environ.get("DISPLAY") else "unknown")

    home = Path.home()
    host_home = os.environ.get("DISTROBOX_HOST_HOME")
    e["home"] = Path(host_home) if host_home and Path(host_home).is_dir() else home
    e["home_redirected"] = e["home"] != home

    desk = None
    for var in ("XDG_CURRENT_DESKTOP", "XDG_SESSION_DESKTOP", "DESKTOP_SESSION"):
        for tok in re.split(r"[:;]", os.environ.get(var, "").lower()):
            tok = tok.strip().rsplit("/", 1)[-1]
            if tok in _DESKTOP_TOKENS:
                desk = _DESKTOP_TOKENS[tok]
                break
            if tok.startswith("plasma"):
                desk = "kde"
                break
        if desk:
            break
    if not desk:
        if os.environ.get("KDE_FULL_SESSION"):
            desk = "kde"
        elif os.environ.get("GNOME_DESKTOP_SESSION_ID"):
            desk = "gnome"
        elif os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
            desk = "hyprland"
        elif os.environ.get("SWAYSOCK"):
            desk = "sway"
    e["desktop"] = desk
    e["host_root"] = host_root
    return e


def xcursor_search_path(env):
    """Directories cursor *loaders* search, in order (libXcursor rules)."""
    raw = os.environ.get("XCURSOR_PATH")
    if raw:
        dirs = [d for d in raw.split(":") if d]
    else:
        dirs = ["~/.local/share/icons", "~/.icons", "/usr/share/icons", "/usr/share/pixmaps"]
    return [Path(str(env["home"]) + d[1:]) if d.startswith("~") else Path(d) for d in dirs]


def choose_user_dest(env):
    """~/.icons: the only user directory Plasma's cursor list scans, and one
    that libXcursor, GTK/GNOME and wlroots compositors all search too."""
    dest = env["home"] / ".icons"
    if os.environ.get("XCURSOR_PATH"):
        search = xcursor_search_path(env)
        if dest not in search:
            mine = [d for d in search if env["home"] in d.parents or d == env["home"]]
            if mine:
                print("  note: XCURSOR_PATH is set and omits ~/.icons; using %s" % mine[0])
                return mine[0]
            print("  warning: XCURSOR_PATH is set and contains no directory in your home;"
                  " the theme may not be found until you add %s to it" % dest)
    return dest


def choose_system_dest(env):
    if env["immutable"]:
        # /usr is read-only on ostree/NixOS; /usr/local maps to writable storage.
        return Path("/usr/local/share/icons")
    return Path("/usr/share/icons")


def find_installed_theme(env, candidates):
    roots = [env["home"] / ".icons", env["home"] / ".local/share/icons"]
    for d in os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(":"):
        if d:
            roots.append(Path(d) / "icons")
    roots += [Path("/usr/share/icons")]
    if env["host_root"]:
        roots += [Path(env["host_root"] + "/usr/share/icons")]
    for name in candidates:
        if any((r / name / "cursors").is_dir() or (r / name / "index.theme").is_file()
               for r in roots):
            return name
    return candidates[0]


def host_runner(env):
    """Prefix that runs a command on the host session when inside a container."""
    if not env["container"]:
        return []
    for tool in (["distrobox-host-exec"], ["host-spawn"], ["flatpak-spawn", "--host"]):
        if shutil.which(tool[0]):
            return tool
    return []


def activation_plan(desktop, name, size):
    """-> (command list or None, GUI hint, extra manual hint)."""
    n, s = name, str(size)
    plans = {
        "kde": (["plasma-apply-cursortheme", n],
                "System Settings > Colours & Themes > Cursors", None),
        "gnome": (["gsettings", "set", "org.gnome.desktop.interface", "cursor-theme", n],
                  "GNOME Tweaks > Appearance > Cursor", None),
        "budgie": (["gsettings", "set", "org.gnome.desktop.interface", "cursor-theme", n],
                   "Budgie Desktop Settings > Style > Cursor", None),
        "cinnamon": (["gsettings", "set", "org.cinnamon.desktop.interface", "cursor-theme", n],
                     "System Settings > Themes > Mouse Pointer", None),
        "mate": (["gsettings", "set", "org.mate.peripherals-mouse", "cursor-theme", n],
                 "Control Center > Appearance > Theme > Customize > Pointer", None),
        "xfce": (["xfconf-query", "-c", "xsettings", "-p", "/Gtk/CursorThemeName",
                  "-n", "-t", "string", "-s", n],
                 "Settings > Mouse and Touchpad > Theme", None),
        "lxqt": (None, "LXQt Configuration Center > Appearance > Cursor", None),
        "sway": (["swaymsg", "seat * xcursor_theme %s %s" % (n, s)], None,
                 "make it permanent: add 'seat * xcursor_theme %s %s' to ~/.config/sway/config"
                 % (n, s)),
        "hyprland": (["hyprctl", "setcursor", n, s], None,
                     "make it permanent: add 'env = XCURSOR_THEME,%s' and "
                     "'env = XCURSOR_SIZE,%s' to ~/.config/hypr/hyprland.conf" % (n, s)),
        "other": (None, None,
                  "set XCURSOR_THEME=%s (and XCURSOR_SIZE=%s) in your session, or put "
                  "'[Icon Theme]\\nInherits=%s' in ~/.icons/default/index.theme" % (n, s, n)),
    }
    return plans[desktop]


def activate(env, desktop, name, size, apply):
    cmd, gui, extra = activation_plan(desktop, name, size)
    if cmd:
        full = host_runner(env) + cmd
        shown = " ".join(c if " " not in c else "'%s'" % c for c in cmd)
        if apply:
            try:
                subprocess.run(full, check=True)
                print("Theme activated.")
            except (OSError, subprocess.CalledProcessError) as e:
                print("Could not activate automatically (%s). Run on the host:\n  %s"
                      % (e, shown))
        else:
            print("Activate with:\n  %s" % shown)
    if gui:
        print("Or: %s." % gui)
    if extra:
        print("To %s" % extra if extra.startswith("make") else "Activate: %s" % extra)
    print("Restart apps (or log out/in) if some keep the old cursor.")


def make_archive(theme_dir, out_dir, tmp):
    """Pack theme_dir as <name>/... into .tar.xz and .tar.gz; keep the smaller.

    Symlinks are stored as symlinks, ownership is neutralised so the archive
    unpacks cleanly for any user. Returns the path of the kept archive.
    """
    theme_dir = Path(theme_dir)

    def neutral(ti):
        ti.uid = ti.gid = 0
        ti.uname = ti.gname = ""
        return ti

    candidates = []
    for ext, mode, kw in ((".tar.xz", "w:xz", {"preset": 9 | lzma.PRESET_EXTREME}),
                          (".tar.gz", "w:gz", {"compresslevel": 9})):
        path = Path(tmp) / (theme_dir.name + ext)
        with tarfile.open(path, mode, **kw) as tf:
            tf.add(theme_dir, arcname=theme_dir.name, filter=neutral)
        candidates.append(path)
    sizes = {p: p.stat().st_size for p in candidates}
    best = min(candidates, key=sizes.get)
    print("Archive: %s" % ", ".join("%s %s" % (p.name, human(sizes[p])) for p in candidates)
          + " -> keeping %s" % best.name)
    out_dir = Path(out_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    final = out_dir / best.name
    shutil.copyfile(best, final)
    return final


def human(n):
    for unit in ("B", "KiB", "MiB", "GiB"):
        if n < 1024:
            return "%.1f %s" % (n, unit)
        n /= 1024.0
    return "%.1f TiB" % n


# =============================================================================
# CLI
# =============================================================================

def main():
    ap = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[0].split(" - ", 1)[1],
        epilog="Edit ROLE_MAP / FALLBACKS / SIZES / ANIMATION_SLOWDOWN_MS at the top of "
               "the script to customise.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", help="ZIP file or directory containing .ani/.cur files")
    ap.add_argument("--desktop", choices=["auto"] + DESKTOPS, default="auto",
                    help="target desktop (default: detect; asks if unknown)")
    ap.add_argument("--name", help="theme name (default: scheme name from the .inf, else the input name)")
    ap.add_argument("--sizes", type=int, nargs="+", default=SIZES, metavar="PX",
                    help="nominal sizes (default: %s)" % " ".join(map(str, SIZES)))
    ap.add_argument("--slowdown", type=float, default=None, metavar="MS",
                    help="add MS milliseconds to every animation step (default %g = exact "
                    "Windows timing)" % ANIMATION_SLOWDOWN_MS)
    ap.add_argument("--filter", choices=["auto", "lanczos", "nearest", "mitchell", "box"],
                    default="auto", help="scaling filter; auto = nearest for integer upscales, "
                    "lanczos otherwise (default)")
    ap.add_argument("--engine", choices=["auto", "win2xcur", "pillow"], default="auto")
    ap.add_argument("--dest", type=Path,
                    help="icon directory to install into (default: detected, normally ~/.icons)")
    ap.add_argument("--system", action="store_true",
                    help="install for all users (/usr/share/icons, or /usr/local/share/icons on "
                    "immutable systems); run the script as root yourself")
    ap.add_argument("--inherits", help="fallback cursor theme (default: detected)")
    ap.add_argument("--cursor-size", type=int, default=24,
                    help="size used when activating on sway/Hyprland (default 24)")
    ap.add_argument("--out", type=Path, help="write the built theme here instead of installing")
    ap.add_argument("--force", action="store_true",
                    help="replace an existing theme/archive without asking")
    ap.add_argument("--archive-dir", type=Path, default=Path.cwd(),
                    help="where to write the .tar.xz/.tar.gz theme archive (default: current dir)")
    ap.add_argument("--no-archive", action="store_true", help="don't write a theme archive")
    ap.add_argument("--dry-run", action="store_true", help="build in a temp dir and report only")
    ap.add_argument("--apply", action="store_true", help="activate the theme after installing")
    args = ap.parse_args()

    check_tables()
    sizes = sorted(set(args.sizes))
    if any(s < 8 or s > 512 for s in sizes):
        sys.exit("sizes must be between 8 and 512")
    slowdown = ANIMATION_SLOWDOWN_MS if args.slowdown is None else args.slowdown
    if not 0 <= slowdown <= 5000:
        sys.exit("--slowdown must be between 0 and 5000 ms")
    inp = Path(args.input).expanduser()
    if not inp.exists():
        sys.exit("input not found: %s" % inp)

    env = detect_env()
    desktop = None if args.desktop == "auto" else args.desktop
    desktop = desktop or env["desktop"]
    if not desktop:
        if sys.stdin.isatty():
            while desktop not in DESKTOPS:
                desktop = input("Desktop not detected. Which one? [%s]: "
                                % "/".join(DESKTOPS)).strip().lower()
        else:
            desktop = "other"
    inherits = args.inherits or find_installed_theme(env, INHERITS.get(desktop, INHERITS["*"]))

    print("System: %s%s | session: %s | desktop: %s%s"
          % (env["os"], " (immutable)" if env["immutable"] else "", env["session"], desktop,
             "" if env["desktop"] or args.desktop != "auto" else " (not detected)"))
    if env["container"]:
        print("  note: running inside a container (%s)%s" % (
            env["container"], "; installing into the host home %s" % env["home"]
            if env["home_redirected"] else ""))

    if args.out:
        dest_root = args.out.expanduser()
    elif args.dest:
        dest_root = args.dest.expanduser()
    elif args.system:
        dest_root = choose_system_dest(env)
    else:
        dest_root = choose_user_dest(env)
    if args.system and not args.out and not args.dry_run:
        probe = dest_root if dest_root.exists() else dest_root.parent
        if not os.access(probe, os.W_OK):
            sys.exit("%s is not writable; rerun this script as root for --system" % dest_root)
        if env["immutable"] and desktop == "kde":
            print("  note: Plasma's cursor list doesn't scan %s; a per-user install is "
                  "recommended on this system" % dest_root)

    engine = make_engine(args.engine)
    with tempfile.TemporaryDirectory(prefix="wincurtolinux_") as tmp:
        tmp = Path(tmp)
        src_root = inp
        if inp.is_file():
            if not zipfile.is_zipfile(inp):
                sys.exit("input file is not a ZIP archive")
            src_root = tmp / "src"
            safe_extract(inp, src_root)

        scheme, roles, unassigned, how = collect_sources(src_root)
        if not roles:
            sys.exit("no .ani/.cur files with a recognisable role found in %s" % inp)
        name = args.name or scheme or re.sub(r"\s+", "_", inp.stem)
        name = re.sub(r"[^A-Za-z0-9_.-]", "_", name)
        comment = "Converted from the Windows cursor scheme '%s'" % (scheme or inp.name)

        print("Engine: %s | theme: %s | roles from %s | fallback: %s"
              % (engine.name, name, how, inherits))
        print("Sizes: %s (sizes above the source resolution are upscaled)"
              % " ".join(map(str, sizes)))
        print("Animation: Windows timing (1 jiffy = 1/60 s)%s"
              % (" + %g ms per step" % slowdown if slowdown else ", exact"))
        for p in unassigned:
            print("  note: %s has no role - add it to FILENAME_ROLES to use it" % p.name)
        missing = [r for r in SCHEME_ORDER[:15] if r not in roles]
        if missing:
            print("  note: no artwork for %s - inherited from %s" % (", ".join(missing), inherits))

        built = tmp / "build" / name
        report = build_theme(built, engine, roles, sizes, args.filter, env, name,
                             inherits, comment, slowdown)
        warned = []
        for role, src, prim, nframes, timing, nal in report:
            if timing:
                nsteps, win_ms, out_ms, tsource, issues = timing
                kind = "%2d frames, %4.2f s loop" % (nframes, out_ms / 1000.0)
                if slowdown:
                    kind += " (Windows %4.2f s)" % (win_ms / 1000.0)
                if tsource != "per-step rate chunk" and tsource != "header rate" or issues:
                    warned.append("%s: timing %s%s" % (src, tsource,
                                  "; " + "; ".join(issues) if issues else ""))
            else:
                kind = "static"
            print("  %-12s %-26s -> %-12s %s, +%d aliases" % (role, src, prim, kind, nal))
        for w in warned:
            print("  timing note: %s - use --slowdown MS if it plays too fast" % w)
        entries = list((built / "cursors").iterdir())
        total = sum(p.stat().st_size for p in entries if not p.is_symlink())
        print("Theme: %d cursor names, %s" % (len(entries), human(total)))

        if args.dry_run:
            print("Dry run: nothing written (would install to %s)." % (dest_root / name))
            return

        archive = None
        if not args.no_archive:
            stale = [args.archive_dir.expanduser() / (name + e) for e in (".tar.xz", ".tar.gz")]
            stale = [p for p in stale if p.exists()]
            if stale and not args.force and (not sys.stdin.isatty() or input(
                    "%s exists. Replace? [y/N] " % stale[0]).strip().lower() != "y"):
                print("Archive skipped (exists; use --force to overwrite).")
            else:
                for p in stale:
                    p.unlink()
                archive = make_archive(built, args.archive_dir, tmp)

        target = dest_root / name
        if target.exists() or target.is_symlink():
            if not args.force:
                if not sys.stdin.isatty() or \
                        input("%s exists. Replace? [y/N] " % target).strip().lower() != "y":
                    sys.exit("aborted; use --force to overwrite")
            shutil.rmtree(target) if target.is_dir() and not target.is_symlink() else target.unlink()
        dest_root.mkdir(parents=True, exist_ok=True)
        shutil.copytree(built, target, symlinks=True)

    print("\nWritten to %s" % target)
    if archive:
        print("Theme archive: %s\n  (for your desktop's 'install from file' option, or to share)"
              % archive)
    if args.out:
        print("Copy that folder into %s/ to install it." % (env["home"] / ".icons"))
        return
    activate(env, desktop, name, args.cursor_size, args.apply)
    print("Flatpak apps: flatpak override --user --filesystem=%s:ro" % dest_root)
    for other in xcursor_search_path(env) + [env["home"] / ".icons"]:
        stale = other / name
        if stale.exists() and stale.resolve() != target.resolve():
            print("Warning: another copy exists at %s and may take precedence;"
                  " remove it with: rm -rf '%s'" % (stale, stale))
    print("Uninstall: rm -rf '%s'" % target)


if __name__ == "__main__":
    main()
