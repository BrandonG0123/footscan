"""How well does the preparation read the real scans? Every imported capture, measured the same way.

    .venv/bin/python scripts/accuracy_eval.py [data/captures] [--json reports/accuracy.json] [--md reports/accuracy.md]

There is no true shape for a real foot here, so this reads what *can* be checked without one, scan
by scan, and between scans of the same person:

Per scan (prepared exactly as Make insole prepares it, foot_prep.PREPARE):
- outline: length x width of the outline the insole is cut to (seen from above, below
  insole.SILHOUETTE_HEIGHT_MM), and how square each end is (completeness.measure).
- full length: heel back to toe tip seen from above, at any height up to the leg trim. Longer than
  the outline when the toe tips rise above the outline's height.
- toe tip height, heel back above the floor, ball roll (how much higher one side of the ball of
  the foot is than the other), floor correction, surface noise, open edges near the floor.
- the plausibility warnings Make insole would give.

Between scans: left against right (lengths and widths: a person's feet differ by a few mm, so a big
gap points at a scan), and each pair of scans of the same foot and kind (compare.compare_prepared:
the "repeat scans within ... mm" measure).

Read-only: nothing in the captures folder is changed. Results are for the scans named, never for
feet in general. Scans are personal data: the report goes to reports/, which is not committed.
"""

from __future__ import annotations

import argparse
import itertools
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from footscan import insole, server  # noqa: E402
from footscan.recon import compare, completeness, foot_prep  # noqa: E402
from footscan.recon.imported import load_geometry  # noqa: E402

FULL_LENGTH_BELOW_MM = 60.0  # the full length is read below this: the foot, not the trimmed shin's lid


def _full_length(placed) -> float:
    """The outline's length measured as completeness.measure measures it, but from everything below
    FULL_LENGTH_BELOW_MM instead of the insole's silhouette height."""
    poly = completeness._along_its_length(insole.silhouette(placed, height=FULL_LENGTH_BELOW_MM))
    _, y0, _, y1 = poly.bounds
    return float(y1 - y0)


def _profile(placed) -> dict:
    """Diagnostics for where the length goes: the outline's length below several heights, and the
    lowest point of the foot every 5 mm from the heel back to the toe tip (mm above the floor)."""
    V = np.asarray(placed.vertices)
    lengths = {}
    for h in (10, 20, 30, 45, 60):
        try:
            poly = completeness._along_its_length(insole.silhouette(placed, height=h))
            lengths[str(h)] = round(float(poly.bounds[3] - poly.bounds[1]), 1)
        except Exception:  # noqa: BLE001 - too little below that height
            lengths[str(h)] = None
    low = V[V[:, 2] < FULL_LENGTH_BELOW_MM]
    y0 = float(low[:, 1].min())
    bins = np.floor((low[:, 1] - y0) / 5.0).astype(int)
    prof = [round(float(low[bins == b, 2].min()), 1) for b in range(int(bins.max()) + 1) if (bins == b).any()]
    return dict(length_below_mm=lengths, lowest_every_5mm_from_heel=prof)


def measure_scan(folder: Path, meta: dict) -> tuple[dict, object]:
    kind = meta.get("scan_kind") or "foot"
    up = (meta.get("mesh") or {}).get("up", "y")
    mesh = load_geometry(folder / "mesh.ply")
    t0 = time.time()
    ins, placed = foot_prep.insole_from_object_capture(mesh, meta["foot"], up, kind=kind)
    info = ins.report["prep"]
    m = info.get("completeness") or completeness.measure(placed)
    sides = info.get("ball_sides_above_floor_mm")
    return dict(
        outline_length_mm=m["length_mm"], outline_width_mm=m["width_mm"],
        toe_end=m["toe_end"], heel_end=m["heel_end"], ball_at=m["ball_at"],
        full_length_mm=round(_full_length(placed), 1),
        toe_tip_above_floor_mm=m["toe_tip_above_floor_mm"],
        footprint_mm=info.get("footprint_mm"),
        heel_back_above_floor_mm=info.get("heel_back_above_floor_mm"),
        ball_roll_mm=round(abs(sides["plus_x"] - sides["minus_x"]), 1) if sides else None,
        ball_sides_above_floor_mm=sides,
        floor_corrected_deg=info.get("floor_corrected_deg"), floor_lifted_mm=info.get("floor_lifted_mm"),
        tipped_to_rest_deg=info.get("tipped_to_rest_deg"),
        surface_noise_mm=info.get("surface_noise_mm"),
        open_edges_near_floor_mm=info.get("open_edges_near_floor_mm"),
        two_feet=info.get("two_feet"),
        toes_laid_flat=info.get("toes_laid_flat"), toes_warning=info.get("toes_warning"),
        max_fill_mm=ins.report.get("max_fill_mm"),
        sole_seen=ins.report.get("sole", {}).get("seen"),
        warnings=ins.report["warnings"],
        **_profile(placed),
        seconds=round(time.time() - t0, 1),
    ), placed


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("captures", nargs="?", default=str(ROOT / "data" / "captures"))
    ap.add_argument("--json", help="write the results here (reports/ is not committed)")
    ap.add_argument("--md", help="write a markdown table here")
    ap.add_argument("--only", nargs="*", help="only captures whose id contains one of these")
    ap.add_argument("--no-repeat", action="store_true", help="skip the scan-against-scan comparisons")
    a = ap.parse_args(argv)
    captures = Path(a.captures)
    rows, placed = [], {}
    for meta in reversed(server.list_captures(captures)):  # oldest first
        cid = meta.get("capture_id", "")
        if meta.get("method") != "imported_mesh" or not (captures / cid / "mesh.ply").is_file():
            continue
        if a.only and not any(s in cid for s in a.only):
            continue
        row = dict(capture_id=cid, foot=meta.get("foot"), kind=meta.get("scan_kind") or "foot",
                   status=meta.get("status"))
        try:
            r, p = measure_scan(captures / cid, meta)
            row.update(r)
            placed[cid] = p
        except Exception as e:  # noqa: BLE001 - reported per scan
            row["error"] = f"{type(e).__name__}: {e}"
        rows.append(row)
        print(json.dumps(row), flush=True)

    ok = [r for r in rows if "error" not in r]
    pairs = []
    for x, y in itertools.combinations(ok, 2):
        if x["kind"] != y["kind"] or x["kind"] not in completeness.CHECKED_KINDS:
            continue
        pr = dict(a=x["capture_id"], b=y["capture_id"], kind=x["kind"], feet=[x["foot"], y["foot"]],
                  length_diff_mm=round(y["outline_length_mm"] - x["outline_length_mm"], 1),
                  width_diff_mm=round(y["outline_width_mm"] - x["outline_width_mm"], 1),
                  full_length_diff_mm=round(y["full_length_mm"] - x["full_length_mm"], 1))
        if x["foot"] == y["foot"] and not a.no_repeat:
            try:
                pr["repeat"] = compare.compare_prepared(placed[x["capture_id"]], placed[y["capture_id"]], x["foot"])
            except Exception as e:  # noqa: BLE001
                pr["repeat_error"] = f"{type(e).__name__}: {e}"
        pairs.append(pr)
        print(json.dumps(pr), flush=True)

    out = dict(scans=rows, pairs=pairs)
    if a.json:
        Path(a.json).parent.mkdir(parents=True, exist_ok=True)
        Path(a.json).write_text(json.dumps(out, indent=2))
    md = to_markdown(out)
    print(md)
    if a.md:
        Path(a.md).parent.mkdir(parents=True, exist_ok=True)
        Path(a.md).write_text(md)
    return 0


def _f(v, nd=1):
    return "-" if v is None else (f"{v:.{nd}f}" if isinstance(v, (int, float)) else str(v))


def to_markdown(out: dict) -> str:
    lines = ["| scan | foot | kind | outline L x W | full L | toe tip up | heel back up | ball roll | floor fix deg "
             "| noise | open edges | toe/heel end | warnings |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in out["scans"]:
        if "error" in r:
            lines.append(f"| {r['capture_id']} | {r['foot']} | {r['kind']} | error: {r['error'][:80]} |" + " |" * 9)
            continue
        lines.append(
            f"| {r['capture_id']} | {r['foot']} | {r['kind']} | {_f(r['outline_length_mm'])} x {_f(r['outline_width_mm'])} "
            f"| {_f(r['full_length_mm'])} | {_f(r['toe_tip_above_floor_mm'])} | {_f(r['heel_back_above_floor_mm'])} "
            f"| {_f(r['ball_roll_mm'])} | {_f(r['floor_corrected_deg'], 2)} | {_f(r['surface_noise_mm'], 2)} "
            f"| {_f(r['open_edges_near_floor_mm'], 0)} | {_f(r['toe_end'], 2)}/{_f(r['heel_end'], 2)} "
            f"| {len(r['warnings'])} |")
    if out["pairs"]:
        lines += ["", "| a | b | feet | outline L diff | W diff | full L diff | repeat typical / p95 | arch diff |",
                  "|---|---|---|---|---|---|---|---|"]
        for p in out["pairs"]:
            rep = p.get("repeat")
            lines.append(f"| {p['a']} | {p['b']} | {'/'.join(map(str, p['feet']))} | {_f(p['length_diff_mm'])} "
                         f"| {_f(p['width_diff_mm'])} | {_f(p['full_length_diff_mm'])} "
                         f"| {(_f(rep['typical_mm'], 2) + ' / ' + _f(rep['p95_mm'], 2)) if rep else p.get('repeat_error', '-')[:40]} "
                         f"| {_f(rep['arch_difference_mm'], 2) if rep else '-'} |")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
