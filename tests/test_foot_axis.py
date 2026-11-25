"""The foot's length axis (recon/plantar.long_axis): down the middle of the footprint, a left foot's the mirror image
of its right foot's. SYNTHETIC shapes only."""

import numpy as np
import pytest

import synth
from footscan import insole
from footscan.recon import plantar


def _footprint(foot):
    m = synth.curved_foot(foot, leg=False)
    V = np.asarray(m.vertices)
    return V[V[:, 2] < 12.0][:, :2]


@pytest.mark.parametrize("foot", ["right", "left"])
def test_the_length_axis_runs_down_the_middle_of_a_footprint_shaped_the_same_on_both_sides(foot):
    """synth.curved_foot's outline is the same on both sides of y = 45 (its sole isn't: the arch is on one side).
    The narrowest-width edge, the old axis, ran 7.7 degrees off that line, along one side, the same way for both
    feet."""
    axis, length, width = plantar.long_axis(_footprint(foot))
    off = np.degrees(np.arctan2(abs(axis[1]), abs(axis[0])))
    assert off < 0.5
    assert length == pytest.approx(250.0, abs=1.0) and width == pytest.approx(100.0, abs=1.0)


def test_the_axis_of_a_mirrored_footprint_is_the_mirror_of_its_axis():
    """Any footprint: mirrored across the x axis, its length axis is mirrored too (the old one could pick the other
    side's edge instead)."""
    xy = _footprint("right")
    xy = xy @ np.array([[np.cos(0.3), -np.sin(0.3)], [np.sin(0.3), np.cos(0.3)]]).T + [40.0, -15.0]  # any turn, anywhere
    xy = np.r_[xy, [[120.0, 160.0]]]  # and not symmetric: a bump on one side
    a, la, wa = plantar.long_axis(xy)
    b, lb, wb = plantar.long_axis(xy * [1.0, -1.0])
    assert abs(a @ (b * [1.0, -1.0])) == pytest.approx(1.0, abs=1e-9)
    assert (la, wa) == pytest.approx((lb, wb), abs=1e-6)


def test_a_left_and_a_right_foot_shaped_alike_get_their_insole_outlines_placed_alike():
    """The insole thread's finding (2026-11-25): with the old axis, the generic outline on this right foot was turned
    -9 degrees and slid 8 mm (its limits) and on the left foot -5.75 and 6 mm. Placed round mirror-image footprints,
    the outlines are placed as mirror images: turned by opposite angles, slid by the same distance the other way."""
    fits = {f: insole.from_scan(synth.curved_foot(f, leg=False), f).report["shoe_fit"] for f in ("right", "left")}
    r, left = fits["right"], fits["left"]
    assert left["turned_deg"] == pytest.approx(-r["turned_deg"], abs=0.3)
    assert left["slid_mm"] == pytest.approx(-r["slid_mm"], abs=0.3)
    assert left["room_past_toes_mm"] == pytest.approx(r["room_past_toes_mm"], abs=0.3)


@pytest.mark.parametrize("seed", [2, 5, 6])
def test_the_front_of_flat_toes_speckled_by_the_scan_is_not_read_as_toes_hanging_up(seed):
    """The underside's lowest point at the last step or two of a toe tip is high up its front, a wall facing
    forward. Speckled (0.3 mm), with the foot turned down the middle of its footprint, that front was read as toes
    raised 77-78 degrees (refused on arrival as too steep: seeds 2 and 5) or 47 degrees (laid flat at three joints:
    258.5 mm of 250, seed 6). The toes are flat: nothing is laid, nothing is warned about, the length is the foot's."""
    from footscan.recon import completeness, foot_prep

    scan = synth.sole_up_capture(synth.speckle(synth.refined(synth.curved_foot("right")), 0.3, seed=seed))
    placed, info = foot_prep.prepare_sole_up(scan, foot="right")
    assert "toes_laid_flat" not in info and "toes_warning" not in info
    assert completeness.measure(placed, "sole_up")["length_mm"] == pytest.approx(250.0, abs=1.0)


@pytest.mark.parametrize("foot", ["right", "left"])
def test_a_foot_lying_along_x_with_no_leg_points_its_toes_toward_plus_x(foot):
    """With no leg in the scan, which end is the toes comes from the mat's instruction (toes toward +y). A foot
    lying across the mat, here exactly along x as the SYNTHETIC feet are built, took the sign of a rounding error
    with the axis down the middle of its footprint: heel first, the arch on the outer side. It points toward +x."""
    frame, info = plantar.provisional_frame(synth.curved_foot(foot, leg=False), foot)
    assert info["toe_end_from"] == "mat"
    assert frame.anterior @ [1.0, 0.0, 0.0] == pytest.approx(1.0, abs=1e-6)
