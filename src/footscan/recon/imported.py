"""Imported scans (LiDAR apps, Apple Object Capture) in the accuracy study.

A footscan photo scan already lives in the mat's frame: millimetres, Z up,
the paper at z = 0. An imported model has none of that, so before the same
accuracy study can run, three things are worked out from the model itself:

1. **Units**, from its size. A scan of a foot or of the calibration object is
   a few tenths of a metre across, so "under 5" means metres, "under 50"
   centimetres, otherwise millimetres (the studio's Import 3D uses the same
   rule).
2. **Which way is up.** Apple's Object Capture and most phone scanning apps
   put Y up (the phone's motion sensors know where gravity is); some tools
   use Z. This is given, not guessed (``up="y"`` or ``"z"``): guessing wrong
   would turn the object on its side.
3. **Where the table is.** If the scan kept the table round the object, the
   table is the flat, upward-facing surface at the very bottom: a plane is
   fitted to it, the model is turned so that plane is exactly level, and it
   becomes z = 0, then it is cut away (the study measures the object's own
   surface, as with footscan's scans). If the app cut the table away (Object Capture usually
   does), the object's lowest scanned points are where it stood; the report
   says which was used, because heights are measured from it.

Then :func:`accuracy.evaluate` runs unchanged. Its alignment still only turns
and shifts, never scales: LiDAR's sense of size is exactly what is being
tested, and a model 1% too big must come out 1% too big.
"""

from __future__ import annotations

import numpy as np

from . import accuracy, calib

# Rotations taking each "up" convention to footscan's Z up (right-handed, so
# the object isn't mirrored): Y up -> turn +90 degrees about X.
UP = {
    "y": np.array([[1.0, 0, 0], [0, 0, -1.0], [0, 1.0, 0]]),
    "z": np.eye(3),
}
FLOOR_MIN_SHARE = 0.05      # the table must be at least this share of the scanned surface
PLANE_TOL_MM = 1.0          # a sample within this of a plane is on it
BELOW_TOL_MM = 2.0          # ...and the table has (almost) nothing more than this below it:
BELOW_MAX_SHARE = 0.02      # at most this share of the surface
RANSAC_TRIES = 300
# A real scan's size is off by a few percent at worst; anything outside this
# isn't the calibration object (another object, clutter, or no real scale).
SIZE_RANGE = (0.7, 1.6)


class NotTheObject(ValueError):
    """The model can't be the calibration object: comparing would be meaningless."""
FLOOR_FACING = 0.97         # cos of the most a "flat" bit may tilt (about 14 degrees)
TABLE_CUT_MM = 0.5          # triangles entirely below this, once levelled, are table


def to_millimetres(mesh):
    """(mesh in mm, units it was in, factor applied). Does not modify the input."""
    extent = float(mesh.extents.max())
    units, factor = ("m", 1000.0) if extent < 5 else ("cm", 10.0) if extent < 50 else ("mm", 1.0)
    out = mesh.copy()
    out.apply_scale(factor)
    return out, units, factor


def _level(n: np.ndarray) -> np.ndarray:
    """Rotation taking unit vector n onto +Z (Rodrigues)."""
    z = np.array([0.0, 0.0, 1.0])
    v = np.cross(n, z)
    s, c = np.linalg.norm(v), float(n @ z)
    if s < 1e-12:
        return np.eye(3)
    K = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]]) / s
    return np.eye(3) + s * K + (1 - c) * (K @ K)


def _find_table(P: np.ndarray, N: np.ndarray, seed: int = 0):
    """The table, if the scan has one: (point, unit normal pointing up, its points), else None.

    The table is the biggest flat, upward-facing surface that (nearly)
    everything else sits on top of. A big table tilted a degree or two rises
    centimetres from one side to the other, so it is found as a plane (a
    random search over upward-facing samples, then a least-squares fit), not
    as "the lowest few millimetres". Flat tops on the object itself fail the
    "everything above it" test: the object's own sides go below them.
    """
    up = N[:, 2] > FLOOR_FACING
    C = P[up]
    if len(C) < FLOOR_MIN_SHARE * len(P):
        return None
    rng = np.random.default_rng(seed)
    best, best_count = None, 0
    for _ in range(RANSAC_TRIES):
        a, b, d = C[rng.choice(len(C), 3, replace=False)]
        n = np.cross(b - a, d - a)
        norm = np.linalg.norm(n)
        if norm < 1e-9:
            continue
        n = n / norm
        if n[2] < 0:
            n = -n
        if n[2] < FLOOR_FACING:
            continue
        count = int(np.sum(np.abs((C - a) @ n) < PLANE_TOL_MM))
        if count > best_count:
            best, best_count = (a, n), count
    if best is None or best_count < FLOOR_MIN_SHARE * len(P):
        return None
    a, n = best
    F = C[np.abs((C - a) @ n) < PLANE_TOL_MM]
    for _ in range(3):  # refine: least squares on the plane's own points
        c, n = accuracy.fit_plane(F)
        F = C[np.abs((C - c) @ n) < PLANE_TOL_MM]
    c, n = accuracy.fit_plane(F)
    below = float(np.mean((P - c) @ n < -BELOW_TOL_MM))
    if below > BELOW_MAX_SHARE:
        return None  # things hang below it: a flat top on the object, not the table
    return c, n, F


def to_floor_frame(mesh_mm, up: str = "y", n_samples: int = 60_000, seed: int = 0):
    """Turn a millimetre model so Z is up and the table is z = 0.

    Returns (mesh, floor_points or None, info). ``floor_points`` are samples
    of the table in the new frame, when the scan kept the table.
    """
    import trimesh

    if up not in UP:
        raise ValueError(f"up must be one of {sorted(UP)}")
    m = mesh_mm.copy()
    T = np.eye(4)
    T[:3, :3] = UP[up]
    m.apply_transform(T)

    P, fi = trimesh.sample.sample_surface(m, n_samples, seed=np.random.default_rng(seed))
    N = m.face_normals[fi]
    low = float(np.percentile(P[:, 2], 0.5))
    plane = _find_table(P, N, seed)
    info = dict(up_axis=up)
    floor_pts = None
    if plane is not None:
        c, n, F = plane
        R = _level(n)
        L = np.eye(4)
        L[:3, :3] = R
        L[:3, 3] = -R @ c
        m.apply_transform(L)
        floor_pts = F @ R.T - R @ c
        # Cut the table out, as footscan's own pipeline does: the study
        # measures the object's surface and gets the table separately.
        # Any triangle lying entirely at (or below) table level goes.
        z = m.vertices[:, 2]
        on_object = z[m.faces].max(axis=1) > TABLE_CUT_MM
        m.update_faces(on_object)
        m.remove_unreferenced_vertices()
        tilt = float(np.degrees(np.arccos(np.clip(n[2], -1, 1))))
        info.update(floor="table found in the scan: levelled, set to z = 0 and cut away",
                    floor_tilt_corrected_deg=round(tilt, 3), floor_points=int(len(F)))
    else:
        L = np.eye(4)
        L[2, 3] = -low
        m.apply_transform(L)
        info.update(floor="no table in the scan: the object's lowest scanned points are taken as where it stood "
                          "(heights are measured from them)")
    return m, floor_pts, info


def evaluate_imported(mesh, up: str = "y", calipers: dict | None = None) -> dict:
    """The accuracy study for a model made by another app (e.g. Object Capture)."""
    mm, units, factor = to_millimetres(mesh)
    placed, floor_pts, info = to_floor_frame(mm, up)
    across = float(np.max(placed.extents))
    if not (SIZE_RANGE[0] * calib.LENGTH <= across <= SIZE_RANGE[1] * calib.LENGTH):
        raise NotTheObject(
            f"once the table is taken off, the model is {across:.0f} mm across; the calibration object is "
            f"{calib.LENGTH:.0f} mm. Wrong file, wrong units, or the scan includes other things: crop it to the "
            "object (Object Capture's box does this) and try again.")
    report = accuracy.evaluate(placed, floor_pts, calipers)
    report["imported"] = dict(units_detected=units, scale_to_mm=factor,
                              extents_mm=[round(float(v), 1) for v in sorted(mm.extents, reverse=True)], **info)
    return report


def summarize(report: dict) -> dict:
    """The few numbers the studio shows at a glance; the full report is kept alongside."""
    dims = {r["key"]: r.get("scan_minus_reference_mm") for r in report["dimensions"]}
    dev = report["surface_deviation"]
    return dict(
        median_mm=dev["median_mm"], p95_mm=dev["p95_mm"], signed_mean_mm=dev["signed_mean_mm"],
        within_1mm=report["completeness"]["within_1mm"], scan_within_2mm=report["registration"]["scan_within_2mm"],
        length_mm=dims.get("length"), width_mm=dims.get("width"), dome_apex_mm=dims.get("dome_apex"),
        reference="calipers" if any(r.get("caliper_mm") is not None for r in report["dimensions"]) else "model",
        floor=report["imported"]["floor"], warnings=report["warnings"],
    )


def score_capture(folder, up: str = "y") -> dict:
    """Run the study on a studio capture's imported mesh.ply (millimetres, as imported).

    Writes accuracy.json next to it and returns the summary, or
    {"error": ...} when the model can't be the calibration object.
    """
    import json
    from pathlib import Path

    import trimesh

    folder = Path(folder)
    calipers_file = folder / "calipers.json"
    calipers = json.loads(calipers_file.read_text()) if calipers_file.exists() else None
    mesh = trimesh.load(folder / "mesh.ply", force="mesh")
    try:
        report = evaluate_imported(mesh, up=up, calipers=calipers)
    except NotTheObject as err:
        (folder / "accuracy.json").unlink(missing_ok=True)
        return dict(error=str(err))
    (folder / "accuracy.json").write_text(json.dumps(report, indent=2))
    return summarize(report)
