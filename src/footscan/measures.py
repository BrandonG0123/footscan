"""Measurements from one scan (landmarks + optional mesh) in the foot frame.

Definitions (see docs/phase0-protocol.md for landmark placement):

foot_length_mm
    Heel_posterior to tip of longest toe along the anterior axis. From the
    mesh if given (extreme vertices below malleolus height), else from the
    ``toe_tip`` landmark.
truncated_foot_length_mm
    Heel_posterior to the 1st MTP joint marker along the anterior axis.
dorsal_height_50_mm
    Height above the reference plane of the highest point of the foot's
    cross-section at 50 % of foot length. Needs a mesh (or a ``dorsum_50``
    landmark).
ahi
    dorsal_height_50_mm / truncated_foot_length_mm  (Williams & McClay).
    Truncated length is used because toe length varies independently of
    arch structure.
navicular_height_mm, navicular_height_norm
    Height of the navicular tuberosity marker above the reference plane;
    normalised by truncated foot length so feet of different sizes compare.
    Navicular *drop* is a between-condition quantity and is computed in
    repeatability.py, not here.
rearfoot_angle_deg
    Frontal-plane angle between the calcaneal bisection and the lower-leg
    bisection. Positive = calcaneus everted relative to leg (valgus).
calcaneal_angle_deg
    Frontal-plane angle between the calcaneal bisection and the reference
    plane normal. In ``fwb`` this is the resting calcaneal stance position.
    Positive = everted.
forefoot_rearfoot_angle_deg
    ``nwb`` only. Frontal-plane angle between the line through the plantar
    1st and 5th met heads and the perpendicular to the calcaneal bisection.
    Positive = forefoot inverted relative to rearfoot (varus).
    Under load the forefoot is flattened onto the floor, so this relationship
    is not observable in ``swb``/``fwb`` and is returned as None.

Frontal-plane angles
--------------------
"Frontal plane" is the plane perpendicular to the foot's long axis: what you
see looking at the heel from behind. Projecting a 3-D line into it means
dropping its anterior component and keeping (medial, up). A line's tilt is
then ``atan2(medial, up)``: 0 when vertical, positive when its upper end
leans medially. For a calcaneal bisection drawn bottom->top, an upper end
leaning medially means the bottom has swung laterally = eversion.
"""

from __future__ import annotations

import math

import numpy as np

from .frame import FootFrame, build_frame

# The dorsum half way along the foot sits below the ankle bones; anything that far along and higher than this
# above the higher malleolus is the leg. A JUDGMENT, not measured: generous so a high instep is never cut.
DORSUM_ABOVE_MALLEOLUS_MM = 30.0

MEASURES = (
    "foot_length_mm",
    "truncated_foot_length_mm",
    "dorsal_height_50_mm",
    "ahi",
    "navicular_height_mm",
    "navicular_height_norm",
    "rearfoot_angle_deg",
    "calcaneal_angle_deg",
    "forefoot_rearfoot_angle_deg",
)


def _tilt_deg(vec_local: np.ndarray) -> float:
    """Frontal-plane tilt of an upward-pointing line; + = upper end medial."""
    _, m, u = vec_local
    if math.hypot(m, u) < 1e-9:
        raise ValueError("line is parallel to the long axis; no frontal-plane angle")
    return math.degrees(math.atan2(m, u))


def cross_section_max_height(vertices_local: np.ndarray, faces: np.ndarray, x0: float,
                             ceiling: float = np.inf) -> float | None:
    """Highest point, below ``ceiling``, where the mesh surface crosses the plane anterior = x0.

    Slicing a triangle mesh with a plane: for every triangle edge, compute the
    signed distance of both endpoints to the plane (here just ``x - x0``). If
    the signs differ, the edge crosses; the crossing is at parameter
    ``t = d0 / (d0 - d1)`` along the edge. The set of crossings traces the
    outline of the section; we want the maximum height on it. Using edge
    crossings rather than "vertices near x0" makes the answer independent of
    mesh density.
    """
    V = np.asarray(vertices_local, float)
    F = np.asarray(faces, int)
    edges = np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]])
    a, b = V[edges[:, 0]], V[edges[:, 1]]
    da, db = a[:, 0] - x0, b[:, 0] - x0
    cross = (da * db) < 0
    on = np.abs(da) < 1e-12
    pts = []
    if cross.any():
        t = da[cross] / (da[cross] - db[cross])
        pts.append(a[cross] + t[:, None] * (b[cross] - a[cross]))
    if on.any():
        pts.append(a[on])
    if not pts:
        return None
    z = np.concatenate(pts)[:, 2]
    # Above the ceiling is the leg (a shin leaning forward over the midfoot crosses this plane too): left out,
    # as the lengths leave out everything above the malleoli.
    z = z[z < ceiling]
    return float(z.max()) if len(z) else None


def measure_scan(record: dict, mesh: tuple[np.ndarray, np.ndarray] | None = None) -> tuple[dict, list[str]]:
    """Return ({measure: value or None}, warnings) for one scan record."""
    warnings: list[str] = []
    cond = record["condition"]
    lm_raw = {k: v for k, v in record["landmarks"].items() if v is not None}
    frame: FootFrame = build_frame(lm_raw, record["foot"], record.get("support_plane"))
    if cond in ("swb", "fwb") and frame.plane_source != "support_plane":
        warnings.append(f"{cond} scan using plantar tripod instead of support plane")
    lm = {k: frame.to_local(v) for k, v in lm_raw.items()}
    out: dict[str, float | None] = dict.fromkeys(MEASURES)

    V = F = None
    if mesh is not None:
        V, F = frame.to_local(mesh[0]), np.asarray(mesh[1])

    # --- lengths ---------------------------------------------------------
    heel_x = 0.0
    above_ankle = np.inf  # mesh above this height is the leg, not the foot (from the malleoli, when marked)
    if V is not None:
        # Restrict extremes to below the malleoli so the lower leg can't be
        # mistaken for heel or toes.
        mall = [lm[k][2] for k in ("malleolus_medial", "malleolus_lateral") if k in lm]
        ceiling = min(mall) if mall else np.inf
        if mall:
            above_ankle = max(mall) + DORSUM_ABOVE_MALLEOLUS_MM
        low = V[V[:, 2] < ceiling]
        heel_x, toe_x = float(low[:, 0].min()), float(low[:, 0].max())
        out["foot_length_mm"] = toe_x - heel_x
    elif "toe_tip" in lm:
        out["foot_length_mm"] = float(lm["toe_tip"][0])
    else:
        warnings.append("no mesh and no toe_tip: foot length unavailable")

    out["truncated_foot_length_mm"] = float(lm["mtpj1_medial"][0] - heel_x)
    tfl = out["truncated_foot_length_mm"]

    # --- arch height -----------------------------------------------------
    if out["foot_length_mm"] is not None and V is not None:
        out["dorsal_height_50_mm"] = cross_section_max_height(V, F, heel_x + 0.5 * out["foot_length_mm"],
                                                              ceiling=above_ankle)
    elif "dorsum_50" in lm:
        out["dorsal_height_50_mm"] = float(lm["dorsum_50"][2])
    else:
        warnings.append("no mesh and no dorsum_50 landmark: AHI unavailable")
    if out["dorsal_height_50_mm"] is not None:
        out["ahi"] = out["dorsal_height_50_mm"] / tfl

    if "navicular_tuberosity" in lm:
        out["navicular_height_mm"] = float(lm["navicular_tuberosity"][2])
        out["navicular_height_norm"] = out["navicular_height_mm"] / tfl

    # --- frontal-plane angles --------------------------------------------
    have = lambda *ks: all(k in lm for k in ks)  # noqa: E731
    if have("calc_bisect_proximal", "calc_bisect_distal"):
        calc = lm["calc_bisect_proximal"] - lm["calc_bisect_distal"]
        theta_c = _tilt_deg(calc)
        out["calcaneal_angle_deg"] = theta_c
        if have("leg_bisect_proximal", "leg_bisect_distal"):
            theta_l = _tilt_deg(lm["leg_bisect_proximal"] - lm["leg_bisect_distal"])
            out["rearfoot_angle_deg"] = theta_c - theta_l

        if cond.startswith("nwb") and have("mth1_plantar", "mth5_plantar"):
            # Forefoot line tilt above horizontal, + = 1st met head higher.
            _, m, u = lm["mth1_plantar"] - lm["mth5_plantar"]
            phi_f = math.degrees(math.atan2(u, m))
            # The perpendicular to a calcaneal bisection tilted theta_c
            # (upper end medial) has its medial end tilted -theta_c. The
            # forefoot relative to that reference is phi_f - (-theta_c).
            out["forefoot_rearfoot_angle_deg"] = phi_f + theta_c
    return out, warnings
