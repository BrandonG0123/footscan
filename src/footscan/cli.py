"""Command line entry point.

    footscan measure scans/*.json -o data/raw/scan_trials.csv
    footscan repeatability data/raw/*.csv -o reports/phase0.md \
        [--target ahi=0.02 --device-condition swb] [--scans-per-device 3]
    footscan serve [--host 0.0.0.0 --https] [--review]
    footscan review [--list | --watch]                    (checks + pictures for each new insole)
    footscan service [--system macos|linux|windows]       (start-at-boot file for an always-on computer)
    footscan calib-object -o calibration-object.stl
    footscan reconstruct data/captures/<id> [--calibration-object] [--calipers calipers.json]
    footscan export-measures -o data/raw/scan_trials.csv     (landmark picks -> repeatability input)
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from .measures import MEASURES, measure_scan
from .report import SAFETY_BANNER, build_report
from .repeatability import read_rows

FIELDS = ["foot", "condition", "source", "session", "capture_id", "pick", "load_kg", "measure", "value", "scan_id"]


def load_mesh(path: Path):
    import trimesh

    m = trimesh.load(path, force="mesh")
    return m.vertices, m.faces


def cmd_measure(args) -> int:
    rows, n_warn = [], 0
    for p in map(Path, args.scans):
        rec = json.loads(p.read_text())
        if rec.get("landmarks_used"):  # a studio pick: includes landmarks found from the surface (heel)
            rec = dict(rec, landmarks=rec["landmarks_used"])
        mesh = load_mesh(p.parent / rec["mesh"]) if rec.get("mesh") else None
        if mesh is not None and rec.get("support_plane"):
            from .landmarks import foot_surface

            mesh = foot_surface(mesh[0], mesh[1], rec["support_plane"], rec["landmarks"])
        values, warnings = measure_scan(rec, mesh)
        for w in warnings:
            print(f"[{p.name}] warning: {w}", file=sys.stderr)
            n_warn += 1
        for m in MEASURES:
            rows.append(dict(
                foot=rec["foot"], condition=rec["condition"], source=rec.get("source", "scan"),
                session=rec["session"], capture_id=rec["capture_id"], pick=rec.get("pick", 1),
                load_kg="" if rec.get("load_kg") is None else rec["load_kg"],
                measure=m, value="" if values[m] is None else values[m], scan_id=rec.get("scan_id", p.stem),
            ))
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} rows from {len(args.scans)} scans to {out} ({n_warn} warnings)")
    return 0


def cmd_repeatability(args) -> int:
    rows = read_rows(args.inputs)
    if not rows:
        print("no measurement rows with values found", file=sys.stderr)
        return 1
    targets = {}
    for t in args.target or []:
        k, _, v = t.partition("=")
        targets[k] = float(v)
    text = build_report(rows, targets, args.device_condition, args.scans_per_device, args.inputs)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text)
    print(SAFETY_BANNER)
    print(f"\nreport written to {out}")
    return 0


def cmd_mat(args) -> int:
    from .mat import write_static

    for path in write_static():
        print(f"wrote {path}")
    return 0


def cmd_calib_object(args) -> int:
    from .recon import calib

    info = calib.write_stl(args.output)
    print(f"wrote {info['path']}: {info['extents_mm']} mm, {info['faces']} triangles, {info['volume_cm3']} cm3")
    print("Print base-down at 100% scale, no supports. Then measure with calipers:")
    for c in calib.CALIPER_CHECKS:
        print(f"  {c.key:13s} {c.label} (model {c.nominal_mm:g} mm): {c.how}")
    return 0


def cmd_reconstruct(args) -> int:
    from .recon import pipeline

    calipers = json.loads(Path(args.calipers).read_text()) if args.calipers else None
    report = pipeline.reconstruct(args.capture, calibration_object=args.calibration_object or bool(calipers),
                                  calipers=calipers)
    print(SAFETY_BANNER)
    s = report["scale"]
    print(f"\nscale from the mat: residual {s['residual_rms_mm']} mm RMS over {s['corners_located']} corners; "
          f"sheets agree within {s.get('sheet_scale_disagreement_pct')}%")
    print(f"mesh: {report['mesh']['final_faces']:,} triangles -> {Path(args.capture) / 'recon' / 'mesh.ply'}")
    if "accuracy" in report:
        a = report["accuracy"]["surface_deviation"]
        print(f"accuracy vs calibration object: median {a['median_mm']} mm, 95th percentile {a['p95_mm']} mm, "
              f"signed mean {a['signed_mean_mm']} mm")
        if report.get("synthetic"):
            print("  (SYNTHETIC capture: this tests the code, not a real phone)")
    for w in report["warnings"]:
        print(f"warning: {w}")
    return 0


def cmd_accuracy(args) -> int:
    from .recon import pipeline

    calipers = json.loads(Path(args.calipers).read_text()) if args.calipers else None
    report = pipeline.recompute_accuracy(args.capture, calipers)
    a = report["accuracy"]["surface_deviation"]
    print(f"accuracy vs calibration object: median {a['median_mm']} mm, 95th percentile {a['p95_mm']} mm")
    return 0


def cmd_accuracy_mesh(args) -> int:
    from .recon import imported

    calipers = json.loads(Path(args.calipers).read_text()) if args.calipers else None
    try:
        mesh = imported.load_geometry(args.mesh)
    except ValueError as err:
        print(f"{args.mesh}: {err}", file=sys.stderr)
        return 1
    try:
        a = imported.evaluate_imported(mesh, up=args.up, calipers=calipers)
    except imported.NotTheObject as err:
        print(f"{args.mesh}: {err}", file=sys.stderr)
        return 1
    imp, reg, dev, comp = a["imported"], a["registration"], a["surface_deviation"], a["completeness"]
    print(f"{args.mesh}: {imp['units_detected']} -> mm, {'x'.join(str(v) for v in imp['extents_mm'])} mm, {args.up} up")
    print(f"  table: {imp['floor']}")
    print(f"  lined up: {100 * reg['scan_within_2mm']:.0f}% of the scan within 2 mm of the object")
    print(f"  surface: median {dev['median_mm']} mm, 95th percentile {dev['p95_mm']} mm, "
          f"signed mean {dev['signed_mean_mm']:+} mm")
    print(f"  coverage: {100 * comp['within_1mm']:.1f}% of the object within 1 mm, {100 * comp['within_2mm']:.1f}% within 2 mm")
    for r in a["dimensions"]:
        diff = "not measured" if r["scan_minus_reference_mm"] is None else f"{r['scan_minus_reference_mm']:+.2f} mm"
        print(f"  {r['label']}: {diff} (vs {r['reference']})")
    for w in a["warnings"]:
        print(f"  warning: {w}", file=sys.stderr)
    if args.output:
        Path(args.output).write_text(json.dumps(a, indent=2))
        print(f"report: {args.output}")
    return 0


def cmd_compare(args) -> int:
    import json

    from .recon import compare
    from .recon.imported import load_geometry

    r = compare.compare_scans(load_geometry(args.a), load_geometry(args.b), args.foot, args.kind, args.kind_b)
    print(compare.verdict(r))
    print(json.dumps(r, indent=2))
    return 0


def cmd_insole(args) -> int:
    from .insole import InsoleError, from_scan, write_outputs
    from .recon.imported import load_geometry, to_millimetres

    try:
        mesh, units, _ = to_millimetres(load_geometry(args.mesh))
        from .insole import InsoleParams

        params = None
        if args.shoe:
            from .recon import shoe

            outline, shoe_info = shoe.outline_from_scan(load_geometry(args.shoe), up=args.shoe_up)
            print(f"shoe's insole: {shoe_info['length_mm']} x {shoe_info['width_mm']} mm"
                  f"{' (on a table)' if shoe_info['table_found'] else ''}")
            params = InsoleParams(shoe_outline=shoe.as_param(outline), target_length_mm=args.length)
        elif args.length:
            params = InsoleParams(target_length_mm=args.length)
        ins = from_scan(mesh, args.foot, params)
    except (InsoleError, ValueError) as err:
        print(f"{args.mesh}: {err}", file=sys.stderr)
        return 1
    files = write_outputs(ins, Path(args.output), f"{args.foot}-insole", str(args.mesh))
    r = ins.report
    print(f"first-fit {args.foot} insole: {r['length_mm']} x {r['width_mm']} mm, {r['volume_cm3']} cm3, "
          f"highest fill {r['max_fill_mm']} mm (from {units})")
    print(f"  sole seen by the scan: {r['sole']['seen']:.0%} of the footprint, {r['sole']['seen_under_arch']:.0%} under the arch")
    print(f"  bed: {r['bed_fit']['how']}")
    for w in r["warnings"]:
        print(f"  warning: {w}", file=sys.stderr)
    for k, v in files.items():
        print(f"  {k}: {v}")
    print("NOT A MEDICAL DEVICE. No posting. Walking-only break-in; no sport until the summary sheet is signed.")
    return 0


def cmd_export_measures(args) -> int:
    from .landmarks import export_rows, list_picks

    folders = sorted(p.parent for p in (Path(args.data) / "captures").glob("*/capture.json"))
    rows = export_rows(folders)
    stale = sum(1 for f in folders for r in list_picks(f) if r.get("stale"))
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    picks = len({(r["capture_id"], r["pick"]) for r in rows})
    print(f"wrote {len(rows)} rows ({picks} picks) to {out}")
    if stale:
        print(f"skipped {stale} pick(s) made on a model that has since been rebuilt; re-pick them", file=sys.stderr)
    return 0


def cmd_serve(args) -> int:
    from .server import DATA_DIR, serve

    if args.review:
        import threading

        from . import review

        # Review packets for new insoles, alongside the studio (a daemon thread: it ends with the server)
        data = (Path(args.data) if args.data else DATA_DIR).resolve()
        threading.Thread(target=review.watch, args=(data,), kwargs=dict(log=lambda m: print(m, flush=True)),
                         daemon=True, name="review-packets").start()
    serve(args.host, args.port, args.https, args.public, data_dir=Path(args.data) if args.data else None,
          allow_indexing=True if args.allow_indexing else None)
    return 0


def cmd_review(args) -> int:
    import shlex
    import subprocess

    from . import review
    from .server import DATA_DIR

    data = (Path(args.data) if args.data else DATA_DIR).resolve()
    if args.list:
        todo = review.unreviewed(data)
        waiting = review.pending(data)
        if waiting:
            print(f"{len(waiting)} insole(s) have no review packet yet: run footscan review")
        for p in todo:
            print(f"insole waiting for review: {p / 'packet.md'}")
        if todo:
            print("To review them, ask Claude Code: /review-insole")
        return 0
    spec = review.load_spec(Path(args.spec) if args.spec else None)
    on_new = None
    if args.exec:
        # e.g. --exec 'claude -p "/review-insole {packet}"': {packet} is the new packet's folder, put in
        # after splitting, so a path with spaces or backslashes stays one argument. Split the shell's way
        # on every system (Windows' non-POSIX split would keep the quotes inside the prompt).
        def on_new(packet):
            cmd = [a.replace("{packet}", str(packet)) for a in shlex.split(args.exec)]
            subprocess.run(cmd, cwd=Path(__file__).resolve().parents[2], check=False)
    if args.watch:
        try:
            review.watch(data, args.interval, Path(args.spec) if args.spec else None, on_new=on_new)
        except KeyboardInterrupt:
            pass
        return 0
    made = review.run_once(data, spec)
    for p in made:
        if on_new:
            on_new(p)
    if not made:
        print("every current insole already has a review packet")
    return 0


def cmd_service(args) -> int:
    from . import service
    from .server import DATA_DIR

    system = args.system or service.this_system()
    root = Path(__file__).resolve().parents[2]
    try:
        r = service.render(system, root, Path(args.data).resolve() if args.data else DATA_DIR, args.port,
                           review=not args.no_review)
    except ValueError as err:
        print(f"footscan service: {err}", file=sys.stderr)
        return 1
    sys.stdout.write(r["content"])  # stdout is the file itself, so it can be redirected into place
    print(f"\n# footscan service for {system}" + (f": save the text above as {r['path']}" if r["path"] else ""),
          file=sys.stderr)
    for i, step in enumerate(r["steps"], 1):
        print(f"#  {i}. {step}", file=sys.stderr)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="footscan", description="Phase 0 foot measurement tools (not a medical device)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    m = sub.add_parser("measure", help="landmark JSON (+ mesh) -> long-format measurement CSV")
    m.add_argument("scans", nargs="+")
    m.add_argument("-o", "--output", required=True)
    m.set_defaults(func=cmd_measure)

    r = sub.add_parser("repeatability", help="measurement CSVs -> repeatability report")
    r.add_argument("inputs", nargs="+")
    r.add_argument("-o", "--output", required=True)
    r.add_argument("--target", action="append", metavar="MEASURE=VALUE",
                   help="intended correction, e.g. ahi=0.02 (repeatable)")
    r.add_argument("--device-condition", help="condition the device would be built from (for --target)")
    r.add_argument("--scans-per-device", type=int, default=1)
    r.set_defaults(func=cmd_repeatability)

    mt = sub.add_parser("mat", help="regenerate the printable scan mat PDFs and board definitions in web/mat/")
    mt.set_defaults(func=cmd_mat)

    co = sub.add_parser("calib-object", help="write the printable calibration object (STL) for the accuracy study")
    co.add_argument("-o", "--output", default="calibration-object.stl")
    co.set_defaults(func=cmd_calib_object)

    rc = sub.add_parser("reconstruct", help="photos on the mat -> mesh in millimetres (Phase 2)")
    rc.add_argument("capture", help="a capture folder (photos + capture.json)")
    rc.add_argument("--calibration-object", action="store_true",
                    help="the photos are of the printed calibration object: also run the accuracy study")
    rc.add_argument("--calipers", help="JSON of caliper measurements of the print, e.g. {\"length\": 149.9}")
    rc.set_defaults(func=cmd_reconstruct)

    ac = sub.add_parser("accuracy", help="redo only the accuracy study of a built calibration-object model")
    ac.add_argument("capture")
    ac.add_argument("--calipers", help="JSON of caliper measurements of the print")
    ac.set_defaults(func=cmd_accuracy)

    am = sub.add_parser("accuracy-mesh",
                        help="accuracy study for a calibration-object model made by another app "
                             "(e.g. the footscan capture iPhone app's Object Capture model)")
    am.add_argument("mesh", help="OBJ, PLY, STL or GLB; metres, centimetres or millimetres (detected from its size)")
    am.add_argument("--up", choices=["y", "z"], default="y",
                    help="which axis points up in the file (Object Capture and most phone apps: y)")
    am.add_argument("--calipers", help="JSON of caliper measurements of the print")
    am.add_argument("-o", "--output", help="write the full report as JSON")
    am.set_defaults(func=cmd_accuracy_mesh)

    ins = sub.add_parser("insole", help="first-fit insole (3MF + STL + clinician summary sheet) from a foot scan on the mat")
    ins.add_argument("mesh", help="foot scan in the mat frame (z up, floor at z = 0): mm, cm or m")
    ins.add_argument("--foot", choices=["left", "right"], required=True)
    ins.add_argument("-o", "--output", required=True, help="folder for the files")
    ins.add_argument("--length", type=float, help="the shoe's insole length, mm: the front is lengthened to it "
                                                   "(the shape under the heel, arch and ball unchanged)")
    ins.add_argument("--shoe", help="a scan of the shoe's own insole lying flat (as the iPhone app hands it over): "
                                    "the insole takes its outline, fitted round the foot")
    ins.add_argument("--shoe-up", default="y", choices=["y", "z"], help="the shoe scan's up axis (default y)")
    ins.set_defaults(func=cmd_insole)

    cp = sub.add_parser("compare", help="how much two scans of the same foot agree (repeatability)")
    cp.add_argument("a", help="first scan (as the iPhone app hands it over: OBJ/PLY, metres, Y up)")
    cp.add_argument("b", help="second scan")
    cp.add_argument("--foot", choices=["left", "right"], required=True)
    cp.add_argument("--kind", default="sole_up", choices=["foot", "sole_up", "sole_hanging", "impression"],
                    help="what kind of scan a is (and b, unless --kind-b)")
    cp.add_argument("--kind-b", choices=["foot", "sole_up", "sole_hanging", "impression"])
    cp.set_defaults(func=cmd_compare)

    ex = sub.add_parser("export-measures", help="landmark picks of research captures -> repeatability CSV")
    ex.add_argument("--data", default="data", help="data folder (default: data/)")
    ex.add_argument("-o", "--output", required=True)
    ex.set_defaults(func=cmd_export_measures)

    sv = sub.add_parser("serve", help="run the local website (capture, library, break-in tracker)")
    sv.add_argument("--host", default="127.0.0.1", help="use 0.0.0.0 to reach it from your phone")
    sv.add_argument("--port", type=int, default=8765)
    sv.add_argument("--https", action="store_true", help="self-signed HTTPS (phones require it for camera access)")
    sv.add_argument("--public", action="store_true",
                    help="behind a tunnel or proxy on the internet: trust nothing as local; studio needs the key")
    sv.add_argument("--data", help="data folder (default: data/). A separate folder keeps demos and tests "
                                   "out of your real library")
    sv.add_argument("--allow-indexing", action="store_true",
                    help="let search engines index the site (with --public it is hidden from them by default)")
    sv.add_argument("--review", action="store_true",
                    help="also write a review packet (checks + pictures) for each new insole: footscan review")
    sv.set_defaults(func=cmd_serve)

    rv = sub.add_parser("review", help="review packets for new insoles: plain checks + pictures, for a person or "
                                       "Claude Code to look over before slicing (docs/ALWAYS-ON.md)")
    rv.add_argument("--data", help="data folder (default: data/)")
    rv.add_argument("--spec", help="the shoe to check against (default: review-spec.json)")
    rv.add_argument("--list", action="store_true", help="only list packets nobody has answered yet")
    rv.add_argument("--watch", action="store_true", help="keep looking for new insoles")
    rv.add_argument("--interval", type=float, default=20.0, help="seconds between looks (--watch)")
    rv.add_argument("--exec", help="command to run after each new packet; {packet} is its folder")
    rv.set_defaults(func=cmd_review)

    sc = sub.add_parser("service", help="print the start-at-boot file for an always-on computer (installs nothing)")
    sc.add_argument("--system", choices=["macos", "linux", "windows"], help="default: this computer's")
    sc.add_argument("--data", help="data folder (default: data/)")
    sc.add_argument("--port", type=int, default=8765)
    sc.add_argument("--no-review", action="store_true", help="leave out --review")
    sc.set_defaults(func=cmd_service)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
