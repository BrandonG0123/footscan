"""Fitting the insole to a shoe's own insole, from a scan of it (recon/shoe.py, insole.build)."""

import numpy as np
import pytest

import synth


def _signed_gaps(outline, truth):
    """Every mm of ``outline``'s edge: how far outside (+) or inside (-) ``truth`` it is, after lining the two
    up (turn and slide: the outline's own frame is arbitrary)."""
    import shapely
    import shapely.affinity

    from footscan.recon import compare

    R, t, _ = compare._fit_outlines(truth, outline, keep=1.0)
    turned = shapely.affinity.rotate(outline, np.degrees(np.arctan2(R[1, 0], R[0, 0])), origin=(0, 0))
    E = np.asarray(shapely.affinity.translate(turned, *t).exterior.segmentize(1.0).coords)
    d = np.asarray(shapely.distance(truth.exterior, shapely.points(E)))
    return np.where(shapely.contains_xy(truth, E[:, 0], E[:, 1]), -d, d)


@pytest.mark.parametrize("kw", [dict(), dict(table=False), dict(upside_down=True, yaw=-70.0), dict(tilt=5.0)],
                         ids=["on a table", "no table", "upside down", "table 5 degrees off level"])
def test_the_shoe_insoles_outline_is_read_from_its_scan(kw):
    import shapely.affinity

    from footscan.recon import shoe

    outline, info = shoe.outline_from_scan(synth.shoe_insole(**kw))
    assert info["table_found"] == kw.get("table", True) and info["units_detected"] == "m"
    if info["table_found"]:  # cut along the table itself, however it's tilted
        assert info["table_tilt_deg"] == pytest.approx(kw.get("tilt", 0.0), abs=0.2)
    assert 270.0 <= info["length_mm"] <= 272.0 and 104.0 <= info["width_mm"] <= 106.0
    assert outline.bounds[0] == pytest.approx(0.0, abs=1e-6)  # heel at x = 0, toes along +x
    if kw.get("upside_down"):  # seen from above it's the mirror image; mirrored back, it's the same shape
        outline = shapely.affinity.scale(outline, 1, -1, origin=(0, 0))
    gaps = _signed_gaps(outline, synth.shoe_plan())
    assert np.abs(gaps).max() < 1.0 and abs(gaps.mean()) < 0.5


def test_something_that_isnt_a_shoe_insole_is_refused():
    import trimesh

    from footscan.recon import shoe

    box = trimesh.creation.box([0.12, 0.03, 0.12])  # 120 x 120 mm seen from above, metres, Y up
    with pytest.raises(shoe.ShoeError, match="doesn't look like a shoe's insole"):
        shoe.outline_from_scan(box)


def _outline_param(**kw):
    from footscan.recon import shoe

    outline, _ = shoe.outline_from_scan(synth.shoe_insole(**kw))
    return shoe.as_param(outline)


def test_the_insole_takes_the_shoes_outline_and_keeps_the_foots_shape_inside_it():
    """The outline is the shoe's (270 mm, not the foot's 250 + margins); the top under the foot is exactly
    what it is without the shoe; the foot fits inside, with the room past the toes reported."""
    from footscan import insole

    foot = synth.curved_foot("right", leg=False)
    plain = insole.from_scan(foot, "right")
    # a roomy shoe: this test foot's toes end in a broad 56 mm half circle, wider than most toe boxes
    fitted = insole.from_scan(foot, "right", insole.InsoleParams(shoe_outline=_outline_param(ball=114.0)))
    fit = fitted.report["shoe_fit"]
    assert fitted.report["length_mm"] == pytest.approx(271.0, abs=1.5)
    assert not fit["mirrored"] and fit["overhang"]["max_mm"] <= 1.0
    assert fit["room_past_toes_mm"] == pytest.approx(271.0 - 3.0 - 250.0, abs=2.0)  # heel 3 mm behind the foot's
    assert fitted.report["max_fill_mm"] == plain.report["max_fill_mm"]
    assert not any("wider than the shoe" in w for w in fitted.report["warnings"])
    # the sheet says the outline is the shoe's
    assert "the shoe's own insole" in insole.summary_html(fitted, "test")


def test_a_shoe_narrower_than_the_foot_is_warned_about_where_and_by_how_much():
    from footscan import insole

    foot = synth.curved_foot("right", leg=False)  # 100 mm across the ball
    fitted = insole.from_scan(foot, "right", insole.InsoleParams(shoe_outline=_outline_param(ball=92.0)))
    o = fitted.report["shoe_fit"]["overhang"]
    assert 3.0 < o["max_mm"] < 9.0 and o["where"].startswith("ball of the foot")
    assert any("wider than the shoe's insole at the ball of the foot" in w for w in fitted.report["warnings"])
    assert o["area_mm2"] > 300  # a real area of the foot is over the edge: the insole stops there


@pytest.mark.parametrize("kw, mirrored", [(dict(), False), (dict(upside_down=True), True), (dict(foot="left"), True)],
                         ids=["right shoe, top up", "right shoe, upside down", "left shoe"])
def test_which_shoe_comes_from_the_insole_itself_and_the_wrong_hand_is_mirrored(kw, mirrored):
    """A shoe's last curves toward the big toe: the toe end says which shoe (and which way up) the scan is. For
    a right foot, a left shoe's insole, or a right one scanned upside down, is mirrored back, and said so;
    a right one top side up never is, however the foot happens to fit."""
    from footscan import insole
    from footscan.recon import shoe

    outline, _ = shoe.outline_from_scan(synth.shoe_insole(**kw))
    hand, left_mm = shoe.handedness(outline)
    assert hand == ("left" if mirrored else "right") and abs(left_mm) > 10
    fitted = insole.from_scan(synth.curved_foot("right", leg=False), "right",
                              insole.InsoleParams(shoe_outline=shoe.as_param(outline)))
    fit = fitted.report["shoe_fit"]
    assert fit["mirrored"] is mirrored
    assert any("mirrored for this foot" in w for w in fitted.report["warnings"]) is mirrored


def test_a_straight_shoe_is_used_as_scanned_with_a_warning_to_check():
    import shapely
    import shapely.affinity

    from footscan.recon import shoe

    plan = synth.shoe_plan()
    straight = plan.union(shapely.affinity.scale(plan, 1, -1, origin=(0, 0)))  # symmetric: no toe-end side
    outline = shoe._oriented(straight)[0]
    assert shoe.handedness(outline)[0] is None
    foot = shapely.affinity.translate(outline.buffer(-6.0), 10.0, 40.0)
    _, fit = shoe.fit_to_foot(outline, foot, "right", 3.0)
    assert not fit["mirrored"] and any("couldn't tell which shoe" in w for w in shoe.fit_warnings(fit))


def test_a_shoe_and_a_length_together_are_refused():
    from footscan import insole

    with pytest.raises(insole.InsoleError, match="not both"):
        insole.from_scan(synth.curved_foot("right", leg=False), "right",
                     insole.InsoleParams(shoe_outline=_outline_param(), target_length_mm=280.0))
