"""How much two scans of the same foot agree: the sole the insole is made from, scan against scan.

Scan the same foot twice (or in two poses) and compare. If a pose lets the
foot hold still, its two scans come out nearly the same; if the foot moves,
they don't. This is the "repeat scans within ... mm" measure foot-scanner
makers publish, so the numbers line up with theirs. It needs nothing but the
two scans: no reference object, no calipers.

How: each scan is prepared exactly as Make insole prepares it (levelled, the
floor through the heel and the ball of the foot, toes forward) and read the
same way, as a height map of the sole above its floor. The two height maps
are then lined up *flat on the table only* (slid and turned, by fitting their
outlines to each other), because where each scan happened to sit on the mat
is arbitrary; their heights and tilts are not, so those are compared as they
are. Then, at every point of the sole both scans saw (more than
``EDGE_MM`` in from the edge):

- typical / p95: the median and 95th percentile of the height difference, mm
- bias: the mean difference (b minus a), mm
- arch: the difference between the two arch tops, after the insole's own smoothing, mm
- outline: length and width of each, and the mean gap between the outlines once lined up
  (over the closest 70% of the outline: the part both scans have), mm
"""

from __future__ import annotations

import numpy as np

GRID_MM = 1.0
EDGE_MM = 6.0
FIT_KEEP = 0.7  # share of the outline the fit uses each round (the closest)


def sole_map(placed, foot: str):
    """A prepared scan (mat frame) -> (outline polygon, xs, ys, heights, seen mask), as the insole reads it."""
    import shapely

    from .. import insole
    from . import plantar

    fm = insole.output_frame(plantar.run(placed, foot)["foot_mesh"], foot)
    sil = insole.silhouette(fm)
    x0, y0, x1, y1 = sil.bounds
    xs, ys = np.arange(x0 - 2, x1 + 2, GRID_MM), np.arange(y0 - 2, y1 + 2, GRID_MM)
    X, Y = np.meshgrid(xs, ys)
    inside = shapely.contains_xy(sil, X, Y)
    H, S = insole.sole_heights(fm, xs, ys, inside)
    return sil, xs, ys, H, inside & (S == 1)


def _fit_outlines(a, b, iterations: int = 40, keep: float = FIT_KEEP):
    """2-D rigid fit (turn + slide) taking outline b onto outline a. -> (2x2 rotation, shift, gap).

    Trimmed: each round fits only the closest ``keep`` share of b's outline points, so a stretch
    one scan has and the other doesn't (toes missed, a heel cut short) can't drag the fit off.
    Both scans come prepared heel at the origin, toes along +x, so the fit starts close."""
    from scipy.spatial import cKDTree

    A = np.asarray(a.exterior.segmentize(1.0).coords)[:-1]
    B = np.asarray(b.exterior.segmentize(1.0).coords)[:-1]
    tree = cKDTree(A)
    R, t = np.eye(2), np.zeros(2)
    for _ in range(iterations):
        moved = B @ R.T + t
        dist, i = tree.query(moved)
        near = dist <= np.quantile(dist, keep)
        P, Q = moved[near], A[i[near]]
        cp, cq = P.mean(0), Q.mean(0)
        U, _, Vt = np.linalg.svd((P - cp).T @ (Q - cq))
        dR = (U @ Vt).T
        if np.linalg.det(dR) < 0:  # a turn, never a mirror
            Vt[-1] *= -1
            dR = (U @ Vt).T
        R, t = dR @ R, dR @ t + (cq - dR @ cp)
    dist = tree.query(B @ R.T + t)[0]
    gap = float(np.mean(dist[dist <= np.quantile(dist, keep)]))
    return R, t, gap


def compare_prepared(placed_a, placed_b, foot: str) -> dict:
    """Two prepared scans of the same foot (mat frame) -> how they differ (see the module docstring)."""
    import shapely
    from scipy import ndimage
    from scipy.interpolate import RegularGridInterpolator

    from .. import insole

    sil_a, xa, ya, Ha, seen_a = sole_map(placed_a, foot)
    sil_b, xb, yb, Hb, seen_b = sole_map(placed_b, foot)
    R, t, gap = _fit_outlines(sil_a, sil_b)

    # every point of a, looked up in b: a point p of a sits at R^-1 (p - t) in b's own frame
    Xa, Ya = np.meshgrid(xa, ya)
    P = np.c_[Xa.ravel(), Ya.ravel()]
    Pb = (P - t) @ R  # R is orthonormal: R^-1 = R^T, and (row vectors) (p - t) R^T^-1 = (p - t) R
    hb = RegularGridInterpolator((yb, xb), np.where(seen_b, Hb, np.nan), bounds_error=False, fill_value=np.nan)
    Hb_on_a = hb(np.c_[Pb[:, 1], Pb[:, 0]]).reshape(Xa.shape)

    # more than EDGE_MM inside both soles (b's edge tested where each point of a falls in b)
    in_b = shapely.contains_xy(sil_b.buffer(-EDGE_MM), Pb[:, 0], Pb[:, 1]).reshape(Xa.shape)
    interior = seen_a & shapely.contains_xy(sil_a.buffer(-EDGE_MM), Xa, Ya) & in_b & np.isfinite(Hb_on_a)
    if interior.sum() < 200:
        raise ValueError("the two scans hardly overlap: are they the same foot, in the same kind of scan?")
    d = Hb_on_a[interior] - Ha[interior]

    def arch_top(H, seen):
        raw = np.where(seen, H, 0.0)
        smooth = ndimage.gaussian_filter(raw, insole.SMOOTH_SIGMA_MM / GRID_MM)
        return float(np.max(np.minimum(smooth, raw + insole.SMOOTH_MAY_RAISE_MM)))

    def size(poly):
        x0, y0, x1, y1 = poly.bounds
        return round(x1 - x0, 1), round(y1 - y0, 1)

    return dict(
        points=int(interior.sum()),
        typical_mm=round(float(np.median(np.abs(d))), 2),
        p95_mm=round(float(np.percentile(np.abs(d), 95)), 2),
        bias_mm=round(float(np.mean(d)), 2),
        arch_top_mm=dict(a=round(arch_top(Ha, seen_a), 2), b=round(arch_top(Hb, seen_b), 2)),
        arch_difference_mm=round(arch_top(Hb, seen_b) - arch_top(Ha, seen_a), 2),
        outline=dict(a=dict(zip(("length_mm", "width_mm"), size(sil_a))),
                     b=dict(zip(("length_mm", "width_mm"), size(sil_b))),
                     mean_gap_mm=round(gap, 2)),
        lined_up=dict(turned_deg=round(float(np.degrees(np.arctan2(R[1, 0], R[0, 0]))), 2),
                      slid_mm=[round(float(v), 1) for v in t]),
    )


def compare_scans(mesh_a, mesh_b, foot: str, kind_a: str = "sole_up", kind_b: str | None = None, up: str = "y") -> dict:
    """Two scans as handed over (any kind PREPARE knows) -> how they differ."""
    from .foot_prep import PREPARE, _settle_floor  # noqa: F401  (the same preparation as Make insole)

    kind_b = kind_b or kind_a
    prep = lambda mesh, kind: PREPARE[kind](mesh, up, foot=foot)[0]
    out = compare_prepared(prep(mesh_a, kind_a), prep(mesh_b, kind_b), foot)
    out["kinds"] = [kind_a, kind_b]
    return out


def verdict(r: dict) -> str:
    """One plain sentence for the studio."""
    return (f"The two scans agree within {r['typical_mm']} mm over a typical point of the sole and "
            f"{r['p95_mm']} mm over 95% of it; their arch tops differ by {abs(r['arch_difference_mm'])} mm "
            f"and their outlines by {r['outline']['mean_gap_mm']} mm on average.")
