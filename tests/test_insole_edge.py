"""The insole's edge beyond the heel: its top corner is rounded (InsoleParams.edge_roll_mm), so where the outline cuts
through the arch fill there is no square wall with a sharp corner under the arch's border. Also the heel cup's rim
as printed, and no lip under the ball of the foot (InsoleParams.forefoot_cap_mm). SYNTHETIC feet only
(tests/synth.py); no number here is from a person."""

import numpy as np
import pytest

import synth
from footscan import insole


@pytest.fixture(scope="module")
def pair():
    """The curved foot (its arch reaches the generic outline's inner edge at 275 mm), with and without the rounding."""
    foot = synth.curved_foot("right", leg=False)
    rounded = insole.from_scan(foot, "right", insole.InsoleParams(target_length_mm=275.0))
    square = insole.from_scan(foot, "right", insole.InsoleParams(target_length_mm=275.0, edge_roll_mm=0.0))
    return rounded, square


def _tops(ins, P):
    """Height of the top surface at each (x, y) in P, by rays from above (nan where nothing is hit)."""
    hit, idx, _ = ins.mesh.ray.intersects_location(np.c_[P, np.full(len(P), 100.0)], np.tile([0, 0, -1.0], (len(P), 1)),
                                                   multiple_hits=False)
    z = np.full(len(P), np.nan)
    z[idx] = hit[:, 2]
    return z


def _grid(ins, step=1.5):
    import shapely

    poly = ins.surface["outline"]
    x0, y0, x1, y1 = poly.bounds
    X, Y = np.meshgrid(np.arange(x0, x1, step), np.arange(y0, y1, step))
    P = np.c_[X.ravel(), Y.ravel()]
    keep = shapely.contains_xy(poly.buffer(-0.3), P[:, 0], P[:, 1])
    return P[keep], np.asarray(shapely.distance(poly.exterior, shapely.points(P[keep])))


def test_the_arch_edge_is_rounded_so_it_stands_lower_than_a_square_one(pair):
    rounded, square = pair
    e_r, e_s = rounded.report["edge_beyond_heel"], square.report["edge_beyond_heel"]
    # SYNTHETIC: the curved foot's arch is cut by the outline's inner edge, so the square edge stands tall there
    assert e_s["side"] == "inner" and e_s["max_mm"] > 12.0
    assert e_r["side"] == "inner"
    assert e_s["max_mm"] - e_r["max_mm"] > 1.5
    assert e_r["max_mm"] < e_s["max_mm"]


def test_rounding_the_edge_only_ever_lowers_the_top_and_only_near_the_edge(pair):
    """Never closer to the sole than the relief: the rounding may only take material away, and only within its
    radius of the edge; further in the top is exactly as it was."""
    rounded, square = pair
    P, d = _grid(rounded)
    a, b = _tops(rounded, P), _tops(square, P)
    ok = ~np.isnan(a) & ~np.isnan(b)
    assert ok.mean() > 0.95
    # (the two meshes are triangulated a little differently near the edge: a few hundredths either way)
    assert np.all(a[ok] <= b[ok] + 0.05)
    far = ok & (d > rounded.params.edge_roll_mm + 1.5)
    assert np.allclose(a[far], b[far], atol=0.05)
    near = ok & (d < 1.0) & (P[:, 0] > 140.0) & (P[:, 0] < 150.0)  # forward of the heel, beside the arch
    assert near.any() and np.all(a[near] <= b[near] + 0.05)


def test_the_heel_cup_keeps_its_full_wall(pair):
    """The rounding fades in with the heel's weight: in the heel zone the cup's wall is exactly as before, so the
    cup holds the heel to its full depth."""
    rounded, square = pair
    P, _ = _grid(rounded, step=1.0)
    x0, x1 = rounded.report["base_taper_x_mm"]  # the foot's own heel and toe
    heel = P[P[:, 0] < x0 + rounded.params.heel_zone * (x1 - x0)]
    a, b = _tops(rounded, heel), _tops(square, heel)
    ok = ~np.isnan(a) & ~np.isnan(b)
    assert ok.mean() > 0.95
    assert np.allclose(a[ok], b[ok], atol=0.05)
    assert np.nanmax(a) > rounded.params.base_mm + 0.85 * rounded.params.heel_cup_depth_mm


def test_the_highest_fill_given_is_the_printed_one_after_rounding(pair):
    """The sheet's highest fill is what is printed: where the rounding lowers the top near the edge, the number
    follows it (never higher than without the rounding), and the foot's own peak doesn't move."""
    rounded, square = pair
    assert rounded.report["max_fill_mm"] <= square.report["max_fill_mm"]
    assert rounded.report["foot_max_fill_mm"] == square.report["foot_max_fill_mm"]


def test_a_left_insole_reports_its_arch_edge_on_the_inner_side():
    foot = synth.curved_foot("left", leg=False)
    ins = insole.from_scan(foot, "left", insole.InsoleParams(target_length_mm=275.0, edge_roll_mm=0.0))
    assert ins.report["edge_beyond_heel"]["side"] == "inner"
    assert ins.report["edge_beyond_heel"]["y"] < 0  # the output frame's y is toward the foot's left: inner is -y


def test_the_solid_stays_closed_with_the_rounding(pair):
    rounded, _ = pair
    assert rounded.mesh.is_watertight and rounded.mesh.volume > 0
    assert rounded.mesh.vertices[:, 2].min() == pytest.approx(0.0, abs=1e-6)


# ---- the heel cup as printed -------------------------------------------------------------------------------------

def test_the_heel_cup_rim_is_reported_as_printed_full_where_the_outline_leaves_room():
    """With the foot's own outline the wall has its 3 mm all round, so the rim stands at the full cup depth on
    both sides and at the back."""
    ins = insole.from_scan(synth.curved_foot("right", leg=False), "right", insole.InsoleParams(foot_outline=True))
    rim = ins.report["heel_cup_rim_mm"]
    depth = ins.params.heel_cup_depth_mm
    assert rim == dict(inner=pytest.approx(depth, abs=0.3), back=pytest.approx(depth, abs=0.3),
                       outer=pytest.approx(depth, abs=0.3))


def test_a_narrow_outline_round_the_heel_shows_on_the_sheet_as_a_lower_rim():
    """SYNTHETIC shaped_foot: square-sided (its heel's sides don't curve up into a cup of their own), its heel as
    wide as the generic outline's heel leaves no room for the wall beside it: the rim at the sides stands well
    below the depth asked for, and the sheet says so rather than giving only the 12 mm asked for."""
    ins = insole.from_scan(synth.shaped_foot("right", leg=False), "right", insole.InsoleParams(target_length_mm=275.0))
    rim = ins.report["heel_cup_rim_mm"]
    depth = ins.params.heel_cup_depth_mm
    assert rim["back"] == pytest.approx(depth, abs=0.3)
    assert min(rim["inner"], rim["outer"]) < depth / 2
    sheet = insole.summary_html(ins, "test", synthetic=True)
    assert f"as printed, its rim stands {rim['inner']} mm inner side, {rim['back']} mm back, {rim['outer']} mm outer side" in sheet


def test_the_sheet_gives_the_edge_and_its_rounding(pair):
    rounded, square = pair
    e = rounded.report["edge_beyond_heel"]
    assert f"top corner rounded to 4 mm beyond the heel; at its tallest {e['max_mm']} mm tall (base included), on the inner side" in \
        insole.summary_html(rounded, "test", synthetic=True)
    assert "square (not rounded)" in insole.summary_html(square, "test", synthetic=True)


# ---- under the ball of the foot ----------------------------------------------------------------------------------

def test_under_the_ball_the_top_is_drawn_down_to_the_forefoot_cap_and_the_arch_is_untouched():
    """SYNTHETIC curved foot (its sole curls up 4 mm over the last 6 mm at every edge, so some fill along the ball's
    sides, about 1 mm inside the generic outline): with a 0.5 mm forefoot cap, past forefoot_full_at nothing rises
    more than that; behind forefoot_from the top is exactly as
    without the cap; nowhere is it higher than without."""
    foot = synth.curved_foot("right", leg=False)
    capped = insole.from_scan(foot, "right", insole.InsoleParams(target_length_mm=275.0, forefoot_cap_mm=0.5))
    free = insole.from_scan(foot, "right", insole.InsoleParams(target_length_mm=275.0, forefoot_cap_mm=None))
    a, b = capped.surface["rise"], free.surface["rise"]
    X = np.broadcast_to(capped.surface["xs"][None, :], a.shape)
    x0, x1 = capped.report["base_taper_x_mm"]
    p = capped.params
    past = np.isfinite(a) & (X >= x0 + p.forefoot_full_at * (x1 - x0))
    behind = np.isfinite(a) & (X < x0 + p.forefoot_from * (x1 - x0))
    assert np.nanmax(b[past]) > 1.0                 # the ball's edges rise without the cap...
    assert np.nanmax(a[past]) <= 0.5 + 1e-9         # ...and no more than the cap with it
    assert np.array_equal(a[behind], b[behind])     # the arch and the heel as they were
    ok = np.isfinite(a)
    assert np.all(a[ok] <= b[ok] + 1e-9)            # only ever lowered
    assert capped.report["foot_max_fill_mm"] == free.report["foot_max_fill_mm"]


def test_the_sheet_says_how_high_the_top_may_stand_under_the_ball():
    ins = insole.from_scan(synth.curved_foot("right", leg=False), "right", insole.InsoleParams(target_length_mm=275.0))
    assert "the top no more than 3 mm above the base from 72% of the foot's length" in \
        insole.summary_html(ins, "test", synthetic=True)


def test_the_arch_support_as_printed_is_the_midfoots_highest_printed_fill_on_the_inner_side(pair):
    """max_fill_mm is the whole insole's highest point, which on a flat foot can be the heel's rounded back; the
    arch support as printed is the highest printed fill between the heel zone and the ball, and the sheet gives it."""
    rounded, square = pair
    a, p = rounded.report["arch_fill"], rounded.params
    assert a["side"] == "inner" and p.heel_zone <= a["share"] <= p.forefoot_from
    assert 0.0 < a["max_mm"] <= rounded.report["max_fill_mm"]
    s = rounded.surface
    band = (s["xs"] >= a["x"] - 0.01) & (s["xs"] <= a["x"] + 0.01)
    assert band.any()  # on the fill's grid
    # rounding the edge lowers it where the outline cuts the arch (SYNTHETIC curved foot: its arch reaches the edge)
    assert a["max_mm"] < square.report["arch_fill"]["max_mm"]
    sheet = insole.summary_html(rounded, "test", synthetic=True)
    assert (f"<th>Arch support as printed</th><td colspan=\"3\">at most {a['max_mm']} mm above the base, inner side, "
            f"{a['share']:.0%} of the foot's length from the heel") in sheet


def test_the_mirror_images_arch_support_is_on_its_own_inner_side(pair):
    rounded, _ = pair
    left = insole.mirrored(rounded)
    a, b = rounded.report["arch_fill"], left.report["arch_fill"]
    assert b["y"] == -a["y"] and b["side"] == "inner" and b["max_mm"] == a["max_mm"]


def test_the_sheets_highest_fill_says_when_it_is_the_heel_not_the_arch():
    """As on right scan 2349 (12.0 mm at the heel's back, 10.66 mm arch support): the highest fill is behind the arch
    and taller than it, so the sheet says where it is; an arch as tall as the highest point gets just the number."""
    r = dict(max_fill_mm=12.0, max_fill_at_mm=dict(x=-1.0, y=1.5), foot_max_fill_mm=20.0, foot_max_fill_past_edge=True,
             arch_fill=dict(max_mm=10.66, x=94.0, y=36.5, share=0.4, side="inner"))
    assert insole.fill_row(r) == ("12.0 mm on the insole at the heel, behind the arch support (20.0 mm under the foot, "
                                  "past the outline's edge)")
    r.update(foot_max_fill_mm=12.0, foot_max_fill_past_edge=False)
    assert insole.fill_row(r) == "12.0 mm at the heel, behind the arch support"
    r["arch_fill"]["max_mm"] = 11.8  # within FILL_PAST_EDGE_MM of it: no note
    assert insole.fill_row(r) == "12.0 mm"
