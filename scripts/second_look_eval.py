"""Would a Claude "second look" at a scan catch problems footscan's own checks miss? An evaluation.

Each case is a real scan, or a real scan with a known kind of damage, run through the same
preparation as Make insole. For each: what footscan's own checks say (its warnings), and, unless
--dry-run, what Claude says when asked exactly what the studio asks it on arrival with
--check-scans-with-claude (src/footscan/second_look.py: the same pictures, measures, question and
model), keep or scan again, judging the SCAN only (never the foot's shape or health). The answers are
scored against what each case is known to be. Claude never changes the shape or gives a number.

  .venv/bin/python scripts/second_look_eval.py SCAN.obj [--mac-rebuild NAME=PATH ...] [--dry-run] [-o DIR]

SCAN is a sole-up scan as the iPhone app hands it over (metres, Y up). The damage is cut out of the
raw scan where the prepared model says (heel, toes, a side, under the arch), so it goes through the
whole preparation like a real flaw. Needs `pip install anthropic` and a key (ANTHROPIC_API_KEY, or an
`ant auth login` profile) unless --dry-run. Sends the eight rendered views of each case (pictures of
the model, no photos of the person) and its measures to the Claude API. Roughly 8 requests.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from footscan import second_look  # noqa: E402
from footscan.insole import InsoleParams  # noqa: E402
from footscan.pictures import png_bytes  # noqa: E402
from footscan.recon import completeness, foot_prep  # noqa: E402
from footscan.recon.imported import load_geometry, to_millimetres  # noqa: E402

# --------------------------------------------------------------------------- cases
def damaged(scan, cut) -> object:
    """``scan`` without the faces whose prepared (mat-frame) position ``cut(x, y, z, length)`` selects."""
    # the cut maps the scan with to_mat, which holds everywhere only for a rigid preparation: toes as scanned
    lay, foot_prep.LAY_TOES_FLAT = foot_prep.LAY_TOES_FLAT, False
    try:
        placed, info = foot_prep.prepare_sole_up(scan, "y")
    finally:
        foot_prep.LAY_TOES_FLAT = lay
    T = np.asarray(info["to_mat"])
    C = np.c_[scan.triangles_center, np.ones(len(scan.faces))] @ T.T
    V = placed.vertices
    y0, length = V[:, 1].min(), np.ptp(V[:, 1])
    gone = cut(C[:, 0] - V[:, 0].mean(), (C[:, 1] - y0) / length, C[:, 2], length)
    out = scan.copy()
    out.update_faces(~gone)
    out.remove_unreferenced_vertices()
    return out


DAMAGE = {  # name: (cut in the prepared frame: x across from the middle (mm), y share from the heel, z mm)
    "toes missing (last 15%)": lambda x, y, z, L: y > 0.85,
    "heel underside missing": lambda x, y, z, L: (y < 0.25) & (z < 15),
    "one side missing (below 25 mm)": lambda x, y, z, L: (x > 15) & (z < 25),
    "hole under the arch": lambda x, y, z, L: (y > 0.35) & (y < 0.6) & (z < 25) & (np.abs(x) < 20),
}


def footscan_checks(scan) -> list[str]:
    # the foot's own outline: what footscan says about the scan, not about how it fits an outline
    ins, _ = foot_prep.insole_from_object_capture(scan, "right", kind="sole_up",
                                                  params=InsoleParams(foot_outline=True))
    return ins.report["warnings"]


def ask_claude(views, measures: dict, info: dict) -> dict:
    """The studio's own question (second_look.ask), or why there was no answer."""
    try:
        return second_look.ask(views, measures, info, "sole_up")
    except second_look.Unavailable as e:
        return dict(verdict="no answer", why=str(e), problems=[])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("scan")
    ap.add_argument("--mac-rebuild", action="append", default=[], metavar="NAME=PATH",
                    help="a rebuild of the same scan known to have lost the heel's underside")
    ap.add_argument("--dry-run", action="store_true", help="pictures and footscan's checks only; no API call")
    ap.add_argument("-o", "--out", default="reports/second-look", help="folder for the pictures and results")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    scan = load_geometry(a.scan)
    cases = [("real scan, as it is", scan, False)]
    cases += [(f"real scan, {k}", damaged(scan, cut), True) for k, cut in DAMAGE.items()]
    cases += [(f"{name} (heel underside lost)", load_geometry(path), True)
              for name, path in (m.split("=", 1) for m in a.mac_rebuild)]

    rows = []
    for name, mesh, faulty in cases:
        warnings = footscan_checks(mesh)
        placed, info = foot_prep.prepare_sole_up(mesh, "y")
        views = second_look.pictures(placed, to_millimetres(mesh)[0])
        slug = "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-")
        for i, (_, rgb) in enumerate(views, 1):
            (out / f"{slug}-{i}.png").write_bytes(png_bytes(rgb))
        # any warning about the scan counts; the routine note that the safety caps clipped some fill doesn't
        about_scan = [w for w in warnings if not w.startswith("the fill was clipped by the safety caps")]
        row = dict(case=name, faulty=faulty, footscan_flagged=bool(about_scan),
                   footscan_warnings=warnings, pictures=f"{slug}-1.png ... -{len(views)}.png")
        if not a.dry_run:
            row["claude"] = ask_claude(views, completeness.measure(placed, "sole_up"), info)
            if row["claude"]["verdict"] != "no answer":
                row["claude_flagged"] = row["claude"]["verdict"] == "scan_again"
        rows.append(row)
        print(f"{name:48s} faulty={faulty!s:5s} footscan={row['footscan_flagged']!s:5s}"
              + ("" if a.dry_run else f" claude={row['claude']['verdict']}"), flush=True)
    (out / "results.json").write_text(json.dumps(rows, indent=2, default=str), encoding="utf-8")

    def score(key):
        ok = [r for r in rows if key in r]
        return sum(r[key] == r["faulty"] for r in ok), len(ok)

    print("\nright calls: footscan's checks %d/%d" % score("footscan_flagged")
          + ("" if a.dry_run else ", Claude %d/%d" % score("claude_flagged")))
    print(f"pictures and results in {out}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
