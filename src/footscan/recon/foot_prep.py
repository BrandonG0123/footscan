"""A foot scan from the iPhone app (Object Capture), made ready for the insole generator.

Object Capture hands over a model in metres with Y up (the phone's motion
sensors know where gravity is), placed and turned however the capture
happened to start, often with the lower leg and a patch of floor in it.
``footscan insole`` wants the mat frame: millimetres, Z up, the floor at
z = 0, toes toward +y. Four steps, each recorded:

1. **Level** (imported.to_floor_frame): Y up becomes Z up. If the scan kept
   the floor round the foot, that floor is found as the biggest flat surface
   everything stands on, levelled exactly and cut away. If it didn't, the
   foot's lowest scanned points are taken as the floor, trusting gravity
   for level. A coarse phone model is then split to 2 mm triangles (adds
   points, not shape) so the steps below work by area, not vertex luck.
2. **Which way the foot points**: the footprint's length (its narrowest
   width, as plantar.long_axis) gives the line. The end the leg stands over
   is the heel. With no leg in the scan, the taller end is the heel (the
   ankle and the back of the foot stand higher than the toes).
3. **Turn** so the toes point along +y, footprint centred on the mat.
4. **Trim the lower leg**: everything above ``LEG_TRIM_MM`` goes. The insole
   uses only the bottom 30 mm, and without the leg the scan is smaller, and
   no shin can be mistaken for part of the foot.
"""

from __future__ import annotations

import numpy as np

from . import imported, plantar

LEG_TRIM_MM = 70.0          # keep the foot, drop the leg above about ankle height
FOOTPRINT_BAND_MM = 12.0
LEG_MIN_HEIGHT_MM = 90.0    # a leg reaches well above the foot itself
MAT_CENTRE = (100.0, 150.0)
DENSIFY_MM = 2.0


class FootPrepError(ValueError):
    pass


def _yaw(angle: float) -> np.ndarray:
    T = np.eye(4)
    c, s = np.cos(angle), np.sin(angle)
    T[:2, :2] = [[c, -s], [s, c]]
    return T


def prepare(mesh, up: str = "y", trim_mm: float | None = LEG_TRIM_MM):
    """Any-units, Object-Capture-frame foot -> (mat-frame mesh, decisions). Doesn't modify the input."""
    mm, units, _ = imported.to_millimetres(mesh)
    placed, _, floor_info = imported.to_floor_frame(mm, up)
    info = dict(units_detected=units, up_axis=up, floor=floor_info["floor"])
    if "floor_tilt_corrected_deg" in floor_info:
        info["floor_tilt_corrected_deg"] = floor_info["floor_tilt_corrected_deg"]

    # The phone builds a coarse model (points ~5 mm apart); split its triangles
    # to 2 mm so the footprint and the leg are found by area, not by luck.
    # Linear: it adds points, not shape.
    import trimesh

    if np.median(placed.edges_unique_length) > DENSIFY_MM:
        v, f = trimesh.remesh.subdivide_to_size(placed.vertices, placed.faces, max_edge=DENSIFY_MM)
        placed = trimesh.Trimesh(v, f, process=True)
        info["densified_to_mm"] = DENSIFY_MM

    V = np.asarray(placed.vertices)
    low = V[V[:, 2] < FOOTPRINT_BAND_MM]
    if len(low) < 100:
        raise FootPrepError("almost nothing of the scan is near the floor: was the foot resting on the floor?")
    mu = low[:, :2].mean(0)
    axis, length, width = plantar.long_axis(low[:, :2])

    high = V[V[:, 2] > LEG_MIN_HEIGHT_MM]
    if len(high) > 50:
        heel_side = float((high[:, :2].mean(0) - mu) @ axis)
        info["heel_from"] = "the leg stands over it"
    else:
        along = (V[:, :2] - mu) @ axis
        t = np.ptp(along) / 3
        rear = V[along < along.min() + t, 2]
        front = V[along > along.max() - t, 2]
        heel_side = -1.0 if np.percentile(rear, 95) >= np.percentile(front, 95) else 1.0
        info["heel_from"] = "no leg in the scan: the taller end (ankle side) taken as the heel"
    toes = -np.sign(heel_side) * axis if heel_side != 0 else axis

    # turn the toes onto +y, then centre the footprint on the mat
    placed.apply_transform(_yaw(np.arctan2(toes[0], toes[1])))
    low_after = placed.vertices[placed.vertices[:, 2] < FOOTPRINT_BAND_MM][:, :2]
    centre = (low_after.min(0) + low_after.max(0)) / 2
    placed.apply_translation([MAT_CENTRE[0] - centre[0], MAT_CENTRE[1] - centre[1], 0.0])

    info["footprint_mm"] = dict(length=round(float(length), 1), width=round(float(width), 1))
    info["height_before_trim_mm"] = round(float(placed.vertices[:, 2].max()), 1)
    if trim_mm is not None and info["height_before_trim_mm"] > trim_mm:
        keep = placed.triangles_center[:, 2] <= trim_mm
        info["trimmed_above_mm"] = trim_mm
        info["trimmed_share"] = round(float(1 - keep.mean()), 3)
        placed.update_faces(keep)
        placed.remove_unreferenced_vertices()
        placed = _lid(placed, trim_mm)
    return placed, info


def _lid(mesh, trim_mm: float):
    """Close the cut where the leg was trimmed with flat lids facing up.

    Without them, the insole generator's upward rays pass up the open leg
    and hit nothing, which it would report as holes in the scan. With them,
    the rays meet a top surface, which reads (correctly) as "the sole wasn't
    seen here: resting on the floor".
    """
    import manifold3d as m3
    import shapely
    import trimesh

    from shapely.geometry import LineString
    from shapely.ops import polygonize, unary_union

    if not len(mesh.faces):
        return mesh
    # the open edges along the cut (edges used by one face only, both ends near the cut height)
    E = mesh.edges_sorted
    border = trimesh.grouping.group_rows(E, require_count=1)
    E = E[border]
    V = np.asarray(mesh.vertices)
    at_cut = (V[E[:, 0], 2] > trim_mm - 5) & (V[E[:, 1], 2] > trim_mm - 5)
    E = E[at_cut]
    if not len(E):
        return mesh
    lid_z = float(V[np.unique(E), 2].max())
    lines = [LineString([V[a, :2], V[b, :2]]) for a, b in E]
    lids = []
    for poly in polygonize(unary_union(lines)):
        if poly.area < 1.0:
            continue
        for g in getattr(poly.buffer(0), "geoms", [poly.buffer(0)]):
            ring = np.asarray(shapely.geometry.polygon.orient(g, 1.0).exterior.coords)[:-1]
            tri = m3.Manifold.extrude(m3.CrossSection([ring], m3.FillRule.Positive), 1.0).to_mesh()
            Vt = np.asarray(tri.vert_properties)[:, :3]
            F = np.asarray(tri.tri_verts)
            top = F[np.all(Vt[F][:, :, 2] > 0.5, axis=1)]
            Vl = Vt.copy()
            Vl[:, 2] = lid_z
            lid = trimesh.Trimesh(Vl, top, process=True)
            lids.append(lid)
    return trimesh.util.concatenate([mesh, *lids]) if lids else mesh


def insole_from_object_capture(mesh, foot: str, up: str = "y", params=None):
    """Object Capture foot scan -> first-fit insole (insole.Insole), with the prep decisions in its report."""
    from .. import insole

    placed, info = prepare(mesh, up)
    ins = insole.from_scan(placed, foot, params)
    ins.report["prep"] = info
    ins.report["warnings"] = plausibility(info, ins.report) + ins.report["warnings"]
    return ins, placed


# An adult foot's footprint: length and width/length ratio well outside these
# means the scan isn't a foot resting on the floor (or wasn't levelled right).
FOOT_LENGTH_MM = (180.0, 330.0)
FOOT_RATIO = (0.28, 0.50)
INVENTED_SOLE_SHARE = 0.9


def plausibility(info: dict, report: dict) -> list[str]:
    """Warnings that the result shouldn't be trusted, in plain words. Empty when it looks like a foot."""
    out = []
    fp = info["footprint_mm"]
    L, W = fp["length"], fp["width"]
    ratio = W / max(L, 1e-9)
    if not (FOOT_LENGTH_MM[0] <= L <= FOOT_LENGTH_MM[1]) or not (FOOT_RATIO[0] <= ratio <= FOOT_RATIO[1]):
        out.append(f"DOESN'T LOOK LIKE A FOOT ON THE FLOOR: the part touching the floor is {L:.0f} x {W:.0f} mm "
                   f"(an adult foot is about {FOOT_LENGTH_MM[0]:.0f}-{FOOT_LENGTH_MM[1]:.0f} mm long and "
                   f"{FOOT_RATIO[0]:.2f}-{FOOT_RATIO[1]:.2f} times as wide as long). Don't print this insole.")
    if report["sole"]["seen"] > INVENTED_SOLE_SHARE:
        out.append(f"THE SOLE MAY BE INVENTED: the model has a surface under {report['sole']['seen']:.0%} of the "
                   "footprint, but a foot resting on the floor hides most of its sole. Object Capture closes the "
                   "bottom of a model by itself, so this underside is probably guessed, not scanned. "
                   "Don't trust the arch shape from this scan.")
    return out
