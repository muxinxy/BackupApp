"""生成 backupapp.ico（PNG-in-ICO，纯 stdlib，无 Pillow）。

用法: .venv\Scripts\python scripts\make_icon.py
输出: packaging/icons/backupapp.ico（256x256，Vista+ 支持 PNG 压缩条目）
"""

import os
import struct
import zlib

SIZE = 256
RADIUS = 52


def lerp(a: int, b: int, t: float) -> int:
    return int(a + (b - a) * t)


def make_png(size: int) -> bytes:
    rows = []
    for y in range(size):
        row = bytearray([0])  # filter: none
        for x in range(size):
            # 圆角矩形判定
            cx = min(x, size - 1 - x)
            cy = min(y, size - 1 - y)
            if cx < RADIUS and cy < RADIUS:
                dx, dy = RADIUS - cx, RADIUS - cy
                if dx * dx + dy * dy > RADIUS * RADIUS:
                    row += bytes((0, 0, 0, 0))
                    continue
            t = (x + y) / (2 * size)
            r = lerp(29, 59, t)
            g = lerp(78, 130, t)
            b = lerp(216, 246, t)
            # 中央白色圆环（靶心样式）
            d2 = (x - size / 2) ** 2 + (y - size / 2) ** 2
            if d2 < (size * 0.30) ** 2:
                if d2 < (size * 0.17) ** 2:
                    row += bytes((r, g, b, 255))  # 内圆为底色
                else:
                    row += bytes((255, 255, 255, 255))
            else:
                row += bytes((r, g, b, 255))
        rows.append(bytes(row))
    raw = b"".join(rows)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def make_ico(png: bytes) -> bytes:
    header = struct.pack("<HHH", 0, 1, 1)  # reserved, type=icon, count=1
    entry = struct.pack("<BBBBHHII", 0, 0, 0, 0, 1, 32, len(png), 22)
    return header + entry + png


def _png_from_rgba(size: int, pixels: bytes) -> bytes:
    """把 size*size*4 的 RGBA 字节流写成 PNG（与 make_png 同一编码路径）。"""
    rows = []
    stride = size * 4
    for y in range(size):
        rows.append(b"\x00" + pixels[y * stride:(y + 1) * stride])  # filter: none
    raw = b"".join(rows)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def _seg_dist(px, py, ax, ay, bx, by) -> float:
    """点 (px,py) 到线段 AB 的距离。"""
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    cx, cy = ax + t * dx, ay + t * dy
    return ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5


def make_check(size: int = 16, color=(255, 255, 255)) -> bytes:
    """生成勾选标记 PNG（透明底 + 指定颜色对勾）。

    QCheckBox::indicator:checked 用它替代默认指示器绘制——暗黑主题下 Fusion 的
    默认指示器与背景几乎同色，勾选框看不清（见 theme.py 的 ::indicator 规则）。
    4x 超采样后降采样做抗锯齿，纯 stdlib，无 Pillow 依赖。
    """
    ss = 4  # 超采样倍数
    half = 0.085  # 描边半宽（归一化坐标）
    # 对勾两段：左下短笔 + 右上长笔
    segs = ((0.20, 0.52, 0.42, 0.73), (0.42, 0.73, 0.81, 0.27))
    out = bytearray()
    for y in range(size):
        for x in range(size):
            hits = 0
            for sy in range(ss):
                for sx in range(ss):
                    px = (x + (sx + 0.5) / ss) / size
                    py = (y + (sy + 0.5) / ss) / size
                    if any(_seg_dist(px, py, *s) <= half for s in segs):
                        hits += 1
            alpha = int(255 * hits / (ss * ss))
            out += bytes((color[0], color[1], color[2], alpha))
    return _png_from_rgba(size, bytes(out))


def main() -> None:
    out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "packaging", "icons", "backupapp.ico")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    ico = make_ico(make_png(SIZE))
    with open(out, "wb") as f:
        f.write(ico)
    print(f"icon -> {out} ({len(ico)} bytes)")

    # 复选框勾选标记（GUI 主题使用）
    icons_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "backupapp", "gui", "icons")
    os.makedirs(icons_dir, exist_ok=True)
    for name, rgb in (("check_white.png", (255, 255, 255)),
                      ("check_dark.png", (15, 23, 42))):
        p = os.path.join(icons_dir, name)
        data = make_check(16, rgb)
        with open(p, "wb") as f:
            f.write(data)
        print(f"check -> {p} ({len(data)} bytes)")


if __name__ == "__main__":
    main()
