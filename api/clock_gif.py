"""Redraws the pixel-art clock in the room GIF with the current time.

How it stays fast: in the source GIF only frame 0 is a full frame; frames 1-23
are small "changed pixels only" patches. The clock digits never change after
frame 0 (only the colon blinks, and its position is untouched), so we re-encode
just frame 0 and splice it back into the original file bytes.
"""
import io
import os
import struct

import numpy as np
from PIL import Image

GIF_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "wallpaper.gif")

# Clock geometry on the artwork's 3px pixel grid (measured from the GIF).
X0, Y0, PX = 1041, 246, 3          # top-left of the digit area, art-pixel size
ROWS = 14                          # digit height in art pixels
COLON_COLS = (19, 20)              # colon never moves, so blink frames stay valid
CELL_W = 9                         # digit cell width in art pixels
# Left edge (art col) of each of the four digit cells, symmetric around the colon.
CELL_STARTS = (-3, 8, 23, 34)
CLEAR_COLS = range(-8, 47)         # whole clock face except the colon


def _read_gif():
    with open(GIF_PATH, "rb") as f:
        return f.read()


def _frame0_span(data):
    """Return (start, end) byte offsets of frame 0's LZW data (min-code-size byte + blocks)."""
    w, h, flags = struct.unpack("<HHB", data[6:11])
    pos = 13
    if flags & 0x80:
        pos += 3 * (2 << (flags & 7))
    while True:
        b = data[pos]
        if b == 0x21:                      # extension block: skip
            pos += 2
            while True:
                n = data[pos]; pos += 1 + n
                if n == 0:
                    break
        elif b == 0x2C:                    # image descriptor
            local = data[pos + 9]
            assert not (local & 0x80), "unexpected local palette"
            pos += 10
            start = pos
            pos += 1                       # min code size
            while True:
                n = data[pos]; pos += 1 + n
                if n == 0:
                    break
            return start, pos
        else:
            raise ValueError("unexpected block")


class _Base:
    """Everything that can be prepared once per process."""
    def __init__(self):
        self.data = _read_gif()
        im = Image.open(io.BytesIO(self.data))
        im.seek(0)
        self.palette = im.getpalette()[:384] if im.getpalette() else None
        raw_palette = im.palette.palette
        self.palette_bytes = bytes(raw_palette[:384])
        self.frame0 = np.array(im, dtype=np.uint8)           # palette indices
        self.span = _frame0_span(self.data)

        # glyph bitmaps taken straight from the artwork, so the font matches exactly
        red = self._red_index()
        self.red = red

        def grab(col0, ncols):
            g = np.zeros((ROWS, ncols), dtype=bool)
            for r in range(ROWS):
                for c in range(ncols):
                    y = Y0 + PX * r + 1
                    x = X0 + PX * (col0 + c) + 1
                    g[r, c] = self.frame0[y, x] == red
            return g

        zero, one, seven = grab(0, 9), grab(12, 5), grab(31, 8)
        self.face = int(self.frame0[Y0 + 1, X0 - PX + 1])    # dark clock-face colour index
        self.glyphs = self._build_glyphs(zero, one, seven)
        self.colon = grab(COLON_COLS[0], 2)                  # untouched, kept for reference

    def _red_index(self):
        y, x = Y0 + 1, X0 + 3 * 1 + 1                        # inside the top bar of the "0"
        return int(self.frame0[y, x])

    @staticmethod
    def _build_glyphs(zero, one, seven):
        W = CELL_W
        Z = zero
        def blank():
            return np.zeros((ROWS, W), dtype=bool)
        def part(rows, cols):
            g = blank()
            for r in rows:
                for c in cols:
                    g[r, c] = Z[r, c]
            return g
        a = part(range(0, 2), range(W))
        d = part(range(12, 14), range(W))
        f = part(range(2, 7), range(0, 3))
        b = part(range(2, 7), range(6, 9))
        e = part(range(7, 12), range(0, 3))
        c = part(range(7, 12), range(6, 9))
        g = blank(); g[6:8, :] = True
        for r in (6, 7):                                     # smooth junctions
            for col in (0, 8):
                g[r, col] = True

        def combo(*parts):
            out = blank()
            for p in parts:
                out |= p
            return out

        glyphs = {
            "0": Z.copy(),
            "2": combo(a, b, g, e, d),
            "3": combo(a, b, g, c, d),
            "5": combo(a, f, g, c, d),
            "6": combo(a, f, g, e, c, d),
            "8": combo(a, b, c, d, e, f, g),
            "9": combo(a, b, c, d, f, g),
        }
        four = blank()
        four[0:8, 0:2] = True
        four[6:8, :] = True
        four[:, 6:8] = True
        glyphs["4"] = four
        one9 = blank(); one9[:, 4:9] = one          # right-aligned, like a real digital clock
        glyphs["1"] = one9
        seven9 = blank(); seven9[:, 0:8] = seven
        glyphs["7"] = seven9
        return glyphs


_BASE = None


def _base():
    global _BASE
    if _BASE is None:
        _BASE = _Base()
    return _BASE


def _paint(frame, text):
    B = _base()
    # wipe the old digits (keep the colon)
    for r in range(ROWS):
        for c in CLEAR_COLS:
            if c in COLON_COLS or c in (COLON_COLS[0], COLON_COLS[1]):
                continue
            y0 = Y0 + PX * r; x0 = X0 + PX * c
            frame[y0:y0 + PX, x0:x0 + PX] = B.face
    # draw the new ones
    for ch, start in zip(text, CELL_STARTS):
        glyph = B.glyphs[ch]
        for r in range(ROWS):
            for c in range(CELL_W):
                if glyph[r, c]:
                    y0 = Y0 + PX * r; x0 = X0 + PX * (start + c)
                    frame[y0:y0 + PX, x0:x0 + PX] = B.red


def _encode_frame0(frame):
    B = _base()
    img = Image.frombytes("P", (frame.shape[1], frame.shape[0]), frame.tobytes())
    img.putpalette(B.palette_bytes)
    buf = io.BytesIO()
    img.save(buf, "GIF", optimize=False, interlace=False)
    out = buf.getvalue()
    start, end = _frame0_span(out)
    # PIL keeps our palette untouched (same 128 colours, same indices), so its
    # frame data can be dropped into the original file as-is.
    assert out[13:13 + len(B.palette_bytes)] == B.palette_bytes, "palette changed"
    return out[start:end]


def render(hhmm):
    """hhmm: 4-character string like '0117'. Returns GIF bytes."""
    B = _base()
    frame = B.frame0.copy()
    _paint(frame, hhmm)
    new_data = _encode_frame0(frame)
    start, end = B.span
    return B.data[:start] + new_data + B.data[end:]
