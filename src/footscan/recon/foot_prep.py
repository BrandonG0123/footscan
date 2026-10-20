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

The bottom of the foot is what the insole is made from, and a foot resting
on the floor hides it. Two kinds of scan show it instead (``PREPARE``):

- **sole up** (``prepare_sole_up``): lying face down, knee bent, the sole
  facing the ceiling. Nothing presses on the foot, so the arch reads as
  high as it is unloaded (the generator's caps still apply).
- **foam print** (``prepare_impression``): the dent a foot leaves in a foam
  impression box, scanned from above. Partly loaded, and the print holds
  still for as long as the scan takes; its depth can be checked with
  calipers.
"""

from __future__ import annotations

import numpy as np

from . import imported, plantar

LEG_TRIM_MM = 70.0          # keep the foot, drop the leg above about ankle height
FOOTPRINT_BAND_MM = 12.0
LEG_MIN_HEIGHT_MM = 90.0    # a leg reaches well above the foot itself
LEG_MIN_AREA_MM2 = 1500.0   # that much surface above it is a leg (a 20 mm stub of shin is about 3500)
MAT_CENTRE = (100.0, 150.0)
DENSIFY_MM = 2.0


class FootPrepError(ValueError):
    pass


def _yaw(angle: float) -> np.ndarray:
    T = np.eye(4)
    c, s = np.cos(angle), np.sin(angle)
    T[:2, :2] = [[c, -s], [s, c]]
    return T


def _shift(x: float, y: float, z: float) -> np.ndarray:
    T = np.eye(4)
    T[:3, 3] = [x, y, z]
    return T


def _move(mesh, T, track: list) -> None:
    """Apply the 4 x 4 transform ``T`` to ``mesh`` and to the running total in ``track[0]``.

    The total (scan as handed over -> mat frame) goes into the decisions as
    ``to_mat``: the studio's preview lays the scan and the insole together
    with it, and the benchmark checks every point against the true shape."""
    mesh.apply_transform(T)
    track[0] = T @ track[0]


def _up_turn(up: str) -> np.ndarray:
    if up not in imported.UP:
        raise ValueError(f"up must be one of {sorted(imported.UP)}")
    T = np.eye(4)
    T[:3, :3] = imported.UP[up]
    return T


def _densify(placed, info):
    """The phone builds a coarse model (points ~5 mm apart); split its triangles
    to 2 mm so the footprint and the leg are found by area, not by luck.
    Linear: it adds points, not shape."""
    import trimesh

    if len(placed.faces) and np.median(placed.edges_unique_length) > DENSIFY_MM:
        v, f = trimesh.remesh.subdivide_to_size(placed.vertices, placed.faces, max_edge=DENSIFY_MM)
        placed = trimesh.Trimesh(v, f, process=True)
        info["densified_to_mm"] = DENSIFY_MM
    return placed


NOISE_PROBE_MM = 4.0          # the noise is read as what a blur this wide takes away
NOISY_SCAN_MM = 0.15          # noise above this is smoothed out; below it the scan is left exactly as it is
DENOISE_SIGMA_MM = 4.0        # the blur for a noisy scan: far smaller than an arch (40 mm and more across)
ROUGH_SCAN_MM = 0.5           # surface noise above this: see plausibility()


def _blur(mesh, sigma_mm: float):
    """Blur the surface over about ``sigma_mm`` (a Gaussian along the skin), whatever the triangle size.

    Repeated neighbour-averaging: each round moves every point half way to
    the average of its neighbours, which spreads it like a Gaussian whose
    width grows with the number of rounds and the triangle size. Bumps much
    smaller than ``sigma_mm`` go; the shape stays, except that tight curves
    flatten by about sigma^2 / (2 x their radius): 0.15 mm on a heel pad
    curving at 30 mm, for a 3 mm blur. Points on an open edge (a print's
    rim, a cut) are smoothed too (held still, their noise would stick out
    of the outline); averaging only ever pulls them slightly inward.
    """
    import trimesh
    import trimesh.smoothing

    m = mesh.copy()
    if not len(m.faces):
        return m
    edge = float(np.median(m.edges_unique_length))
    rounds = int(np.clip(np.ceil(4.0 * (sigma_mm / max(edge, 1e-3)) ** 2), 1, 2000))
    L = trimesh.smoothing.laplacian_calculation(m, equal_weight=True)
    V = np.array(m.vertices, dtype=float)
    for _ in range(rounds):
        V = 0.5 * V + 0.5 * L.dot(V)
    m.vertices = V
    return m


def _denoise(m, info):
    """Smooth out scan speckle if the scan has any; records how rough it was.

    Roughness: what a narrow blur (``NOISE_PROBE_MM``) takes away, measured
    along the surface's normal, as a robust typical value (1.48 x the median
    distance, which is the standard deviation for random noise). The median
    ignores the few points on edges and tight curves, which the blur also
    moves. It reads speckle up to a few mm across; longer undulations are
    shape as far as any scan can tell.

    A scan under ``NOISY_SCAN_MM`` is left exactly as it is. A noisier one
    is blurred over ``DENOISE_SIGMA_MM``: otherwise the insole would copy
    the noise's bumps into its surface.
    """
    probe = _blur(m, NOISE_PROBE_MM)
    d = np.einsum("ij,ij->i", m.vertices - probe.vertices, probe.vertex_normals)
    noise = float(1.4826 * np.median(np.abs(d)))
    info["surface_noise_mm"] = round(noise, 2)
    if noise <= NOISY_SCAN_MM:
        info["denoised"] = "no: the scan's surface is clean"
        return m
    info["denoised"] = f"blurred over about {DENOISE_SIGMA_MM} mm to take out scan speckle"
    return _blur(m, DENOISE_SIGMA_MM)


def _pieces(mesh, reaches_z: float | None = None):
    """Connected pieces as face masks, biggest (by area) first, with their areas.

    With ``reaches_z``, only pieces that reach up to that height count."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components

    n = len(mesh.faces)
    adj = mesh.face_adjacency
    g = coo_matrix((np.ones(len(adj)), (adj[:, 0], adj[:, 1])), shape=(n, n))
    count, label = connected_components(g, directed=False)
    areas = np.bincount(label, weights=mesh.area_faces, minlength=count)
    if reaches_z is not None:
        top = np.full(count, -np.inf)
        np.maximum.at(top, label, mesh.triangles_center[:, 2])
        areas[top < reaches_z] = 0.0
    order = [i for i in np.argsort(areas)[::-1] if areas[i] > 0]
    return [(label == i, float(areas[i])) for i in order]


def _largest_piece(mesh, reaches_z: float | None = None):
    """The biggest connected piece by area (drops stray bits the scan picked up).

    With ``reaches_z``, only pieces that reach up to that height count.
    Returns (piece, second-biggest area / biggest area)."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components

    n = len(mesh.faces)
    adj = mesh.face_adjacency
    g = coo_matrix((np.ones(len(adj)), (adj[:, 0], adj[:, 1])), shape=(n, n))
    count, label = connected_components(g, directed=False)
    if count <= 1:
        return mesh, 0.0
    areas = np.bincount(label, weights=mesh.area_faces, minlength=count)
    if reaches_z is not None:
        top = np.full(count, -np.inf)
        np.maximum.at(top, label, mesh.triangles_center[:, 2])
        areas[top < reaches_z] = 0.0
        if not areas.any():
            return mesh, 0.0  # nothing qualifies: the caller's own check says so
    order = np.argsort(areas)[::-1]
    out = mesh.copy()
    out.update_faces(label == order[0])
    out.remove_unreferenced_vertices()
    return out, float(areas[order[1]] / areas[order[0]])


def rest_on_hull(mesh):
    """Lay the foot on a flat floor the way it would rest on a table: no weight, no squashing.

    Wrap the scan in its convex hull (a rubber band round it) and find the
    hull's underside directly below the scan's centre (area-weighted). That
    face touches the lowest parts of the sole, normally the heel and the ball
    of the foot, and it becomes the floor: turned flat and set to z = 0.
    The arch stays up, as far above that floor as it really is. Run on the
    denoised scan (``_denoise``): on the benchmark (scripts/benchmark_prep.py)
    that leaves no measurable floor bias even with 1 mm of scan noise.
    Returns (mesh, degrees it was tipped, 4 x 4 transform applied).
    """
    from scipy.spatial import ConvexHull

    m = mesh.copy()
    V = np.asarray(m.vertices)
    hull = ConvexHull(V)
    normals = hull.equations[:, :3]  # outward, unit length
    w = m.area_faces
    c = (m.triangles_center * w[:, None]).sum(0) / w.sum()
    best, best_cos = None, -1.0
    for fi in np.nonzero(normals[:, 2] < -0.3)[0]:
        n = normals[fi]
        tri = V[hull.simplices[fi]]
        z = tri[0][2] - (n[0] * (c[0] - tri[0][0]) + n[1] * (c[1] - tri[0][1])) / n[2]
        q = np.array([c[0], c[1], z])
        v0, v1, v2 = tri[1] - tri[0], tri[2] - tri[0], q - tri[0]
        d00, d01, d11, d20, d21 = v0 @ v0, v0 @ v1, v1 @ v1, v2 @ v0, v2 @ v1
        den = d00 * d11 - d01 * d01
        if abs(den) < 1e-12:
            continue
        b1 = (d11 * d20 - d01 * d21) / den
        b2 = (d00 * d21 - d01 * d20) / den
        if b1 >= -1e-6 and b2 >= -1e-6 and b1 + b2 <= 1 + 1e-6 and -n[2] > best_cos:
            best, best_cos = fi, -n[2]
    if best is None:
        raise FootPrepError("couldn't find what the sole would rest on: is the sole in the scan?")
    R = imported._level(-normals[best])  # that face's downward normal -> straight down
    T = np.eye(4)
    T[:3, :3] = R
    T[2, 3] = -(V @ R.T)[:, 2].min()  # the floor: that face, now level, at z = 0
    m.apply_transform(T)
    return m, float(np.degrees(np.arccos(np.clip(best_cos, -1, 1)))), T


def _bowl_low(Q, keep_mm: float) -> np.ndarray | None:
    """The bottom of a contact area: a smooth bowl (z = quadratic in x, y) fitted to points Q
    by least squares, three times, each time keeping only the points where the last fit is
    within ``keep_mm`` of its lowest (a contact area's rising rim, where the sole curves up
    toward the edge, would otherwise tilt it). Returns the middle of what's left and the
    fitted height there: steadier than the fit's own lowest point, which slides to whichever
    edge a slight tilt favours. None if too few points.
    """
    for _ in range(3):
        if len(Q) < 30:
            return None
        c = Q[:, :2].mean(0)
        dx, dy = Q[:, 0] - c[0], Q[:, 1] - c[1]
        A = np.c_[np.ones(len(Q)), dx, dy, dx * dx, dx * dy, dy * dy]
        coef, *_ = np.linalg.lstsq(A, Q[:, 2], rcond=None)
        fit = A @ coef
        kept = Q[fit < fit.min() + keep_mm]
        if len(kept) < 30:
            break
        Q = kept
    c = Q[:, :2].mean(0)
    dx, dy = Q[:, 0] - c[0], Q[:, 1] - c[1]
    A = np.c_[np.ones(len(Q)), dx, dy, dx * dx, dx * dy, dy * dy]
    coef, *_ = np.linalg.lstsq(A, Q[:, 2], rcond=None)
    return np.array([c[0], c[1], coef[0]])  # coef[0]: the fitted height at the middle


def _settle_floor(placed, info) -> np.ndarray:
    """On a noisy scan, put the floor where the skin really is. -> 4 x 4 transform (identity if clean).

    ``rest_on_hull`` lays the scan on its three lowest points. On a noisy
    scan those are specks of noise, a little below the skin and in random
    places: the floor sits low (every height reads high, by about 1.5 x the
    noise on the benchmark) and can tilt by a degree, a wedge of nearly
    2 mm across the foot, which a first fit must not have.

    So the floor is set from the tripod a foot stands on: the heel, and the
    inner and outer sides of the ball of the foot. The contact areas (the
    underside within a few noise-widths of the floor) are split into those
    three, each is fitted with a smooth bowl by least squares (which
    averages the noise out instead of picking its lowest speck), and the
    floor goes through the three bowls' lowest points. If a part has too
    few points, only the floor's height is corrected, from the parts there
    are. A clean scan is left exactly as it is.
    """
    noise = info.get("surface_noise_mm", 0.0)
    if noise <= NOISY_SCAN_MM:
        return np.eye(4)
    V, N = placed.vertices, placed.vertex_normals
    band = 3.0 * noise + 0.5
    contact = (N[:, 2] < -0.7) & (V[:, 2] < band)
    if contact.sum() < 60:
        return np.eye(4)
    P = V[contact]
    axis, _, _ = plantar.long_axis(P[:, :2])
    side = np.array([-axis[1], axis[0]])
    along = (P[:, :2] - P[:, :2].mean(0)) @ axis
    lo, L = along.min(), np.ptp(along)
    ends = [P[along < lo + 0.35 * L], P[along > lo + 0.55 * L]]
    # which end is the heel doesn't matter here: the narrower contact area is split no further,
    # the wider one (the ball of the foot) into its two sides
    widths = [np.ptp(E[:, :2] @ side) if len(E) else 0.0 for E in ends]
    heel, ball = (ends[0], ends[1]) if widths[0] <= widths[1] else (ends[1], ends[0])
    keep = max(1.0, 2.0 * noise)
    lows = [_bowl_low(heel, keep)]
    if len(ball):
        across = ball[:, :2] @ side
        mid = np.median(across)
        lows += [_bowl_low(ball[across <= mid], keep), _bowl_low(ball[across > mid], keep)]
    lows = [q for q in lows if q is not None]
    if len(lows) == 3:
        n = np.cross(lows[1] - lows[0], lows[2] - lows[0])
        n = n / np.linalg.norm(n) if np.linalg.norm(n) > 1e-9 else np.array([0.0, 0.0, 1.0])
        n = n if n[2] > 0 else -n
        if n[2] > np.cos(np.radians(3.0)):  # a correction of the hull's floor, not a new one
            R = imported._level(n)
            T = np.eye(4)
            T[:3, :3] = R
            T[2, 3] = -float(np.mean((np.array(lows) @ R.T)[:, 2]))
            info["floor_from"] = "tripod: smooth fits under the heel and both sides of the ball of the foot"
            info["floor_corrected_deg"] = round(float(np.degrees(np.arccos(np.clip(n[2], -1, 1)))), 2)
            info["floor_lifted_mm"] = round(-float(T[2, 3]), 2)
            return T
    if not lows:
        return np.eye(4)
    lift = float(np.clip(np.mean([q[2] for q in lows]), 0.0, band))
    info["floor_lifted_mm"] = round(lift, 2)
    return _shift(0.0, 0.0, -lift)


def _end_widths(V, mu, axis):
    """Widths (mm) of the footprint's two end thirds: (toward -axis, toward +axis).

    The same share of the length at each end: the back 30% holds the heel,
    the front 30% the ball of the foot."""
    P = V[V[:, 2] < insole_silhouette_mm()][:, :2] - mu
    along, across = P @ axis, P @ np.array([-axis[1], axis[0]])
    lo, L = along.min(), np.ptp(along)
    return float(np.ptp(across[along < lo + 0.3 * L])), float(np.ptp(across[along > lo + 0.7 * L]))


def _heel_side(placed, mu, axis, by: str, info) -> float:
    """+1 if the heel is toward +axis, -1 if toward -axis. Records how it was decided.

    In order: the leg, if the scan has one (it stands over the heel); else
    the narrower end (a heel is about 2/3 as wide as the ball of the foot),
    if the ends clearly differ; else the taller end (the ankle side).
    ``by="width"`` (a foam print: no leg) starts at the width test."""
    V = np.asarray(placed.vertices)
    if by != "width":
        up = placed.triangles_center[:, 2] > LEG_MIN_HEIGHT_MM
        # by surface area, not point count: a coarsely meshed leg has few points
        if placed.area_faces[up].sum() > LEG_MIN_AREA_MM2:
            info["heel_from"] = "the leg stands over it"
            c = np.average(placed.triangles_center[up, :2], axis=0, weights=placed.area_faces[up])
            return float(np.sign((c - mu) @ axis) or 1.0)
    wa, wb = _end_widths(V, mu, axis)
    info["end_widths_mm"] = dict(minus_end=round(wa, 1), plus_end=round(wb, 1))
    if min(wa, wb) / max(wa, wb, 1e-9) <= 0.9:
        info["heel_from"] = ("the narrower end (a heel is narrower than the ball of the foot)" if by == "width"
                             else "no leg in the scan: the narrower end (a heel is narrower than the ball of the foot)")
        return -1.0 if wa < wb else 1.0
    info["heel_warning"] = ("both ends are almost the same width, so which end is the heel is a guess: "
                            "check the toes point the right way in the 3D model")
    along = (V[:, :2] - mu) @ axis
    t = np.ptp(along) / 3
    rear = V[along < along.min() + t, 2]
    front = V[along > along.max() - t, 2]
    info["heel_from"] = "no leg, ends the same width: the taller end (ankle side) taken as the heel"
    return -1.0 if np.percentile(rear, 95) >= np.percentile(front, 95) else 1.0


def insole_silhouette_mm() -> float:
    from .. import insole

    return insole.SILHOUETTE_HEIGHT_MM


def _orient_and_trim(placed, info, trim_mm, heel_by: str = "leg", track: list | None = None):
    """Floor already at z = 0: turn toes to +y, centre on the mat, trim the leg."""
    track = track if track is not None else [np.eye(4)]
    V = np.asarray(placed.vertices)
    low = V[V[:, 2] < FOOTPRINT_BAND_MM]
    if len(low) < 100:
        raise FootPrepError("almost nothing of the scan is near the floor: was the foot resting on the floor?")
    mu = low[:, :2].mean(0)
    axis, length, width = plantar.long_axis(low[:, :2])
    heel_side = _heel_side(placed, mu, axis, heel_by, info)
    toes = -heel_side * axis

    # turn the toes onto +y, then centre the footprint on the mat
    _move(placed, _yaw(np.arctan2(toes[0], toes[1])), track)
    low_after = placed.vertices[placed.vertices[:, 2] < FOOTPRINT_BAND_MM][:, :2]
    centre = (low_after.min(0) + low_after.max(0)) / 2
    _move(placed, _shift(MAT_CENTRE[0] - centre[0], MAT_CENTRE[1] - centre[1], 0.0), track)

    info["footprint_mm"] = dict(length=round(float(length), 1), width=round(float(width), 1))
    info["to_mat"] = np.round(track[0], 9).tolist()
    info["height_before_trim_mm"] = round(float(placed.vertices[:, 2].max()), 1)
    if trim_mm is not None and info["height_before_trim_mm"] > trim_mm:
        keep = placed.triangles_center[:, 2] <= trim_mm
        info["trimmed_above_mm"] = trim_mm
        info["trimmed_share"] = round(float(1 - keep.mean()), 3)
        placed.update_faces(keep)
        placed.remove_unreferenced_vertices()
        placed = _lid(placed, trim_mm)
    info["to_mat"] = np.round(track[0], 9).tolist()
    return placed


def prepare(mesh, up: str = "y", trim_mm: float | None = LEG_TRIM_MM):
    """Any-units, Object-Capture-frame foot -> (mat-frame mesh, decisions). Doesn't modify the input."""
    mm, units, _ = imported.to_millimetres(mesh)
    placed, _, floor_info = imported.to_floor_frame(mm, up)
    info = dict(kind="foot", units_detected=units, up_axis=up, floor=floor_info["floor"])
    if "floor_tilt_corrected_deg" in floor_info:
        info["floor_tilt_corrected_deg"] = floor_info["floor_tilt_corrected_deg"]
    placed = _densify(placed, info)
    placed = _denoise(placed, info)
    return _orient_and_trim(placed, info, trim_mm), info


# A sole-up scan: lying face down, knee bent, the sole facing the ceiling.
SOLE_UP_KEEP_MM = 300.0     # keep this much above the lowest point: the foot tipped as far as 50 degrees (toes
                            # lowest, heel ~190 mm up) plus enough shin to find the heel by; the bed is ~400 away
SOLE_UP_MAX_TIP_DEG = 50.0


def prepare_sole_up(mesh, up: str = "y", trim_mm: float | None = LEG_TRIM_MM):
    """Sole-up scan (the sole faced the ceiling, nothing pressing on it) -> (mat-frame mesh, decisions).

    1. Turn it over: the phone knows which way was up, so the sole now faces
       down and the shin stands up from it, as if standing (but unloaded).
    2. Keep the bottom ``SOLE_UP_KEEP_MM`` (the foot and some shin; the bed
       and the rest of the leg go) and the biggest connected piece.
    3. Rest it on a flat floor (``rest_on_hull``): the heel and the ball of
       the foot touch, the arch stays as high as it was scanned.
    4. Toes to +y (the shin is over the heel), centre, trim the shin, lid it.
    """
    mm, units, factor = imported.to_millimetres(mesh)
    track = [np.diag([factor, factor, factor, 1.0])]
    m = mm.copy()
    _move(m, _up_turn(up), track)
    _move(m, np.diag([1.0, -1.0, -1.0, 1.0]), track)  # half a turn about x: sole down, shin up (not a mirror)
    _move(m, _shift(0, 0, -m.vertices[:, 2].min()), track)
    info = dict(kind="sole_up", units_detected=units, up_axis=up,
                floor="sole-up scan: turned over, then rested on the heel and the ball of the foot")
    m = _densify(m, info)
    m.update_faces(m.triangles_center[:, 2] < SOLE_UP_KEEP_MM)
    m.remove_unreferenced_vertices()
    m, other = _largest_piece(m)
    if other > 0.2:
        info["pieces_warning"] = "the scan had more than one large piece; the biggest was used"
    m = _denoise(m, info)
    placed, tip, T = rest_on_hull(m)
    T = _settle_floor(placed, info) @ T
    placed = m.copy()
    placed.apply_transform(T)
    track[0] = T @ track[0]
    info["tipped_to_rest_deg"] = round(tip, 1)
    return _orient_and_trim(placed, info, trim_mm, track=track), info


# A foam print: the dent a foot leaves in a foam impression box, scanned from above.
PRINT_BELOW_TOP_MM = 1.0    # the print starts this far below the foam's top surface
PRINT_MAX_DEPTH_MM = 90.0   # deeper than this is the box's sides or the table, not the print
PRINT_EDGE_MM = 4.0         # ignore this close to the foam's outer edge (the box's walls)
PRINT_MIN_AREA_MM2 = 8000.0
PRINT_SHALLOW_MM = 15.0     # shallower than this, an arch may never have touched the foam
FOAM_TOP_MIN_AREA_MM2 = 5000.0  # the foam's top round the print: a few times this, even for one narrow block
FOAM_TOP_MAX_TILT_DEG = 25.0    # the box may sit this far off level


def _foam_top(m, tries: int = 200, seed: int = 0):
    """The foam's flat top: the highest big flat surface. -> (a point on it, its normal, its points).

    Planes are found whole, at whatever modest tilt the box sits (a table
    needn't be level, and the phone's sense of level is close, not exact):
    pick a patch of upward-facing surface (bigger triangles more often), fit
    its plane from the patch's average normal, and collect everything within
    2.5 mm of that plane. Membership goes by distance only, not by which way
    each triangle faces: on a rough scan the little triangles tilt every
    which way while still lying on the surface. Planes of at least
    ``FOAM_TOP_MIN_AREA_MM2`` are candidates; the highest is the foam's top
    (a table round the box, or a flat-bottomed print, is lower).
    """
    from scipy.spatial import cKDTree

    up = m.face_normals[:, 2] > np.cos(np.radians(FOAM_TOP_MAX_TILT_DEG))
    if not up.any():
        raise FootPrepError("no flat foam surface found: is this a scan of a foam box from above?")
    Ca, Aa = m.triangles_center, m.area_faces
    C, N, A = Ca[up], m.face_normals[up], Aa[up]
    tree = cKDTree(C)
    rng = np.random.default_rng(seed)
    best = None
    for i in rng.choice(len(C), size=min(tries, len(C)), replace=False, p=A / A.sum()):
        nb = tree.query_ball_point(C[i], 15.0)
        c = np.average(C[nb], axis=0, weights=A[nb])
        n = np.average(N[nb], axis=0, weights=A[nb])
        n /= np.linalg.norm(n)
        on = np.abs((Ca - c) @ n) < 2.5
        area = float(Aa[on].sum())
        if area < FOAM_TOP_MIN_AREA_MM2:
            continue
        height = float(np.average(Ca[on, 2], weights=Aa[on]))
        if best is None or height > best[0] + 5.0 or (abs(height - best[0]) <= 5.0 and area > best[3]):
            best = (height, c, n, area)
    if best is None:
        raise FootPrepError("no flat foam surface found: is this a scan of a foam box from above?")
    _, c, n, _ = best
    # Refit exactly from the triangles on it, three times (each fit gathers the whole top better):
    # their centres, weighted by area, and only roughly flat ones (within 45 degrees), so a steep
    # wall triangle whose centre happens to be near the top can't drag the plane.
    Na = m.face_normals
    for _ in range(3):
        on = (np.abs((Ca - c) @ n) < 2.5) & (Na @ n > np.cos(np.radians(45.0)))
        w = Aa[on]
        c = np.average(Ca[on], axis=0, weights=w)
        D = Ca[on] - c
        n = np.linalg.eigh((D * w[:, None]).T @ D)[1][:, 0]  # least-spread direction (3 x 3: any number of points)
        n = n if n[2] > 0 else -n
    P = m.vertices[np.unique(m.faces[on])]
    return c, n, P


def _looks_like(placed) -> str | None:
    """Which foot a sole (mat frame, toes toward +y) looks like, from where its arch is.

    The arch is on the inner side: across the middle of the foot, the sole
    stands higher there. Facing the toes, a right foot's inner side is on the
    left (-x), a left foot's on the right (+x). None if the two sides are
    within a millimetre of each other.
    """
    V, N = placed.vertices, placed.vertex_normals
    y0, y1 = V[:, 1].min(), V[:, 1].max()
    L = y1 - y0
    sole = (N[:, 2] < -0.5) & (V[:, 1] > y0 + 0.35 * L) & (V[:, 1] < y0 + 0.6 * L) & (V[:, 2] < 30)
    if sole.sum() < 20:
        return None
    cx = np.median(V[sole, 0])
    left = V[sole & (V[:, 0] < cx), 2]
    right = V[sole & (V[:, 0] >= cx), 2]
    if not len(left) or not len(right) or abs(np.mean(left) - np.mean(right)) < 1.0:
        return None
    return "right" if np.mean(left) > np.mean(right) else "left"


def prepare_impression(mesh, up: str = "y", trim_mm: float | None = LEG_TRIM_MM, foot: str | None = None):
    """Foam-print scan -> (mat-frame mesh of the sole, decisions).

    A foot pressed into foam leaves its sole's exact shape, facing down, just
    as it was: the print *is* the bottom of the foot, held still.
    1. Find the foam's flat top (the highest big level surface) and level it.
    2. The print is everything below that top, inside the foam's outline,
       in one connected piece that opens at the top (the box's walls, its
       closed-off bottom and the table are left out).
    3. Its surface is the sole seen from the foot's side, so its triangles
       are turned to face down, the way the sole faces.
    4. Rest it on a flat floor (``rest_on_hull``): the deepest points (heel
       and ball of the foot) become z = 0, the arch is as high above it as
       the print is shallower there.
    5. Toes to +y: the narrower end is the heel. Centre on the mat.
    With two prints in the scan (a box with a block for each foot), each is
    prepared and the one whose arch is on ``foot``'s inner side is used.
    """
    import shapely
    from shapely.geometry import MultiPoint

    mm, units, factor = imported.to_millimetres(mesh)
    track = [np.diag([factor, factor, factor, 1.0])]
    m = mm.copy()
    _move(m, _up_turn(up), track)
    info = dict(kind="impression", units_detected=units, up_axis=up)
    c, n, top_pts = _foam_top(m)
    R = imported._level(n)
    T = np.eye(4)
    T[:3, :3] = R
    T[:3, 3] = -R @ c
    _move(m, T, track)  # foam top at z = 0, level
    info["foam_top_tilt_deg"] = round(float(np.degrees(np.arccos(np.clip(n[2], -1, 1)))), 2)
    outline = shapely.convex_hull(MultiPoint(((top_pts - c) @ R.T)[:, :2])).buffer(-PRINT_EDGE_MM)
    ctr = m.triangles_center
    inside = shapely.contains_xy(outline, m.vertices[:, 0], m.vertices[:, 1])[m.faces].all(axis=1)
    # Below the top, inside the foam's outline. No test of which way triangles face (a rough scan's
    # tilt every which way): the box's closed-off bottom and any table under it are separate pieces
    # that don't reach up to the foam's top, and are left out below.
    keep = (ctr[:, 2] < -PRINT_BELOW_TOP_MM) & (ctr[:, 2] > -PRINT_MAX_DEPTH_MM) & inside
    if not keep.any():
        raise FootPrepError("no print found below the foam's top surface")
    m.update_faces(keep)
    m.remove_unreferenced_vertices()
    # a print opens at the foam's top: pieces that don't reach up to it (a table showing under the box) aren't prints
    pieces = _pieces(m, reaches_z=-PRINT_BELOW_TOP_MM - 5)
    if not pieces:
        raise FootPrepError("what's below the foam's top doesn't reach up to it, so it isn't a print in the foam")
    candidates = [pieces[0]] + [p for p in pieces[1:2] if p[1] > 0.4 * pieces[0][1]]

    results = []
    for mask, _area in candidates:
        piece = m.copy()
        piece.update_faces(mask)
        piece.remove_unreferenced_vertices()
        pinfo = dict(info)
        piece = _densify(piece, pinfo)  # only the print: the box and the table aren't needed in detail
        if piece.area < PRINT_MIN_AREA_MM2:
            continue
        piece.invert()  # the print's surface faces up out of the foam; the sole it holds faces down
        piece = _denoise(piece, pinfo)
        placed, tip, Tr = rest_on_hull(piece)
        Tr = _settle_floor(placed, pinfo) @ Tr
        placed = piece.copy()
        placed.apply_transform(Tr)
        # depth: how far the floor the sole rests on lies below the foam's top (the fitted floor, so
        # a single noisy speck isn't taken for the bottom of the print)
        foam_top_z = (Tr @ np.array([0.0, 0.0, 0.0, 1.0]))[2]
        pinfo["print_deepest_mm"] = round(float(foam_top_z), 1)
        ptrack = [Tr @ track[0]]
        pinfo["tipped_to_rest_deg"] = round(tip, 1)
        placed = _orient_and_trim(placed, pinfo, trim_mm, heel_by="width", track=ptrack)
        results.append((placed, pinfo, _looks_like(placed)))
    if not results:
        raise FootPrepError(f"the print is only {m.area / 100:.0f} cm2 of surface: too small for a foot print. "
                            "If there is a print in the scan, scan again closer and in brighter light")

    placed, info, looks = results[0]
    if len(results) > 1:
        match = [r for r in results if foot and r[2] == foot]
        if len(match) == 1:
            placed, info, looks = match[0]
            info["pieces_note"] = f"two prints found (two foam blocks?): used the one that looks like a {foot} foot"
        else:
            info["pieces_warning"] = ("two prints found (two foam blocks?) and it isn't clear which is the "
                                      f"{foot or 'chosen'} foot: the bigger one was used. Scan one print at a time")
    if info["print_deepest_mm"] < PRINT_SHALLOW_MM:
        info["shallow_warning"] = (f"the print is only {info['print_deepest_mm']:.0f} mm deep: the arch may not have reached "
                                   "the foam, and then the insole is flat under it. Press the foot in deeper and scan again")
    info["floor"] = "foam print: the foam's top levelled, then rested on the print's deepest points (heel and ball)"
    return placed, info


PREPARE = {"foot": prepare, "sole_up": prepare_sole_up, "impression": prepare_impression}


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


def insole_from_object_capture(mesh, foot: str, up: str = "y", params=None, kind: str = "foot"):
    """Object Capture scan (a foot, a sole-up foot or a foam print) -> first-fit insole, with the prep decisions in its report."""
    from .. import insole

    if kind not in PREPARE:
        raise FootPrepError(f"kind must be one of {sorted(PREPARE)}")
    placed, info = (PREPARE[kind](mesh, up, foot=foot) if kind == "impression" else PREPARE[kind](mesh, up))
    ins = insole.from_scan(placed, foot, params)
    ins.report["prep"] = info
    ins.report["warnings"] = plausibility(info, ins.report, foot) + ins.report["warnings"]
    return ins, placed


# An adult foot's footprint: length and width/length ratio well outside these
# means the scan isn't a foot resting on the floor (or wasn't levelled right).
FOOT_LENGTH_MM = (180.0, 330.0)
FOOT_RATIO = (0.28, 0.50)
INVENTED_SOLE_SHARE = 0.9


def plausibility(info: dict, report: dict, foot: str | None = None) -> list[str]:
    """Warnings that the result shouldn't be trusted, in plain words. Empty when it looks like a foot."""
    out = []
    kind = info.get("kind", "foot")
    fp = info["footprint_mm"]
    L, W = fp["length"], fp["width"]
    ratio = W / max(L, 1e-9)
    if not (FOOT_LENGTH_MM[0] <= L <= FOOT_LENGTH_MM[1]) or not (FOOT_RATIO[0] <= ratio <= FOOT_RATIO[1]):
        out.append(f"DOESN'T LOOK LIKE A FOOT ON THE FLOOR: the part touching the floor is {L:.0f} x {W:.0f} mm "
                   f"(an adult foot is about {FOOT_LENGTH_MM[0]:.0f}-{FOOT_LENGTH_MM[1]:.0f} mm long and "
                   f"{FOOT_RATIO[0]:.2f}-{FOOT_RATIO[1]:.2f} times as wide as long). Don't print this insole.")
    if kind == "foot" and report["sole"]["seen"] > INVENTED_SOLE_SHARE:
        out.append(f"THE SOLE MAY BE INVENTED: the model has a surface under {report['sole']['seen']:.0%} of the "
                   "footprint, but a foot resting on the floor hides most of its sole. Object Capture closes the "
                   "bottom of a model by itself, so this underside is probably guessed, not scanned. "
                   "Don't trust the arch shape from this scan.")
    if kind != "foot" and report["sole"]["seen"] < 0.6:
        out.append(f"ONLY {report['sole']['seen']:.0%} OF THE SOLE WAS SCANNED: this kind of scan should show "
                   "nearly all of it. Scan again, covering the whole sole.")
    if kind == "sole_up" and info.get("tipped_to_rest_deg", 0) > SOLE_UP_MAX_TIP_DEG:
        out.append(f"the scan had to be tipped {info['tipped_to_rest_deg']:.0f} degrees to rest the sole flat: "
                   "was the sole really facing the ceiling? Check the insole's shape before printing.")
    if kind != "foot" and foot and report["max_fill_mm"] >= 3:
        y = report["max_fill_at_mm"]["y"]
        inner = y > 0 if foot == "right" else y < 0
        if not inner:
            out.append(f"THE ARCH IS ON THE OUTSIDE: the highest fill is on the outer side of the {foot} foot. "
                       f"Is this really the {foot} foot? Check before printing.")
    if info.get("surface_noise_mm", 0) > ROUGH_SCAN_MM:
        out.append(f"the scan's surface is rough ({info['surface_noise_mm']} mm of noise). It was smoothed and the "
                   "floor set from the heel and the ball of the foot, but on test shapes this much noise still left "
                   "the sole off by up to about a millimetre and the floor tipped by up to about a degree. "
                   "Scan again more slowly, in brighter, even light.")
    for k in ("heel_warning", "pieces_warning", "shallow_warning"):
        if k in info:
            out.append(info[k])
    return out
