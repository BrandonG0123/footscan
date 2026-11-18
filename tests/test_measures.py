"""Geometry tests on hand-constructed feet with analytically known answers.

These check the maths, not a real foot. No output of these tests is a
measurement of anyone.
"""

import math

import numpy as np
import pytest
import trimesh

from footscan.frame import FrameError, build_frame
from footscan.measures import cross_section_max_height, measure_scan


def tilt(base, length, deg):
    """Point `length` above `base`, upper end tilted `deg` toward +y."""
    r = math.radians(deg)
    return list(np.add(base, [0, length * math.sin(r), length * math.cos(r)]))


def right_foot(calc_eversion=6.0, leg_tilt=2.0):
    # Local frame: x anterior, y medial (right foot => y is left), z up.
    return {
        "heel_posterior": [0, 0, 20],
        "toe_tip": [250, 0, 10],
        "mtpj1_medial": [180, 40, 25],
        "mtpj5_lateral": [160, -40, 20],
        "calc_plantar": [30, 0, 0],
        "mth1_plantar": [180, 30, 0],
        "mth5_plantar": [160, -30, 0],
        "navicular_tuberosity": [120, 35, 45],
        "dorsum_50": [125, 0, 70],
        "malleolus_medial": [60, 30, 80],
        "malleolus_lateral": [60, -30, 75],
        "calc_bisect_distal": [10, 0, 25],
        "calc_bisect_proximal": tilt([10, 0, 25], 40, calc_eversion),
        "leg_bisect_distal": [60, 0, 100],
        "leg_bisect_proximal": tilt([60, 0, 100], 150, leg_tilt),
    }


def random_rigid(seed):
    rng = np.random.default_rng(seed)
    q, _ = np.linalg.qr(rng.normal(size=(3, 3)))
    if np.linalg.det(q) < 0:
        q[:, 0] *= -1
    return q, rng.normal(scale=500, size=3)


def transform(lm, R, t):
    return {k: list(R @ np.asarray(v) + t) for k, v in lm.items()}


def record(lm, foot="right", condition="nwb", **kw):
    return dict(foot=foot, condition=condition, landmarks=lm, session="S1", capture_id="C1", **kw)


EXPECTED = {
    "foot_length_mm": 250,
    "truncated_foot_length_mm": 180,
    "dorsal_height_50_mm": 70,
    "ahi": 70 / 180,
    "navicular_height_mm": 45,
    "navicular_height_norm": 45 / 180,
    "rearfoot_angle_deg": 4.0,
    "calcaneal_angle_deg": 6.0,
    "forefoot_rearfoot_angle_deg": 6.0,  # forefoot flat on tripod, calcaneus everted 6 => 6 varus
}


def check(values):
    for k, v in EXPECTED.items():
        assert values[k] == pytest.approx(v, abs=1e-6), k


def test_canonical_right_foot():
    values, warnings = measure_scan(record(right_foot()))
    check(values)
    assert warnings == []


@pytest.mark.parametrize("seed", range(5))
def test_invariant_to_scanner_pose(seed):
    R, t = random_rigid(seed)
    values, _ = measure_scan(record(transform(right_foot(), R, t)))
    check(values)


def test_left_foot_mirror_gives_same_signs():
    mirrored = {k: [v[0], -v[1], v[2]] for k, v in right_foot().items()}
    values, _ = measure_scan(record(mirrored, foot="left"))
    check(values)


def test_inverted_calcaneus_is_negative():
    values, _ = measure_scan(record(right_foot(calc_eversion=-3.0, leg_tilt=0.0)))
    assert values["calcaneal_angle_deg"] == pytest.approx(-3.0)
    assert values["rearfoot_angle_deg"] == pytest.approx(-3.0)


def test_forefoot_varus_with_support_plane():
    lm = right_foot(calc_eversion=0.0)
    lm["mth1_plantar"] = [180, 30, 5]  # 1st met head raised 5 mm over 60 mm span
    rec = record(lm, support_plane={"point": [0, 0, 0], "normal": [0, 0, -1]})  # normal deliberately flipped
    values, _ = measure_scan(rec)
    assert values["forefoot_rearfoot_angle_deg"] == pytest.approx(math.degrees(math.atan2(5, 60)))
    assert values["navicular_height_mm"] == pytest.approx(45)


def test_forefoot_rearfoot_not_reported_under_load():
    rec = record(right_foot(), condition="fwb", support_plane={"point": [0, 0, 0], "normal": [0, 0, 1]})
    values, warnings = measure_scan(rec)
    assert values["forefoot_rearfoot_angle_deg"] is None
    assert warnings == []


def test_weight_bearing_without_support_plane_warns():
    _, warnings = measure_scan(record(right_foot(), condition="fwb"))
    assert any("support plane" in w for w in warnings)


def test_missing_tripod_and_plane_raises():
    lm = right_foot()
    del lm["mth5_plantar"]
    with pytest.raises(FrameError):
        measure_scan(record(lm))


def test_mesh_lengths_and_cross_section():
    box = trimesh.creation.box(extents=[250, 80, 60])
    box.apply_translation([125, 0, 30])  # occupies x 0..250, z 0..60
    lm = right_foot()
    del lm["dorsum_50"], lm["toe_tip"]
    lm["mtpj1_medial"] = [180, 40, 25]
    R, t = random_rigid(42)
    lm_w = transform(lm, R, t)
    V_w = box.vertices @ R.T + t
    values, _ = measure_scan(record(lm_w), mesh=(V_w, box.faces))
    assert values["foot_length_mm"] == pytest.approx(250)
    assert values["dorsal_height_50_mm"] == pytest.approx(60)
    assert values["ahi"] == pytest.approx(60 / 180)


def test_cross_section_uses_edge_crossings_not_vertices():
    # A single sloped triangle: height rises linearly with x. No vertex at x=50.
    V = np.array([[0, 0, 0], [100, -10, 100], [100, 10, 100]], float)
    F = np.array([[0, 1, 2]])
    assert cross_section_max_height(V, F, 50.0) == pytest.approx(50.0)
    assert cross_section_max_height(V, F, 150.0) is None


def test_frame_axes_orthonormal():
    R, t = random_rigid(7)
    f = build_frame(transform(right_foot(), R, t), "right")
    assert np.allclose(f.rotation @ f.rotation.T, np.eye(3))


def test_dorsal_height_leaves_out_a_shin_leaning_over_the_midfoot():
    # SYNTHETIC: a 250 x 80 x 60 block foot with a "shin" column standing over its midpoint, up to z = 250.
    # The lengths already leave out everything above the malleoli; the dorsum must not read the shin either.
    foot = trimesh.creation.box(extents=[250, 80, 60])
    foot.apply_translation([125, 0, 30])
    shin = trimesh.creation.box(extents=[30, 40, 190])
    shin.apply_translation([125, 0, 60 + 95])
    mesh = trimesh.util.concatenate([foot, shin])
    lm = right_foot()
    del lm["dorsum_50"], lm["toe_tip"]
    values, _ = measure_scan(record(lm), mesh=(mesh.vertices, mesh.faces))
    assert values["dorsal_height_50_mm"] == pytest.approx(60)
    assert values["ahi"] == pytest.approx(60 / 180)
