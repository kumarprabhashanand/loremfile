"""Browser icons and the social card, drawn in pure Python (docs/07 §4).

No imaging library: the daily integrity rebuild must reproduce these bytes exactly, and a PNG
written row by row through zlib depends on nothing else.
"""

from __future__ import annotations

import struct
import zlib

Color = tuple[int, int, int]

INK: Color = (15, 23, 42)
PAPER: Color = (255, 255, 255)
ACCENT: Color = (37, 99, 235)
BACKDROP: Color = (241, 245, 249)

#: 5x7 glyphs for the wordmark, top row first.
GLYPHS: dict[str, tuple[str, ...]] = {
    "l": (".##..", "..#..", "..#..", "..#..", "..#..", "..#..", ".###."),
    "o": (".....", ".....", ".###.", "#...#", "#...#", "#...#", ".###."),
    "r": (".....", ".....", "#.##.", "##..#", "#....", "#....", "#...."),
    "e": (".....", ".....", ".###.", "#...#", "#####", "#....", ".###."),
    "m": (".....", ".....", "##.#.", "#.#.#", "#.#.#", "#.#.#", "#.#.#"),
    "f": ("..##.", ".#...", "####.", ".#...", ".#...", ".#...", ".#..."),
    "i": ("..#..", ".....", ".##..", "..#..", "..#..", "..#..", ".###."),
    ".": (".....", ".....", ".....", ".....", ".....", ".##..", ".##.."),
    "d": ("....#", "....#", ".####", "#...#", "#...#", "#...#", ".####"),
    "v": (".....", ".....", "#...#", "#...#", "#...#", ".#.#.", "..#.."),
}


class Canvas:
    def __init__(self, width: int, height: int, background: Color) -> None:
        self.width = width
        self.height = height
        self.rows = [bytearray(bytes(background) * width) for _ in range(height)]

    def fill(self, x: int, y: int, w: int, h: int, color: Color) -> None:
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(self.width, x + w), min(self.height, y + h)
        if x0 >= x1 or y0 >= y1:
            return
        run = bytes(color) * (x1 - x0)
        for row in self.rows[y0:y1]:
            row[x0 * 3 : x1 * 3] = run

    def png(self) -> bytes:
        raw = b"".join(b"\x00" + bytes(row) for row in self.rows)
        header = struct.pack(">IIBBBBB", self.width, self.height, 8, 2, 0, 0, 0)
        return (
            b"\x89PNG\r\n\x1a\n"
            + _chunk(b"IHDR", header)
            + _chunk(b"IDAT", zlib.compress(raw, 9))
            + _chunk(b"IEND", b"")
        )


def _chunk(kind: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(kind + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)


def draw_mark(canvas: Canvas, x: int, y: int, size: int) -> None:
    """The brand mark on a 16-unit grid: a page with three lines of text."""
    unit = size / 16

    def box(left: float, top: float, width: float, height: float, color: Color) -> None:
        canvas.fill(
            x + round(left * unit),
            y + round(top * unit),
            max(1, round(width * unit)),
            max(1, round(height * unit)),
            color,
        )

    box(0, 0, 16, 16, ACCENT)
    box(3, 2, 10, 12, PAPER)
    for top, width in ((5, 6), (8, 6), (11, 4)):
        box(5, top, width, 1, INK)


def draw_text(canvas: Canvas, text: str, x: int, y: int, scale: int, color: Color) -> None:
    for position, char in enumerate(text):
        for row, cells in enumerate(GLYPHS[char]):
            for column, cell in enumerate(cells):
                if cell == "#":
                    left = x + (position * 6 + column) * scale
                    canvas.fill(left, y + row * scale, scale, scale, color)


def mark_png(size: int) -> bytes:
    canvas = Canvas(size, size, ACCENT)
    draw_mark(canvas, 0, 0, size)
    return canvas.png()


def favicon_ico() -> bytes:
    """An ICO holding PNG images at 16, 32 and 48 pixels."""
    sizes = (16, 32, 48)
    images = [mark_png(size) for size in sizes]
    offset = 6 + 16 * len(images)
    entries = b""
    for size, data in zip(sizes, images, strict=True):
        entries += struct.pack("<BBBBHHII", size, size, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    return struct.pack("<HHH", 0, 1, len(images)) + entries + b"".join(images)


def og_card() -> bytes:
    """The 1200x630 Open Graph image: the mark and the wordmark."""
    canvas = Canvas(1200, 630, BACKDROP)
    draw_mark(canvas, 120, 195, 240)
    draw_text(canvas, "loremfile.dev", 420, 284, 9, INK)
    return canvas.png()
