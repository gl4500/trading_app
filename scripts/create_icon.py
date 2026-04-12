"""
Generate launcher.ico — AI Trading Competition robot icon.
Run once before building the exe:
    runtime/python/python.exe create_icon.py

Requires Pillow (installed by build_exe.ps1 automatically).
Falls back to a minimal stdlib icon if Pillow is not available.
"""
import math
import struct
import zlib

try:
    from PIL import Image, ImageDraw
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


def make_icon_pil(size: int = 256) -> "Image.Image":
    """Draw a dark robot/trading themed icon."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    cx, cy = size // 2, size // 2
    s = size

    # ── Background circle ──────────────────────────────────────────────────────
    r = int(s * 0.46)
    # Glow
    for i in range(8, 0, -1):
        alpha = int(20 * (9 - i) / 8)
        draw.ellipse(
            [cx - r - i*3, cy - r - i*3, cx + r + i*3, cy + r + i*3],
            fill=(34, 197, 94, alpha),
        )
    # Main circle — dark navy
    for band in range(r, 0, -1):
        t = band / r
        rr = int(10 + 20 * t)
        gg = int(15 + 30 * t)
        bb = int(30 + 60 * t)
        draw.ellipse(
            [cx - band, cy - band, cx + band, cy + band],
            fill=(rr, gg, bb, 255),
        )
    # Rim
    draw.ellipse(
        [cx - r, cy - r, cx + r, cy + r],
        outline=(34, 197, 94, 180),
        width=max(2, s // 80),
    )

    # ── Robot head ────────────────────────────────────────────────────────────
    hw = int(s * 0.30)   # head half-width
    hh = int(s * 0.24)   # head half-height
    hy = cy - int(s * 0.04)

    head_box = [cx - hw, hy - hh, cx + hw, hy + hh]
    corner   = int(s * 0.06)
    draw.rounded_rectangle(head_box, radius=corner,
                           fill=(30, 41, 80, 255),
                           outline=(34, 197, 94, 200),
                           width=max(1, s // 100))

    # ── Antenna ───────────────────────────────────────────────────────────────
    ant_x, ant_y = cx, hy - hh
    ant_h = int(s * 0.10)
    lw = max(2, s // 80)
    draw.line([(ant_x, ant_y), (ant_x, ant_y - ant_h)],
              fill=(34, 197, 94, 220), width=lw)
    dot_r = int(s * 0.025)
    draw.ellipse([ant_x - dot_r, ant_y - ant_h - dot_r,
                  ant_x + dot_r, ant_y - ant_h + dot_r],
                 fill=(34, 197, 94, 255))

    # ── Eyes ─────────────────────────────────────────────────────────────────
    eye_r  = int(s * 0.055)
    eye_y  = hy - int(s * 0.04)
    eye_lx = cx - int(s * 0.10)
    eye_rx = cx + int(s * 0.10)

    for ex in (eye_lx, eye_rx):
        # Outer glow
        for i in range(4, 0, -1):
            draw.ellipse(
                [ex - eye_r - i*2, eye_y - eye_r - i*2,
                 ex + eye_r + i*2, eye_y + eye_r + i*2],
                fill=(96, 165, 250, int(40 * (5 - i) / 4)),
            )
        draw.ellipse([ex - eye_r, eye_y - eye_r,
                      ex + eye_r, eye_y + eye_r],
                     fill=(96, 165, 250, 255))
        # Pupil
        pr = int(eye_r * 0.45)
        draw.ellipse([ex - pr, eye_y - pr, ex + pr, eye_y + pr],
                     fill=(15, 25, 60, 255))

    # ── Mouth / data display ──────────────────────────────────────────────────
    mouth_w = int(hw * 1.1)
    mouth_y = hy + int(hh * 0.35)
    mouth_h = int(s * 0.055)
    mx0 = cx - mouth_w // 2
    mx1 = cx + mouth_w // 2

    draw.rounded_rectangle(
        [mx0, mouth_y, mx1, mouth_y + mouth_h],
        radius=int(s * 0.02),
        fill=(15, 25, 60, 255),
        outline=(34, 197, 94, 120),
        width=1,
    )

    # Mini chart inside mouth bar
    bar_count = 7
    bar_w = (mx1 - mx0 - 8) // bar_count
    heights = [0.3, 0.5, 0.4, 0.8, 0.6, 0.9, 0.7]
    for i, h_frac in enumerate(heights):
        bx = mx0 + 4 + i * bar_w
        bh = int(mouth_h * 0.75 * h_frac)
        col = (34, 197, 94, 220) if h_frac > 0.6 else (96, 165, 250, 200)
        draw.rectangle(
            [bx, mouth_y + mouth_h - bh - 2,
             bx + bar_w - 2, mouth_y + mouth_h - 2],
            fill=col,
        )

    # ── Collar / body top ────────────────────────────────────────────────────
    col_y = hy + hh
    col_w = int(hw * 0.7)
    col_h = int(s * 0.06)
    draw.rounded_rectangle(
        [cx - col_w, col_y, cx + col_w, col_y + col_h],
        radius=int(s * 0.02),
        fill=(20, 30, 60, 255),
        outline=(34, 197, 94, 120),
        width=1,
    )

    return img


def save_ico_pil(path: str):
    img256 = make_icon_pil(256)
    sizes  = [256, 128, 64, 48, 32, 16]
    frames = [img256.resize((s, s), Image.LANCZOS) for s in sizes]
    frames[0].save(
        path,
        format="ICO",
        sizes=[(s, s) for s in sizes],
        append_images=frames[1:],
    )
    print(f"Icon saved: {path}")


def save_ico_fallback(path: str):
    """Minimal stdlib ICO — dark circle with no Pillow needed."""
    SIZE = 32
    pixels = []
    cx = cy = SIZE // 2
    r  = SIZE // 2 - 2
    for y in range(SIZE):
        for x in range(SIZE):
            dx, dy = x - cx, y - cy
            if math.sqrt(dx*dx + dy*dy) <= r:
                t = math.sqrt(dx*dx + dy*dy) / r
                pixels += [int(10 + 20*t), int(15 + 30*t), int(30 + 60*t), 255]
            else:
                pixels += [0, 0, 0, 0]

    raw = bytes(pixels)

    def _png_chunk(tag, data):
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    def _make_png(w, h, raw_rgba):
        scanlines = b""
        row_bytes = w * 4
        for row in range(h):
            scanlines += b"\x00" + raw_rgba[row*row_bytes:(row+1)*row_bytes]
        compressed = zlib.compress(scanlines, 9)
        ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
        return (
            b"\x89PNG\r\n\x1a\n"
            + _png_chunk(b"IHDR", ihdr)
            + _png_chunk(b"IDAT", compressed)
            + _png_chunk(b"IEND", b"")
        )

    png = _make_png(SIZE, SIZE, raw)
    ico_header = struct.pack("<HHH", 0, 1, 1)
    entry = struct.pack("<BBBBHHII",
                        SIZE, SIZE, 0, 0, 1, 32,
                        len(png), 6 + 16)
    with open(path, "wb") as f:
        f.write(ico_header + entry + png)
    print(f"Fallback icon saved: {path}")


if __name__ == "__main__":
    import pathlib
    out = str(pathlib.Path(__file__).parent / "launcher.ico")
    if HAS_PIL:
        save_ico_pil(out)
    else:
        print("Pillow not found — using minimal stdlib icon.")
        save_ico_fallback(out)
