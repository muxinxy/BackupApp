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


def main() -> None:
    out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "packaging", "icons", "backupapp.ico")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    ico = make_ico(make_png(SIZE))
    with open(out, "wb") as f:
        f.write(ico)
    print(f"icon -> {out} ({len(ico)} bytes)")


if __name__ == "__main__":
    main()
