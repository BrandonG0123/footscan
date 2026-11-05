"""Run Phase 2 on one capture folder and write everything to <capture>/recon/.

    footscan reconstruct data/captures/<id> [--calibration-object] [--calipers calipers.json]

Outputs (all in millimetres, mat frame unless noted):

    report.json       every number below, every setting, software versions, warnings
    colmap/           COLMAP's database and sparse model (model units)
    sparse_mm/        the same sparse model moved into the mat frame
    points.ply        the fused dense point cloud
    floor.npy         dense points on the paper (for the accuracy study's table top)
    (the surface step runs in its own process: see in_clean_process)
    mesh_raw.ply      Poisson surface, cut at the floor and trimmed to the data
    mesh.ply          after hole filling, Taubin smoothing and decimation (the result), coloured
    viewer.bin        the same mesh in a compact form for the studio's 3-D viewer
    accuracy.json     calibration-object captures only: scan vs. model
    mesh_foot.ply     foot scans standing on the mat: the mesh in the (provisional) foot frame
    plantar.ply       ... its downward-facing underside (arch), foot frame
    plantar.json      ... frame, footprint size and outline, medial arch profile
    status.json       progress while running (the studio reads it)

Warnings never stop the run; they say which numbers to distrust, in plain
words, and the studio shows them next to the result.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import threading
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import accuracy, dense, markers, mesh, plantar, scale, sfm, viewer_data

# Thresholds for warnings (not failures).
WARN_REGISTERED_FRACTION = 0.8
WARN_REPROJECTION_PX = 1.0
WARN_SCALE_RESIDUAL_MM = 1.0
WARN_SHEET_DISAGREEMENT_PCT = 0.3


@dataclass
class Settings:
    sfm: sfm.SfmConfig = field(default_factory=sfm.SfmConfig)
    dense: dense.DenseConfig = field(default_factory=dense.DenseConfig)
    mesh: mesh.MeshConfig = field(default_factory=mesh.MeshConfig)


# Everything a build writes into recon/ (log.txt and status.json belong to the run that's starting).
OUTPUTS = ("report.json", "accuracy.json", "plantar.json", "mesh.ply", "mesh_raw.ply", "mesh_foot.ply",
           "plantar.ply", "points.ply", "viewer.bin", "floor.npy", "dense.npz")


def clear_outputs(out: Path) -> None:
    import shutil

    for name in OUTPUTS:
        (out / name).unlink(missing_ok=True)
    for d in ("sparse_mm", "images", "colmap"):
        shutil.rmtree(out / d, ignore_errors=True)


def write_json_atomic(path: Path, obj) -> None:
    """Write to a temporary file, then rename over the target: a reader sees the old or the new file, never half."""
    from ..atomic import replace

    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(obj, indent=1, default=_json_default), encoding="utf-8")
    try:
        replace(tmp, path)  # tried again for a moment while a reader has it open (Windows)
    finally:
        tmp.unlink(missing_ok=True)


def frame_names(capture_dir: Path) -> tuple[list[str], dict]:
    meta_path = capture_dir / "capture.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    frames = meta.get("frames")
    if frames:
        names = [f["file"] for f in frames if not f.get("excluded") and (capture_dir / f["file"]).exists()]
    else:
        names = sorted(p.name for p in capture_dir.glob("*.jpg"))
    return names, meta


def link_or_copy(src: Path, dst: Path) -> None:
    """A second name for a photo without copying it, where the system allows.

    Symbolic links need administrator rights on Windows; hard links don't
    (same drive), and a copy always works.
    """
    import shutil

    try:
        os.symlink(os.path.relpath(src, dst.parent), dst)
        return
    except OSError:
        pass
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def stage_images(capture_dir: Path, names: list[str], out: Path) -> tuple[Path, list[str], dict]:
    """Put every photo the right way up in <recon>/images/ (links, or rotated copies).

    One camera means one image size. A phone turned sideways mid-scan saves
    a landscape frame among portrait ones; COLMAP's single-camera mode would
    silently drop it. Turning the picture back 90 degrees is exact: it is the
    same lens with the phone rolled a quarter-turn, which the camera solving
    handles like any other tilt. Frames of any other size are left out and
    listed.
    """
    import os
    from collections import Counter

    import cv2

    staged = out / "images"
    if staged.exists():
        for p in staged.iterdir():
            p.unlink()
    staged.mkdir(parents=True, exist_ok=True)
    sizes = {}
    for n in names:
        img = cv2.imread(str(capture_dir / n), cv2.IMREAD_REDUCED_GRAYSCALE_8)
        if img is None:
            continue
        sizes[n] = (img.shape[1], img.shape[0])  # an eighth-size decode: enough to compare sizes, 64x faster
    if not sizes:
        raise RuntimeError("none of the photos could be read")
    main = Counter(sizes.values()).most_common(1)[0][0]
    kept, rotated, excluded = [], [], []
    for n in names:
        sz = sizes.get(n)
        if sz == main:
            link_or_copy(capture_dir / n, staged / n)
            kept.append(n)
        elif sz == (main[1], main[0]):
            img = cv2.imread(str(capture_dir / n), cv2.IMREAD_COLOR)
            cv2.imwrite(str(staged / n), cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE), [cv2.IMWRITE_JPEG_QUALITY, 97])
            kept.append(n)
            rotated.append(n)
        else:
            excluded.append(n)
    return staged, kept, dict(rotated=rotated, excluded=excluded)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _versions() -> dict:
    # Read installed versions without importing (importing MeshLab here would
    # load its OpenMP next to COLMAP's; see in_clean_process).
    from importlib.metadata import PackageNotFoundError, version

    def v(name):
        try:
            return version(name)
        except PackageNotFoundError:
            return None

    return dict(python=platform.python_version(), numpy=v("numpy"), scipy=v("scipy"),
                opencv=v("opencv-python-headless") or v("opencv-python"), pycolmap=v("pycolmap"),
                trimesh=v("trimesh"), pymeshlab=v("pymeshlab"), machine=platform.machine())


def write_ply_points(path: Path, P: np.ndarray, C: np.ndarray | None = None) -> None:
    import trimesh

    if C is None:
        colors = None
    else:
        C = np.asarray(C)
        C = np.repeat(C[:, None], 3, 1) if C.ndim == 1 else C
        colors = (np.clip(C, 0, 1) * 255).astype(np.uint8)
    trimesh.PointCloud(P, colors=colors).export(path)


def reconstruct(capture_dir, *, calibration_object: bool = False, calipers: dict | None = None,
                settings: Settings | None = None, log=print) -> dict:
    import pycolmap

    capture_dir = Path(capture_dir)
    settings = settings or Settings()
    out = capture_dir / "recon"
    out.mkdir(exist_ok=True)
    clear_outputs(out)  # nothing from an earlier build may be mistaken for this one's
    t_start = time.time()

    def status(stage: str, state: str = "running", **extra):
        write_json_atomic(out / "status.json", dict(stage=stage, state=state, at=time.time(), pid=os.getpid(),
                                                    elapsed_s=round(time.time() - t_start, 1), **extra))
        log(f"[{stage}]")

    report: dict = dict(capture=capture_dir.name, not_a_medical_device=True,
                        started=time.strftime("%Y-%m-%dT%H:%M:%S"), warnings=[])
    warn = report["warnings"].append
    status("starting")
    try:
        names, meta = frame_names(capture_dir)
        report.update(synthetic=bool(meta.get("synthetic")), versions=_versions(),
                      inputs=dict(photos=len(names), sha256={n: _sha256(capture_dir / n) for n in names}))
        if len(names) < 10:
            raise RuntimeError(f"only {len(names)} photos; at least 10 are needed (60+ is normal)")
        recorded = meta.get("mat_paper") or (meta.get("summary") or {}).get("mat_paper")
        paper = recorded if recorded in ("letter", "a4") else None
        paper = paper or markers.guess_paper(capture_dir, names)
        if paper is None:
            raise RuntimeError("no scan-mat markers found in the photos; this capture can't be put in millimetres")
        report["paper"] = paper
        board = markers.load_board(paper)

        image_dir, names, staging = stage_images(capture_dir, names, out)
        report["images"] = staging
        if staging["rotated"]:
            warn(f"{len(staging['rotated'])} photo(s) were taken with the phone turned sideways; turned upright and used")
        if staging["excluded"]:
            warn(f"{len(staging['excluded'])} photo(s) of a different size were left out: {', '.join(staging['excluded'])}")

        status("cameras")
        sres = sfm.run(image_dir, names, out / "colmap", settings.sfm, log=log)
        report["sfm"] = sres.report
        rec = sres.reconstruction
        if sres.report["registered"] < WARN_REGISTERED_FRACTION * len(names):
            warn(f"only {sres.report['registered']} of {len(names)} photos could be placed; parts of the "
                 "subject may be missing or less accurate")
        if sres.report["mean_reprojection_error_px"] > WARN_REPROJECTION_PX:
            warn(f"camera solution is loose (reprojection error {sres.report['mean_reprojection_error_px']} px); "
                 "blurry photos are the usual cause")
        report["warnings"].extend(sres.report.get("warnings", []))

        status("scale")
        registered = sorted(img.name for img in rec.images.values() if img.has_pose)
        dets = markers.detect_images(image_dir, registered, paper)
        sc = scale.recover(rec, dets, board)
        report["scale"] = sc.report
        if sc.report["residual_rms_mm"] > WARN_SCALE_RESIDUAL_MM:
            warn(f"mat corners fit their printed positions only to {sc.report['residual_rms_mm']} mm RMS; "
                 "the mat may not have been flat, or the print was not at 100%")
        dis = sc.report.get("sheet_scale_disagreement_pct")
        if dis is not None and dis > WARN_SHEET_DISAGREEMENT_PCT:
            warn(f"the two mat sheets disagree on scale by {dis}%; check both sheets were printed at 100%")
        if dis is None:
            warn("only one mat sheet was seen well enough, so the scale has no independent check")
        rec.transform(pycolmap.Sim3d(sc.scale, pycolmap.Rotation3d(sc.R), sc.t))
        (out / "sparse_mm").mkdir(exist_ok=True)
        rec.write(str(out / "sparse_mm"))

        status("depth")
        P, V, C, drep = dense.run(rec, image_dir, board, settings.dense, log=log)
        report["dense"] = drep
        if drep.get("box_from", "").startswith("mat area"):
            warn("the surface had very little texture for the camera to lock onto, so the whole mat area was "
                 "searched; expect a slower build and a patchier surface")
        write_ply_points(out / "points.ply", P, C)

        status("surface")
        np.savez(out / "dense.npz", P=P, V=V, C=C)
        report["mesh"] = in_clean_process(_surface_job, str(out), settings.mesh)

        if calibration_object:
            status("accuracy")
            acc = _accuracy(out, calipers, report["synthetic"])
            report["accuracy"] = _accuracy_summary(acc)
            report["warnings"].extend(acc["warnings"])
        (out / "dense.npz").unlink(missing_ok=True)

        foot, condition = meta.get("foot"), meta.get("condition")
        if foot in ("left", "right") and condition in ("swb", "fwb"):
            status("foot frame")
            res = plantar.run(_load(out / "mesh.ply"), foot)
            res["foot_mesh"].export(out / "mesh_foot.ply")
            res["plantar"].export(out / "plantar.ply")
            (out / "plantar.json").write_text(json.dumps(
                dict(**res["summary"], outline_mm=res["outline"].round(2).tolist()), indent=1), encoding="utf-8")
            report["plantar"] = {k: v for k, v in res["summary"].items() if k != "medial_profile"}
            report["warnings"].extend(res["summary"]["notes"])
        elif foot in ("left", "right"):
            report["plantar"] = dict(skipped=f"'{condition}' scans have no floor under the foot; the foot frame "
                                     "comes from landmarks in Phase 3")

        report["seconds"] = round(time.time() - t_start, 1)
        report["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        write_json_atomic(out / "report.json", report)
        status("done", "done", seconds=report["seconds"])
        return report
    except Exception as e:
        report["error"] = str(e)
        report["traceback"] = traceback.format_exc()
        write_json_atomic(out / "report.json", report)
        status("failed", "failed", error=str(e))
        raise
    finally:
        (out / "dense.npz").unlink(missing_ok=True)


def _accuracy(out: Path, calipers: dict | None, synthetic: bool) -> dict:
    floor = np.load(out / "floor.npy")
    acc = accuracy.evaluate(_load(out / "mesh.ply"), floor, calipers)
    acc["before_smoothing"] = accuracy.evaluate(_load(out / "mesh_raw.ply"), floor, calipers)["surface_deviation"]
    acc["synthetic"] = synthetic
    acc["calipers"] = calipers
    write_json_atomic(out / "accuracy.json", acc)
    return acc


def _accuracy_summary(acc: dict) -> dict:
    return {k: acc[k] for k in ("surface_deviation", "completeness", "dimensions", "registration",
                                "before_smoothing", "warnings")}


def recompute_accuracy(capture_dir, calipers: dict | None, log=print) -> dict:
    """Redo only the accuracy study on an existing model (e.g. after entering caliper readings).

    Seconds instead of a full rebuild: the surface doesn't change, only what
    it is compared against. Refuses if the last build didn't finish, so a
    stale surface is never scored as if it were current.
    """
    out = Path(capture_dir) / "recon"
    t0 = time.time()

    def status(stage, state, **extra):
        write_json_atomic(out / "status.json", dict(stage=stage, state=state, at=time.time(), pid=os.getpid(), **extra))

    status("accuracy", "running")
    try:
        report = json.loads((out / "report.json").read_text(encoding="utf-8"))
        if report.get("error") or not (out / "mesh.ply").exists():
            raise RuntimeError("the last build didn't finish; rebuild the model first")
        acc = _accuracy(out, calipers, bool(report.get("synthetic")))
    except Exception as e:
        status("failed", "failed", error=str(e))
        raise
    old = set(report.get("accuracy", {}).get("warnings", []))
    report["warnings"] = [w for w in report.get("warnings", []) if w not in old] + acc["warnings"]
    report["accuracy"] = _accuracy_summary(acc)
    report["accuracy_recomputed"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    write_json_atomic(out / "report.json", report)
    status("done", "done", elapsed_s=round(time.time() - t0, 1), seconds=report.get("seconds"))
    log(f"accuracy recomputed with calipers: {sorted(calipers or {})}")
    return report


def _load(path: Path):
    import trimesh

    return trimesh.load(path, force="mesh", process=False)


def _surface_job(out_dir: str, cfg) -> dict:
    """Runs in a separate process: points -> mesh files. Returns the mesh report."""
    out = Path(out_dir)
    z = np.load(out / "dense.npz")
    final, stages, floor, rep = mesh.run(z["P"], z["V"], cfg)
    np.save(out / "floor.npy", floor.astype(np.float32))
    stages["trimmed"].export(out / "mesh_raw.ply")
    if "C" in z.files:
        mesh.color_vertices(final, z["P"], z["C"])
    final.export(out / "mesh.ply")
    viewer_data.write(final, out / "viewer.bin")
    return rep


def in_clean_process(fn, *args):
    """Run fn(*args) in a fresh Python process and return its result.

    COLMAP and MeshLab each ship their own copy of the OpenMP threading
    library; loading both into one process makes OpenMP abort. So the
    surface step runs in a brand-new interpreter that never imports COLMAP.

    It is started as ``python -m footscan.recon.pipeline <module> <function>``
    rather than with multiprocessing, whose "spawn" start re-runs the
    caller's main script in the child: harmless for ``footscan reconstruct``,
    but any script without an ``if __name__ == "__main__"`` guard would
    start a second reconstruction inside the child and crash it.
    Arguments and result travel as pickles in temporary files.
    """
    import pickle
    import subprocess
    import sys
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        arg_file, res_file = Path(tmp) / "args.pkl", Path(tmp) / "result.pkl"
        arg_file.write_bytes(pickle.dumps((fn.__module__, fn.__name__, args)))
        proc = subprocess.run([sys.executable, "-m", "footscan.recon.pipeline", str(arg_file), str(res_file)],
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                              encoding="utf-8", errors="replace")  # native libraries print in any encoding
        if proc.returncode != 0 or not res_file.exists():
            tail = (proc.stdout or "")[-1500:]
            raise RuntimeError(f"the surface step stopped (exit {proc.returncode}):\n{tail}")
        ok, value = pickle.loads(res_file.read_bytes())
    if not ok:
        raise RuntimeError(value)
    return value


def _child_main(arg_file: str, res_file: str) -> None:
    import importlib
    import pickle

    module, name, args = pickle.loads(Path(arg_file).read_bytes())
    try:
        result = (True, getattr(importlib.import_module(module), name)(*args))
    except Exception:  # noqa: BLE001 - reported to the parent with its traceback
        result = (False, traceback.format_exc())
    Path(res_file).write_bytes(pickle.dumps(result))


def _json_default(o):
    if isinstance(o, np.generic):
        return o.item()
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, tuple):
        return list(o)
    raise TypeError(type(o).__name__)


if __name__ == "__main__":
    import sys

    _child_main(sys.argv[1], sys.argv[2])
