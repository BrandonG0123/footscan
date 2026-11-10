"""The printed clog: generated shapes and synthetic feet with known answers. No number here is from a person.

A shoe built from two ruler numbers alone has a flat footbed; one built on ``synth.curved_foot`` (a SYNTHETIC
foot whose arch stands 14 mm off the floor on the inner side) must carry that foot's first-fit fill in its
floor: the arch less the insole generator's 1 mm relief, on the inner side only.
Shoe coordinates: x forward from the back of the shoe, y toward the foot's left (a right foot's inner side is
+y), z up, the sole on z = 0.
"""

import json
from dataclasses import fields, replace

import numpy as np
import pytest

import synth
from footscan import cli, footwear as fw, insole

RULER = dict(foot_length_mm=260.0, foot_width_mm=97.0)


@pytest.fixture(scope="module")
def plain():
    """A closed-upper shoe from ruler numbers alone: no windows for a probing ray to slip through."""
    return fw.build("right", fw.ShoeParams(style="stone", **RULER))


@pytest.fixture(scope="module")
def curved():
    return insole.from_scan(synth.curved_foot("right", leg=False), "right")


@pytest.fixture(scope="module")
def block():
    """The first-fit insole of the SYNTHETIC block foot (a right one): 11 mm of fill under its arch tunnel, none elsewhere."""
    return insole.from_scan(synth.block_foot(37.0, "right"), "right")


@pytest.fixture(scope="module")
def shod(curved):
    """The default shoe on the SYNTHETIC curved foot's footbed, sized by that foot's own outline."""
    return fw.build("right", fw.ShoeParams(), footbed=curved)


def _hit(mesh, origin, direction):
    """Where a ray from ``origin`` first meets the shoe (None if it meets nothing)."""
    hit, _, _ = mesh.ray.intersects_location([origin], [direction], multiple_hits=False)
    return hit[0] if len(hit) else None


def _floor(mesh, x, y, from_z=45.0):
    """Height of the footbed at (x, y): a ray straight down from inside the shoe."""
    hit = _hit(mesh, [x, y, from_z], [0, 0, -1.0])
    return None if hit is None else float(hit[2])


def test_the_shoe_is_one_closed_solid_standing_on_its_sole(plain, shod):
    for shoe in (plain, shod):
        m = shoe.mesh
        assert m.is_watertight and m.is_winding_consistent and m.volume > 0
        assert m.body_count == 1
        assert m.vertices[:, 2].min() == pytest.approx(0.0, abs=1e-6)   # flat on the bed
        assert m.vertices[:, 0].min() == pytest.approx(0.0, abs=1e-6)   # the back of the shoe at x = 0


def test_no_two_points_of_the_surface_are_a_hair_apart(shod, tmp_path):
    """Cutting the footbed, the opening and the windows leaves hair-length edges; they are welded, so the file
    a slicer reads (rounded to single precision) is still one closed surface."""
    import trimesh
    from scipy.spatial import cKDTree

    assert len(cKDTree(shod.mesh.vertices).query_pairs(fw.WELD_MM)) == 0
    shod.mesh.export(tmp_path / "shoe.stl")
    back = trimesh.load(tmp_path / "shoe.stl")   # an STL has no shared points: they are merged again on reading
    assert back.is_watertight and back.volume == pytest.approx(shod.mesh.volume, rel=1e-4)


@pytest.mark.parametrize("fit", ["snug", "regular", "roomy"])
def test_the_inside_is_the_foot_plus_the_fits_room(fit):
    shoe = fw.build("right", fw.ShoeParams(style="stone", fit=fit, **RULER))
    r, room = shoe.report, fw.FIT[fit]
    assert r["inside"]["length_mm"] == pytest.approx(260.0 + room["toe_room_mm"], abs=0.1)
    assert r["inside"]["width_mm"] == pytest.approx(97.0 + room["width_mm"], abs=0.1)
    assert r["made_for"] == dict(foot_length_mm=260.0, foot_width_mm=97.0, length_from="ruler", width_from="ruler",
                                 fit=fit, sock_mm=0.0)
    # and the shoe itself measures that, not just its report. Length: from the back wall where a heel reaches
    # it (20 mm above the footbed) to the front wall where the toes do (10 mm above it)
    m, sole = shoe.mesh, r["sole"]
    back = min(_hit(m, [60.0, y, sole["under_heel_mm"] + 20.0], [-1.0, 0, 0])[0] for y in np.linspace(-12, 12, 9))
    front = max(_hit(m, [200.0, y, sole["under_ball_mm"] + 10.0], [1.0, 0, 0])[0] for y in np.linspace(-10, 30, 21))
    assert front - back == pytest.approx(r["inside"]["length_mm"], abs=1.0)
    # width: the furthest the walls stand apart across the ball, 12 mm above the footbed
    xs = np.linspace(0.5, 0.9, 41) * r["length_mm"]
    z = sole["under_ball_mm"] + 12.0
    inner = max(_hit(m, [x, 0.0, z + 4.0 * (x < 170)], [0, 1.0, 0])[1] for x in xs)
    outer = min(_hit(m, [x, 0.0, z + 4.0 * (x < 170)], [0, -1.0, 0])[1] for x in xs)
    assert inner - outer == pytest.approx(r["inside"]["width_mm"], abs=1.0)


def test_a_thicker_sock_adds_room_all_round():
    bare = fw.build("right", fw.ShoeParams(style="stone", **RULER)).report["inside"]
    sock = fw.build("right", fw.ShoeParams(style="stone", sock_mm=1.5, **RULER)).report["inside"]
    assert sock["length_mm"] == pytest.approx(bare["length_mm"] + 1.5, abs=0.1)
    assert sock["width_mm"] == pytest.approx(bare["width_mm"] + 3.0, abs=0.1)
    assert sock["roof_over_ball_mm"] == pytest.approx(bare["roof_over_ball_mm"] + 1.5, abs=0.3)


def test_a_long_narrow_foot_gets_a_normal_shoe_not_a_long_thin_one():
    """The foot sets the size; the proportions stay a shoe's. Too narrow or too wide for its length, the inside
    is held at the nearest normal width and the shoe says how far off the foot's own width that is."""
    narrow = fw.build("right", fw.ShoeParams(style="stone", foot_length_mm=280.0, foot_width_mm=70.0)).report
    assert narrow["inside"]["width_mm"] == pytest.approx(fw.BALL_SHARE[0] * narrow["inside"]["length_mm"], abs=0.2)
    assert any("narrow for its length" in w and "room at the sides" in w for w in narrow["warnings"])
    wide = fw.build("right", fw.ShoeParams(style="stone", foot_length_mm=240.0, foot_width_mm=125.0)).report
    assert wide["inside"]["width_mm"] == pytest.approx(fw.BALL_SHARE[1] * wide["inside"]["length_mm"], abs=0.2)
    assert any("wide for its length" in w and "tight" in w for w in wide["warnings"])
    usual = fw.build("right", fw.ShoeParams(style="stone", **RULER)).report
    assert not any("for its length" in w for w in usual["warnings"])


def test_left_is_the_mirror_of_right(plain):
    left = fw.build("left", plain.params)
    assert left.mesh.is_watertight and left.mesh.volume == pytest.approx(plain.mesh.volume, rel=1e-6)
    a = np.asarray(plain.mesh.vertices)
    b = np.asarray(left.mesh.vertices) * [1.0, -1.0, 1.0]
    assert len(a) == len(b)
    key = lambda v: v[np.lexsort(np.round(v, 2).T[::-1])]  # noqa: E731
    assert np.abs(np.sort(a, axis=0) - np.sort(b, axis=0)).max() < 1e-3   # the same points, each axis in order
    assert np.abs(key(a) - key(b)).max() < 0.05
    assert {k: v for k, v in left.report.items() if k not in ("foot", "bed_fit")} == \
           {k: v for k, v in plain.report.items() if k not in ("foot", "bed_fit")}


def test_the_front_is_closed_and_the_back_is_open(plain):
    m, r = plain.mesh, plain.report
    heel, ball = r["sole"]["under_heel_mm"], r["sole"]["under_ball_mm"]
    # over the toes a ray from above lands on the roof, well above the footbed...
    assert _hit(m, [0.85 * r["length_mm"], 5.0, 300.0], [0, 0, -1.0])[2] > ball + 25.0
    # ...and over the heel it goes straight in, down to the footbed
    assert _hit(m, [40.0, 0.0, 300.0], [0, 0, -1.0])[2] == pytest.approx(heel, abs=0.05)
    # behind the heel: a lip up to heel_rim_mm above the footbed, nothing above it until the instep
    assert _hit(m, [-50.0, 0.0, heel + r["heel_rim_mm"] - 4.0], [1.0, 0, 0])[0] < 1.0
    over_the_lip = _hit(m, [-50.0, 0.0, heel + r["heel_rim_mm"] + 4.0], [1.0, 0, 0])
    assert over_the_lip is None or over_the_lip[0] > 0.3 * r["length_mm"]


def test_the_floor_has_no_sideways_tilt(plain):
    """A heel-to-ball drop is front to back only. Any tilt across the foot would be posting, which a first fit
    never has: the shoe has no setting for it, and its floor is level across at every point along it."""
    assert not any("post" in f.name or "tilt" in f.name or "wedge" in f.name for f in fields(fw.ShoeParams))
    r = plain.report
    for x in np.linspace(30.0, 0.8 * r["length_mm"], 12):
        assert _floor(plain.mesh, x, 14.0) == pytest.approx(_floor(plain.mesh, x, -14.0), abs=0.02)
    assert _floor(plain.mesh, 40.0, 0.0) - _floor(plain.mesh, 0.72 * r["length_mm"], 0.0) == pytest.approx(plain.params.drop_mm, abs=0.05)


@pytest.mark.parametrize("foot, inner", [("right", 1.0), ("left", -1.0)])
def test_the_footbed_is_the_first_fit_insoles_surface_built_into_the_floor(foot, inner):
    """SYNTHETIC block foot: 240 x 90 mm, a 12 mm-high tunnel under its inner 36 mm from 70 to 150 mm. Its
    first-fit fill is 11 mm there (12 less the relief) and nothing anywhere else, and that is exactly what the
    shoe's floor carries: under the arch, on the inner side only (a left foot's is the other side), no higher
    than the insole generator made it."""
    block = insole.from_scan(synth.block_foot(37.0, foot), foot)
    shoe = fw.build(foot, fw.ShoeParams(style="stone"), footbed=block)
    fb = shoe.report["footbed"]
    assert fb["max_fill_mm"] == block.report["max_fill_mm"] == pytest.approx(11.0, abs=0.05)
    assert fb["posting_deg"] == dict(rearfoot=0.0, forefoot=0.0) and fb["relief_mm"] == block.params.relief_mm
    assert shoe.report["made_for"] == dict(foot_length_mm=240.0, foot_width_mm=90.0, length_from="scan", width_from="scan",
                                           fit="regular", sock_mm=0.0)
    assert fb["scaled_percent"] == 0.0
    # the same shoe with a flat floor: the difference between the two floors is the fill. The foot's heel
    # stands 3.5 mm in from the back of the shoe (the upper, and the rounding of the heel's end)
    flat = fw.build(foot, replace(shoe.params, foot_length_mm=240.0, foot_width_mm=90.0))
    assert flat.report["inside"] == shoe.report["inside"]
    fill = {(x, y): _floor(shoe.mesh, x, inner * y, 36.0) - _floor(flat.mesh, x, inner * y, 36.0)   # y: toward the inner side
            for x in np.arange(40.0, 205.0, 5.0) for y in np.arange(-30.0, 31.0, 3.0)}
    for (x, y), f in fill.items():
        if 85.0 <= x <= 140.0 and y >= 15.0:
            assert f == pytest.approx(11.0, abs=0.1), (x, y)          # under the tunnel
        elif x <= 65.0 or x >= 160.0 or y <= 0.0:
            assert abs(f) < 0.05, (x, y)                              # heel, ball, toes and the whole outer side
        assert -0.05 < f < 11.05, (x, y)                              # never above the insole's own fill
    # a block's square toes don't fit a shoe's rounded front, and the shoe says so
    assert any("wider than the shoe's inside at the toes" in w for w in shoe.report["warnings"])


def test_a_real_shaped_footbed_stays_within_the_insoles_own_fill(curved, shod):
    """SYNTHETIC curved foot (a smooth 14 mm arch on the inner side): the floor rises under the arch on the
    inner side, rests flat under the heel and along the outer side, and is nowhere above the insole's fill."""
    fb = shod.report["footbed"]
    assert fb["max_fill_mm"] == pytest.approx(curved.report["max_fill_mm"], abs=0.05)
    flat = fw.build("right", replace(shod.params, foot_length_mm=fb["scan_length_mm"], foot_width_mm=fb["scan_width_mm"]))
    fill = {(x, y): _floor(shod.mesh, x, y) - _floor(flat.mesh, x, y)
            for x in np.arange(70.0, 160.0, 5.0) for y in np.arange(-24.0, 33.0, 4.0)}
    highest = max(fill, key=fill.get)
    assert 0.7 * fb["max_fill_mm"] < fill[highest] <= fb["max_fill_mm"] + 0.1
    assert highest[1] > 10.0 and 95.0 < highest[0] < 135.0            # under the arch, on the inner side
    assert max(v for (x, y), v in fill.items() if -20.0 <= y <= -4.0) < 0.5   # the outer side rests flat
    assert min(fill.values()) > -0.05
    assert _floor(shod.mesh, 35.0, 0.0) == pytest.approx(_floor(flat.mesh, 35.0, 0.0), abs=0.3)   # under the heel


def test_a_ruler_wins_over_the_scans_size_and_the_footbed_is_scaled_to_it(curved, shod):
    fb = shod.report["footbed"]
    longer = fw.build("right", fw.ShoeParams(foot_length_mm=round(fb["scan_length_mm"] * 1.05, 1),
                                             foot_width_mm=fb["scan_width_mm"]), footbed=curved)
    r = longer.report
    assert r["made_for"]["length_from"] == "ruler" and r["made_for"]["foot_length_mm"] == pytest.approx(fb["scan_length_mm"] * 1.05, abs=0.06)
    assert r["inside"]["length_mm"] == pytest.approx(r["made_for"]["foot_length_mm"] + 12.0, abs=0.1)
    assert r["footbed"]["scaled_percent"] == pytest.approx(5.0, abs=0.1)
    assert r["footbed"]["max_fill_mm"] == pytest.approx(fb["max_fill_mm"], abs=0.05)   # heights are never scaled
    assert any("sized by the ruler" in w and "scaled +5.0% along and across" in w for w in r["warnings"])
    assert not any("scaled" in w for w in shod.report["warnings"])
    with pytest.raises(fw.FootwearError, match="mm long and the ruler .* too far apart to be the same foot"):
        fw.build("right", fw.ShoeParams(foot_length_mm=round(fb["scan_length_mm"] * 1.2, 1), foot_width_mm=fb["scan_width_mm"]),
                 footbed=curved)


def test_a_scan_that_reads_short_is_scaled_the_same_along_and_across_and_no_higher(block):
    """SYNTHETIC block foot (240 mm long, its fill a level 11 mm over the 80 x 36 mm arch tunnel), given a ruler
    length of 264 mm: the scan reads 10% short, so the patch of fill is 10% longer and 10% wider (1.21 times
    the area), and still 11 mm high."""
    import shapely

    def patch(length):
        bed = fw.Footbed(block, "right")
        bed.size_to(length, None)
        p = fw.ShoeParams(style="stone")
        loft = fw._loft_for(fw.size_inside(length or 240.0, 99.0, p), p, 13.0, 0.0, 0)
        bed.place(loft.floor.polygon, loft.inside_ends()[0])
        foot = bed.in_shoe("outline")
        x0, y0, x1, y1 = foot.bounds
        X, Y = np.meshgrid(np.arange(x0, x1, 0.25), np.arange(y0, y1, 0.25))
        H = np.where(shapely.contains_xy(foot, X, Y), bed.height(X, Y), 0.0)
        return (H > 5.5).sum() * 0.25 ** 2, np.ptp(X[H > 5.5]), H.max(), foot.bounds[2] - foot.bounds[0]

    (area, along, top, length), (area2, along2, top2, length2) = patch(None), patch(264.0)
    assert area == pytest.approx(80.0 * 36.0, rel=0.02) and along == pytest.approx(80.0, abs=1.0)
    assert area2 / area == pytest.approx(1.21, abs=0.01) and along2 / along == pytest.approx(1.10, abs=0.01)
    assert top == pytest.approx(11.0, abs=0.05) and top2 == pytest.approx(11.0, abs=0.05)
    assert length2 / length == pytest.approx(1.10, abs=0.005)


def test_the_rulers_width_sizes_the_shoe_and_is_only_compared_with_the_scans(block):
    """SYNTHETIC block foot, 90 mm across. A ruler's width sets the shoe's width and never stretches the
    footbed; a few percent between the two is a standing foot spreading and isn't mentioned, more is said, and
    far more isn't the same foot."""
    near = fw.build("right", fw.ShoeParams(style="stone", foot_width_mm=93.0), footbed=block).report
    assert near["made_for"]["width_from"] == "ruler" and near["inside"]["width_mm"] == pytest.approx(95.0, abs=0.1)
    assert near["footbed"]["scaled_percent"] == 0.0 and not any("across the ball" in w for w in near["warnings"])
    far = fw.build("right", fw.ShoeParams(style="stone", foot_width_mm=98.0), footbed=block).report
    assert far["footbed"]["scaled_percent"] == 0.0
    assert any("90.0 mm across the ball, the ruler 98.0 mm" in w and "worth measuring again" in w for w in far["warnings"])
    with pytest.raises(fw.FootwearError, match="across the ball and the ruler 110 mm: too far apart"):
        fw.build("right", fw.ShoeParams(style="stone", foot_width_mm=110.0), footbed=block)


def _wall(mesh, x, z, toward):
    """Where the inside's wall stands at (x, z): a level ray from the middle of the shoe toward +y or -y."""
    return float(_hit(mesh, [x, 0.0, z], [0.0, toward, 0.0])[1])


def _skin(mesh, x, z, side):
    """Where the outside stands at (x, z) on the +y or -y side: a level ray from far outside, inward."""
    return float(_hit(mesh, [x, 200.0 * side, z], [0.0, -side, 0.0])[1])


def test_the_wall_is_let_out_where_the_foot_is_wider_above_the_floor_and_the_sole_stands_under_it(block):
    """SYNTHETIC: the block foot with a 10 mm block standing out of its inner side from 14 to 25 mm up, over
    95 to 135 mm from the heel (as a flat foot's inner side stands out over its own footprint). What stands on
    the floor is the same foot, so it is stood in the shoe exactly as without the bulge; the inner wall is
    10 mm further out beside the bulge and nowhere else, the outside and the sole with it (the ground under
    the let-out wall), and the footbed under the bulge is its underside less the relief."""
    bulged = insole.from_scan(synth.block_foot(37.0, "right", inner_bulge=10.0), "right")
    p = fw.ShoeParams(style="stone", foot_length_mm=240.0, foot_width_mm=90.0)
    a, b = fw.build("right", p, footbed=block), fw.build("right", p, footbed=bulged)
    fa, fb = a.report["footbed"], b.report["footbed"]
    assert (fb["turned_deg"], fb["slid_mm"]) == (fa["turned_deg"], fa["slid_mm"])     # stood by its sole
    assert a.report["inside"] == b.report["inside"]                                    # the same standard shape
    assert fb["let_out"]["inner"]["max_mm"] == pytest.approx(fa["let_out"]["inner"]["max_mm"] + 10.0, abs=1.0)
    assert fb["let_out"]["outer"] == fa["let_out"]["outer"]
    assert any("wider above the floor than the standard shape on its inner side" in w for w in b.report["warnings"])
    for x in (105.0, 118.0, 130.0):                       # beside the bulge (the heel stands 3.5 mm into the shoe)
        assert _wall(b.mesh, x, 38.0, 1.0) - _wall(a.mesh, x, 38.0, 1.0) == pytest.approx(10.0, abs=0.7), x
        assert _wall(b.mesh, x, 38.0, -1.0) == pytest.approx(_wall(a.mesh, x, 38.0, -1.0), abs=0.05), x
        for z in (2.0, 10.0, 30.0):                       # the sole's side near the ground and half way up, the upper
            assert _skin(b.mesh, x, z, 1.0) - _skin(a.mesh, x, z, 1.0) == pytest.approx(10.0, abs=0.7), (x, z)
            assert _skin(b.mesh, x, z, -1.0) == pytest.approx(_skin(a.mesh, x, z, -1.0), abs=0.05), (x, z)
    for x in (45.0, 175.0):                               # well behind it and well in front: as without
        assert _wall(b.mesh, x, 38.0, 1.0) == pytest.approx(_wall(a.mesh, x, 38.0, 1.0), abs=0.3), x
    # the bulge is held: what still hangs over is the block's square toes, as without it
    assert fb["overhang"]["where"] == "toes" and fb["overhang"]["max_mm"] == pytest.approx(fa["overhang"]["max_mm"], abs=0.5)
    # under the bulge the footbed is its underside (14 mm up) less the 1 mm relief; beside it, the tunnel's 11
    edge = _wall(a.mesh, 118.0, 38.0, 1.0)
    assert _floor(b.mesh, 118.0, edge + 5.0) - _floor(a.mesh, 118.0, edge - 12.0) == pytest.approx(13.0 - 11.0, abs=0.15)
    # ruler numbers alone: nothing is known of the foot's sides, so nothing is let out
    assert fw.build("right", p).report["footbed"] is None


def test_what_stands_out_above_the_floor_does_not_move_where_the_foot_stands(block):
    """Two made-up feet with the same outline near the floor (the shoe's own floor outline, 8 mm smaller all
    round, a rubber band round it), one of them up to 17 mm wider above the floor along its inner side from
    heel to arch, as a flat foot is. Both are stood in the shoe in exactly the same place: a foot stands where
    its sole does. (Stood by its whole outline instead, the wider one is moved toward its bulge.)"""
    import shapely

    p = fw.ShoeParams(style="stone")
    loft = fw._loft_for(fw.size_inside(240.0, 90.0, p), p, 13.0, 0.0, 0)
    floor, L = loft.floor.polygon, loft.L
    standing = floor.buffer(-8.0).convex_hull
    bulge = floor.buffer(9.0).intersection(shapely.box(0.15 * L, float(loft.floor.middle(0.3 * L)), 0.5 * L, 200.0))
    fits = []
    for whole in (standing, standing.union(bulge)):
        bed = fw.Footbed(block, "right")
        bed.outline, bed.standing, bed.heel_x = whole, standing, whole.bounds[0]
        fits.append(bed.place(floor, loft.inside_ends()[0]))
        assert bed.in_shoe("standing").difference(floor).area == 0.0     # the sole is on the floor
    assert (fits[0]["turned_deg"], fits[0]["slid_mm"]) == (fits[1]["turned_deg"], fits[1]["slid_mm"])


def test_the_shoe_is_never_narrower_than_the_standard_shape(block):
    """SYNTHETIC block foot (90 mm across) in a shoe sized by a ruler width of 98 mm: across the ball the
    standard shape is wider than the scanned foot, and stays exactly as wide (letting out only ever adds room);
    further back, where the block's straight sides are wider than a shoe's waist, it is wider than standard."""
    p = fw.ShoeParams(style="stone", foot_length_mm=240.0, foot_width_mm=98.0)
    scanned, standard = fw.build("right", p, footbed=block), fw.build("right", p)
    for x in np.arange(40.0, 215.0, 12.5):
        for side in (1.0, -1.0):
            more = side * (_wall(scanned.mesh, x, 36.0, side) - _wall(standard.mesh, x, 36.0, side))
            assert more > -0.05, (x, side)
            if 175.0 <= x <= 195.0:
                assert abs(more) < 0.05, (x, side)                      # across the ball: the standard shape
    assert max(_wall(scanned.mesh, x, 36.0, 1.0) - _wall(standard.mesh, x, 36.0, 1.0) for x in (90.0, 105.0, 120.0)) > 2.0


def test_a_foot_too_wide_to_let_out_for_is_let_out_to_the_limit_and_the_rest_is_said(block):
    """SYNTHETIC: the block foot with a 40 mm block standing out of its inner side. The inside is let out by
    the limit and no more, and the sheet says where the foot is still wider than the shoe."""
    wide = insole.from_scan(synth.block_foot(37.0, "right", inner_bulge=40.0), "right")
    p = fw.ShoeParams(style="stone", foot_length_mm=240.0, foot_width_mm=90.0)
    r = fw.build("right", p, footbed=wide).report
    assert r["footbed"]["let_out"]["inner"]["max_mm"] == pytest.approx(fw.LET_OUT_MAX_MM, abs=0.1)
    plain = fw.build("right", p, footbed=block).report["footbed"]["let_out"]["inner"]["max_mm"]
    over = r["footbed"]["overhang"]
    assert over["where"] == "arch, inner side" and over["max_mm"] == pytest.approx(plain + 40.0 - fw.LET_OUT_MAX_MM, abs=1.0)
    assert any("wider than the shoe's inside at the arch, inner side" in w and "It may press there" in w for w in r["warnings"])


def test_the_whole_heel_goes_against_the_back_not_only_its_footprint(block):
    """SYNTHETIC: the block foot with a 4 mm block standing out of the back of its heel from 14 to 25 mm up (a
    heel reaches further back above the floor than on it). The foot is 244 mm long then, the inside 12 mm
    longer than that, and the foot stands with that bulge against the back: the same room past its toes as
    the plain block has, and nothing hanging over behind."""
    heeled = insole.from_scan(synth.block_foot(37.0, "right", heel_bulge=4.0), "right")
    p = fw.ShoeParams(style="stone")
    a, b = fw.build("right", p, footbed=block).report, fw.build("right", p, footbed=heeled).report
    assert b["made_for"]["foot_length_mm"] == pytest.approx(244.0, abs=0.1) and b["inside"]["length_mm"] == pytest.approx(256.0, abs=0.1)
    assert b["footbed"]["room_past_scanned_toes_mm"] == pytest.approx(a["footbed"]["room_past_scanned_toes_mm"], abs=0.3)
    assert b["footbed"]["room_past_scanned_toes_mm"] == pytest.approx(12.0, abs=1.5)   # (less what the turn takes)
    assert (b["footbed"]["turned_deg"], b["footbed"]["slid_mm"]) == (a["footbed"]["turned_deg"], a["footbed"]["slid_mm"])
    assert b["footbed"]["overhang"]["where"] == "toes"


def test_the_footbed_runs_level_past_the_foots_edge_without_the_dip_the_insole_has_there(block):
    """SYNTHETIC block foot: its tunnel runs out through the inner side, so the true fill is a level 11 mm right
    up to the foot's edge. The insole's own surface dips at that edge (its smoothing blends in the bare floor
    beside the foot); the shoe's footbed doesn't build the dip in: just inside the edge, at it and past it, it
    is what the insole's surface is 3 mm in, and never above the true 11 mm."""
    s = block.surface
    j = int(np.argmin(abs(s["xs"] - 110.0)))
    under = np.flatnonzero(s["under_foot"][:, j])
    assert s["fill"][under[-1], j] < 7.0 and s["fill"][under[-7], j] == pytest.approx(10.84, abs=0.1)   # the insole's dip
    bed = fw.Footbed(block, "right")
    p = fw.ShoeParams(style="stone")
    loft = fw._loft_for(fw.size_inside(240.0, 90.0, p), p, 13.0, 0.0, 0)
    bed.place(loft.floor.polygon, loft.inside_ends()[0])
    foot = bed.in_shoe("outline")
    for x in foot.bounds[0] + np.array([95.0, 110.0, 130.0]):
        edge = fw._across(foot, np.array([x]))[1][0]                  # the foot's inner edge here
        h = bed.height(np.full(7, x), edge + np.array([-3.5, -2.0, -1.0, -0.25, 0.5, 2.0, 5.0]))
        assert np.all(np.abs(h - 10.85) < 0.2) and h.max() <= 11.0, (x, h)


def test_the_footbed_climbs_between_the_insoles_two_caps_instead_of_stepping(block):
    """SYNTHETIC: an insole whose fill stands at both of the generator's caps, 12 mm round the heel and 20 mm
    from there on (as a sole that is high everywhere would leave it), so its surface steps 8 mm on the line
    where the heel zone ends (30% of the length). In the shoe that step would be a ledge inside the wall: the
    footbed climbs it over the next 15% of the length instead, never above the insole's own surface."""
    s = block.surface
    x0, length = 0.0, 240.0
    stepped = np.where(s["under_foot"], np.where(s["xs"][None, :] <= x0 + 0.30 * length, 12.0, 20.0), 0.0)
    bed = fw.Footbed(replace(block, surface={**s, "fill": stepped}), "right")
    p = fw.ShoeParams(style="stone")
    loft = fw._loft_for(fw.size_inside(240.0, 90.0, p), p, 13.0, 0.0, 0)
    fit = bed.place(loft.floor.polygon, loft.inside_ends()[0])
    heel = bed.in_shoe("outline").bounds[0]
    x = heel + np.arange(20.0, 160.0, 0.5)
    h = bed.height(x, np.full(len(x), -10.0))
    assert h[x < heel + 0.29 * length].max() == pytest.approx(12.0, abs=0.01)
    assert h[x > heel + 0.46 * length].min() == pytest.approx(20.0, abs=0.01)
    assert np.abs(np.diff(h)).max() < 0.2                                   # per half millimetre: a slope, not a step
    assert np.all(np.diff(h) > -1e-9)
    assert abs(fit["turned_deg"]) < 3.0                                      # (so "along x" is along the foot)


def test_a_style_changes_the_outside_never_the_inside(plain):
    vent = fw.build("right", fw.ShoeParams(style="vent", **RULER))
    stream = fw.build("right", fw.ShoeParams(style="stream", **RULER))
    assert vent.report["inside"] == stream.report["inside"] == plain.report["inside"]
    # the walls stand in the same place: across the shoe 6 mm above the footbed (below any window), at the heel
    # and at the ball; the three soles differ in thickness, so heights are taken from each shoe's own floor
    for x in (45.0, 150.0, 200.0):
        wall = [[_hit(s.mesh, [x, 0.0, _floor(s.mesh, x, 0.0) + 6.0], [0, d, 0])[1] for d in (1.0, -1.0)]
                for s in (plain, vent, stream)]
        assert np.ptp(np.array(wall), axis=0).max() < 0.02
    # what does differ: the windows, the sole's thickness, how far it stands out at the ground
    assert plain.report["pattern"]["count"] == 0 and vent.report["pattern"]["count"] > 50
    assert stream.report["pattern"]["window_mm"][0] > 2 * stream.report["pattern"]["window_mm"][1]
    assert stream.report["sole"]["under_ball_mm"] > vent.report["sole"]["under_ball_mm"] > plain.report["sole"]["under_ball_mm"]
    assert stream.report["width_mm"] > vent.report["width_mm"] > plain.report["width_mm"]
    closed = fw.build("right", fw.ShoeParams(style="vent", openness=0.0, **RULER))
    assert closed.report["pattern"]["count"] == 0 and closed.mesh.volume > vent.mesh.volume + 1000.0


def _cut_area(mesh, origin, normal):
    """How much material a flat cut through the shoe goes through (mm2)."""
    return float(mesh.section(plane_origin=origin, plane_normal=normal).to_2D()[0].area)


def test_windows_stay_out_of_the_sole_the_toe_cap_and_the_heel():
    """The same shoe with its windows as open as they go and with none: cut across through the heel and
    through the toe cap, and level through the sole, the two are the same; only in between do they differ."""
    windowed, closed = (fw.build("right", fw.ShoeParams(style="vent", openness=o, **RULER)) for o in (0.5, 0.0))
    r = windowed.report
    assert windowed.mesh.body_count == 1 and 0.2 < r["pattern"]["openness"] <= 0.5 and r["pattern"]["count"] > 50
    L = r["inside"]["floor_length_mm"]
    cuts = [([x, 0, 0], [1, 0, 0]) for x in np.arange(2.0, fw.END_ROUND[0] * L + 6.0, 2.0)]                      # the heel
    cuts += [([x, 0, 0], [1, 0, 0]) for x in np.arange((1 - fw.END_ROUND[1]) * L, r["length_mm"] - 2.0, 2.0)]   # the toe cap
    cuts += [([0, 0, z], [0, 0, 1]) for z in np.arange(2.0, r["sole"]["under_ball_mm"], 2.0)]                   # the sole
    assert len(cuts) > 30
    for origin, normal in cuts:
        assert _cut_area(windowed.mesh, origin, normal) == pytest.approx(_cut_area(closed.mesh, origin, normal), abs=0.05), origin
    assert _cut_area(windowed.mesh, [0.7 * L, 0, 0], [1, 0, 0]) < _cut_area(closed.mesh, [0.7 * L, 0, 0], [1, 0, 0]) - 5.0
    # the sole: a level cut half way up it is one solid patch with no hole in it
    cut = windowed.mesh.section(plane_origin=[0, 0, r["sole"]["under_ball_mm"] / 2], plane_normal=[0, 0, 1]).to_2D()[0]
    assert len(cut.polygons_full) == 1 and len(cut.polygons_full[0].interiors) == 0
    with pytest.raises(fw.FootwearError, match="between 0 and 0.5"):
        fw.build("right", fw.ShoeParams(style="vent", openness=0.8, **RULER))


def test_windows_keep_clear_of_the_openings_edge():
    """Just under the opening's edge, all the way along it, the wall is whole: a ray from the middle of the
    shoe out to either side meets it where the windowless shoe's wall is."""
    p = fw.ShoeParams(style="vent", openness=0.5, **RULER)
    windowed, closed = fw.build("right", p), fw.build("right", replace(p, openness=0.0))
    st = fw.STYLES["vent"]
    loft = fw._loft_for(fw.size_inside(260.0, 97.0, p), p, st["sole_mm"], st["flare_mm"], st["grooves"])
    edge = fw._opening(loft, p)[0]
    xs = np.arange(0.12 * loft.L, p.throat * loft.L - 8.0, 1.0)
    origins = np.array([[x - loft.x0, float(loft.top_y(x)), float(edge(x)) - below] for x in xs for below in (1.5, 4.0)])
    for side in (1.0, -1.0):
        walls = []
        for shoe in (windowed, closed):
            hit, ray, _ = shoe.mesh.ray.intersects_location(origins, np.tile([0.0, side, 0.0], (len(origins), 1)), multiple_hits=False)
            assert len(hit) == len(origins)
            walls.append(hit[np.argsort(ray), 1])
        assert np.abs(walls[0] - walls[1]).max() < 0.01


def test_no_window_opens_onto_the_footbed():
    """SYNTHETIC: the block foot's fill made 1.6 times as high (17.6 mm, under the 20 mm cap), so the footbed
    stands behind the inner wall where the lowest windows would be. Those windows are left out, and a level cut
    through the footbed there is the same with windows as without."""
    import functools

    import shapely

    block = insole.from_scan(synth.block_foot(37.0, "right"), "right")
    tall = replace(block, surface={**block.surface, "fill": block.surface["fill"] * 1.6})
    p = fw.ShoeParams(style="vent")
    low, high, closed = (fw.build("right", q, footbed=f) for q, f in ((p, block), (p, tall), (replace(p, openness=0.0), tall)))
    assert high.report["footbed"]["max_fill_mm"] == pytest.approx(17.6, abs=0.1)
    assert high.report["pattern"]["count"] < low.report["pattern"]["count"]

    def cut(shoe, z):   # the material a level cut goes through, under the arch on the inner side
        loops = [shapely.Polygon(d[:, :2]) for d in shoe.mesh.section(plane_origin=[0, 0, z], plane_normal=[0, 0, 1]).discrete]
        return functools.reduce(lambda a, b: a.symmetric_difference(b), loops).intersection(shapely.box(90.0, 0.0, 135.0, 90.0))

    top = _floor(high.mesh, 110.0, 25.0)                      # the footbed's surface under the arch
    assert top - _floor(low.mesh, 110.0, 25.0) == pytest.approx(0.6 * 11.0, abs=0.15)
    for below in (1.0, 2.5, 4.0):
        assert cut(high, top - below).area == pytest.approx(cut(closed, top - below).area, abs=0.05)


def test_the_upper_is_its_thickness_everywhere_even_where_the_roof_slopes():
    """SYNTHETIC (a generated shape): from points all over the inside's surface, the nearest the outside comes.
    Down the slope from the instep to the toes a roof raised by the thickness straight up would be thinner
    than that measured square to it."""
    import trimesh

    p = fw.ShoeParams(style="stone", **RULER)
    loft = fw._loft_for(fw.size_inside(260.0, 97.0, p), p, 13.0, 0.0, 0)

    def as_mesh(solid):
        mm = solid.to_mesh()
        return trimesh.Trimesh(np.asarray(mm.vert_properties)[:, :3], np.asarray(mm.tri_verts), process=False)

    pts, _ = trimesh.sample.sample_surface(as_mesh(loft.inside()), 3000, seed=1)
    pts = pts[pts[:, 2] > loft.floor_z(pts[:, 0]) + 0.5]               # not its floor: the sole is under that
    gap = trimesh.proximity.closest_point(as_mesh(loft.outside()), pts)[1]
    assert gap.min() > 0.92 * p.upper_mm and np.median(gap) == pytest.approx(p.upper_mm, abs=0.1)


@pytest.mark.parametrize("length, width", [(180.0, 68.0), (330.0, 125.0)])
@pytest.mark.parametrize("style, toe, fit", [("vent", "round", "regular"), ("stream", "square", "roomy"), ("stone", "tapered", "snug")])
def test_every_style_builds_at_both_ends_of_adult_sizes(length, width, style, toe, fit):
    shoe = fw.build("right", fw.ShoeParams(foot_length_mm=length, foot_width_mm=width, style=style, toe=toe, fit=fit))
    assert shoe.mesh.is_watertight and shoe.mesh.body_count == 1
    assert shoe.report["inside"]["length_mm"] == pytest.approx(length + fw.FIT[fit]["toe_room_mm"], abs=0.1)
    assert shoe.report["height_mm"] < 0.4 * shoe.report["length_mm"]


def test_the_toe_shape_changes_the_front_only():
    lengths = {}
    for toe in ("tapered", "round", "square"):
        r = fw.build("right", fw.ShoeParams(style="stone", toe=toe, **RULER))
        at = r.mesh.vertices[np.abs(r.mesh.vertices[:, 0] - 0.96 * r.report["length_mm"]) < 1.0]
        lengths[toe] = np.ptp(at[:, 1])
        assert r.report["inside"]["width_mm"] == pytest.approx(99.0, abs=0.1)
    assert lengths["tapered"] + 5.0 < lengths["round"] < lengths["square"] - 5.0   # width across, just behind the tip


def test_a_shoe_too_long_for_the_bed_says_so(plain):
    assert plain.report["bed_fit"]["fits"] and "turned" in plain.report["bed_fit"]["how"]   # 278 mm: only cornerwise
    big = fw.build("right", fw.ShoeParams(style="stone", foot_length_mm=320.0, foot_width_mm=118.0)).report
    assert not big["bed_fit"]["fits"]
    assert any("bigger printer" in w for w in big["warnings"])


def test_what_isnt_a_shoe_is_refused(curved):
    for bad in (dict(style="boot"), dict(fit="tight"), dict(toe="pointed"), dict(cushion="hard"), dict(sole_mm=3.0),
                dict(drop_mm=30.0), dict(upper_mm=0.8), dict(throat=0.9), dict(heel_rim_mm=5.0), dict(sock_mm=9.0),
                dict(foot_length_mm=26.0)):                        # centimetres
        with pytest.raises(fw.FootwearError):
            fw.build("right", fw.ShoeParams(**{**RULER, **bad}))
    with pytest.raises(fw.FootwearError, match="length and width"):
        fw.build("right", fw.ShoeParams())                         # no ruler numbers and no scan
    with pytest.raises(fw.FootwearError, match="right foot's and the shoe a left"):
        fw.build("left", fw.ShoeParams(), footbed=curved)
    with pytest.raises(fw.FootwearError, match="left.*right"):
        fw.build("both", fw.ShoeParams(**RULER))


def test_a_mirrored_shoe_says_it_was_not_made_from_that_foots_scan(shod):
    left = fw.mirrored(shod)
    assert left.foot == "left" and left.report["foot"] == "left" and left.report["mirrored_from"] == "right"
    assert left.mesh.is_watertight and left.mesh.volume == pytest.approx(shod.mesh.volume, rel=1e-9)
    assert np.allclose(left.mesh.bounds[:, 1], -shod.mesh.bounds[::-1, 1])
    assert "mirror image" in left.report["warnings"][0] and "not made from a scan of the left foot" in left.report["warnings"][0]
    assert shod.report["foot"] == "right" and "mirrored_from" not in shod.report      # the original is untouched
    assert "mirror image" in fw.summary_html(left, "x")


def test_the_files_carry_the_safety_rules_and_say_what_is_untested(curved, shod, tmp_path):
    files = fw.write_outputs(shod, tmp_path, "right-clog", "SYNTHETIC curved foot", synthetic=True)
    sheet = open(files["summary"], encoding="utf-8").read()
    for must in ("NOT A MEDICAL DEVICE", "not equivalent to, or a substitute for, a prescribed orthotic",
                 "not for tennis, running or any other sport", "This shoe is not for sport, whoever signs",
                 "SYNTHETIC TEST GEOMETRY", "No posting, no correction, one stiffness", "0.0&deg; (none)",
                 "standard shape in this foot's size", fw.UNTESTED, "Clinician review", "Signature",
                 "walking and casual wear", "not approved", "First wear indoors"):
        assert must in sheet, must
    # the break-in is the insole sheet's, word for word (docs/SAFETY.md, requirement 2)
    assert fw.BREAK_IN_HTML in sheet and fw.BREAK_IN_HTML in insole.summary_html(curved, "x")
    assert "Day 1: 1 h" in fw.BREAK_IN_HTML and "Stop at once" in fw.BREAK_IN_HTML
    # a shoe made from a real scan isn't labelled synthetic
    assert "SYNTHETIC" not in fw.summary_html(shod, "a scan")

    notes = open(files["notes"], encoding="utf-8").read()
    assert "NOT A MEDICAL DEVICE" in notes and "not for sport" in notes and fw.UNTESTED in notes
    assert "100%" in notes and f"{shod.report['length_mm']} x {shod.report['width_mm']}" in notes

    back = insole.read_3mf(files["threemf"])
    assert back["unit"] == "millimeter" and len(back["faces"]) == len(shod.mesh.faces)
    assert "NOT A MEDICAL DEVICE" in back["metadata"]["Description"] and "SYNTHETIC" in back["metadata"]["Description"]
    t = np.array(back["transform"]).reshape(4, 3)
    on_bed = back["vertices"] @ t[:3] + t[3]
    assert on_bed[:, :2].min() > 0 and on_bed[:, :2].max() < shod.params.bed_mm and on_bed[:, 2].min() == pytest.approx(0, abs=1e-3)

    saved = json.loads(open(files["json"], encoding="utf-8").read())
    assert saved["synthetic"] is True and saved["foot"] == "right" and saved["params"]["style"] == "vent"
    assert saved["footbed"]["max_fill_mm"] == shod.report["footbed"]["max_fill_mm"]
    for view in fw.VIEWS:
        assert open(files[f"picture_{view}"], "rb").read(8) == b"\x89PNG\r\n\x1a\n"


def test_a_flat_shoes_sheet_says_there_is_no_footbed_from_a_scan(plain):
    assert any("no sole scan" in w for w in plain.report["warnings"]) and plain.report["footbed"] is None
    sheet = fw.summary_html(plain, "ruler only")
    assert "The footbed is flat" in sheet and "no arch fill and no shaped heel cup" in sheet


def test_pictures_show_the_shoe_from_every_side(shod):
    pics = fw.pictures(shod)
    assert set(pics) == set(fw.VIEWS) | {"views"}
    side = pics["side"]
    drawn = (side < 250).any(axis=2)
    assert side.dtype == np.uint8 and 0.25 < drawn.mean() < 0.9
    # half a millimetre a pixel: the side view is as long as the shoe
    cols = np.flatnonzero(drawn.any(axis=0))
    assert (cols[-1] - cols[0] + 1) * fw.PICTURE_MM_PER_PX == pytest.approx(shod.report["length_mm"], abs=2.0)
    # no pinholes: inside the sole's band every pixel is drawn
    rows = np.flatnonzero(drawn.any(axis=1))
    band = drawn[rows[-1] - 20:rows[-1] - 4, cols[0] + 20:cols[-1] - 20]
    assert band.all()


def test_a_sole_up_phone_scan_makes_the_shoe_the_way_the_studio_makes_the_insole():
    """SYNTHETIC sole-up scan (as the iPhone app hands one over): prepared exactly as for an insole, whose
    surface is then the footbed; the insole's own notes travel with the shoe."""
    scan = synth.sole_up_capture(synth.curved_foot("right"))
    shoe = fw.from_scan(scan, "right", fw.ShoeParams(style="stone"), kind="sole_up")
    fb = shoe.report["footbed"]
    assert fb["prep"]["kind"] == "sole_up" and fb["max_fill_mm"] == pytest.approx(synth.CURVED_ARCH_MM - 1.0, abs=0.8)
    assert shoe.report["made_for"]["length_from"] == "scan"
    assert shoe.report["made_for"]["foot_length_mm"] == pytest.approx(248.5, abs=2.5)   # curved_plan: 0 to 250
    assert "Sole up" in fw.summary_html(shoe, "x")                                       # how the foot was captured


def test_the_command_writes_a_pair_from_one_scan_and_refuses_nonsense(tmp_path, capsys):
    scan = tmp_path / "foot.ply"
    synth.curved_foot("right", leg=False).export(scan)
    out = tmp_path / "out"
    assert cli.main(["footwear", "--foot", "right", "--scan", str(scan), "--style", "stream", "--pair", "-o", str(out)]) == 0
    said = capsys.readouterr()
    assert "right clog (stream)" in said.out and "left clog (stream)" in said.out and "NOT A MEDICAL DEVICE" in said.out
    assert "mirror image" in said.err
    for foot in ("right", "left"):
        for end in (".3mf", ".stl", "-summary.html", "-print-notes.txt", ".json", "-views.png"):
            assert (out / f"{foot}-clog{end}").stat().st_size > 500
    assert json.loads((out / "left-clog.json").read_text())["mirrored_from"] == "right"

    assert cli.main(["footwear", "--foot", "right", "--length", "26", "--width", "9.7", "-o", str(tmp_path / "bad")]) == 1
    assert "check the length, in millimetres" in capsys.readouterr().err
    assert not (tmp_path / "bad").exists()
    assert cli.main(["footwear", "--foot", "left", "-o", str(tmp_path / "bad")]) == 1   # nothing to size it by
    assert "length and width" in capsys.readouterr().err
