"""Does a sole scan read the same however it was held? Prepares each scan several times, turned a little first.

A scan of a foot held a few degrees differently is the same foot, so what the studio reads from it (the outline's
length and width, how square each end is, the ball of the foot's roll, whether the arrival check would refuse it on
its own faults, not counting the length against the person's other scans)
should not change. For each imported sole scan in the studio's captures folder (or the folders named), this turns
the model as the app sent it by up to ``--tilt`` degrees about two level axes and any amount about the vertical,
``--turns`` times (the same turns every run), prepares it as Make insole does each time, and prints the spread.
Read-only: nothing in the captures folder is changed.

It's how the floor fault fixed on 2026-11-25 was found (docs/insole.md): the left sole-up scan
LIDAR_nwb_relaxed_L_20261027-151404-89df read 228.5-250.2 mm long over 12 turns of up to 5 degrees; it now reads
the same every time. Results are for the scans named, never for feet in general. A scan takes about 4-5 s a turn.

  .venv/bin/python scripts/pose_spread.py [data/captures | capture folders...] [--turns 8] [--tilt 5]
      [--json reports/pose-spread.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from footscan import server  # noqa: E402
from footscan.recon import completeness, foot_prep  # noqa: E402
from footscan.recon.imported import load_geometry  # noqa: E402


def turns(n: int, tilt_deg: float, up: str, seed: int = 0) -> list[np.ndarray]:
    """``n`` 4 x 4 turns, the first none: about the model's up axis by any amount, then up to ``tilt_deg`` about
    each of the two level axes."""
    import trimesh

    rot = trimesh.transformations.rotation_matrix
    axes = {"y": ([1, 0, 0], [0, 1, 0], [0, 0, 1]), "z": ([1, 0, 0], [0, 0, 1], [0, 1, 0])}[up]
    level_a, vertical, level_b = axes
    rng = np.random.default_rng(seed)
    out = [np.eye(4)]
    for _ in range(n - 1):
        out.append(rot(np.radians(rng.uniform(-tilt_deg, tilt_deg)), level_a)
                   @ rot(np.radians(rng.uniform(-tilt_deg, tilt_deg)), level_b)
                   @ rot(np.radians(rng.uniform(0, 360)), vertical))
    return out


def spread(mesh, meta: dict, n: int, tilt_deg: float) -> dict:
    """One scan, prepared after each turn -> each reading, and the spread of each."""
    kind = meta.get("scan_kind")
    up = (meta.get("mesh") or {}).get("up", "y")
    rows = []
    for T in turns(n, tilt_deg, up):
        m = mesh.copy()
        m.apply_transform(T)
        try:
            placed, info = foot_prep.PREPARE[kind](m, up, foot=meta["foot"])
            c = completeness.measure(placed, kind)
        except Exception as e:  # noqa: BLE001 - reported per turn
            rows.append(dict(error=f"{type(e).__name__}: {e}"))
            continue
        sides = info.get("ball_sides_above_floor_mm") or {}
        rows.append(dict(length_mm=c["length_mm"], width_mm=c["width_mm"], toe_end=c["toe_end"], heel_end=c["heel_end"],
                         ball_roll_mm=round(abs(sides.get("plus_x", 0.0) - sides.get("minus_x", 0.0)), 1),
                         refused=bool(completeness.problems(c) + completeness.from_prep(info))))
    ok = [r for r in rows if "error" not in r]
    summary = {k: [min(r[k] for r in ok), max(r[k] for r in ok)] for k in
               ("length_mm", "width_mm", "toe_end", "heel_end", "ball_roll_mm")} if ok else {}
    summary["verdicts"] = sorted({"refused" if r["refused"] else "kept" for r in ok})
    summary["errors"] = len(rows) - len(ok)
    return dict(turns=rows, spread=summary)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="*", default=[str(ROOT / "data" / "captures")],
                    help="a captures folder, or capture folders")
    ap.add_argument("--turns", type=int, default=8)
    ap.add_argument("--tilt", type=float, default=5.0, help="largest turn about a level axis, degrees")
    ap.add_argument("--json", help="also write the results here (reports/ is not committed)")
    a = ap.parse_args(argv)
    folders = []
    for p in map(Path, a.paths):
        folders += [p] if (p / "capture.json").is_file() else sorted(q for q in p.iterdir() if (q / "capture.json").is_file())
    out = {}
    for folder in folders:
        meta = server.read_json(folder / "capture.json")
        if not server._checked(meta) or not (folder / "mesh.ply").is_file():
            continue  # only the sole scans the arrival check reads
        r = spread(load_geometry(folder / "mesh.ply"), meta, a.turns, a.tilt)
        out[folder.name] = r
        s = r["spread"]
        if not s.get("verdicts"):
            print(f"{folder.name}: couldn't prepare it at any turn")
            continue
        print(f"{folder.name} ({meta['foot']}, {meta['scan_kind']}), {a.turns} turns of up to {a.tilt:g} degrees: "
              f"length {s['length_mm'][0]}-{s['length_mm'][1]} mm, width {s['width_mm'][0]}-{s['width_mm'][1]} mm, "
              f"ball roll {s['ball_roll_mm'][0]}-{s['ball_roll_mm'][1]} mm, {'/'.join(s['verdicts'])}"
              + (f", {s['errors']} turns couldn't be prepared" if s["errors"] else ""))
    if a.json:
        Path(a.json).parent.mkdir(parents=True, exist_ok=True)
        Path(a.json).write_text(json.dumps(out, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
