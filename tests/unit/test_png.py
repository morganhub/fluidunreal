"""The runtime's PNG reader and frame comparison, on images whose answer is known.

The runtime module is standard library only, so it is exercised here without Unreal. The engine
writes filtered rows; every PNG filter type is written below, so a decoding slip shows as a wrong
share rather than as a plausible one.
"""

from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "unreal_runtime"))

from fluidunreal_runtime import png  # noqa: E402


def encode(path: Path, pixels: list[list[tuple[int, int, int]]], filters: list[int]) -> Path:
    """Write an 8-bit RGB PNG, row y filtered with filters[y % len(filters)]."""
    height, width = len(pixels), len(pixels[0])
    raw = bytearray()
    previous = bytes(width * 3)
    for y, row in enumerate(pixels):
        line = bytes(channel for pixel in row for channel in pixel)
        kind = filters[y % len(filters)]
        out = bytearray()
        for i, value in enumerate(line):
            left = line[i - 3] if i >= 3 else 0
            up = previous[i]
            corner = previous[i - 3] if i >= 3 else 0
            if kind == 0:
                predicted = 0
            elif kind == 1:
                predicted = left
            elif kind == 2:
                predicted = up
            elif kind == 3:
                predicted = (left + up) // 2
            else:
                estimate = left + up - corner
                distances = (abs(estimate - left), abs(estimate - up), abs(estimate - corner))
                predicted = (left, up, corner)[distances.index(min(distances))]
            out.append((value - predicted) & 0xFF)
        raw += bytes([kind]) + out
        previous = line

    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    path.write_bytes(
        png.SIGNATURE
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(bytes(raw)))
        + chunk(b"IEND", b"")
    )
    return path


def scene(
    width: int, height: int, figure: tuple[int, int, int, int] | None
) -> list[list[tuple[int, int, int]]]:
    """A gradient background, and optionally a dark block standing for the character."""
    rows = []
    for y in range(height):
        row = []
        for x in range(width):
            inside = figure and figure[0] <= x <= figure[2] and figure[1] <= y <= figure[3]
            row.append((10, 20, 30) if inside else ((x * 7) % 256, (y * 5) % 256, 128))
        rows.append(row)
    return rows


def test_a_figure_is_measured_as_its_share_and_its_box(tmp_path: Path):
    for filters in ([0], [1], [2], [3], [4], [0, 1, 2, 3, 4]):
        with_it = encode(tmp_path / "a.png", scene(40, 30, (10, 5, 19, 24)), filters)
        without = encode(tmp_path / "b.png", scene(40, 30, None), filters)
        result = png.compare(with_it, without)
        assert result["differing_pixels"] == 10 * 20, filters
        assert result["share"] == pytest.approx(200 / 1200)
        assert result["box"] == [10, 5, 19, 24]


def test_two_identical_frames_differ_nowhere(tmp_path: Path):
    """The negative control: without the character in either frame, nothing differs."""
    first = encode(tmp_path / "a.png", scene(32, 16, None), [4])
    second = encode(tmp_path / "b.png", scene(32, 16, None), [1])
    result = png.compare(first, second)
    assert result["share"] == 0.0 and result["box"] is None


def test_noise_under_the_threshold_is_not_a_difference(tmp_path: Path):
    base = scene(16, 8, None)
    noisy = [
        [(r + png.DIFFERENCE_THRESHOLD, g, b) if r < 200 else (r, g, b) for r, g, b in row] for row in base
    ]
    result = png.compare(encode(tmp_path / "a.png", base, [0]), encode(tmp_path / "b.png", noisy, [0]))
    assert result["differing_pixels"] == 0


def test_frames_that_cannot_be_compared_are_refused(tmp_path: Path):
    small = encode(tmp_path / "a.png", scene(8, 8, None), [0])
    large = encode(tmp_path / "b.png", scene(9, 8, None), [0])
    with pytest.raises(ValueError, match="differ in size"):
        png.compare(small, large)
    (tmp_path / "c.png").write_bytes(b"not a png at all")
    with pytest.raises(ValueError, match="not a PNG"):
        png.read_png(tmp_path / "c.png")
