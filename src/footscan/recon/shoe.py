"""A shoe's own insole, scanned lying on a table: its outline, to fit the printed insole to that shoe.

A shoe's insole is the exact shape of the inside of the shoe at the footbed:
an insole cut to it goes in the way the stock one came out. The foot's own
outline doesn't: it's narrower than most shoes at the heel and wider at the
ball, and a shoe's toe box runs well past the toes.

Reading the scan (``outline_from_scan``):

1. Millimetres, Z up (the phone knows which way was up).
2. The table, if the model kept it: try cutting at each big level surface,
   lowest first, and keep the first cut that leaves something insole-shaped
   above it (180-360 mm long, a quarter to a half as wide). The insole's own
   flat top is level too, but cutting there leaves only its heel cup's rim,
   which isn't insole-shaped, so it's passed over. No table: the whole model.
3. The outline seen from above (everything, at every height: the heel cup's
   rim flares out to the shoe's counter).
4. Its long axis along x, the narrower end (the heel) at x = 0, the heel's
   middle at y = 0.

Which shoe it's from (``handedness``): a shoe's last curves in toward the
big toe, so the insole's toe end lies to the big-toe side of the line from
the heel's middle through the ball's middle. Seen from above, a right shoe's
insole top side up has its toe end to the left of that line. An insole
from the other shoe, or one scanned upside down, is the mirror image of the
one wanted, so it is mirrored back, and the report says so. If the toe end
is within ``HAND_MIN_MM`` of the line (a straight-lasted shoe), it's used
as scanned, with a warning to check.

Fitting it to a foot (``fit_to_foot``), in the insole's frame (x forward
from the back of the heel, y toward the foot's left), against the foot's
outline within ``FIT_HEIGHT_MM`` of the floor, which is what stands on an
insole (higher up, a heel bulges out over it, inside the shoe's counter):

- The shoe's heel goes behind the foot's heel by the heel-cup wall margin
  (in a shoe the heel sits against the counter), its middle on the foot
  heel's middle.
- Then turned (up to 10 degrees, about the heel) and slid sideways (up to
  8 mm) to the place where the least of the foot hangs over the shoe's
  edge, then the least of a 3 mm band round the foot (so a shoe with room
  to spare has the foot in the middle), then the smallest move.

Where the foot is wider than the shoe's insole, the printed insole still
stops at the shoe's edge, and a warning says where and by how much.
"""

from __future__ import annotations

import numpy as np

from . import imported

TABLE_LEVEL_DEG = 10.0       # a surface this close to level may be the table
TABLE_MIN_AREA_MM2 = 5000.0  # ...and at least this big
TABLE_CUT_MM = 0.8           # keep what's more than this above it
TABLE_TRIES = 4
SHOE_LENGTH_MM = (180.0, 360.0)
SHOE_RATIO = (0.25, 0.50)
FIT_TURN_DEG = 10.0
FIT_SLIDE_MM = 8.0
FIT_BAND_MM = 3.0
OVERHANG_WARN_MM = 1.0
FIT_HEIGHT_MM = 10.0   # the foot's outline this close to the floor is what an insole has to hold
HAND_MIN_MM = 4.0      # the toe end this far to one side of the heel-ball line says which shoe it's from


class ShoeError(ValueError):
    pass


def _outline(xy: np.ndarray, cell: float = 1.0):
    """Points seen from above (2 mm apart or closer) -> the filled outline round them.

    The points are marked on a ``cell`` mm grid, the grid's gaps closed and its holes filled, and the
    outline drawn round the filled grid's edge cells only (a concave hull of every point is the same
    outline, many times slower)."""
    import shapely
    from scipy import ndimage
    from shapely.geometry import MultiPoint

    lo = xy.min(axis=0) - 4 * cell
    ij = np.floor((xy - lo) / cell).astype(int)
    occ = np.zeros(ij.max(axis=0) + 5, dtype=bool)
    occ[ij[:, 0], ij[:, 1]] = True
    occ = ndimage.binary_fill_holes(ndimage.binary_closing(occ, iterations=2))
    edge = occ & ~ndimage.binary_erosion(occ)
    pts = (np.argwhere(edge) + 0.5) * cell + lo
    try:
        poly = shapely.concave_hull(MultiPoint(pts), ratio=0.05)
    except shapely.errors.GEOSException:
        poly = shapely.convex_hull(MultiPoint(pts))
    poly = poly.buffer(cell / 2).buffer(-cell / 2)
    if poly.geom_type != "Polygon":
        poly = max(poly.geoms, key=lambda g: g.area)
    return poly


def _plausible(poly) -> bool:
    if poly.is_empty or poly.area < 100.0:
        return False
    x0, y0, x1, y1 = _oriented(poly)[0].bounds
    length, width = x1 - x0, y1 - y0
    return SHOE_LENGTH_MM[0] <= length <= SHOE_LENGTH_MM[1] and SHOE_RATIO[0] <= width / length <= SHOE_RATIO[1]


def _oriented(poly):
    """Outline -> (outline with its long axis along x, heel (narrower end) at x = 0, heel middle at y = 0,
    {heel and ball widths})."""
    import shapely
    import shapely.affinity

    P = np.asarray(poly.exterior.segmentize(1.0).coords)[:-1]
    mu = P.mean(axis=0)
    _, _, Vt = np.linalg.svd(P - mu, full_matrices=False)
    ax = Vt[0] / np.linalg.norm(Vt[0])
    c, s = float(ax[0]), float(ax[1])  # turn ax onto +x, about mu (GEOS's own transform: a ring stays closed)
    out = shapely.affinity.affine_transform(poly, [c, s, -s, c, -(c * mu[0] + s * mu[1]), s * mu[0] - c * mu[1]])
    x0, y0, x1, y1 = out.bounds
    length = x1 - x0

    def width_at(a, b):
        part = out.intersection(shapely.box(a, y0 - 1, b, y1 + 1))
        return 0.0 if part.is_empty else part.bounds[3] - part.bounds[1]

    back, front = width_at(x0, x0 + 0.2 * length), width_at(x1 - 0.2 * length, x1)
    if front < back:  # the heel is the narrower end: turn it round
        out = shapely.affinity.affine_transform(out, [-1.0, 0.0, 0.0, -1.0, 0.0, 0.0])
        x0, y0, x1, y1 = out.bounds
    heel = out.intersection(shapely.box(x0, y0 - 1, x0 + 0.2 * length, y1 + 1))
    hy = (heel.bounds[1] + heel.bounds[3]) / 2
    out = shapely.affinity.translate(out, -x0, -hy)
    widths = dict(back_fifth_mm=round(min(back, front), 1), front_fifth_mm=round(max(back, front), 1))
    return out, widths


def outline_from_scan(mesh, up: str = "y"):
    """A scan of a shoe's insole lying flat (as the app hands it over) -> (outline, info). See the module
    docstring. The outline is in mm: heel at x = 0, toes along +x, the heel's middle at y = 0."""
    import trimesh

    from .foot_prep import _pieces, _up_turn

    mm, units, factor = imported.to_millimetres(mesh)
    m = mm.copy()
    m.apply_transform(_up_turn(up))
    info = dict(units_detected=units, up_axis=up)

    level = m.face_normals[:, 2] > np.cos(np.radians(TABLE_LEVEL_DEG))
    tops = []
    if level.any():
        flat = m.copy()
        flat.update_faces(level)
        flat.remove_unreferenced_vertices()
        for mask, area in _pieces(flat):
            if area < TABLE_MIN_AREA_MM2:
                break
            z = flat.triangles_center[mask, 2]
            tops.append(float(np.average(z, weights=flat.area_faces[mask])))
    candidates = sorted(tops)[:TABLE_TRIES]

    def above(z_cut):
        keep = m.triangles_center[:, 2] > z_cut
        if not keep.any():
            return None
        part = m.copy()
        part.update_faces(keep)
        part.remove_unreferenced_vertices()
        pieces = _pieces(part)
        if not pieces:
            return None
        part.update_faces(pieces[0][0])
        part.remove_unreferenced_vertices()
        return part

    chosen, table = None, None
    for z in candidates:
        part = above(z + TABLE_CUT_MM)
        if part is not None and len(part.vertices) >= 20:
            v, f = trimesh.remesh.subdivide_to_size(part.vertices, part.faces, 2.0)
            poly = _outline(np.asarray(v)[:, :2])
            if _plausible(poly):
                chosen, table = poly, z
                break
    if chosen is None:  # no table in the model: the insole on its own
        v, f = trimesh.remesh.subdivide_to_size(m.vertices, m.faces, 2.0)
        chosen = _outline(np.asarray(v)[:, :2])
        if not _plausible(chosen):
            x0, y0, x1, y1 = _oriented(chosen)[0].bounds
            raise ShoeError(f"this doesn't look like a shoe's insole lying flat ({x1 - x0:.0f} x {y1 - y0:.0f} mm "
                            f"seen from above; expected {SHOE_LENGTH_MM[0]:.0f}-{SHOE_LENGTH_MM[1]:.0f} mm long, "
                            f"a quarter to a half as wide)")
    out, widths = _oriented(chosen)
    x0, y0, x1, y1 = out.bounds
    info.update(table_found=table is not None, length_mm=round(x1 - x0, 1), width_mm=round(y1 - y0, 1),
                end_widths_mm=widths)
    return out, info


def handedness(outline) -> tuple[str | None, float]:
    """Which shoe an insole's outline (heel at the origin, toes along +x, as seen from above) is from.
    -> ("right" / "left" / None, how far the toe end is to the left (+) of the heel-ball line, mm)."""
    import shapely

    x0, y0, x1, y1 = outline.bounds
    length = x1 - x0

    def middle(a, b):
        part = outline.intersection(shapely.box(x0 + a * length, y0 - 1, x0 + b * length, y1 + 1))
        return np.array(part.centroid.coords[0])

    heel, ball = middle(0.0, 0.2), middle(0.6, 0.75)
    d = (ball - heel) / np.linalg.norm(ball - heel)
    P = np.asarray(outline.exterior.segmentize(1.0).coords)[:-1]
    along = (P - heel) @ d
    tip = P[along >= along.max() - 3.0].mean(axis=0)  # the toe end: the outline's last 3 mm along that line
    v = tip - heel
    left = float(d[0] * v[1] - d[1] * v[0])  # 2-D cross product: + when the tip is to the left of the line
    hand = "right" if left > HAND_MIN_MM else "left" if left < -HAND_MIN_MM else None
    return hand, round(left, 1)


def as_param(outline) -> tuple:
    """The outline as InsoleParams.shoe_outline takes it (and insole.json records it): mm, to 0.5 mm."""
    ring = np.asarray(outline.simplify(0.5).exterior.coords)[:-1]
    return tuple((round(float(x), 2), round(float(y), 2)) for x, y in ring)


def _place(shoe, mirrored: bool, turn_deg: float, x: float, y: float):
    import shapely.affinity

    a = np.radians(turn_deg)
    c, s = np.cos(a), np.sin(a)
    my = -1.0 if mirrored else 1.0
    # mirror (y -> -y), turn about the heel (the origin), then move the heel to (x, y)
    return shapely.affinity.affine_transform(shoe, [c, -s * my, s, c * my, x, y])


def fit_to_foot(shoe, sil, foot: str, heel_gap_mm: float):
    """Place the shoe's outline (heel at the origin, see outline_from_scan) round the foot's outline within
    FIT_HEIGHT_MM of the floor, ``sil`` (insole frame). -> (placed outline, fit report). See the module docstring."""
    import shapely

    hand, toe_left = handedness(shoe)
    mirrored = hand is not None and hand != foot
    x0, y0, x1, y1 = sil.bounds
    length = x1 - x0
    heel = sil.intersection(shapely.box(x0 - 1, y0 - 1, x0 + 0.2 * length, y1 + 1))
    hx, hy = x0 - heel_gap_mm, (heel.bounds[1] + heel.bounds[3]) / 2
    band = sil.buffer(FIT_BAND_MM)

    def score(mir, turn, dy):
        placed = _place(shoe, mir, turn, hx, hy + dy)
        return (round(sil.difference(placed).area, 1), round(band.difference(placed).area, 1),
                abs(turn) / 2 + abs(dy), mir), placed

    best = None
    mir = mirrored
    for turn in np.arange(-FIT_TURN_DEG, FIT_TURN_DEG + 1e-9, 1.0):
        for dy in np.arange(-FIT_SLIDE_MM, FIT_SLIDE_MM + 1e-9, 1.0):
            s, _ = score(mir, turn, dy)
            if best is None or s < best[0]:
                best = (s, mir, turn, dy)
    _, mir, t0, d0 = best
    for turn in np.arange(t0 - 1.0, t0 + 1.0 + 1e-9, 0.25):  # then finer, round the best
        for dy in np.arange(d0 - 1.0, d0 + 1.0 + 1e-9, 0.25):
            if abs(turn) <= FIT_TURN_DEG and abs(dy) <= FIT_SLIDE_MM:
                s, _ = score(mir, turn, dy)
                if s < best[0]:
                    best = (s, mir, turn, dy)
    _, mir, turn, dy = best
    placed = _place(shoe, mir, turn, hx, hy + dy)

    # where the foot hangs over the shoe's edge, and by how much
    edge = np.asarray(sil.exterior.segmentize(1.0).coords)[:-1]
    out = ~shapely.contains_xy(placed, edge[:, 0], edge[:, 1])
    over = np.asarray(shapely.distance(placed.exterior, shapely.points(edge[out]))) if out.any() else np.zeros(0)
    overhang = dict(max_mm=0.0, where=None)
    if len(over) and over.max() > 0:
        i = int(np.argmax(over))
        px, py = edge[out][i]
        share = (px - x0) / length
        part = "heel" if share < 0.3 else "arch" if share < 0.6 else "ball of the foot" if share < 0.85 else "toes"
        inner = (py - hy) * (1.0 if foot == "right" else -1.0) > 0  # the foot's inner side is +y for a right foot
        overhang = dict(max_mm=round(float(over.max()), 1),
                        where=part if part in ("heel", "toes") else f"{part}, {'inner' if inner else 'outer'} side",
                        area_mm2=round(float(sil.difference(placed).area), 0))
    px0, _, px1, _ = placed.bounds
    report = dict(shoe=hand, toe_end_left_mm=toe_left, mirrored=bool(mir), turned_deg=round(float(turn), 2), slid_mm=round(float(dy), 2),
                  shoe_length_mm=round(px1 - px0, 1), foot_length_mm=round(length, 1),
                  room_past_toes_mm=round(px1 - x1, 1), overhang=overhang)
    return placed, report


def fit_warnings(fit: dict) -> list[str]:
    w = []
    o = fit["overhang"]
    if o["max_mm"] > OVERHANG_WARN_MM:
        w.append(f"the foot is wider than the shoe's insole at the {o['where']}, by up to {o['max_mm']} mm: the "
                 f"insole stops at the shoe's edge there. If the shoe feels tight there too, it's the shoe's size "
                 f"or width, not the insole")
    if fit["room_past_toes_mm"] < 0:
        w.append(f"the shoe's insole is {-fit['room_past_toes_mm']} mm shorter than the foot: is this the right "
                 f"shoe, and the whole insole in the scan?")
    if fit["mirrored"]:
        w.append(f"the shoe's insole is a {fit['shoe']} shoe's as scanned (scanned upside down, or from the other "
                 f"shoe), so it was mirrored for this foot. If it was the right shoe, top side up, check the scan")
    if fit["shoe"] is None:
        w.append("couldn't tell which shoe the insole is from (its toe end is nearly straight ahead of the heel), "
                 "so it was used as scanned: check it was top side up, from this foot's shoe")
    return w
