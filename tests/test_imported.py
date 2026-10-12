"""Imported models (Object Capture, LiDAR apps) in the accuracy study.

The calibration object's own model is put into the frame a phone app would
export it in (metres, Y up, somewhere on the table, turned any way, the table
slightly tilted) and must come back as a perfect scan; a copy 1% too big must
report 1% too big. Synthetic geometry only: no number here is a scan result.
"""

import numpy as np
import pytest
import trimesh

from footscan.recon import calib, imported


def _rot(axis, deg):
    return trimesh.transformations.rotation_matrix(np.radians(deg), axis)[:3, :3]


def _as_exported(scale=1.0, table=True, tilt_deg=1.5, yaw_deg=38.0):
    """The object (mm, Z up) as Object Capture would hand it over: metres, Y up."""
    parts = [calib.build()]
    if table:
        # just the tabletop's upper surface: a scan only ever sees that side
        x0, x1, y0, y1 = calib.LENGTH / 2 - 200, calib.LENGTH / 2 + 200, calib.WIDTH / 2 - 150, calib.WIDTH / 2 + 150
        top = trimesh.Trimesh([[x0, y0, 0], [x1, y0, 0], [x1, y1, 0], [x0, y1, 0]], [[0, 1, 2], [0, 2, 3]])
        parts.append(top.subdivide().subdivide().subdivide())
    m = trimesh.util.concatenate(parts)
    m.apply_scale(scale)
    T = np.eye(4)
    T[:3, :3] = _rot([1, 0, 0], tilt_deg) @ _rot([0, 0, 1], yaw_deg)
    T[:3, 3] = [-80.0, 40.0, 12.0]
    m.apply_transform(T)
    # Z up -> Y up (the inverse of imported.UP["y"]), then millimetres -> metres
    m.apply_transform(np.block([[imported.UP["y"].T, np.zeros((3, 1))], [np.zeros((1, 3)), np.ones((1, 1))]]))
    m.apply_scale(0.001)
    return m


@pytest.mark.parametrize("table", [True, False])
def test_a_perfect_model_from_an_app_comes_back_perfect(table):
    a = imported.evaluate_imported(_as_exported(table=table, tilt_deg=1.5 if table else 0.0), up="y")
    assert a["imported"]["units_detected"] == "m"
    assert ("table found" in a["imported"]["floor"]) == table
    if table:
        assert a["imported"]["floor_tilt_corrected_deg"] == pytest.approx(1.5, abs=0.05)
    assert a["surface_deviation"]["median_mm"] < 0.01
    dims = {r["key"]: r for r in a["dimensions"]}
    for k in ("length", "width", "terrace_high", "terrace_low", "dome_apex"):
        assert abs(dims[k]["scan_minus_reference_mm"]) < 0.06, k


def test_a_model_one_percent_too_big_reports_one_percent_too_big():
    a = imported.evaluate_imported(_as_exported(scale=1.01), up="y")
    dims = {r["key"]: r for r in a["dimensions"]}
    assert dims["length"]["scan_minus_reference_mm"] == pytest.approx(1.5, abs=0.1)
    assert dims["terrace_high"]["scan_minus_reference_mm"] == pytest.approx(0.35, abs=0.06)
    assert a["surface_deviation"]["median_mm"] > 0.1


def test_millimetres_and_z_up_are_left_alone():
    m = calib.build()
    m.apply_transform(np.block([[_rot([0, 0, 1], -20.0), np.array([[5.0], [7.0], [0.0]])], [np.zeros((1, 3)), np.ones((1, 1))]]))
    a = imported.evaluate_imported(m, up="z")
    assert a["imported"]["units_detected"] == "mm" and a["imported"]["scale_to_mm"] == 1.0
    assert a["surface_deviation"]["median_mm"] < 0.01


def test_the_wrong_up_axis_is_refused():
    with pytest.raises(ValueError):
        imported.to_floor_frame(calib.build(), up="x")


def test_something_that_isnt_the_calibration_object_is_refused():
    big = calib.build()
    big.apply_scale(3.0)  # e.g. a model with no real-world scale
    with pytest.raises(imported.NotTheObject):
        imported.evaluate_imported(big, up="z")
