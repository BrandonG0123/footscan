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
4. **Whether the bottom is real.** The phone can't see under an object on a
   table, so Object Capture closes the model with a guess, and the guess can
   hang far below the object (a wedge about 30 mm deep under the printed block on
   17 Nov 2026). When the lowest points are well below where the base slab's
   flat top says the bottom must be, the model is stood on that top instead
   and the guessed part cut away (``evaluate_imported``).

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
TABLE_TRIES = 4             # planes tried, largest first, before giving up on finding the table
# A real scan's size is off by a few percent at worst; anything outside this
# isn't the calibration object (another object, clutter, or no real scale).
SIZE_RANGE = (0.7, 1.6)


class NotTheObject(ValueError):
    """The model can't be the calibration object: comparing would be meaningless."""
FLOOR_FACING = 0.97         # cos of the most a "flat" bit may tilt (about 14 degrees)
TABLE_CUT_MM = 0.5          # triangles entirely below this, once levelled, are table
# With no table in the scan, the phone never saw the object's underside and
# Object Capture closes the model with a guess. If the lowest points sit more
# than this below where the base slab's top says the bottom must be, the
# guess is not a flat bottom and heights can't be measured from it. A real
# flat bottom, rounded a little at its edges, sits within a millimetre or so.
UNDERSIDE_TOL_MM = 3.0
# The base slab's top is the object's biggest flat upward surface (about
# 2,900 mm2 in the design; the terraces are 1,710 and 1,440). A scan whose
# biggest flat top is under a third of that hasn't caught the slab's top.
DECK_MIN_AREA_MM2 = 1000.0
DECK_BIN_MM = 0.5


def load_geometry(path):
    """Just the triangles of a 3D file, in the file's own units and axes.

    Scanning apps attach colour textures (Object Capture's OBJ points at a
    PNG). Measuring needs only the shape, and reading textures would need an
    image library and can fail on files that are fine geometrically, so each
    part's vertices and faces are taken directly, placed where the file puts
    them, and nothing else is read.
    """
    import trimesh

    loaded = trimesh.load(path, process=False)
    if isinstance(loaded, trimesh.Trimesh):
        parts = [(np.eye(4), loaded)]
    elif isinstance(loaded, trimesh.Scene):
        parts = []
        for node in loaded.graph.nodes_geometry:
            T, name = loaded.graph[node]
            g = loaded.geometry.get(name)
            if isinstance(g, trimesh.Trimesh):
                parts.append((T, g))
    else:
        parts = []
    if not parts:
        raise ValueError("no triangles found")
    V, F, offset = [], [], 0
    for T, g in parts:
        v = np.asarray(g.vertices, dtype=float)
        V.append(v @ T[:3, :3].T + T[:3, 3])
        F.append(np.asarray(g.faces) + offset)
        offset += len(v)
    mesh = trimesh.Trimesh(np.vstack(V), np.vstack(F), process=True)
    if not len(mesh.faces):
        raise ValueError("no triangles found")
    return mesh


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
    rng = np.random.default_rng(seed)
    # The largest upward plane first. When things hang below it (a flat top on the object bigger than the
    # table still in view), its points are set aside and the next largest is tried, so a big object top can't
    # hide the table under it.
    for _ in range(TABLE_TRIES):
        if len(C) < FLOOR_MIN_SHARE * len(P):
            return None
        found, F = _largest_plane(P, C, rng)
        if found is not None:
            return found
        if F is None:
            return None
        keep = np.ones(len(C), bool)
        keep[F] = False
        C = C[keep]
    return None


def _largest_plane(P, C, rng):
    """The largest plane through the upward-facing points C. -> ((centre, normal, its points), None) when
    nothing hangs below it (the table); (None, indices into C of its points) when things do (a flat top on the
    object); (None, None) when there's no plane big enough."""
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
        return None, None
    a, n = best
    on = np.abs((C - a) @ n) < PLANE_TOL_MM
    for _ in range(3):  # refine: least squares on the plane's own points
        c, n = accuracy.fit_plane(C[on])
        on = np.abs((C - c) @ n) < PLANE_TOL_MM
    c, n = accuracy.fit_plane(C[on])
    below = float(np.mean((P - c) @ n < -BELOW_TOL_MM))
    if below > BELOW_MAX_SHARE:
        return None, np.flatnonzero(on)  # things hang below it: a flat top on the object, not the table
    return (c, n, C[on]), None


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
    info["transform"] = (L @ T).tolist()  # the turn and move applied: millimetre input -> this frame
    return m, floor_pts, info


def _deck(mesh_z_up):
    """The base slab's flat top in a Z-up millimetre model: (point on it, the object's up, area mm2), or None.

    First the object's own "up" is found from its flat tops: the area-weighted
    average direction of the triangles facing within about 14 degrees of up,
    taken again round each new average. All the flat tops are parallel, so
    this is square to them even when the phone's sense of gravity is a degree
    or two out (without it, a tilted 60 mm slab top spreads over several
    height bands and a terrace can outweigh it). Then every flat triangle is
    put in a 0.5 mm band by its height along that up, the bands are weighed by
    area, and the heaviest band is the slab's top, the biggest flat surface.
    """
    n = mesh_z_up.face_normals
    a = mesh_z_up.area_faces
    c = mesh_z_up.triangles_center
    up = np.array([0.0, 0.0, 1.0])
    for _ in range(4):
        flat = n @ up > FLOOR_FACING
        if not flat.any():
            return None
        up = (n[flat] * a[flat, None]).sum(0)
        up /= np.linalg.norm(up)
    flat = n @ up > FLOOR_FACING
    h, w, cf = c[flat] @ up, a[flat], c[flat]
    bins = np.arange(h.min(), h.max() + 2 * DECK_BIN_MM, DECK_BIN_MM)
    weight, edges = np.histogram(h, bins, weights=w)
    k = int(np.argmax(weight))
    on = np.abs(h - 0.5 * (edges[k] + edges[k + 1])) < PLANE_TOL_MM
    area = float(w[on].sum())
    if area < DECK_MIN_AREA_MM2:
        return None
    return (cf[on] * w[on, None]).sum(0) / area, up, area


def _stand_on_deck(placed, base_mm: float):
    """Check the bottom of a no-table model against its base slab; stand it on the slab if the bottom was made up.

    Returns (mesh or None, info or None). info is None when the slab's top
    can't be found. Otherwise it says how far the lowest points reach below
    where the slab's top puts the real bottom: the slab's top less its
    thickness, scaled by the model's own size (so a scan that is simply too
    big, with a real bottom, isn't taken for a made-up one). When that is
    more than UNDERSIDE_TOL_MM, the mesh comes back levelled on the slab's
    top, with that top ``base_mm`` above z = 0 (unscaled, so a size error
    still shows in every other height), and sliced at z = 0, the made-up
    part below discarded.
    """
    import trimesh

    deck = _deck(placed)
    if deck is None:
        return None, None
    c, up, area = deck
    P, _ = trimesh.sample.sample_surface(placed, 60_000, seed=np.random.default_rng(0))
    h = (P - c) @ up
    # The model's own size: the spread along its longest direction, above the
    # slab's top (the made-up underside can bulge out sideways), against the design.
    top = P[h > -1.0] - c
    top = top - np.outer(top @ up, up)
    _, _, Vt = np.linalg.svd(top - top.mean(0), full_matrices=False)
    along = top @ Vt[0]
    size = float(np.percentile(along, 99.5) - np.percentile(along, 0.5)) / calib.LENGTH
    expected = base_mm * size
    below = -float(np.percentile(h, 0.5)) - expected
    info = dict(underside_below_expected_mm=round(below, 1))
    if below <= UNDERSIDE_TOL_MM:
        return None, info
    R = _level(up)
    L = np.eye(4)
    L[:3, :3] = R
    L[:3, 3] = -R @ c + np.array([0.0, 0.0, base_mm])
    m = placed.copy()
    m.apply_transform(L)
    m = trimesh.intersections.slice_mesh_plane(m, [0.0, 0.0, 1.0], [0.0, 0.0, 0.0])
    tilt = float(np.degrees(np.arccos(np.clip(up[2], -1, 1))))
    info.update(
        floor=f"no table in the scan, and the phone made up the underside (it reaches {below:.0f} mm below the "
              f"object): heights are measured from the base slab's top, less its {base_mm:g} mm thickness, and the "
              "made-up part is cut away",
        underside_made_up_mm=round(below, 1), deck_tilt_corrected_deg=round(tilt, 3),
        deck_area_mm2=round(area), deck_transform=L.tolist())
    return m, info


def evaluate_imported(mesh, up: str = "y", calipers: dict | None = None) -> dict:
    """The accuracy study for a model made by another app (e.g. Object Capture).

    With no table in the scan, heights are normally measured from the
    object's lowest points. Object Capture can't see under an object on a
    table, so it invents a bottom; when that invented bottom hangs well below
    where the base slab's top puts the real one (17 Nov 2026: a wedge about
    30 mm deep under the printed block), measuring from it makes every height wrong
    by that much. Then the base slab's flat top is used instead: the model is
    levelled on it and stood with the top ``base`` mm up (the calipers'
    reading if given, else the design's 10 mm). The base thickness is then
    assumed rather than measured, and is reported as not measured; the other
    heights still test the steps between the flat tops, and length and width
    are measured on the real sides as usual.
    """
    mm, units, factor = to_millimetres(mesh)
    placed, floor_pts, info = to_floor_frame(mm, up)
    base_mm = float((calipers or {}).get("base") or calib.BASE)
    deck_info, bottom_warning = None, None
    if floor_pts is None:
        stood, checked = _stand_on_deck(placed, base_mm)
        if stood is not None:
            placed, deck_info = stood, checked
            info["transform"] = (np.array(deck_info.pop("deck_transform")) @ np.array(info["transform"])).tolist()
            info.update(deck_info)
        elif checked is None:
            bottom_warning = ("no table in the scan and the base slab's flat top couldn't be found, so whether the "
                              "bottom is real couldn't be checked: heights are measured from the lowest points, and "
                              "if the phone made up the underside they are all too big by however far it hangs down")
        else:
            info.update(checked)
    across = float(np.max(placed.extents))
    if not (SIZE_RANGE[0] * calib.LENGTH <= across <= SIZE_RANGE[1] * calib.LENGTH):
        raise NotTheObject(
            f"once the table is taken off, the model is {across:.0f} mm across; the calibration object is "
            f"{calib.LENGTH:.0f} mm. Wrong file, wrong units, or the scan includes other things: crop it to the "
            "object (Object Capture's box does this) and try again.")
    report = accuracy.evaluate(placed, floor_pts, calipers, walls_clear_of_bottom=deck_info is not None)
    if bottom_warning:
        report["warnings"].append(bottom_warning)
    if deck_info is not None:
        for row in report["dimensions"]:
            if row["key"] == "base":
                row.update(scan_mm=None, scan_minus_reference_mm=None,
                           note="not measured: the scan's underside was made up, so the base slab's thickness is "
                                "taken as known and heights are measured from its top")
        report["warnings"].append(
            f"the phone never saw under the object and made up a bottom reaching {deck_info['underside_made_up_mm']:.0f}"
            f" mm below it; heights are measured from the base slab's top less {base_mm:g} mm instead, and the "
            "base thickness is not measured. Scale is still tested by the length, the width and the steps "
            "between the flat tops.")
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
    calipers = json.loads(calipers_file.read_text(encoding="utf-8-sig")) if calipers_file.exists() else None  # a BOM too, like --calipers
    mesh = trimesh.load(folder / "mesh.ply", force="mesh")
    try:
        report = evaluate_imported(mesh, up=up, calipers=calipers)
    except NotTheObject as err:
        (folder / "accuracy.json").unlink(missing_ok=True)
        return dict(error=str(err))
    (folder / "accuracy.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return summarize(report)
