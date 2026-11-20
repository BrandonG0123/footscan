"""Shaded pictures of a 3-D surface, drawn with numpy alone (no 3-D or plotting library on the studio's computer).

Used for the clog's views (footwear.py) and for the pictures of a sole scan that Claude looks at on arrival
(second_look.py). ``png_bytes`` writes any of them as a PNG.
"""

from __future__ import annotations

import struct
import zlib

import numpy as np


def surface_points(mesh, per_mm2: float = 16.0, least: int = 50_000, most: int = 6_000_000):
    """Points spread evenly over the surface (``per_mm2`` per square millimetre, between ``least`` and ``most``),
    each with its face's outward direction, about the middle of the mesh's bounding box."""
    import trimesh

    n = int(min(max(mesh.area * per_mm2, least), most))
    pts, face = trimesh.sample.sample_surface(mesh, n, seed=0)
    return pts - mesh.bounds.mean(0), mesh.face_normals[face]


def shaded_view(P: np.ndarray, N: np.ndarray, toward: np.ndarray, right: np.ndarray, mm_per_px: float,
                colour=(0.80, 0.84, 0.86), pad: int = 24) -> np.ndarray:
    """One shaded picture (RGB) of surface points ``P`` with outward directions ``N``, seen from far off along
    ``toward`` (the direction from the surface to the camera, unit length), with ``right`` along the picture's
    width (unit length, square to ``toward``), at ``mm_per_px``.

    The camera's view of each point is worked out, and each pixel keeps the nearest point that faces the
    camera. Its brightness is how squarely that point's surface faces a lamp up and to the left (Lambert's
    cosine law), plus some light from everywhere, a little darker further away to tell front from back. A
    pixel no point of the near surface happened to land in (so it is empty, or shows something several
    millimetres behind), with nearer drawn pixels nearly all round it, takes their average, which closes the
    pinholes. Everything else is white."""
    upward = np.cross(toward, right)
    keep = N @ toward > 0.02
    u, v, depth = P[keep] @ right, P[keep] @ upward, P[keep] @ toward
    Nk = N[keep]
    lo_u, lo_v = (P @ right).min(), (P @ upward).min()
    w = int(np.ceil(((P @ right).max() - lo_u) / mm_per_px)) + 2 * pad
    h = int(np.ceil(((P @ upward).max() - lo_v) / mm_per_px)) + 2 * pad
    col = np.clip(((u - lo_u) / mm_per_px).astype(int) + pad, 0, w - 1)
    row = np.clip(h - 1 - (((v - lo_v) / mm_per_px).astype(int) + pad), 0, h - 1)
    order = np.argsort(depth)                      # nearest last, so it is the one a pixel ends up with
    nearest = np.full(h * w, -1)
    nearest[(row * w + col)[order]] = order
    nearest = nearest.reshape(h, w)
    lamp = -0.45 * right + 0.55 * upward + 0.70 * toward
    lamp /= np.linalg.norm(lamp)
    lit = np.clip(Nk @ lamp, 0.0, 1.0)
    d = (depth - depth.min()) / max(np.ptp(depth), 1e-6) if len(depth) else depth
    shade = (0.30 + 0.70 * lit) * (0.72 + 0.28 * d)
    hit = nearest >= 0
    grey = np.where(hit, shade[np.clip(nearest, 0, None)], 0.0) if len(shade) else np.zeros((h, w))
    deep = np.where(hit, depth[np.clip(nearest, 0, None)], -np.inf) if len(depth) else np.full((h, w), -np.inf)
    for _ in range(2):                             # pinholes
        pg, pd = np.pad(grey, 1), np.pad(deep, 1, constant_values=-np.inf)
        nearer = [(pd[1 + a:h + 1 + a, 1 + b:w + 1 + b] > deep + 2.0, pg[1 + a:h + 1 + a, 1 + b:w + 1 + b],
                   pd[1 + a:h + 1 + a, 1 + b:w + 1 + b]) for a in (-1, 0, 1) for b in (-1, 0, 1) if a or b]
        around = sum(n.astype(int) for n, _, _ in nearer)
        fill = around >= 6
        grey = np.where(fill, sum(np.where(n, g, 0.0) for n, g, _ in nearer) / np.maximum(around, 1), grey)
        deep = np.where(fill, sum(np.where(n, d, 0.0) for n, _, d in nearer) / np.maximum(around, 1), deep)
        hit = hit | fill
    img = np.ones((h, w, 3))
    img[hit] = grey[hit][:, None] * np.array(colour)
    return (np.clip(img, 0, 1) * 255).astype(np.uint8)


def png_bytes(rgb: np.ndarray) -> bytes:
    """An 8-bit RGB PNG, written by hand (each row: filter byte 0, then the pixels)."""
    h, w, _ = rgb.shape
    raw = b"".join(b"\x00" + rgb[r].astype(np.uint8).tobytes() for r in range(h))

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))
