"""Benchmark: how close does the sole the insole is built from come to the true sole?

    .venv/bin/python scripts/benchmark_prep.py                 # all cases -> reports/benchmark-prep.md
    .venv/bin/python scripts/benchmark_prep.py --quick         # a few cases, for a quick check

SYNTHETIC feet only: every number here comes from computer-made scans
whose true shape is known exactly, so the error at every point can be
measured. It says how much the processing itself adds (levelling,
resting, trimming, smoothing, reading the sole's height) under the kinds
of damage a phone scan has. It does NOT say how accurate a real phone scan
of a real foot is: that needs the calibration object and real feet.

The foot (tests/synth.py curved_foot): 250 x 100 mm, heel pad and ball of
the foot flat on the floor, a smooth arch rising to 14 mm on the inner
side, rounded edges. Each case builds the scan the way the iPhone app
would hand it over (metres, Y up, turned, maybe tilted, with damage), runs
the same preparation as Make insole, then maps every point of the sole the
generator read back onto the true foot (the preparation records the exact
turn and move it made) and compares heights there.

Measures, over the sole away from its rounded edge (more than 8 mm in):
Heights are above each floor: the one the preparation found, and the true
one. So a floor that is off shows up in every height, as it would in the
insole.
- bias: mean (read - true) height, mm. Positive = reads high.
- rms: root-mean-square height error, mm.
- p95: 95th percentile of the absolute error, mm.
- arch: the highest point of the surface the insole is shaped to (read
  heights after the generator's own smoothing) minus the highest true
  point, mm.
- tilt: angle between the floor found and the true floor, degrees; and the
  wedge the heights carry (a plane fitted to the height errors: its slope
  heel-to-toe and side-to-side), which is what the insole would carry.
- length: the longest dimension of the outline the insole is cut to (the
  foot seen from above, below 30 mm) minus the true one, mm.
- side: the arch came out on the inner side.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import synth  # noqa: E402
from footscan import insole  # noqa: E402
from footscan.recon import foot_prep, imported, plantar  # noqa: E402

EDGE_MM = 8.0
GRID = 1.0


# ---------------------------------------------------------------------------
# building scans
# ---------------------------------------------------------------------------
def _rot(deg, axis, point=(0, 0, 0)):
    import trimesh

    return trimesh.transformations.rotation_matrix(np.radians(deg), axis, point)


def to_object_capture(yaw=63.0, gravity_tilt=0.0):
    """mm, Z up -> what the app hands over: turned, maybe not quite level, Y up, metres."""
    T = _rot(yaw, [0, 0, 1])
    T[:3, 3] = [40, -25, 7]
    if gravity_tilt:
        T = _rot(gravity_tilt, [1, 0.3, 0]) @ T
    U = np.eye(4)
    U[:3, :3] = imported.UP["y"].T
    S = np.diag([0.001, 0.001, 0.001, 1.0])
    return S @ U @ T


def damage(m, rng, noise=0.0, grain=2.0, wavy=0.0, jitter=0.0, holes=0, junk=0):
    import trimesh

    if noise:  # scan speckle: bumps about ``grain`` mm across
        m = synth.speckle(m, noise, grain_mm=grain, seed=int(rng.integers(1 << 30)))
    if wavy:  # long, gentle undulations: a different shape, not noise (the error here is the shape change)
        m = synth.bumps(m, wavy, waves=(12.0, 40.0), seed=int(rng.integers(1 << 30)))
    if jitter:
        m = trimesh.Trimesh(m.vertices + rng.normal(0, jitter, m.vertices.shape), m.faces, process=False)
    if holes:
        under = np.nonzero((m.face_normals[:, 2] < -0.5) & (m.triangles_center[:, 2] < 20))[0]
        keep = np.ones(len(m.faces), bool)
        for c in rng.choice(under, holes, replace=False):
            keep &= np.linalg.norm(m.triangles_center - m.triangles_center[c], axis=1) > 8.0
        m = m.copy()
        m.update_faces(keep)
        m.remove_unreferenced_vertices()
    if junk:
        parts = [m]
        for _ in range(junk):
            b = trimesh.creation.icosphere(1, rng.uniform(3, 8))
            b.apply_translation([125, 45, 20] + rng.uniform(-120, 120, 3) * [1, 1, 0.3])
            parts.append(b)
        m = trimesh.util.concatenate(parts)
    return m


TOES_BEND_FROM, TOES_BEND_BLEND = 185.0, 12.0  # synth.bend_toes' hinge (x, foot coordinates) and blend, mm
TIPS_BEND_FROM = 220.0  # a second bend, nearer the tips (the toes' own joints), for toes that curl as well


def _bent(foot, toes_up, tips_up=0.0):
    """The synthetic foot, its toes bent up ``toes_up`` degrees (synth.bend_toes) if any, and their tips a
    further ``tips_up`` degrees from ``TIPS_BEND_FROM`` (bent first, so the toes' bend carries it). Split to
    2 mm triangles first, so the bend is smooth (it adds points, not shape)."""
    m = synth.curved_foot(foot)
    if not toes_up and not tips_up:
        return m
    m = synth.refined(m)
    if tips_up:
        m = synth.bend_toes(m, tips_up, x_from=TIPS_BEND_FROM, blend=TOES_BEND_BLEND)
    return synth.bend_toes(m, toes_up, x_from=TOES_BEND_FROM, blend=TOES_BEND_BLEND) if toes_up else m


def _truth(foot, toes_up, tips_up=0.0):
    """The true sole height at x, y; with the toes bent, only behind the bend (NaN past it: the toes are
    laid flat by the preparation, which isn't a rigid move, so there they can't be mapped back exactly)."""
    if not toes_up and not tips_up:
        return lambda x, y: synth.curved_sole(x, y, foot)
    behind = (TOES_BEND_FROM if toes_up else TIPS_BEND_FROM) - TOES_BEND_BLEND / 2 - EDGE_MM
    return lambda x, y: np.where(np.asarray(x) < behind, synth.curved_sole(x, y, foot), np.nan)


def sole_up_case(foot, rng, tip=25.0, roll=0.0, yaw=63.0, gravity_tilt=0.0, bed=True, toes_up=0.0, tips_up=0.0,
                 **dmg):
    """Lying face down, knee bent: the foot (with leg) turned sole-up, tipped by its relaxed ankle."""
    import trimesh

    m = damage(_bent(foot, toes_up, tips_up), rng, **dmg)
    P = np.diag([1.0, -1, -1, 1]) @ _rot(roll, [1, 0, 0], [0, 45, 0]) @ _rot(tip, [0, 1, 0], [0, 45, 0])
    m.apply_transform(P)
    if bed:
        b = trimesh.creation.box(extents=[700, 500, 30])
        b.apply_translation([100, 45, -420])
        m = trimesh.util.concatenate([m, b])
    S = to_object_capture(yaw, gravity_tilt)
    m.apply_transform(S)
    # synthetic foot coordinates <- scan as handed over; the true sole there is curved_sole, floor z = 0
    return m, np.linalg.inv(S @ P), _truth(foot, toes_up, tips_up), 0.0


def legs_flat_case(foot, rng, yaw=63.0, gravity_tilt=0.0, bed=True, toes_up=0.0, tips_up=0.0, **dmg):
    """Face down, legs straight, the foot just past the end of the bed: the sole faces back."""
    import trimesh

    m = damage(_bent(foot, toes_up, tips_up), rng, **dmg)
    W = np.eye(4)
    W[:3, :3] = np.c_[[0, 0, -1.0], [0, -1.0, 0], [-1.0, 0, 0]]  # standing -> lying: up -> -x, front -> down
    m.apply_transform(W)
    if bed:
        V = m.vertices
        shin = V[V[:, 0] < -80]
        b = trimesh.creation.box(extents=[700, 600, 40])
        b.apply_translation([V[:, 0][V[:, 0] < -60].max() - 20 - 350, shin[:, 1].mean(), shin[:, 2].min() - 20.5])
        m = trimesh.util.concatenate([m, b])
    S = to_object_capture(yaw, gravity_tilt)
    m.apply_transform(S)
    return m, np.linalg.inv(S @ W), _truth(foot, toes_up, tips_up), 0.0


def print_case(foot, rng, depth=30.0, yaw=63.0, gravity_tilt=0.0, **dmg):
    """The foot pressed ``depth`` mm into a foam block on a table, scanned from all round."""
    m = damage(synth.refined(synth.foam_print(foot, depth=depth, shape="curved"), 3.0), rng, **dmg)
    S = to_object_capture(yaw, gravity_tilt)
    m.apply_transform(S)
    sole_z = 70.0 - depth
    return m, np.linalg.inv(S), lambda x, y: sole_z + synth.curved_sole(x, y, foot), sole_z


CASES = [
    # (name, kind, builder, kwargs)
    ("clean", "sole_up", sole_up_case, {}),
    ("not tipped", "sole_up", sole_up_case, dict(tip=0.0)),
    ("tipped 45", "sole_up", sole_up_case, dict(tip=45.0)),
    ("toes up 15", "sole_up", sole_up_case, dict(tip=-15.0)),
    ("rolled 15", "sole_up", sole_up_case, dict(roll=15.0)),
    ("phone level off 4", "sole_up", sole_up_case, dict(gravity_tilt=4.0)),
    ("speckle 0.3", "sole_up", sole_up_case, dict(noise=0.3)),
    ("speckle 0.6", "sole_up", sole_up_case, dict(noise=0.6)),
    ("speckle 1.0", "sole_up", sole_up_case, dict(noise=1.0)),
    ("coarse speckle 0.6", "sole_up", sole_up_case, dict(noise=0.6, grain=4.0)),
    ("jitter 0.5", "sole_up", sole_up_case, dict(jitter=0.5)),
    ("holes x6", "sole_up", sole_up_case, dict(holes=6)),
    ("stray bits", "sole_up", sole_up_case, dict(junk=6)),
    ("speckle 0.6 + holes", "sole_up", sole_up_case, dict(noise=0.6, holes=6)),
    ("toes bent up 20", "sole_up", sole_up_case, dict(toes_up=20.0)),
    ("toes bent up 35", "sole_up", sole_up_case, dict(toes_up=35.0)),
    ("toes bent up 35 + speckle 0.6", "sole_up", sole_up_case, dict(toes_up=35.0, noise=0.6)),
    ("toes up 20, tips 30 more", "sole_up", sole_up_case, dict(toes_up=20.0, tips_up=30.0)),
    ("toes up 30, tips 40 more", "sole_up", sole_up_case, dict(toes_up=30.0, tips_up=40.0)),
    ("clean", "sole_hanging", legs_flat_case, {}),
    ("no bed in the scan", "sole_hanging", legs_flat_case, dict(bed=False)),
    ("phone level off 4", "sole_hanging", legs_flat_case, dict(gravity_tilt=4.0)),
    ("speckle 0.6", "sole_hanging", legs_flat_case, dict(noise=0.6)),
    ("jitter 0.5", "sole_hanging", legs_flat_case, dict(jitter=0.5)),
    ("toes bent up 35", "sole_hanging", legs_flat_case, dict(toes_up=35.0)),
    ("toes up 20, tips 30 more", "sole_hanging", legs_flat_case, dict(toes_up=20.0, tips_up=30.0)),
    ("clean", "impression", print_case, {}),
    ("shallow 18", "impression", print_case, dict(depth=18.0)),
    ("deep 45", "impression", print_case, dict(depth=45.0)),
    ("box tilted 8", "impression", print_case, dict(gravity_tilt=8.0)),
    ("speckle 0.3", "impression", print_case, dict(noise=0.3)),
    ("speckle 0.6", "impression", print_case, dict(noise=0.6)),
    ("speckle 1.0", "impression", print_case, dict(noise=1.0)),
    ("coarse speckle 0.6", "impression", print_case, dict(noise=0.6, grain=4.0)),
    ("jitter 0.5", "impression", print_case, dict(jitter=0.5)),
    ("crumbs", "impression", print_case, dict(junk=8)),
]
QUICK = {("clean", "sole_up"), ("speckle 0.6", "sole_up"), ("clean", "impression"), ("speckle 0.6", "impression")}


# ---------------------------------------------------------------------------
# measuring
# ---------------------------------------------------------------------------
def measure(name, kind, builder, kw, foot, seed=0):
    import shapely

    rng = np.random.default_rng(seed)
    scan, to_synth, truth, floor0 = builder(foot, rng, **kw)
    t = time.time()
    ins, placed = foot_prep.insole_from_object_capture(scan, foot, kind=kind)
    secs = time.time() - t
    r = ins.report
    to_mat = np.array(r["prep"]["to_mat"])

    # the sole the generator reads: the same steps as insole.build
    run = plantar.run(placed, foot)
    fm = insole.output_frame(run["foot_mesh"], foot)
    sil = insole.silhouette(fm)
    x0, y0, x1, y1 = sil.bounds
    xs, ys = np.arange(x0, x1, GRID), np.arange(y0, y1, GRID)
    X, Y = np.meshgrid(xs, ys, indexing="xy")
    inside = shapely.contains_xy(sil, X, Y)
    H, S = insole.sole_heights(fm, xs, ys, inside)
    seen = inside & (S == 1)
    P_out = np.c_[X[seen], Y[seen], H[seen]]

    # output frame -> foot frame -> mat -> scan as handed over -> synthetic foot coordinates
    fr = run["summary"]["frame"]
    Rf = np.vstack([fr["anterior"], fr["medial"], fr["up"]])
    local = P_out.copy()
    if foot == "left":
        local[:, 1] *= -1  # output frame's y is the foot's left; for a left foot that's lateral
    mat = local @ Rf + np.array(fr["origin_mat_mm"])
    T = to_synth @ np.linalg.inv(to_mat)
    syn = np.c_[mat, np.ones(len(mat))] @ T.T
    xs_, ys_, zs_ = syn[:, 0], syn[:, 1], syn[:, 2]

    plan = synth.curved_plan()
    d_edge = shapely.distance(plan.exterior, shapely.points(np.c_[xs_, ys_]))
    interior = shapely.contains_xy(plan, xs_, ys_) & (d_edge > EDGE_MM)
    tz = truth(xs_[interior], ys_[interior])
    interior[interior] = np.isfinite(tz)  # a case may compare only part of the sole
    true_z = tz[np.isfinite(tz)]
    # the height the insole uses (above the floor the preparation found) against the true height
    # above the true floor, at the same spot on the foot: floor errors and surface errors together
    err = H[seen][interior] - (true_z - floor0)
    surface_err = zs_[interior] - true_z  # where the surface is, whatever the floor: the surface alone

    # wedge: a plane fitted to the height errors over the sole; its slope is the tilt the insole
    # would really carry (a floor tilt the height map shows), in degrees, front-back and side-side
    A = np.c_[np.ones(interior.sum()), xs_[interior], ys_[interior]]
    coef, *_ = np.linalg.lstsq(A, err, rcond=None)
    wedge_pitch, wedge_roll = (float(np.degrees(np.arctan(abs(c)))) for c in coef[1:])

    # the floor found, as a direction in synthetic coordinates, against the true floor's
    up_out = np.array([0.0, 0.0, 1.0])
    up_local = up_out.copy()
    up_mat = up_local @ Rf
    up_syn = T[:3, :3] @ up_mat
    up_syn /= np.linalg.norm(up_syn)
    tilt = float(np.degrees(np.arccos(np.clip(up_syn[2], -1, 1))))

    # arch: the highest point of the surface the insole is shaped to (the generator's smoothing:
    # a 1.5 mm Gaussian that may only lower, min(smooth, raw + 0.5)) vs the highest true point,
    # over the same interior points, each above its own floor
    from scipy import ndimage

    raw = np.where(seen, H, 0.0)
    smooth = ndimage.gaussian_filter(raw, insole.SMOOTH_SIGMA_MM / GRID)
    shaped = np.minimum(smooth, raw + insole.SMOOTH_MAY_RAISE_MM)
    arch_read = float(np.max(shaped[seen][interior]))
    arch_true = float(np.max(true_z - floor0))
    inner_side = (r["max_fill_at_mm"]["y"] > 0) == (foot == "right")
    return dict(
        name=name, kind=kind, foot=foot, secs=round(secs, 1), points=int(interior.sum()),
        bias=float(np.mean(err)), rms=float(np.sqrt(np.mean(err ** 2))), p95=float(np.percentile(np.abs(err), 95)),
        arch=arch_read - arch_true, tilt=tilt, pitch=wedge_pitch, roll=wedge_roll, length=_longest(sil) - _longest(synth.curved_plan()),
        surface_rms=float(np.sqrt(np.mean(surface_err ** 2))), side=inner_side, noise=r["prep"].get("surface_noise_mm"), warnings=r["warnings"],
    )


def _longest(poly) -> float:
    """The outline's longest dimension (largest distance between two of its points), mm: its length
    whichever way the foot frame's axis happens to point."""
    from scipy.spatial.distance import pdist

    P = np.asarray(poly.convex_hull.exterior.coords)
    return float(pdist(P).max())


def row(m):
    w = "; ".join(x.split(":")[0][:48] for x in m["warnings"]) or "-"
    return (f"| {m['kind']} | {m['name']} | {m['foot']} | {m['bias']:+.2f} | {m['rms']:.2f} | {m['p95']:.2f} | "
            f"{m['arch']:+.2f} | {m['tilt']:.2f} ({m['pitch']:.2f} / {m['roll']:.2f}) | {m['length']:+.1f} | "
            f"{'yes' if m['side'] else 'NO'} | {m['noise']} | {w} |")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("-o", "--output", default=str(ROOT / "reports" / "benchmark-prep.md"))
    args = ap.parse_args(argv)

    results = []
    for name, kind, builder, kw in CASES:
        if args.quick and (name, kind) not in QUICK:
            continue
        for foot in ("right", "left"):
            try:
                m = measure(name, kind, builder, kw, foot)
            except Exception as e:  # noqa: BLE001 - a case that fails is a result
                m = dict(name=name, kind=kind, foot=foot, error=f"{type(e).__name__}: {e}")
                print(f"{kind:10s} {name:22s} {foot:5s} FAILED {m['error']}", flush=True)
            else:
                print(f"{kind:10s} {name:22s} {foot:5s} bias {m['bias']:+.2f} rms {m['rms']:.2f} p95 {m['p95']:.2f} "
                      f"arch {m['arch']:+.2f} tilt {m['tilt']:.2f} len {m['length']:+.1f} side {m['side']} "
                      f"noise {m['noise']} warn {len(m['warnings'])} ({m['secs']}s)", flush=True)
            results.append(m)

    ok = [m for m in results if "error" not in m]
    lines = [
        "# Sole-reading benchmark (synthetic feet)",
        "",
        "SYNTHETIC: computer-made scans of a foot whose true shape is known exactly. This measures the error",
        "the processing adds, not the accuracy of a real phone scan of a real foot. Made by",
        "`scripts/benchmark_prep.py`; heights in mm, tilt in degrees.",
        "",
        "| scan | case | foot | bias | rms | p95 | arch | floor tilt (wedge: heel-toe / side) | length | inner side | noise read | warnings |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
        *[row(m) if "error" not in m else f"| {m['kind']} | {m['name']} | {m['foot']} | FAILED: {m['error']} |" for m in results],
        "",
    ]
    if ok:
        worst = max(ok, key=lambda m: m["p95"])
        lines += [f"Cases: {len(results)}, failed: {len(results) - len(ok)}. Largest p95 error: {worst['p95']:.2f} mm "
                  f"({worst['kind']}, {worst['name']}, {worst['foot']}).", ""]
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text("\n".join(lines))
    print(f"written: {args.output}")
    return 0 if len(ok) == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
