"""Phase 3: landmarks clicked on a 3-D scan, saved with it, and turned into measurements.

The studio's viewer (web/studio/landmarks.html) shows the reconstructed
surface; you click each landmark on the skin-marker sticker you placed
(docs/phase0-protocol.md, section 3). Each complete set of clicks is a
**pick**. Picks are saved in the same JSON format ``footscan measure``
already reads (data/templates/scan_landmarks.json), so a pick is a Phase 0
scan record:

    <capture>/landmarks/pick-<n>.json

Re-picking the same scan (pick 2, 3...) without seeing the earlier clicks
is what lets the repeatability study separate *picking* error from
*capture* error, so the viewer hides earlier picks while you pick.

Coordinates are the mesh's own: for reconstructed scans that is the mat
frame (mm, z up from the paper), which also gives the floor under a
standing foot exactly. Imported LiDAR meshes have no mat, so for standing
scans you click three points on the floor beside the foot instead.

Each pick records the SHA-256 of the mesh it was clicked on. If the scan is
rebuilt, the landmarks no longer sit exactly on the new surface; the pick is
marked stale rather than silently reused.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from pathlib import Path

import numpy as np

from .measures import MEASURES, measure_scan

# key, label, where (from the protocol), which conditions it applies to,
# and which way to look at the foot to see it (the viewer turns there).
LANDMARKS = [
    dict(key="navicular_tuberosity", label="Navicular", view="medial",
         where="Most prominent point of the navicular tuberosity, inner side of the foot."),
    dict(key="mtpj1_medial", label="1st MTP joint", view="medial",
         where="Inner prominence of the big-toe joint (1st metatarsophalangeal joint)."),
    dict(key="mtpj5_lateral", label="5th MTP joint", view="lateral",
         where="Outer prominence of the little-toe joint (5th metatarsophalangeal joint)."),
    dict(key="malleolus_medial", label="Inner ankle bone", view="medial",
         where="Most prominent point of the medial malleolus."),
    dict(key="malleolus_lateral", label="Outer ankle bone", view="lateral",
         where="Most prominent point of the lateral malleolus."),
    dict(key="calc_bisect_distal", label="Heel line, lower dot", view="posterior",
         where="Lower dot of the heel bisection line, just above the heel pad."),
    dict(key="calc_bisect_proximal", label="Heel line, upper dot", view="posterior",
         where="Upper dot of the heel bisection line, just below the Achilles insertion."),
    dict(key="leg_bisect_distal", label="Leg line, lower dot", view="posterior",
         where="Lower dot of the lower-leg bisection line, just above the ankle bones."),
    dict(key="leg_bisect_proximal", label="Leg line, upper dot", view="posterior",
         where="Upper dot of the lower-leg bisection line, about 15 cm up."),
    dict(key="calc_plantar", label="Under the heel", view="plantar", conditions=("nwb", "nwb_relaxed"),
         where="Sole, under the calcaneal tuberosity (centre of the heel)."),
    dict(key="mth1_plantar", label="Under 1st met head", view="plantar", conditions=("nwb", "nwb_relaxed"),
         where="Sole, under the 1st metatarsal head."),
    dict(key="mth5_plantar", label="Under 5th met head", view="plantar", conditions=("nwb", "nwb_relaxed"),
         where="Sole, under the 5th metatarsal head."),
    dict(key="heel_posterior", label="Back of the heel", view="posterior", optional=True,
         where="Rearmost point of the heel. Leave it and it is found from the surface."),
    dict(key="floor_a", label="Floor point A", view="top", floor=True,
         where="Any point on the floor beside the foot (imported scans only: there is no mat)."),
    dict(key="floor_b", label="Floor point B", view="top", floor=True,
         where="A second floor point, well away from A."),
    dict(key="floor_c", label="Floor point C", view="top", floor=True,
         where="A third floor point, not in line with A and B."),
]
KEYS = {lm["key"] for lm in LANDMARKS}
FLOOR_KEYS = ("floor_a", "floor_b", "floor_c")
STANDING = ("swb", "fwb")
MAT_PLANE = {"point": [0.0, 0.0, 0.0], "normal": [0.0, 0.0, 1.0]}


class LandmarkError(ValueError):
    pass


def spec(condition: str, in_mat_frame: bool) -> list[dict]:
    """The landmarks to click for this scan, in order."""
    out = []
    for lm in LANDMARKS:
        if "conditions" in lm and condition not in lm["conditions"]:
            continue
        if lm.get("floor") and (in_mat_frame or condition not in STANDING):
            continue
        out.append({k: v for k, v in lm.items() if k != "conditions"})
    return out


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def support_plane(condition: str, landmarks: dict, in_mat_frame: bool) -> dict | None:
    """The floor under a standing foot: the mat, or three clicked floor points."""
    if condition not in STANDING:
        return None
    if in_mat_frame:
        return dict(MAT_PLANE)
    pts = [landmarks.get(k) for k in FLOOR_KEYS]
    if any(p is None for p in pts):
        return None
    a, b, c = (np.asarray(p, float) for p in pts)
    n = np.cross(b - a, c - a)
    if np.linalg.norm(n) < 1e-6:
        raise LandmarkError("the three floor points are in a line; spread them out")
    n /= np.linalg.norm(n)
    # The order of the clicks decides which way the cross product points.
    # "Up" is toward the foot: flip if the ankle bones are below the plane.
    above = [np.asarray(landmarks[k], float) for k in ("malleolus_medial", "malleolus_lateral", "navicular_tuberosity")
             if landmarks.get(k) is not None]
    if above and np.mean([(p - a) @ n for p in above]) < 0:
        n = -n
    return {"point": a.tolist(), "normal": n.tolist()}


def auto_heel_posterior(V: np.ndarray, lm: dict, plane: dict | None, foot: str) -> list[float] | None:
    """Rearmost point of the heel, found from the surface.

    "Rearmost" needs a forward direction, and the forward direction needs
    the heel: so iterate. Start from the point under the ankle bones, take
    forward = from there toward the midpoint of the 1st and 5th MTP joints
    (flattened onto the floor), find the surface point farthest backward
    among those below the ankle bones, and repeat from it until it stops
    moving.

    "Up" comes from the floor, or for a scan without one, from the sole's
    three landmarks (under the heel, 1st and 5th met heads), turned to point
    toward the ankle bones. With neither, there is no trustworthy "below
    the ankle" and the heel must be clicked.
    """
    need = ("mtpj1_medial", "mtpj5_lateral")
    if any(k not in lm for k in need):
        return None
    mall = [np.asarray(lm[k], float) for k in ("malleolus_medial", "malleolus_lateral") if k in lm]
    if not mall:
        return None
    if plane:
        up = np.asarray(plane["normal"], float)
    elif all(k in lm for k in ("calc_plantar", "mth1_plantar", "mth5_plantar")):
        a, b, c = (np.asarray(lm[k], float) for k in ("calc_plantar", "mth1_plantar", "mth5_plantar"))
        up = np.cross(b - a, c - a)
        if np.linalg.norm(up) < 1e-9:
            return None
        up /= np.linalg.norm(up)
    else:
        return None
    if (np.mean(mall, 0) - np.asarray(lm["mtpj1_medial"], float)) @ up < 0:
        up = -up  # ankle bones are above the foot
    fore = (np.asarray(lm["mtpj1_medial"], float) + np.asarray(lm["mtpj5_lateral"], float)) / 2
    heel = np.mean(mall, 0)
    ceiling = min(float(p @ up) for p in mall)
    low = V[V @ up < ceiling]
    if len(low) == 0:
        return None
    for _ in range(10):
        f = fore - heel
        f -= (f @ up) * up
        f /= np.linalg.norm(f)
        new = low[np.argmin(low @ f)]
        if np.linalg.norm(new - heel) < 0.01:
            break
        heel = new
    return [round(float(v), 3) for v in heel]


def validate(body: dict, condition: str, bounds: np.ndarray) -> dict:
    """{key: [x, y, z]} with known keys and points on (or near) the scan."""
    raw = body.get("landmarks")
    if not isinstance(raw, dict):
        raise LandmarkError("landmarks: expected an object of {name: [x, y, z]}")
    lo, hi = bounds[0] - 20, bounds[1] + 20
    out = {}
    for k, v in raw.items():
        if k not in KEYS:
            raise LandmarkError(f"unknown landmark {k!r}")
        if v is None:
            continue
        if not (isinstance(v, list) and len(v) == 3
                and all(isinstance(x, (int, float)) and not isinstance(x, bool) and abs(x) < 1e6 and math.isfinite(x)
                        for x in v)):
            raise LandmarkError(f"{k}: expected [x, y, z] in millimetres")
        if not np.all((np.asarray(v) >= lo) & (np.asarray(v) <= hi)):
            raise LandmarkError(f"{k}: not on the scan")
        out[k] = [round(float(x), 3) for x in v]
    return out


FLOOR_CLEARANCE_MM = 2.0


def foot_surface(V: np.ndarray, F: np.ndarray, plane: dict | None, landmarks: dict) -> tuple[np.ndarray, np.ndarray]:
    """The foot (and leg) on its own, without the floor it stands on.

    An imported LiDAR scan includes the floor, and every measurement that
    looks for an extreme ("rearmost point", "longest toe") would find the
    floor's edge instead (a 240 mm test foot measured 558 mm). So: drop the
    triangles lying within FLOOR_CLEARANCE_MM of the floor, then keep only
    the connected pieces of surface that carry a clicked landmark. That
    removes the floor and any bumps of floor noise that survive the height
    cut. The few millimetres of foot right at the floor go too; the heel's
    rearmost point and the toe tip sit well above that.
    """
    import trimesh

    if plane is None:
        return V, F
    p0, n = np.asarray(plane["point"], float), np.asarray(plane["normal"], float)
    centres = V[F].mean(1)
    above = (centres - p0) @ n > FLOOR_CLEARANCE_MM
    F2 = F[above]
    if len(F2) == 0:
        return V, F
    labels = trimesh.graph.connected_component_labels(trimesh.Trimesh(V, F2, process=False).face_adjacency,
                                                      node_count=len(F2))
    pts = [np.asarray(v, float) for k, v in landmarks.items() if k not in FLOOR_KEYS and v is not None]
    if pts:
        from scipy.spatial import cKDTree

        _, near = cKDTree(V[F2].mean(1)).query(np.array(pts))
        F2 = F2[np.isin(labels, labels[near])]
    # Only the vertices those triangles use: the measurements look at
    # vertices, and leftover floor corners would still be "the rearmost point".
    used = np.unique(F2)
    return V[used], np.searchsorted(used, F2)


def compute(record: dict, V: np.ndarray, F: np.ndarray, in_mat_frame: bool) -> dict:
    """Fill in support plane, automatic heel, measurements and warnings for one pick."""
    lm = dict(record["landmarks"])
    warnings = []
    try:
        plane = support_plane(record["condition"], lm, in_mat_frame)
    except LandmarkError as e:
        plane, warnings = None, [str(e)]
    if record["condition"] in STANDING and plane is None and not warnings:
        warnings.append("a standing scan needs the floor: click the three floor points")
    record["support_plane"] = plane
    V, F = foot_surface(V, F, plane, lm)
    if "heel_posterior" not in lm or record.get("heel_posterior_auto"):
        auto = auto_heel_posterior(V, {k: v for k, v in lm.items() if k != "heel_posterior"}, plane, record["foot"])
        if auto is not None:
            lm["heel_posterior"] = auto
            record["heel_posterior_auto"] = True
    record["landmarks_used"] = lm
    try:
        values, w = measure_scan(dict(record, landmarks=lm), (V, F))
        warnings += w
    except (ValueError, KeyError) as e:
        values = dict.fromkeys(MEASURES)
        warnings.append(f"measurements need more landmarks: {e}")
    record["measures"] = {k: None if v is None else round(float(v), 4) for k, v in values.items()}
    record["warnings"] = warnings
    return record


# --------------------------------------------------------------------------
# storage
# --------------------------------------------------------------------------
def mesh_path(folder: Path) -> Path | None:
    """The surface to click on: a reconstruction, else an imported (LiDAR) mesh."""
    for p in (folder / "recon" / "mesh.ply", folder / "mesh.ply"):
        if p.exists():
            return p
    return None


def viewer_path(folder: Path) -> Path | None:
    for p in (folder / "recon" / "viewer.bin", folder / "viewer.bin"):
        if p.exists():
            return p
    return None


def in_mat_frame(folder: Path) -> bool:
    m = mesh_path(folder)
    return m is not None and m.parent.name == "recon"


def list_picks(folder: Path) -> list[dict]:
    d = folder / "landmarks"
    out = []
    mesh = mesh_path(folder)
    current = sha256(mesh) if mesh else None
    files = [p for p in d.glob("pick-*.json") if p.stem.split("-", 1)[1].isdigit()] if d.exists() else []
    for p in sorted(files, key=lambda p: int(p.stem.split("-", 1)[1])):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            continue  # a damaged file is skipped, not allowed to break the page
        rec["stale"] = rec.get("mesh_sha256") != current
        out.append(rec)
    return out


def save_pick(folder: Path, n: int, body: dict, ident: dict) -> dict:
    """ident: foot, condition, session, capture_id, load_kg."""
    import trimesh

    mesh_file = mesh_path(folder)
    if mesh_file is None:
        raise LandmarkError("this scan has no 3-D model yet; build it first")
    if not 1 <= n <= 99:
        raise LandmarkError("pick number must be 1-99")
    current = sha256(mesh_file)
    shown = body.get("mesh_sha256")
    if shown is not None and shown != current:
        # The page was opened on a model that has since been rebuilt: its
        # clicks belong to the old surface and must not be stamped as current.
        raise LandmarkError("the 3-D model was rebuilt after this page was opened; reload the page and pick again")
    m = trimesh.load(mesh_file, force="mesh", process=False)
    V, F = np.asarray(m.vertices, float), np.asarray(m.faces)
    lm = validate(body, ident["condition"], m.bounds)
    mat = in_mat_frame(folder)
    record = dict(
        scan_id=f"{ident['capture_id']}-pick{n}",
        foot=ident["foot"], condition=ident["condition"], source="scan",
        session=ident.get("session") or "", capture_id=ident["capture_id"], pick=n,
        load_kg=ident.get("load_kg"), units="mm",
        mesh=str(Path("..") / mesh_file.relative_to(folder)),
        mesh_sha256=current, coordinates="mat frame" if mat else "imported mesh",
        picked_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
        notes=str(body.get("notes", ""))[:1000],
        landmarks=lm,
        # which points were snapped to a sticker's centre (vs. placed where clicked)
        snapped={k: bool(v) for k, v in (body.get("snapped") if isinstance(body.get("snapped"), dict) else {}).items()
                 if k in lm},
    )
    record = compute(record, V, F, mat)
    (folder / "landmarks").mkdir(exist_ok=True)
    (folder / "landmarks" / f"pick-{n}.json").write_text(json.dumps(record, indent=1), encoding="utf-8")
    record["stale"] = False
    return record


def export_rows(folders: list[Path]) -> list[dict]:
    """Long-format rows for the repeatability study (same columns as ``footscan measure``).

    Skips picks made on a model that has since been rebuilt, and captures
    marked synthetic.
    """
    rows = []
    for folder in folders:
        meta = folder / "capture.json"
        if meta.exists() and json.loads(meta.read_text(encoding="utf-8")).get("synthetic"):
            continue  # rendered/test scenes never enter real measurement data
        for rec in list_picks(folder):
            if rec.get("stale"):
                continue
            for k in MEASURES:
                v = rec.get("measures", {}).get(k)
                rows.append(dict(
                    foot=rec["foot"], condition=rec["condition"], source="scan", session=rec["session"],
                    capture_id=rec["capture_id"], pick=rec["pick"],
                    load_kg="" if rec.get("load_kg") is None else rec["load_kg"],
                    measure=k, value="" if v is None else v, scan_id=rec["scan_id"]))
    return rows
