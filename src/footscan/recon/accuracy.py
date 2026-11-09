"""How far is the scan from the truth? Scan of the calibration object vs. its model.

Two kinds of answer, because they catch different mistakes:

**Surface deviation.** Put the scan and the model on top of each other and
measure, all over the scanned surface, the distance to the model. Reported
as the median (the typical error), the 95th percentile (how bad the worst
twentieth gets) and the maximum, plus the *signed* mean: if the scan is
consistently a little too big or too small, the signed mean shows it while
the median of absolute distances wouldn't. Also the reverse direction,
**completeness**: what fraction of the model's visible surface has scan
within 1 mm and 2 mm of it (a scan can be very accurate where it exists and
still be missing half the shape).

**Caliper dimensions.** The same lengths and heights you measure with
calipers on the printed object, measured on the scan: wall-to-wall length
and width, heights of flat tops above the table, the dome's radius. These
don't depend on how the two shapes were lined up.

Lining up (registration)
------------------------
The scan is already in millimetres (from the mat) and the object stands on
the mat, but we don't know exactly where on it or which way round. So:

1. *Coarse:* the object's long axis is the direction in which the scanned
   points spread most (principal component analysis in the floor plane).
   That gives the turn up to a half-turn; both are tried.
2. *Fine: ICP (iterative closest point), point-to-plane.* Pair each scan
   point with the nearest point on the model; find the small rotation and
   shift that minimise the distances *along the model's surface normals*
   (sliding along a flat face costs nothing, as it should); apply; repeat
   until nothing moves. Pairs farther apart than a threshold are ignored so
   a bit of stray surface can't pull the alignment.

ICP is only allowed to rotate and shift, **never to scale**. Scale comes
from the mat and is one of the things being tested; letting the alignment
rescale the scan would hide exactly the error we're looking for.

One honest caveat, stated in the report: ICP chooses the position that makes
the distances smallest, so the surface statistics are slightly optimistic
compared with knowing the true position. The caliper dimensions don't have
this problem.
"""

from __future__ import annotations

import numpy as np

from . import calib
from .geometry import SurfaceIndex

REJECT_MM = 6.0
ICP_MIN_REJECT_MM = 2.0
ICP_ITERS = 60
ICP_POINTS = 20_000  # alignment uses a random subset; the statistics use every sample
WALL_WINDOW = 0.12   # the wall-to-wall search reaches this share of the dimension either side of each wall
SCALE_WARN_PCT = 1.0  # length and width both off by more than this, the same way: the scan's scale is off


# --------------------------------------------------------------------------
# registration
# --------------------------------------------------------------------------
def _reference_samples(ref, n: int = 400_000, seed: int = 0):
    """Dense points (and normals) on the model's surfaces the camera can see (not the bottom)."""
    import trimesh

    pts, fi = trimesh.sample.sample_surface(ref, n, seed=np.random.default_rng(seed))
    nrm = ref.face_normals[fi]
    visible = nrm[:, 2] > -0.9
    return pts[visible], nrm[visible]


def _rot(axis_angle: np.ndarray) -> np.ndarray:
    import cv2

    return cv2.Rodrigues(np.asarray(axis_angle, float).reshape(3, 1))[0]


def icp(Q: np.ndarray, tree, ref_pts: np.ndarray, ref_nrm: np.ndarray, T0: np.ndarray, reject: float = REJECT_MM):
    """Point-to-plane ICP; Q are scan points, T0 maps them into the model frame. Returns (T, trimmed RMS)."""
    T = T0.copy()
    rms = np.inf
    thr = reject
    for it in range(ICP_ITERS):
        X = Q @ T[:3, :3].T + T[:3, 3]
        # Searching only within the rejection distance keeps the k-d tree
        # fast: far points come back as "no neighbour" (infinite distance).
        d, idx = tree.query(X, distance_upper_bound=thr, workers=-1)
        use = np.isfinite(d)
        if it >= 5 and use.sum() > 100:
            # Tighten toward 3x the typical distance, but never below 2 mm:
            # a scan with a scale error can't fit everywhere at once, and a
            # threshold that keeps shrinking lets ICP lock onto one end of
            # it, which *hides* the error it should reveal.
            thr = min(reject, max(ICP_MIN_REJECT_MM, 3 * float(np.median(d[use]))))
            use &= d < thr
        if use.sum() < 100:
            break
        x, p, n = X[use], ref_pts[idx[use]], ref_nrm[idx[use]]
        # Linearised: a small rotation w and shift v move x to x + w x x + v.
        # Residual along the normal: ((x + w x x + v) - p) . n
        #   = (x x n) . w + n . v + (x - p) . n
        A = np.c_[np.cross(x, n), n]
        b = -np.einsum("ij,ij->i", x - p, n)
        sol, *_ = np.linalg.lstsq(A, b, rcond=None)
        dT = np.eye(4)
        dT[:3, :3] = _rot(sol[:3])
        dT[:3, 3] = sol[3:]
        T = dT @ T
        rms = float(np.sqrt(np.mean(np.einsum("ij,ij->i", x - p, n) ** 2)))
        if np.linalg.norm(sol[:3]) < 1e-7 and np.linalg.norm(sol[3:]) < 1e-5:
            break
    X = Q @ T[:3, :3].T + T[:3, 3]
    d, _ = tree.query(X, distance_upper_bound=ICP_MIN_REJECT_MM, workers=-1)
    T_inliers = float(np.mean(np.isfinite(d)))  # share of the scan within 2 mm of the model once aligned
    return T, rms, T_inliers


def register(scan_pts: np.ndarray, ref) -> tuple[np.ndarray, dict]:
    """Rigid transform (4x4) taking scan (mat frame) points into the model frame."""
    from scipy.spatial import cKDTree

    ref_pts, ref_nrm = _reference_samples(ref)
    tree = cKDTree(ref_pts)
    Q = scan_pts[scan_pts[:, 2] > 2.0]
    if len(Q) > ICP_POINTS:
        Q = Q[np.random.default_rng(0).choice(len(Q), ICP_POINTS, replace=False)]
    xy = Q[:, :2] - Q[:, :2].mean(0)
    _, vec = np.linalg.eigh(xy.T @ xy)
    long_axis = vec[:, 1]
    theta = np.arctan2(long_axis[1], long_axis[0])
    best = None
    for yaw in (theta, theta + np.pi):
        c, s = np.cos(-yaw), np.sin(-yaw)
        Rz = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1.0]])
        r = Q @ Rz.T
        mid = (r.min(0) + r.max(0)) / 2
        T0 = np.eye(4)
        T0[:3, :3] = Rz
        T0[:3, 3] = [calib.LENGTH / 2 - mid[0], calib.WIDTH / 2 - mid[1], 0.0]
        T, rms, inl = icp(Q, tree, ref_pts, ref_nrm, T0)
        # The right way round matches more of the surface; a wrong turn can
        # still fit a part tightly, so compare coverage first, then tightness.
        if best is None or (inl, -rms) > (best[2], -best[1]):
            best = (T, rms, inl)
    T, rms, inl = best
    tilt = np.degrees(np.arccos(np.clip(T[2, 2], -1, 1)))
    return T, dict(icp_rms_mm=round(rms, 4), tilt_from_floor_deg=round(float(tilt), 3),
                   scan_within_2mm=round(inl, 4))


# --------------------------------------------------------------------------
# measurements on the scan
# --------------------------------------------------------------------------
def fit_plane(P: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Least-squares plane: centroid and the direction of least spread (normal, z >= 0)."""
    c = P.mean(0)
    _, _, Vt = np.linalg.svd(P - c, full_matrices=False)
    n = Vt[2]
    return c, n if n[2] >= 0 else -n


def fit_sphere(P: np.ndarray) -> tuple[np.ndarray, float]:
    """Algebraic sphere fit: |p|^2 = 2 c.p + (r^2 - |c|^2) is linear in c and the constant."""
    A = np.c_[2 * P, np.ones(len(P))]
    b = (P**2).sum(1)
    sol, *_ = np.linalg.lstsq(A, b, rcond=None)
    c = sol[:3]
    return c, float(np.sqrt(sol[3] + c @ c))


def _robust(P: np.ndarray, fn, keep: float = 2.5, rounds: int = 3):
    """Refit after dropping points far from the fit (robust to the odd stray point)."""
    for _ in range(rounds):
        res, out = fn(P)
        mad = 1.4826 * np.median(np.abs(res - np.median(res))) + 1e-9
        ok = np.abs(res - np.median(res)) < keep * mad
        if ok.all() or ok.sum() < 20:
            break
        P = P[ok]
        _, out = fn(P)  # the fit and the count always describe the same points
    return out, len(P)


def measure_dimensions(scan_ref: np.ndarray, floor_plane: tuple[np.ndarray, np.ndarray],
                       floor_ref: np.ndarray | None = None) -> dict:
    """Caliper-style dimensions measured on scan points already in the model frame.

    Heights are measured from ``floor_plane`` (point, unit normal): the
    paper's plane, which is z = 0 of the mat frame, carried into the model
    frame by the alignment. Not from the model's own z = 0: the alignment is
    free to slide the scan up or down a little, which would hide a scale
    error in exactly the numbers meant to reveal it.
    """
    out = {}
    floor_c, floor_n = floor_plane

    # Diagnostic only: where the dense points on the paper around the object
    # lie relative to that plane.
    if floor_ref is not None and len(floor_ref) > 50:
        x, y = floor_ref[:, 0], floor_ref[:, 1]
        ring = ((x > -30) & (x < calib.LENGTH + 30) & (y > -30) & (y < calib.WIDTH + 30)
                & ~((x > -4) & (x < calib.LENGTH + 4) & (y > -4) & (y < calib.WIDTH + 4)))
        if ring.sum() > 50:
            h = (floor_ref[ring] - floor_c) @ floor_n
            out["dense_floor_offset_mm"] = dict(value=round(float(np.median(h)), 3), n=int(ring.sum()))

    def height(P):
        return (P - floor_c) @ floor_n

    for name, reg in calib.regions().items():
        sel = reg["test"](scan_ref)
        if reg["kind"] == "plane_z":
            sel &= np.abs(scan_ref[:, 2] - reg["nominal"]) < 3.0
            if sel.sum() < 30:
                continue
            h = height(scan_ref[sel])
            out[{"base": "base", "terrace_high": "terrace_high", "terrace_low": "terrace_low"}[name]] = dict(
                value=round(float(np.median(h)), 3), spread_mm=round(float(np.std(h)), 3), n=int(sel.sum()))
        elif reg["kind"] == "sphere":
            if sel.sum() < 50:
                continue

            def sphere_res(P):
                c, r = fit_sphere(P)
                return np.linalg.norm(P - c, axis=1) - r, (c, r)
            (c, r), n_used = _robust(scan_ref[sel], sphere_res)
            apex = float(height(c[None])[0] + r)
            out["dome_radius"] = dict(value=round(r, 3), n=n_used)
            out["dome_apex"] = dict(value=round(apex, 3), n=n_used)

    # Wall-to-wall: points on the base's side walls (between 2 and 8 mm up).
    band = (height(scan_ref) > 2) & (height(scan_ref) < 8)
    for key, axis, lo_pos, hi_pos, other in (
        ("length", 0, 0.0, calib.LENGTH, (1, 6, calib.WIDTH - 6)),
        ("width", 1, 0.0, calib.WIDTH, (0, 6, calib.LENGTH - 6)),
    ):
        o_axis, o_lo, o_hi = other
        span_ok = band & (scan_ref[:, o_axis] > o_lo) & (scan_ref[:, o_axis] < o_hi)
        # Wide windows round where each wall should be: a scan several percent too big or too small still has its
        # walls inside them, and must be measured, not dropped. The rigid alignment can't scale the scan, so it
        # may line one end up and leave the other wall a whole scale error away: 5% of the length is 7.5 mm (a
        # SYNTHETIC scan 5% small lost its length at +-6 mm). In the 2-8 mm band, with the corners cut off by
        # span_ok, the end walls are the only surface there, so a wide window can't catch anything else.
        win = max(6.0, WALL_WINDOW * (hi_pos - lo_pos))
        lo = span_ok & (np.abs(scan_ref[:, axis] - lo_pos) < win)
        hi = span_ok & (np.abs(scan_ref[:, axis] - hi_pos) < win)
        if lo.sum() > 20 and hi.sum() > 20:
            out[key] = dict(value=round(float(np.median(scan_ref[hi, axis]) - np.median(scan_ref[lo, axis])), 3),
                            n=int(lo.sum() + hi.sum()))
    return out


# --------------------------------------------------------------------------
# the study
# --------------------------------------------------------------------------
def _stats(d: np.ndarray) -> dict:
    a = np.abs(d)
    return dict(
        median_mm=round(float(np.median(a)), 4),
        mean_mm=round(float(a.mean()), 4),
        rms_mm=round(float(np.sqrt(np.mean(d**2))), 4),
        p90_mm=round(float(np.percentile(a, 90)), 4),
        p95_mm=round(float(np.percentile(a, 95)), 4),
        max_mm=round(float(a.max()), 4),
        signed_mean_mm=round(float(d.mean()), 4),
    )




def scale_estimate(table: list[dict]) -> dict | None:
    """How far the scan's size is off, from its wall-to-wall length and width against the reference (calipers if
    given, else the model): each as a percentage, and their mean. A scan that's scaled as a whole reads off by the
    same share both ways; an edge that's missing or swollen moves one, not the other. None without both."""
    rows = {r["key"]: r for r in table}
    pct = {}
    for k in ("length", "width"):
        r = rows.get(k)
        if r is None or r.get("scan_mm") is None:
            return None
        ref = r["caliper_mm"] if r.get("caliper_mm") is not None else r["model_mm"]  # as evaluate() picks it
        pct[k] = 100.0 * (r["scan_mm"] / ref - 1.0)
    return dict(length_pct=round(pct["length"], 2), width_pct=round(pct["width"], 2),
                mean_pct=round((pct["length"] + pct["width"]) / 2, 2),
                same_way=bool(np.sign(pct["length"]) == np.sign(pct["width"])))


def evaluate(scan_mesh, floor_pts: np.ndarray | None = None, calipers: dict | None = None,
             n_samples: int = 100_000) -> dict:
    import trimesh

    ref = calib.build()
    rng = np.random.default_rng(0)
    samples, _ = trimesh.sample.sample_surface(scan_mesh, n_samples, seed=rng)
    T, reg = register(samples, ref)
    S = samples @ T[:3, :3].T + T[:3, 3]
    floor_ref = None if floor_pts is None or not len(floor_pts) else floor_pts @ T[:3, :3].T + T[:3, 3]

    # Accuracy: every scanned bit of object surface vs. the model. Points
    # within half a millimetre of the table are the seam with the floor,
    # which belongs to neither surface; they are left out.
    on_object = S[:, 2] > 0.5
    d = SurfaceIndex(ref).closest(S[on_object])[2]

    # Completeness: the model's visible surface vs. the scan.
    scan_in_ref = scan_mesh.copy()
    scan_in_ref.apply_transform(T)
    ref_pts, ref_fi = trimesh.sample.sample_surface(ref, n_samples, seed=np.random.default_rng(1))
    visible = ref.face_normals[ref_fi][:, 2] > -0.9
    back = SurfaceIndex(scan_in_ref).closest(ref_pts[visible])[1]

    # The paper (z = 0 in the scan's mat frame), carried into the model frame.
    floor_plane = (T[:3, 3].copy(), T[:3, :3] @ np.array([0.0, 0.0, 1.0]))
    dims = measure_dimensions(S, floor_plane, floor_ref)
    table = []
    for chk in calib.CALIPER_CHECKS:
        row = dict(key=chk.key, label=chk.label, model_mm=chk.nominal_mm,
                   caliper_mm=None if not calipers else calipers.get(chk.key),
                   scan_mm=dims.get(chk.key, {}).get("value"))
        ref_val = row["caliper_mm"] if row["caliper_mm"] is not None else row["model_mm"]
        row["scan_minus_reference_mm"] = None if row["scan_mm"] is None else round(row["scan_mm"] - ref_val, 3)
        row["reference"] = "calipers" if row["caliper_mm"] is not None else "model"
        table.append(row)
    if "dome_radius" in dims:
        table.append(dict(key="dome_radius", label="Dome radius (sphere fit)", model_mm=calib.DOME_RADIUS,
                          caliper_mm=None, scan_mm=dims["dome_radius"]["value"],
                          scan_minus_reference_mm=round(dims["dome_radius"]["value"] - calib.DOME_RADIUS, 3),
                          reference="model"))

    scale = scale_estimate(table)
    warnings = []
    if scale is not None and abs(scale["mean_pct"]) > SCALE_WARN_PCT:
        how = ("both ways, so the whole scan is scaled, not just an edge missing. Foot scans made the same way are "
               "probably off by about as much" if scale["same_way"] and min(abs(scale["length_pct"]),
                                                                            abs(scale["width_pct"])) > SCALE_WARN_PCT / 2
               else "but not the same both ways: check the scan for a missing or swollen edge before reading it as "
                    "the scan's scale")
        warnings.append(f"the scan reads {abs(scale['mean_pct']):.1f}% too {'small' if scale['mean_pct'] < 0 else 'big'} "
                        f"(length {scale['length_pct']:+.1f}%, width {scale['width_pct']:+.1f}%), {how}. The surface "
                        f"statistics include this error")
    missing = [row["label"] for row in table if row["scan_mm"] is None]
    if missing:
        warnings.append(f"couldn't measure on the scan: {', '.join(missing)} (that part of the surface is missing "
                        "or far from where it should be)")
    if reg["scan_within_2mm"] < 0.9:
        warnings.append(f"only {100 * reg['scan_within_2mm']:.0f}% of the scan lies within 2 mm of the object once "
                        "lined up: the scan is badly off (wrong scale?) or includes something else")
    for row in table:
        if row.get("caliper_mm") is not None and abs(row["caliper_mm"] - row["model_mm"]) > calib.PRINT_TOLERANCE_MM:
            warnings.append(f"{row['label']}: the print measures {row['caliper_mm']} mm but the model says "
                            f"{row['model_mm']} mm. The print differs from the model by more than "
                            f"{calib.PRINT_TOLERANCE_MM} mm, so surface deviations include print error.")
    return dict(
        reference="footscan calibration object (model)",
        registration=reg,
        registration_note="ICP aligns rigidly (no scaling); surface statistics are slightly optimistic because "
                          "the alignment minimises them. Caliper dimensions are alignment-independent.",
        surface_deviation=_stats(d),
        surface_samples=int(on_object.sum()),
        completeness=dict(
            within_1mm=round(float(np.mean(back <= 1.0)), 4),
            within_2mm=round(float(np.mean(back <= 2.0)), 4),
        ),
        dimensions=table,
        scale=scale,
        warnings=warnings,
        dense_floor_offset_mm=dims.get("dense_floor_offset_mm", {}).get("value"),
        transform_scan_to_model=T.tolist(),
    )
