"""Would the studio's completeness check (recon/completeness.py) refuse the sole scans already kept?

Reads every imported sole scan in the studio's captures folder, prepares it as Make insole does, and
prints its outline length, how square each end is, and what the check would say if the scans arrived
now, one after another, oldest first: the toes, the heel, what the preparation found missing, and the
length against the newest other scan of each foot taken before it that would have been kept. (The studio
itself compares with scans kept before the check on their own faults only, so for those its answer can differ.) Read-only: nothing in the captures folder is changed (the studio itself saves the measures
the first time it compares with a scan). Results are for the scans named, never for feet in general.

  .venv/bin/python scripts/check_completeness.py [data/captures] [--json reports/completeness.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from footscan import server  # noqa: E402
from footscan.recon import completeness  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("captures", nargs="?", default=str(ROOT / "data" / "captures"))
    ap.add_argument("--json", help="also write the results here (reports/ is not committed)")
    a = ap.parse_args(argv)
    captures = Path(a.captures)
    rows = []
    for meta in reversed(server.list_captures(captures)):  # oldest first, so each is compared with earlier ones
        if not server._checked(meta) or not (captures / meta["capture_id"] / "mesh.ply").is_file():
            continue
        row = dict(capture_id=meta["capture_id"], foot=meta["foot"], kind=meta["scan_kind"])
        try:
            m, info = server.scan_measures(captures / meta["capture_id"], meta)
        except Exception as e:  # noqa: BLE001 - reported per scan
            row["error"] = f"{type(e).__name__}: {e}"
            rows.append(row)
            continue
        own = completeness.problems(m) + completeness.from_prep(info)
        newest = {}
        for r in rows:  # earlier scans kept had each arrived in turn with the check on (refused ones deleted)
            if "measures" in r and not r["problems"]:
                newest[r["foot"]] = dict(foot=r["foot"], same_foot=r["foot"] == meta["foot"],
                                         capture_id=r["capture_id"], length_mm=r["measures"]["length_mm"])
        row.update(measures=m, own_problems=own,
                   problems=own + completeness.against_others(m, list(newest.values())))
        rows.append(row)
    for r in rows:
        if "error" in r:
            print(f"{r['capture_id']} ({r['foot']}, {r['kind']}): couldn't prepare: {r['error']}")
            continue
        m = r["measures"]
        verdict = "REFUSED" if r["problems"] else "kept"
        print(f"{r['capture_id']} ({r['foot']}, {r['kind']}): {m['length_mm']} x {m['width_mm']} mm, "
              f"toe end {m['toe_end']}, heel end {m['heel_end']}, toe tip {m['toe_tip_above_floor_mm']} mm up: {verdict}")
        for p in r["problems"]:
            print(f"    {p}")
    if a.json:
        Path(a.json).parent.mkdir(parents=True, exist_ok=True)
        Path(a.json).write_text(json.dumps(rows, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
