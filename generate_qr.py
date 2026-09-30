#!/usr/bin/env python3
"""
Adel Restaurant - QR code generator
====================================

Builds a scannable QR code styled to match the restaurant artwork
(gold / dark-cherry / wood palette, dotted modules, elegant framing)
and points it at your hosted landing page.

Two output modes
----------------
  code  -> just the QR artwork (PNG + SVG)
  card  -> the full designed table card: framed QR + Persian caption
           rendered with a real browser, so the Persian text is shaped
           correctly. This is what you print.

Usage
-----
  python generate_qr.py --url https://adel-restaurant.pages.dev --mode card
  python generate_qr.py --url https://adel-restaurant.pages.dev --eyes circle
  python generate_qr.py --url https://... --no-logo

IMPORTANT
---------
Always test-scan the result on the exact phones your guests use before
printing a batch. Styling a QR code always costs some reliability headroom,
so this script uses the highest error correction (H = ~30% recovery) and
caps the centre logo at 22% of the code width.
"""

from __future__ import annotations

import argparse
import html
import io
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import qrcode
from PIL import Image, ImageDraw
from qrcode.constants import (
    ERROR_CORRECT_H,
    ERROR_CORRECT_L,
    ERROR_CORRECT_M,
    ERROR_CORRECT_Q,
)
from qrcode.util import pattern_position

HERE = Path(__file__).resolve().parent

# --------------------------------------------------------------------------
# Palette - sampled from the artwork
# --------------------------------------------------------------------------
PALETTES = {
    # "cherry" matches the press-ready artwork: ivory stock, cocoa dots,
    # crimson rings on the three eyes.
    "cherry": {
        "bg": "#F2EDE3",        # ivory paper
        "dark": "#3B2412",      # cocoa dots          (contrast 12.6:1)
        "gold": "#6B4410",      # warm brown accent   (contrast  7.0:1)
        "frame": "#8C1A2B",     # crimson
        "rich_gold": "#8C1A2B",
    },
    # name: (background, primary dark, secondary accent, frame)
    "brandy": {
        "bg": "#F5F0E6",        # ivory paper
        "dark": "#402C19",      # dark cherry / cocoa  (contrast 11.6:1)
        "gold": "#7A5C12",      # antique gold        (contrast  5.5:1)
        "frame": "#8B6F47",     # wood
        "rich_gold": "#A8842C", # decorative only, never for modules
    },
    "noir": {
        "bg": "#0A0A0A",
        "dark": "#F5F0E6",
        "gold": "#C9A84C",
        "frame": "#8B6F47",
        "rich_gold": "#E8D48B",
    },
}

# Layout constants, in SVG user units. 1 module = MODULE units.
MODULE = 10
QUIET = 4            # quiet zone, in modules (spec minimum is 4)
# Dot radius as a fraction of a module. Measured against a real decoder:
# 0.40 and below fails to decode, 0.46 and above is reliable. 0.48 keeps the
# dotted look while staying well clear of the failure edge.
DOT_RATIO = 0.48


# --------------------------------------------------------------------------
# QR construction
# --------------------------------------------------------------------------
def build_matrix(url: str, ecc):
    qr = qrcode.QRCode(
        version=None,
        error_correction=ecc,
        box_size=MODULE,
        border=0,          # we draw our own quiet zone
    )
    qr.add_data(url)
    qr.make(fit=True)
    return qr.get_matrix(), qr.version


def in_finder(row: int, col: int, n: int) -> bool:
    """True inside a finder pattern or its 1-module separator.

    The bottom-right corner deliberately has no finder, so alignment patterns
    can live there.
    """
    if row < 8 and col < 8:
        return True
    if row < 8 and col >= n - 8:
        return True
    if row >= n - 8 and col < 8:
        return True
    return False


def alignment_centers(version: int, n: int):
    """Return [(row, col), ...] centres of the alignment patterns.

    qrcode's PATTERN_POSITION_TABLE holds a list of *coordinate values* for the
    version, e.g. [6, 26] for version 4 - not (row, col) pairs. The real
    positions are the full cross product of those coordinates, minus the three
    that would collide with a finder pattern. For version 4 that leaves a
    single pattern at (26, 26); without it the code cannot be detected.
    """
    if version < 2:
        return []
    coords = list(pattern_position(version))
    first, last = coords[0], coords[-1]
    out = []
    for r in coords:
        for c in coords:
            # the three that overlap a finder + separator are omitted
            if (r, c) in ((first, first), (first, last), (last, first)):
                continue
            out.append((r, c))
    return out


def alignment_cells(version: int, n: int):
    """Yield (row, col) module coordinates covered by alignment patterns."""
    for (ar, ac) in alignment_centers(version, n):
        for dr in range(-2, 3):
            for dc in range(-2, 3):
                r, c = ar + dr, ac + dc
                if 0 <= r < n and 0 <= c < n:
                    yield r, c


def _tone(row: int, col: int, gold_pct: int) -> bool:
    """Deterministic pseudo-random two-tone split, so the art is stable."""
    h = ((row * 73856093) ^ (col * 19349663) ^ (row * col * 83492791)) & 0xFFFFFFFF
    return (h % 100) < gold_pct


# --------------------------------------------------------------------------
# Self-check: does the rendered image still decode to the URL?
# --------------------------------------------------------------------------
def verify_png(png_path: Path, expected: str, colors) -> bool | None:
    """Decode the rendered PNG and compare against the expected URL.

    Returns True/False, or None when no decoder is available. A styled QR has
    less margin than a plain one, so this is the cheapest way to catch a
    palette or geometry mistake before a print run.

    zxing-cpp is tried first: it is the strictest of the two and behaves most
    like a phone. OpenCV is more forgiving and will happily accept codes a
    real camera would struggle with, so a pass there alone is not enough.
    """
    img = Image.open(png_path).convert("RGB")

    results = {}

    try:
        import zxingcpp
        res = zxingcpp.read_barcodes(img)
        results["zxing"] = res[0].text.strip() if res else ""
    except ImportError:
        pass

    try:
        import cv2
        import numpy as np
        data, _, _ = cv2.QRCodeDetector().detectAndDecode(np.array(img))
        results["opencv"] = (data or "").strip()
    except ImportError:
        pass

    if not results:
        print("  · no decoder installed. Install one to auto-verify:")
        print("    pip install zxing-cpp opencv-python-headless")
        return None

    want = expected.strip()
    # zxing is the authority: it is strict and behaves like a phone. OpenCV is
    # much weaker on dotted or stylised codes, so a failure there alone is
    # reported but does not block the build.
    for name, got in results.items():
        if not got:
            print(f"  FAIL {name}: could not read the code")
        elif got != want:
            print(f"  FAIL {name}: read the wrong payload -> {got}")
        else:
            print(f"  OK   {name}: decoded to the expected URL")

    if "zxing" in results:
        return results["zxing"] == want
    if "opencv" in results:
        return results["opencv"] == want
    return None


def verify_print_sizes(card_path: Path, expected: str, args) -> None:
    """Downscale the card the way a printer or a phone camera would.

    A code that only reads at full resolution is not fit for a table card, so
    this is the check that actually matters before a print run.
    """
    try:
        import zxingcpp
    except ImportError:
        return
    base = Image.open(card_path).convert("RGB")
    w, h = base.size
    want = expected.strip()
    worst = None
    for target in (1200, 900, 700, 500, 400):
        small = base.resize((target, max(1, int(h * target / w))), Image.LANCZOS)
        res = zxingcpp.read_barcodes(small)
        ok = bool(res) and res[0].text.strip() == want
        print(f"  {'OK  ' if ok else 'FAIL'} at {target}px wide")
        if not ok and worst is None:
            worst = target
    if worst:
        print(f"  ! stops reading at {worst}px. Print the code at least "
              f"{worst * 1.5:.0f}px wide, or use --eyes square.")


def verify_geometry(matrix, colors) -> bool:
    """Structural checks that need no decoder."""
    n = len(matrix)
    problems = []

    # 1. finder patterns must be intact
    for (er, ec) in [(0, 0), (0, n - 7), (n - 7, 0)]:
        ok = True
        for r in range(7):
            for c in range(7):
                want = (r in (0, 6) or c in (0, 6)
                        or (2 <= r <= 4 and 2 <= c <= 4))
                if bool(matrix[er + r][ec + c]) != want:
                    ok = False
        if not ok:
            problems.append(f"finder at ({er},{ec}) is malformed")

    # 2. timing patterns must alternate, dark on even indices
    for i in range(8, n - 8):
        want = (i % 2 == 0)
        if bool(matrix[6][i]) != want:
            problems.append(f"horizontal timing break at col {i}")
            break
    for i in range(8, n - 8):
        want = (i % 2 == 0)
        if bool(matrix[i][6]) != want:
            problems.append(f"vertical timing break at row {i}")
            break

    # 3. dark module bit must be present
    if not matrix[n - 8][8]:
        problems.append("dark module missing")

    # 4. contrast of the two module tones against the paper
    def rel_lum(hexstr):
        hexstr = hexstr.lstrip("#")
        out = []
        for k in (0, 2, 4):
            c = int(hexstr[k:k + 2], 16) / 255
            out.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
        return 0.2126 * out[0] + 0.7152 * out[1] + 0.0722 * out[2]

    def ratio(a, b):
        la, lb = rel_lum(a), rel_lum(b)
        hi, lo = max(la, lb), min(la, lb)
        return (hi + 0.05) / (lo + 0.05)

    for name in ("dark", "gold"):
        cr = ratio(colors[name], colors["bg"])
        flag = "OK " if cr >= 4.5 else "LOW"
        print(f"  {flag} contrast {name} on paper: {cr:.1f}:1")
        if cr < 4.5:
            problems.append(f"{name} module contrast only {cr:.1f}:1")

    for p in problems:
        print(f"  ! {p}")
    return not problems


# --------------------------------------------------------------------------
# SVG rendering
# --------------------------------------------------------------------------
def render_svg(matrix, colors, eyes: str = "artwork", gold_pct: int = 45,
               logo_svg: str = "", logo_frac: float = 0.0) -> str:
    n = len(matrix)
    span = (n + QUIET * 2) * MODULE
    bg, dark, gold = colors["bg"], colors["dark"], colors["gold"]

    def cx(c):  # centre x of module c, in user units
        return (QUIET + c + 0.5) * MODULE

    def cy(r):
        return (QUIET + r + 0.5) * MODULE

    align = set(alignment_cells(VERSION, n))
    align_centres = alignment_centers(VERSION, n)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {span} {span}" '
        f'width="{span}" height="{span}" shape-rendering="geometricPrecision">',
        f'<rect width="{span}" height="{span}" fill="{bg}"/>',
        f'<g fill="{dark}">',
    ]

    # --- data modules as dots -------------------------------------------
    r_dot = MODULE * DOT_RATIO
    for r in range(n):
        for c in range(n):
            if in_finder(r, c, n):
                continue
            if (r, c) in align:
                continue  # drawn as a solid shape below
            if not matrix[r][c]:
                continue
            fill = f' fill="{gold}"' if _tone(r, c, gold_pct) else ""
            parts.append(
                f'<circle cx="{cx(c):.2f}" cy="{cy(r):.2f}" r="{r_dot:.2f}"{fill}/>'
            )
    parts.append("</g>")

    # --- alignment patterns ---------------------------------------------
    # Strokes are centred on the path, so the rect must be inset by half the
    # stroke width. Otherwise the ring spills a half module into neighbouring
    # data and corrupts the code.
    align_ring = colors.get("frame", dark)
    sw = MODULE
    a_s = 5 * MODULE - sw          # path size for a 5-module outer footprint
    for (ar, ac) in align_centres:
        x0 = (QUIET + ac + 0.5) * MODULE - a_s / 2
        y0 = (QUIET + ar + 0.5) * MODULE - a_s / 2
        parts.append(
            f'<rect x="{x0:.2f}" y="{y0:.2f}" width="{a_s:.2f}" height="{a_s:.2f}" '
            f'rx="{a_s * 0.28:.2f}" fill="none" stroke="{align_ring}" '
            f'stroke-width="{sw:.2f}"/>'
        )
        parts.append(
            f'<circle cx="{(QUIET + ac + 0.5) * MODULE:.2f}" cy="{(QUIET + ar + 0.5) * MODULE:.2f}" '
            f'r="{0.5 * MODULE:.2f}" fill="{dark}"/>'
        )

    # --- finder patterns (the "eyes") ------------------------------------
    eye_centres = [
        (0, 0), (0, n - 7), (n - 7, 0),
    ]
    # Only two eye shapes survive a real decoder. A thin ring loses the outer
    # corners the detector locks onto, so the artwork eye is a solid disc with
    # a knocked-out gap and a solid core: it reads as a crimson ring to the eye,
    # but keeps the full 7-module footprint the scanner needs.
    eye_ring = colors.get("frame", gold)   # crimson on the "cherry" artwork
    for (er, ec) in eye_centres:
        mx, my = cx(ec), cy(er)
        if eyes == "square":
            s = 7 * MODULE - MODULE
            parts.append(
                f'<rect x="{mx - s / 2:.2f}" y="{my - s / 2:.2f}" width="{s}" height="{s}" '
                f'fill="none" stroke="{dark}" stroke-width="{MODULE:.2f}"/>'
            )
            s3 = 3 * MODULE
            parts.append(
                f'<rect x="{mx - s3 / 2:.2f}" y="{my - s3 / 2:.2f}" width="{s3}" height="{s3}" '
                f'rx="{MODULE * 0.6:.2f}" fill="{dark}"/>'
            )
        else:  # "artwork"
            parts.append(
                f'<circle cx="{mx:.2f}" cy="{my:.2f}" r="{3.5 * MODULE:.2f}" fill="{eye_ring}"/>'
            )
            parts.append(
                f'<circle cx="{mx:.2f}" cy="{my:.2f}" r="{2.5 * MODULE:.2f}" fill="{bg}"/>'
            )
            parts.append(
                f'<circle cx="{mx:.2f}" cy="{my:.2f}" r="{1.5 * MODULE:.2f}" fill="{dark}"/>'
            )

    # --- centre logo ------------------------------------------------------
    if logo_svg and logo_frac > 0:
        size = n * MODULE * logo_frac
        lx = (QUIET * 2 * MODULE + n * MODULE) / 2 - size / 2
        ly = lx
        mid = f"{lx + size / 2:.2f}"
        clip_id = "logoClip"
        # clip the logo to a circle so its square corners never poke out
        parts.append(
            f'<defs><clipPath id="{clip_id}">'
            f'<circle cx="{mid}" cy="{mid}" r="{size / 2:.2f}"/>'
            f'</clipPath></defs>'
        )
        parts.append(
            f'<circle cx="{mid}" cy="{mid}" r="{size / 2:.2f}" fill="{bg}"/>'
        )
        parts.append(
            f'<g clip-path="url(#{clip_id})">'
            f'<svg x="{lx:.2f}" y="{ly:.2f}" width="{size:.2f}" height="{size:.2f}" '
            f'viewBox="0 0 600 600" preserveAspectRatio="xMidYMid slice">'
            f'{logo_svg}</svg></g>'
        )
        # hairline ring on top for a crisp edge
        parts.append(
            f'<circle cx="{mid}" cy="{mid}" r="{size / 2:.2f}" fill="none" '
            f'stroke="{colors["frame"]}" stroke-width="{MODULE * 0.4:.2f}"/>'
        )

    parts.append("</svg>")
    return "".join(parts)


# --------------------------------------------------------------------------
# Logo -> inline SVG (keeps the card a single self-contained file)
# --------------------------------------------------------------------------
def load_logo_svg(path: Path, size: int = 600):
    """Centre-crop the logo to a square and return an <image> data-URI body.

    Only the <image> element is returned (no outer <svg>), so the caller can
    place it inside a viewport-sized <svg> and control the scale precisely.
    """
    try:
        img = Image.open(path).convert("RGBA")
    except Exception as exc:  # pragma: no cover
        print(f"  ! could not read logo ({exc}); continuing without it")
        return None
    w, h = img.size
    side = min(w, h)
    img = img.crop(((w - side) // 2, (h - side) // 2,
                    (w - side) // 2 + side, (h - side) // 2 + side))
    img = img.resize((size, size), Image.LANCZOS)
    tmp = Path(tempfile.gettempdir()) / "adel_logo_embed.png"
    img.save(tmp, "PNG")
    import base64
    b64 = base64.b64encode(tmp.read_bytes()).decode("ascii")
    return f'<image href="data:image/png;base64,{b64}" width="{size}" height="{size}"/>'


# --------------------------------------------------------------------------
# PIL fallback (no Persian shaping - Latin caption only)
# --------------------------------------------------------------------------
def render_png(matrix, colors, eyes: str, gold_pct: int, scale: int,
                logo_path: Path | None, logo_frac: float,
                caption: str | None, font_path: str | None):
    n = len(matrix)
    q = QUIET
    span = (n + q * 2) * MODULE * scale // MODULE  # modules * scale
    quiet_px = q * scale
    img = Image.new("RGB", (span, span), colors["bg"])
    d = ImageDraw.Draw(img)
    r_dot = scale * DOT_RATIO
    r_eye_out = scale * 3.0
    r_eye_in = scale * 1.5
    eye_s = 7 * scale - scale

    align = set(alignment_cells(VERSION, n))
    for r in range(n):
        for c in range(n):
            if in_finder(r, c, n) or (r, c) in align:
                continue
            if matrix[r][c]:
                x = quiet_px + c * scale + scale / 2
                y = quiet_px + r * scale + scale / 2
                d.ellipse([x - r_dot, y - r_dot, x + r_dot, y + r_dot],
                          fill=colors["gold"] if _tone(r, c, gold_pct) else colors["dark"])

    for (ar, ac) in alignment_centers(VERSION, n):
        # inset by half the stroke so the 5-module footprint stays exact
        a_s = 5 * scale - scale
        x = quiet_px + (ac + 0.5) * scale - a_s / 2
        y = quiet_px + (ar + 0.5) * scale - a_s / 2
        d.rounded_rectangle([x, y, x + a_s, y + a_s], radius=a_s * 0.28,
                            outline=colors.get("frame", colors["dark"]), width=scale)
        cx_ = quiet_px + ac * scale + scale / 2
        cy_ = quiet_px + ar * scale + scale / 2
        d.ellipse([cx_ - scale / 2, cy_ - scale / 2, cx_ + scale / 2, cy_ + scale / 2],
                  fill=colors["dark"])

    eye_ring = colors.get("frame", colors["gold"])
    for (er, ec) in [(0, 0), (0, n - 7), (n - 7, 0)]:
        x = quiet_px + ec * scale + 3.5 * scale
        y = quiet_px + er * scale + 3.5 * scale
        if eyes == "square":
            # NOTE: PIL draws the outline inward from the given box, so the
            # box is the full 7-module footprint. Do not inset it.
            s = 7 * scale
            d.rectangle([x - s / 2, y - s / 2, x + s / 2, y + s / 2],
                        outline=colors["dark"], width=scale)
            s3 = 3 * scale
            d.rounded_rectangle([x - s3 / 2, y - s3 / 2, x + s3 / 2, y + s3 / 2],
                                radius=scale * 0.6, fill=colors["dark"])
        else:  # artwork: solid disc, knocked-out gap, solid core
            d.ellipse([x - 3.5 * scale, y - 3.5 * scale,
                       x + 3.5 * scale, y + 3.5 * scale], fill=eye_ring)
            d.ellipse([x - 2.5 * scale, y - 2.5 * scale,
                       x + 2.5 * scale, y + 2.5 * scale], fill=colors["bg"])
            d.ellipse([x - 1.5 * scale, y - 1.5 * scale,
                       x + 1.5 * scale, y + 1.5 * scale], fill=colors["dark"])

    if logo_path and logo_path.exists() and logo_frac > 0:
        size = int(n * scale * logo_frac)
        try:
            lg = Image.open(logo_path).convert("RGBA")
            w, h = lg.size
            side = min(w, h)
            lg = lg.crop(((w - side) // 2, (h - side) // 2,
                          (w - side) // 2 + side, (h - side) // 2 + side))
            lg = lg.resize((size, size), Image.LANCZOS)
            mask = Image.new("L", (size, size), 0)
            ImageDraw.Draw(mask).ellipse([0, 0, size - 1, size - 1], fill=255)
            plate = Image.new("RGB", (size, size), colors["bg"])
            plate.paste(lg, (0, 0), mask)
            px = (span - size) // 2
            img.paste(plate, (px, px))
        except Exception as exc:  # pragma: no cover
            print(f"  ! could not place logo ({exc})")

    if caption:
        from PIL import ImageFont
        fp = font_path or "C:/Windows/Fonts/tahoma.ttf"
        try:
            font = ImageFont.truetype(fp, max(14, scale * 2))
        except Exception:
            font = ImageFont.load_default()
        bbox = d.textbbox((0, 0), caption, font=font)
        tw = bbox[2] - bbox[0]
        d.text(((span - tw) / 2, span - int(scale * 3.2)), caption,
               fill=colors["dark"], font=font)
    return img


# --------------------------------------------------------------------------
# Designed card (browser-rendered so Persian shapes correctly)
# --------------------------------------------------------------------------
CARD_TEMPLATE = """<!doctype html>
<html lang="fa" dir="rtl"><head><meta charset="utf-8">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Vazirmatn:wght@300;400;500;700&display=swap" rel="stylesheet">
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  html, body {{ width:{W}px; height:{H}px; background:{bg}; }}
  body {{ font-family:'Vazirmatn', 'Segoe UI', Tahoma, sans-serif; }}
  .card {{
    position:relative; width:{W}px; height:{H}px; background:{bg};
    display:flex; flex-direction:column; align-items:center; justify-content:center;
    padding:{pad}px;
  }}
  .frame {{
    position:absolute; inset:{f1}px; border:2px solid {frame}; border-radius:{rad}px;
  }}
  .frame::after {{
    content:''; position:absolute; inset:9px; border:1px solid {frame}66; border-radius:{rad2}px;
  }}
  .qr {{ width:{qr}px; height:{qr}px; display:block; }}
  /* The QR ships as a PNG, not inline SVG. Chrome antialiases SVG circles,
     and on a dotted pattern the soft edges close the gaps between modules,
     which stops scanners reading the code. PIL draws hard edges. */
  .qr > img {{ width:100%; height:100%; display:block; }}
  .caption {{
    margin-top:{capgap}px; font-size:{capsz}px; font-weight:500; color:{dark};
    letter-spacing:0; line-height:1.7;
  }}
  .nudge {{
    margin-top:{ndgap}px; font-size:{ndsz}px; font-weight:500; color:{dark};
    letter-spacing:0; line-height:1.7;
  }}
  .brand {{
    margin-top:{brgap}px; font-size:{brsz}px; font-weight:400; color:{frame};
    letter-spacing:{brls}px; text-transform:uppercase; direction:ltr;
  }}
</style></head>
<body>
  <div class="card">
    <div class="frame"></div>
    <div class="qr"><img src="{qr_png}" alt="QR code"></div>
    <div class="caption">{caption}</div>
    <div class="nudge">{nudge}</div>
    <div class="brand">{brand}</div>
  </div>
</body></html>
"""


def render_card(qr_png: str, colors, caption: str, nudge: str, brand: str,
                W: int = 1080, H: int = 1120, qr: int = 760,
                pad: int = 40, f1: int = 26) -> str:
    return CARD_TEMPLATE.format(
        W=W, H=H, qr=qr, pad=pad, f1=f1,
        rad=max(14, f1), rad2=max(8, f1 - 10),
        bg=colors["bg"], dark=colors["dark"], frame=colors["frame"],
        capgap=round(qr * 0.055), capsz=round(qr * 0.050),
        ndgap=round(qr * 0.010), ndsz=round(qr * 0.050),
        brgap=round(qr * 0.030), brsz=round(qr * 0.021),
        brls=round(qr * 0.009),
        qr_png=qr_png, caption=html.escape(caption), nudge=html.escape(nudge),
        brand=html.escape(brand),
    )


# --------------------------------------------------------------------------
# Headless Chrome -> PNG
# --------------------------------------------------------------------------
CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
]


def find_browser() -> str | None:
    for p in CHROME_CANDIDATES:
        if os.path.exists(p):
            return p
    for name in ("google-chrome", "chromium", "chromium-browser", "msedge"):
        found = shutil.which(name)
        if found:
            return found
    return None


def screenshot(browser: str, html_path: Path, png_path: Path,
               W: int, H: int, scale: int = 3) -> bool:
    profile = Path(tempfile.mkdtemp(prefix="adel-chrome-"))
    cmd = [
        browser,
        "--headless=new",
        "--disable-gpu",
        "--no-sandbox",
        "--hide-scrollbars",
        f"--user-data-dir={profile}",
        "--virtual-time-budget=4000",
        "--default-background-color=00000000",
        f"--force-device-scale-factor={scale}",
        f"--window-size={W},{H}",
        f"--screenshot={png_path}",
        html_path.resolve().as_uri(),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=120)
    except Exception as exc:
        print(f"  ! headless render failed ({exc})")
        return False
    finally:
        shutil.rmtree(profile, ignore_errors=True)
    return png_path.exists() and png_path.stat().st_size > 0


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
VERSION = 1


def url_reachable(url: str, timeout: int = 20) -> bool:
    """True if the URL answers over HTTP with a success status.

    A QR code is printed and lives for months, so a link that 404s today is
    a real risk rather than a technicality. This is the cheapest guard.
    """
    import urllib.error
    import urllib.request
    req = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0 (QR preflight check)"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 400
    except urllib.error.HTTPError as exc:
        return 200 <= exc.code < 400
    except Exception as exc:
        print(f"  ! could not reach {url}: {exc}")
        return False


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Generate the Adel Restaurant table QR code.")
    ap.add_argument("--url", help="Hosted landing page URL. Omit to be prompted.")
    ap.add_argument("--mode", choices=["code", "card", "both"], default="card",
                    help="card = framed print-ready card, code = bare QR")
    ap.add_argument("--palette", choices=sorted(PALETTES), default="cherry")
    ap.add_argument("--eyes", choices=["artwork", "square"], default="artwork",
                    help="artwork = crimson ring eyes, square = plain square eyes")
    ap.add_argument("--ecc", choices=["L", "M", "Q", "H"], default="H")
    ap.add_argument("--gold-pct", type=int, default=45,
                    help="share of modules in the accent tone (0-100)")
    ap.add_argument("--logo", default="logo.png", help="centre logo image")
    ap.add_argument("--no-logo", action="store_true")
    ap.add_argument("--logo-frac", type=float, default=0.22,
                    help="logo width as a fraction of the QR. Keep <= 0.25")
    ap.add_argument("--caption", default="برای دیدن منو اسکن کنید.")
    ap.add_argument("--nudge", default="نظر دادن یادتون نره 😉")
    ap.add_argument("--brand", default="Adel Restaurant")
    ap.add_argument("--out", default="adel_qr", help="output basename")
    ap.add_argument("--qr-px", type=int, default=760, help="QR size in the card")
    ap.add_argument("--card-w", type=int, default=1080)
    ap.add_argument("--card-h", type=int, default=1120)
    ap.add_argument("--scale", type=int, default=3, help="render scale factor")
    ap.add_argument("--force", action="store_true",
                    help="allow building a QR for the placeholder URL (mock-ups only)")
    ap.add_argument("--skip-check", action="store_true",
                    help="skip the live HTTP preflight (use when offline)")
    args = ap.parse_args()

    url = args.url or input("Hosted landing page URL: ").strip()
    if not url:
        print("No URL given. Host index.html first, then run this again.")
        return 1
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    # Guard against printing a dead QR. Rather than blocklist a host name
    # (which cannot tell a real deployment from a stale copy of the same
    # name), actually fetch the URL and confirm it answers. A sandboxed or
    # firewalled machine cannot do that, so --skip-check bypasses just this.
    if not args.force and not args.skip_check and not url_reachable(url):
        print(f"Refusing to build a QR for {url}\n"
              "That address did not answer over HTTP, so a printed code\n"
              "pointing at it would be dead on arrival.\n\n"
              "Check the deployment, or pass --skip-check if this machine\n"
              "has no outbound network, or --force to build a mock-up.")
        return 2

    ecc = {"L": ERROR_CORRECT_L, "M": ERROR_CORRECT_M,
           "Q": ERROR_CORRECT_Q, "H": ERROR_CORRECT_H}[args.ecc]
    colors = PALETTES[args.palette]

    global VERSION
    matrix, VERSION = build_matrix(url, ecc)
    n = len(matrix)
    print(f"URL      : {url}")
    print(f"Version  : {VERSION}  ({n}x{n} modules)")
    print(f"ECC      : {args.ecc}   Palette: {args.palette}   Eyes: {args.eyes}")

    logo_path = HERE / args.logo
    use_logo = (not args.no_logo) and logo_path.exists()
    if not args.no_logo and not use_logo:
        print(f"  · no {args.logo} found, rendering without a centre logo")

    logo_svg = load_logo_svg(logo_path) if use_logo else None
    if use_logo and args.logo_frac > 0.25:
        print(f"  ! logo-frac {args.logo_frac} is above 0.25 and may break scanning")
    if use_logo and not logo_svg:
        use_logo = False

    svg = render_svg(matrix, colors, args.eyes, args.gold_pct,
                     logo_svg or "", args.logo_frac if use_logo else 0.0)

    (HERE / f"{args.out}.svg").write_text(svg, encoding="utf-8")
    print(f"  -> {args.out}.svg")

    print("\nSelf-check")
    geo_ok = verify_geometry(matrix, colors)

    png_pil = HERE / f"{args.out}-raw.png"
    render_png(matrix, colors, args.eyes, args.gold_pct, 24,
               logo_path if use_logo else None,
               args.logo_frac if use_logo else 0.0,
               None, None).save(png_pil)
    print(f"  -> {png_pil.name}  (plain QR, no Persian text)")

    dec = verify_png(png_pil, url, colors)
    if dec is False or not geo_ok:
        print("\n  STOP: the code did not verify. Fix the issues above before printing.")
        return 3

    if args.mode in ("card", "both"):
        # Render the code at print resolution with PIL (hard edges) and inline
        # it as a data URI, so the card is one self-contained file.
        import base64
        card_qr = render_png(matrix, colors, args.eyes, args.gold_pct,
                             max(24, args.qr_px // 2),
                             logo_path if use_logo else None,
                             args.logo_frac if use_logo else 0.0,
                             None, None)
        buf = io.BytesIO()
        card_qr.save(buf, "PNG", optimize=True)
        qr_png = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")

        card_html = render_card(qr_png, colors, args.caption, args.nudge, args.brand,
                                W=args.card_w, H=args.card_h, qr=args.qr_px)
        card_path = HERE / f"{args.out}-card.html"
        card_path.write_text(card_html, encoding="utf-8")
        print(f"  -> {card_path.name}")

        browser = find_browser()
        if browser:
            out = HERE / f"{args.out}-card.png"
            if screenshot(browser, card_path, out, args.card_w, args.card_h, args.scale):
                print(f"  -> {out.name}  ({out.stat().st_size // 1024} KB, print ready)")
                print("\nCard self-check")
                if verify_png(out, url, colors) is False:
                    print("  STOP: the card does not read. Do not print it.")
                    return 3
                verify_print_sizes(out, url, args)
            else:
                print(f"  ! open {card_path.name} in a browser and export as PNG")
        else:
            print(f"  ! no Chrome/Edge found. Open {card_path.name} in any browser")
            print("    and export it as a PNG, or use --mode code.")

    if dec is None:
        print("\nNo decoder available, so the code was NOT machine-verified.")
        print("Install one, then re-run:  pip install opencv-python-headless")
    print("\nTest-scan it on a real phone before printing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
