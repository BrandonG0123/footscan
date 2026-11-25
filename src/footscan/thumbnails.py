"""A small picture of each capture's 3-D model, for the studio's library (instead of a box that says "3D").

The model is drawn as it arrived (or as footscan's photo reconstruction built it), seen from straight above, shaded
with the same renderer as the clog's views and Claude's look at a sole scan (pictures.py). For a sole-up scan,
above is the sole; for a foam print, the dent; for a shoe's insole lying flat, its top. Nothing is measured from
the picture and nothing is changed in the model: it is only there so a scan can be told apart, and a bad one
(the other foot in the frame, a torn sole) seen, at a glance.

The picture is turned so the model's long axis runs across it (the main direction of its points seen from above),
because a phone scan arrives turned however the phone was held. It is kept beside the model as
``thumb-<stamp>.png``, named by the model file's stamp (filestamp.py): a model replaced or rebuilt gets a new
picture, and the old one is removed.
"""

from __future__ import annotations

import hashlib
import secrets
import threading
from pathlib import Path

import numpy as np

from . import atomic
from .filestamp import file_stamp

PICTURE_PX = 360          # the picture's long side, about (plus the renderer's margin)
# Pictures drawn at once: each takes about a second of one core, and a library page asks for all of them together.
_drawing = threading.BoundedSemaphore(2)


def thumb_path(folder: Path, model: Path) -> Path | None:
    """Where the picture of ``model`` (a file in or under ``folder``) is kept, or None without a model."""
    stamp = file_stamp(model)
    if stamp is None:
        return None
    return Path(folder) / f"thumb-{hashlib.sha1(stamp.encode()).hexdigest()[:12]}.png"


def draw(model: Path, up: str = "y") -> bytes:
    """The model at ``model`` (mm) seen from above (``up``: which axis is up in the file), as a PNG."""
    from .pictures import png_bytes, shaded_view, surface_points
    from .recon.imported import load_geometry

    mesh = load_geometry(model)
    V = np.asarray(mesh.vertices, dtype=float)
    if up == "y":  # (x, y, z) -> (x, -z, y): Y up becomes Z up, the same way round
        mesh.vertices = np.c_[V[:, 0], -V[:, 2], V[:, 1]]
    ext = float(np.max(mesh.extents))
    mm_per_px = max(ext / PICTURE_PX, 0.2)
    P, N = surface_points(mesh, per_mm2=4.0 / mm_per_px ** 2, least=20_000, most=1_500_000)
    # the long axis across the picture: the main direction of the points seen from above
    flat = P[:, :2] - P[:, :2].mean(0)
    _, vecs = np.linalg.eigh(flat.T @ flat)
    along = vecs[:, -1]
    right = np.array([along[0], along[1], 0.0])
    right /= np.linalg.norm(right)
    return png_bytes(shaded_view(P, N, np.array([0.0, 0.0, 1.0]), right, mm_per_px, pad=8))


def thumbnail(folder: Path, model: Path, up: str = "y") -> Path:
    """The picture of ``model``, drawn now if there isn't one for this version of it. Raises if it can't be drawn
    (an unreadable model): the page then shows its box without a picture."""
    path = thumb_path(folder, model)
    if path is None:
        raise FileNotFoundError(model)
    if path.is_file():
        return path
    with _drawing:
        if path.is_file():  # drawn by another request while this one waited
            return path
        png = draw(model, up)
        tmp = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
        try:
            tmp.write_bytes(png)
            atomic.replace(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)
    for old in Path(folder).glob("thumb-*.png"):  # pictures of models since replaced
        if old != path:
            try:
                old.unlink(missing_ok=True)
            except OSError:  # being sent right now (Windows won't remove an open file): removed next time
                pass
    return path
