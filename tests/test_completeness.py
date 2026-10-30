"""The whole foot must be in a sole scan: toes and heel there, not much shorter than the person's other scans.

All shapes here are SYNTHETIC (tests/synth.py). The cut ones are closed over, as Object Capture closes a part
of the foot it never saw, so nothing is torn and the older checks don't see them.
"""

import pytest

import synth
from footscan.recon import completeness, foot_prep


def _measured(mesh):
    placed, info = foot_prep.prepare_sole_up(synth.sole_up_capture(mesh))
    return completeness.measure(placed), info


@pytest.mark.parametrize("foot", ["right", "left"])
@pytest.mark.parametrize("shape", ["shaped", "curved"])
def test_a_whole_foot_passes(foot, shape):
    mesh = synth.shaped_foot(foot) if shape == "shaped" else synth.curved_foot(foot)
    m, info = _measured(mesh)
    assert m["length_mm"] == pytest.approx(250.0, abs=3.0)
    assert m["toe_end"] < completeness.TOE_END_SQUARE and m["heel_end"] < completeness.HEEL_END_SQUARE
    assert completeness.problems(m) == [] and completeness.from_prep(info) == []


@pytest.mark.parametrize("foot", ["right", "left"])
@pytest.mark.parametrize("shape", ["shaped", "curved"])
def test_a_scan_without_its_toes_is_caught(foot, shape):
    """The front 50 mm gone (the toes and the end of the forefoot), the cut closed over."""
    mesh = synth.shaped_foot(foot) if shape == "shaped" else synth.curved_foot(foot)
    m, info = _measured(synth.cut_ends(mesh, x_to=200.0))
    found = completeness.problems(m)
    assert len(found) == 1 and found[0].startswith("THE TOES ARE MISSING") and "Scan again" in found[0]


@pytest.mark.parametrize("foot", ["right", "left"])
def test_a_scan_with_the_heel_cut_off_is_caught(foot):
    """The back 30 mm of the heel gone, the cut closed over."""
    m, info = _measured(synth.cut_ends(synth.shaped_foot(foot), x_from=30.0))
    found = completeness.problems(m) + completeness.from_prep(info)
    assert any(p.startswith("THE HEEL IS CUT OFF") for p in found)
    assert not any(p.startswith("THE TOES") for p in found)


def test_a_scan_much_shorter_than_the_other_foot_is_caught_and_a_close_one_is_not():
    """The left sole-up scan 89df against the right foot's 2349 (real insole outlines, 227.0 and 246.4 mm)."""
    m = dict(length_mm=227.0)
    right = dict(foot="right", same_foot=False, capture_id="LIDAR_nwb_relaxed_R_x", length_mm=246.4)
    found = completeness.against_others(m, [right])
    assert len(found) == 1 and found[0].startswith("THIS FOOT IS 19 MM SHORTER than your right foot's scan")
    assert completeness.against_others(dict(length_mm=240.0), [right]) == []
    # longer than the other is not this scan's fault
    assert completeness.against_others(dict(length_mm=265.0), [right]) == []
    earlier = dict(right, foot="left", same_foot=True, capture_id="LIDAR_nwb_relaxed_L_y")
    assert "an earlier scan of the same foot" in completeness.against_others(m, [earlier])[0]


def test_make_insole_warns_about_missing_toes_too():
    """Scans kept from before the check (or imported some other way) still say so when an insole is made."""
    ins, _ = foot_prep.insole_from_object_capture(synth.sole_up_capture(synth.cut_ends(synth.shaped_foot("right"),
                                                                                       x_to=200.0)),
                                                  "right", kind="sole_up")
    assert any(w.startswith("THE TOES ARE MISSING") for w in ins.report["warnings"])
    whole, _ = foot_prep.insole_from_object_capture(synth.sole_up_capture(synth.shaped_foot("right")), "right",
                                                    kind="sole_up")
    assert not any("MISSING" in w or "CUT OFF" in w for w in whole.report["warnings"])


def test_a_scan_that_isnt_one_foot_is_caught_when_its_ends_look_whole():
    """The legs-flat scan 2190 caught both feet merged: its outline read 264.9 x 254.3 mm (real check, Oct 28).
    A real kept right sole scan, 2349, read 244.1 x 89.6 mm."""
    both = dict(length_mm=264.9, width_mm=254.3, toe_end=0.24, heel_end=0.28)
    found = completeness.problems(both)
    assert len(found) == 1 and found[0].startswith("THIS ISN'T ONE WHOLE FOOT: seen from above the scan is 265 x 254 mm")
    assert completeness.problems(dict(length_mm=244.1, width_mm=89.6, toe_end=0.23, heel_end=0.48)) == []
    # far too short to be an adult foot
    assert completeness.problems(dict(length_mm=150.0, width_mm=60.0, toe_end=0.3, heel_end=0.4))[0].startswith(
        "THIS ISN'T ONE WHOLE FOOT")
