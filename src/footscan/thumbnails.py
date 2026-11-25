"""A small picture of each capture's 3-D model, for the studio's library (instead of a box that says "3D").

The model is drawn as it arrived (or as footscan's photo reconstruction built it), seen from straight above, shaded
with the same renderer as the clog's views and Claude's look at a sole scan (pictures.py). For a sole-up scan,
above is the sole; for a foam print, the dent; for a shoe's insole lying flat, its top. Nothing is measured from
the picture and nothing is changed in the model: it is only there so a scan can be told apart, and a bad one
(the other foot in the frame, a torn sole) seen, at a glance.

The picture is turned so the model's long axis runs across it (the main direction of its points seen from above),
because a phone scan arrives turned however the phone was held. It is kept beside the model as
``thumb-<stamp>.png``, named by the model file's stamp (filestamp.py): a model replaced or rebuilt gets a new
picture, and the old one is removed. A model that can't be drawn leaves ``thumb-<stamp>.failed`` saying why, and
isn't tried again for an hour (FAILED_RETRY_S).
"""

from __future__ import annotations

import hashlib
import secrets
import threading
import time
from pathlib import Path

import numpy as np

from . import atomic
from .filestamp import file_stamp

PICTURE_PX = 360          # the picture's long side, about (plus the renderer's margin)
# A model that couldn't be drawn isn't tried again for this long (the library asks on every visit, and a failed
# try can take seconds of the computer): long enough to spare it, short enough that a fixed studio tries again.
FAILED_RETRY_S = 3600
# Pictures drawn at once: a library page asks for all of them together, and each takes a while (about 1 s of one
# core for a SYNTHETIC curved foot's 4.9 MB mesh.ply in the cloud container, 2026-11-25).
_drawing = threading.BoundedSemaphore(2)


class CantDraw(Exception):
    """This version of the model couldn't be drawn (and was tried within FAILED_RETRY_S)."""


def _recent(marker: Path) -> bool:
    try:
        return time.time() - marker.stat().st_mtime < FAILED_RETRY_S
    except OSError:
        return False


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
    (an unreadable model): the page then shows its box without a picture.

    The model can be replaced while it is drawn (the iPhone app sending the scan again): the picture is kept only
    if the model is still the version it was named for, else it is drawn again from the new one (once), so a
    picture never carries another version's name. Only pictures of versions other than the current one are
    removed afterwards."""
    for _ in range(2):
        path = thumb_path(folder, model)
        if path is None:
            raise FileNotFoundError(model)
        if path.is_file():
            break
        failed = path.with_suffix(".failed")
        if _recent(failed):
            raise CantDraw(failed.read_text(encoding="utf-8", errors="replace") or "it couldn't be drawn")
        with _drawing:
            if path.is_file():  # drawn by another request while this one waited
                break
            try:
                png = draw(model, up)
            except (FileNotFoundError, PermissionError, MemoryError):
                raise  # the model went, or a moment's trouble: not the model's fault, so not remembered
            except Exception as e:
                # remembered beside the model (named for this version of it), so the next visit doesn't try again
                why = f"{type(e).__name__}: {e}"[:300]
                try:
                    failed.write_text(why, encoding="utf-8")
                except OSError:
                    pass  # not remembered: tried again next time, no worse than before
                raise CantDraw(why) from e
            if thumb_path(folder, model) != path:  # replaced while it was drawn: draw the new one instead
                continue
            tmp = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
            try:
                tmp.write_bytes(png)
                atomic.replace(tmp, path)
            finally:
                tmp.unlink(missing_ok=True)
        break
    else:
        raise FileNotFoundError(model)  # replaced twice while drawing: asked again later, when it's settled
    current = thumb_path(folder, model)
    # pictures of models since replaced, and notes of failed tries (this version's too: it is drawn now)
    for old in [*Path(folder).glob("thumb-*.png"), *Path(folder).glob("thumb-*.failed")]:
        if old not in (current, path):
            try:
                old.unlink(missing_ok=True)
            except OSError:  # being sent right now (Windows won't remove an open file): removed next time
                pass
    return path
