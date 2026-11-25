"""The underside of the foot, in the foot's own coordinate frame.

After reconstruction the mesh is in *mat* coordinates: x across the paper,
y toward the toe sheet, z up. Measurements and the insole design need *foot*
coordinates (frame.py): x forward along the foot, y toward the inside
(medial), z up, origin under the back of the heel. Phase 3 will place that
frame from landmarks you click (heel, 1st and 5th metatarsal joints); this
module builds a **provisional** frame from the mesh alone, so a scan can be
looked at and roughly measured before any clicking. The report labels it
provisional, and Phase 3 replaces it.

The provisional frame
---------------------
- **Up** is the mat's z axis: in a standing or semi-standing scan, the floor
  under the foot *is* the reference plane (frame.py's ``support_plane``).
- **Forward** is the long axis of the footprint: take the part of the foot
  within ``FOOTPRINT_BAND_MM`` of the floor, flatten it onto the floor, and
  find the line its filled outline is spread along most (see ``long_axis``).
  That gives a line, not a direction. Two independent clues pick the toe end:
  the mat says "toes toward sheet 2" (+y), and the leg rises above the
  *heel*, so the scan's high points (the shin) sit over the back of the
  foot. If the clues disagree, the leg wins and the report says so.
- **Medial** is up x forward (the foot's left) for a right foot, and the
  opposite for a left foot, so both feet get the same sign conventions.
- **Origin** is the rearmost point of the footprint, on the floor.

What "plantar surface" means here
---------------------------------
In a weight-bearing scan the sole is pressed on the paper and no camera
sees it. What the cameras *do* see is where the sole leaves the floor: under
the inner arch, the surface curves up from the paper and is visible from
low, inside views. So:

- ``plantar.ply``: the downward-facing part of the surface (normal pointing
  more than ``DOWNWARD_COS`` toward the floor) near the floor: the arch's
  underside and the rounded edges of the heel and forefoot.
- **Footprint outline**: where the surface meets the paper (the open edge
  the floor cut left behind), flattened onto the floor.
- **Medial arch profile**: walking forward along the foot in 2 mm steps,
  the height of the lowest surface point on the inside third of the foot.
  Where the foot touches the floor it is ~0; under the arch it rises. This
  is the shape the insole's arch is defined *relative to* (Phase 4), and for
  a flat foot it is the number that matters most, so it is reported as a
  curve, not a single value.

In a non-weight-bearing scan the sole *is* visible, and the same
downward-facing selection is the full plantar surface; but there is no floor
under the foot, so the frame must come from landmarks (Phase 3).
"""

from __future__ import annotations

import numpy as np

from ..frame import FootFrame

FOOTPRINT_BAND_MM = 12.0
LEG_MIN_HEIGHT_MM = 70.0
MAT_ACROSS_TOL = 0.02  # an axis whose y part is under this (about 1 degree off the mat's x) lies along x
DOWNWARD_COS = 0.25
PLANTAR_MAX_HEIGHT_MM = 40.0
PROFILE_STEP_MM = 2.0


class PlantarError(ValueError):
    pass


def long_axis(xy: np.ndarray) -> tuple[np.ndarray, float, float]:
    """Direction of the footprint's length -> (unit direction, length along it, width across it).

    Wrap the footprint in its convex hull (a rubber band around it), fill it,
    and take the direction the filled hull is spread out along most (its
    principal axis of area: the line about which it has the least second
    moment). A footprint shaped the same on both sides of a line gets that
    line, and a left foot's axis is the mirror image of its right foot's.
    Using the hull, not the points, ignores the arch's gap, which lies inside
    the outline and would otherwise tilt the axis toward the outer border.

    Until 25 Nov 2026 this was the hull edge across which the hull is
    narrowest ("rotating calipers"). On a foot that edge is the straight line
    from the heel's curve to the ball's along one side, not the foot's middle:
    on the SYNTHETIC curved_foot, whose outline is the same on both sides of
    its middle line, it came out 7.7 degrees off that line, the same way for
    the right and the left foot (the insole thread's finding, checked here),
    and the insole's outline was then turned and slid by up to its limits to
    make up for it, differently for each foot.

    The width returned is the hull's extent across that line, no longer the
    narrowest width in any direction, so it can only come out the same or
    wider: on the real scans (footprint_mm, 25 Nov) 2349 86.3 -> 86.6 mm and
    89df 74.8 -> 74.9; the legs-flat 2190, both feet in it, 108.1 -> 110.7,
    0.504 of its length, past foot_prep.FOOT_RATIO's 0.50 (refused anyway).
    """
    from scipy.spatial import ConvexHull

    H = xy[ConvexHull(xy).vertices]  # anticlockwise
    x, y = (H - H.mean(0)).T
    x1, y1 = np.roll(x, -1), np.roll(y, -1)
    cross = x * y1 - x1 * y  # twice each triangle's area, from the polygon's own middle to one edge
    area = cross.sum() / 2
    cx, cy = ((x + x1) * cross).sum() / (6 * area), ((y + y1) * cross).sum() / (6 * area)
    # second moments of the filled polygon about the origin (the vertices' mean), then about its centroid
    sxx = ((x * x + x * x1 + x1 * x1) * cross).sum() / 12 - area * cx * cx
    syy = ((y * y + y * y1 + y1 * y1) * cross).sum() / 12 - area * cy * cy
    sxy = ((x * y1 + 2 * x * y + 2 * x1 * y1 + x1 * y) * cross).sum() / 24 - area * cx * cy
    _, vecs = np.linalg.eigh(np.array([[sxx, sxy], [sxy, syy]]))
    e = vecs[:, -1]
    e = e / np.linalg.norm(e)
    # a line has two directions; the same one every time (its larger part positive). Only the line means anything:
    # the direction flips where the line passes 45 degrees, so no caller should read the foot's toe end from it
    e = e if e[np.argmax(np.abs(e))] > 0 else -e
    perp = np.array([-e[1], e[0]])
    return e, float(np.ptp(H @ e)), float(np.ptp(H @ perp))


def provisional_frame(mesh, foot: str) -> tuple[FootFrame, dict]:
    if foot not in ("left", "right"):
        raise PlantarError(f"foot must be 'left' or 'right', got {foot!r}")
    V = np.asarray(mesh.vertices)
    low = V[V[:, 2] < FOOTPRINT_BAND_MM]
    if len(low) < 100:
        raise PlantarError("almost no surface near the floor; is this a standing or semi-standing scan?")
    xy = low[:, :2]
    mu = xy.mean(0)
    axis, length, width = long_axis(xy)
    elongation = length / max(width, 1e-9)

    notes = []
    # the mat's instruction: toes toward +y, however far the foot lies from the mat's y. Only a foot lying along x
    # (within MAT_ACROSS_TOL) the instruction says nothing about: then toward +x, as the SYNTHETIC test feet lie in
    # foot coordinates. Until 25 Nov that case took the sign of the axis's y part too, a rounding error's sign:
    # with the axis down the middle of the footprint, synth.curved_foot without a leg came out heel first.
    along_x = abs(axis[1]) < MAT_ACROSS_TOL
    by_mat = 1.0 if (axis[0] if along_x else axis[1]) >= 0 else -1.0
    high = V[V[:, 2] > LEG_MIN_HEIGHT_MM]
    by_leg = None
    if len(high) > 50:
        s = (high[:, :2].mean(0) - mu) @ axis
        by_leg = -1.0 if s > 0 else 1.0  # the leg is over the heel, so forward points away from it
    sign = by_leg if by_leg is not None else by_mat
    if by_leg is not None and by_leg != by_mat:
        notes.append("the foot points away from the toe sheet (the leg says so); used the leg")
    if by_leg is None:
        notes.append("no leg in the scan, so the toe end was taken from the mat's direction")
    fwd2 = sign * axis
    along = (low[:, :2] - mu) @ fwd2
    heel_xy = mu + along.min() * fwd2

    anterior = np.r_[fwd2, 0.0]
    up = np.array([0.0, 0.0, 1.0])
    left = np.cross(up, anterior)
    medial = left if foot == "right" else -left
    frame = FootFrame(np.r_[heel_xy, 0.0], anterior, medial, up, foot, "support_plane")
    info = dict(
        provisional=True,
        method="mat floor + footprint principal axis; replaced by landmarks in Phase 3",
        footprint_elongation=round(elongation, 2),
        toe_end_from="leg" if by_leg is not None else "mat",
        notes=notes,
    )
    return frame, info


def to_foot(mesh, frame: FootFrame):
    """A copy of the mesh in foot coordinates (anterior, medial, up)."""
    out = mesh.copy()
    T = np.eye(4)
    T[:3, :3] = frame.rotation
    T[:3, 3] = -frame.rotation @ frame.origin
    # Left-foot frames are mirror images; trimesh notices the negative
    # determinant and flips the triangles' winding so they still face outward.
    out.apply_transform(T)
    return out


def plantar_surface(foot_mesh):
    """Downward-facing surface near the floor (foot coordinates)."""
    m = foot_mesh.copy()
    keep = (m.face_normals[:, 2] < -DOWNWARD_COS) & (m.triangles_center[:, 2] < PLANTAR_MAX_HEIGHT_MM)
    m.update_faces(keep)
    m.remove_unreferenced_vertices()
    return m


def footprint_outline(foot_mesh, max_height: float = 1.5) -> np.ndarray:
    """Open-edge vertices at floor level, flattened: where the foot meets the paper (N x 2)."""
    import trimesh

    edges = foot_mesh.edges_sorted
    groups = trimesh.grouping.group_rows(edges, require_count=1)  # edges used by one face = the border
    border = np.unique(edges[groups].ravel())
    P = foot_mesh.vertices[border]
    return P[P[:, 2] < max_height][:, :2]


def medial_profile(foot_mesh, step: float = PROFILE_STEP_MM) -> list[dict]:
    """Lowest surface height on the inside third of the foot, every ``step`` mm from heel to toe."""
    V = np.asarray(foot_mesh.vertices)
    low = V[V[:, 2] < FOOTPRINT_BAND_MM]
    length = float(low[:, 0].max())
    out = []
    for x in np.arange(step, length - step / 2, step):
        sl = V[np.abs(V[:, 0] - x) < step / 2]
        sl = sl[sl[:, 2] < PLANTAR_MAX_HEIGHT_MM]
        if len(sl) < 5:
            continue
        lo, hi = np.percentile(sl[:, 1], [1, 99])
        inner = sl[sl[:, 1] > hi - (hi - lo) / 3]
        if len(inner) < 3:
            continue
        out.append(dict(x_mm=round(float(x), 1), height_mm=round(float(inner[:, 2].min()), 2)))
    return out


def run(mesh, foot: str) -> dict:
    """Frame, foot-frame mesh, plantar surface, outline and arch profile for one weight-bearing scan."""
    frame, info = provisional_frame(mesh, foot)
    fm = to_foot(mesh, frame)
    low = fm.vertices[fm.vertices[:, 2] < FOOTPRINT_BAND_MM]
    outline = footprint_outline(fm)
    profile = medial_profile(fm)
    arch = max(profile, key=lambda r: r["height_mm"]) if profile else None
    summary = dict(
        **info,
        foot=foot,
        frame=dict(origin_mat_mm=frame.origin.round(3).tolist(), anterior=frame.anterior.round(6).tolist(),
                   medial=frame.medial.round(6).tolist(), up=frame.up.tolist()),
        footprint_length_mm=round(float(low[:, 0].max() - low[:, 0].min()), 1),
        footprint_width_mm=round(float(np.percentile(low[:, 1], 99.5) - np.percentile(low[:, 1], 0.5)), 1),
        medial_profile=profile,
        highest_medial_point=arch,
        outline_points=int(len(outline)),
    )
    return dict(summary=summary, foot_mesh=fm, plantar=plantar_surface(fm), outline=outline)
