"""Put someone else's foot scan (e.g. a Foot3D OBJ) on the mat, then make a first-fit insole from it.

    .venv/bin/python scripts/external_foot.py path/to/foot.obj --foot right -o reports/foot3d-0000

Foot3D (github.com/OllieBoyne/Foot3D) doesn't document its meshes' units,
axes or pose, so nothing is assumed; each step is decided from the shape
and written to placement.json so it can be checked:

1. **Units**: from the size (a foot is a few tenths of a metre), as Import 3D does.
2. **Length**: the foot's longest direction (principal component analysis).
3. **Up**: of the four directions across the foot (± the other two axes),
   the one whose *lowest* part looks like a sole: the most downward-facing
   area within 15 mm of the bottom. The ankle side is narrow; the sole is broad.
4. **Floor**: the foot is turned and lowered onto a flat floor the way it
   would rest on a table: the face of its convex hull directly under its
   centre of mass becomes z = 0. For a foot scanned off the ground this
   touches the heel and the ball of the foot, and the arch stays up.
5. **Toes toward +y** (the mat's toe sheet): the ankle (the highest part)
   sits over the heel, so the toes are at the other end.

Then it runs the same generator as ``footscan insole`` and checks the
result makes sense for this kind of scan (see ``sanity``). Someone else's
foot: the outputs are labelled as such, and are for testing the software.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from footscan import insole  # noqa: E402
from footscan.recon.imported import load_geometry, to_millimetres  # noqa: E402

SOLE_BAND_MM = 15.0


def _rotation_to(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Rotation taking unit vector a onto unit vector b."""
    v = np.cross(a, b)
    s, c = np.linalg.norm(v), float(a @ b)
    if s < 1e-12:
        if c > 0:
            return np.eye(3)
        # opposite: turn half a turn about any perpendicular axis
        p = np.cross(a, [1.0, 0, 0] if abs(a[0]) < 0.9 else [0, 1.0, 0])
        p /= np.linalg.norm(p)
        return 2 * np.outer(p, p) - np.eye(3)
    K = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]]) / s
    return np.eye(3) + s * K + (1 - c) * (K @ K)


def _apply(mesh, R: np.ndarray, t: np.ndarray | None = None):
    T = np.eye(4)
    T[:3, :3] = R
    if t is not None:
        T[:3, 3] = t
    mesh.apply_transform(T)


def sole_score(mesh, up: np.ndarray) -> float:
    """Downward-facing area near the bottom, if `up` is up. Bigger = more sole-like."""
    h = mesh.triangles_center @ up
    low = h < h.min() + SOLE_BAND_MM
    down = (mesh.face_normals @ up) < -0.5
    return float(mesh.area_faces[low & down].sum())


def place_on_mat(mesh, up_hint: str | None = None) -> tuple[object, dict]:
    """Millimetre mesh -> mat frame (z up, floor z = 0, toes toward +y). Returns (mesh, decisions)."""
    m = mesh.copy()
    V = np.asarray(m.vertices)
    c = V.mean(0)
    _, vecs = np.linalg.eigh(np.cov((V - c).T))
    length_axis, mid, small = vecs[:, 2], vecs[:, 1], vecs[:, 0]
    decisions = {}

    # up
    if up_hint:
        sign = -1.0 if up_hint.startswith("-") else 1.0
        up = sign * np.eye(3)["xyz".index(up_hint[-1])]
        decisions["up"] = f"given: {up_hint}"
    else:
        cands = [mid, -mid, small, -small]
        scores = [sole_score(m, u) for u in cands]
        best = int(np.argmax(scores))
        up = cands[best]
        ranked = sorted(scores, reverse=True)
        decisions["up"] = "detected (most sole-like bottom)"
        decisions["up_confidence"] = round(ranked[0] / max(ranked[1], 1e-9), 2)  # best vs runner-up
    m.apply_translation(-c)
    _apply(m, _rotation_to(up / np.linalg.norm(up), np.array([0.0, 0, 1.0])))

    # rest on a flat floor: the hull face under the centre of mass
    hull = m.convex_hull
    com = m.center_mass if m.is_volume else m.vertices.mean(0)
    down = hull.face_normals[:, 2] < -0.3
    best_face, best_cos = None, -1.0
    for fi in np.nonzero(down)[0]:
        n = hull.face_normals[fi]
        p0 = hull.triangles[fi][0]
        # where the vertical line through the centre of mass meets this face's plane
        z = p0[2] - (n[0] * (com[0] - p0[0]) + n[1] * (com[1] - p0[1])) / n[2]
        q = np.array([com[0], com[1], z])
        tri = hull.triangles[fi]
        # is q inside the triangle (projected on the plane)? barycentric test
        v0, v1, v2 = tri[1] - tri[0], tri[2] - tri[0], q - tri[0]
        d00, d01, d11, d20, d21 = v0 @ v0, v0 @ v1, v1 @ v1, v2 @ v0, v2 @ v1
        den = d00 * d11 - d01 * d01
        if abs(den) < 1e-12:
            continue
        b1 = (d11 * d20 - d01 * d21) / den
        b2 = (d00 * d21 - d01 * d20) / den
        if b1 >= -1e-6 and b2 >= -1e-6 and b1 + b2 <= 1 + 1e-6 and -n[2] > best_cos:
            best_face, best_cos = fi, -n[2]
    if best_face is None:  # fall back to the lowest point
        _apply(m, np.eye(3), np.array([0, 0, -m.vertices[:, 2].min()]))
        decisions["floor"] = "lowest point (no hull face under the centre of mass)"
    else:
        n = hull.face_normals[best_face]
        R = _rotation_to(n, np.array([0.0, 0, -1.0]))  # that face's outward normal points straight down
        _apply(m, R)
        _apply(m, np.eye(3), np.array([0, 0, -m.vertices[:, 2].min()]))
        decisions["floor"] = f"rests on the hull face under its centre of mass (tilted {np.degrees(np.arccos(min(1, best_cos))):.1f} deg from the first guess)"

    # toes toward +y: length along y, ankle (highest part) over the heel
    V = np.asarray(m.vertices)
    xy = V[:, :2] - V[:, :2].mean(0)
    _, vecs2 = np.linalg.eigh(np.cov(xy.T))
    ax = vecs2[:, 1]
    yaw = np.arctan2(ax[0], ax[1])  # turn the length axis onto +y
    cz, sz = np.cos(yaw), np.sin(yaw)
    _apply(m, np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1.0]]))
    V = np.asarray(m.vertices)
    top = V[V[:, 2] > np.percentile(V[:, 2], 90)]
    if top[:, 1].mean() > V[:, 1].mean():  # the ankle is toward +y: turn round so toes go +y
        _apply(m, np.diag([-1.0, -1.0, 1.0]))
        decisions["toes"] = "turned round: the ankle (highest part) was at the toe end"
    else:
        decisions["toes"] = "the ankle (highest part) is over the heel end, as expected"
    _apply(m, np.eye(3), np.array([100.0, 150.0, 0.0]) - np.r_[np.asarray(m.vertices)[:, :2].mean(0), 0])
    decisions["size_mm"] = [round(float(v), 1) for v in sorted(m.extents, reverse=True)]
    return m, decisions


def sanity(report: dict, foot: str) -> list[str]:
    """What a sensible result looks like for a foot scanned off the ground (its whole sole visible)."""
    out = []
    sole = report["sole"]
    out.append(("ok: " if sole["seen"] > 0.6 else "CHECK: ") +
               f"sole seen over {sole['seen']:.0%} of the footprint (an off-the-ground scan shows most of it)")
    out.append(("ok: " if sole["seen_under_arch"] > 0.6 else "CHECK: ") +
               f"sole seen under the arch: {sole['seen_under_arch']:.0%}")
    arch_warned = any("under the arch" in w for w in report["warnings"])
    out.append(("CHECK: the 'arch not seen' warning fired" if arch_warned else "ok: no 'arch not seen' warning"))
    length = report["length_mm"]
    at = report["max_fill_at_mm"]
    frac = at["x"] / max(length, 1e-9)
    out.append(("ok: " if 0.25 <= frac <= 0.7 else "CHECK: ") +
               f"highest fill {report['max_fill_mm']} mm at {frac:.0%} of the length from the heel (expected: midfoot)")
    # insole frame: y toward the foot's left, so the inner (arch) side is +y for a right foot, -y for a left
    inner = at["y"] > 0 if foot == "right" else at["y"] < 0
    out.append(("ok: " if inner else "CHECK: ") +
               f"highest fill on the {'inner' if inner else 'outer'} side (y = {at['y']} mm)" +
               ("" if inner or report["max_fill_mm"] < 1 else f": is this really a {foot} foot? check --foot"))
    if any("clipped" in w for w in report["warnings"]):
        out.append("CHECK: the safety caps clipped the fill (an unloaded foot's arch is higher than a standing one's)")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("mesh", help="OBJ/PLY/STL of a foot (any units, any orientation)")
    ap.add_argument("--foot", choices=["left", "right"], required=True)
    ap.add_argument("-o", "--output", required=True)
    ap.add_argument("--up", choices=["x", "y", "z", "-x", "-y", "-z"], help="override the detected up axis")
    ap.add_argument("--label", default=None, help="what to call it on the sheet (default: the file name)")
    args = ap.parse_args(argv)

    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    mesh, units, _ = to_millimetres(load_geometry(args.mesh))
    placed, decisions = place_on_mat(mesh, args.up)
    decisions["units_detected"] = units
    ply = out / "foot-on-mat.ply"
    placed.export(ply)

    ins = insole.from_scan(placed, args.foot)
    label = args.label or f"{Path(args.mesh).name} (external scan, not the wearer's foot)"
    files = insole.write_outputs(ins, out, f"{args.foot}-insole", label, synthetic=True)
    checks = sanity(ins.report, args.foot)
    (out / "placement.json").write_text(json.dumps(dict(source=str(args.mesh), decisions=decisions,
                                                        checks=checks, report=ins.report), indent=2))

    r = ins.report
    print(f"{args.mesh}: {units} -> mm, {decisions['size_mm']} mm; up {decisions['up']}"
          + (f" (confidence {decisions['up_confidence']}x)" if "up_confidence" in decisions else ""))
    print(f"  floor: {decisions['floor']}")
    print(f"  toes: {decisions['toes']}")
    print(f"  insole {r['length_mm']} x {r['width_mm']} mm, highest fill {r['max_fill_mm']} mm")
    for w in r["warnings"]:
        print(f"  warning: {w}")
    for c in checks:
        print(f"  {c}")
    print(f"  files: {out}  (foot-on-mat.ply, placement.json, {Path(files['threemf']).name}, summary sheet)")
    return 0 if not any(c.startswith("CHECK") for c in checks) else 2


if __name__ == "__main__":
    sys.exit(main())
