"""Read the PNGs the engine writes and compare two of them, with the standard library only.

The engine writes 8-bit RGB or RGBA. That is all this reads; anything else is refused by name
rather than decoded wrong.
"""

import struct
import zlib

SIGNATURE = b"\x89PNG\r\n\x1a\n"
# 8-bit levels: below this on every channel, two pixels are the same picture. Temporal
# anti-aliasing leaves a few levels of noise between two renders of an unchanged scene.
DIFFERENCE_THRESHOLD = 12


def read_png(path):
    """Return (width, height, channels, rows), each row a bytes object of width * channels."""
    with open(path, "rb") as handle:
        data = handle.read()
    if data[:8] != SIGNATURE:
        raise ValueError("not a PNG: %s" % path)
    offset, header, packed = 8, None, bytearray()
    while offset < len(data):
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        kind = data[offset + 4 : offset + 8]
        body = data[offset + 8 : offset + 8 + length]
        if kind == b"IHDR":
            header = struct.unpack(">IIBBBBB", body[:13])
        elif kind == b"IDAT":
            packed += body
        elif kind == b"IEND":
            break
        offset += 12 + length
    if header is None:
        raise ValueError("no IHDR: %s" % path)
    width, height, depth, colour, _compression, _filter, interlace = header
    if depth != 8 or colour not in (2, 6) or interlace != 0:
        raise ValueError(
            "unsupported PNG (%d-bit, colour %d, interlace %d): %s" % (depth, colour, interlace, path)
        )
    channels = 3 if colour == 2 else 4
    raw = zlib.decompress(bytes(packed))
    stride = width * channels
    rows, previous, position = [], bytearray(stride), 0
    for _ in range(height):
        kind = raw[position]
        line = bytearray(raw[position + 1 : position + 1 + stride])
        position += 1 + stride
        for index in range(stride):
            left = line[index - channels] if index >= channels else 0
            up = previous[index]
            corner = previous[index - channels] if index >= channels else 0
            if kind == 1:
                line[index] = (line[index] + left) & 0xFF
            elif kind == 2:
                line[index] = (line[index] + up) & 0xFF
            elif kind == 3:
                line[index] = (line[index] + (left + up) // 2) & 0xFF
            elif kind == 4:
                estimate = left + up - corner
                distances = (abs(estimate - left), abs(estimate - up), abs(estimate - corner))
                line[index] = (line[index] + (left, up, corner)[distances.index(min(distances))]) & 0xFF
        rows.append(bytes(line))
        previous = line
    return width, height, channels, rows


def compare(first, second):
    """Share of pixels that differ between two frames, and the box that holds them.

    The box is what tells a character from a changed view: a character is one region, a camera
    that moved differs everywhere.
    """
    w1, h1, c1, rows1 = read_png(first)
    w2, h2, c2, rows2 = read_png(second)
    if (w1, h1) != (w2, h2):
        raise ValueError("the two frames differ in size (%dx%d, %dx%d)" % (w1, h1, w2, h2))
    differing = 0
    box = None
    for y, (row1, row2) in enumerate(zip(rows1, rows2, strict=True)):
        for x in range(w1):
            a, b = x * c1, x * c2
            if (
                abs(row1[a] - row2[b]) > DIFFERENCE_THRESHOLD
                or abs(row1[a + 1] - row2[b + 1]) > DIFFERENCE_THRESHOLD
                or abs(row1[a + 2] - row2[b + 2]) > DIFFERENCE_THRESHOLD
            ):
                differing += 1
                if box is None:
                    box = [x, y, x, y]
                else:
                    box = [min(box[0], x), min(box[1], y), max(box[2], x), max(box[3], y)]
    return {
        "width": w1,
        "height": h1,
        "share": differing / float(w1 * h1),
        "differing_pixels": differing,
        "box": box,
        "threshold_levels": DIFFERENCE_THRESHOLD,
    }
