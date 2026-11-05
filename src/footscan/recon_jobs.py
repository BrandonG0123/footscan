"""Running Phase 2 from the studio: one reconstruction at a time, in its own process.

The web server stays standard-library only and never imports COLMAP or
MeshLab itself. A reconstruction is started as a separate
``footscan reconstruct <folder>`` process, writing progress to
``<folder>/recon/status.json`` and its output to ``<folder>/recon/log.txt``.
A crash there (or OpenMP's dislike of two copies of itself) can't take the
website down, and the studio just reads the files.

One at a time on purpose: dense reconstruction uses the whole CPU for
several minutes, and two at once would make both slower and the website
sluggish for the person scanning.
"""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

# Files the studio may download from a recon folder (nothing else is served).
RECON_FILES = {
    "mesh.ply": "model/ply",
    "mesh_raw.ply": "model/ply",
    "mesh_foot.ply": "model/ply",
    "plantar.ply": "model/ply",
    "points.ply": "model/ply",
    "report.json": "application/json",
    "accuracy.json": "application/json",
    "plantar.json": "application/json",
}
CALIPER_KEYS = ("length", "width", "base", "dome_apex", "terrace_high", "terrace_low")


class Busy(Exception):
    pass


def pid_alive(pid) -> bool:
    """Is a process with this id still running?"""
    if not isinstance(pid, int) or pid <= 0:
        return False
    if os.name == "nt":
        # On Windows os.kill(pid, 0) is not a harmless check: signal 0 is
        # CTRL_C_EVENT, which would interrupt the build. Ask Windows instead.
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION, STILL_ACTIVE = 0x1000, 259
        k32 = ctypes.windll.kernel32
        handle = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            return bool(k32.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == STILL_ACTIVE
        finally:
            k32.CloseHandle(handle)
    try:
        os.kill(pid, 0)  # signal 0: "does it exist?", sends nothing
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def validate_calipers(body: dict) -> dict:
    """Caliper readings of the printed calibration object, mm. Blank = not measured."""
    out = {}
    for k in CALIPER_KEYS:
        v = body.get(k)
        if v in (None, ""):
            continue
        v = float(v)
        if not math.isfinite(v) or not 1 <= v <= 300:
            raise ValueError(f"{k}: expected millimetres between 1 and 300")
        out[k] = round(v, 3)
    return out


class ReconRunner:
    def __init__(self, python: str = sys.executable):
        self.python = python
        self.proc: subprocess.Popen | None = None
        self.folder: Path | None = None
        self.lock = threading.Lock()

    def busy(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self, folder: Path, calibration_object: bool, accuracy_only: bool = False) -> None:
        with self.lock:
            if self.busy():
                raise Busy(f"another 3D model is being built ({self.folder.name}); try again when it finishes")
            st = folder / "recon" / "status.json"
            if st.exists():
                try:
                    cur = json.loads(st.read_text(encoding="utf-8"))
                except (ValueError, OSError):  # garbled, not UTF-8 (both ValueErrors), or gone meanwhile
                    cur = {}
                if cur.get("state") == "running" and pid_alive(cur.get("pid")):
                    raise Busy("this model is already being built")
            out = folder / "recon"
            out.mkdir(exist_ok=True)
            (out / "status.json").write_text(json.dumps(dict(stage="queued", state="running", at=time.time())), encoding="utf-8")
            if accuracy_only:
                cmd = [self.python, "-m", "footscan.cli", "accuracy", str(folder)]
                if (folder / "calipers.json").exists():
                    cmd += ["--calipers", str(folder / "calipers.json")]
            else:
                cmd = [self.python, "-m", "footscan.cli", "reconstruct", str(folder)]
            if calibration_object and not accuracy_only:
                cmd.append("--calibration-object")
                if (folder / "calipers.json").exists():
                    cmd += ["--calipers", str(folder / "calipers.json")]
            log = open(out / "log.txt", "wb")  # noqa: SIM115 - handed to the child process, which writes it
            # UTF-8 mode in the child, so what it prints and writes is UTF-8 on Windows too (its default there is
            # the ANSI code page, which can't write characters like the √ in a report and crashes)
            env = {**os.environ, "PYTHONUTF8": "1"}
            self.proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env=env)
            self.folder = folder
            log.close()


def summary(folder: Path, runner: ReconRunner | None = None) -> dict:
    """What the studio shows about a folder's reconstruction."""
    out = folder / "recon"
    if not (out / "status.json").exists():
        return dict(state="none")
    try:
        status = json.loads((out / "status.json").read_text(encoding="utf-8"))
    except (ValueError, OSError):  # garbled, not UTF-8 (both ValueErrors), or gone meanwhile
        return dict(state="running", stage="starting")  # being written this instant
    # A process that died without writing "done"/"failed" (killed, crashed).
    # The process id survives a restart of the web server; the runner doesn't.
    running_here = runner is not None and runner.busy() and runner.folder == folder
    if status.get("state") == "running" and not running_here and not pid_alive(status.get("pid")):
        status.update(state="failed", error="the reconstruction process stopped unexpectedly")
    elapsed = status.get("elapsed_s") or 0
    if status.get("state") == "running" and status.get("at"):
        elapsed += time.time() - status["at"]  # status is written per stage; count the time since
    res = dict(state=status.get("state"), stage=status.get("stage"), elapsed_s=round(elapsed),
               error=status.get("error"))
    if (out / "report.json").exists() and res["state"] != "running":
        try:
            r = json.loads((out / "report.json").read_text(encoding="utf-8"))
        except (ValueError, OSError):  # garbled, not UTF-8 (both ValueErrors), or gone meanwhile
            r = {}
        res.update(
            synthetic=r.get("synthetic"),
            seconds=r.get("seconds"),
            warnings=r.get("warnings", []),
            photos=r.get("inputs", {}).get("photos"),
            sfm={k: r["sfm"].get(k) for k in ("registered", "mean_reprojection_error_px", "colmap_version")} if "sfm" in r else None,
            scale={k: r["scale"].get(k) for k in ("residual_rms_mm", "mat_flatness_rms_mm", "corners_located",
                                                   "sheet_scale_disagreement_pct", "sheet_scale_disagreement_mm_per_250mm",
                                                   "seam_offset", "note")} if "scale" in r else None,
            mesh={k: r["mesh"].get(k) for k in ("final_faces", "surface_area_cm2", "points_meshed",
                                                 "decimation_max_deviation_mm")} if "mesh" in r else None,
            accuracy=r.get("accuracy"),
            plantar=r.get("plantar"),
        )
    if (out / "plantar.json").exists() and res["state"] == "done":
        p = json.loads((out / "plantar.json").read_text(encoding="utf-8"))
        res["medial_profile"] = p.get("medial_profile")
    if res["state"] == "failed" and (out / "log.txt").exists():
        res["log_tail"] = (out / "log.txt").read_text(encoding="utf-8", errors="replace")[-2000:]
    res["files"] = [f for f in RECON_FILES if (out / f).exists()] if res["state"] == "done" else []
    if (folder / "calipers.json").exists():
        res["calipers"] = json.loads((folder / "calipers.json").read_text(encoding="utf-8"))
    return res
