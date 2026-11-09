"""The insole's outline keeps a shoe insole's shape, whatever the foot: SYNTHETIC feet only.

Brandon's rule (2026-11-04): the foot's shape must not change the insole's outline, because the insole has to go
into a shoe; the foot only shapes the top (the arch fill, the heel cup). Before the generic outline, a very long foot
made a long, thin insole ("a french fry"), and a scan that read short, lengthened to the shoe's length, did too
(on synth.curved_foot at 80% size, lengthened to 275 mm: 76 mm across the ball, 0.28 of the length).

The bounds below are a judgment of a normal shoe insole's plan shape, not measured from a shoe: the width across
the ball 0.33-0.42 of the length (Menz et al. 2014 measured shoe lasts at 0.343; an insole is a little wider than
its last's bottom) and across the heel 0.22-0.29.
"""

import numpy as np
import pytest

import synth
from footscan import insole
from footscan.recon import shoe as shoe_mod

BALL_RATIO = (0.33, 0.42)
HEEL_RATIO = (0.22, 0.29)


def _proportions(poly_or_ins):
    """(length, heel width over 10-20% of the length, ball width over 60-75%) of an outline or an insole's mesh,
    measured along the outline's own length (an insole's outline is turned a few degrees to lie along the foot)."""
    if isinstance(poly_or_ins, insole.Insole):
        fit = poly_or_ins.report["shoe_fit"]
        a = np.radians(fit["turned_deg"]) if fit else 0.0
        P = np.asarray(poly_or_ins.mesh.vertices)[:, :2] @ np.array([[np.cos(a), -np.sin(a)], [np.sin(a), np.cos(a)]])
    else:
        P = np.asarray(poly_or_ins.exterior.segmentize(1.0).coords)
    x0, x1 = P[:, 0].min(), P[:, 0].max()
    length = x1 - x0

    def width(a, b):
        s = P[(P[:, 0] >= x0 + a * length) & (P[:, 0] <= x0 + b * length)]
        return s[:, 1].max() - s[:, 1].min()

    return length, width(0.10, 0.20), width(0.60, 0.75)


def _in_bounds(length, heel, ball):
    return BALL_RATIO[0] <= ball / length <= BALL_RATIO[1] and HEEL_RATIO[0] <= heel / length <= HEEL_RATIO[1]


def _foot(length_scale=1.0, width_scale=1.0, foot="right"):
    m = synth.curved_foot(foot, leg=False)
    m.apply_transform(np.diag([length_scale, width_scale, 1.0, 1.0]))
    return m


@pytest.mark.parametrize("length", [200.0, 240.0, 275.0, 310.0, 340.0])
def test_the_generic_outline_is_an_insole_shape_at_every_length(length):
    poly = insole.generic_outline(length)
    assert poly.is_valid and poly.geom_type == "Polygon"
    x0, _, x1, _ = poly.bounds
    assert x0 == pytest.approx(0.0, abs=1e-6) and x1 == pytest.approx(length, abs=1e-6)
    assert _in_bounds(*_proportions(poly))
    # a right shoe's: the big-toe end to the inner side (+y), so fit_to_foot mirrors it for a left foot
    assert shoe_mod.handedness(poly)[0] == "right"


def test_the_generic_outline_is_scaled_as_a_whole_not_only_lengthened():
    a, b = _proportions(insole.generic_outline(250.0)), _proportions(insole.generic_outline(325.0))
    assert b[1] / a[1] == pytest.approx(1.3, rel=0.01) and b[2] / a[2] == pytest.approx(1.3, rel=0.01)


def test_a_very_long_foot_gets_a_big_insole_of_the_usual_shape_not_a_long_thin_one():
    """A foot 25% longer at the same width (318 mm): the old outline followed it, 0.33 across the ball."""
    long_foot = insole.build(_foot(length_scale=1.25), "right")
    assert long_foot.report["outline_from"] == "generic"
    length, heel, ball = _proportions(long_foot)
    assert length > 320 and _in_bounds(length, heel, ball)
    normal = _proportions(insole.build(_foot(), "right"))
    assert ball / length == pytest.approx(normal[2] / normal[0], abs=0.01)


def test_a_short_scan_lengthened_to_the_shoes_length_keeps_the_insole_shape():
    """A scan reading 20% small, made at the shoe's 275 mm: the generic outline at 275 mm, not the small foot's
    outline stretched forward (which this same foot gives with foot_outline: 0.28 across the ball)."""
    small = _foot(0.8, 0.8)
    ins = insole.build(small, "right", insole.InsoleParams(target_length_mm=275.0))
    length, heel, ball = _proportions(ins)
    assert ins.report["shoe_fit"]["outline_length_mm"] == pytest.approx(275.0, abs=0.1)
    assert _in_bounds(length, heel, ball)
    stretched = _proportions(insole.build(small, "right", insole.InsoleParams(target_length_mm=275.0,
                                                                              foot_outline=True)))
    assert stretched[2] / stretched[0] < BALL_RATIO[0]  # the old way: the french fry


@pytest.mark.parametrize("scale", [0.93, 0.95])
def test_a_scan_reading_a_few_percent_small_at_the_shoes_length_gets_the_same_outline(scale):
    """The right-foot scan LIDAR_nwb_relaxed_R_20261027-151404-2349 read about 5% short of the owner's ruler
    (2026-11-05): at the shoe's length, the outline doesn't move with the scan's size."""
    ref = insole.build(_foot(), "right", insole.InsoleParams(target_length_mm=275.0))
    small = insole.build(_foot(scale, scale), "right", insole.InsoleParams(target_length_mm=275.0))
    assert small.report["shoe_fit"]["outline_length_mm"] == ref.report["shoe_fit"]["outline_length_mm"]
    assert _proportions(small)[2] == pytest.approx(_proportions(ref)[2], abs=2.0)


def test_wide_and_narrow_feet_get_the_same_outline_and_a_wide_foot_is_told_where_it_hangs_over():
    wide = insole.build(_foot(width_scale=1.25), "right", insole.InsoleParams(target_length_mm=275.0))
    narrow = insole.build(_foot(width_scale=0.8), "right", insole.InsoleParams(target_length_mm=275.0))
    for ins in (wide, narrow):
        assert _in_bounds(*_proportions(ins))
    assert _proportions(wide)[2] == pytest.approx(_proportions(narrow)[2], abs=2.0)
    assert wide.report["shoe_fit"]["overhang"]["max_mm"] > 10
    # it's the generic outline that's narrow there, not the shoe: the sheet mustn't blame the shoe
    assert any("wider than the generic insole outline" in w for w in wide.report["warnings"])
    assert not any("the shoe's size or width" in w for w in wide.report["warnings"])
    assert narrow.report["shoe_fit"]["overhang"]["max_mm"] == 0.0


def test_the_sheet_gives_the_highest_fill_on_the_printed_insole_when_the_foots_is_past_the_outline():
    """A wide foot's highest arch fill can lie where the foot hangs over the generic outline: nothing is printed
    there, so the sheet gives the highest printed fill too (SYNTHETIC: 13.99 under the foot, 11.86 on the insole)."""
    wide = insole.build(_foot(width_scale=1.25), "right", insole.InsoleParams(target_length_mm=275.0))
    r = wide.report
    assert r["max_fill_printed_mm"] < r["max_fill_mm"] - 1.0
    assert f"{r['max_fill_printed_mm']} mm on the insole ({r['max_fill_mm']} mm under the foot" in insole.summary_html(
        wide, "SYNTHETIC wide foot", synthetic=True)
    normal = insole.build(_foot(), "right", insole.InsoleParams(target_length_mm=275.0)).report
    assert insole.fill_row(normal) == f"{normal['max_fill_mm']} mm"


def test_with_no_length_the_generic_outline_is_sized_from_the_foot_and_the_sheet_asks_for_the_shoes():
    ins = insole.build(_foot(), "right")
    fit = ins.report["shoe_fit"]
    assert fit["room_past_toes_mm"] == pytest.approx(insole.GENERIC_ROOM_MM, abs=1.0)
    sheet = insole.summary_html(ins, "SYNTHETIC curved foot", synthetic=True)
    assert "the generic insole outline, the same shape for every foot" in sheet
    assert "sized from the scanned foot" in sheet and "give the shoe's insole length" in sheet


def test_left_and_right_get_mirror_image_outlines_without_a_mirroring_warning():
    right = insole.build(_foot(), "right", insole.InsoleParams(target_length_mm=275.0))
    left = insole.build(_foot(foot="left"), "left", insole.InsoleParams(target_length_mm=275.0))
    assert left.report["shoe_fit"]["mirrored"] and not right.report["shoe_fit"]["mirrored"]
    assert not any("mirrored" in w for w in left.report["warnings"])
    assert _proportions(left)[2] == pytest.approx(_proportions(right)[2], abs=2.0)


def test_a_shoes_length_shorter_than_the_foot_is_refused():
    with pytest.raises(insole.InsoleError, match="shorter than this foot"):
        insole.build(_foot(1.25), "right", insole.InsoleParams(target_length_mm=275.0))


def test_the_foots_own_outline_is_still_there_when_asked_for():
    ins = insole.build(_foot(), "right", insole.InsoleParams(foot_outline=True))
    assert ins.report["outline_from"] == "foot" and ins.report["shoe_fit"] is None
    with pytest.raises(insole.InsoleError, match="not both"):
        insole.build(_foot(), "right", insole.InsoleParams(foot_outline=True,
                                                           shoe_outline=shoe_mod.as_param(insole.generic_outline(270))))
